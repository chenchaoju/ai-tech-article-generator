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
        "参考第一篇已选原文的信…26218 tokens truncated…正文和元信息，不得声称访问了未提供的内容。"
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
