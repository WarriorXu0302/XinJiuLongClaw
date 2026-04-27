import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend 默认跑在 8002（8001 会被 SSH 端口转发 / VS Code Plugin Host 等占用）
const BACKEND = 'http://localhost:8002'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // 固定 5175（5173 常被微信/支付宝小程序开发工具占用，5174 给 Vite preview 留着）
    port: 5175,
    strictPort: true,
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
      },
      '/mcp': {
        target: BACKEND,
        changeOrigin: true,
      },
    },
  },
})
