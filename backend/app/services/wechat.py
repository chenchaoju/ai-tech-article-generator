import mimetypes
import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

import httpx
import markdown
from bs4 import BeautifulSoup

from app.core.config import settings
from app.models.article import Article


WECHAT_ERROR_HINTS = {
    40013: "AppID 无效，请检查公众号后台的开发者 ID。",
    40125: "AppSecret 无效，请在公众号后台重置后重新保存。",
    40164: "当前服务器 IP 不在公众号 IP 白名单中，请先加入白名单。",
    45009: "微信接口调用次数已达上限，请稍后重试。",
    48001: "当前公众号没有此接口权限；通常需要已认证的服务号或订阅号。",
}


def _wechat_error(data: dict[str, Any], action: str) -> None:
    code = int(data.get("errcode") or 0)
    if code == 0:
        return
    hint = WECHAT_ERROR_HINTS.get(code) or str(data.get("errmsg") or "未知错误")
    raise RuntimeError(f"{action}失败（微信错误 {code}）：{hint}")


async def get_wechat_access_token(
    app_id: str | None = None,
    app_secret: str | None = None,
) -> str:
    resolved_app_id = (app_id or settings.wechat_app_id).strip()
    resolved_secret = (app_secret or settings.wechat_app_secret).strip()
    if not resolved_app_id or not resolved_secret:
        raise ValueError("请先在模型设置中填写并保存微信公众号 AppID 和 AppSecret。")
    try:
        async with httpx.AsyncClient(
            timeout=30,
            proxy=settings.glm_proxy_url or None,
        ) as client:
            response = await client.post(
                f"{settings.wechat_api_base_url.rstrip('/')}/cgi-bin/stable_token",
                json={
                    "grant_type": "client_credential",
                    "appid": resolved_app_id,
                    "secret": resolved_secret,
                    "force_refresh": False,
                },
            )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"无法连接微信公众平台：{exc}") from exc
    _wechat_error(data, "获取微信访问令牌")
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("微信公众平台未返回 access_token。")
    return token


def _filename_for_image(url: str, content_type: str) -> str:
    filename = PurePosixPath(urlparse(url).path).name or "article-image"
    if "." not in filename:
        extension = mimetypes.guess_extension(content_type.split(";")[0]) or ".jpg"
        filename = f"{filename}{extension}"
    return filename[:160]


async def _download_image(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[str, bytes, str]:
    response = await client.get(url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
    if not content_type.startswith("image/"):
        raise RuntimeError(f"图片地址返回的不是图片：{url[:120]}")
    if not response.content:
        raise RuntimeError(f"图片内容为空：{url[:120]}")
    return _filename_for_image(url, content_type), response.content, content_type


async def _upload_content_image(
    client: httpx.AsyncClient,
    access_token: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> str:
    response = await client.post(
        f"{settings.wechat_api_base_url.rstrip('/')}/cgi-bin/media/uploadimg",
        params={"access_token": access_token},
        files={"media": (filename, content, content_type)},
    )
    response.raise_for_status()
    data = response.json()
    _wechat_error(data, "上传微信正文图片")
    url = str(data.get("url") or "").strip()
    if not url:
        raise RuntimeError("微信公众平台未返回正文图片地址。")
    return url


async def _upload_cover_material(
    client: httpx.AsyncClient,
    access_token: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> str:
    response = await client.post(
        f"{settings.wechat_api_base_url.rstrip('/')}/cgi-bin/material/add_material",
        params={"access_token": access_token, "type": "image"},
        files={"media": (filename, content, content_type)},
    )
    response.raise_for_status()
    data = response.json()
    _wechat_error(data, "上传微信公众号封面")
    media_id = str(data.get("media_id") or "").strip()
    if not media_id:
        raise RuntimeError("微信公众平台未返回封面素材 media_id。")
    return media_id


def _markdown_to_wechat_html(content: str, title: str) -> BeautifulSoup:
    rendered = markdown.markdown(
        content,
        extensions=["extra", "fenced_code", "tables", "sane_lists"],
        output_format="html5",
    )
    soup = BeautifulSoup(rendered, "html.parser")
    first_heading = soup.find("h1")
    if first_heading and first_heading.get_text(" ", strip=True) == title.strip():
        first_heading.decompose()
    for tag in soup.find_all(True):
        tag.attrs.pop("id", None)
        tag.attrs.pop("class", None)
    return soup


async def publish_article_to_wechat(article: Article) -> dict[str, Any]:
    if article.status != "generated" or not (article.content or "").strip():
        raise ValueError("只有已生成且正文不为空的文章才能发布到微信公众号。")

    access_token = await get_wechat_access_token()
    soup = _markdown_to_wechat_html(article.content, article.title)
    image_nodes = list(soup.find_all("img"))
    if not image_nodes:
        raise ValueError(
            "微信公众号图文发布需要封面。请先在创作台加入至少一张图片，再自动发布。"
        )

    uploaded_urls: dict[str, str] = {}
    first_image_binary: tuple[str, bytes, str] | None = None
    try:
        async with httpx.AsyncClient(
            timeout=60,
            proxy=settings.glm_proxy_url or None,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 ArticleStudio/1.0",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        ) as client:
            for image_node in image_nodes:
                original_url = str(image_node.get("src") or "").strip()
                if not original_url.startswith(("http://", "https://")):
                    image_node.decompose()
                    continue
                if original_url not in uploaded_urls:
                    filename, binary, content_type = await _download_image(
                        client,
                        original_url,
                    )
                    if first_image_binary is None:
                        first_image_binary = (filename, binary, content_type)
                    uploaded_urls[original_url] = await _upload_content_image(
                        client,
                        access_token,
                        filename,
                        binary,
                        content_type,
                    )
                image_node["src"] = uploaded_urls[original_url]
                image_node.attrs.pop("referrerpolicy", None)

            if first_image_binary is None:
                raise ValueError("没有找到可用的微信公众号封面图片。")
            thumb_media_id = await _upload_cover_material(
                client,
                access_token,
                *first_image_binary,
            )

            plain_text = re.sub(
                r"\s+",
                " ",
                soup.get_text(" ", strip=True),
            )
            draft_response = await client.post(
                f"{settings.wechat_api_base_url.rstrip('/')}/cgi-bin/draft/add",
                params={"access_token": access_token},
                json={
                    "articles": [
                        {
                            "title": article.title.strip()[:64],
                            "author": settings.wechat_author.strip()[:16],
                            "digest": plain_text[:120],
                            "content": str(soup),
                            "content_source_url": "",
                            "thumb_media_id": thumb_media_id,
                            "need_open_comment": 1,
                            "only_fans_can_comment": 0,
                        }
                    ]
                },
            )
            draft_response.raise_for_status()
            draft_data = draft_response.json()
            _wechat_error(draft_data, "创建微信公众号草稿")
            draft_media_id = str(draft_data.get("media_id") or "").strip()
            if not draft_media_id:
                raise RuntimeError("微信公众平台未返回草稿 media_id。")

            publish_response = await client.post(
                f"{settings.wechat_api_base_url.rstrip('/')}/cgi-bin/freepublish/submit",
                params={"access_token": access_token},
                json={"media_id": draft_media_id},
            )
            publish_response.raise_for_status()
            publish_data = publish_response.json()
            _wechat_error(publish_data, "提交微信公众号发布")
    except ValueError:
        raise
    except httpx.HTTPError as exc:
        raise RuntimeError(f"微信公众号发布网络请求失败：{exc}") from exc

    return {
        "draft_media_id": draft_media_id,
        "publish_id": str(publish_data.get("publish_id") or ""),
        "uploaded_image_count": len(uploaded_urls),
        "status": "submitted",
    }
