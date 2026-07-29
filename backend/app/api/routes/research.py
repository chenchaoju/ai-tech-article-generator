from fastapi import APIRouter, HTTPException

from app.schemas.research import (
    ResearchContentRequest,
    ResearchRequest,
    ResearchResult,
    ResearchResponse,
    TitleSuggestionRequest,
    TitleSuggestionResponse,
)
from app.services.glm import fetch_source_content, search_web, suggest_titles


router = APIRouter(prefix="/research", tags=["research"])


@router.post("/search", response_model=ResearchResponse)
async def research_topic(payload: ResearchRequest) -> ResearchResponse:
    try:
        items = await search_web(
            payload.query,
            exclude_urls=payload.exclude_urls,
            count=payload.count,
            source_domain=payload.source_domain,
            source_name=payload.source_name,
            title_only=payload.title_only,
            broad_search=payload.broad_search,
            include_images=False,
            date_range=payload.date_range,
            sort_order=payload.sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ResearchResponse(
        query=payload.query,
        items=items,
        has_more=len(items) >= 5,
    )


@router.post("/content", response_model=ResearchResult)
async def read_selected_article(payload: ResearchContentRequest) -> ResearchResult:
    try:
        item = await fetch_source_content(
            {
                **payload.model_dump(mode="json"),
                "url": str(payload.url),
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ResearchResult(**item)


@router.post("/titles", response_model=TitleSuggestionResponse)
async def create_title_suggestions(
    payload: TitleSuggestionRequest,
) -> TitleSuggestionResponse:
    try:
        titles = await suggest_titles(
            topic=payload.topic,
            article_type=payload.article_type,
            custom_type_description=payload.custom_type_description,
            writing_style=payload.writing_style,
            layout_style=payload.layout_style,
            excluded_titles=payload.excluded_titles,
            source_titles=payload.source_titles,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return TitleSuggestionResponse(titles=titles)
