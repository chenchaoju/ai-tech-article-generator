import asyncio
from contextlib import suppress
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.db.session import SessionLocal
from app.models.article import Article
from app.models.scheduled_publish import ScheduledPublish
from app.services.wechat import publish_article_to_wechat


SCHEDULER_INTERVAL_SECONDS = 20


def apply_wechat_publish_result(
    article: Article,
    result: dict,
    submitted_at: datetime,
    schedule_id: int | None = None,
) -> None:
    records = [
        record
        for record in list(article.publish_records or [])
        if isinstance(record, dict) and record.get("platform") != "wechat"
    ]
    record = {
        "platform": "wechat",
        "platform_name": "微信公众号",
        "status": result["status"],
        "submitted_at": submitted_at.isoformat(),
        "draft_media_id": result["draft_media_id"],
        "publish_id": result["publish_id"],
        "uploaded_image_count": result["uploaded_image_count"],
    }
    if schedule_id is not None:
        record["schedule_id"] = schedule_id
        record["scheduled_publish"] = True
    records.append(record)
    article.publish_records = records
    article.status = "published"


async def process_scheduled_publish(schedule_id: int) -> None:
    with SessionLocal() as db:
        claimed = db.execute(
            update(ScheduledPublish)
            .where(
                ScheduledPublish.id == schedule_id,
                ScheduledPublish.status == "pending",
            )
            .values(
                status="processing",
                attempt_count=ScheduledPublish.attempt_count + 1,
                last_error="",
            )
            .returning(ScheduledPublish.article_id)
        ).first()
        if not claimed:
            return
        db.commit()
        article_id = claimed[0]
        article = db.get(Article, article_id)
        if not article:
            schedule = db.get(ScheduledPublish, schedule_id)
            schedule.status = "failed"
            schedule.last_error = "关联文章不存在"
            db.commit()
            return

    try:
        with SessionLocal() as db:
            article = db.get(Article, article_id)
            if not article:
                raise ValueError("关联文章不存在")
            result = await publish_article_to_wechat(article)

        completed_at = datetime.now(timezone.utc)
        with SessionLocal() as db:
            schedule = db.get(ScheduledPublish, schedule_id)
            article = db.get(Article, article_id)
            if not schedule or not article:
                return
            apply_wechat_publish_result(article, result, completed_at, schedule.id)
            schedule.status = "published"
            schedule.published_at = completed_at
            schedule.last_error = ""
            db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            schedule = db.get(ScheduledPublish, schedule_id)
            if not schedule:
                return
            schedule.status = "failed"
            schedule.last_error = str(exc)[:2000]
            db.commit()


async def run_due_scheduled_publishes() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        due_ids = list(
            db.scalars(
                select(ScheduledPublish.id)
                .where(
                    ScheduledPublish.status == "pending",
                    ScheduledPublish.scheduled_at <= now,
                )
                .order_by(ScheduledPublish.scheduled_at.asc())
                .limit(5)
            ).all()
        )
    for schedule_id in due_ids:
        await process_scheduled_publish(schedule_id)


async def scheduled_publish_loop() -> None:
    with SessionLocal() as db:
        db.execute(
            update(ScheduledPublish)
            .where(ScheduledPublish.status == "processing")
            .values(status="pending", last_error="服务重启后自动恢复任务")
        )
        db.commit()

    while True:
        await run_due_scheduled_publishes()
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


async def stop_scheduler(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
