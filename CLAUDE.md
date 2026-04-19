# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NewERP System (新鑫久隆 ERP) — a full-stack ERP application for managing orders, inventory, policies (rebates/claims), finance, HR, purchasing, and inspections. FastAPI backend + React/TypeScript frontend.

## Development Commands

### Infrastructure (required first)
```bash
docker-compose up -d          # Start PostgreSQL (port 5433) and Redis (port 6379)
```

### Backend (from `backend/`)
```bash
pip install -r requirements.txt                          # Install dependencies
python app/main.py                                       # Run dev server (port 8000)
alembic upgrade head                                     # Apply all migrations
alembic revision --autogenerate -m "description"         # Generate new migration
```

### Frontend (from `frontend/`)
```bash
npm install        # Install dependencies
npm run dev        # Dev server (port 5173, proxies /api and /mcp to localhost:8001)
npm run build      # Type-check then build (tsc -b && vite build)
npm run lint       # ESLint
```

**Note:** The Vite proxy targets port 8001, not 8000. When running both together, start the backend on port 8001 or update `vite.config.ts`.

## Architecture

### Backend (FastAPI + SQLAlchemy 2.0 Async)

**Layered pattern:** Routes (`app/api/routes/`) → Services (`app/services/`) → Models (`app/models/`)

- **Routes** define API endpoints. Each route module is registered in `app/main.py` with a `/api/` prefix.
- **Models** use SQLAlchemy 2.0 declarative style. All models inherit from `Base` in `models/base.py`. Common column types (`StrPK`, `IntPK`, `CreatedAt`, `UpdatedAt`) and all business enums are defined there.
- **Schemas** (`app/schemas/`) are Pydantic models for request/response validation.
- **Config** is via Pydantic Settings loading from `.env` (`app/core/config.py`). Access settings via the `settings` singleton.

**Key patterns:**
- Database sessions: inject via `db: AsyncSession = Depends(get_db)`. Sessions auto-commit on success, auto-rollback on exception.
- Authentication: JWT Bearer tokens. Use `CurrentUser` type alias (from `app/core/security.py`) for authenticated endpoints. The token payload contains `sub` (user ID), `role`, and `brand_ids`.
- Roles (RBAC): `admin`, `boss`, `finance`, `salesman`, `warehouse`, `hr`, `purchase`, `manufacturer_staff` — defined in `UserRoleCode` enum.
- MCP tools endpoint at `/mcp` prefix for Claude Code integration.

### Frontend (React 19 + Vite + TypeScript)

- **UI:** Ant Design v6 components
- **State:** Zustand stores (`src/stores/`) — `authStore` persists JWT tokens and roles to localStorage under key `erp-auth`
- **Data fetching:** TanStack React Query + Axios client (`src/api/client.ts`). The Axios instance auto-attaches the JWT token and redirects to `/login` on 401.
- **Routing:** React Router v7 (`src/router/`)
- **Pages:** Feature-based organization under `src/pages/` (orders, inventory, finance, hr, etc.)
- **Layouts:** `MainLayout` with sidebar navigation, `AuthGuard` for route protection

### Database

- PostgreSQL 16 via Docker (host port **5433** → container port 5432)
- Default credentials: `erpuser` / `erppassword` / database `newerp`
- Migrations managed by Alembic (`backend/migrations/`)
- Redis 7 for caching (port 6379)

## Code Conventions

- Backend: Python 3.10+, async/await throughout, Pydantic v2 for validation
- Frontend: TypeScript strict mode, functional components only, Ant Design for all UI elements
- All business status enums are centralized in `backend/app/models/base.py`
- The project language context is Chinese (UI labels, business terms, docs in `docs/`)
