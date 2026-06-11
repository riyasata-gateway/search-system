from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin, write_audit_log
from core.database import get_db
from models.brand import Brand, BrandGroup
from models.user import User

router = APIRouter()


class BrandGroupOut(BaseModel):
    id: int
    name: str
    manufacturer: Optional[str]

    class Config:
        from_attributes = True


class BrandIn(BaseModel):
    name: str
    manufacturer: Optional[str] = None
    country: Optional[List[str]] = None
    is_competitor: bool = False
    brand_group_id: Optional[int] = None


class BrandOut(BaseModel):
    id: int
    name: str
    manufacturer: Optional[str]
    country: Optional[List[str]]
    is_competitor: bool
    brand_group_id: Optional[int]

    class Config:
        from_attributes = True


@router.get("/", response_model=List[BrandOut])
async def list_brands(
    is_competitor: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Brand)
    if is_competitor is not None:
        q = q.where(Brand.is_competitor == is_competitor)
    result = await db.execute(q.order_by(Brand.name))
    return result.scalars().all()


@router.post("/", response_model=BrandOut, status_code=status.HTTP_201_CREATED)
async def create_brand(
    request: Request,
    body: BrandIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    brand = Brand(**body.model_dump())
    db.add(brand)
    await db.flush()
    await write_audit_log(db, current_user.id, "create", "brand", str(brand.id), request.client.host)
    await db.commit()
    await db.refresh(brand)
    return brand


@router.put("/{brand_id}", response_model=BrandOut)
async def update_brand(
    request: Request,
    brand_id: int,
    body: BrandIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(Brand).where(Brand.id == brand_id))
    brand = result.scalar_one_or_none()
    if not brand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found")

    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(brand, k, v)

    await write_audit_log(db, current_user.id, "update", "brand", str(brand_id), request.client.host)
    await db.commit()
    await db.refresh(brand)
    return brand


@router.delete("/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand(
    request: Request,
    brand_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(Brand).where(Brand.id == brand_id))
    brand = result.scalar_one_or_none()
    if not brand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found")
    await db.delete(brand)
    await write_audit_log(db, current_user.id, "delete", "brand", str(brand_id), request.client.host)
    await db.commit()
