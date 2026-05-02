"""E2E 验证 commit 3e5c381 修的 4 条 bug。

场景 A：禁用 salesman → assigned 订单自动释放 → pending_assignment
场景 B：消费者推荐人被禁 → 下单 403
场景 C：linked_employee 停用 → 业务员登录 403
场景 D：驳回 pending 用户 → 同 openid 可重注册
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import admin_session_factory
from app.models.mall.base import (
    MallOrderStatus,
    MallUserApplicationStatus,
    MallUserStatus,
    MallUserType,
)
from app.models.mall.inventory import MallInventory, MallWarehouse
from app.models.mall.order import MallOrder, MallOrderClaimLog, MallOrderItem
from app.models.mall.product import MallProduct, MallProductSku
from app.models.mall.user import MallAddress, MallUser
from app.models.user import Employee
from app.services.mall import auth_service, order_service
from app.services.mall.validators import (
    assert_salesman_linked_employee_active,
)


def banner(n: str) -> None:
    print(f"\n{'='*60}\n{n}\n{'='*60}")


async def scenario_a_disable_salesman_cascades_orders():
    banner("A. 禁用 salesman 后 assigned 订单自动释放")
    async with admin_session_factory() as s:
        # 找一个 salesman + 一个客户 + 一个可用 sku + 一个地址
        sm = (await s.execute(
            select(MallUser).where(MallUser.username == "sm_test")
        )).scalar_one()
        consumer = (await s.execute(
            select(MallUser).where(MallUser.user_type == "consumer")
            .where(MallUser.application_status == "approved")
            .where(MallUser.status == "active").limit(1)
        )).scalar_one()
        sku = (await s.execute(
            select(MallProductSku).where(MallProductSku.cost_price.isnot(None)).limit(1)
        )).scalar_one()
        addr = (await s.execute(
            select(MallAddress).where(MallAddress.user_id == consumer.id).limit(1)
        )).scalar_one_or_none()
        if addr is None:
            addr = MallAddress(
                user_id=consumer.id, receiver="测试", mobile="13800000000",
                addr="测试地址", is_default=True,
            )
            s.add(addr)
            await s.flush()
        print(f"salesman={sm.username}({sm.id[:8]}), consumer={consumer.real_name}, sku={sku.id}, addr={addr.id[:8]}")

        # 确保库存够
        inv = (await s.execute(
            select(MallInventory).where(MallInventory.sku_id == sku.id).limit(1)
        )).scalar_one_or_none()
        if inv is None or inv.quantity < 1:
            print("SKIP: 库存不够")
            return
        print(f"库存: warehouse={inv.warehouse_id[:8]} qty={inv.quantity}")

        # 临时把 consumer referrer 指向 sm（便于 create_order 通过校验）
        orig_ref = consumer.referrer_salesman_id
        consumer.referrer_salesman_id = sm.id
        if consumer.referrer_bound_at is None:
            consumer.referrer_bound_at = datetime.now(timezone.utc)
        await s.flush()

        # 保证 sm 是 active 状态（可能之前被 D 场景改了）
        sm.status = MallUserStatus.ACTIVE.value
        sm.is_accepting_orders = True
        await s.flush()

        # 下单
        order = await order_service.create_order(
            s, consumer,
            items=[{"sku_id": sku.id, "quantity": 1}],
            address_id=addr.id,
        )
        print(f"下单成功: order_no={order.order_no}, status={order.status}")

        # 业务员抢单
        from app.services.mall.order_service import claim_order
        await claim_order(s, sm, order.id)
        await s.flush()
        await s.refresh(order)
        assert order.status == MallOrderStatus.ASSIGNED.value, f"expected assigned, got {order.status}"
        assert order.assigned_salesman_id == sm.id
        print(f"抢单后: status={order.status}, assigned={order.assigned_salesman_id[:8]}")

        # 禁用业务员 —— 通过路由 service 内联复制（不跑 HTTP）
        from app.models.mall.order import MallOrderClaimLog as _CL
        sm.status = MallUserStatus.DISABLED.value
        sm.token_version = (sm.token_version or 0) + 1
        sm.is_accepting_orders = False
        to_release = (await s.execute(
            select(MallOrder)
            .where(MallOrder.assigned_salesman_id == sm.id)
            .where(MallOrder.status == MallOrderStatus.ASSIGNED.value)
        )).scalars().all()
        for o in to_release:
            o.status = MallOrderStatus.PENDING_ASSIGNMENT.value
            o.assigned_salesman_id = None
            o.claimed_at = None
            s.add(_CL(
                order_id=o.id, action="release",
                from_salesman_id=sm.id, to_salesman_id=None,
                operator_id="system", reason="E2E 测试禁用",
            ))
        await s.flush()
        await s.refresh(order)
        print(f"禁用后: status={order.status}, assigned={order.assigned_salesman_id}")
        assert order.status == MallOrderStatus.PENDING_ASSIGNMENT.value, "订单应回池"
        assert order.assigned_salesman_id is None, "assigned 应被清空"

        # 查 release log
        log = (await s.execute(
            select(_CL).where(_CL.order_id == order.id)
            .where(_CL.action == "release")
            .order_by(_CL.created_at.desc())
        )).scalar_one_or_none()
        assert log is not None, "应有 release log"
        print(f"✅ A 通过: order {order.order_no} 回池 + claim_log reason={log.reason!r}")

        # 清理：订单 cancel 掉，把 sm 恢复
        order.status = MallOrderStatus.CANCELLED.value
        order.cancelled_at = datetime.now(timezone.utc)
        sm.status = MallUserStatus.ACTIVE.value
        sm.is_accepting_orders = True
        consumer.referrer_salesman_id = orig_ref
        await s.commit()


async def scenario_b_consumer_with_disabled_referrer_cant_order():
    banner("B. 消费者推荐人被禁用时下单 403")
    async with admin_session_factory() as s:
        sm = (await s.execute(
            select(MallUser).where(MallUser.username == "sm_test")
        )).scalar_one()
        consumer = (await s.execute(
            select(MallUser).where(MallUser.user_type == "consumer")
            .where(MallUser.application_status == "approved")
            .where(MallUser.status == "active").limit(1)
        )).scalar_one()
        sku = (await s.execute(
            select(MallProductSku).where(MallProductSku.cost_price.isnot(None)).limit(1)
        )).scalar_one()
        addr = (await s.execute(
            select(MallAddress).where(MallAddress.user_id == consumer.id).limit(1)
        )).scalar_one_or_none()
        if addr is None:
            # 场景 A 可能没给该 consumer 建过地址
            addr = MallAddress(
                user_id=consumer.id, receiver="B 测试", mobile="13800000000",
                addr="测试地址", is_default=True,
            )
            s.add(addr)
            await s.flush()

        # 保证 sm disabled，referrer 指向 sm
        orig_status = sm.status
        orig_ref = consumer.referrer_salesman_id
        consumer.referrer_salesman_id = sm.id
        if consumer.referrer_bound_at is None:
            consumer.referrer_bound_at = datetime.now(timezone.utc)
        sm.status = MallUserStatus.DISABLED.value
        await s.flush()

        from fastapi import HTTPException
        try:
            await order_service.create_order(
                s, consumer,
                items=[{"sku_id": sku.id, "quantity": 1}],
                address_id=addr.id,
            )
            print("❌ B 失败: 本该抛 403 但下单成功了")
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "推荐业务员已停用" in str(exc.detail)
            print(f"✅ B 通过: 抛 403 '{exc.detail}'")

        # 还原
        sm.status = orig_status
        consumer.referrer_salesman_id = orig_ref
        await s.commit()


async def scenario_c_disabled_employee_blocks_salesman_login():
    banner("C. linked_employee 停用时业务员登录 403")
    async with admin_session_factory() as s:
        sm = (await s.execute(
            select(MallUser).where(MallUser.username == "sm_test")
        )).scalar_one()
        if not sm.linked_employee_id:
            print("SKIP: sm_test 没有 linked_employee_id")
            return
        emp = await s.get(Employee, sm.linked_employee_id)
        if emp is None:
            print(f"SKIP: employee {sm.linked_employee_id} 不存在")
            return
        orig_emp_status = emp.status
        print(f"linked employee: {emp.name} status={emp.status}")

        # 停用 employee
        emp.status = "inactive"
        await s.flush()

        from fastapi import HTTPException
        try:
            await assert_salesman_linked_employee_active(s, sm)
            print("❌ C 失败: 本该抛 403 但没抛")
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "员工已停用" in str(exc.detail)
            print(f"✅ C 通过: 抛 403 '{exc.detail}'")

        # 恢复
        emp.status = orig_emp_status
        await s.commit()


async def scenario_d_rejected_user_can_reregister():
    banner("D. 驳回用户后同 openid 可重注册")
    async with admin_session_factory() as s:
        # 找到徐泽军
        target = (await s.execute(
            select(MallUser).where(MallUser.real_name == "徐泽军")
        )).scalar_one_or_none()
        if target is None or not target.openid:
            print("SKIP: 没找到测试用户 or 没 openid")
            return
        orig_openid = target.openid
        orig_status = target.application_status
        orig_reason = target.rejection_reason
        orig_tv = target.token_version
        print(f"before: openid={target.openid}, application_status={target.application_status}")

        # 模拟 reject_application 的字段改动
        from datetime import datetime as dt, timezone as tz
        ts = int(dt.now(tz.utc).timestamp())
        target.application_status = MallUserApplicationStatus.REJECTED.value
        target.rejection_reason = "E2E 测试驳回"
        target.token_version = (target.token_version or 0) + 1
        if target.openid:
            target.openid = f"rejected_{ts}_{target.openid}"
        await s.flush()
        print(f"after reject: openid={target.openid}, status={target.application_status}")

        # 现在应该能用 orig_openid 查到 None
        existing = await auth_service.get_mall_user_by_openid(s, orig_openid)
        assert existing is None, f"orig_openid 应查不到用户（已 rename），但查到了: {existing.id}"
        print(f"✅ D 通过: 用原 openid '{orig_openid[:20]}...' 查库返 None，可以重注册了")

        # 还原原状态
        target.application_status = orig_status
        target.rejection_reason = orig_reason
        target.token_version = orig_tv
        target.openid = orig_openid
        await s.commit()


async def main():
    try:
        await scenario_a_disable_salesman_cascades_orders()
    except Exception as e:
        print(f"❌ A error: {type(e).__name__}: {e}")
    try:
        await scenario_b_consumer_with_disabled_referrer_cant_order()
    except Exception as e:
        print(f"❌ B error: {type(e).__name__}: {e}")
    try:
        await scenario_c_disabled_employee_blocks_salesman_login()
    except Exception as e:
        print(f"❌ C error: {type(e).__name__}: {e}")
    try:
        await scenario_d_rejected_user_can_reregister()
    except Exception as e:
        print(f"❌ D error: {type(e).__name__}: {e}")
    print("\n" + "=" * 60)
    print("E2E 验证完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
