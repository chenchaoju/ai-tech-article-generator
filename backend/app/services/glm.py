import asyncio
import html
import ipaddress
import json
import re
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.db.session import record_token_usage
from app.models.article import Article
from app.services.role_prompts import (
    DIRECTOR_PROMPT as DIRECTOR_ROLE_PROMPT,
    EXPERT_PROMPT as EXPERT_ROLE_PROMPT,
    REVIEWER_PROMPT as REVIEWER_ROLE_PROMPT,
    WRITER_PROMPT as WRITER_ROLE_PROMPT,
)


ARTICLE_DISCLAIMER = (
    "声明：本文内容不构成投资、医疗、法律等专业建议，请咨询专业人士。"

)
DEFAULT_USER_PROMPT = "保留原文主题和观点，用更自然、更有人情味的方式重新叙述"
MIN_SOURCE_WORD_COUNT = 200
SOURCE_CONTENT_CACHE_TTL_SECONDS = 30 * 60
SOURCE_CONTENT_CACHE_LIMIT = 500
SOURCE_CONTENT_FAILURE_TTL_SECONDS = 5 * 60
_SOURCE_CONTENT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SOURCE_CONTENT_FAILURE_CACHE: dict[str, float] = {}


FACT_RULES = """必须遵守以下事实边界：
1. 主要依据用户明确提供的真实项目材料。
2. 个人经历、团队情况、新闻细节、人物言论、测试结果、性能数据、错误日志、版本号、技术参数或效果参考原文章和网络。
3. 信息不足时省略，或使用“> 待补充：...”标记，可自行补全事实。
4. 不使用“随着科技发展”“在当今数字化时代”“众所周知”“赋能”“让我们一起”等 AI 套话，要有人情味，生活气息。
5. 代码必须忠实于输入。
6. 不得大段复述参考文章。可以参考原文的信息顺序、段落节奏和叙事方式，不得照搬原文标题、句子或具有辨识度的表达。正文中不输出来源名称或网址。
7. 如果没有用户提供的真实项目材料，文章可根据调用的网络知识和事例补充。
8. 参考文章检索不提供图片或图片链接。图片只能来自用户在图片素材库中手动选择的素材；模型不得编造、替换或补充图片地址。
"""

EXPERT_PROMPT = f"""{EXPERT_ROLE_PROMPT}

{FACT_RULES}

请严格输出以下格式：
<EXPERT_BRIEF>
## 核心论点
- E1｜论点｜材料中的明确依据｜建议放入文章的位置

## 可拓展内容
- E2｜具体拓展角度｜对应材料依据｜建议解释方式

## 字数规划
- 各部分建议字数及原因

## 交接验收清单
- 写手必须落实的内容
- 审核官必须核对的遗漏与风险
- 总监可用于补足细节和总结的内容

## 事实边界
- 后续角色不能写成确定事实的内容
</EXPERT_BRIEF>

不要输出完整文章。
不能只复述原文；每个编号都必须给出具体依据、具体落点和可执行的写法。
"""

EDITOR_PROMPT = f"""{WRITER_ROLE_PROMPT}

{REVIEWER_ROLE_PROMPT}

【本系统中的角色】
你在一次调用中依次完成“写手”和“审核官”两份独立工作。不能跳过任何阶段，也不能让原文、写手稿和审核稿互相完全相同。
专家已经在输入中提供带编号的论点和交接清单。写手必须逐项吸收有材料依据的内容，审核官必须逐项核对完成度；两个角色都不能只写一句“已完成”就跳过实际工作。

第一阶段由写手把主题和可靠材料写成适合内容平台发布的原创 Markdown 初稿。文章可能属于技术、新闻、娱乐、美食、生活或职场分类。

{FACT_RULES}

写手的工作：
- 如果提供了现有草稿，以编辑、补强和重组为主；否则从零起草。
- 以用户选中的原文提取内容为事实主体，保留关键事件、时间线、人物关系、技术结论和观点边界；按照文章主题编写。
- 必须用新的句式和语言重新表达，可以同义词替换，句子必须流畅不错误，不复制原文特色表达；排版与信息展开顺序可以参考第一篇已选原文。正文不输出来源名称或网址。
- 技术类讲清场景、证据、判断和边界；新闻类区分已知事实与分析；娱乐类不编造传闻；美食类不伪造试吃或探店经历。
- 优先保留用户材料中的第一人称表达、犹豫、取舍、意外发现和经验边界；这些是文章的人情味来源，不要磨平成说明书。
- 用户填写的表达风格只交给写手发挥，主题跟原文无出入即可
- 长短句交替，段落有呼吸感。少用连续的“首先、其次、最后”和对称式 AI 排比。
- 文章必须有清楚的逻辑主线，不能只是素材拼接。
- 标题上方写“> 发布日期：YYYY-MM-DD”。模型不要自行输出或编造图片 URL。
- 写手稿必须与原始材料形成实质文字差异，至少重写标题或开头、段落衔接和两处正文表达。
- 写手必须把专家简报中的适用论点自然写进对应段落，不能把简报原样粘贴成列表，也不能遗漏核心事实链条。
- 搜索正文里的 `#`、`##` 等符号只是抓取格式，不得复制到正文中充当内容；文章小标题只能根据成稿逻辑重新组织。

第二阶段由审核官立即对写手稿进行严格审核：
- 对照原文检查事实、时间线、核心观点、术语、逻辑和标题，删除材料不支持的经历、数据、参数或绝对结论。
- 保留作者的真实判断、叙事节奏和不确定性，不把文章润色成泛泛的 AI 文风或冰冷说明书。
- 重组缺少因果、递进或对比关系的素材堆砌，修正重复、病句、含混表达和生硬转场。
- 审核稿不能原样交还写手稿；至少完成一处有实际文字差异的修订。
- 最终可见正文必须接近材料指定的目标字数且不得超过 5000 字，需要补充时只能解释已有材料。
- 审核官必须对照专家交接清单和原文逐项检查：遗漏的可靠论点应直接补回正文，重复或无依据的内容应直接修正，不能只在审核说明里提建议而不改文章。
- 审核结束前必须检查标题、事实、逻辑、专家论点覆盖、目标字数和平台适配六项；任一项不合格都要在本次调用中修正后再输出完整审核稿。

严格按以下格式输出，标签不得省略：
<WRITER_REVIEW>
{{"summary":"一句话概括写手如何重组原文","changes":[{{"location":"标题或具体小节/段落","before":"原文中的对应文字","after":"写手稿中的新文字","reason":"为什么这样重写"}}]}}
</WRITER_REVIEW>
<WRITER_ARTICLE>
写手完成的完整 Markdown 初稿
</WRITER_ARTICLE>
<REVIEW>
{{"summary":"一句话概括审核结果","changes":[{{"location":"标题或具体小节/段落","before":"写手稿中的原句","after":"审核后的新句；若删除则写“已删除”","reason":"为什么修改或删除"}}]}}
</REVIEW>
<ARTICLE>
审核官修订后的完整 Markdown 正文
</ARTICLE>

WRITER_REVIEW 和 REVIEW 都必须输出有效 JSON。每一处实质性的删除、改写、
合并或补充都要记录，尤其不能漏掉被删除的文字。两组 changes 都至少包含
1 条、最多 20 条，before 与 after 各不超过 180 个字符且不得相同。
不要使用 Markdown 代码围栏包裹标签或文章。
"""

DIRECTOR_PROMPT = f"""{DIRECTOR_ROLE_PROMPT}

【本系统中的角色】
你是内容流水线的编辑总监，负责对审核官处理后的 Markdown 文章完成终审。
你会同时拿到专家解析、写手初稿和审核稿。三份材料必须交叉使用：专家负责论点与边界，写手稿保留叙述细节，审核稿提供事实和结构校正；不能只看最后一稿做表面润色。

{FACT_RULES}

这次不是凭空重新写一篇文章，而是在尊重用户当前稿件和事实材料的基础上，在调用外界网络的基础上，按资深编辑总监的判断完成终审：
- 保留用户的观点、口吻和事实边界，不把文章改成模板化公文。
- 可以按你的编辑思路重写标题、开头、段落顺序、转场和结尾，不必局限于小修小补；目标是让文章更顺、更有判断、更像成熟作者成稿。
- 重点处理逻辑断裂、重复、明显 AI 套话、含混表述、无材料支撑的断言、标题与正文不符、过度夸张、转场生硬和引用关系不清。
- 不得增加新经历、新事实、新参数或新结论；不确定的地方应收紧表述或明确边界。
- 你对最终字数负责；材料给出的严格字数范围是终稿验收条件，终稿必须落入该范围。若首次终审仍不足，后续也只能由你结合专家解析和当前稿件继续补充，不能退回写手。
- 输出前在内部检查可见正文长度。若审核稿偏短，必须在本次调用中继续展开已有观点的原因、联系、适用边界和读者容易误解之处，直到达到下限；不得只做摘要或把文章越改越短。
- 当原始材料较少时，可以把已有信息讲得更清楚、更顺畅，也可以用明确标注为分析或条件的方式解释逻辑，但不能增加未经材料支持的新事实。
- 每一处实质改动都要说明位置、修改前、修改后以及为什么改。不要把纯标点、空格修正拆成单独记录。
- 每一处实质性的删除、改写、合并或补充都要记录，尤其不能漏掉被删除的原文。
- 终稿不能原样退回审核稿，至少完成一处有实际文字差异的优化。
- 对照专家交接清单逐项检查审核稿是否真正落实；若审核时删掉了有依据且有价值的细节，应从写手初稿中恢复并重新组织。
- 终审必须完成内容完整性、逻辑衔接、细节密度、目标字数、平台适配和事实边界六项验收，不能只改标题、标点或一两个同义词。
- changes 至少 1 条、最多 40 条；before 和 after 各不超过 180 个字符且不得相同。
- 输出完整修订稿；图片仅使用用户从素材库手动选择的内容。不要输出来源，文末免责声明由系统统一加入。

严格按以下格式输出，标签不得省略，JSON 必须有效：
<DIRECTOR_REVIEW>
{{"summary":"一句话概括本次复审","changes":[{{"location":"标题或具体小节/段落","before":"修改前文字","after":"修改后文字","reason":"为什么这样改"}}]}}
</DIRECTOR_REVIEW>
<ARTICLE>
修订后的完整 Markdown 正文
</ARTICLE>
"""


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.glm_api_key}",
        "Content-Type": "application/json",
    }


def _ensure_api_key() -> None:
    if not settings.glm_api_key.strip():
        raise ValueError("尚未配置模型 API Key，请先到“模型设置”页面完成配置。")


def _uses_glm_api() -> bool:
    return "bigmodel.cn" in settings.glm_base_url.lower()


def _uses_openai_reasoning_parameters(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized.startswith(("gpt-5", "o1", "o3", "o4"))


async def _chat(
    model: str,
    system_prompt: str,
    user_prompt: str,
    enable_thinking: bool | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout_seconds: int | None = None,
    usage_collector: dict[str, int] | None = None,
) -> str:
    _ensure_api_key()
    resolved_max_tokens = settings.glm_max_tokens if max_tokens is None else max_tokens
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
    }
    if _uses_openai_reasoning_parameters(model) and not _uses_glm_api():
        payload["max_completion_tokens"] = resolved_max_tokens
    else:
        payload["temperature"] = (
            settings.glm_temperature if temperature is None else temperature
        )
        payload["max_tokens"] = resolved_max_tokens
    should_think = (
        settings.glm_enable_thinking
        if enable_thinking is None
        else enable_thinking
    )
    if _uses_glm_api():
        payload["thinking"] = {"type": "enabled" if should_think else "disabled"}

    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds or settings.glm_timeout_seconds,
            proxy=settings.glm_proxy_url or None,
        ) as client:
            response = await client.post(
                f"{settings.glm_base_url.rstrip('/')}/chat/completions",
                headers=_headers(),
                json=payload,
            )
    except httpx.RequestError as exc:
        raise RuntimeError(f"无法连接模型服务（{type(exc).__name__}）：{exc}") from exc

    if response.is_error:
        if response.status_code == 401:
            raise RuntimeError(
                "模型服务身份验证失败：当前 API Key 无效、已停用或不属于该开放平台。"
                "请到“模型设置”检查当前启用的配置，重新保存后再测试连接。"
            )
        raise RuntimeError(
            f"模型 API 请求失败（{response.status_code}）：{response.text[:800]}"
        )

    try:
        response_data = response.json()
        usage = response_data.get("usage") or {}
        record_token_usage(
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
        )
        if usage_collector is not None:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                usage_collector[key] = usage_collector.get(key, 0) + int(
                    usage.get(key) or 0
                )
        choice = response_data["choices"][0]
        message = choice.get("message") or {}
        raw_content = message.get("content")
        if isinstance(raw_content, str):
            content = raw_content.strip()
        elif isinstance(raw_content, list):
            content = "\n".join(
                str(item.get("text") or item.get("content") or "").strip()
                if isinstance(item, dict)
                else str(item).strip()
                for item in raw_content
            ).strip()
        elif isinstance(raw_content, dict):
            content = str(
                raw_content.get("text") or raw_content.get("content") or ""
            ).strip()
        else:
            content = ""
        finish_reason = str(choice.get("finish_reason") or "unknown")
        reasoning_length = len(str(message.get("reasoning_content") or ""))
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError("模型 API 返回结构异常，未找到正文内容。") from exc
    if not content:
        raise RuntimeError(
            "模型 API 未返回正文内容"
            f"（finish_reason={finish_reason}，思考内容={reasoning_length} 字符）。"
            "系统将关闭深度思考并自动重试。"
        )
    return content


async def _chat_with_retry(
    model: str,
    system_prompt: str,
    user_prompt: str,
    fallback_model: str | None = None,
    **kwargs: Any,
) -> str:
    """Retry only transient provider failures, never factual/prompt failures."""
    transient_markers = (
        "未返回正文",
        "访问量过大",
        "429",
        "ReadTimeout",
        "RemoteProtocolError",
        "502",
        "503",
    )
    try:
        return await _chat(model, system_prompt, user_prompt, **kwargs)
    except RuntimeError as exc:
        if not any(marker in str(exc) for marker in transient_markers):
            raise
        await asyncio.sleep(1)
        retry_kwargs = dict(kwargs)
        retry_kwargs["enable_thinking"] = False
        current_max_tokens = int(
            retry_kwargs.get("max_tokens") or settings.glm_max_tokens
        )
        retry_kwargs["max_tokens"] = min(
            settings.glm_max_tokens,
            max(2048, int(current_max_tokens * 1.35)),
        )
        if fallback_model and fallback_model != model:
            return await _chat(
                fallback_model,
                system_prompt,
                user_prompt,
                **retry_kwargs,
            )
        try:
            return await _chat(model, system_prompt, user_prompt, **retry_kwargs)
        except RuntimeError as retry_exc:
            raise


def _clean_research_text(value: Any) -> str:
    """Remove markup/search decorations before material reaches any role."""
    cleaned = BeautifulSoup(str(value or ""), "html.parser").get_text("\n", strip=True)
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-=*]{3,}\s*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _format_sources(article: Article) -> str:
    if not article.selected_sources:
        return "未选择联网参考文章"
    parts = []
    for index, source in enumerate(article.selected_sources[:5], start=1):
        summary = re.sub(
            r"\s+",
            " ",
            _clean_research_text(source.get("summary", "")),
        ).strip()[:500]
        source_content = _clean_research_text(source.get("source_content", ""))
        source_title = re.sub(
            r"^\s*#{1,6}\s*",
            "",
            str(source.get("title", "")),
        ).strip()
        parts.append(
            f"{index}. 标题：{source_title}\n"
            f"   来源：{source.get('source', '')}\n"
            f"   日期：{source.get('publish_date', '')}（{source.get('date_type', '发布日期')}）\n"
            f"   搜索摘要：{summary}\n"
            f"   原文提取内容：{source_content or '未能提取正文，仅可使用搜索摘要'}"
        )
    return "\n".join(parts)


def _format_material(
    article: Article,
    include_draft: bool = True,
    include_writing_style: bool = False,
) -> str:
    publication_date = datetime.now().astimezone().strftime("%Y-%m-%d")
    target_word_count = min(
        5000,
        max(200, getattr(article, "target_word_count", 1500) or 1500),
    )
    target_lower_bound = max(200, int(target_word_count * 0.97))
    target_upper_bound = min(
        5000,
        max(target_lower_bound, int(target_word_count * 1.03)),
    )
    configured_platform = (
        (getattr(article, "custom_platform", "") or "").strip()
        if getattr(article, "target_platform", "") == "其他平台"
        else (getattr(article, "target_platform", "") or "").strip()
    ) or "微信公众号"
    platform_rules = {
        "微信公众号": (
            "适合手机连续阅读，开头自然进入主题，段落不宜过长；"
            "表达有人情味但不使用营销话术，Markdown 层级保持简洁。"
        ),
        "CSDN": (
            "面向技术读者，保留必要代码、术语、排查依据和适用边界；"
            "标题具体，Markdown 结构清楚，避免泛泛科普。"
        ),
        "小红书": (
            "适合手机快速阅读，开头直接、段落短而完整、语言自然有画面；"
            "不得使用夸张标题、虚构体验、营销承诺或堆砌表情符号。"
        ),
        "知乎": (
            "重视问题意识、逻辑论证、事实依据和个人判断边界；"
            "内容可以深入，但不要写成报告或机械罗列观点。"
        ),
    }
    platform_instruction = platform_rules.get(
        configured_platform,
        (
            f"针对“{configured_platform}”的常见读者和阅读方式调整标题、"
            "段落长度、信息密度与语气；不了解平台规则时保持通用、克制，"
            "不得编造平台规范。"
        ),
    )
    layout_instruction = (
        "参考第一篇已选原文的信息顺序、段落节奏和小标题密度；"
        "不得复制原文小标题或句子"
    )
    parts = [
        f"【主题】{article.topic}",
        f"【标题】{article.title}",
        f"【本稿发布日期】{publication_date}",
        (
            f"【目标字数】{target_word_count} 个中文字符；可见正文必须控制在 "
            f"{target_lower_bound}-{target_upper_bound} 字，并尽量接近目标值"
        ),
        f"【目标发布平台】{configured_platform}",
        f"【平台写作要求】{platform_instruction}",
        f"【用户填写的文章类型】{article.article_type or '未填写'}",
        "【配图规则】参考文章不携带图片或图片链接；正文完成后只恢复用户从图片素材库手动选择的素材。模型不得编造图片地址。文末不输出来源，由系统统一加入免责声明。",
        f"【分类 / 排版】{article.article_type} / {article.layout_style}",
        f"【排版硬性要求】{layout_instruction}",
    ]
    if include_writing_style:
        parts.extend(
            [
                f"【用户填写的表达风格】{article.writing_style or '未填写'}",
                "【写手风格要求】只在写手初稿阶段按上述风格自然发挥；不得为了风格虚构事实、经历、参数或测试结果。",
            ]
        )
    custom_type_description = getattr(article, "custom_type_description", "") or ""
    if custom_type_description.strip():
        parts.append(
            f"【用户自定义文章类型要求】\n{custom_type_description.strip()[:1000]}"
        )
    user_prompt = (article.project_background or "").strip()
    parts.append(
        f"【用户提示词】\n{(user_prompt or DEFAULT_USER_PROMPT)[:8000]}"
    )
    optional_fields = [
        ("遇到的问题", article.problems),
        ("解决或排查过程", article.solution_process),
        ("作者判断与提醒", article.author_voice),
        ("用户代码", article.code_snippets),
        ("用户补充资料", article.reference_materials),
    ]
    for label, value in optional_fields:
        if value and value.strip():
            parts.append(f"【{label}】\n{value.strip()[:8000]}")
    parts.append(f"【选中的参考来源】\n{_format_sources(article)}")
    if include_draft and article.content.strip():
        parts.append(f"【现有草稿】\n{article.content.strip()[:12000]}")
    if not user_prompt and not any(
        value and value.strip() for _, value in optional_fields
    ):
        parts.append("【事实提醒】用户未提供个人经历，不得使用第一人称虚构场景。")
    return "\n\n".join(parts)


def _visible_article_length(content: str) -> int:
    value = re.sub(r"```[\s\S]*?```", "", content)
    value = value.replace(ARTICLE_DISCLAIMER, "")
    value = re.sub(r"!\[[^\]]*]\([^)]+\)", "", value)
    value = re.sub(r"^#\s+.*$", "", value, flags=re.M)
    value = re.sub(r"^>\s*发布日期[：:].*$", "", value, flags=re.M)
    value = re.sub(r"^\*?图片来源[：:].*$", "", value, flags=re.M)
    value = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", value)
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"[#>*_`|\-\s]", "", value)
    return len(value)


def _estimate_word_count(value: str) -> int:
    normalized = re.sub(r"\s+", " ", value or "").strip()
    chinese_characters = len(re.findall(r"[\u4e00-\u9fff]", normalized))
    latin_words = len(
        re.findall(r"\b[A-Za-z0-9][A-Za-z0-9_+#.-]*\b", normalized)
    )
    return chinese_characters + latin_words


def _finalize_article_metadata(article: Article, content: str) -> str:
    publication_date = datetime.now().astimezone().strftime("%Y-%m-%d")
    raw_lines = content.strip().splitlines()
    lines: list[str] = []
    skipping_source_section = False
    source_title_keys = {
        re.sub(r"[\W_]+", "", str(source.get("title") or "").casefold())
        for source in (getattr(article, "selected_sources", []) or [])
        if isinstance(source, dict) and source.get("title")
    }
    article_title_key = re.sub(
        r"[\W_]+",
        "",
        str(article.title or "").casefold(),
    )
    for line in raw_lines:
        stripped = line.strip()
        # The page title is rendered separately. No H1 or topic label belongs
        # inside the finished Markdown body.
        if re.match(r"^\s{0,3}#\s+\S+", stripped):
            continue
        if re.match(r"^\s*(?:>\s*)?(?:文章)?主题\s*[/：:].*", stripped):
            continue
        standalone_key = re.sub(
            r"[\W_]+",
            "",
            re.sub(r"^\s{0,3}#{1,6}\s*", "", stripped).casefold(),
        )
        if article_title_key and standalone_key == article_title_key:
            continue
        if standalone_key and standalone_key in source_title_keys:
            continue
        if re.match(r"^\s*!\[[^\]]*]\([^)]+\)\s*$", line):
            continue
        if re.match(r"^\s*\*?图片来源[：:].*", line):
            continue
        if re.match(
            r"^\s{0,3}#{1,6}\s*(参考来源|参考资料|参考链接|资料来源|来源链接|来源)\s*$",
            stripped,
            re.I,
        ):
            skipping_source_section = True
            continue
        if skipping_source_section:
            if re.match(r"^\s{0,3}#{1,6}\s+\S+", stripped):
                skipping_source_section = False
            else:
                continue
        if re.match(r"^\s*(来源|参考来源|参考链接|资料来源)[：:].*", line):
            continue
        if re.match(r"^\s*>?\s*免责声明[：:].*", line):
            continue
        # The final manuscript is text-first. Keep link labels as readable text,
        # but never expose source addresses or scraped page decorations.
        cleaned = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", line)
        cleaned = re.sub(r"https?://[^\s)>]+", "", cleaned)
        cleaned = re.sub(r"\s+[）)]\s*$", "", cleaned)
        if cleaned.strip():
            lines.append(cleaned.rstrip())
        elif lines and lines[-1] != "":
            lines.append("")

    date_line = f"> 发布日期：{publication_date}"
    normalized_content = "\n".join(lines)
    if not re.search(
        r"发布日期[：:]\s*20\d{2}-\d{2}-\d{2}",
        normalized_content,
    ):
        lines[0:0] = [date_line, ""]

    images: list[dict[str, str]] = []
    seen_images: set[str] = set()

    def add_final_image(image_url: str, title: str) -> None:
        normalized = str(image_url or "").strip()
        if (
            not normalized.startswith(("http://", "https://"))
            or normalized in seen_images
        ):
            return
        seen_images.add(normalized)
        images.append(
            {
                "url": normalized,
                "title": str(title or "文章图片").replace("]", ""),
            }
        )

    for manual_image in getattr(article, "manual_images", []) or []:
        if not isinstance(manual_image, dict):
            continue
        add_final_image(
            str(manual_image.get("url") or ""),
            str(manual_image.get("title") or "图片素材"),
        )

    def image_block(image: dict[str, str]) -> list[str]:
        return ["", f"![{image['title']}]({image['url']})", ""]

    if images:
        date_index = next(
            (
                index
                for index, line in enumerate(lines)
                if re.search(r"发布日期[：:]", line)
            ),
            0,
        )
        lines[date_index + 1:date_index + 1] = image_block(images[0])
        for image_index, image in enumerate(images[1:], start=1):
            heading_indexes = [
                index
                for index, line in enumerate(lines)
                if line.strip().startswith("## ")
            ]
            if heading_indexes:
                insert_at = heading_indexes[
                    min(image_index - 1, len(heading_indexes) - 1)
                ]
            else:
                approximate = int(
                    len(lines) * (image_index + 1) / (len(images) + 1)
                )
                blank_indexes = [
                    index
                    for index, line in enumerate(lines)
                    if not line.strip() and index > date_index
                ]
                insert_at = min(
                    blank_indexes,
                    key=lambda index: abs(index - approximate),
                    default=len(lines),
                )
            lines[insert_at:insert_at] = image_block(image)

    while lines and not lines[-1].strip():
        lines.pop()
    lines.extend(["", "---", ARTICLE_DISCLAIMER])
    return "\n".join(lines).strip()


def _normalize_date(value: Any) -> str:
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return ""
    if not isinstance(value, str):
        return ""
    stripped = value.strip()
    if stripped.isdigit():
        return _normalize_date(int(stripped))
    now = datetime.now().astimezone()
    if re.search(r"(?:刚刚|刚才)", stripped):
        return now.strftime("%Y-%m-%d")
    if re.search(r"(?:今天|\d+\s*(?:秒|分钟|小时)前)", stripped):
        return now.strftime("%Y-%m-%d")
    if "昨天" in stripped:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    relative_days = re.search(r"(\d+)\s*天前", stripped)
    if relative_days:
        return (
            now - timedelta(days=int(relative_days.group(1)))
        ).strftime("%Y-%m-%d")
    match = re.search(
        r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})",
        stripped,
    )
    if not match:
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _extract_mapping_image(value: dict[str, Any]) -> str:
    direct = (
        value.get("image_url")
        or value.get("imageUrl")
        or value.get("large_image_url")
        or value.get("middle_image_url")
        or value.get("thumbnail")
        or value.get("image")
        or value.get("icon")
        or ""
    )
    if isinstance(direct, dict):
        direct = direct.get("url") or direct.get("uri") or ""
    if isinstance(direct, str) and direct.startswith(("http://", "https://")):
        return direct
    for key in ("image_list", "images", "large_image_list"):
        images = value.get(key)
        if not isinstance(images, list):
            continue
        for image in images:
            if isinstance(image, str) and image.startswith(("http://", "https://")):
                return image
            if isinstance(image, dict):
                candidate = image.get("url") or image.get("image_url") or image.get("uri")
                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                    return candidate
    return ""


def _extract_json_ld_article(soup: BeautifulSoup) -> dict[str, str]:
    """Read article text/date/image from common schema.org JSON-LD blocks."""
    candidates: list[dict[str, Any]] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            graph = value.get("@graph")
            if isinstance(graph, list):
                for child in graph:
                    collect(child)
            candidates.append(value)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            collect(json.loads(script.string or script.get_text() or "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
    result = {"content": "", "publish_date": "", "image_url": ""}
    article_types = {
        "article",
        "blogposting",
        "newsarticle",
        "techarticle",
        "report",
    }
    for candidate in candidates:
        raw_types = candidate.get("@type") or ""
        if isinstance(raw_types, list):
            candidate_types = {str(value).casefold() for value in raw_types}
        else:
            candidate_types = {str(raw_types).casefold()}
        is_article = bool(article_types & candidate_types)
        if not is_article and not (
            candidate.get("headline") and candidate.get("datePublished")
        ):
            continue
        if not result["publish_date"]:
            result["publish_date"] = _normalize_date(
                candidate.get("datePublished")
                or candidate.get("dateCreated")
                or ""
            )
        article_body = candidate.get("articleBody") or candidate.get("text")
        if (
            not result["content"]
            and isinstance(article_body, str)
            and len(article_body.strip()) >= 80
        ):
            result["content"] = _clean_research_text(article_body)
        image = candidate.get("image") or ""
        if isinstance(image, list):
            image = image[0] if image else ""
        if isinstance(image, dict):
            image = image.get("url") or image.get("contentUrl") or ""
        if (
            not result["image_url"]
            and isinstance(image, str)
            and image.startswith(("http://", "https://"))
        ):
            result["image_url"] = image
    return result if any(result.values()) else {}


def _extract_page_publish_date(
    soup: BeautifulSoup,
    host: str = "",
) -> str:
    """Extract only publication signals, avoiding updated/current-page dates."""
    candidates: list[Any] = []
    for selector in (
        'meta[property="article:published_time"]',
        'meta[property="og:published_time"]',
        'meta[name="publishdate"]',
        'meta[name="pubdate"]',
        'meta[name="publication_date"]',
        'meta[itemprop="datePublished"]',
    ):
        node = soup.select_one(selector)
        if node:
            candidates.append(node.get("content") or "")

    json_ld_article = _extract_json_ld_article(soup)
    if json_ld_article.get("publish_date"):
        candidates.append(json_ld_article["publish_date"])

    if host.endswith("cnblogs.com"):
        for selector in ("#post-date", ".postDesc", ".post-info"):
            node = soup.select_one(selector)
            if node:
                candidates.append(node.get_text(" ", strip=True))
    else:
        for selector in (
            'time[itemprop="datePublished"]',
            "time.published[datetime]",
            "article header time[datetime]",
        ):
            node = soup.select_one(selector)
            if node:
                candidates.append(
                    node.get("datetime") or node.get_text(" ", strip=True)
                )

    return next(
        (
            normalized
            for candidate in candidates
            if (normalized := _normalize_date(candidate))
        ),
        "",
    )


async def _enrich_search_metadata(
    items: list[dict[str, str]],
    include_images: bool = True,
) -> list[dict[str, str]]:
    """Fill page text and metadata, optionally collecting an image for media search."""
    if not items:
        return items
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    semaphore = asyncio.Semaphore(5)
    reader_semaphore = asyncio.Semaphore(5)

    async def enrich(item: dict[str, str], client: httpx.AsyncClient) -> None:
        item["publish_date"] = _normalize_date(item.get("publish_date", ""))
        if item["publish_date"]:
            item["date_type"] = "发布日期"
        needs_page = (
            not item["publish_date"]
            or not item.get("word_count")
            or not item.get("source_content")
            or (include_images and not item.get("image_url"))
        )
        if needs_page and item.get("url", "").startswith(("http://", "https://")):
            try:
                async with semaphore:
                    response = await client.get(item["url"])
                if response.status_code < 400 and "html" in response.headers.get(
                    "content-type", ""
                ).lower():
                    soup = BeautifulSoup(response.text[:1_500_000], "html.parser")
                    host = urlparse(str(response.url)).netloc.lower()
                    json_ld_article = _extract_json_ld_article(soup)
                    page_date = _extract_page_publish_date(soup, host)
                    if page_date:
                        # Article-page metadata is more authoritative than a
                        # search snippet, which may expose a crawl/current date.
                        item["publish_date"] = page_date
                        item["date_type"] = "发布日期"
                    if include_images and not item.get("image_url"):
                        image_node = (
                            soup.select_one('meta[property="og:image"]')
                            or soup.select_one('meta[name="twitter:image"]')
                            or soup.select_one('meta[itemprop="image"]')
                        )
                        if image_node:
                            candidate = image_node.get("content") or ""
                            if candidate:
                                item["image_url"] = urljoin(
                                    str(response.url), candidate
                                )
                    site_selectors: tuple[str, ...] = ()
                    if host.endswith("csdn.net"):
                        site_selectors = (
                            "#content_views",
                            ".blog-content-box",
                            ".article_content",
                        )
                    elif host.endswith("zhihu.com"):
                        site_selectors = (
                            ".RichContent-inner",
                            ".Post-RichTextContainer",
                            ".QuestionAnswer-content",
                            ".ContentItem.AnswerItem",
                        )
                    elif host.endswith("cnblogs.com"):
                        site_selectors = (
                            "#cnblogs_post_body",
                            ".postBody",
                            ".blogpost-body",
                        )
                    article_body = next(
                        (
                            node
                            for selector in (
                                *site_selectors,
                                "article",
                                "[itemprop='articleBody']",
                                ".article-content",
                                ".post-content",
                                ".entry-content",
                                ".markdown-body",
                                "main",
                            )
                            if (node := soup.select_one(selector))
                        ),
                        None,
                    )
                    if not item["publish_date"] and json_ld_article.get(
                        "publish_date"
                    ):
                        item["publish_date"] = json_ld_article["publish_date"]
                        item["date_type"] = "发布日期"
                    if (
                        include_images
                        and not item.get("image_url")
                        and json_ld_article.get("image_url")
                    ):
                        item["image_url"] = json_ld_article["image_url"]
                    if article_body:
                        if include_images and not item.get("image_url"):
                            first_image = article_body.select_one("img")
                            if first_image:
                                candidate = next(
                                    (
                                        str(first_image.get(attribute) or "").strip()
                                        for attribute in (
                                            "data-src",
                                            "data-original",
                                            "data-url",
                                            "data-lazy-src",
                                            "src",
                                        )
                                        if str(first_image.get(attribute) or "").strip()
                                        and not str(
                                            first_image.get(attribute) or ""
                                        ).startswith("data:")
                                    ),
                                    "",
                                )
                                if candidate:
                                    item["image_url"] = urljoin(
                                        str(response.url),
                                        candidate,
                                    )
                        for node in article_body.select(
                            "script,style,noscript,nav,footer,header,aside,form"
                        ):
                            node.decompose()
                        body_text = _clean_research_text(
                            article_body.get_text("\n", strip=True)
                        )
                        item["source_content"] = body_text[:4000]
                        item["word_count"] = _estimate_word_count(body_text)
                    elif json_ld_article.get("content"):
                        body_text = json_ld_article["content"]
                        item["source_content"] = body_text[:4000]
                        item["word_count"] = _estimate_word_count(body_text)
                    else:
                        description_node = (
                            soup.select_one('meta[name="description"]')
                            or soup.select_one('meta[property="og:description"]')
                        )
                        description = (
                            str(description_node.get("content") or "")
                            if description_node
                            else ""
                        )
                        if _estimate_word_count(description) >= MIN_SOURCE_WORD_COUNT:
                            item["source_content"] = _clean_research_text(
                                description
                            )[:4000]
                            item["word_count"] = _estimate_word_count(description)
            except (httpx.HTTPError, ValueError):
                pass
        page_host = urlparse(str(item.get("url") or "")).netloc.lower()
        if (
            _estimate_word_count(item.get("source_content", ""))
            < MIN_SOURCE_WORD_COUNT
            and page_host.endswith("zhihu.com")
        ):
            # Zhihu commonly returns a login shell to server-side requests.
            # Use a public reader representation of the same URL as a text-only
            # fallback; no browser cookies or account data are forwarded.
            try:
                reader_url = f"https://r.jina.ai/{item['url']}"
                async with reader_semaphore:
                    reader_response = await client.get(
                        reader_url,
                        timeout=18,
                        headers={"Accept": "text/plain"},
                    )
                if (
                    reader_response.status_code >= 400
                    or "Markdown Content:" not in reader_response.text
                    or "安全验证 - 知乎" in reader_response.text
                ):
                    raise ValueError("reader did not return article content")
                if reader_response.status_code < 400:
                    reader_text = reader_response.text
                    body_text = (
                        reader_text.split("Markdown Content:", 1)[1]
                        if "Markdown Content:" in reader_text
                        else reader_text
                    )
                    body_text = _clean_research_text(body_text)
                    if _estimate_word_count(body_text) >= MIN_SOURCE_WORD_COUNT:
                        item["source_content"] = body_text[:4000]
                        item["word_count"] = _estimate_word_count(body_text)
                    if not item["publish_date"]:
                        published_match = re.search(
                            r"Published Time:\s*([^\n]+)",
                            reader_text,
                            re.I,
                        )
                        if published_match and (
                            published_date := _normalize_date(
                                published_match.group(1)
                            )
                        ):
                            item["publish_date"] = published_date
                            item["date_type"] = "发布日期"
            except (httpx.HTTPError, ValueError):
                pass
        if not item["publish_date"]:
            item["publish_date"] = ""
            item["date_type"] = "日期未知"
        if include_images:
            item.setdefault("image_url", "")
        else:
            item.pop("image_url", None)
            item.pop("image_urls", None)
        item["title"] = re.sub(
            r"^\s*#{1,6}\s*",
            "",
            str(item.get("title", "")),
        ).strip()
        item["summary"] = _clean_research_text(item.get("summary", ""))
        item["source_content"] = _clean_research_text(
            item.get("source_content") or item["summary"]
        )[:4000]
        if not item.get("word_count"):
            item["word_count"] = _estimate_word_count(
                f"{item.get('title', '')} {item.get('summary', '')}"
            )
        item.setdefault("date_type", "发布日期")

    async with httpx.AsyncClient(
        timeout=10,
        proxy=settings.glm_proxy_url or None,
        follow_redirects=True,
        headers=headers,
    ) as client:
        await asyncio.gather(*(enrich(item, client) for item in items))
    if include_images:
        items.sort(key=lambda item: bool(item.get("image_url")), reverse=True)
    return items


def _validate_public_article_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("文章地址无效，只支持公开的 HTTP 或 HTTPS 地址。")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise ValueError("不能抓取本机或局域网地址。")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ValueError("不能抓取内网或保留地址。")
    return parsed.geturl()


def _is_toutiao_article_url(value: str) -> bool:
    """Keep real Toutiao article/video detail URLs, not topic aggregation pages."""
    parsed = urlparse(str(value or "").strip())
    host = parsed.netloc.lower().removeprefix("www.")
    if not host.endswith("toutiao.com"):
        return True
    return bool(re.match(r"^/(?:article|group|item)/\d+/?$", parsed.path))


def _is_toutiao_detail_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    host = parsed.netloc.lower().removeprefix("www.")
    return host.endswith("toutiao.com") and _is_toutiao_article_url(value)


def _toutiao_reader_urls(value: str) -> list[str]:
    """Build canonical URL fallbacks because the same Toutiao item has several routes."""
    parsed = urlparse(value)
    host = parsed.netloc.lower().removeprefix("www.")
    if not host.endswith("toutiao.com"):
        return [value]
    item_match = re.search(r"/(?:article|group|item)/(\d+)", parsed.path)
    if not item_match:
        return [value]
    item_id = item_match.group(1)
    candidates = [
        f"https://www.toutiao.com/article/{item_id}/",
        f"https://www.toutiao.com/item/{item_id}/",
        value,
    ]
    return list(dict.fromkeys(candidates))


def _is_usable_selected_body(value: str, title: str, url: str) -> bool:
    body = str(value or "").strip()
    if _estimate_word_count(body) < MIN_SOURCE_WORD_COUNT:
        return False
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if not host.endswith("toutiao.com"):
        return True
    if not _is_toutiao_article_url(url):
        return False
    # A Toutiao video shell can be several hundred words long because it contains
    # navigation and recommendations, but it has no article正文.
    shell_signals = (
        "视频加载失败",
        "推荐视频",
        "下载今日头条APP",
        "自动连播",
        "点击切换下一个视频",
    )
    if sum(signal in body for signal in shell_signals) >= 2:
        return False
    navigation_signals = ("关注", "推荐", "北京", "视频", "财经", "科技", "热点", "国际")
    if sum(signal in body[:500] for signal in navigation_signals) >= 6:
        return False
    return True


def _source_cache_key(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _cache_source_content(item: dict[str, Any]) -> None:
    url = _source_cache_key(item.get("url", ""))
    body = _clean_research_text(item.get("source_content", ""))[:20_000]
    title = str(item.get("title") or "").strip()
    if not url or not _is_usable_selected_body(body, title, url):
        return
    now = time.monotonic()
    expired = [
        key
        for key, (expires_at, _) in _SOURCE_CONTENT_CACHE.items()
        if expires_at <= now
    ]
    for key in expired:
        _SOURCE_CONTENT_CACHE.pop(key, None)
    while len(_SOURCE_CONTENT_CACHE) >= SOURCE_CONTENT_CACHE_LIMIT:
        _SOURCE_CONTENT_CACHE.pop(next(iter(_SOURCE_CONTENT_CACHE)), None)
    cached = dict(item)
    cached["source_content"] = body
    cached["word_count"] = _estimate_word_count(body)
    cached.pop("image_url", None)
    cached.pop("image_urls", None)
    _SOURCE_CONTENT_CACHE[url] = (
        now + SOURCE_CONTENT_CACHE_TTL_SECONDS,
        cached,
    )
    _SOURCE_CONTENT_FAILURE_CACHE.pop(url, None)


def _get_cached_source_content(value: str) -> dict[str, Any] | None:
    key = _source_cache_key(value)
    cached = _SOURCE_CONTENT_CACHE.get(key)
    if not cached:
        return None
    expires_at, item = cached
    if expires_at <= time.monotonic():
        _SOURCE_CONTENT_CACHE.pop(key, None)
        return None
    return dict(item)


def _source_content_recently_failed(value: str) -> bool:
    key = _source_cache_key(value)
    expires_at = _SOURCE_CONTENT_FAILURE_CACHE.get(key, 0)
    if expires_at <= time.monotonic():
        _SOURCE_CONTENT_FAILURE_CACHE.pop(key, None)
        return False
    return True


def _mark_source_content_failure(value: str) -> None:
    key = _source_cache_key(value)
    if key:
        _SOURCE_CONTENT_FAILURE_CACHE[key] = (
            time.monotonic() + SOURCE_CONTENT_FAILURE_TTL_SECONDS
        )


def _clean_reader_markdown(value: str) -> str:
    body = str(value or "")
    if "Markdown Content:" in body:
        body = body.split("Markdown Content:", 1)[1]
    if "\n正文：" in body:
        body = body.split("\n正文：", 1)[1]
    for end_marker in ("\n举报\n", "\n评论区\n", "\n相关推荐\n"):
        marker_index = body.find(end_marker)
        if marker_index >= MIN_SOURCE_WORD_COUNT:
            body = body[:marker_index]
            break
    body = re.sub(r"!\[[^\]]*]\([^)]+\)", "", body)
    body = re.sub(r"\[\]\([^)]+\)", "", body)
    body = re.sub(r"\[([^\]]+)]\((?:https?://|//)[^)]+\)", r"\1", body)
    body = re.sub(r"(?m)^\s*(?:Title|URL Source|Published Time):.*$", "", body)
    return _clean_research_text(body)


async def fetch_source_content(source: dict[str, Any]) -> dict[str, Any]:
    """Deep-read one selected article after the lightweight search stage."""
    item = {
        "title": str(source.get("title") or "").strip(),
        "url": _validate_public_article_url(str(source.get("url") or "")),
        "summary": _clean_research_text(source.get("summary", ""))[:500],
        "source_content": "",
        "source": str(source.get("source") or "").strip(),
        "publish_date": _normalize_date(source.get("publish_date", "")),
        "date_type": str(source.get("date_type") or "发布日期"),
        "word_count": max(0, int(source.get("word_count") or 0)),
    }
    cached_item = _get_cached_source_content(item["url"])
    if cached_item:
        cached_item["title"] = item["title"] or cached_item.get("title", "")
        cached_item["source"] = item["source"] or cached_item.get("source", "")
        cached_item["publish_date"] = (
            item["publish_date"] or cached_item.get("publish_date", "")
        )
        return cached_item
    host = urlparse(item["url"]).netloc.lower().removeprefix("www.")
    reader_first = host.endswith(("toutiao.com", "zhihu.com"))
    reader_text = ""

    async def read_public_reader(article_url: str) -> str:
        reader_url = f"https://r.jina.ai/{article_url}"
        try:
            async with httpx.AsyncClient(
                timeout=45,
                proxy=settings.glm_proxy_url or None,
                follow_redirects=True,
                headers={"Accept": "text/plain"},
            ) as client:
                response = await client.get(reader_url)
            if response.status_code >= 400 or "Markdown Content:" not in response.text:
                return ""
            if re.search(r"内容可能已删除|安全验证|页面不存在", response.text):
                return ""
            if not item["publish_date"]:
                published_match = re.search(
                    r"Published Time:\s*([^\n]+)",
                    response.text,
                    re.I,
                )
                if published_match and (
                    published_date := _normalize_date(published_match.group(1))
                ):
                    item["publish_date"] = published_date
                    item["date_type"] = "发布日期"
            body = _clean_reader_markdown(response.text)
            return body if _is_usable_selected_body(body, item["title"], article_url) else ""
        except (httpx.HTTPError, ValueError):
            return ""

    if reader_first:
        for reader_candidate in _toutiao_reader_urls(item["url"]):
            reader_text = await read_public_reader(reader_candidate)
            if reader_text:
                break
    if _estimate_word_count(reader_text) >= MIN_SOURCE_WORD_COUNT:
        item["source_content"] = reader_text[:20_000]
    else:
        enriched = await _enrich_search_metadata([item], include_images=False)
        if enriched:
            item.update(enriched[0])
        if (
            _estimate_word_count(item.get("source_content", ""))
            < MIN_SOURCE_WORD_COUNT
            and not reader_first
        ):
            reader_text = await read_public_reader(item["url"])
            if _estimate_word_count(reader_text) >= MIN_SOURCE_WORD_COUNT:
                item["source_content"] = reader_text[:20_000]

    item.pop("image_url", None)
    item.pop("image_urls", None)
    item["source_content"] = _clean_research_text(
        item.get("source_content", "")
    )[:20_000]
    if not _is_usable_selected_body(
        item["source_content"],
        item["title"],
        item["url"],
    ):
        item["source_content"] = ""
    item["word_count"] = _estimate_word_count(item["source_content"])
    if item["word_count"] < MIN_SOURCE_WORD_COUNT:
        raise ValueError(
            "找到了文章标题，但平台没有返回可用正文。"
            "请打开原文确认文章仍可访问，或选择另一篇文章。"
        )
    if not item["publish_date"]:
        item["date_type"] = "日期未知"
    _cache_source_content(item)
    return item


def _usable_search_results(
    items: list[dict[str, str]],
    count: int,
) -> list[dict[str, str]]:
    usable: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in items:
        normalized_url = str(item.get("url", "")).rstrip("/")
        item["source_content"] = _clean_research_text(
            item.get("source_content") or item.get("summary", "")
        )[:4000]
        item["word_count"] = max(
            int(item.get("word_count") or 0),
            _estimate_word_count(item["source_content"]),
        )
        if (
            not item.get("title")
            or not normalized_url
            or normalized_url in seen_urls
            or item["word_count"] < MIN_SOURCE_WORD_COUNT
        ):
            continue
        seen_urls.add(normalized_url)
        usable.append(item)
        if len(usable) >= count:
            break
    return usable


async def _hydrate_selected_source_content(article: Article) -> None:
    """Read selected public pages and keep only a bounded text excerpt."""
    sources = list(article.selected_sources)
    if not sources:
        return
    max_chars = min(12_000, max(4000, 20_000 // len(sources)))

    async def hydrate(source: dict[str, Any]) -> None:
        source.pop("image_url", None)
        source.pop("image_urls", None)
        if (
            _estimate_word_count(source.get("source_content", ""))
            >= MIN_SOURCE_WORD_COUNT
        ):
            source["source_content"] = _clean_research_text(
                source["source_content"]
            )[:max_chars]
            source["word_count"] = _estimate_word_count(source["source_content"])
            return
        try:
            hydrated = await fetch_source_content(source)
            source.update(hydrated)
        except ValueError:
            source["source_content"] = _clean_research_text(
                source.get("summary", "")
            )[:max_chars]
        source["source_content"] = source.get("source_content", "")[:max_chars]
        source["word_count"] = _estimate_word_count(source["source_content"])

    await asyncio.gather(*(hydrate(source) for source in sources))


def _title_match_score(query: str, item: dict[str, str]) -> float:
    """Score search intent without requiring the whole query verbatim."""
    query_text = re.sub(r"\s+", " ", str(query or "")).strip().lower()
    title_text = re.sub(
        r"\s+",
        " ",
        str(item.get("title", "") or "").strip().lower(),
    )
    summary_text = re.sub(
        r"\s+",
        " ",
        str(item.get("summary", "") or "").strip().lower(),
    )
    if not query_text or not title_text:
        return 0

    query_key = re.sub(r"[\W_]+", "", query_text, flags=re.UNICODE)
    title_key = re.sub(r"[\W_]+", "", title_text, flags=re.UNICODE)
    score = 4.0 if query_key and query_key in title_key else 0.0

    latin_terms = re.findall(r"[a-z][a-z0-9+#.-]*", query_text)
    title_latin_terms = set(re.findall(r"[a-z][a-z0-9+#.-]*", title_text))
    summary_latin_terms = set(re.findall(r"[a-z][a-z0-9+#.-]*", summary_text))
    for term in latin_terms:
        if term in title_latin_terms:
            score += 2.0
        elif term in summary_latin_terms:
            score += 0.35

    generic_chinese_terms = {
        "应用",
        "文章",
        "技术",
        "教程",
        "介绍",
        "分析",
        "相关",
        "最新",
        "新闻",
        "实践",
        "怎么",
        "如何",
    }
    chinese_segments = re.findall(r"[\u4e00-\u9fff]+", query_text)
    for segment in chinese_segments:
        weight = 0.35 if segment in generic_chinese_terms else 1.5
        if segment in title_text:
            score += weight
            continue
        bigrams = {
            segment[index : index + 2]
            for index in range(max(0, len(segment) - 1))
        }
        if bigrams:
            title_hits = sum(bigram in title_text for bigram in bigrams)
            score += weight * (title_hits / len(bigrams))

    concept_groups = (
        {"ai", "人工智能", "大模型", "智能体", "agent"},
        {"应用", "工具", "产品", "落地", "实践"},
        {"教程", "指南", "入门", "实战", "上手"},
        {"故障", "报错", "排查", "问题", "修复"},
    )
    combined_query = f"{query_text} {query_key}"
    combined_title = f"{title_text} {title_key}"
    for group in concept_groups:
        if any(term in combined_query for term in group) and any(
            term in combined_title for term in group
        ):
            score += 0.8

    # Latin product names must match as complete tokens. This keeps "codex"
    # from treating "AlphaCode" as a relevant result merely due to letters.
    if latin_terms and not any(term in title_latin_terms for term in latin_terms):
        return 0
    return round(score, 4)


def _search_query_variants(query: str) -> list[str]:
    """Build a small, deterministic intent set for fuzzy discovery."""
    original = re.sub(r"\s+", " ", str(query or "")).strip()
    if not original:
        return []
    variants = [original]
    separated = re.sub(
        r"(?<=[A-Za-z0-9])(?=[\u4e00-\u9fff])|"
        r"(?<=[\u4e00-\u9fff])(?=[A-Za-z0-9])",
        " ",
        original,
    )
    variants.append(separated)

    lowered = original.lower()
    if re.search(r"(^|[^a-z])ai([^a-z]|$)", lowered) or "人工智能" in original:
        variants.extend(
            [
                re.sub(r"(?i)(^|[^a-z])ai([^a-z]|$)", r"\1人工智能\2", original),
                "AI 工具 产品 应用",
                "大模型 智能体 应用 落地",
            ]
        )
    if "应用" in original:
        variants.extend(
            [
                original.replace("应用", "工具"),
                original.replace("应用", "落地实践"),
            ]
        )
    if "教程" in original:
        variants.extend(
            [
                original.replace("教程", "入门指南"),
                original.replace("教程", "实战"),
            ]
        )
    if "问题" in original or "报错" in original:
        variants.append(
            original.replace("问题", "排查").replace("报错", "排查修复")
        )
    if (
        len(set(variants)) == 1
        and len(original) <= 16
        and not re.search(r"\s", original)
    ):
        variants.extend(
            [
                f"{original} 科普",
                f"{original} 经验",
                f"{original} 方法",
                f"{original} 知识",
                f"{original} 技巧",
            ]
        )

    unique: list[str] = []
    seen: set[str] = set()
    for value in variants:
        normalized = re.sub(r"\s+", " ", value).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique[:6]


def _fuzzy_search_expression(query: str) -> str:
    variants = _search_query_variants(query)
    if len(variants) <= 1:
        return variants[0] if variants else query
    return " OR ".join(f'"{variant}"' for variant in variants)


def _published_timestamp(item: dict[str, Any]) -> float:
    if str(item.get("date_type") or "") != "发布日期":
        return 0
    normalized = _normalize_date(item.get("publish_date"))
    if not normalized:
        return 0
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        ).timestamp()
    except ValueError:
        return 0


def _sort_search_results(
    items: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """Newest real publication date first, relevance and depth as tie-breakers."""
    return sorted(
        items,
        key=lambda item: (
            _published_timestamp(item),
            _title_match_score(query, item),
            bool(item.get("image_url")),
            int(item.get("word_count") or 0),
        ),
        reverse=True,
    )


def _finalize_search_results(
    items: list[dict[str, Any]],
    query: str,
    count: int,
    date_range: str = "all",
    sort_order: str = "newest",
) -> list[dict[str, Any]]:
    """Apply the requested real-date window and deterministic date ordering."""
    filtered = list(items)
    days = {"7d": 7, "30d": 30, "1y": 365}.get(date_range)
    if days:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).timestamp()
        filtered = [
            item
            for item in filtered
            if _published_timestamp(item) >= cutoff
        ]

    if sort_order == "oldest":
        filtered.sort(
            key=lambda item: (
                _published_timestamp(item) <= 0,
                _published_timestamp(item)
                if _published_timestamp(item) > 0
                else float("inf"),
                -_title_match_score(query, item),
            )
        )
    else:
        filtered = _sort_search_results(filtered, query)
    return _usable_search_results(filtered, count)


def _finalize_search_metadata(
    items: list[dict[str, Any]],
    query: str,
    count: int,
    date_range: str = "all",
    sort_order: str = "newest",
) -> list[dict[str, Any]]:
    """Return selectable article metadata without requiring full body extraction."""
    normalized_items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for raw_item in items:
        item = dict(raw_item)
        title = re.sub(
            r"^\s*#{1,6}\s*",
            "",
            str(item.get("title") or ""),
        ).strip()
        title = title.replace("**", "").replace("__", "").replace("_", "")
        url = str(item.get("url") or "").strip()
        normalized_url = url.rstrip("/")
        parsed_url = urlparse(url)
        if (
            not title
            or not url.startswith(("http://", "https://"))
            or parsed_url.path in {"", "/"}
            or normalized_url in seen_urls
            or _title_match_score(query, item) <= 0
        ):
            continue
        seen_urls.add(normalized_url)
        item["title"] = title
        item["url"] = url
        item["summary"] = _clean_research_text(item.get("summary", ""))[:500]
        _cache_source_content(item)
        item["source_content"] = ""
        item["publish_date"] = _normalize_date(item.get("publish_date", ""))
        item["date_type"] = "发布日期" if item["publish_date"] else "日期未知"
        item["word_count"] = max(0, int(item.get("word_count") or 0))
        item.pop("image_url", None)
        item.pop("image_urls", None)
        normalized_items.append(item)

    days = {"7d": 7, "30d": 30, "1y": 365}.get(date_range)
    if days:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).timestamp()
        normalized_items = [
            item
            for item in normalized_items
            if _published_timestamp(item) >= cutoff
        ]

    if sort_order == "oldest":
        normalized_items.sort(
            key=lambda item: (
                _published_timestamp(item) <= 0,
                _published_timestamp(item)
                if _published_timestamp(item) > 0
                else float("inf"),
                -_title_match_score(query, item),
            )
        )
    else:
        normalized_items = _sort_search_results(normalized_items, query)
    return normalized_items[:count]


async def _filter_extractable_metadata(
    items: list[dict[str, Any]],
    count: int,
) -> list[dict[str, Any]]:
    """Preflight selectable results and cache正文 so every displayed item can open."""
    if not items or count <= 0:
        return []
    candidate_limit = min(len(items), max(count + 10, count))
    semaphore = asyncio.Semaphore(10)

    async def validate(item: dict[str, Any]) -> dict[str, Any] | None:
        url = str(item.get("url") or "")
        if _source_content_recently_failed(url):
            return None
        try:
            async with semaphore:
                hydrated = await asyncio.wait_for(
                    fetch_source_content(item),
                    timeout=32,
                )
        except (
            asyncio.TimeoutError,
            httpx.HTTPError,
            RuntimeError,
            ValueError,
            KeyError,
            TypeError,
        ):
            _mark_source_content_failure(url)
            return None
        metadata = dict(item)
        metadata["source_content"] = ""
        metadata["word_count"] = int(hydrated.get("word_count") or 0)
        metadata["publish_date"] = (
            hydrated.get("publish_date") or metadata.get("publish_date") or ""
        )
        metadata["date_type"] = hydrated.get("date_type") or metadata.get(
            "date_type",
            "发布日期",
        )
        return metadata

    validated = await asyncio.gather(
        *(validate(dict(item)) for item in items[:candidate_limit])
    )
    return [item for item in validated if item is not None][:count]


def _parse_juejin_results(
    payload: dict[str, Any],
    query: str,
    source_name: str,
    excluded_urls: set[str],
) -> list[dict[str, Any]]:
    """Convert Juejin native search data and retain its full article body."""
    raw_items = payload.get("data") or []
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("data") or raw_items.get("items") or []
    if not isinstance(raw_items, list):
        return []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        model = raw_item.get("result_model") or raw_item
        if not isinstance(model, dict):
            continue
        article_info = model.get("article_info") or model
        if not isinstance(article_info, dict):
            continue
        article_id = str(
            article_info.get("article_id")
            or model.get("article_id")
            or ""
        ).strip()
        title = BeautifulSoup(
            str(article_info.get("title") or ""),
            "html.parser",
        ).get_text(" ", strip=True)
        if not article_id or not title:
            continue
        url = f"https://juejin.cn/post/{article_id}"
        normalized_url = url.rstrip("/")
        if normalized_url in excluded_urls or normalized_url in seen:
            continue
        content = _clean_research_text(article_info.get("content") or "")
        summary = _clean_research_text(
            article_info.get("brief_content") or ""
        )
        item = {
            "title": title,
            "url": url,
            "summary": summary,
            "source_content": content[:20_000],
            "source": source_name.strip() or "掘金",
            "publish_date": _normalize_date(
                article_info.get("ctime")
                or article_info.get("mtime")
            ),
            "date_type": "发布日期",
            "word_count": _estimate_word_count(content or summary),
            "image_url": str(
                article_info.get("cover_image")
                or article_info.get("cover_image_url")
                or ""
            ).strip(),
        }
        if _title_match_score(query, item) <= 0:
            continue
        seen.add(normalized_url)
        results.append(item)
    return _sort_search_results(results, query)


async def _search_juejin(
    query: str,
    source_name: str,
    excluded_urls: list[str],
    count: int,
) -> list[dict[str, Any]]:
    variants = _search_query_variants(query)[:4]
    if not variants or count <= 0:
        return []
    excluded = {url.rstrip("/") for url in excluded_urls}
    collected: list[dict[str, Any]] = []
    seen = set(excluded)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://juejin.cn/",
    }
    async with httpx.AsyncClient(
        timeout=18,
        proxy=settings.glm_proxy_url or None,
        follow_redirects=True,
        headers=headers,
    ) as client:
        for page in range(3):
            tasks = [
                client.post(
                    "https://api.juejin.cn/search_api/v1/search",
                    params={"aid": "2608", "spider": "0"},
                    json={
                        "key_word": variant,
                        "id_type": 0,
                        "cursor": str(page * 20),
                        "limit": 20,
                        "search_type": 0,
                        # Juejin's native "newest" order.
                        "sort_type": 1,
                        "version": 1,
                    },
                )
                for variant in variants
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            page_added = 0
            for response in responses:
                if isinstance(response, Exception) or response.is_error:
                    continue
                try:
                    parsed = _parse_juejin_results(
                        response.json(),
                        query=query,
                        source_name=source_name,
                        excluded_urls=seen,
                    )
                except ValueError:
                    continue
                for item in parsed:
                    normalized_url = str(item.get("url") or "").rstrip("/")
                    if not normalized_url or normalized_url in seen:
                        continue
                    seen.add(normalized_url)
                    collected.append(item)
                    page_added += 1
            if len(collected) >= max(count * 2, 20) or page_added == 0:
                break
    return _sort_search_results(collected, query)


def _parse_csdn_results(
    payload: dict[str, Any],
    query: str,
    source_name: str,
    excluded_urls: set[str],
) -> list[dict[str, Any]]:
    raw_items = payload.get("result_vos") or []
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        title = BeautifulSoup(
            str(raw_item.get("title") or ""),
            "html.parser",
        ).get_text(" ", strip=True)
        raw_url = str(
            raw_item.get("url")
            or raw_item.get("url_location")
            or ""
        ).strip()
        parsed_url = urlparse(raw_url)
        url = (
            f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
            if parsed_url.scheme in {"http", "https"} and parsed_url.netloc
            else ""
        )
        normalized_url = url.rstrip("/")
        if (
            not title
            or not normalized_url
            or normalized_url in excluded_urls
            or normalized_url in seen
        ):
            continue
        content = _clean_research_text(raw_item.get("body") or "")
        summary = _clean_research_text(
            raw_item.get("description")
            or raw_item.get("digest")
            or ""
        )
        item = {
            "title": title,
            "url": url,
            "summary": summary,
            "source_content": content[:20_000],
            "source": str(
                raw_item.get("nickname")
                or raw_item.get("author")
                or source_name
                or "CSDN"
            ).strip(),
            "publish_date": _normalize_date(
                raw_item.get("created_at")
                or raw_item.get("create_time_str")
                or raw_item.get("create_time")
            ),
            "date_type": "发布日期",
            "word_count": _estimate_word_count(content or summary),
            "image_url": _extract_mapping_image(raw_item),
        }
        if _title_match_score(query, item) <= 0:
            continue
        seen.add(normalized_url)
        items.append(item)
    return _sort_search_results(items, query)


async def _search_csdn(
    query: str,
    source_name: str,
    excluded_urls: list[str],
    count: int,
) -> list[dict[str, Any]]:
    variants = _search_query_variants(query)[:4]
    if not variants or count <= 0:
        return []
    excluded = {url.rstrip("/") for url in excluded_urls}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://so.csdn.net/so/search",
    }
    page = 1 + len(excluded) // 30
    base_params = {
        "t": "blog",
        "p": page,
        "s": 0,
        "tm": 0,
        "lv": -1,
        "ft": 0,
        "ct": -1,
        "pnt": -1,
        "ry": -1,
        "ss": -1,
        "dct": -1,
        "vco": -1,
        "cc": -1,
        "sc": -1,
        "akt": -1,
        "art": -1,
        "ca": -1,
        "ecc": -1,
        "ebc": -1,
        "ia": 1,
        "cl": -1,
        "scl": -1,
        "tcl": -1,
        "platform": "pc",
    }
    collected: list[dict[str, Any]] = []
    seen = set(excluded)
    async with httpx.AsyncClient(
        timeout=20,
        proxy=settings.glm_proxy_url or None,
        follow_redirects=True,
        headers=headers,
    ) as client:
        responses = await asyncio.gather(
            *[
                client.get(
                    "https://so.csdn.net/api/v3/search",
                    params={**base_params, "q": variant},
                )
                for variant in variants
            ],
            return_exceptions=True,
        )
    for response in responses:
        if isinstance(response, Exception) or response.is_error:
            continue
        try:
            parsed = _parse_csdn_results(
                response.json(),
                query=query,
                source_name=source_name,
                excluded_urls=seen,
            )
        except ValueError:
            continue
        for item in parsed:
            normalized_url = str(item.get("url") or "").rstrip("/")
            if not normalized_url or normalized_url in seen:
                continue
            seen.add(normalized_url)
            collected.append(item)
    return _sort_search_results(collected, query)[: max(count * 2, 30)]


async def _search_zhihu_candidates(
    query: str,
    source_name: str,
    excluded_urls: list[str],
    count: int,
) -> list[dict[str, Any]]:
    """Discover Zhihu columns and long-form answers before reader enrichment."""
    variants = _search_query_variants(query)[:4] or [query]
    zhihu_domains = ("zhuanlan.zhihu.com", "www.zhihu.com")
    tasks = [
        _search_sogou(
            query=variant,
            source_domain=domain,
            source_name=source_name or "知乎",
            excluded_urls=excluded_urls,
            count=max(10, count),
        )
        for variant in variants
        for domain in zhihu_domains
    ]
    tasks.extend(
        [
            _search_bing(
                query=query,
                source_domain=domain,
                source_name=source_name or "知乎",
                excluded_urls=excluded_urls,
                count=max(10, count),
            )
            for domain in zhihu_domains
        ]
    )
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    seen = {url.rstrip("/") for url in excluded_urls}
    items: list[dict[str, Any]] = []
    for batch in batches:
        if isinstance(batch, Exception):
            continue
        for item in batch:
            normalized_url = str(item.get("url") or "").rstrip("/")
            if not normalized_url or normalized_url in seen:
                continue
            seen.add(normalized_url)
            items.append(item)
    items.sort(
        key=lambda item: _title_match_score(query, item),
        reverse=True,
    )
    return items[: max(count * 2, 30)]


async def search_web(
    query: str,
    exclude_urls: list[str] | None = None,
    count: int = 10,
    source_domain: str = "",
    source_name: str = "",
    title_only: bool = True,
    broad_search: bool = False,
    include_images: bool = True,
    date_range: str = "all",
    sort_order: str = "newest",
) -> list[dict[str, str]]:
    excluded = {url.rstrip("/") for url in (exclude_urls or [])}
    requested_domain = source_domain.strip().lower().removeprefix("www.")
    search_expression = _fuzzy_search_expression(query)
    pool_count = min(40, max(count * 2, 20))
    payload = {
        "search_query": search_expression,
        "search_engine": settings.glm_search_engine,
        "search_intent": True,
        "count": min(max(pool_count + len(excluded), 20), 50),
        "search_recency_filter": {
            "7d": "oneWeek",
            "30d": "oneMonth",
            "1y": "oneYear",
        }.get(date_range, "noLimit"),
        "content_size": "large",
    }
    direct_task = None
    if requested_domain.endswith("juejin.cn"):
        direct_task = asyncio.create_task(
            _search_juejin(
                query=query,
                source_name=source_name,
                excluded_urls=list(excluded),
                count=pool_count,
            )
        )
    elif requested_domain.endswith("csdn.net"):
        direct_task = asyncio.create_task(
            _search_csdn(
                query=query,
                source_name=source_name,
                excluded_urls=list(excluded),
                count=pool_count,
            )
        )
    elif requested_domain.endswith("zhihu.com"):
        direct_task = asyncio.create_task(
            _search_zhihu_candidates(
                query=query,
                source_name=source_name,
                excluded_urls=list(excluded),
                count=pool_count,
            )
        )
    elif requested_domain.endswith("toutiao.com"):
        direct_task = asyncio.create_task(
            _search_toutiao(
                query=query,
                source_domain=requested_domain,
                source_name=source_name,
                excluded_urls=list(excluded),
                count=pool_count,
            )
        )
    direct_results: list[dict[str, str]] = []
    if requested_domain:
        payload["search_domain_filter"] = requested_domain
    raw_items: list[dict[str, Any]] = []
    if settings.glm_api_key.strip():
        try:
            async with httpx.AsyncClient(
                timeout=35,
                proxy=settings.glm_proxy_url or None,
            ) as client:
                response = await client.post(
                    f"{settings.glm_base_url.rstrip('/')}/web_search",
                    headers=_headers(),
                    json=payload,
                )
            if not response.is_error:
                response_data = response.json()
                usage = response_data.get("usage") or {}
                record_token_usage(
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    total_tokens=int(usage.get("total_tokens") or 0),
                )
                raw_items = response_data.get("search_result", [])
        except (httpx.RequestError, ValueError):
            raw_items = []

    if direct_task:
        try:
            direct_results = await direct_task
        except (httpx.HTTPError, ValueError):
            direct_results = []
        if not title_only:
            direct_results = await _enrich_search_metadata(
                direct_results[:pool_count],
                include_images=include_images,
            )
            direct_results = _sort_search_results(direct_results, query)
            direct_usable = _finalize_search_results(
                direct_results,
                query,
                count,
                date_range,
                sort_order,
            )
            if len(direct_usable) >= count:
                return direct_usable
    candidates = []
    seen_urls: set[str] = {
        str(item.get("url", "")).rstrip("/") for item in direct_results
    }
    for item in raw_items:
        link = item.get("link", "")
        title = item.get("title", "").strip()
        normalized = link.rstrip("/")
        if not title or not link or normalized in excluded or normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        candidates.append(
            {
                "title": title,
                "url": link,
                "summary": item.get("content", "").strip(),
                "source": item.get("media", "").strip(),
                "publish_date": item.get("publish_date", "") or "",
                "date_type": "发布日期",
                "image_url": _extract_mapping_image(item),
            }
        )

    candidates = [
        item for item in candidates if _title_match_score(query, item) > 0
    ]
    if requested_domain.endswith("toutiao.com"):
        candidates = [
            item
            for item in candidates
            if _is_toutiao_detail_url(str(item.get("url") or ""))
        ]
    candidates = _sort_search_results(candidates, query)

    if title_only:
        metadata_candidates = _finalize_search_metadata(
            direct_results + candidates,
            query,
            min(pool_count, count + 10),
            date_range,
            sort_order,
        )
        metadata_results = await _filter_extractable_metadata(
            metadata_candidates,
            count,
        )
        if len(metadata_results) >= count:
            return metadata_results
        metadata_excluded = list(
            excluded
            | {
                str(item.get("url", "")).rstrip("/")
                for item in metadata_results
                if item.get("url")
            }
        )
        fallback_domain = (
            "zhuanlan.zhihu.com"
            if requested_domain.endswith("zhihu.com")
            else requested_domain
        )
        fallback_queries = (
            (_search_query_variants(query)[:4] or [query])
            if broad_search or requested_domain
            else [query]
        )
        fallback_tasks = []
        for fallback_query in fallback_queries:
            fallback_tasks.extend(
                [
                    _search_bing(
                        query=fallback_query,
                        source_domain=fallback_domain,
                        source_name=source_name,
                        excluded_urls=metadata_excluded,
                        count=pool_count,
                    ),
                    _search_sogou(
                        query=fallback_query,
                        source_domain=fallback_domain,
                        source_name=source_name,
                        excluded_urls=metadata_excluded,
                        count=pool_count,
                    ),
                ]
            )
        fallback_batches = await asyncio.gather(*fallback_tasks)
        fallback_metadata = [
            item
            for batch in fallback_batches
            for item in batch
        ]
        if requested_domain.endswith("toutiao.com"):
            fallback_metadata = [
                item
                for item in fallback_metadata
                if _is_toutiao_detail_url(str(item.get("url") or ""))
            ]
        combined_metadata = _finalize_search_metadata(
            direct_results + candidates + fallback_metadata,
            query,
            min(pool_count, count + 10),
            date_range,
            sort_order,
        )
        return await _filter_extractable_metadata(combined_metadata, count)

    # Prefer different websites first, then fill remaining slots with other
    # unique articles. This gives users visibly broader source choices.
    results: list[dict[str, str]] = list(direct_results)
    deferred: list[dict[str, str]] = []
    seen_domains: set[str] = set()
    for item in candidates:
        candidate_domain = urlparse(item["url"]).netloc.lower().removeprefix("www.")
        if candidate_domain and candidate_domain not in seen_domains:
            seen_domains.add(candidate_domain)
            results.append(item)
        else:
            deferred.append(item)
    results.extend(deferred)
    results = await _enrich_search_metadata(
        results[:pool_count],
        include_images=include_images,
    )
    results = _sort_search_results(results, query)
    usable_results = _finalize_search_results(
        results,
        query,
        count,
        date_range,
        sort_order,
    )
    if len(usable_results) >= count:
        return usable_results

    # The structured API occasionally returns zero results for colloquial
    # queries. Use a public search-results page as a resilient fallback.
    fallback_excluded = list(
        excluded
        | {
            str(item.get("url", "")).rstrip("/")
            for item in results
            if item.get("url")
        }
    )
    fallback_domain = (
        "zhuanlan.zhihu.com"
        if requested_domain.endswith("zhihu.com")
        else requested_domain
    )
    fallback_tasks = [
        _search_bing(
            query=query,
            source_domain=fallback_domain,
            source_name=source_name,
            excluded_urls=fallback_excluded,
            count=pool_count,
        )
    ]
    fallback_tasks.append(
        _search_sogou(
            query=query,
            source_domain=fallback_domain,
            source_name=source_name,
            excluded_urls=fallback_excluded,
            count=pool_count,
        )
    )
    fallback_batches = await asyncio.gather(*fallback_tasks)
    fallback = [
        item
        for batch in fallback_batches
        for item in batch
    ]
    if requested_domain.endswith("toutiao.com"):
        fallback = [
            item
            for item in fallback
            if _is_toutiao_detail_url(str(item.get("url") or ""))
        ]
    fallback = await _enrich_search_metadata(
        fallback[:pool_count],
        include_images=include_images,
    )
    return _finalize_search_results(
        usable_results + fallback,
        query,
        count,
        date_range,
        sort_order,
    )


async def _search_toutiao(
    query: str,
    source_domain: str,
    source_name: str,
    excluded_urls: list[str],
    count: int,
) -> list[dict[str, str]]:
    if count <= 0:
        return []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    variants = _search_query_variants(query)[:4] or [query]
    try:
        async with httpx.AsyncClient(
            timeout=20,
            proxy=settings.glm_proxy_url or None,
            follow_redirects=True,
            headers=headers,
        ) as client:
            responses = await asyncio.gather(
                *[
                    client.get(
                        "https://so.toutiao.com/search",
                        params={
                            "keyword": variant,
                            "offset": len(excluded_urls),
                            "pd": "synthesis",
                            "source": "input",
                        },
                    )
                    for variant in variants
                ],
                return_exceptions=True,
            )
    except httpx.HTTPError:
        return []

    excluded = {url.rstrip("/") for url in excluded_urls}
    seen: set[str] = set()
    items: list[dict[str, str]] = []
    per_variant = max(5, (count + len(variants) - 1) // len(variants) + 2)

    def clean_text(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return BeautifulSoup(html.unescape(value), "html.parser").get_text(
            " ", strip=True
        )

    def clean_date(value: Any) -> str:
        if isinstance(value, (int, float)):
            timestamp = value / 1000 if value > 10_000_000_000 else value
            try:
                return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                )
            except (ValueError, OSError, OverflowError):
                return ""
        if isinstance(value, str):
            if value.isdigit():
                return clean_date(int(value))
            date_match = re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", value)
            return date_match.group(0).replace("/", "-").replace(".", "-") if date_match else ""
        return ""

    def clean_word_count(value: Any) -> int:
        try:
            return max(0, int(float(value or 0)))
        except (TypeError, ValueError, OverflowError):
            return 0

    def walk(value: Any, bucket: list[dict[str, str]]) -> None:
        if len(bucket) >= per_variant:
            return
        if isinstance(value, dict):
            raw_url = value.get("article_url") or value.get("doc_url") or ""
            h5_url = (
                parse_qs(urlparse(raw_url).query).get("h5_url", [""])[0]
                if isinstance(raw_url, str)
                else ""
            )
            url = h5_url if h5_url.startswith(("http://", "https://")) else raw_url
            emphasized = value.get("emphasized") or {}
            title = value.get("title") or emphasized.get("title") or ""
            summary = (
                value.get("abstract")
                or value.get("summary")
                or emphasized.get("summary")
                or ""
            )
            normalized = url.rstrip("/") if isinstance(url, str) else ""
            is_video = bool(
                value.get("has_video")
                or value.get("video_url")
                or str(value.get("media_type") or "") == "2"
                or str(value.get("content_schema_type") or "") == "3"
            )
            raw_host = (
                urlparse(raw_url).netloc.lower().removeprefix("www.")
                if isinstance(raw_url, str)
                else ""
            )
            if (
                normalized
                and title
                and normalized not in excluded
                and normalized not in seen
                and not is_video
                and _is_toutiao_article_url(url)
                and (
                    raw_host.endswith("toutiao.com")
                    or raw_host.endswith("zlink.toutiao.com")
                )
            ):
                seen.add(normalized)
                candidate = {
                    "title": clean_text(title),
                    "url": url,
                    "summary": clean_text(summary),
                    "source": clean_text(
                        value.get("source")
                        or value.get("media_name")
                        or source_name
                        or "今日头条"
                    ),
                    "publish_date": clean_date(
                        value.get("publish_time")
                        or value.get("create_time")
                        or value.get("display_time")
                        or value.get("datetime")
                    ),
                    "date_type": "发布日期",
                    "word_count": clean_word_count(
                        (value.get("data_ext") or {}).get("core_content_size")
                        or value.get("content_size")
                    ),
                    "image_url": _extract_mapping_image(value),
                }
                if _title_match_score(query, candidate) > 0:
                    bucket.append(candidate)
            for child in value.values():
                walk(child, bucket)
        elif isinstance(value, list):
            for child in value:
                walk(child, bucket)

    decoder = json.JSONDecoder()
    for response in responses:
        if isinstance(response, Exception) or response.is_error:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        bucket: list[dict[str, str]] = []
        for script in soup.find_all("script"):
            script_text = script.string or script.get_text()
            if "article_url" not in script_text:
                continue
            marker = re.search(r"data:\s*", script_text)
            if not marker:
                continue
            start = script_text.find("{", marker.end())
            if start < 0:
                continue
            try:
                data = decoder.raw_decode(script_text[start:])[0]
            except (json.JSONDecodeError, TypeError):
                continue
            walk(data, bucket)
            if len(bucket) >= per_variant:
                break
        items.extend(bucket)
        if len(items) >= count:
            break

    return _sort_search_results(items, query)[:count]


async def _search_sogou(
    query: str,
    source_domain: str,
    source_name: str,
    excluded_urls: list[str],
    count: int,
) -> list[dict[str, str]]:
    if count <= 0:
        return []
    fuzzy_query = _fuzzy_search_expression(query)
    search_query = (
        f"site:{source_domain} ({fuzzy_query})"
        if source_domain
        else fuzzy_query
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    page = 1 + (len(excluded_urls) // 8)
    excluded = {url.rstrip("/") for url in excluded_urls}
    raw_results: list[dict[str, str]] = []

    async with httpx.AsyncClient(
        timeout=25,
        proxy=settings.glm_proxy_url or None,
        follow_redirects=True,
        headers=headers,
    ) as client:
        try:
            response = await client.get(
                "https://www.sogou.com/web",
                params={"query": search_query, "page": page},
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            if "antispider" not in str(response.url):
                for result in soup.select(".vrwrap"):
                    heading = result.select_one("h3")
                    anchor = heading.select_one("a") if heading else None
                    if not heading or not anchor:
                        continue
                    title = heading.get_text(" ", strip=True)
                    raw_url = str(anchor.get("href") or "").strip()
                    if not title or not raw_url:
                        continue
                    snippet = result.select_one(".fz-mid") or result.select_one(
                        ".str_info"
                    )
                    date_node = result.select_one(".cite-date")
                    image_node = result.select_one("img")
                    image_url = ""
                    if image_node:
                        image_url = (
                            image_node.get("data-src")
                            or image_node.get("src")
                            or ""
                        )
                        image_url = (
                            urljoin(str(response.url), image_url)
                            if image_url
                            else ""
                        )
                    raw_results.append(
                        {
                            "title": title,
                            "raw_url": urljoin(str(response.url), raw_url),
                            "summary": (
                                snippet.get_text(" ", strip=True)
                                if snippet
                                else ""
                            ),
                            "publish_date": (
                                date_node.get_text(" ", strip=True)
                                if date_node
                                else ""
                            ),
                            "image_url": image_url,
                        }
                    )
        except httpx.HTTPError:
            pass

        if not raw_results:
            reader_target = (
                "http://www.sogou.com/web?"
                + urlencode({"query": search_query, "page": page})
            )
            try:
                reader_response = await client.get(
                    f"https://r.jina.ai/{reader_target}",
                    headers={"Accept": "text/plain"},
                )
                if reader_response.status_code < 400:
                    for title, raw_url in re.findall(
                        r"(?m)^###\s+\[([^\]\n]+)]"
                        r"\((https?://www\.sogou\.com/link\?url=[^)]+)\)",
                        reader_response.text,
                    ):
                        raw_results.append(
                            {
                                "title": _clean_research_text(title),
                                "raw_url": html.unescape(raw_url),
                                "summary": "",
                                "publish_date": "",
                                "image_url": "",
                            }
                        )
            except httpx.HTTPError:
                pass

        async def resolve_result(raw_item: dict[str, str]) -> dict[str, str] | None:
            raw_url = raw_item["raw_url"]
            actual_url = raw_url
            raw_host = urlparse(raw_url).netloc.lower().removeprefix("www.")
            if raw_host.endswith("sogou.com"):
                try:
                    redirect_response = await client.get(raw_url)
                except httpx.HTTPError:
                    return None
                actual_url = str(redirect_response.url)
                if urlparse(actual_url).netloc.lower().endswith("sogou.com"):
                    redirect_match = re.search(
                        r"""(?:window\.location\.replace\(|URL=['"])["']?([^"'<>]+)""",
                        redirect_response.text,
                        re.I,
                    )
                    if redirect_match:
                        actual_url = html.unescape(redirect_match.group(1))
            host = urlparse(actual_url).netloc.lower().removeprefix("www.")
            normalized = actual_url.rstrip("/")
            if (
                not actual_url.startswith(("http://", "https://"))
                or normalized in excluded
                or (source_domain and not host.endswith(source_domain))
            ):
                return None
            return {
                "title": raw_item["title"],
                "url": actual_url,
                "summary": raw_item["summary"],
                "source": source_name.strip() or source_domain or host,
                "publish_date": raw_item["publish_date"],
                "date_type": "发布日期",
                "image_url": raw_item["image_url"],
            }

        resolved = await asyncio.gather(
            *(resolve_result(item) for item in raw_results[: max(count * 2, 20)])
        )

    seen: set[str] = set()
    items: list[dict[str, str]] = []
    for item in resolved:
        if not item:
            continue
        normalized = item["url"].rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        items.append(item)
        if len(items) >= count:
            break
    return items


async def _search_bing(
    query: str,
    source_domain: str,
    source_name: str,
    excluded_urls: list[str],
    count: int,
) -> list[dict[str, str]]:
    if count <= 0:
        return []
    fuzzy_query = _fuzzy_search_expression(query)
    search_query = (
        f"site:{source_domain} ({fuzzy_query})"
        if source_domain
        else fuzzy_query
    )
    params = {
        "q": search_query,
        "count": min(max(count * 2, 10), 30),
        "first": len(excluded_urls) + 1,
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        async with httpx.AsyncClient(
            timeout=20,
            proxy=settings.glm_proxy_url or None,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(
                "https://cn.bing.com/search",
                params=params,
            )
        response.raise_for_status()
    except httpx.HTTPError:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    excluded = {url.rstrip("/") for url in excluded_urls}
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for result in soup.select("li.b_algo"):
        anchor = result.select_one("h2 a")
        if not anchor:
            continue
        url = (anchor.get("href") or "").strip()
        title = anchor.get_text(" ", strip=True)
        normalized = url.rstrip("/")
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if (
            not title
            or not url.startswith(("http://", "https://"))
            or normalized in excluded
            or normalized in seen
            or (source_domain and not host.endswith(source_domain))
        ):
            continue
        snippet = result.select_one(".b_caption p")
        summary = snippet.get_text(" ", strip=True) if snippet else ""
        date_match = _normalize_date(summary)
        image_node = result.select_one("img")
        image_url = ""
        if image_node:
            image_url = image_node.get("data-src") or image_node.get("src") or ""
            image_url = urljoin(str(response.url), image_url) if image_url else ""
        site_label = source_name.strip() or host or "网页来源"
        seen.add(normalized)
        items.append(
            {
                "title": title,
                "url": url,
                "summary": summary,
                "source": site_label,
                "publish_date": date_match,
                "date_type": "发布日期",
                "image_url": image_url,
            }
        )
        if len(items) >= count:
            break
    return items


async def suggest_titles(
    topic: str,
    article_type: str,
    custom_type_description: str,
    writing_style: str,
    layout_style: str,
    excluded_titles: list[str] | None = None,
    source_titles: list[str] | None = None,
) -> list[str]:
    fallback_titles = [
        f"{topic}，这次把关键细节讲清楚",
        f"{topic}为什么又被大家提起",
        f"{topic}没有想象中那么简单",
        f"聊到{topic}，有件事很容易被忽略",
        f"{topic}背后，变化发生在哪里",
        f"关于{topic}，原文里最值得保留的信息",
        f"{topic}之后，留下了哪些实际变化",
        f"别急着评价{topic}，细节比结论重要",
        f"{topic}这件事，可能和你想的不太一样",
        f"再聊{topic}，把容易漏掉的部分补上",
    ]
    excluded = [title.strip() for title in (excluded_titles or []) if title.strip()]
    source_title_keys = {
        re.sub(r"[\W_]+", "", title.casefold(), flags=re.UNICODE)
        for title in (source_titles or [])
        if title and title.strip()
    }
    formula_patterns = (
        r"^从.+(?:出发|看懂|理解|读懂)",
        r"从.+角度",
        r"三种视角",
        r"先把问题说清楚",
        r"真正应该",
        r"适用边界",
        r"一条可检查",
        r"重新审视",
        r"角度\s*\d+",
    )

    def normalize(title: str) -> str:
        value = title.lower().replace(topic.lower(), "")
        return re.sub(r"[\W_]+", "", value, flags=re.UNICODE)

    def is_distinct(title: str, accepted: list[str]) -> bool:
        title = re.sub(r"\s+", " ", title).strip().strip("\"'“”")
        if not 6 <= len(title) <= 48 or title in excluded:
            return False
        full_title_key = re.sub(
            r"[\W_]+",
            "",
            title.casefold(),
            flags=re.UNICODE,
        )
        if full_title_key in source_title_keys:
            return False
        if any(re.search(pattern, title) for pattern in formula_patterns):
            return False
        normalized = normalize(title)
        if len(normalized) < 3:
            return False
        for previous in [*excluded, *accepted]:
            previous_normalized = normalize(previous)
            if normalized == previous_normalized:
                return False
            if SequenceMatcher(None, normalized, previous_normalized).ratio() >= 0.72:
                return False
        return True

    references = "\n".join(
        f"- {title.strip()}" for title in (source_titles or [])[:8] if title.strip()
    ) or "- 暂无来源标题，只能围绕用户主题拟题"
    excluded_text = "\n".join(f"- {title}" for title in excluded[-30:]) or "- 无"
    prompt = f"""请为下面的中文文章生成恰好 10 个自然、不公式化的候选标题。

主题：{topic}
文章类型与排版：{article_type} / {layout_style}
自定义类型要求：{custom_type_description.strip() or "无"}

用户当前选中的原文标题（这是最重要的拟题依据）：
{references}

禁止重复：
{excluded_text}

先观察原文标题里的主体、人物、事件、关键词、语序和自然语气，再拟出同一话题下的新标题。
不得原样返回任何一个原文标题；保留题眼，但必须形成新的完整标题。
至少 6 个标题要保留原文标题中的核心名词或事件，不把具体题目改成抽象方法论。
如果原文像新闻，就直接说事件；像教程，就说清要做什么；像娱乐、美食或生活内容，就保留原文自然口吻。
十个标题的句式、开头和语气必须明显不同；最多 3 个使用冒号，最多 2 个使用问号。
换一批时必须避开“禁止重复”中的标题，也不能只换一个近义词。

禁止出现这些公式句：
- “从……角度出发/看懂/理解……”
- “到底在解决什么”“真正应该先查什么”“先把问题说清楚”
- “适用边界”“三种视角”“一条可检查的路径”
- “关于 X 的几个判断”“重新审视 X”“角度 1/2/3”

具体、顺口、像真实作者拟的标题，不用标题党词，不虚构经历、结果或数字。每个 10-32 个汉字，不加序号。
只输出合法 JSON：{{"titles":["标题1","标题2"]}}"""

    candidates: list[str] = []
    try:
        raw = await _chat(
            settings.glm_title_model,
            "你是中文内容平台的资深标题编辑。你尊重原文题眼，标题自然、具体、有口语节奏，不套固定方法论模板。",
            prompt,
            enable_thinking=False,
            temperature=0.98,
            max_tokens=450,
            timeout_seconds=25,
        )
        json_match = re.search(r"\{.*\}", raw, re.S)
        parsed = json.loads(json_match.group(0) if json_match else raw)
        values = parsed.get("titles", []) if isinstance(parsed, dict) else []
        for item in values:
            title = item.get("title", "") if isinstance(item, dict) else str(item)
            title = re.sub(r"^\s*\d+[.、]\s*", "", title).strip()
            if is_distinct(title, candidates):
                candidates.append(title)
    except (RuntimeError, json.JSONDecodeError, TypeError, AttributeError):
        # Title generation should not block source research. Diverse local
        # fallbacks keep the workflow usable if the fast model is unavailable.
        candidates = []

    for title in fallback_titles:
        if len(candidates) >= 10:
            break
        if is_distinct(title, candidates):
            candidates.append(title)

    # This branch is only reached after many "换一批" requests or an API failure.
    emergency_templates = [
        "{topic}，还有一些细节值得单独说说",
        "这次聊{topic}，重点落在具体变化上",
        "{topic}热度之外，原文还说了什么",
        "{topic}的故事，比一句结论更完整",
        "把{topic}放回真实场景再聊一次",
        "{topic}，哪些信息值得留下",
        "大家都在聊{topic}，这部分却很少被提到",
        "{topic}并不遥远，它已经影响到这些细节",
        "再看{topic}，原来重点藏在这里",
        "{topic}的前因后果，一篇说完整",
    ]
    batch = 1 + len(excluded) // 10
    for template in emergency_templates:
        if len(candidates) >= 10:
            break
        title = template.format(topic=topic)
        if batch > 1:
            title = f"{title}（新稿）"
        if is_distinct(title, candidates):
            candidates.append(title)
    return candidates[:10]


async def _prepare_expert_brief(
    article: Article,
    usage: dict[str, int],
) -> tuple[str, list[dict[str, str]]]:
    source_baseline = _writer_source_baseline(article)
    target_words = min(
        5000,
        max(200, getattr(article, "target_word_count", 1500) or 1500),
    )
    try:
        raw = await _chat_with_retry(
            settings.glm_expert_model,
            EXPERT_PROMPT,
            (
                "请为后续写手和编辑总监准备资料简报。所有论点必须能回到以下"
                "材料核对，并重点解决目标字数需要哪些真实内容来支撑。\n\n"
                f"{_format_material(article, include_draft=True)}"
            ),
            fallback_model=settings.glm_writer_model,
            max_tokens=min(
                settings.glm_max_tokens,
                5000,
                max(1600, min(4200, target_words + 1200)),
            ),
            enable_thinking=False,
            temperature=min(settings.glm_temperature, 0.3),
            timeout_seconds=min(settings.glm_timeout_seconds, 150),
            usage_collector=usage,
        )
    except RuntimeError:
        return "", []

    brief = _extract_tagged_section(raw, "EXPERT_BRIEF")
    if not brief:
        brief = re.sub(
            r"^```(?:markdown|md)?\s*|\s*```$",
            "",
            raw.strip(),
            flags=re.I,
        ).strip()
    if not brief:
        return "", []

    before_excerpt = re.sub(r"\s+", " ", source_baseline).strip()[:180]
    after_excerpt = re.sub(r"\s+", " ", brief).strip()[:180]
    if not after_excerpt or before_excerpt == after_excerpt:
        return brief, []
    return brief, [
        {
            "role": "专家",
            "location": "论点与字数拓展资料",
            "before": before_excerpt or "用户主题和选定原文",
            "after": after_excerpt,
            "reason": (
                f"基于现有材料为约 {target_words} 字文章提炼可拓展论点、"
                "材料依据、篇幅安排和事实边界，供写手与总监使用。"
            ),
        }
    ]


async def _request_writer_revision(
    article: Article,
    current_content: str,
    requester_role: str,
    usage: dict[str, int],
    expert_brief: str = "",
    require_expansion: bool = False,
) -> tuple[str, list[dict[str, str]]]:
    target_words = min(
        5000,
        max(200, getattr(article, "target_word_count", 1500) or 1500),
    )
    lower_bound = max(200, int(target_words * 0.97))
    upper_bound = min(5000, max(lower_bound, int(target_words * 1.03)))
    action = "补写和拓展" if require_expansion else "重新修订"
    role_label = f"写手（{requester_role}退回补写）"
    best_content = current_content
    best_words = _visible_article_length(best_content)
    attempts = 2 if require_expansion else 1

    for attempt in range(1, attempts + 1):
        try:
            raw = await _chat_with_retry(
                settings.glm_writer_model,
                f"""{WRITER_ROLE_PROMPT}

{FACT_RULES}

你收到{requester_role}退回的稿件，需要在这次调用内完成{action}。
只能展开现有材料已经包含的事实、原因、联系、解释和适用边界，不得新增经历、
数据、人物、参数或确定性结论。保留文章完整逻辑、Markdown 标题和发布日期。
这是第 {attempt}/{attempts} 次补写机会。当前最佳稿约 {best_words} 字，必须尽量达到 {lower_bound}-{upper_bound} 字，
并接近 {target_words} 字。不要用重复句、空话或机械列表凑字数。
只输出 <ARTICLE>完整 Markdown 文章</ARTICLE>，不要输出说明或代码围栏。""",
                (
                    f"{_format_material(article, include_draft=False, include_writing_style=True)}"
                    f"\n\n【专家提供的论点与拓展资料】\n"
                    f"{expert_brief[:10000] if expert_brief else '本次没有可用专家简报，只能使用原始材料'}"
                    f"\n\n【{requester_role}退回的当前稿件】\n{best_content[:18000]}"
                ),
                fallback_model=settings.glm_reviewer_model,
                max_tokens=min(
                    settings.glm_max_tokens,
                    9000,
                    max(2200, target_words + 1800),
                ),
                enable_thinking=False,
                temperature=min(settings.glm_temperature, 0.4),
                timeout_seconds=min(settings.glm_timeout_seconds, 180),
                usage_collector=usage,
            )
        except RuntimeError:
            continue

        candidate = _extract_tagged_section(raw, "ARTICLE")
        if not candidate and re.search(r"(?m)^\s*#\s+\S+", raw):
            candidate = raw.strip()
        if not candidate or not _has_substantive_body_difference(
            best_content,
            candidate,
        ):
            continue

        candidate_words = _visible_article_length(candidate)
        if require_expansion and candidate_words <= best_words:
            continue
        if abs(candidate_words - target_words) > abs(best_words - target_words):
            continue
        best_content = candidate
        best_words = candidate_words
        if lower_bound <= best_words <= upper_bound:
            break

    if best_content == current_content:
        return current_content, []

    reason = (
        f"{requester_role}发现稿件约 {_visible_article_length(current_content)} 字，低于目标区间 "
        f"{lower_bound}-{upper_bound} 字，退回写手基于已有材料补充解释和边界。"
        if require_expansion
        else f"{requester_role}退回写手完成一轮实质修订。"
    )
    changes = _build_verified_change_records(
        current_content,
        best_content,
        role_label,
        reason,
        limit=12,
    )
    return (best_content, changes) if changes else (current_content, [])


async def _request_director_revision(
    article: Article,
    current_content: str,
    expert_brief: str,
    writer_draft: str,
    usage: dict[str, int],
    require_expansion: bool = False,
) -> tuple[str, list[dict[str, str]]]:
    target_words = min(
        5000,
        max(200, getattr(article, "target_word_count", 1500) or 1500),
    )
    lower_bound = max(200, int(target_words * 0.97))
    upper_bound = min(5000, max(lower_bound, int(target_words * 1.03)))
    best_content = current_content
    best_words = _visible_article_length(best_content)
    attempts = 2 if require_expansion else 1

    for attempt in range(1, attempts + 1):
        try:
            raw = await _chat_with_retry(
                settings.glm_director_model,
                f"""{DIRECTOR_ROLE_PROMPT}

{FACT_RULES}

你仍然是编辑总监。发现终稿内容或字数不足时，不得把工作退回给写手，
而要亲自结合专家资料和当前稿件重新组织文章、补充已有事实的细节描述、
解释逻辑并完善总结，使文章更完整、更自然。
这是第 {attempt}/{attempts} 次总监修订机会。当前最佳稿约 {best_words} 字，
终稿应达到 {lower_bound}-{upper_bound} 字并接近 {target_words} 字。
不得新增材料没有支持的数据、人物、经历、参数或结论，不得重复凑字数。
只输出 <ARTICLE>完整 Markdown 终稿</ARTICLE>，不要输出解释或代码围栏。""",
                (
                    f"{_format_material(article, include_draft=False)}\n\n"
                    f"【专家解析的论点与拓展资料】\n"
                    f"{expert_brief[:10000] if expert_brief else '没有额外专家资料，只能使用原始材料'}"
                    f"\n\n【写手初稿】\n"
                    f"{writer_draft[:16000] if writer_draft else '未单独保留写手初稿，请以当前稿件为准'}"
                    f"\n\n【总监当前稿件】\n{best_content[:18000]}"
                ),
                max_tokens=min(
                    settings.glm_max_tokens,
                    9000,
                    max(2200, target_words + 1800),
                ),
                enable_thinking=False,
                temperature=min(settings.glm_temperature, 0.25),
                timeout_seconds=min(settings.glm_timeout_seconds, 180),
                usage_collector=usage,
            )
        except RuntimeError:
            continue

        candidate = _extract_tagged_section(raw, "ARTICLE")
        if not candidate and re.search(r"(?m)^\s*#\s+\S+", raw):
            candidate = raw.strip()
        if not candidate or not _has_substantive_body_difference(
            best_content,
            candidate,
        ):
            continue

        candidate_words = _visible_article_length(candidate)
        if require_expansion and candidate_words <= best_words:
            continue
        if abs(candidate_words - target_words) > abs(best_words - target_words):
            continue
        best_content = candidate
        best_words = candidate_words
        if lower_bound <= best_words <= upper_bound:
            break

    if best_content == current_content:
        return current_content, []

    initial_words = _visible_article_length(current_content)
    reason = (
        f"编辑总监发现稿件约 {initial_words} 字，结合专家论点和当前文章，"
        f"亲自补充细节、解释与总结，使内容接近 {lower_bound}-{upper_bound} 字。"
        if require_expansion
        else "编辑总监结合专家解析和当前文章，亲自重新组织并完善细节与总结。"
    )
    changes = _build_verified_change_records(
        current_content,
        best_content,
        "编辑总监",
        reason,
        limit=12,
    )
    return (best_content, changes) if changes else (current_content, [])


async def edit_and_review_article(
    article: Article,
) -> tuple[
    str,
    str,
    str,
    list[dict[str, str]],
    dict[str, int],
]:
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    requested_words = min(
        5000,
        max(200, getattr(article, "target_word_count", 1500) or 1500),
    )
    await _hydrate_selected_source_content(article)
    expert_brief, expert_changes = await _prepare_expert_brief(article, usage)
    material = _format_material(article, include_writing_style=True)
    source_baseline = _writer_source_baseline(article)
    first_stage = await _chat_with_retry(
        settings.glm_writer_model,
        EDITOR_PROMPT,
        (
            "请严格依次完成写手和审核官两轮工作。只能使用这里给出的标题、"
            "摘要、已提取正文和元信息，不得声称访问了未提供的内容。"
            "两版文章必须都完整输出，审核稿必须对写手稿作出真实可见的修改。\n\n"
            f"{material}\n\n【专家提供的论点与拓展资料】\n"
            f"{expert_brief[:10000] if expert_brief else '本次没有可用专家简报，只能使用原始材料'}"
        ),
        fallback_model=settings.glm_reviewer_model,
        enable_thinking=False,
        max_tokens=min(
            settings.glm_max_tokens,
            15000,
            max(3200, requested_words * 2 + 2800),
        ),
        temperature=min(settings.glm_temperature, 0.5),
        timeout_seconds=min(settings.glm_timeout_seconds, 210),
        usage_collector=usage,
    )

    writer_article = _extract_tagged_section(first_stage, "WRITER_ARTICLE")
    reviewed_article = _extract_tagged_section(first_stage, "ARTICLE")
    raw_writer_review = _extract_tagged_section(first_stage, "WRITER_REVIEW")
    raw_review = _extract_tagged_section(first_stage, "REVIEW")
    if not writer_article or not reviewed_article:
        raise RuntimeError(
            "写手与审核官返回格式异常，必须同时返回完整写手稿和审核稿。请重试。"
        )

    writer_summary, writer_claimed_changes = _parse_role_audit_payload(
        raw_writer_review,
        "写手",
        "写手已依据原始材料重新组织标题、结构和表达。",
    )
    review_notes, reviewer_claimed_changes = _parse_role_audit_payload(
        raw_review,
        "审核官",
        "审核官已对照原始材料检查事实、逻辑和表达。",
    )
    writer_changes = _build_verified_change_records(
        source_baseline,
        writer_article,
        "写手",
        writer_summary,
        writer_claimed_changes,
        limit=12,
    )
    if not _has_substantive_body_difference(source_baseline, writer_article):
        writer_changes = []
    reviewer_changes = _build_verified_change_records(
        writer_article,
        reviewed_article,
        "审核官",
        review_notes,
        reviewer_claimed_changes,
        limit=12,
    )
    if not _has_substantive_body_difference(writer_article, reviewed_article):
        reviewed_article, returned_changes = await _request_writer_revision(
            article,
            reviewed_article,
            "审核官",
            usage,
            expert_brief=expert_brief,
            require_expansion=(
                _visible_article_length(reviewed_article)
                < max(200, int(requested_words * 0.97))
            ),
        )
        reviewer_changes = returned_changes

    target_word_count = min(
        5000,
        max(200, getattr(article, "target_word_count", 1500) or 1500),
    )
    lower_bound = max(200, int(target_word_count * 0.97))
    reviewer_word_count = _visible_article_length(reviewed_article)
    if reviewer_word_count < lower_bound:
        reviewed_article, supplement_changes = await _request_writer_revision(
            article,
            reviewed_article,
            "审核官",
            usage,
            expert_brief=expert_brief,
            require_expansion=True,
        )
        if supplement_changes:
            writer_changes.extend(supplement_changes)
            review_notes = (
                f"{review_notes.rstrip('。')}；审核官发现正文只有约 "
                f"{reviewer_word_count} 字，已退回写手补充并重新提交。"
            )

    # The first API call performs writer + reviewer. The second and final role
    # call belongs to the director. Keep the temporary audit manuscript out of
    # the database until both calls have succeeded.
    original_content = article.content
    original_status = article.status
    article.content = reviewed_article
    article.status = "generated"
    try:
        (
            final_content,
            director_summary,
            director_changes,
            director_usage,
        ) = await director_review_article(
            article,
            expert_brief=expert_brief,
            writer_draft=writer_article,
        )
    finally:
        article.content = original_content
        article.status = original_status
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        usage[key] = usage.get(key, 0) + director_usage.get(key, 0)

    generation_changes: list[dict[str, str]] = list(expert_changes)
    generation_changes.extend(writer_changes)
    generation_changes.extend(reviewer_changes)
    generation_changes.extend(
        {
            **change,
            "role": str(change.get("role") or "编辑总监"),
        }
        for change in director_changes
    )

    usage["word_count"] = _visible_article_length(final_content)
    if not usage["total_tokens"]:
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return (
        final_content,
        review_notes,
        director_summary,
        generation_changes,
        usage,
    )


def _extract_tagged_section(value: str, tag: str) -> str:
    complete = re.search(
        rf"<{tag}>\s*(.*?)\s*</{tag}>",
        value,
        re.S | re.I,
    )
    if complete:
        return complete.group(1).strip()
    opened = re.search(rf"<{tag}>\s*(.*)$", value, re.S | re.I)
    if not opened:
        return ""
    return re.split(r"<[A-Z_]+>", opened.group(1), maxsplit=1, flags=re.I)[0].strip()


def _audit_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw_line in (value or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or line in {ARTICLE_DISCLAIMER, "---"}:
            continue
        if re.match(r"^#\s+\S+", line):
            continue
        if re.match(r"^(?:>\s*)?(?:文章)?主题\s*[/：:].*", line):
            continue
        if re.match(r"^!\[[^\]]*]\([^)]+\)$", line):
            continue
        if re.match(r"^>\s*发布日期[：:].*$", line):
            continue
        lines.append(line)
    return lines


def _normalize_audit_change(
    item: dict[str, Any],
    role: str,
    default_reason: str,
) -> dict[str, str] | None:
    before = str(item.get("before") or "").strip()[:180]
    after = str(item.get("after") or "").strip()[:180]
    reason = str(item.get("reason") or default_reason).strip()[:300]
    if not before and not after and not reason:
        return None
    if not before:
        before = "原稿此处没有对应内容"
    if not after:
        after = "已删除"
    if re.sub(r"\s+", "", before) == re.sub(r"\s+", "", after):
        return None
    return {
        "role": role,
        "location": str(item.get("location") or "正文").strip()[:120],
        "before": before,
        "after": after,
        "reason": reason or default_reason,
    }


def _build_text_change_records(
    before_text: str,
    after_text: str,
    role: str,
    reason: str,
    limit: int = 12,
) -> list[dict[str, str]]:
    before_lines = _audit_lines(before_text)
    after_lines = _audit_lines(after_text)
    matcher = SequenceMatcher(None, before_lines, after_lines, autojunk=False)
    records: list[dict[str, str]] = []
    for tag, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        before_value = " ".join(before_lines[before_start:before_end]).strip()
        full_after_value = " ".join(
            after_lines[after_start:after_end]
        ).strip()
        after_value = _only_changed_after_fragment(
            before_value,
            full_after_value,
        )
        change = _normalize_audit_change(
            {
                "location": f"正文第 {len(records) + 1} 处",
                "before": before_value,
                "after": after_value,
                "reason": reason,
            },
            role,
            reason,
        )
        if change:
            records.append(change)
        if len(records) >= limit:
            break
    return records


def _only_changed_after_fragment(before_value: str, after_value: str) -> str:
    """Return only added/replaced text while omitting unchanged context."""
    if not after_value or not before_value:
        return after_value
    matcher = SequenceMatcher(None, before_value, after_value, autojunk=False)
    if matcher.ratio() < 0.35:
        return after_value
    fragments = [
        after_value[after_start:after_end].strip()
        for tag, _before_start, _before_end, after_start, after_end in matcher.get_opcodes()
        if tag != "equal" and after_start < after_end
    ]
    meaningful = [fragment for fragment in fragments if fragment]
    return " … ".join(meaningful) if meaningful else after_value


def _writer_source_baseline(article: Article) -> str:
    if (article.content or "").strip():
        return article.content.strip()

    source_parts: list[str] = []
    for source in article.selected_sources or []:
        if not isinstance(source, dict):
            continue
        source_text = str(
            source.get("source_content")
            or source.get("summary")
            or source.get("title")
            or ""
        ).strip()
        if source_text:
            source_parts.append(source_text)
    if source_parts:
        return "\n\n".join(source_parts)

    material_parts = [
        article.project_background,
        article.problems,
        article.solution_process,
        article.author_voice,
        article.reference_materials,
    ]
    fallback = "\n\n".join(
        str(value).strip() for value in material_parts if str(value or "").strip()
    )
    return fallback or f"{article.title}\n{article.topic}"


def _has_substantive_body_difference(before_text: str, after_text: str) -> bool:
    def body(value: str) -> str:
        lines = [
            line
            for line in _audit_lines(value)
            if not re.match(r"^#{1,6}\s+\S+", line)
        ]
        return re.sub(r"[\s*_`>|-]+", "", "\n".join(lines))

    return bool(body(after_text)) and body(before_text) != body(after_text)


def _build_verified_change_records(
    before_text: str,
    after_text: str,
    role: str,
    default_reason: str,
    claimed_changes: list[dict[str, str]] | None = None,
    limit: int = 12,
) -> list[dict[str, str]]:
    records = _build_text_change_records(
        before_text,
        after_text,
        role,
        default_reason,
        limit=limit,
    )
    for index, record in enumerate(records):
        if not claimed_changes or index >= len(claimed_changes):
            continue
        claim = claimed_changes[index]
        claimed_location = str(claim.get("location") or "").strip()
        claimed_reason = str(claim.get("reason") or "").strip()
        if claimed_location:
            record["location"] = claimed_location[:120]
        if claimed_reason:
            record["reason"] = claimed_reason[:300]
    return records


def _parse_role_audit_payload(
    raw_review: str,
    role: str,
    fallback_summary: str,
) -> tuple[str, list[dict[str, str]]]:
    clean_review = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        (raw_review or "").strip(),
        flags=re.I,
    ).strip()
    try:
        review_data = json.loads(clean_review)
    except (json.JSONDecodeError, TypeError):
        review_data = None

    if not isinstance(review_data, dict):
        summary = re.sub(r"\s+", " ", clean_review).strip()[:300]
        return summary or fallback_summary, []

    summary = str(review_data.get("summary") or fallback_summary).strip()[:300]
    changes: list[dict[str, str]] = []
    for item in (review_data.get("changes") or [])[:20]:
        if not isinstance(item, dict):
            continue
        change = _normalize_audit_change(
            item,
            role,
            fallback_summary,
        )
        if change:
            changes.append(change)
    return summary, changes


def _parse_reviewer_payload(
    raw_review: str,
) -> tuple[str, list[dict[str, str]]]:
    return _parse_role_audit_payload(
        raw_review,
        "审核官",
        "审核官已完成事实、逻辑和表达审核。",
    )


def _parse_director_payload(
    reviewed: str,
) -> tuple[str, str, list[dict[str, str]]]:
    article_text = _extract_tagged_section(reviewed, "ARTICLE")
    raw_review = (
        _extract_tagged_section(reviewed, "DIRECTOR_REVIEW")
        or _extract_tagged_section(reviewed, "REVIEW")
    )

    fenced = re.sub(
        r"^```(?:json|markdown|md)?\s*|\s*```$",
        "",
        reviewed.strip(),
        flags=re.I,
    ).strip()
    parsed_whole: dict[str, Any] | None = None
    if fenced.startswith("{") and fenced.endswith("}"):
        try:
            candidate = json.loads(fenced)
            if isinstance(candidate, dict):
                parsed_whole = candidate
        except json.JSONDecodeError:
            parsed_whole = None

    if parsed_whole:
        article_text = article_text or str(
            parsed_whole.get("article")
            or parsed_whole.get("content")
            or parsed_whole.get("revised_article")
            or ""
        ).strip()
        if not raw_review:
            review_candidate = parsed_whole.get("review") or parsed_whole
            raw_review = (
                json.dumps(review_candidate, ensure_ascii=False)
                if isinstance(review_candidate, (dict, list))
                else str(review_candidate or "")
            )

    if not article_text:
        manuscript_heading = re.search(
            r"(?:^|\n)#{1,6}\s*(?:完整)?(?:修订稿|修改后文章|最终稿|文章正文)\s*\n([\s\S]+)$",
            reviewed,
            re.I,
        )
        if manuscript_heading:
            article_text = manuscript_heading.group(1).strip()
        elif re.search(r"(?m)^\s*#\s+\S+", reviewed):
            without_review = re.sub(
                r"<(?:DIRECTOR_REVIEW|REVIEW)>[\s\S]*?</(?:DIRECTOR_REVIEW|REVIEW)>",
                "",
                reviewed,
                flags=re.I,
            )
            article_text = without_review.strip()

    summary = "资深编辑总监已完成复审。"
    changes: list[dict[str, str]] = []
    if raw_review:
        clean_review = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            raw_review.strip(),
            flags=re.I,
        ).strip()
        try:
            review_data = json.loads(clean_review)
        except (json.JSONDecodeError, TypeError):
            review_data = None
            summary = re.sub(r"\s+", " ", clean_review).strip()[:300] or summary
        if isinstance(review_data, dict):
            summary = str(review_data.get("summary") or summary).strip()
            for item in (review_data.get("changes") or [])[:20]:
                if not isinstance(item, dict):
                    continue
                change = _normalize_audit_change(
                    item,
                    "编辑总监",
                    "从完整性、可读性和事实边界角度完成终审。",
                )
                if change:
                    changes.append(change)

    article_text = re.sub(
        r"^```(?:markdown|md)?\s*|\s*```$",
        "",
        article_text.strip(),
        flags=re.I,
    ).strip()
    return article_text, summary, changes


async def director_review_article(
    article: Article,
    expert_brief: str = "",
    writer_draft: str = "",
) -> tuple[str, str, list[dict[str, str]], dict[str, int]]:
    """Review the user's current editable draft and return an auditable revision."""
    current_content = (article.content or "").strip()
    if article.status != "generated":
        raise ValueError("资深编辑总监只复审已经生成的文章，请先完成“生成并审核”。")
    if not current_content:
        raise ValueError("当前文章没有可复审的内容，请先生成或填写文章。")

    await _hydrate_selected_source_content(article)
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    requested_words = min(
        5000,
        max(200, getattr(article, "target_word_count", 1500) or 1500),
    )
    lower_bound = max(200, int(requested_words * 0.97))
    upper_bound = min(5000, max(lower_bound, int(requested_words * 1.03)))
    current_word_count = _visible_article_length(current_content)
    reviewed = await _chat_with_retry(
        settings.glm_director_model,
        DIRECTOR_PROMPT,
        (
            f"{_format_material(article, include_draft=False)}\n\n"
            f"【本次终审硬性验收】审核稿当前约 {current_word_count} 字；"
            f"终稿必须达到 {lower_bound}-{upper_bound} 字，并尽量接近 "
            f"{requested_words} 字。不得把短稿继续压缩。输出前自行核对字数。\n\n"
            f"【专家提供的论点与拓展资料】\n"
            f"{expert_brief[:10000] if expert_brief else '本次没有可用专家简报，只能使用原始材料'}\n\n"
            f"【写手初稿】\n"
            f"{writer_draft[:16000] if writer_draft else '本次未单独保留写手初稿，请以审核稿为准'}\n\n"
            f"【用户当前可编辑稿件】\n{current_content[:18000]}"
        ),
        max_tokens=min(
            settings.glm_max_tokens,
            9000,
            max(2200, requested_words + 1800),
        ),
        enable_thinking=False,
        temperature=0.2,
        timeout_seconds=min(settings.glm_timeout_seconds, 180),
        usage_collector=usage,
    )
    final_content, summary, claimed_changes = _parse_director_payload(reviewed)
    if not final_content:
        final_content = current_content
        claimed_changes = []
        summary = (
            "编辑总监首次返回格式不完整，已保留审核稿并继续独立修订。"
        )
    final_content = _finalize_article_metadata(article, final_content)
    changes = _build_verified_change_records(
        current_content,
        final_content,
        "编辑总监",
        summary,
        claimed_changes,
        limit=12,
    )
    has_director_revision = bool(changes) and _has_substantive_body_difference(
        current_content,
        final_content,
    )
    final_word_count = _visible_article_length(final_content)
    if final_word_count < lower_bound or not has_director_revision:
        supplemented, supplement_changes = await _request_director_revision(
            article,
            final_content,
            expert_brief,
            writer_draft,
            usage,
            require_expansion=final_word_count < lower_bound,
        )
        if supplement_changes:
            final_content = _finalize_article_metadata(article, supplemented)
            changes.extend(supplement_changes)
            summary = (
                f"{summary.rstrip('。')}；编辑总监结合专家解析和当前文章，"
                f"亲自{'补充细节、描述与总结' if final_word_count < lower_bound else '重新组织并完善终稿'}。"
            )
            final_word_count = _visible_article_length(final_content)

    if final_word_count < lower_bound or final_word_count > upper_bound:
        summary = (
            f"{summary.rstrip('。')}；本次最完整终稿约 {final_word_count} 字，"
            f"目标区间为 {lower_bound}-{upper_bound} 字，文章仍已完整保存。"
        )
    if final_word_count < MIN_SOURCE_WORD_COUNT:
        raise RuntimeError(
            "四个角色完成协作后正文仍不足 200 字，本次不保存短稿。"
            "请更换一篇内容更完整的原文后重试。"
        )
    usage["word_count"] = final_word_count
    if not usage["total_tokens"]:
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return final_content, summary, changes, usage
