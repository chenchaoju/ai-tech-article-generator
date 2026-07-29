import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.image_asset import ImageAsset
from app.models.image_asset_category import ImageAssetCategory
from app.schemas.media import (
    ImageAssetCategoryCreate,
    ImageAssetCategoryReorder,
    ImageAssetCategoryResponse,
    ImageAssetCategoryUpdate,
    ImageAssetCreate,
    ImageAssetReorder,
    ImageAssetResponse,
    ImageAssetUpdate,
    ImageSearchRequest,
    ImageSearchResponse,
)
from app.services.image_search import search_images as search_image_provider


router = APIRouter(prefix="/media", tags=["media"])


@router.post("/search", response_model=ImageSearchResponse)
async def search_images(payload: ImageSearchRequest) -> ImageSearchResponse:
    try:
        results = await search_image_provider(
            payload.query.strip(),
            engine=payload.engine,
            page=payload.page,
            count=payload.count,
            exclude_urls=payload.exclude_urls,
            prefer_clean=payload.prefer_clean,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="图片搜索服务暂时无法访问，请稍后重试。",
        ) from exc
    return ImageSearchResponse(
        query=payload.query,
        page=payload.page,
        engine=payload.engine,
        items=results,
        has_more=len(results) >= payload.count,
    )


@router.get(
    "/categories",
    response_model=list[ImageAssetCategoryResponse],
)
def list_image_asset_categories(
    db: Session = Depends(get_db),
) -> list[ImageAssetCategory]:
    return list(
        db.scalars(
            select(ImageAssetCategory).order_by(
                ImageAssetCategory.sort_order.asc(),
                ImageAssetCategory.id.asc(),
            )
        ).all()
    )


@router.post(
    "/categories",
    response_model=ImageAssetCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_image_asset_category(
    payload: ImageAssetCategoryCreate,
    db: Session = Depends(get_db),
) -> ImageAssetCategory:
    name = payload.name.strip()
    if db.scalar(select(ImageAssetCategory).where(ImageAssetCategory.name == name)):
        raise HTTPException(status_code=409, detail="分类名称已经存在")
    next_order = int(
        db.scalar(
            select(func.coalesce(func.max(ImageAssetCategory.sort_order), 0))
        )
        or 0
    ) + 1
    category = ImageAssetCategory(name=name, sort_order=next_order)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.patch(
    "/categories/{category_id}",
    response_model=ImageAssetCategoryResponse,
)
def update_image_asset_category(
    category_id: int,
    payload: ImageAssetCategoryUpdate,
    db: Session = Depends(get_db),
) -> ImageAssetCategory:
    category = db.get(ImageAssetCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="素材分类不存在")
    if category.name == "未分类":
        raise HTTPException(status_code=400, detail="“未分类”是系统分类，不能重命名")
    new_name = payload.name.strip()
    duplicate = db.scalar(
        select(ImageAssetCategory).where(
            ImageAssetCategory.name == new_name,
            ImageAssetCategory.id != category_id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="分类名称已经存在")
    old_name = category.name
    category.name = new_name
    db.execute(
        update(ImageAsset)
        .where(ImageAsset.category == old_name)
        .values(category=new_name)
    )
    db.commit()
    db.refresh(category)
    return category


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image_asset_category(
    category_id: int,
    db: Session = Depends(get_db),
) -> None:
    category = db.get(ImageAssetCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="素材分类不存在")
    if category.name == "未分类":
        raise HTTPException(status_code=400, detail="“未分类”是系统分类，不能删除")
    db.execute(delete(ImageAsset).where(ImageAsset.category == category.name))
    db.delete(category)
    db.commit()


@router.post(
    "/categories/reorder",
    response_model=list[ImageAssetCategoryResponse],
)
def reorder_image_asset_categories(
    payload: ImageAssetCategoryReorder,
    db: Session = Depends(get_db),
) -> list[ImageAssetCategory]:
    categories = list(
        db.scalars(
            select(ImageAssetCategory).where(
                ImageAssetCategory.id.in_(payload.ordered_ids)
            )
        ).all()
    )
    category_by_id = {category.id: category for category in categories}
    if len(category_by_id) != len(set(payload.ordered_ids)):
        raise HTTPException(status_code=400, detail="排序列表包含不存在的分类")
    for index, category_id in enumerate(payload.ordered_ids):
        category_by_id[category_id].sort_order = index
    db.commit()
    return list(
        db.scalars(
            select(ImageAssetCategory).order_by(
                ImageAssetCategory.sort_order.asc(),
                ImageAssetCategory.id.asc(),
            )
        ).all()
    )


@router.get("/assets", response_model=list[ImageAssetResponse])
def list_image_assets(db: Session = Depends(get_db)) -> list[ImageAsset]:
    return list(
        db.scalars(
            select(ImageAsset)
            .order_by(ImageAsset.sort_order.asc(), ImageAsset.id.asc())
            .limit(500)
        ).all()
    )


@router.post(
    "/assets",
    response_model=ImageAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_image_asset(
    payload: ImageAssetCreate,
    db: Session = Depends(get_db),
) -> ImageAsset:
    image_url = str(payload.image_url)
    category_name = payload.category.strip() or "未分类"
    if not db.scalar(
        select(ImageAssetCategory).where(ImageAssetCategory.name == category_name)
    ):
        raise HTTPException(status_code=400, detail="请选择已经创建的素材分类")
    existing = db.scalar(
        select(ImageAsset).where(ImageAsset.image_url == image_url)
    )
    if existing:
        return existing
    next_order = int(
        db.scalar(select(func.coalesce(func.max(ImageAsset.sort_order), 0))) or 0
    ) + 1
    asset = ImageAsset(
        title=payload.title.strip() or "图片素材",
        image_url=image_url,
        source_page_url=payload.source_page_url.strip(),
        source_name=payload.source_name.strip(),
        category=category_name,
        sort_order=next_order,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/assets/{asset_id}", response_model=ImageAssetResponse)
def update_image_asset(
    asset_id: int,
    payload: ImageAssetUpdate,
    db: Session = Depends(get_db),
) -> ImageAsset:
    asset = db.get(ImageAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="图片素材不存在")
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes:
        asset.title = changes["title"].strip()
    if "category" in changes:
        category_name = changes["category"].strip() or "未分类"
        if not db.scalar(
            select(ImageAssetCategory).where(
                ImageAssetCategory.name == category_name
            )
        ):
            raise HTTPException(status_code=400, detail="请选择已经创建的素材分类")
        asset.category = category_name
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/assets/reorder", response_model=list[ImageAssetResponse])
def reorder_image_assets(
    payload: ImageAssetReorder,
    db: Session = Depends(get_db),
) -> list[ImageAsset]:
    assets = list(
        db.scalars(
            select(ImageAsset).where(ImageAsset.id.in_(payload.ordered_ids))
        ).all()
    )
    asset_by_id = {asset.id: asset for asset in assets}
    if len(asset_by_id) != len(set(payload.ordered_ids)):
        raise HTTPException(status_code=400, detail="排序列表包含不存在的素材")
    for index, asset_id in enumerate(payload.ordered_ids, start=1):
        asset_by_id[asset_id].sort_order = index
    db.commit()
    return list(
        db.scalars(
            select(ImageAsset)
            .order_by(ImageAsset.sort_order.asc(), ImageAsset.id.asc())
            .limit(500)
        ).all()
    )


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image_asset(
    asset_id: int,
    db: Session = Depends(get_db),
) -> None:
    asset = db.get(ImageAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="图片素材不存在")
    db.delete(asset)
    db.commit()
