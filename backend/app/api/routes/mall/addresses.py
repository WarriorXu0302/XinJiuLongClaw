"""
/api/mall/addresses/*
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_mall_db
from app.core.security import CurrentMallUser
from app.models.mall.user import MallAddress
from app.schemas.mall.user import MallAddressVO, MallAddressWriteRequest
from app.services.mall import auth_service

router = APIRouter()


@router.get("", response_model=list[MallAddressVO])
async def list_addresses(
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    rows = (
        await db.execute(
            select(MallAddress)
            .where(MallAddress.user_id == user.id)
            .order_by(MallAddress.is_default.desc(), MallAddress.created_at.desc())
        )
    ).scalars().all()
    return [MallAddressVO.model_validate(r, from_attributes=True) for r in rows]


@router.get("/{addr_id}", response_model=MallAddressVO)
async def get_address(
    addr_id: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    row = (
        await db.execute(
            select(MallAddress)
            .where(MallAddress.id == addr_id)
            .where(MallAddress.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="地址不存在")
    return MallAddressVO.model_validate(row, from_attributes=True)


@router.post("", response_model=MallAddressVO)
async def create_address(
    body: MallAddressWriteRequest,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)

    # 新建默认地址前，先把原来的默认清掉（保持最多一条 is_default=True）
    if body.is_default:
        await db.execute(
            update(MallAddress)
            .where(MallAddress.user_id == user.id)
            .where(MallAddress.is_default.is_(True))
            .values(is_default=False)
        )

    row = MallAddress(
        user_id=user.id,
        receiver=body.receiver, mobile=body.mobile,
        province_code=body.province_code, city_code=body.city_code, area_code=body.area_code,
        province=body.province, city=body.city, area=body.area,
        addr=body.addr, is_default=body.is_default,
    )
    db.add(row)
    await db.flush()
    return MallAddressVO.model_validate(row, from_attributes=True)


@router.put("/{addr_id}", response_model=MallAddressVO)
async def update_address(
    addr_id: str,
    body: MallAddressWriteRequest,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    row = (
        await db.execute(
            select(MallAddress)
            .where(MallAddress.id == addr_id)
            .where(MallAddress.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="地址不存在")

    if body.is_default and not row.is_default:
        await db.execute(
            update(MallAddress)
            .where(MallAddress.user_id == user.id)
            .where(MallAddress.is_default.is_(True))
            .values(is_default=False)
        )

    row.receiver = body.receiver
    row.mobile = body.mobile
    row.province_code = body.province_code
    row.city_code = body.city_code
    row.area_code = body.area_code
    row.province = body.province
    row.city = body.city
    row.area = body.area
    row.addr = body.addr
    row.is_default = body.is_default
    await db.flush()
    return MallAddressVO.model_validate(row, from_attributes=True)


@router.delete("/{addr_id}")
async def delete_address(
    addr_id: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    # 删掉 is_default 地址时，自动把最早剩余的地址提为新默认（保证永远有一条默认）
    row = (
        await db.execute(
            select(MallAddress)
            .where(MallAddress.id == addr_id)
            .where(MallAddress.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="地址不存在")
    was_default = row.is_default
    await db.delete(row)
    await db.flush()
    if was_default:
        next_default = (await db.execute(
            select(MallAddress)
            .where(MallAddress.user_id == user.id)
            .order_by(MallAddress.created_at)
            .limit(1)
        )).scalar_one_or_none()
        if next_default:
            next_default.is_default = True
            await db.flush()
    return {"success": True}


@router.put("/{addr_id}/default")
async def set_default_address(
    addr_id: str,
    current: CurrentMallUser,
    db: AsyncSession = Depends(get_mall_db),
):
    user = await auth_service.verify_token_and_load_user(db, current)
    row = (
        await db.execute(
            select(MallAddress)
            .where(MallAddress.id == addr_id)
            .where(MallAddress.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="地址不存在")

    await db.execute(
        update(MallAddress)
        .where(MallAddress.user_id == user.id)
        .values(is_default=False)
    )
    row.is_default = True
    await db.flush()
    return {"success": True}
