from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ArticleBase(BaseModel):
    title: str = Field(default="未命名文章", max_length=255)
    topic: str = Field(min_length=1, max_length=255)
    article_type: str = Field(default="技术", max_length=64)
    custom_type_description: str = Field(default="", max_length=1000)
    writing_style: str = Field(default="温暖同行", max_length=64)
    layout_style: str = Field(default="跟随原文", max_length=64)
    target_word_count: int = Field(default=1500, ge=200, le=5000)
    target_platform: str = Field(default="微信公众号", max_length=100)
    custom_platform: str = Field(default="", max_length=500)
    project_background: str = ""
    problems: str = ""
    solution_process: str = ""
    author_voice: str = ""
    code_snippets: str = ""
    reference_materials: str = ""
    content: str = ""
    status: str = "draft"
    selected_sources: list[dict] = Field(default_factory=list)
    include_source_images: bool = False
    manual_images: list[dict] = Field(default_factory=list)
    review_notes: str = ""
    publish_records: list[dict] = Field(default_factory=list)


class ArticleCreate(ArticleBase):
    pass


class ArticleUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    topic: str | None = Field(default=None, min_length=1, max_length=255)
    article_type: str | None = Field(default=None, max_length=64)
    custom_type_description: str | None = Field(default=None, max_length=1000)
    writing_style: str | None = Field(default=None, max_length=64)
    layout_style: str | None = Field(default=None, max_length=64)
    target_word_count: int | None = Field(default=None, ge=200, le=5000)
    target_platform: str | None = Field(default=None, max_length=100)
    custom_platform: str | None = Field(default=None, max_length=500)
    project_background: str | None = None
    problems: str | None = None
    solution_process: str | None = None
    author_voice: str | None = None
    code_snippets: str | None = None
    reference_materials: str | None = None
    content: str | None = None
    status: str | None = None
    selected_sources: list[dict] | None = None
    include_source_images: bool | None = None
    manual_images: list[dict] | None = None
    review_notes: str | None = None
    publish_records: list[dict] | None = None


class ArticleResponse(ArticleBase):
    id: int
    model_name: str | None = None
    reviewer_model_name: str | None = None
    director_review_summary: str = ""
    director_review_changes: list[dict] = Field(default_factory=list)
    director_reviewed_at: datetime | None = None
    director_model_name: str | None = None
    generated_word_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArticleListItem(BaseModel):
    id: int
    title: str
    topic: str
    status: str
    content: str
    generated_word_count: int = 0
    total_tokens: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArticleListResponse(BaseModel):
    items: list[ArticleListItem]
    total: int
    page: int
    page_size: int


class GenerateResponse(BaseModel):
    article: ArticleResponse
    message: str
    review_notes: str = ""


class GenerationStartResponse(BaseModel):
    article_id: int
    status: str
    message: str


class DirectorReviewResponse(BaseModel):
    article: ArticleResponse
    message: str
    changes: list[dict] = Field(default_factory=list)


class WechatPublishResponse(BaseModel):
    article: ArticleResponse
    message: str
    draft_media_id: str
    publish_id: str = ""
    uploaded_image_count: int = 0
    status: str


class ScheduledPublishCreate(BaseModel):
    scheduled_at: datetime
    platform: str = Field(default="wechat", pattern="^wechat$")


class ScheduledPublishResponse(BaseModel):
    id: int
    article_id: int
    platform: str
    scheduled_at: datetime
    status: str
    attempt_count: int = 0
    last_error: str = ""
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenUsageArticleItem(BaseModel):
    id: int
    title: str
    topic: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenUsageStatsResponse(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    request_count: int
    average_tokens_per_request: int
    article_count: int
    generated_article_count: int
    director_review_count: int
    initialized_at: datetime
    updated_at: datetime
    provider_balance_supported: bool = False
    configured_token_budget: int = 0
    estimated_remaining_tokens: int | None = None
    provider_console_url: str
    balance_note: str
    recent_articles: list[TokenUsageArticleItem]
    scope_note: str
