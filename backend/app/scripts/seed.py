"""
Seed script — creates initial roles, employees, and users.
Run with:  python -m app.scripts.seed
"""
import asyncio
import uuid

from app.core.database import get_db_context
from app.core.security import get_password_hash
from app.models.user import Employee, Role, User, UserRole
from app.models.product import Account, Brand, Product, Supplier, Warehouse
from app.models.customer import Customer


async def seed() -> None:
    async with get_db_context() as db:
        # ── Roles ────────────────────────────────────────────────────
        role_defs = [
            ("admin", "超级管理员"),
            ("boss", "老板"),
            ("finance", "财务"),
            ("salesman", "业务员"),
            ("warehouse", "库管"),
            ("hr", "人事"),
            ("purchase", "采购"),
        ]
        roles: dict[str, Role] = {}
        for code, name in role_defs:
            role = Role(id=str(uuid.uuid4()), code=code, name=name, is_system=True)
            db.add(role)
            roles[code] = role

        # ── Employees ────────────────────────────────────────────────
        admin_emp = Employee(
            id=str(uuid.uuid4()),
            employee_no="EMP001",
            name="系统管理员",
            position="管理员",
        )
        db.add(admin_emp)

        boss_emp = Employee(
            id=str(uuid.uuid4()),
            employee_no="EMP002",
            name="张老板",
            position="总经理",
        )
        db.add(boss_emp)

        finance_emp = Employee(
            id=str(uuid.uuid4()),
            employee_no="EMP003",
            name="李财务",
            position="财务主管",
        )
        db.add(finance_emp)

        salesman_emp = Employee(
            id=str(uuid.uuid4()),
            employee_no="EMP004",
            name="王业务",
            position="业务员",
        )
        db.add(salesman_emp)

        warehouse_emp = Employee(
            id=str(uuid.uuid4()),
            employee_no="EMP005",
            name="赵库管",
            position="库管员",
        )
        db.add(warehouse_emp)

        # ── Users ────────────────────────────────────────────────────
        users_def = [
            ("admin", "admin123", admin_emp, "admin"),
            ("boss", "boss123", boss_emp, "boss"),
            ("finance", "finance123", finance_emp, "finance"),
            ("salesman", "sales123", salesman_emp, "salesman"),
            ("warehouse", "wh123", warehouse_emp, "warehouse"),
        ]
        for username, password, emp, role_code in users_def:
            user = User(
                id=str(uuid.uuid4()),
                username=username,
                hashed_password=get_password_hash(password),
                employee_id=emp.id,
            )
            db.add(user)
            ur = UserRole(
                id=str(uuid.uuid4()),
                user_id=user.id,
                role_id=roles[role_code].id,
            )
            db.add(ur)

        # ── Warehouses ───────────────────────────────────────────────
        main_wh = Warehouse(
            id=str(uuid.uuid4()),
            code="WH-MAIN",
            name="主仓库",
            warehouse_type="main",
            manager_id=warehouse_emp.id,
        )
        db.add(main_wh)
        backup_wh = Warehouse(
            id=str(uuid.uuid4()),
            code="WH-BACKUP",
            name="备用仓库",
            warehouse_type="backup",
        )
        db.add(backup_wh)

        # ── Accounts ─────────────────────────────────────────────────
        db.add(Account(id=str(uuid.uuid4()), code="CASH-01", name="现金账户", account_type="cash"))
        db.add(Account(id=str(uuid.uuid4()), code="FCLASS-01", name="F类账户", account_type="f_class"))
        db.add(Account(id=str(uuid.uuid4()), code="FIN-01", name="融资账户", account_type="financing"))

        # ── Suppliers / Manufacturers ────────────────────────────────
        mfr = Supplier(
            id=str(uuid.uuid4()),
            code="MFR-QHL",
            name="青花郎厂家",
            type="manufacturer",
            contact_name="厂家联系人",
        )
        db.add(mfr)
        await db.flush()

        # ── Brands ───────────────────────────────────────────────────
        qhl_brand = Brand(id=str(uuid.uuid4()), code="QHL", name="青花郎", manufacturer_id=mfr.id)
        db.add(qhl_brand)
        wly_brand = Brand(id=str(uuid.uuid4()), code="WLY", name="五粮液")
        db.add(wly_brand)
        z15_brand = Brand(id=str(uuid.uuid4()), code="Z15", name="珍十五")
        db.add(z15_brand)

        # ── Products ────────────────────────────────────────────────
        db.add(Product(id=str(uuid.uuid4()), code="QHL-53-500", name="青花郎53度500ml", brand_id=qhl_brand.id, unit="箱", purchase_price=885, sale_price=885))
        db.add(Product(id=str(uuid.uuid4()), code="WLY-52-500", name="五粮液52度500ml", brand_id=wly_brand.id, unit="箱", purchase_price=1099, sale_price=1099))
        db.add(Product(id=str(uuid.uuid4()), code="Z15-53-500", name="珍十五53度500ml", brand_id=z15_brand.id, unit="箱", purchase_price=428, sale_price=428))

        # ── Customers ───────────────────────────────────────────────
        db.add(Customer(id=str(uuid.uuid4()), code="C001", name="张三烟酒店", contact_name="张三", contact_phone="13800000001", settlement_mode="cash", salesman_id=salesman_emp.id))
        db.add(Customer(id=str(uuid.uuid4()), code="C002", name="李四酒业", contact_name="李四", contact_phone="13800000002", settlement_mode="credit", credit_days=30, salesman_id=salesman_emp.id))
        db.add(Customer(id=str(uuid.uuid4()), code="C003", name="王五商贸", contact_name="王五", contact_phone="13800000003", settlement_mode="cash"))

        await db.flush()
        print("Seed data created successfully!")
        print()
        print("Available login accounts:")
        print("  admin    / admin123    (超级管理员)")
        print("  boss     / boss123     (老板)")
        print("  finance  / finance123  (财务)")
        print("  salesman / sales123    (业务员)")
        print("  warehouse/ wh123       (库管)")


if __name__ == "__main__":
    asyncio.run(seed())
