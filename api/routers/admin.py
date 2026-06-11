from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import require_admin, write_audit_log
from core.database import get_db
from core.security import hash_password
from models.user import AuditLog, User, UserRole

router = APIRouter()


class UserIn(BaseModel):
    email: EmailStr
    password: str
    role: UserRole
    pharmacy_id: Optional[int] = None
    brand_group_id: Optional[int] = None


class UserOut(BaseModel):
    id: int
    email: str
    role: UserRole
    pharmacy_id: Optional[int]
    brand_group_id: Optional[int]
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime]

    class Config:
        from_attributes = True


class PharmacyOption(BaseModel):
    id: int
    name: str
    city: Optional[str] = None

    class Config:
        from_attributes = True


class BrandGroupOption(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class AuditLogOut(BaseModel):
    id: int
    user_id: Optional[int]
    action: str
    resource_type: str
    resource_id: Optional[str]
    ip_address: Optional[str]
    timestamp: datetime
    detail: Optional[str]

    class Config:
        from_attributes = True


@router.get("/users", response_model=List[UserOut])
async def list_users(
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    q = select(User)
    if role:
        q = q.where(User.role == role)
    if is_active is not None:
        q = q.where(User.is_active == is_active)
    result = await db.execute(q.order_by(User.created_at.desc()))
    return result.scalars().all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: Request,
    body: UserIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
        pharmacy_id=body.pharmacy_id,
        brand_group_id=body.brand_group_id,
    )
    db.add(user)
    await db.flush()
    await write_audit_log(db, current_user.id, "create_user", "user", str(user.id), request.client.host)
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/users/{user_id}/deactivate", response_model=UserOut)
async def deactivate_user(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_active = False
    await write_audit_log(db, current_user.id, "deactivate_user", "user", str(user_id), request.client.host)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/pharmacies", response_model=List[PharmacyOption])
async def list_pharmacies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Pharmacies available to assign a pharmacist to (Admin create-user form)."""
    from models.pharmacy import Pharmacy

    rows = (await db.execute(select(Pharmacy).order_by(Pharmacy.name))).scalars().all()
    return rows


@router.get("/brand-groups", response_model=List[BrandGroupOption])
async def list_brand_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Brand groups available to assign a marketing/brand_manager user to."""
    from models.brand import BrandGroup

    rows = (await db.execute(select(BrandGroup).order_by(BrandGroup.name))).scalars().all()
    return rows


@router.get("/audit-logs", response_model=List[AuditLogOut])
async def list_audit_logs(
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    q = select(AuditLog)
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if action:
        q = q.where(AuditLog.action == action)
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)
    if date_from:
        q = q.where(AuditLog.timestamp >= date_from)
    if date_to:
        q = q.where(AuditLog.timestamp <= date_to)
    q = q.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()
