import asyncio
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.main import app
from app.models.article import Article
from app.models.image_asset import ImageAsset
from app.models.image_asset_category import ImageAssetCategory
from app.models.scheduled_publish import ScheduledPublish
from app.api.routes.articles import _run_background_generation
from app.api.routes.settings import _normalize_base_url
from app.services.glm import (
    ARTICLE_DISCLAIMER,
    _build_text_change_records,
    _clean_research_text,
    _enrich_search_metadata,
    _extract_json_ld_article,
    _extract_page_publish_date,
    _finalize_search_metadata,
    _finalize_search_results,
    _parse_csdn_results,
    _parse_juejin_results,
    _search_query_variants,
    _sort_search_results,
    _title_match_score,
    director_review_article,
    edit_and_review_article,
    _finalize_article_metadata,
    _parse_director_payload,
    _usable_search_results,
)
from app.services.role_prompts import ROLE_PROMPTS
from app.services.wechat import _markdown_to_wechat_html
from app.services.scheduled_publish import process_scheduled_publish


def test_article_crud_and_generation_guard(monkeypatch) -> None:
    topic = f"集成测试-{uuid4().hex[:8]}"
    created_id: int | None = None
    schedule_id: int | None = None

    try:
        with TestClient(app) as client:
            health = client.get("/api/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"

            settings = client.get("/api/settings")
            assert settings.status_code == 200
            assert "glm_api_key" not in settings.json()
            assert "api_key" not in settings.json()
            assert "wechat_app_secret" not in settings.json()

            profiles = client.get("/api/settings/profiles")
            assert profiles.status_code == 200
            assert profiles.json()["active_profile_id"]
            assert profiles.json()["profiles"]
            assert "api_key" not in profiles.json()["profiles"][0]
            assert profiles.json()["profiles"][0]["api_key_masked"]

            created = client.post(
                "/api/articles",
                json={
                    "title": "接口联调草稿",
                    "topic": topic,
                    "project_background": "真实测试背景",
                    "target_word_count": 1000,
                    "target_platform": "小红书",
                    "problems": "连接池出现等待",
                    "solution_process": "先核对连接释放路径",
                    "code_snippets": "",
                    "reference_materials": "",
                    "content": "# 初始草稿",
                    "status": "draft",
                },
            )
            assert created.status_code == 201
            created_id = created.json()["id"]
            assert created.json()["selected_sources"] == []
            assert created.json()["review_notes"] == ""
            assert created.json()["target_platform"] == "小红书"

            source_switched = client.put(
                f"/api/articles/{created_id}",
                json={
                    "selected_sources": [
                        {"title": "第一篇", "url": "https://example.com/first"},
                        {"title": "第二篇", "url": "https://example.com/second"},
                    ]
                },
            )
            assert source_switched.status_code == 200
            assert source_switched.json()["selected_sources"] == [
                {"title": "第二篇", "url": "https://example.com/second"}
            ]

            detail = client.get(f"/api/articles/{created_id}")
            assert detail.status_code == 200
            assert detail.json()["topic"] == topic

            updated = client.put(
                f"/api/articles/{created_id}",
                json={
                    "content": "# 已在线编辑",
                    "status": "draft",
                    "target_word_count": 5000,
                },
            )
            assert updated.status_code == 200
            assert updated.json()["content"] == "# 已在线编辑"
            assert updated.json()["target_word_count"] == 5000

            short_target = client.put(
                f"/api/articles/{created_id}",
                json={"target_word_count": 120},
            )
            assert short_target.status_code == 422

            minimum_target = client.put(
                f"/api/articles/{created_id}",
                json={"target_word_count": 200},
            )
            assert minimum_target.status_code == 200
            assert minimum_target.json()["target_word_count"] == 200

            publishing = client.put(
                f"/api/articles/{created_id}",
                json={
                    "publish_records": [
                        {
                            "platform": "csdn",
                            "platform_name": "CSDN",
                            "status": "prepared",
                        }
                    ]
                },
            )
            assert publishing.status_code == 200
            assert publishing.json()["publish_records"][0]["platform"] == "csdn"

            image_markdown = (
                "# 已在线编辑\n\n"
                "![持久化配图](https://images.example.com/persistent.jpg)"
            )
            image_saved = client.put(
                f"/api/articles/{created_id}",
                json={
                    "content": image_markdown,
                    "manual_images": [
                        {
                            "title": "持久化配图",
                            "url": "https://images.example.com/persistent.jpg",
                        }
                    ],
                },
            )
            assert image_saved.status_code == 200
            image_reloaded = client.get(f"/api/articles/{created_id}")
            assert image_reloaded.json()["content"] == image_markdown
            assert image_reloaded.json()["manual_images"][0]["url"].endswith(
                "persistent.jpg"
            )

            listing = client.get("/api/articles", params={"keyword": topic})
            assert listing.status_code == 200
            assert listing.json()["total"] == 1

            async def fake_edit_and_review(_article):
                return (
                    "# 已审核文章",
                    "- 删除了无法验证的结论",
                    {
                        "word_count": 800,
                        "prompt_tokens": 1200,
                        "completion_tokens": 900,
                        "total_tokens": 2100,
                    },
                )

            monkeypatch.setattr(
                "app.api.routes.articles.edit_and_review_article",
                fake_edit_and_review,
            )
            generated = client.post(f"/api/articles/{created_id}/generate")
            assert generated.status_code == 200
            assert generated.json()["article"]["content"] == "# 已审核文章"
            assert generated.json()["review_notes"]
            assert generated.json()["article"]["generated_word_count"] == 800
            assert generated.json()["article"]["total_tokens"] == 2100

            async def fake_director_review(_article):
                return (
                    "# 总监复审后的文章",
                    "收紧了无法验证的结论，并改善了段落衔接。",
                    [
                        {
                            "location": "第一段",
                            "before": "一定可以解决",
                            "after": "在当前条件下可以作为排查方向",
                            "reason": "原表述过于绝对，材料不足以支持。",
                        }
                    ],
                    {
                        "word_count": 850,
                        "prompt_tokens": 200,
                        "completion_tokens": 100,
                        "total_tokens": 300,
                    },
                )

            monkeypatch.setattr(
                "app.api.routes.articles.director_review_article",
                fake_director_review,
            )
            director_reviewed = client.post(
                f"/api/articles/{created_id}/director-review"
            )
            assert director_reviewed.status_code == 200
            director_data = director_reviewed.json()
            assert director_data["article"]["content"] == "# 总监复审后的文章"
            assert director_data["article"]["director_review_summary"]
            assert len(director_data["changes"]) == 1
            assert director_data["article"]["total_tokens"] == 2400

            scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)
            scheduled = client.post(
                f"/api/articles/{created_id}/publish-schedules",
                json={
                    "platform": "wechat",
                    "scheduled_at": scheduled_at.isoformat(),
                },
            )
            assert scheduled.status_code == 201
            schedule_id = scheduled.json()["id"]
            assert scheduled.json()["status"] == "pending"

            schedules = client.get(
                f"/api/articles/{created_id}/publish-schedules"
            )
            assert schedules.status_code == 200
            assert any(item["id"] == schedule_id for item in schedules.json())

            cancelled = client.delete(
                f"/api/articles/{created_id}/publish-schedules/{schedule_id}"
            )
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"

            async def fake_wechat_publish(_article):
                return {
                    "draft_media_id": "draft-media-id",
                    "publish_id": "publish-id",
                    "uploaded_image_count": 3,
                    "status": "submitted",
                }

            monkeypatch.setattr(
                "app.api.routes.articles.publish_article_to_wechat",
                fake_wechat_publish,
            )
            wechat_published = client.post(
                f"/api/articles/{created_id}/wechat-publish"
            )
            assert wechat_published.status_code == 200
            wechat_data = wechat_published.json()
            assert wechat_data["status"] == "submitted"
            assert wechat_data["uploaded_image_count"] == 3
            assert wechat_data["article"]["status"] == "published"
            assert any(
                item["platform"] == "wechat"
                for item in wechat_data["article"]["publish_records"]
            )

            token_usage = client.get("/api/articles/statistics/tokens")
            assert token_usage.status_code == 200
            token_data = token_usage.json()
            assert token_data["total_tokens"] >= 0
            assert token_data["request_count"] >= 0
            assert token_data["provider_balance_supported"] is False
            assert "balance_note" in token_data
            assert "scope_note" in token_data

            deleted = client.delete(f"/api/articles/{created_id}")
            assert deleted.status_code == 204
            assert client.get(f"/api/articles/{created_id}").status_code == 404
            created_id = None
            schedule_id = None
    finally:
        if created_id is not None:
            with SessionLocal() as db:
                if schedule_id is not None:
                    db.execute(
                        delete(ScheduledPublish).where(
                            ScheduledPublish.id == schedule_id
                        )
                    )
                db.execute(delete(Article).where(Article.id == created_id))
                db.commit()


def test_research_and_title_routes(monkeypatch) -> None:
    async def fake_search_web(
        query,
        exclude_urls,
        count,
        source_domain,
        source_name,
        title_only,
        broad_search,
        include_images,
        date_range,
        sort_order,
    ):
        assert query == "FastAPI 连接池"
        assert count == 10
        assert source_domain == "toutiao.com"
        assert source_name == "今日头条"
        assert title_only is True
        assert broad_search is False
        assert include_images is False
        assert date_range == "all"
        assert sort_order == "newest"
        return [
            {
                "title": f"来源 {index}",
                "url": f"https://example{index}.com/article",
                "summary": "摘要",
                "source_content": "",
                "source": f"站点 {index}",
                "publish_date": "",
                "word_count": 0,
                "image_url": "https://images.example.com/should-not-return.jpg",
            }
            for index in range(1, 6)
        ]

    async def fake_titles(**_kwargs):
        return [f"标题候选 {index}" for index in range(1, 11)]

    async def fake_source_content(source):
        assert source["url"] == "https://example1.com/article"
        return {
            **source,
            "source_content": "完整正文" * 80,
            "word_count": 320,
        }

    monkeypatch.setattr("app.api.routes.research.search_web", fake_search_web)
    monkeypatch.setattr("app.api.routes.research.suggest_titles", fake_titles)
    monkeypatch.setattr(
        "app.api.routes.research.fetch_source_content",
        fake_source_content,
    )

    with TestClient(app) as client:
        research = client.post(
            "/api/research/search",
            json={
                "query": "FastAPI 连接池",
                "count": 10,
                "source_domain": "toutiao.com",
                "source_name": "今日头条",
            },
        )
        assert research.status_code == 200
        assert len(research.json()["items"]) == 5
        assert research.json()["items"][0]["source_content"] == ""
        assert "image_url" not in research.json()["items"][0]

        content = client.post(
            "/api/research/content",
            json=research.json()["items"][0],
        )
        assert content.status_code == 200
        assert content.json()["word_count"] == 320
        assert len(content.json()["source_content"]) >= 200

        titles = client.post(
            "/api/research/titles",
            json={
                "topic": "FastAPI 连接池",
                "article_type": "故障排查",
                "writing_style": "温暖同行",
                "layout_style": "问题驱动",
            },
        )
        assert titles.status_code == 200
        assert len(titles.json()["titles"]) == 10


def test_research_route_forwards_date_filter_and_sort(monkeypatch) -> None:
    async def fake_search_web(query, **kwargs):
        assert query == "日期筛选"
        assert kwargs["date_range"] == "30d"
        assert kwargs["sort_order"] == "oldest"
        return []

    monkeypatch.setattr("app.api.routes.research.search_web", fake_search_web)
    with TestClient(app) as client:
        response = client.post(
            "/api/research/search",
            json={
                "query": "日期筛选",
                "date_range": "30d",
                "sort_order": "oldest",
            },
        )
    assert response.status_code == 200


def test_finalize_search_results_applies_real_date_order_and_range() -> None:
    today = datetime.now(timezone.utc).date()

    def item(title: str, days_ago: int) -> dict:
        content = title + "正文" * 120
        return {
            "title": title,
            "url": f"https://example.com/{days_ago}",
            "summary": content,
            "source_content": content,
            "source": "测试站点",
            "publish_date": (today - timedelta(days=days_ago)).isoformat(),
            "date_type": "发布日期",
            "word_count": len(content),
        }

    items = [item("较旧文章", 20), item("最新文章", 1), item("过期文章", 80)]
    newest = _finalize_search_results(items, "文章", 10, "30d", "newest")
    oldest = _finalize_search_results(items, "文章", 10, "30d", "oldest")
    assert [entry["title"] for entry in newest] == ["最新文章", "较旧文章"]
    assert [entry["title"] for entry in oldest] == ["较旧文章", "最新文章"]


def test_search_metadata_keeps_candidates_without_body_text() -> None:
    items = [
        {
            "title": "# 香蕉的保存方法",
            "url": "https://example.com/banana",
            "summary": "只有搜索摘要",
            "source_content": "不应在检索阶段返回",
            "source": "测试站点",
            "publish_date": "2026-07-28",
            "date_type": "发布日期",
            "word_count": 0,
        }
    ]
    results = _finalize_search_metadata(items, "香蕉", 10)
    assert len(results) == 1
    assert results[0]["title"] == "香蕉的保存方法"
    assert results[0]["source_content"] == ""
    assert results[0]["word_count"] == 0


def test_search_material_filters_short_pages_and_removes_heading_markers() -> None:
    cleaned = _clean_research_text("# 抓取标题\n\n## 正文\n" + "内容" * 100)
    assert "# 抓取标题" not in cleaned
    assert "抓取标题" in cleaned

    results = _usable_search_results(
        [
            {
                "title": "过短结果",
                "url": "https://example.com/short",
                "source_content": "很短",
                "word_count": 2,
            },
            {
                "title": "完整结果",
                "url": "https://example.com/long",
                "source_content": "# 原文标题\n" + "内容" * 100,
                "word_count": 0,
            },
        ],
        10,
    )
    assert [item["title"] for item in results] == ["完整结果"]
    assert results[0]["word_count"] >= 200
    assert "# 原文标题" not in results[0]["source_content"]


def test_juejin_native_results_use_full_content_and_strict_latin_relevance() -> None:
    payload = {
        "data": [
            {
                "result_type": 2,
                "result_model": {
                    "article_id": "123",
                    "article_info": {
                        "article_id": "123",
                        "title": "Codex 从安装到实战",
                        "brief_content": "简短摘要",
                        "content": "# Codex 从安装到实战\n\n" + "完整正文" * 80,
                        "ctime": 1784004703,
                    },
                },
            },
            {
                "result_type": 2,
                "result_model": {
                    "article_id": "456",
                    "article_info": {
                        "article_id": "456",
                        "title": "AlphaCode 模型学习笔记",
                        "brief_content": "名称里有相似字母，但不是 Codex",
                        "content": "其他正文" * 80,
                        "ctime": 1784004703,
                    },
                },
            },
        ]
    }
    items = _parse_juejin_results(
        payload,
        query="codex",
        source_name="掘金",
        excluded_urls=set(),
    )
    assert [item["title"] for item in items] == ["Codex 从安装到实战"]
    assert items[0]["word_count"] >= 200
    assert not items[0]["source_content"].startswith("#")
    assert _title_match_score(
        "codex",
        {"title": "AlphaCode 模型学习笔记"},
    ) == 0


def test_fuzzy_query_expansion_and_newest_real_date_priority() -> None:
    variants = _search_query_variants("AI应用")
    assert "AI应用" in variants
    assert any("人工智能" in item or "大模型" in item for item in variants)
    assert _title_match_score(
        "AI应用",
        {"title": "DevSecOps 智能化：Gitee 分层 AI 落地实践"},
    ) > 0

    sorted_items = _sort_search_results(
        [
            {
                "title": "检索当天才发现的旧文章",
                "publish_date": "2026-07-28",
                "date_type": "检索日期",
                "word_count": 900,
            },
            {
                "title": "AI 工具的新进展",
                "publish_date": "2026-07-27",
                "date_type": "发布日期",
                "word_count": 500,
            },
            {
                "title": "AI 应用的较早文章",
                "publish_date": "2026-06-01",
                "date_type": "发布日期",
                "word_count": 1000,
            },
        ],
        "AI应用",
    )
    assert [item["title"] for item in sorted_items] == [
        "AI 工具的新进展",
        "AI 应用的较早文章",
        "检索当天才发现的旧文章",
    ]


def test_csdn_native_results_keep_full_body_and_clean_url() -> None:
    payload = {
        "result_vos": [
            {
                "title": "AI <em>应用</em>开发实践",
                "url": "https://blog.csdn.net/demo/article/details/123?utm_source=test",
                "body": "完整正文" * 100,
                "description": "摘要",
                "nickname": "测试作者",
                "created_at": "2026-07-28 10:00:00",
            }
        ]
    }
    items = _parse_csdn_results(
        payload,
        query="AI应用",
        source_name="CSDN",
        excluded_urls=set(),
    )
    assert len(items) == 1
    assert items[0]["title"] == "AI 应用 开发实践"
    assert items[0]["url"] == "https://blog.csdn.net/demo/article/details/123"
    assert items[0]["word_count"] >= 200
    assert items[0]["publish_date"] == "2026-07-28"


def test_json_ld_article_is_a_full_text_fallback() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        """
        <script type="application/ld+json">
        {
          "@type": "Article",
          "datePublished": "2026-07-28T10:00:00+08:00",
          "articleBody": "完整文章正文内容完整文章正文内容完整文章正文内容完整文章正文内容完整文章正文内容完整文章正文内容完整文章正文内容完整文章正文内容完整文章正文内容完整文章正文内容",
          "image": "https://example.com/cover.jpg"
        }
        </script>
        """,
        "html.parser",
    )
    article = _extract_json_ld_article(soup)
    assert article["content"].startswith("完整文章正文")
    assert article["publish_date"] == "2026-07-28"
    assert article["image_url"] == "https://example.com/cover.jpg"


def test_cnblogs_publish_date_uses_page_metadata_not_crawl_date() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        """
        <html><head>
          <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "BlogPosting",
              "headline": "AI 大模型应用",
              "datePublished": "2024-01-04T11:47:00+08:00"
            }
          </script>
        </head><body>
          <span id="post-date">2024-01-04 11:47</span>
        </body></html>
        """,
        "html.parser",
    )
    assert _extract_json_ld_article(soup)["publish_date"] == "2024-01-04"
    assert _extract_page_publish_date(soup, "www.cnblogs.com") == "2024-01-04"


def test_unknown_publish_date_is_not_replaced_with_today() -> None:
    items = asyncio.run(
        _enrich_search_metadata(
            [
                {
                    "title": "无日期文章",
                    "url": "",
                    "summary": "正文" * 120,
                    "source_content": "正文" * 120,
                    "source": "测试站点",
                    "publish_date": "",
                    "date_type": "发布日期",
                    "word_count": 240,
                }
            ],
            include_images=False,
        )
    )
    assert items[0]["publish_date"] == ""
    assert items[0]["date_type"] == "日期未知"


def test_change_record_after_contains_only_changed_fragment() -> None:
    records = _build_text_change_records(
        "今天去公园散步，天气很好。",
        "今天去公园慢慢散步，天气很好。",
        "编辑总监",
        "补充动作细节。",
    )
    assert records
    assert records[0]["after"] == "慢慢"


def test_persistent_image_library(monkeypatch) -> None:
    async def fake_image_search(
        query,
        engine,
        page,
        count,
        exclude_urls,
        prefer_clean,
    ):
        assert query == "牛油果"
        assert engine == "sohu"
        assert page == 2
        assert count == 10
        assert exclude_urls == ["https://images.example.com/old.jpg"]
        assert prefer_clean is True
        return [
            {
                "title": f"清晰牛油果图片 {index}",
                "source_page_url": f"https://example.com/avocado/{index}",
                "source_name": "example.com",
                "image_url": f"https://images.example.com/avocado-{index}.jpg",
            }
            for index in range(1, 11)
        ]

    monkeypatch.setattr(
        "app.api.routes.media.search_image_provider",
        fake_image_search,
    )
    asset_id = None
    category_id = None
    category_name = f"测试分类-{uuid4().hex[:8]}"
    try:
        with TestClient(app) as client:
            searched = client.post(
                "/api/media/search",
                json={
                    "query": "牛油果",
                    "count": 10,
                    "page": 2,
                    "exclude_urls": ["https://images.example.com/old.jpg"],
                    "engine": "sohu",
                    "prefer_clean": True,
                },
            )
            assert searched.status_code == 200
            assert searched.json()["page"] == 2
            assert searched.json()["engine"] == "sohu"
            assert searched.json()["has_more"] is True
            assert len(searched.json()["items"]) == 10
            item = searched.json()["items"][0]

            saved = client.post("/api/media/assets", json=item)
            assert saved.status_code == 201
            asset_id = saved.json()["id"]
            assert saved.json()["category"] == "未分类"

            created_category = client.post(
                "/api/media/categories",
                json={"name": category_name},
            )
            assert created_category.status_code == 201
            category_id = created_category.json()["id"]

            categorized = client.patch(
                f"/api/media/assets/{asset_id}",
                json={"category": category_name},
            )
            assert categorized.status_code == 200
            assert categorized.json()["category"] == category_name

            renamed_name = f"{category_name}-已改名"
            renamed_category = client.patch(
                f"/api/media/categories/{category_id}",
                json={"name": renamed_name},
            )
            assert renamed_category.status_code == 200
            assert renamed_category.json()["name"] == renamed_name

            categories = client.get("/api/media/categories")
            assert categories.status_code == 200
            ordered_category_ids = [
                category["id"] for category in categories.json()
            ]
            reordered_categories = client.post(
                "/api/media/categories/reorder",
                json={"ordered_ids": ordered_category_ids},
            )
            assert reordered_categories.status_code == 200

            reordered = client.post(
                "/api/media/assets/reorder",
                json={"ordered_ids": [asset_id]},
            )
            assert reordered.status_code == 200
            reordered_asset = next(
                asset for asset in reordered.json() if asset["id"] == asset_id
            )
            assert reordered_asset["sort_order"] == 1

            listed = client.get("/api/media/assets")
            assert listed.status_code == 200
            listed_asset = next(
                asset for asset in listed.json() if asset["id"] == asset_id
            )
            assert listed_asset["category"] == renamed_name

            deleted_category = client.delete(
                f"/api/media/categories/{category_id}"
            )
            assert deleted_category.status_code == 204
            category_id = None
            listed_after_category_delete = client.get("/api/media/assets")
            assert all(
                asset["id"] != asset_id
                for asset in listed_after_category_delete.json()
            )
            asset_id = None
    finally:
        if asset_id is not None or category_id is not None:
            with SessionLocal() as db:
                if asset_id is not None:
                    db.execute(
                        delete(ImageAsset).where(ImageAsset.id == asset_id)
                    )
                if category_id is not None:
                    db.execute(
                        delete(ImageAssetCategory).where(
                            ImageAssetCategory.id == category_id
                        )
                    )
                db.commit()


def test_final_article_ignores_source_images_and_uses_disclaimer() -> None:
    sources = [
        {
            "title": "无图来源",
            "url": "https://example.com/no-image",
            "source": "示例站点",
            "image_url": "",
        },
        *[
            {
                "title": f"配图来源 {index}",
                "url": f"https://example.com/{index}",
                "source": "示例站点",
                "image_url": f"https://images.example.com/{index}.jpg",
                "image_urls": [
                    f"https://images.example.com/{index}.jpg",
                    f"https://images.example.com/{index}-detail.jpg",
                ],
            }
            for index in range(1, 4)
        ],
    ]
    draft = """# 测试文章

![模型多放的图片](https://invalid.example/model.jpg)
*图片来源：错误来源*

## 第一部分
正文。

## 第二部分
正文。

## 第三部分
正文。
"""
    article = Article(
        title="测试文章",
        topic="来源图片隔离校验",
        selected_sources=sources,
    )
    final_content = _finalize_article_metadata(article, draft)
    embedded = re.findall(r"!\[[^\]]*]\((https?://[^)]+)\)", final_content)
    assert embedded == []
    assert "invalid.example" not in final_content
    assert final_content.endswith(ARTICLE_DISCLAIMER)
    assert final_content.count(ARTICLE_DISCLAIMER) == 1
    assert "来源：示例站点" not in final_content
    assert "https://example.com/" not in final_content
    assert "发布日期：" in final_content


def test_director_response_accepts_article_without_review_tag() -> None:
    article, summary, changes = _parse_director_payload(
        """<ARTICLE>
# 修订后的标题

这是总监修订后的正文。
</ARTICLE>"""
    )
    assert article.startswith("# 修订后的标题")
    assert summary == "资深编辑总监已完成复审。"
    assert changes == []


def test_final_article_uses_selected_new_title_and_removes_original_title() -> None:
    article = Article(
        title="这是重新选择的新标题",
        topic="标题替换",
        selected_sources=[{"title": "抓取到的原标题"}],
    )
    final_content = _finalize_article_metadata(
        article,
        "# 模型临时标题\n\n抓取到的原标题\n\n正文内容。",
    )
    assert final_content.startswith("> 发布日期：")
    assert "# 这是重新选择的新标题" not in final_content
    assert "模型临时标题" not in final_content
    assert "抓取到的原标题" not in final_content


def test_manual_image_policy_can_disable_all_source_images() -> None:
    article = Article(
        title="手动配图",
        topic="图片素材",
        include_source_images=False,
        selected_sources=[
            {
                "title": "原文",
                "source": "示例站点",
                "image_url": "https://images.example.com/source.jpg",
            }
        ],
        manual_images=[
            {
                "title": "手动选择",
                "url": "https://images.example.com/manual.jpg",
            }
        ],
    )
    final_content = _finalize_article_metadata(article, "# 手动配图\n\n正文。")
    assert "https://images.example.com/source.jpg" not in final_content
    assert "https://images.example.com/manual.jpg" in final_content


def test_glm_base_url_normalization() -> None:
    expected = "https://open.bigmodel.cn/api/paas/v4"
    assert _normalize_base_url(expected) == expected
    assert _normalize_base_url(f"{expected}/chat") == expected
    assert _normalize_base_url(f"{expected}/chat/completions") == expected


def test_wechat_markdown_conversion_removes_duplicate_title() -> None:
    soup = _markdown_to_wechat_html(
        "# 测试标题\n\n正文。\n\n![配图](https://example.com/image.jpg)",
        "测试标题",
    )
    assert soup.find("h1") is None
    assert soup.find("p").get_text(strip=True) == "正文。"
    assert soup.find("img")["src"] == "https://example.com/image.jpg"


def test_four_role_generation_pipeline_records_each_role(monkeypatch) -> None:
    calls: list[str] = []
    api_prompts: list[str] = []
    writer_body = "这是一段严格依据原始材料整理的正文。" * 12
    reviewer_body = writer_body.replace("严格依据", "认真依据", 1)
    director_body = reviewer_body.replace("整理的正文", "改写的正文", 1)

    async def fake_hydrate(_article):
        return None

    async def fake_chat(_model, system_prompt, user_prompt, **kwargs):
        api_prompts.append(user_prompt)
        usage = kwargs.get("usage_collector")
        if usage is not None:
            usage["prompt_tokens"] += 10
            usage["completion_tokens"] += 10
            usage["total_tokens"] += 20
        if "内容研究专家和论点策划顾问" in system_prompt:
            calls.append("专家")
            return (
                "<EXPERT_BRIEF>\n"
                "## 核心论点\n- 只能依据原始材料解释主题\n\n"
                "## 可拓展内容\n- 解释材料中的因果关系\n"
                "</EXPERT_BRIEF>"
            )
        if "一次调用中依次完成“写手”和“审核官”" in system_prompt:
            calls.append("写手+审核官")
            return (
                '<WRITER_REVIEW>{"summary":"重组原文表达",'
                '"changes":[{"location":"开头","before":"原始材料",'
                '"after":"重新组织后的开头","reason":"避免照搬原文"}]}'
                "</WRITER_REVIEW>\n"
                f"<WRITER_ARTICLE>\n# 写手初稿\n\n{writer_body}\n</WRITER_ARTICLE>\n"
                '<REVIEW>{"summary":"收紧了材料未明确支持的表达",'
                '"changes":[{"location":"第一段","before":"严格依据",'
                '"after":"认真依据","reason":"表达更自然"}]}'
                "</REVIEW>\n"
                f"<ARTICLE>\n# 审核稿\n\n{reviewer_body}\n</ARTICLE>"
            )
        if "内容流水线的编辑总监" in system_prompt:
            calls.append("编辑总监")
            return (
                '<DIRECTOR_REVIEW>{"summary":"四角色终审完成",'
                '"changes":[{"location":"开头","before":"旧开头",'
                    '"after":"新开头","reason":"进入主题更自然"}]}'
                    "</DIRECTOR_REVIEW>\n"
                    f"<ARTICLE>\n# 最终稿\n\n{director_body}\n</ARTICLE>"
                )
        raise AssertionError("出现了四角色以外的模型调用")

    monkeypatch.setattr(
        "app.services.glm._hydrate_selected_source_content",
        fake_hydrate,
    )
    monkeypatch.setattr("app.services.glm._chat_with_retry", fake_chat)
    article = Article(
        title="四角色测试",
        topic="四角色工作流",
        article_type="技术",
        writing_style="温暖同行",
        layout_style="跟随原文",
        target_word_count=216,
        target_platform="小红书",
        content="",
        selected_sources=[
            {
                "title": "原始材料",
                "source": "测试来源",
                "source_content": "这是一段可以核验的原始材料。",
            }
        ],
    )

    content, review_notes, summary, changes, usage = asyncio.run(
        edit_and_review_article(article)
    )

    assert calls == ["专家", "写手+审核官", "编辑总监"]
    assert len(api_prompts) == 3
    assert all("【目标发布平台】小红书" in prompt for prompt in api_prompts)
    assert all("不得使用夸张标题" in prompt for prompt in api_prompts)
    assert all("【用户填写的文章类型】技术" in prompt for prompt in api_prompts)
    assert "【用户填写的表达风格】温暖同行" in api_prompts[1]
    assert "【用户填写的表达风格】" not in api_prompts[0]
    assert "【用户填写的表达风格】" not in api_prompts[2]
    assert all(
        "【用户提示词】\n请按照已选文章主题进行修改" in prompt
        for prompt in api_prompts
    )
    assert all("只能依据原始材料解释主题" in prompt for prompt in api_prompts[1:])
    assert content.startswith("> 发布日期：")
    assert "# 四角色测试" not in content
    assert "# 最终稿" not in content
    assert "收紧了" in review_notes
    assert summary == "四角色终审完成"
    assert {item["role"] for item in changes} == {"专家", "写手", "审核官", "编辑总监"}
    assert all(item["before"] and item["after"] for item in changes)
    assert usage["total_tokens"] == 60
    assert 209 <= usage["word_count"] <= 222
    assert set(ROLE_PROMPTS) == {"专家", "写手", "审核官", "编辑总监"}


def test_director_keeps_article_without_fake_identical_record(monkeypatch) -> None:
    content = "# 保留原稿\n\n" + "这是已经完成审核且事实边界清楚的正文。" * 12

    async def fake_hydrate(_article):
        return None

    async def fake_chat(_model, _system_prompt, _user_prompt, **_kwargs):
        return (
            '<DIRECTOR_REVIEW>{"summary":"终审后确认原稿可以保留","changes":[]}'
            "</DIRECTOR_REVIEW>\n"
            f"<ARTICLE>\n{content}\n</ARTICLE>"
        )

    monkeypatch.setattr(
        "app.services.glm._hydrate_selected_source_content",
        fake_hydrate,
    )
    monkeypatch.setattr("app.services.glm._chat_with_retry", fake_chat)
    article = Article(
        title="保留原稿",
        topic="记录总监工作",
        article_type="技术",
        writing_style="自然叙述",
        layout_style="跟随原文",
        target_word_count=216,
        target_platform="微信公众号",
        content=content,
        status="generated",
        selected_sources=[],
    )

    final_content, summary, changes, _ = asyncio.run(
        director_review_article(article)
    )

    assert "这是已经完成审核且事实边界清楚的正文" in final_content
    assert changes == []
    assert "完整保存" in summary


def test_director_independently_expands_when_word_count_is_short(
    monkeypatch,
) -> None:
    calls: list[str] = []
    expanded_body = "补充已有解释" * 34

    async def fake_hydrate(_article):
        return None

    async def fake_chat(_model, system_prompt, _user_prompt, **kwargs):
        usage = kwargs.get("usage_collector")
        if usage is not None:
            usage["prompt_tokens"] += 10
            usage["completion_tokens"] += 10
            usage["total_tokens"] += 20
        if "内容流水线的编辑总监" in system_prompt:
            calls.append("编辑总监")
            return (
                '<DIRECTOR_REVIEW>{"summary":"终审稿仍然偏短",'
                '"changes":[{"location":"正文","before":"审核稿正文",'
                '"after":"总监短稿","reason":"先梳理逻辑"}]}'
                "</DIRECTOR_REVIEW>\n"
                "<ARTICLE>\n# 总监短稿\n\n总监短稿总监短稿\n</ARTICLE>"
            )
        if "不得把工作退回给写手" in system_prompt:
            calls.append("编辑总监补充")
            return f"<ARTICLE>\n# 补充终稿\n\n{expanded_body}\n</ARTICLE>"
        raise AssertionError("出现了预期之外的模型调用")

    monkeypatch.setattr(
        "app.services.glm._hydrate_selected_source_content",
        fake_hydrate,
    )
    monkeypatch.setattr("app.services.glm._chat_with_retry", fake_chat)
    article = Article(
        title="补写测试",
        topic="总监独立补充",
        article_type="技术",
        writing_style="自然叙述",
        layout_style="跟随原文",
        target_word_count=200,
        target_platform="微信公众号",
        content="# 审核稿\n\n审核稿正文" * 8,
        status="generated",
        selected_sources=[],
    )

    final_content, summary, changes, usage = asyncio.run(
        director_review_article(article)
    )

    assert calls == ["编辑总监", "编辑总监补充"]
    assert expanded_body in final_content
    assert "亲自补充细节、描述与总结" in summary
    assert any(change["role"] == "编辑总监" for change in changes)
    assert usage["word_count"] == 204
    assert usage["total_tokens"] == 40


def test_background_generation_finishes_after_request_scope(monkeypatch) -> None:
    article_id: int | None = None

    async def fake_generation(_article):
        return (
            "# 后台终稿\n\n后台生成不依赖创作台页面。",
            "审核完成",
            "总监终审完成",
            [
                {
                    "role": "编辑总监",
                    "location": "全文",
                    "before": "审核稿",
                    "after": "终稿",
                    "reason": "完成最终检查",
                }
            ],
            {
                "word_count": 16,
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            },
        )

    monkeypatch.setattr(
        "app.api.routes.articles.edit_and_review_article",
        fake_generation,
    )
    try:
        with SessionLocal() as db:
            article = Article(
                title="后台生成测试",
                topic="页面切换不中断",
                article_type="技术",
                writing_style="自然",
                layout_style="跟随原文",
                target_word_count=100,
                target_platform="微信公众号",
                content="",
                status="generating",
                selected_sources=[],
            )
            db.add(article)
            db.commit()
            db.refresh(article)
            article_id = article.id

        asyncio.run(_run_background_generation(article_id))

        with SessionLocal() as db:
            completed = db.get(Article, article_id)
            assert completed is not None
            assert completed.status == "generated"
            assert completed.content.startswith("# 后台终稿")
            assert completed.total_tokens == 30
            assert completed.director_review_changes[0]["role"] == "编辑总监"
    finally:
        if article_id is not None:
            with SessionLocal() as db:
                article = db.get(Article, article_id)
                if article:
                    db.delete(article)
                    db.commit()


def test_scheduled_wechat_publish_updates_article_status(monkeypatch) -> None:
    article_id: int | None = None
    schedule_id: int | None = None

    async def fake_wechat_publish(_article):
        return {
            "draft_media_id": "scheduled-draft",
            "publish_id": "scheduled-publish",
            "uploaded_image_count": 1,
            "status": "submitted",
        }

    monkeypatch.setattr(
        "app.services.scheduled_publish.publish_article_to_wechat",
        fake_wechat_publish,
    )
    try:
        with SessionLocal() as db:
            article = Article(
                title="定时发布测试",
                topic=f"定时发布-{uuid4().hex[:8]}",
                content="# 定时发布测试\n\n正文。",
                status="generated",
            )
            db.add(article)
            db.flush()
            schedule = ScheduledPublish(
                article_id=article.id,
                platform="wechat",
                scheduled_at=datetime.now(timezone.utc),
                status="pending",
            )
            db.add(schedule)
            db.commit()
            article_id = article.id
            schedule_id = schedule.id

        asyncio.run(process_scheduled_publish(schedule_id))

        with SessionLocal() as db:
            article = db.get(Article, article_id)
            schedule = db.get(ScheduledPublish, schedule_id)
            assert article.status == "published"
            assert schedule.status == "published"
            assert schedule.published_at is not None
            assert article.publish_records[0]["scheduled_publish"] is True
    finally:
        with SessionLocal() as db:
            if schedule_id is not None:
                db.execute(
                    delete(ScheduledPublish).where(
                        ScheduledPublish.id == schedule_id
                    )
                )
            if article_id is not None:
                db.execute(delete(Article).where(Article.id == article_id))
            db.commit()
