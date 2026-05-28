from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin, write_audit_log
from core.database import get_db
from models.product import AliasType, Product, ProductAlias, ProductCategory
from models.user import User

router = APIRouter()


class CategoryOut(BaseModel):
    id: int
    slug: str
    name_en: str
    name_fr: Optional[str]
    name_nl: Optional[str]
    is_otc: bool

    class Config:
        from_attributes = True


class ProductIn(BaseModel):
    name: str
    brand_id: Optional[int] = None
    category_id: Optional[int] = None
    active_ingredient: Optional[str] = None
    cnk: Optional[str] = None
    ean: Optional[str] = None
    is_otc: bool = True
    is_prescription: bool = False
    country: Optional[List[str]] = None


class ProductOut(BaseModel):
    id: int
    name: str
    brand_id: Optional[int]
    category_id: Optional[int]
    active_ingredient: Optional[str]
    cnk: Optional[str]
    ean: Optional[str]
    is_otc: bool
    is_prescription: bool
    country: Optional[List[str]]

    class Config:
        from_attributes = True


class AliasIn(BaseModel):
    alias: str
    language: Optional[str] = None
    country: Optional[str] = None
    alias_type: AliasType


class AliasOut(BaseModel):
    id: int
    alias: str
    language: Optional[str]
    country: Optional[str]
    alias_type: AliasType

    class Config:
        from_attributes = True


@router.get("/categories", response_model=List[CategoryOut])
async def list_categories(
    is_otc: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(ProductCategory)
    if is_otc is not None:
        q = q.where(ProductCategory.is_otc == is_otc)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/", response_model=List[ProductOut])
async def list_products(
    brand_id: Optional[int] = None,
    category_id: Optional[int] = None,
    is_otc: Optional[bool] = None,
    is_prescription: Optional[bool] = None,
    country: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Product)
    if brand_id is not None:
        q = q.where(Product.brand_id == brand_id)
    if category_id is not None:
        q = q.where(Product.category_id == category_id)
    if is_otc is not None:
        q = q.where(Product.is_otc == is_otc)
    if is_prescription is not None:
        q = q.where(Product.is_prescription == is_prescription)
    result = await db.execute(q.order_by(Product.name))
    return result.scalars().all()


@router.post("/", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    request: Request,
    body: ProductIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    product = Product(**body.model_dump())
    db.add(product)
    await db.flush()
    await write_audit_log(db, current_user.id, "create", "product", str(product.id), request.client.host)
    await db.commit()
    await db.refresh(product)
    return product


@router.post("/{product_id}/aliases", response_model=AliasOut, status_code=status.HTTP_201_CREATED)
async def add_alias(
    request: Request,
    product_id: int,
    body: AliasIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    alias = ProductAlias(product_id=product_id, **body.model_dump())
    db.add(alias)
    await db.flush()
    await write_audit_log(db, current_user.id, "create", "product_alias", str(alias.id), request.client.host)
    await db.commit()
    await db.refresh(alias)
    return alias


@router.get("/{product_id}/aliases", response_model=List[AliasOut])
async def list_aliases(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ProductAlias).where(ProductAlias.product_id == product_id)
    )
    return result.scalars().all()
