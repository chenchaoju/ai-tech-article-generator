from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class ResearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    exclude_urls: list[str] = Field(default_factory=list, max_length=100)
    count: int = Field(default=10, ge=5, le=20)
    source_domain: str = Field(default="", max_length=255)
    source_name: str = Field(default="", max_length=100)
    title_only: bool = True
    broad_search: bool = False
    date_range: Literal["all", "7d", "30d", "1y"] = "all"
    sort_order: Literal["newest", "oldest"] = "newest"


class ResearchResult(BaseModel):
    title: str
    url: str
    summary: str = ""
    source_content: str = ""
    source: str = ""
    publish_date: str = ""
    date_type: str = "发布日期"
    word_count: int = 0


class ResearchContentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    url: HttpUrl
    summary: str = Field(default="", max_length=4000)
    source: str = Field(default="", max_length=200)
    publish_date: str = Field(default="", max_length=50)
    date_type: str = Field(default="发布日期", max_length=50)
    word_count: int = Field(default=0, ge=0)


class ResearchResponse(BaseModel):
    query: str
    items: list[ResearchResult]
    has_more: bool = True


class TitleSuggestionRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    article_type: str = Field(default="技术", max_length=64)
    custom_type_description: str = Field(default="", max_length=1000)
    writing_style: str = Field(default="温暖同行", max_length=64)
    layout_style: str = Field(default="跟随原文", max_length=64)
    excluded_titles: list[str] = Field(default_factory=list, max_length=100)
    source_titles: list[str] = Field(default_factory=list, max_length=20)


class TitleSuggestionResponse(BaseModel):
    titles: list[str]
