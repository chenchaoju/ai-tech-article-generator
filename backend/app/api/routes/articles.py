from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal, get_db, get_token_usage_totals
from app.models.article import Article
from app.models.scheduled_publish import ScheduledPublish
from app.schemas.article import (
    ArticleCreate,
    ArticleListResponse,
    ArticleResponse,
    ArticleUpdate,
    DirectorReviewResponse,
    GenerationStartResponse,
    GenerateResponse,
    ScheduledPublishCreate,
    ScheduledPublishResponse,
    TokenUsageStatsResponse,
    WechatPublishResponse,
)
from app.services.glm import director_review_article, edit_and_review_article
from app.services.scheduled_publish import apply_wechat_publish_result
from app.services.wechat import publish_article_to_wechat


router = APIRouter(prefix="/articles", tags=["articles"])


def _get_article_or_404(db: Session, article_id: int) -> Article:
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    return article


def _unpack_generation_result(
    generation_result: tuple,
) -> tuple[str, str, str, list[dict], dict[str, int]]:
    if len(generation_result) == 5:
        content, review_notes, director_summary, director_changes, usage = (
            generation_result
        )
    elif len(generation_result) == 3:
        content, review_notes, usage = generation_result
        director_summary = "文章生成流程已完成。"
        director_changes = []
    else:
        # Keeps locally mocked integrations compatible.
        content, review_notes = generation_result
        director_summary = "文章生成流程已完成。"
        director_changes = []
        usage = {
            "word_count": len(content.replace(" ", "")),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    return content, review_notes, director_summary, director_changes, usage


def _apply_generation_result(article: Article, generation_result: tuple) -> None:
    content, review_notes, director_summary, director_changes, usage = (
        _unpack_generation_result(generation_result)
    )
    article.content = content
    article.status = "generated"
    article.model_name = settings.glm_writer_model
    # 写手和审核官在同一次 GLM 调用内依次完成工作，因此两者共享
    # 本次实际调用的模型；审核官配置仅作为首轮调用的故障回退模型。
    article.reviewer_model_name = settings.glm_writer_model
    article.review_notes = review_notes
    article.director_review_summary = director_summary
    article.director_review_changes = director_changes
    article.director_reviewed_at = datetime.now(timezone.utc)
    article.director_model_name = settings.glm_director_model
    article.generated_word_count = usage["word_count"]
    article.prompt_tokens = usage["prompt_tokens"]
    article.completion_tokens = usage["completion_tokens"]
    article.total_tokens = usage["total_tokens"]
    if article.title == "未命名文章":
        first_line = content.splitlines()[0].lstrip("# ").strip()
        if first_line:
            article.title = first_line[:255]


async def _run_background_generation(article_id: int) -> None:
    with SessionLocal() as db:
        article = db.get(Article, article_id)
        if not article:
            return
        try:
            generation_result = await edit_and_review_article(article)
            _apply_generation_result(article, generation_result)
        except (ValueError, RuntimeError) as exc:
            article.status = "generation_failed"
            article.review_notes = f"后台生成失败：{str(exc)[:900]}"
        except Exception as exc:  # pragma: no cover - final safety net for the job
            article.status = "generation_failed"
            article.review_notes = (
                f"后台生成发生未预期错误：{type(exc).__name__}。"
                "草稿已保留，可以重新生成。"
            )
        db.commit()


@router.post("", response_model=ArticleResponse, status_code=status.HTTP_201_CREATED)
def create_article(payload: ArticleCreate, db: Session = Depends(get_db)) -> Article:
    article_data = payload.model_dump()
    selected_sources = article_data.get("selected_sources") or []
    article_data["selected_sources"] = selected_sources[-1:]
    article = Article(**article_data)
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


@router.get("", response_model=ArticleListResponse)
def list_articles(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=100),
    keyword: str = Query(default="", max_length=100),
    article_status: str = Query(default="", alias="status", max_length=32),
    db: Session = Depends(get_db),
) -> ArticleListResponse:
    conditions = []
    if keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append(or_(Article.title.ilike(pattern), Article.topic.ilike(pattern)))
    if article_status.strip():
        conditions.append(Article.status == article_status.strip())

    query = select(Article)
    count_query = select(func.count(Article.id))
    if conditions:
        query = query.where(*conditions)
        count_query = count_query.where(*conditions)

    total = db.scalar(count_query) or 0
    items = db.scalars(
        query.order_by(Article.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ArticleListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/statistics/tokens", response_model=TokenUsageStatsResponse)
def get_token_usage_statistics(
    db: Session = Depends(get_db),
) -> TokenUsageStatsResponse:
    totals = get_token_usage_totals()
    article_count = db.scalar(select(func.count(Article.id))) or 0
    generated_article_count = (
        db.scalar(
            select(func.count(Article.id)).where(
                Article.status.in_(["generated", "published"])
            )
        )
        or 0
    )
    director_review_count = (
        db.scalar(
            select(func.count(Article.id)).where(
                Article.director_reviewed_at.is_not(None)
            )
        )
        or 0
    )
    recent_articles = db.scalars(
        select(Article)
        .where(Article.total_tokens > 0)
        .order_by(Article.updated_at.desc())
        .limit(20)
    ).all()
    total_tokens = int(totals["total_tokens"] or 0)
    request_count = int(totals["request_count"] or 0)
    return TokenUsageStatsResponse(
        prompt_tokens=int(totals["prompt_tokens"] or 0),
        completion_tokens=int(totals["completion_tokens"] or 0),
        total_tokens=total_tokens,
        request_count=request_count,
        average_tokens_per_request=(
            round(total_tokens / request_count) if request_count else 0
        ),
        article_count=article_count,
        generated_article_count=generated_article_count,
        director_review_count=director_review_count,
        initialized_at=totals["initialized_at"],
        updated_at=totals["updated_at"],
        provider_balance_supported=False,
        configured_token_budget=settings.glm_token_budget,
        estimated_remaining_tokens=(
            max(0, settings.glm_token_budget - total_tokens)
            if settings.glm_token_budget > 0
            else None
        ),
        provider_console_url="https://open.bigmodel.cn/console/overview",
        balance_note=(
            "智谱公开 API 当前未提供账户现金余额或资源包剩余 Token 查询接口。"
            "如手动配置资源包总额度，这里只按本项目已记录用量计算预计剩余；"
            "其他应用消费、现金余额和不同资源包抵扣不会包含在内。"
        ),
        recent_articles=recent_articles,
        scope_note=(
            "首次启用统计时，以数据库中已保存文章的 Token 作为历史基线；"
            "此后累计所有成功的 GLM 对话调用，包括拟题、生成、审核、"
            "编辑总监终审与连接测试。Web Search 未返回 Token 用量时不计入。"
        ),
    )


@router.get("/{article_id}", response_model=ArticleResponse)
def get_article(article_id: int, db: Session = Depends(get_db)) -> Article:
    return _get_article_or_404(db, article_id)


@router.put("/{article_id}", response_model=ArticleResponse)
def update_article(
    article_id: int,
    payload: ArticleUpdate,
    db: Session = Depends(get_db),
) -> Article:
    article = _get_article_or_404(db, article_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "selected_sources":
            value = (value or [])[-1:]
        setattr(article, key, value)
    db.commit()
    db.refresh(article)
    return article


@router.delete(
    "/{article_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_article(article_id: int, db: Session = Depends(get_db)) -> None:
    article = _get_article_or_404(db, article_id)
    if article.status == "generating":
        raise HTTPException(status_code=409, detail="文章正在后台生成，完成后再删除")
    db.delete(article)
    db.commit()


@router.post("/{article_id}/generate", response_model=GenerateResponse)
async def generate_article_content(
    article_id: int,
    db: Session = Depends(get_db),
) -> GenerateResponse:
    article = _get_article_or_404(db, article_id)
    try:
        generation_result = await edit_and_review_article(article)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _apply_generation_result(article, generation_result)
    db.commit()
    db.refresh(article)
    return GenerateResponse(
        article=article,
        message="文章完成",
        review_notes=article.review_notes,
    )


@router.post(
    "/{article_id}/generate-async",
    response_model=GenerationStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_background_generation(
    article_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> GenerationStartResponse:
    article = _get_article_or_404(db, article_id)
    if article.status == "generating":
        return GenerationStartResponse(
            article_id=article.id,
            status="generating",
            message="文章已经在后台生成，无需重复提交。",
        )
    article.status = "generating"
    article.review_notes = ""
    article.director_review_summary = ""
    article.director_review_changes = []
    db.commit()
    background_tasks.add_task(_run_background_generation, article.id)
    return GenerationStartResponse(
        article_id=article.id,
        status="generating",
        message="文章已进入后台生成，可以离开创作台。",
    )


@router.post("/{article_id}/director-review", response_model=DirectorReviewResponse)
async def review_article_by_director(
    article_id: int,
    db: Session = Depends(get_db),
) -> DirectorReviewResponse:
    article = _get_article_or_404(db, article_id)
    try:
        content, summary, changes, usage = await director_review_article(article)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    article.content = content
    article.status = "generated"
    article.director_review_summary = summary
    article.director_review_changes = changes
    article.director_reviewed_at = datetime.now(timezone.utc)
    article.director_model_name = settings.glm_director_model
    article.generated_word_count = usage["word_count"]
    article.prompt_tokens = (article.prompt_tokens or 0) + usage["prompt_tokens"]
    article.completion_tokens = (
        (article.completion_tokens or 0) + usage["completion_tokens"]
    )
    article.total_tokens = (article.total_tokens or 0) + usage["total_tokens"]
    db.commit()
    db.refresh(article)
    return DirectorReviewResponse(
        article=article,
        message="资深编辑总监已完成复审并应用必要修改",
        changes=changes,
    )


@router.post("/{article_id}/wechat-publish", response_model=WechatPublishResponse)
async def publish_article_by_wechat(
    article_id: int,
    db: Session = Depends(get_db),
) -> WechatPublishResponse:
    article = _get_article_or_404(db, article_id)
    try:
        result = await publish_article_to_wechat(article)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    apply_wechat_publish_result(article, result, datetime.now(timezone.utc))
    db.commit()
    db.refresh(article)
    return WechatPublishResponse(
        article=article,
        message="文章已创建微信草稿并提交发布，正在等待微信处理。",
        **result,
    )


@router.get(
    "/{article_id}/publish-schedules",
    response_model=list[ScheduledPublishResponse],
)
def list_article_publish_schedules(
    article_id: int,
    db: Session = Depends(get_db),
) -> list[ScheduledPublish]:
    _get_article_or_404(db, article_id)
    return list(
        db.scalars(
            select(ScheduledPublish)
            .where(ScheduledPublish.article_id == article_id)
            .order_by(ScheduledPublish.created_at.desc())
        ).all()
    )


@router.post(
    "/{article_id}/publish-schedules",
    response_model=ScheduledPublishResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_article_publish_schedule(
    article_id: int,
    payload: ScheduledPublishCreate,
    db: Session = Depends(get_db),
) -> ScheduledPublish:
    article = _get_article_or_404(db, article_id)
    if article.status != "generated" or not (article.content or "").strip():
        raise HTTPException(
            status_code=400,
            detail="只有已完成且正文不为空的文章才能设置定时发布。",
        )

    scheduled_at = payload.scheduled_at
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    else:
        scheduled_at = scheduled_at.astimezone(timezone.utc)
    if scheduled_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="定时发布时间必须晚于当前时间。")

    existing = db.scalar(
        select(ScheduledPublish).where(
            ScheduledPublish.article_id == article_id,
            ScheduledPublish.platform == payload.platform,
            ScheduledPublish.status == "pending",
        )
    )
    if existing:
        existing.scheduled_at = scheduled_at
        existing.last_error = ""
        schedule = existing
    else:
        schedule = ScheduledPublish(
            article_id=article_id,
            platform=payload.platform,
            scheduled_at=scheduled_at,
            status="pending",
        )
        db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.delete(
    "/{article_id}/publish-schedules/{schedule_id}",
    response_model=ScheduledPublishResponse,
)
def cancel_article_publish_schedule(
    article_id: int,
    schedule_id: int,
    db: Session = Depends(get_db),
) -> ScheduledPublish:
    _get_article_or_404(db, article_id)
    schedule = db.get(ScheduledPublish, schedule_id)
    if not schedule or schedule.article_id != article_id:
        raise HTTPException(status_code=404, detail="定时发布任务不存在")
    if schedule.status == "processing":
        raise HTTPException(status_code=409, detail="文章正在发布，当前无法取消。")
    if schedule.status == "published":
        raise HTTPException(status_code=409, detail="文章已经发布，无法取消。")
    schedule.status = "cancelled"
    db.commit()
    db.refresh(schedule)
    return schedule
