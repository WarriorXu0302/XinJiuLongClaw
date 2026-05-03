# Repository Guidelines

## Project Structure & Module Organization
This repository is a monorepo with three deployable applications:
- `backend/`: FastAPI + SQLAlchemy async backend APIs and scripts.
- `frontend/`: ERP admin web frontend (React/TypeScript).
- `miniprogram/`: uni-app (Vue 3) client for H5, WeChat mini-program, and mobile app builds.

Most active client work is under `miniprogram/src/`:
- `pages/`: route pages (must be registered in `src/pages.json`)
- `utils/`: shared request/auth/helper modules (auto-imported)
- `styles/` and `uni.scss`: design tokens and shared styles
- `static/`: image/static assets

## Build, Test, and Development Commands
Run commands in `miniprogram/` for client work:
- `pnpm install`: install dependencies (pnpm is the expected package manager)
- `pnpm run dev:h5`: start H5 dev server
- `pnpm run dev:mp-weixin`: build/watch WeChat mini-program output
- `pnpm run build:h5`: production H5 build
- `pnpm run lint`: run ESLint on `src/**/*.{js,vue}`
- `pnpm run lint:fix`: auto-fix lint issues

Example single-file lint:
- `pnpm exec eslint src/pages/index/index.vue`

## Coding Style & Naming Conventions
- Follow existing Vue 3 + uni-app patterns and keep page files under `src/pages/<name>/<name>.vue`.
- Use 2-space indentation and keep functions focused (project lint enforces complexity/size limits).
- Prefer existing tokens in `src/uni.scss` or `src/styles/variables.scss`; keep the black-gold-cream visual system consistent.
- Reuse `http.request(...)` from `src/utils/http.js` for API calls instead of custom fetch wrappers.
- Respect platform guards (`#ifdef H5`, `#ifdef MP-WEIXIN`, etc.) when touching platform-specific behavior.

## Testing Guidelines
- No dedicated unit/integration test runner is currently configured in `miniprogram/`.
- Required quality gate: `pnpm run lint` must pass before merging.
- For functional changes, verify behavior in at least one target runtime (H5 and/or MP-Weixin), especially for login, payment, and routing flows.

## Commit & Pull Request Guidelines
- Follow Conventional Commits style seen in history: `feat(...)`, `fix(...)`, `docs(...)`, `chore(...)`, `revert(...)`.
- Keep scope explicit when possible, e.g. `feat(mall): ...`, `fix(miniprogram): ...`.
- PRs should include: purpose, key changes, impacted modules, manual verification steps, and screenshots/GIFs for UI updates.
- Link related issue/task IDs and call out any env/config updates (`.env.*`, `manifest.json`, domain changes).

## Security & Configuration Tips
- Never commit secrets; keep runtime config in `.env.development`, `.env.testing`, `.env.production`.
- Only `VITE_APP_*` variables are exposed to client code via `import.meta.env`.
- When changing H5 domain or deployment host, update related config consistently (`manifest.json`, `nginx.conf`, deployment files).
