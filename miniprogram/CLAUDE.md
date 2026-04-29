# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`mall4uni-pro` — a uni-app (Vue 3) client for the mall4j Spring Boot backend, rebranded here as **鑫久隆批发商城** (Xinjiulong wholesale mall) with a black-gold minimalist theme. A single codebase ships to H5, WeChat mini program, and Android/iOS apps.

## Commands

Package manager is **pnpm** (enforced by `preinstall: npx only-allow pnpm` — delete that script if you must use npm/yarn).

```bash
pnpm install              # install deps

pnpm run dev:h5           # H5 dev (vite at :5173, auto-opens)
pnpm run dev:h5-test      # H5 dev against the testing env (.env.testing)
pnpm run dev:mp-weixin    # WeChat mini-program dev (compiles to dist/dev/mp-weixin)

pnpm run build:h5         # H5 production build
pnpm run build:h5-test    # H5 build using testing env → dist/test/h5
pnpm run build:mp-weixin  # WeChat mini-program production build
pnpm run build:app-android
pnpm run build:app-ios

pnpm run lint             # eslint on src/**/*.{js,vue}
pnpm run lint:fix         # auto-fix

# run a single file through lint:
pnpm exec eslint src/pages/index/index.vue
```

There is **no test runner configured** in this project.

### Environment files

`.env.development`, `.env.testing`, `.env.production` at the repo root. Only `VITE_APP_*`-prefixed vars are exposed; read via `import.meta.env.VITE_APP_XXX`. Key vars:

- `VITE_APP_BASE_API` — backend origin used by `http.request`
- `VITE_APP_RESOURCES_URL` — CDN prefix; `util.checkFileUrl` prepends it to relative image paths
- `VITE_APP_MP_APPID` — WeChat **公众号** appid (the mini-program appid lives in `src/manifest.json` under `mp-weixin.appid`)

## Architecture

### Auto-imports — read this before adding imports

`vite.config.js` wires `unplugin-auto-import` to globally expose:

- All `vue` APIs (`ref`, `computed`, `onMounted`, …)
- All `uni-app` composition APIs (`onLoad`, `onPullDownRefresh`, …)
- **Every default export from `src/utils/*` and `src/wxs/**`** — accessible by filename: `http`, `util`, `loginMethods`, `number`, plus named exports like `encrypt` from `crypto.js` and `PayType`/`AppType` from `constant.js`

Consequence: `.vue` files reference `http.request(...)`, `util.checkFileUrl(...)`, `number()`, etc. with **no import statement**. Types land in `src/auto-imports.d.ts` and an ESLint globals file `.eslintrc-auto-import.json` (generated; both git-ignored). If you add a new util and ESLint flags it as undefined, run a dev/build once to regenerate these.

Additional ESLint globals (see `.eslintrc.cjs`): `uni`, `getApp`, `wx`, `getCurrentPages`, `plus`.

### HTTP layer (`src/utils/http.js`)

Single entrypoint for every backend call. Key behaviors any caller inherits:

- Auto-refreshes the token via `loginMethods.refreshToken()` before each request (skipped when `params.login`, `params.isRefreshing`, or during the landing/bootstrap flow)
- Injects `Authorization` header from `uni.getStorageSync('Token')`
- Prepends `params.domain || VITE_APP_BASE_API` to `params.url`
- Defaults to `POST` and `dataType: 'json'`
- Dispatches on mall4j response codes:
  - `00000` / `A00002` → resolve
  - `A00004` → clear token, optionally show a "please login" modal, and navigate to `/pages/accountLogin/accountLogin` (suppress modal with `params.dontTrunLogin: true`)
  - `A00005` → generic server-error toast
  - `A00001` / `A04001` / `A00006` / `A00012` → auto-toast `responseData.msg` (suppress with `params.hasCatch: true`)
  - Any non-`00000` → promise rejects with the parsed body
- `responseType: 'arraybuffer'` short-circuits code parsing (used for QR codes)

When adding API calls, use `http.request({ url, method, data, … })` and rely on these conventions rather than re-implementing error handling.

### Routing / pages

Pages are **declared in `src/pages.json`** (not file-system routed). Adding a page means:
1. Create `src/pages/<name>/<name>.vue`
2. Register its path in `pages.json` (with `style` if a custom nav bar is needed)
3. If it should appear in the bottom tab bar, add it under `tabBar.list`

Tab bar currently: `pages/index/index` (首页), `pages/basket/basket` (购物车), `pages/user/user` (我的). Note the cart-count code calls `uni.setTabBarBadge({ index: 2 })` for the cart, while `util.removeTabBadge` uses `index: 3` — if you touch tab indices, check both sites.

The project also declares `uni-crazy-router` as a dep and ships `uni-vite-plugin-h5-prod-effect` to keep it functional in H5 production builds — keep that plugin in `vite.config.js`.

### Design tokens — two parallel systems (be careful)

Both are imported into different places; don't assume one is canonical:

- `src/uni.scss` — the **uni-app-standard token file** (`$uni-color-primary`, `$uni-bg-color`, …). Auto-injected by uni-app; remaps uni defaults onto the black-gold palette (`$brand-ink #0E0E0E`, `$brand-gold #C9A961`, `$brand-cream #FAF8F5`, `$brand-line #ECE8E1`, etc.).
- `src/styles/variables.scss` — a **separate** token file (`$color-primary`, `$spacing-*`, `$radius-*`) with mixins (`text-ellipsis`, `flex-center`, `flex-between`). Components must `@import '@/styles/variables.scss'` explicitly to use these.

When styling, prefer the existing tokens from whichever file is already imported in that component, and match the black/gold/cream palette described in the header comments of `src/app.css`.

### Path aliases

- `@` → `src/` (set in both `vite.config.js` and available in templates like `src="@/static/images/..."`)

### Multi-platform conditional compilation

Because builds target H5, WeChat, Alipay, Android, iOS, etc., platform-specific code lives behind uni-app conditional compilation comments (`#ifdef H5` / `#ifdef MP-WEIXIN` / `#endif`). When editing anything that touches platform APIs (payment, location, share, login flow), check whether an `#ifdef` block already handles the branch you care about.

## ESLint — notable project rules

`.eslintrc.cjs` extends `standard` + `plugin:vue/vue3-recommended`. Sharper limits than defaults:

- `max-lines-per-function`: **150** (skipBlankLines)
- `max-depth`: 5, `max-params`: 5, `max-nested-callbacks`: 10
- `eqeqeq: 'off'` — `==` is allowed (and used throughout `src/wxs/number.js`)
- `no-console: 'warn'`, `no-debugger: 'error'` only in production
- `vue/v-on-event-hyphenation` auto-fixes to kebab-case
- `vue/multi-word-component-names: 'off'` — single-word page names like `user.vue`, `basket.vue` are intentional

`lint-staged` runs `eslint --fix` on staged `*.{js,vue}`, but no git hook is installed by default — wire up `husky`/`simple-git-hooks` yourself if you want it to fire pre-commit.

## Deployment

`Dockerfile` copies `./dist/build/h5` into an nginx image; `nginx.conf` serves it on port 80 with caching disabled and `mini-h5.mall4j.com` as the server name. The H5 production `domain` in `src/manifest.json` is `https://mini-h5.xinjiulong.com` — update that (and nginx `server_name`) together when changing the H5 host.
