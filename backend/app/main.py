"""
NewERP Backend - FastAPI Application Entry Point
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown events."""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    await init_db()
    logger.info("Database tables initialized")

    # APScheduler（mall housekeeping 定时任务）
    from app.core.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    logger.info("APScheduler started (mall housekeeping jobs)")

    # MCP bridge 的 StreamableHTTPSessionManager 必须在 app lifespan 内运行
    from app.mcp.bridge import bridge_lifespan
    async with bridge_lifespan():
        logger.info("MCP bridge (streamable-http) ready at /mcp/stream")
        yield

    logger.info("Shutting down...")
    await stop_scheduler()
    await close_db()
    logger.info("Database connections closed")


def create_app() -> FastAPI:
    """Factory function to create the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="新鑫久隆 ERP 系统后端 API",
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 审计 middleware：把当前 Request 注入 ContextVar，log_audit 自动取 IP
    @app.middleware("http")
    async def audit_request_middleware(request, call_next):
        from app.services.audit_service import set_current_request
        set_current_request(request)
        try:
            return await call_next(request)
        finally:
            set_current_request(None)

    # Health check endpoint
    @app.get("/health")
    async def health_check() -> dict:
        return {"status": "healthy", "version": settings.APP_VERSION}

    # Register routers
    from app.api.routes import (
        accounts,
        audit_logs,
        auth,
        customers,
        dashboard,
        finance,
        financing,
        hr,
        inspections,
        inventory,
        notifications,
        orders,
        policies,
        policy_templates,
        products,
        purchase,
        suppliers,
        tasting,
        uploads,
        expense_claims,
        payroll,
        sales_targets,
        attendance,
        performance,
        transfers,
    )

    app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
    app.include_router(accounts.router, prefix="/api", tags=["Accounts"])
    app.include_router(orders.router, prefix="/api/orders", tags=["Orders"])
    app.include_router(inventory.router, prefix="/api/inventory", tags=["Inventory"])
    app.include_router(policies.router, prefix="/api/policies", tags=["Policies"])
    app.include_router(finance.router, prefix="/api", tags=["Finance"])
    app.include_router(customers.router, prefix="/api/customers", tags=["Customers"])
    app.include_router(products.router, prefix="/api/products", tags=["Products"])
    app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
    app.include_router(audit_logs.router, prefix="/api/audit-logs", tags=["Audit"])
    app.include_router(inspections.router, prefix="/api", tags=["Inspections"])
    app.include_router(tasting.router, prefix="/api", tags=["Tasting"])
    app.include_router(purchase.router, prefix="/api/purchase-orders", tags=["Purchase"])
    app.include_router(transfers.router, prefix="/api/transfers", tags=["Transfers"])
    app.include_router(suppliers.router, prefix="/api/suppliers", tags=["Suppliers"])
    app.include_router(hr.router, prefix="/api/hr", tags=["HR"])
    app.include_router(policy_templates.router, prefix="/api/policy-templates", tags=["PolicyTemplates"])
    app.include_router(financing.router, prefix="/api/financing-orders", tags=["Financing"])
    app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
    app.include_router(expense_claims.router, prefix="/api/expense-claims", tags=["ExpenseClaims"])
    app.include_router(uploads.router, prefix="/api/uploads", tags=["Uploads"])
    app.include_router(payroll.router, prefix="/api/payroll", tags=["Payroll"])
    app.include_router(sales_targets.router, prefix="/api/sales-targets", tags=["SalesTargets"])
    app.include_router(attendance.router, prefix="/api/attendance", tags=["Attendance"])
    app.include_router(performance.router, prefix="/api/performance", tags=["Performance"])

    # MCP tools — AI Agent 工具集（JWT + 飞书双认证）REST 版本
    from app.mcp import mcp_router
    app.include_router(mcp_router, prefix="/mcp")

    # MCP Streamable-HTTP 协议桥（给 Bisheng / Claude Code 等标准 MCP client 用）
    from app.mcp.bridge import mcp_bridge_asgi
    app.mount("/mcp/stream", mcp_bridge_asgi)

    # 飞书 Agent 绑定 + token 签发（服务间密钥鉴权）
    from app.feishu.routes import router as feishu_router
    app.include_router(feishu_router, prefix="/api/feishu", tags=["Feishu"])

    # Mall (小程序) routes — 按 milestone 逐个解开
    from app.api.routes.mall import (
        auth as mall_auth,
        addresses as mall_addresses,
        cart as mall_cart,
        categories as mall_categories,
        collections as mall_collections,
        notices as mall_notices,
        orders as mall_orders,
        products as mall_products,
        regions as mall_regions,
        search as mall_search,
    )
    app.include_router(mall_auth.router, prefix="/api/mall/auth", tags=["Mall-Auth"])
    app.include_router(mall_products.router, prefix="/api/mall/products", tags=["Mall-Products"])
    app.include_router(mall_categories.router, prefix="/api/mall/categories", tags=["Mall-Categories"])
    app.include_router(mall_notices.router, prefix="/api/mall/notices", tags=["Mall-Notices"])
    app.include_router(mall_regions.router, prefix="/api/mall/regions", tags=["Mall-Regions"])
    app.include_router(mall_search.router, prefix="/api/mall/search", tags=["Mall-Search"])
    app.include_router(mall_cart.router, prefix="/api/mall/cart", tags=["Mall-Cart"])
    app.include_router(mall_addresses.router, prefix="/api/mall/addresses", tags=["Mall-Addresses"])
    app.include_router(mall_orders.router, prefix="/api/mall/orders", tags=["Mall-Orders"])
    app.include_router(mall_collections.router, prefix="/api/mall/collections", tags=["Mall-Collections"])

    # 注册审批：匿名可访问的公共上传端点（营业执照等）
    from app.api.routes.mall import public_uploads as mall_public_uploads
    app.include_router(
        mall_public_uploads.router,
        prefix="/api/mall/public-uploads",
        tags=["Mall-Public"],
    )

    # M4a: 履约闭环（抢单/出库/送达/凭证/财务确认/跳单告警）
    from app.api.routes.mall import attachments as mall_attachments
    from app.api.routes.mall.salesman import (
        alerts as ms_alerts,
        orders as ms_orders,
    )
    from app.api.routes.mall.admin import (
        orders as ma_orders,
        skip_alerts as ma_skip_alerts,
    )
    app.include_router(
        mall_attachments.router,
        prefix="/api/mall/salesman/attachments",
        tags=["Mall-Salesman-Attachments"],
    )
    app.include_router(ms_orders.router, prefix="/api/mall/salesman/orders", tags=["Mall-Salesman"])
    app.include_router(ms_alerts.router, prefix="/api/mall/salesman/skip-alerts", tags=["Mall-Salesman"])
    app.include_router(ma_orders.router, prefix="/api/mall/admin/orders", tags=["Mall-Admin"])
    app.include_router(ma_skip_alerts.router, prefix="/api/mall/admin/skip-alerts", tags=["Mall-Admin"])

    # M4s: 管理员手动触发定时任务（housekeeping）
    from app.api.routes.mall.admin import housekeeping as ma_housekeeping
    app.include_router(ma_housekeeping.router, prefix="/api/mall/admin/housekeeping", tags=["Mall-Admin"])

    # M5a.8: 商城退货审批（admin/boss/finance）
    from app.api.routes.mall.admin import returns as ma_returns
    app.include_router(ma_returns.router, prefix="/api/mall/admin/returns", tags=["Mall-Admin"])

    # M4c: workspace 薄转发（ERP 复用模块 — 通知 / 打卡 / 拜访 / 请假 / 报销 / 稽查 / KPI / 客户）
    from app.api.routes.mall.workspace import (
        attendance as mw_attendance,
        customers as mw_customers,
        expense as mw_expense,
        inspection as mw_inspection,
        kpi as mw_kpi,
        leave as mw_leave,
        notifications as mw_notifications,
    )
    app.include_router(
        mw_notifications.router,
        prefix="/api/mall/workspace/notifications",
        tags=["Mall-Workspace"],
    )
    app.include_router(
        mw_attendance.router,
        prefix="/api/mall/workspace/attendance",
        tags=["Mall-Workspace"],
    )
    app.include_router(
        mw_leave.router,
        prefix="/api/mall/workspace/leave-requests",
        tags=["Mall-Workspace"],
    )
    app.include_router(
        mw_expense.router,
        prefix="/api/mall/workspace/expense-claims",
        tags=["Mall-Workspace"],
    )
    app.include_router(
        mw_inspection.router,
        prefix="/api/mall/workspace/inspection-cases",
        tags=["Mall-Workspace"],
    )
    app.include_router(
        mw_kpi.router,
        prefix="/api/mall/workspace/sales-targets",
        tags=["Mall-Workspace"],
    )
    app.include_router(
        mw_customers.router,
        prefix="/api/mall/workspace/customers",
        tags=["Mall-Workspace"],
    )

    # M5: 管理后台（users / salesmen / payments / warehouses / inventory / categories / tags）+ 业务员工作台剩余页
    from app.api.routes.mall.admin import (
        audit_logs as ma_audit_logs,
        categories as ma_categories,
        dashboard as ma_dashboard,
        inventory as ma_inventory,
        invite_codes as ma_invite_codes,
        login_logs as ma_login_logs,
        notices as ma_notices,
        payments as ma_payments,
        products as ma_products,
        salesmen as ma_salesmen,
        search_keywords as ma_search_keywords,
        user_applications as ma_user_applications,
        users as ma_users,
        warehouses as ma_warehouses,
    )
    from app.api.routes.mall.salesman import (
        invite as ms_invite,
        my_customers as ms_customers,
        profile as ms_profile,
        stats as ms_stats,
    )
    app.include_router(ma_users.router, prefix="/api/mall/admin/users", tags=["Mall-Admin"])
    app.include_router(
        ma_user_applications.router,
        prefix="/api/mall/admin/user-applications",
        tags=["Mall-Admin"],
    )
    app.include_router(ma_payments.router, prefix="/api/mall/admin/payments", tags=["Mall-Admin"])
    app.include_router(ma_salesmen.router, prefix="/api/mall/admin/salesmen", tags=["Mall-Admin"])
    app.include_router(ma_warehouses.router, prefix="/api/mall/admin/warehouses", tags=["Mall-Admin"])
    app.include_router(ma_inventory.router, prefix="/api/mall/admin/inventory", tags=["Mall-Admin"])
    app.include_router(ma_categories.router, prefix="/api/mall/admin/categories", tags=["Mall-Admin"])
    app.include_router(ma_categories.tag_router, prefix="/api/mall/admin/tags", tags=["Mall-Admin"])
    app.include_router(ma_products.router, prefix="/api/mall/admin/products", tags=["Mall-Admin"])
    app.include_router(ma_products.sku_router, prefix="/api/mall/admin/skus", tags=["Mall-Admin"])
    app.include_router(ma_dashboard.router, prefix="/api/mall/admin/dashboard", tags=["Mall-Admin"])
    app.include_router(ma_invite_codes.router, prefix="/api/mall/admin/invite-codes", tags=["Mall-Admin"])
    app.include_router(ma_audit_logs.router, prefix="/api/mall/admin/audit-logs", tags=["Mall-Admin"])
    app.include_router(ma_login_logs.router, prefix="/api/mall/admin/login-logs", tags=["Mall-Admin"])
    app.include_router(ma_notices.router, prefix="/api/mall/admin/notices", tags=["Mall-Admin"])
    app.include_router(
        ma_search_keywords.router,
        prefix="/api/mall/admin/search-keywords",
        tags=["Mall-Admin"],
    )
    app.include_router(ms_invite.router, prefix="/api/mall/salesman/invite-codes", tags=["Mall-Salesman"])
    app.include_router(ms_customers.router, prefix="/api/mall/salesman/my-customers", tags=["Mall-Salesman"])
    app.include_router(ms_stats.router, prefix="/api/mall/salesman/stats", tags=["Mall-Salesman"])
    app.include_router(ms_profile.router, prefix="/api/mall/salesman/profile", tags=["Mall-Salesman"])

    # TODO(M5 后续): collections / notices 等

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
