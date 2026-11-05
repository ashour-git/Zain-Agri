"""Catalog API: units, categories, brands, products, unit conversions."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.session import get_session
from app.modules.auth.dependencies import (
    Principal,
    TenantContext,
    get_current_principal,
    require_permission,
)
from app.modules.authorization.permissions import Permission
from app.modules.catalog import service
from app.modules.catalog.models import ProductStatus
from app.modules.catalog.schemas import (
    BrandCreate,
    BrandOut,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ConversionCreate,
    ConversionOut,
    ProductCreate,
    ProductDetailOut,
    ProductListOut,
    ProductUpdate,
    UnitOut,
)

router = APIRouter(prefix="/api/v1", tags=["catalog"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_current_principal)]

ProductsReader = Annotated[TenantContext, Depends(require_permission(Permission.PRODUCTS_READ))]
ProductsCreator = Annotated[TenantContext, Depends(require_permission(Permission.PRODUCTS_CREATE))]
ProductsUpdater = Annotated[TenantContext, Depends(require_permission(Permission.PRODUCTS_UPDATE))]
ProductsArchiver = Annotated[
    TenantContext, Depends(require_permission(Permission.PRODUCTS_ARCHIVE))
]
TaxonomyManager = Annotated[
    TenantContext, Depends(require_permission(Permission.CATEGORIES_MANAGE))
]

Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/units", response_model=list[UnitOut])
async def list_units(
    context: ProductsReader,
    db: SessionDep,
) -> list[UnitOut]:
    return await service.list_units(db)


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(context: ProductsReader, db: SessionDep) -> list[CategoryOut]:
    return await service.list_categories(db, context.tenant.id)


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    context: TaxonomyManager,
    principal: PrincipalDep,
    db: SessionDep,
) -> CategoryOut:
    return await service.create_category(
        db, context=context, actor_id=principal.user_id, payload=payload
    )


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    context: TaxonomyManager,
    principal: PrincipalDep,
    db: SessionDep,
) -> CategoryOut:
    return await service.update_category(
        db,
        context=context,
        actor_id=principal.user_id,
        category_id=category_id,
        payload=payload,
    )


@router.get("/brands", response_model=list[BrandOut])
async def list_brands(context: ProductsReader, db: SessionDep) -> list[BrandOut]:
    return await service.list_brands(db, context.tenant.id)


@router.post("/brands", response_model=BrandOut, status_code=status.HTTP_201_CREATED)
async def create_brand(
    payload: BrandCreate,
    context: TaxonomyManager,
    principal: PrincipalDep,
    db: SessionDep,
) -> BrandOut:
    return await service.create_brand(
        db, context=context, actor_id=principal.user_id, payload=payload
    )


@router.get("/products", response_model=ProductListOut)
async def list_products(
    context: ProductsReader,
    db: SessionDep,
    page: Page = 1,
    page_size: PageSize = 25,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category_id: uuid.UUID | None = None,
    product_status: Annotated[ProductStatus | None, Query(alias="status")] = None,
) -> ProductListOut:
    return await service.list_products(
        db,
        tenant_id=context.tenant.id,
        page=page,
        page_size=page_size,
        q=q,
        category_id=category_id,
        status=product_status,
        view_cost=context.allows(Permission.INVENTORY_VIEW_COST),
    )


@router.post("/products", response_model=ProductDetailOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    context: ProductsCreator,
    principal: PrincipalDep,
    db: SessionDep,
) -> ProductDetailOut:
    return await service.create_product(
        db, context=context, actor_id=principal.user_id, payload=payload
    )


@router.get("/products/{product_id}", response_model=ProductDetailOut)
async def get_product(
    product_id: uuid.UUID,
    context: ProductsReader,
    db: SessionDep,
) -> ProductDetailOut:
    return await service.get_product(
        db,
        tenant_id=context.tenant.id,
        product_id=product_id,
        view_cost=context.allows(Permission.INVENTORY_VIEW_COST),
    )


@router.patch("/products/{product_id}", response_model=ProductDetailOut)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    context: ProductsUpdater,
    principal: PrincipalDep,
    db: SessionDep,
) -> ProductDetailOut:
    return await service.update_product(
        db,
        context=context,
        actor_id=principal.user_id,
        product_id=product_id,
        payload=payload,
    )


@router.delete("/products/{product_id}", response_model=ProductDetailOut)
async def archive_product(
    product_id: uuid.UUID,
    context: ProductsArchiver,
    principal: PrincipalDep,
    db: SessionDep,
) -> ProductDetailOut:
    """Archive, never delete: movements must keep pointing at the product."""
    return await service.set_product_status(
        db,
        context=context,
        actor_id=principal.user_id,
        product_id=product_id,
        status=ProductStatus.ARCHIVED,
    )


@router.post("/products/{product_id}/restore", response_model=ProductDetailOut)
async def restore_product(
    product_id: uuid.UUID,
    context: ProductsArchiver,
    principal: PrincipalDep,
    db: SessionDep,
) -> ProductDetailOut:
    return await service.set_product_status(
        db,
        context=context,
        actor_id=principal.user_id,
        product_id=product_id,
        status=ProductStatus.ACTIVE,
    )


@router.post(
    "/products/{product_id}/conversions",
    response_model=ConversionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversion(
    product_id: uuid.UUID,
    payload: ConversionCreate,
    context: ProductsUpdater,
    principal: PrincipalDep,
    db: SessionDep,
) -> ConversionOut:
    return await service.create_conversion(
        db,
        context=context,
        actor_id=principal.user_id,
        product_id=product_id,
        payload=payload,
    )
