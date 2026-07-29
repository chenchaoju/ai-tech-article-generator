from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.bing_images import search_bing_images


SO_IMAGES_URL = "https://image.so.com/j"
WATERMARK_HINTS = ("水印", "logo", "角标", "带字", "文字模板", "海报模板")
WATERMARK_HEAVY_DOMAINS = (
    "699pic.com",
    "58pic.com",
    "tuchong.com",
    "nipic.com",
    "veer.com",
)


def _matches_domain(host: str, domain: str) -> bool:
    normalized_host = host.lower().removeprefix("www.")
    normalized_domain = domain.lower().removeprefix("www.")
    return normalized_host == normalized_domain or normalized_host.endswith(
        f".{normalized_domain}"
    )


def _looks_clean(title: str, host: str) -> bool:
    lowered_title = title.lower()
    if any(hint in lowered_title for hint in WATERMARK_HINTS):
        return False
    return not any(_matches_domain(host, domain) for domain in WATERMARK_HEAVY_DOMAINS)


async def search_360_images(
    query: str,
    *,
    page: int,
    count: int,
    exclude_urls: list[str] | None,
    source_domain: str = "",
    prefer_clean: bool = True,
) -> list[dict[str, str]]:
    excluded = {
        str(url).strip()
        for url in (exclude_urls or [])
        if str(url).strip().startswith(("http://", "https://"))
    }
    candidates: list[dict[str, str]] = []
    seen_urls = set(excluded)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://image.so.com/",
    }
    async with httpx.AsyncClient(
        timeout=18,
        proxy=settings.glm_proxy_url or None,
        follow_redirects=True,
        headers=headers,
    ) as client:
        for batch in range(3):
            offset = ((page - 1) * 126) + (batch * 126)
            response = await client.get(
                SO_IMAGES_URL,
                params={
                    "q": query.strip(),
                    "src": "srp",
                    "sn": offset,
                    "pn": 126,
                    "z": "9",
                    "hd": "1",
                    "copyright": "0",
                },
            )
            response.raise_for_status()
            payload = response.json()
            for raw in payload.get("list") or []:
                image_url = str(raw.get("img") or "").strip()
                if (
                    not image_url.startswith(("http://", "https://"))
                    or image_url in seen_urls
                ):
                    continue
                title = str(raw.get("title") or query).strip()
                source_page_url = str(raw.get("link") or "").strip()
                host = str(raw.get("site") or "").strip() or urlparse(
                    source_page_url
                ).netloc
                if source_domain and not _matches_domain(host, source_domain):
                    continue
                width = int(str(raw.get("width") or "0") or 0)
                height = int(str(raw.get("height") or "0") or 0)
                if max(width, height) < 640:
                    continue
                if prefer_clean and not _looks_clean(title, host):
                    continue
                seen_urls.add(image_url)
                candidates.append(
                    {
                        "title": title[:255] or query,
                        "image_url": image_url,
                        "source_page_url": (
                            source_page_url
                            if source_page_url.startswith(("http://", "https://"))
                            else ""
                        ),
                        "source_name": host.removeprefix("www.") or "360 图片",
                    }
                )
                if len(candidates) >= count:
                    return candidates
    return candidates[:count]


async def search_images(
    query: str,
    *,
    engine: str,
    page: int,
    count: int,
    exclude_urls: list[str] | None,
    prefer_clean: bool,
) -> list[dict[str, str]]:
    if engine == "bing":
        return await search_bing_images(
            query,
            page=page,
            count=count,
            exclude_urls=exclude_urls,
            prefer_clean=prefer_clean,
        )
    source_domain = {
        "baidu": "baidu.com",
        "sohu": "sohu.com",
    }.get(engine, "")
    return await search_360_images(
        query,
        page=page,
        count=count,
        exclude_urls=exclude_urls,
        source_domain=source_domain,
        prefer_clean=prefer_clean,
    )
