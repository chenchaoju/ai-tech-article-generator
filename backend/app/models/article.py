from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="未命名文章")
    topic: Mapped[str] = mapped_column(String(255), index=True)
    article_type: Mapped[str] = mapped_column(String(64), default="技术")
    custom_type_description: Mapped[str] = mapped_column(Text, default="")
    writing_style: Mapped[str] = mapped_column(
        Text,
        default="保留原文主题和观点，用更自然、更有人情味的方式重新叙述",
    )
    layout_style: Mapped[str] = mapped_column(String(64), default="跟随原文")
    target_word_count: Mapped[int] = mapped_column(Integer, default=1500)
    target_platform: Mapped[str] = mapped_column(
        String(100),
        default="微信公众号",
    )
    custom_platform: Mapped[str] = mapped_column(Text, default="")
    project_background: Mapped[str] = mapped_column(Text, default="")
    problems: Mapped[str] = mapped_column(Text, default="")
    solution_process: Mapped[str] = mapped_column(Text, default="")
    author_voice: Mapped[str] = mapped_column(Text, default="")
    code_snippets: Mapped[str] = mapped_column(Text, default="")
    reference_materials: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewer_model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_sources: Mapped[list[dict]] = mapped_column(JSON, default=list)
    include_source_images: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_images: Mapped[list[dict]] = mapped_column(JSON, default=list)
    review_notes: Mapped[str] = mapped_column(Text, default="")
    director_review_summary: Mapped[str] = mapped_column(Text, default="")
    director_review_changes: Mapped[list[dict]] = mapped_column(JSON, default=list)
    director_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    director_model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    publish_records: Mapped[list[dict]] = mapped_column(JSON, default=list)
    generated_word_count: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
