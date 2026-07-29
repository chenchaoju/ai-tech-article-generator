import json
from uuid import uuid4

import httpx
from dotenv import set_key
from fastapi import APIRouter, HTTPException

from app.core.config import PROJECT_ROOT, settings
from app.db.session import record_token_usage
from app.schemas.settings import (
    ConnectionTestResponse,
    ModelProfileListResponse,
    ModelProfileResponse,
    ModelProfileSaveRequest,
    ModelSettingsResponse,
    ModelSettingsUpdate,
    WechatConnectionTestRequest,
)
from app.services.wechat import get_wechat_access_token


router = APIRouter(prefix="/settings", tags=["settings"])
ENV_FILE = PROJECT_ROOT / ".env"
PROFILE_FIELDS = (
    "base_url",
    "title_model",
    "expert_model",
    "writer_model",
    "reviewer_model",
    "director_model",
    "temperature",
    "max_tokens",
    "enable_thinking",
    "proxy_url",
    "token_budget",
)


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:4]}••••••••{value[-4:]}"


def _normalize_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    for suffix in ("/chat/completions", "/chat"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].rstrip("/")
            break
    return normalized


def _current_profile(profile_id: str = "default", name: str = "默认模型") -> dict:
    return {
        "id": profile_id,
        "name": name,
        "api_key": settings.glm_api_key.strip(),
        "base_url": settings.glm_base_url,
        "title_model": settings.glm_title_model,
        "expert_model": settings.glm_expert_model,
        "writer_model": settings.glm_writer_model,
        "reviewer_model": settings.glm_reviewer_model,
        "director_model": settings.glm_director_model,
        "temperature": settings.glm_temperature,
        "max_tokens": settings.glm_max_tokens,
        "enable_thinking": settings.glm_enable_thinking,
        "proxy_url": settings.glm_proxy_url,
        "token_budget": settings.glm_token_budget,
    }


def _load_profiles() -> list[dict]:
    try:
        raw_profiles = json.loads(settings.model_profiles_json or "[]")
    except (TypeError, json.JSONDecodeError):
        raw_profiles = []
    profiles = [
        profile
        for profile in raw_profiles
        if isinstance(profile, dict)
        and str(profile.get("id") or "").strip()
        and str(profile.get("name") or "").strip()
    ]
    if profiles:
        return profiles
    return [_current_profile()]


def _active_profile_id(profiles: list[dict] | None = None) -> str:
    available = profiles or _load_profiles()
    configured_id = settings.active_model_profile_id.strip()
    if configured_id and any(item["id"] == configured_id for item in available):
        return configured_id
    return str(available[0]["id"])


def _save_profiles(profiles: list[dict], active_profile_id: str) -> None:
    serialized = json.dumps(profiles, ensure_ascii=False, separators=(",", ":"))
    set_key(str(ENV_FILE), "MODEL_PROFILES_JSON", serialized, quote_mode="always")
    set_key(
        str(ENV_FILE),
        "ACTIVE_MODEL_PROFILE_ID",
        active_profile_id,
        quote_mode="never",
    )
    settings.model_profiles_json = serialized
    settings.active_model_profile_id = active_profile_id


def _profile_response(profile: dict, active_profile_id: str) -> ModelProfileResponse:
    api_key = str(profile.get("api_key") or "")
    return ModelProfileResponse(
        id=str(profile["id"]),
        name=str(profile["name"]),
        api_key_configured=bool(api_key.strip()),
        api_key_masked=_mask_key(api_key.strip()),
        base_url=str(profile.get("base_url") or settings.glm_base_url),
        title_model=str(profile.get("title_model") or settings.glm_title_model),
        expert_model=str(profile.get("expert_model") or settings.glm_expert_model),
        writer_model=str(profile.get("writer_model") or settings.glm_writer_model),
        reviewer_model=str(
            profile.get("reviewer_model") or settings.glm_reviewer_model
        ),
        director_model=str(
            profile.get("director_model") or settings.glm_director_model
        ),
        temperature=float(profile.get("temperature", settings.glm_temperature)),
        max_tokens=int(profile.get("max_tokens", settings.glm_max_tokens)),
        enable_thinking=bool(
            profile.get("enable_thinking", settings.glm_enable_thinking)
        ),
        proxy_url=str(profile.get("proxy_url") or ""),
        token_budget=int(profile.get("token_budget") or 0),
        active=str(profile["id"]) == active_profile_id,
    )


def _profiles_response() -> ModelProfileListResponse:
    profiles = _load_profiles()
    active_profile_id = _active_profile_id(profiles)
    return ModelProfileListResponse(
        active_profile_id=active_profile_id,
        profiles=[
            _profile_response(profile, active_profile_id) for profile in profiles
        ],
    )


def _apply_profile(profile: dict) -> None:
    values = {
        "GLM_API_KEY": str(profile.get("api_key") or "").strip(),
        "GLM_BASE_URL": _normalize_base_url(str(profile["base_url"])),
        "GLM_TITLE_MODEL": str(profile["title_model"]),
        "GLM_EXPERT_MODEL": str(profile["expert_model"]),
        "GLM_WRITER_MODEL": str(profile["writer_model"]),
        "GLM_REVIEWER_MODEL": str(profile["reviewer_model"]),
        "GLM_DIRECTOR_MODEL": str(profile["director_model"]),
        "GLM_MODEL": str(profile["writer_model"]),
        "GLM_TEMPERATURE": str(profile["temperature"]),
        "GLM_MAX_TOKENS": str(profile["max_tokens"]),
        "GLM_ENABLE_THINKING": str(bool(profile.get("enable_thinking"))).lower(),
        "GLM_PROXY_URL": str(profile.get("proxy_url") or "").strip(),
        "GLM_TOKEN_BUDGET": str(profile.get("token_budget") or 0),
    }
    for key, value in values.items():
        set_key(str(ENV_FILE), key, value, quote_mode="never")

    settings.glm_api_key = values["GLM_API_KEY"]
    settings.glm_base_url = values["GLM_BASE_URL"]
    settings.glm_model = values["GLM_MODEL"]
    settings.glm_title_model = values["GLM_TITLE_MODEL"]
    settings.glm_expert_model = values["GLM_EXPERT_MODEL"]
    settings.glm_writer_model = values["GLM_WRITER_MODEL"]
    settings.glm_reviewer_model = values["GLM_REVIEWER_MODEL"]
    settings.glm_director_model = values["GLM_DIRECTOR_MODEL"]
    settings.glm_temperature = float(values["GLM_TEMPERATURE"])
    settings.glm_max_tokens = int(values["GLM_MAX_TOKENS"])
    settings.glm_enable_thinking = values["GLM_ENABLE_THINKING"] == "true"
    settings.glm_proxy_url = values["GLM_PROXY_URL"]
    settings.glm_token_budget = int(values["GLM_TOKEN_BUDGET"])


def _profile_from_payload(
    payload: ModelProfileSaveRequest,
    profile_id: str,
    previous: dict | None = None,
) -> dict:
    api_key = (
        payload.api_key.strip()
        if payload.api_key and payload.api_key.strip()
        else str((previous or {}).get("api_key") or "").strip()
    )
    if not api_key:
        raise HTTPException(status_code=400, detail="新模型配置必须填写 API Key")
    return {
        "id": profile_id,
        "name": payload.name.strip(),
        "api_key": api_key,
        "base_url": _normalize_base_url(payload.base_url),
        "title_model": payload.title_model.strip(),
        "expert_model": payload.expert_model.strip(),
        "writer_model": payload.writer_model.strip(),
        "reviewer_model": payload.reviewer_model.strip(),
        "director_model": payload.director_model.strip(),
        "temperature": payload.temperature,
        "max_tokens": payload.max_tokens,
        "enable_thinking": payload.enable_thinking,
        "proxy_url": payload.proxy_url.strip(),
        "token_budget": payload.token_budget,
    }


def _sync_active_profile(payload: ModelSettingsUpdate) -> None:
    profiles = _load_profiles()
    active_id = _active_profile_id(profiles)
    for profile in profiles:
        if str(profile["id"]) != active_id:
            continue
        profile["api_key"] = settings.glm_api_key
        for field in PROFILE_FIELDS:
            profile[field] = getattr(payload, field)
        profile["base_url"] = _normalize_base_url(payload.base_url)
        break
    _save_profiles(profiles, active_id)


def _response() -> ModelSettingsResponse:
    return ModelSettingsResponse(
        api_key_configured=bool(settings.glm_api_key.strip()),
        api_key_masked=_mask_key(settings.glm_api_key.strip()),
        base_url=settings.glm_base_url,
        title_model=settings.glm_title_model,
        expert_model=settings.glm_expert_model,
        writer_model=settings.glm_writer_model,
        reviewer_model=settings.glm_reviewer_model,
        director_model=settings.glm_director_model,
        temperature=settings.glm_temperature,
        max_tokens=settings.glm_max_tokens,
        enable_thinking=settings.glm_enable_thinking,
        search_engine=settings.glm_search_engine,
        search_count=settings.glm_search_count,
        proxy_url=settings.glm_proxy_url,
        token_budget=settings.glm_token_budget,
        wechat_configured=bool(
            settings.wechat_app_id.strip() and settings.wechat_app_secret.strip()
        ),
        wechat_app_id=settings.wechat_app_id,
        wechat_secret_masked=_mask_key(settings.wechat_app_secret),
        wechat_author=settings.wechat_author,
    )


@router.get("", response_model=ModelSettingsResponse)
def get_settings() -> ModelSettingsResponse:
    return _response()


@router.get("/profiles", response_model=ModelProfileListResponse)
def list_model_profiles() -> ModelProfileListResponse:
    return _profiles_response()


@router.post("/profiles", response_model=ModelProfileListResponse)
def create_model_profile(payload: ModelProfileSaveRequest) -> ModelProfileListResponse:
    profiles = _load_profiles()
    profile = _profile_from_payload(payload, uuid4().hex)
    profiles.append(profile)
    _apply_profile(profile)
    _save_profiles(profiles, profile["id"])
    return _profiles_response()


@router.put("/profiles/{profile_id}", response_model=ModelProfileListResponse)
def update_model_profile(
    profile_id: str,
    payload: ModelProfileSaveRequest,
) -> ModelProfileListResponse:
    profiles = _load_profiles()
    for index, profile in enumerate(profiles):
        if str(profile["id"]) == profile_id:
            profiles[index] = _profile_from_payload(payload, profile_id, profile)
            _apply_profile(profiles[index])
            _save_profiles(profiles, profile_id)
            return _profiles_response()
    raise HTTPException(status_code=404, detail="模型配置不存在")


@router.post(
    "/profiles/{profile_id}/activate",
    response_model=ModelSettingsResponse,
)
def activate_model_profile(profile_id: str) -> ModelSettingsResponse:
    profiles = _load_profiles()
    profile = next(
        (item for item in profiles if str(item["id"]) == profile_id),
        None,
    )
    if not profile:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    if not str(profile.get("api_key") or "").strip():
        raise HTTPException(status_code=400, detail="该模型配置尚未保存 API Key")
    _apply_profile(profile)
    _save_profiles(profiles, profile_id)
    return _response()


@router.put("", response_model=ModelSettingsResponse)
def update_settings(payload: ModelSettingsUpdate) -> ModelSettingsResponse:
    values = {
        "GLM_BASE_URL": _normalize_base_url(payload.base_url),
        "GLM_TITLE_MODEL": payload.title_model,
        "GLM_EXPERT_MODEL": payload.expert_model,
        "GLM_WRITER_MODEL": payload.writer_model,
        "GLM_REVIEWER_MODEL": payload.reviewer_model,
        "GLM_DIRECTOR_MODEL": payload.director_model,
        "GLM_MODEL": payload.writer_model,
        "GLM_TEMPERATURE": str(payload.temperature),
        "GLM_MAX_TOKENS": str(payload.max_tokens),
        "GLM_ENABLE_THINKING": str(payload.enable_thinking).lower(),
        "GLM_SEARCH_ENGINE": payload.search_engine,
        "GLM_SEARCH_COUNT": str(payload.search_count),
        "GLM_PROXY_URL": payload.proxy_url.strip(),
        "GLM_TOKEN_BUDGET": str(payload.token_budget),
        "WECHAT_APP_ID": payload.wechat_app_id.strip(),
        "WECHAT_AUTHOR": payload.wechat_author.strip(),
    }
    if payload.api_key and payload.api_key.strip():
        values["GLM_API_KEY"] = payload.api_key.strip()
    if payload.wechat_app_secret and payload.wechat_app_secret.strip():
        values["WECHAT_APP_SECRET"] = payload.wechat_app_secret.strip()

    for key, value in values.items():
        set_key(str(ENV_FILE), key, value, quote_mode="never")

    if "GLM_API_KEY" in values:
        settings.glm_api_key = values["GLM_API_KEY"]
    settings.glm_base_url = values["GLM_BASE_URL"]
    settings.glm_model = values["GLM_MODEL"]
    settings.glm_title_model = values["GLM_TITLE_MODEL"]
    settings.glm_expert_model = values["GLM_EXPERT_MODEL"]
    settings.glm_writer_model = values["GLM_WRITER_MODEL"]
    settings.glm_reviewer_model = values["GLM_REVIEWER_MODEL"]
    settings.glm_director_model = values["GLM_DIRECTOR_MODEL"]
    settings.glm_temperature = payload.temperature
    settings.glm_max_tokens = payload.max_tokens
    settings.glm_enable_thinking = payload.enable_thinking
    settings.glm_search_engine = payload.search_engine
    settings.glm_search_count = payload.search_count
    settings.glm_proxy_url = payload.proxy_url.strip()
    settings.glm_token_budget = payload.token_budget
    settings.wechat_app_id = payload.wechat_app_id.strip()
    settings.wechat_author = payload.wechat_author.strip()
    if "WECHAT_APP_SECRET" in values:
        settings.wechat_app_secret = values["WECHAT_APP_SECRET"]
    _sync_active_profile(payload)
    return _response()


@router.post("/test", response_model=ConnectionTestResponse)
async def test_connection(
    payload: ModelSettingsUpdate | None = None,
) -> ConnectionTestResponse:
    api_key = (
        payload.api_key.strip()
        if payload and payload.api_key and payload.api_key.strip()
        else settings.glm_api_key.strip()
    )
    base_url = _normalize_base_url(
        payload.base_url if payload else settings.glm_base_url
    )
    proxy_url = payload.proxy_url.strip() if payload else settings.glm_proxy_url
    models = list(
        dict.fromkeys(
            [
                payload.title_model if payload else settings.glm_title_model,
                payload.expert_model if payload else settings.glm_expert_model,
                payload.writer_model if payload else settings.glm_writer_model,
                payload.reviewer_model if payload else settings.glm_reviewer_model,
                payload.director_model if payload else settings.glm_director_model,
            ]
        )
    )
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写并保存 API Key")

    try:
        async with httpx.AsyncClient(
            timeout=45,
            proxy=proxy_url or None,
        ) as client:
            for model in models:
                request_body = {
                    "model": model,
                    "messages": [{"role": "user", "content": "只回复：OK"}],
                }
                normalized_model = model.strip().lower()
                if (
                    "bigmodel.cn" not in base_url.lower()
                    and normalized_model.startswith(("gpt-5", "o1", "o3", "o4"))
                ):
                    request_body["max_completion_tokens"] = 16
                else:
                    request_body["max_tokens"] = 16
                    request_body["temperature"] = 0
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=request_body,
                )
                if response.is_error:
                    if response.status_code == 401:
                        raise HTTPException(
                            status_code=502,
                            detail=(
                                "模型服务身份验证失败：当前填写的 API Key 无效、"
                                "已停用或复制不完整。"
                            ),
                        )
                    raise HTTPException(
                        status_code=502,
                        detail=(
                            f"模型 {model} 连接失败（{response.status_code}）："
                            f"{response.text[:300]}"
                        ),
                    )
                response_data = response.json()
                usage = response_data.get("usage") or {}
                record_token_usage(
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    total_tokens=int(usage.get("total_tokens") or 0),
                )
    except HTTPException:
        raise
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"无法连接当前填写的模型服务（{type(exc).__name__}）：{exc}",
        ) from exc
    return ConnectionTestResponse(
        ok=True,
        message=f"当前填写配置有效，已验证：{'、'.join(models)}",
    )


@router.post("/test-wechat", response_model=ConnectionTestResponse)
async def test_wechat_connection(
    payload: WechatConnectionTestRequest | None = None,
) -> ConnectionTestResponse:
    app_id = (
        payload.app_id.strip()
        if payload and payload.app_id.strip()
        else settings.wechat_app_id.strip()
    )
    app_secret = (
        payload.app_secret.strip()
        if payload and payload.app_secret and payload.app_secret.strip()
        else settings.wechat_app_secret.strip()
    )
    try:
        await get_wechat_access_token(app_id, app_secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ConnectionTestResponse(
        ok=True,
        message="微信公众号配置有效，已成功获取 access_token。",
    )
