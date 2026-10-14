import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The API key lives in frontend/.env.local as BACKEND_API_KEY (no VITE_ prefix,
// so it is never bundled into the client). The dev server adds it to proxied calls.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.BACKEND_URL || 'http://127.0.0.1:8000'
  const proxy = {
    target,
    changeOrigin: true,
    headers: env.BACKEND_API_KEY ? { 'X-API-Key': env.BACKEND_API_KEY } : {},
  }
  return {
    plugins: [react(), tailwindcss()],
    server: { proxy: { '/api': proxy, '/health': proxy } },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: './src/test/setup.ts',
      exclude: ['e2e/**', 'node_modules/**', 'dist/**'], // e2e/ belongs to Playwright
    },
  }
})
