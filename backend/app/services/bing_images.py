import html
import json
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings


BING_IMAGES_URL = "https://cn.bing.com/images/async"
WATERMARK_HINTS = ("水印", "logo", "角标", "带字", "文字模板", "海报模板")
WATERMARK_HEAVY_DOMAINS = (
    "699pic.com",
    "58pic.com",
    "tuchong.com",
    "nipic.com",
    "veer.com",
)


def _is_clear_image_url(value: str) -> bool:
    if not value.startswith(("http://", "https://")):
        return False
    lowered = value.lower().split("?", 1)[0]
    if lowered.endswith((".gif", ".svg", ".ico")):
        return False
    host = urlparse(value).netloc.lower()
    return bool(host) and "bing.net" not in host


def _parse_bing_results(
    markup: str,
    *,
    fallback_title: str,
    excluded_urls: set[str],
    prefer_clean: bool,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen_urls = set(excluded_urls)
    soup = BeautifulSoup(markup, "html.parser")
    for node in soup.select("a.iusc[m]"):
        try:
            metadata = json.loads(html.unescape(str(node.get("m") or "")))
        except (json.JSONDecodeError, TypeError):
            continue
        image_url = str(metadata.get("murl") or "").strip()
        if not _is_clear_image_url(image_url) or image_url in seen_urls:
            continue
        seen_urls.add(image_url)
        title = str(
            metadata.get("t")
            or metadata.get("desc")
            or fallback_title
        ).strip()
        source_page_url = str(metadata.get("purl") or "").strip()
        source_host = urlparse(source_page_url).netloc.removeprefix("www.")
        if prefer_clean and (
            any(hint in title.lower() for hint in WATERMARK_HINTS)
            or any(
                source_host == domain or source_host.endswith(f".{domain}")
                for domain in WATERMARK_HEAVY_DOMAINS
            )
        ):
            continue
        items.append(
            {
                "title": title[:255] or fallback_title,
                "image_url": image_url,
                "source_page_url": (
                    source_page_url
                    if source_page_url.startswith(("http://", "https://"))
                    else ""
                ),
                "source_name": source_host or "Bing 图片",
            }
        )
    return items


async def search_bing_images(
    query: str,
    *,
    page: int = 1,
    count: int = 10,
    exclude_urls: list[str] | None = None,
    prefer_clean: bool = True,
) -> list[dict[str, str]]:
    """Search Bing Images and return original large-image URLs."""
    excluded = {
        str(url).strip()
        for url in (exclude_urls or [])
        if str(url).strip().startswith(("http://", "https://"))
    }
    results: list[dict[str, str]] = []
    fetched_markups: list[str] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://cn.bing.com/images/",
    }
    async with httpx.AsyncClient(
        timeout=18,
        proxy=settings.glm_proxy_url or None,
        follow_redirects=True,
        headers=headers,
    ) as client:
        # Bing may repeat a few results between offsets. Fetch another batch
        # when needed and filter against every URL already shown to the user.
        for batch in range(3):
            first = ((page - 1) * 50) + 1 + (batch * 50)
            response = await client.get(
                BING_IMAGES_URL,
                params={
                    "q": query.strip(),
                    "first": first,
                    "count": 50,
                    "qft": "+filterui:imagesize-large",
                    "scenario": "ImageBasicHover",
                    "mmasync": "1",
                    "adlt": "moderate",
                    "setlang": "zh-hans",
                    "cc": "cn",
                },
            )
            response.raise_for_status()
            fetched_markups.append(response.text)
            parsed = _parse_bing_results(
                response.text,
                fallback_title=query.strip(),
                excluded_urls=excluded | {item["image_url"] for item in results},
                prefer_clean=prefer_clean,
            )
            results.extend(parsed)
            if len(results) >= count:
                break
    if prefer_clean and len(results) < count:
        for markup in fetched_markups:
            parsed = _parse_bing_results(
                markup,
                fallback_title=query.strip(),
                excluded_urls=excluded | {item["image_url"] for item in results},
                prefer_clean=False,
            )
            results.extend(parsed)
            if len(results) >= count:
                break
    return results[:count]
