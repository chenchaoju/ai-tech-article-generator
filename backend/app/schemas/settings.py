from pydantic import BaseModel, Field


class ModelSettingsResponse(BaseModel):
    api_key_configured: bool
    api_key_masked: str
    base_url: str
    title_model: str
    expert_model: str
    writer_model: str
    reviewer_model: str
    director_model: str
    temperature: float
    max_tokens: int
    enable_thinking: bool
    search_engine: str
    search_count: int
    proxy_url: str
    token_budget: int = 0
    wechat_configured: bool = False
    wechat_app_id: str = ""
    wechat_secret_masked: str = ""
    wechat_author: str = ""


class ModelProfileResponse(BaseModel):
    id: str
    name: str
    api_key_configured: bool
    api_key_masked: str
    base_url: str
    title_model: str
    expert_model: str
    writer_model: str
    reviewer_model: str
    director_model: str
    temperature: float
    max_tokens: int
    enable_thinking: bool
    proxy_url: str
    token_budget: int = 0
    active: bool = False


class ModelProfileListResponse(BaseModel):
    active_profile_id: str
    profiles: list[ModelProfileResponse]


class ModelProfileSaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str = Field(min_length=8, max_length=500)
    title_model: str = Field(min_length=1, max_length=100)
    expert_model: str = Field(min_length=1, max_length=100)
    writer_model: str = Field(min_length=1, max_length=100)
    reviewer_model: str = Field(min_length=1, max_length=100)
    director_model: str = Field(min_length=1, max_length=100)
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=1024, le=50000)
    enable_thinking: bool = False
    proxy_url: str = Field(default="", max_length=500)
    token_budget: int = Field(default=0, ge=0, le=1_000_000_000_000)


class ModelSettingsUpdate(BaseModel):
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str = Field(min_length=8, max_length=500)
    title_model: str = Field(default="glm-4-flash-250414", min_length=1, max_length=100)
    expert_model: str = Field(default="glm-4.6", min_length=1, max_length=100)
    writer_model: str = Field(min_length=1, max_length=100)
    reviewer_model: str = Field(min_length=1, max_length=100)
    director_model: str = Field(default="glm-4.6", min_length=1, max_length=100)
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(ge=1024, le=50000)
    enable_thinking: bool = False
    search_engine: str = Field(default="search_std", max_length=100)
    search_count: int = Field(default=8, ge=3, le=20)
    proxy_url: str = Field(default="", max_length=500)
    token_budget: int = Field(default=0, ge=0, le=1_000_000_000_000)
    wechat_app_id: str = Field(default="", max_length=100)
    wechat_app_secret: str | None = Field(default=None, max_length=500)
    wechat_author: str = Field(default="", max_length=64)


class ConnectionTestResponse(BaseModel):
    ok: bool
    message: str


class WechatConnectionTestRequest(BaseModel):
    app_id: str = Field(default="", max_length=100)
    app_secret: str | None = Field(default=None, max_length=500)
