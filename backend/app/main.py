import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.articles import router as articles_router
from app.api.routes.media import router as media_router
from app.api.routes.research import router as research_router
from app.api.routes.settings import router as settings_router
from app.core.config import settings
from app.db.session import create_tables
from app.services.scheduled_publish import scheduled_publish_loop, stop_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    scheduler_task = asyncio.create_task(scheduled_publish_loop())
    try:
        yield
    finally:
        await stop_scheduler(scheduler_task)


base_path = f"/{settings.app_base_path.strip('/')}" if settings.app_base_path.strip("/") else ""
api_prefix = f"{base_path}/api"


app = FastAPI(
    title=settings.app_name,
    description="基于 GLM-4.6 的中文文章生成与草稿管理 API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=f"{api_prefix}/docs",
    redoc_url=f"{api_prefix}/redoc",
    openapi_url=f"{api_prefix}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(articles_router, prefix=api_prefix)
app.include_router(media_router, prefix=api_prefix)
app.include_router(research_router, prefix=api_prefix)
app.include_router(settings_router, prefix=api_prefix)


@app.get(f"{api_prefix}/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
