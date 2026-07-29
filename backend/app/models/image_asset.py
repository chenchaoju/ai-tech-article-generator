from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ImageAsset(Base):
    __tablename__ = "image_assets"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="图片素材")
    image_url: Mapped[str] = mapped_column(Text, unique=True, index=True)
    source_page_url: Mapped[str] = mapped_column(Text, default="")
    source_name: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(100), default="未分类", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
