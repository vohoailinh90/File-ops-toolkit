import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `npm run dev` proxies the API to the Python server, started with a fixed token:
//   FOT_DEV_TOKEN=dev python3 app.py serve --no-browser     (and VITE_FOT_TOKEN=dev npm run dev)
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
      '@locales': path.resolve(import.meta.dirname, '../file_ops_toolkit/locales'),
    },
  },
  server: {
    fs: { allow: ['..'] },
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
})
