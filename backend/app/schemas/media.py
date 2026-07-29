from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ImageSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    count: int = Field(default=10, ge=1, le=20)
    page: int = Field(default=1, ge=1, le=100)
    exclude_urls: list[str] = Field(default_factory=list, max_length=500)
    engine: Literal["bing", "360", "baidu", "sohu"] = "bing"
    prefer_clean: bool = True


class ImageSearchItem(BaseModel):
    title: str
    image_url: str
    source_page_url: str = ""
    source_name: str = ""


class ImageSearchResponse(BaseModel):
    query: str
    page: int
    engine: str
    items: list[ImageSearchItem]
    has_more: bool = True


class ImageAssetCreate(BaseModel):
    title: str = Field(default="图片素材", max_length=255)
    image_url: HttpUrl
    source_page_url: str = Field(default="", max_length=2000)
    source_name: str = Field(default="", max_length=255)
    category: str = Field(default="未分类", min_length=1, max_length=100)


class ImageAssetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=100)


class ImageAssetReorder(BaseModel):
    ordered_ids: list[int] = Field(min_length=1, max_length=500)


class ImageAssetCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ImageAssetCategoryUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ImageAssetCategoryReorder(BaseModel):
    ordered_ids: list[int] = Field(min_length=1, max_length=100)


class ImageAssetCategoryResponse(BaseModel):
    id: int
    name: str
    sort_order: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ImageAssetResponse(BaseModel):
    id: int
    title: str
    image_url: str
    source_page_url: str
    source_name: str
    category: str
    sort_order: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
