import { readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const certPath = process.env.WAREHOUSE_HTTPS_CERT
const keyPath = process.env.WAREHOUSE_HTTPS_KEY

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    https: certPath && keyPath ? { cert: readFileSync(certPath), key: readFileSync(keyPath) } : undefined,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', headers: { 'X-Forwarded-Proto': certPath && keyPath ? 'https' : 'http' } } },
  },
})
