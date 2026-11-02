import process from 'node:process'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
function buildIdentityPlugin() {
  return {
    name: "bluepace-build-identity",
    transformIndexHtml(html) {
      const candidate = process.env.VERCEL_GIT_COMMIT_SHA || process.env.GITHUB_SHA || "";
      const commit = /^[a-f0-9]{40}$/i.test(candidate) ? candidate.toLowerCase() : "unknown";
      const marker = `<meta name="bluepace-build-commit" content="${commit}" />`;
      return html.replace("</head>", `  ${marker}\n  </head>`);
    },
  };
}

export default defineConfig({
  plugins: [react(), buildIdentityPlugin()],
  base: process.env.GITHUB_PAGES ? '/bluepace-ats/' : '/',
  server: {
    allowedHosts: true,
  },
  preview: {
    allowedHosts: true,
  },
})
// Deployment target: GitHub Pages
