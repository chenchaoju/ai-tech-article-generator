from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    from app.models.article import Article  # noqa: F401
    from app.models.image_asset import ImageAsset  # noqa: F401
    from app.models.image_asset_category import ImageAssetCategory  # noqa: F401
    from app.models.scheduled_publish import ScheduledPublish  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # create_all does not add columns to an existing table. These idempotent
    # statements keep the first-version database compatible with new workflows.
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS model_usage_totals (
                    id INTEGER PRIMARY KEY,
                    prompt_tokens BIGINT NOT NULL DEFAULT 0,
                    completion_tokens BIGINT NOT NULL DEFAULT 0,
                    total_tokens BIGINT NOT NULL DEFAULT 0,
                    request_count BIGINT NOT NULL DEFAULT 0,
                    initialized_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT model_usage_totals_singleton CHECK (id = 1)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO model_usage_totals (
                    id, prompt_tokens, completion_tokens, total_tokens, request_count
                )
                SELECT
                    1,
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(completion_tokens), 0),
                    COALESCE(SUM(total_tokens), 0),
                    COUNT(*) FILTER (WHERE total_tokens > 0)
                FROM articles
                WHERE NOT EXISTS (
                    SELECT 1 FROM model_usage_totals WHERE id = 1
                )
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "reviewer_model_name VARCHAR(64)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE image_assets ADD COLUMN IF NOT EXISTS "
                "category VARCHAR(100) NOT NULL DEFAULT '未分类'"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE image_assets ADD COLUMN IF NOT EXISTS "
                "sort_order INTEGER NOT NULL DEFAULT 0"
            )
        )
        connection.execute(
            text(
                "UPDATE image_assets SET sort_order = id "
                "WHERE sort_order = 0"
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO image_asset_categories (name, sort_order)
                VALUES ('未分类', 0)
                ON CONFLICT (name) DO NOTHING
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO image_asset_categories (name, sort_order)
                SELECT DISTINCT category, ROW_NUMBER() OVER (ORDER BY category)
                FROM image_assets
                WHERE category <> '' AND category <> '未分类'
                ON CONFLICT (name) DO NOTHING
                """
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "selected_sources JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "include_source_images BOOLEAN NOT NULL DEFAULT TRUE"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "manual_images JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "review_notes TEXT NOT NULL DEFAULT ''"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "director_review_summary TEXT NOT NULL DEFAULT ''"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "director_review_changes JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "director_reviewed_at TIMESTAMPTZ"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "director_model_name VARCHAR(64)"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "publish_records JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "author_voice TEXT NOT NULL DEFAULT ''"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "article_type VARCHAR(64) NOT NULL DEFAULT '技术'"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "custom_type_description TEXT NOT NULL DEFAULT ''"
            )
        )
        connection.execute(
            text("ALTER TABLE articles ALTER COLUMN article_type SET DEFAULT '技术'")
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "writing_style VARCHAR(64) NOT NULL DEFAULT '温暖同行'"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "layout_style VARCHAR(64) NOT NULL DEFAULT '跟随原文'"
            )
        )
        connection.execute(
            text("ALTER TABLE articles ALTER COLUMN layout_style SET DEFAULT '跟随原文'")
        )
        connection.execute(
            text(
                "UPDATE articles SET layout_style = '跟随原文' "
                "WHERE layout_style <> '跟随原文'"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "target_word_count INTEGER NOT NULL DEFAULT 1500"
            )
        )
        connection.execute(
            text("ALTER TABLE articles ALTER COLUMN target_word_count SET DEFAULT 1500")
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "target_platform VARCHAR(100) NOT NULL DEFAULT '微信公众号'"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "custom_platform TEXT NOT NULL DEFAULT ''"
            )
        )
        connection.execute(
            text(
                "UPDATE articles SET target_word_count = 200 "
                "WHERE target_word_count < 200"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "generated_word_count INTEGER NOT NULL DEFAULT 0"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "prompt_tokens INTEGER NOT NULL DEFAULT 0"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "completion_tokens INTEGER NOT NULL DEFAULT 0"
            )
        )
        connection.execute(
            text(
                "ALTER TABLE articles ADD COLUMN IF NOT EXISTS "
                "total_tokens INTEGER NOT NULL DEFAULT 0"
            )
        )
        connection.execute(
            text(
                "UPDATE articles SET generated_word_count = "
                "CHAR_LENGTH(REGEXP_REPLACE(content, '\\s', '', 'g')) "
                "WHERE generated_word_count = 0 AND content <> ''"
            )
        )


def record_token_usage(
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    total = max(0, int(total_tokens or prompt + completion))
    if not total and not prompt and not completion:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE model_usage_totals
                SET prompt_tokens = prompt_tokens + :prompt,
                    completion_tokens = completion_tokens + :completion,
                    total_tokens = total_tokens + :total,
                    request_count = request_count + 1,
                    updated_at = NOW()
                WHERE id = 1
                """
            ),
            {
                "prompt": prompt,
                "completion": completion,
                "total": total,
            },
        )


def get_token_usage_totals() -> dict[str, object]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT prompt_tokens, completion_tokens, total_tokens,
                       request_count, initialized_at, updated_at
                FROM model_usage_totals
                WHERE id = 1
                """
            )
        ).mappings().one()
    return dict(row)
