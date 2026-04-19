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
    yield
    logger.info("Shutting down...")
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

    # MCP tools for openclaw
    from app.mcp.tools import router as mcp_router

    app.include_router(mcp_router, prefix="/mcp", tags=["MCP Tools"])

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
