import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: process.env.GITHUB_PAGES ? '/bluepace-ats/' : '/',
  server: {
    allowedHosts: true,
  },
  preview: {
    allowedHosts: true,
  },
})
// Deployment target: GitHub Pages
