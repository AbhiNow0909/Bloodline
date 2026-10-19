/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

import { contentSecurityPolicyPlugin } from './csp.ts'

export default defineConfig({
  plugins: [react(), tailwindcss(), contentSecurityPolicyPlugin()],
  // The repo-root .env supplies VITE_API_BASE_URL (only VITE_* variables reach the browser).
  envDir: '..',
  server: { port: 5173, strictPort: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
