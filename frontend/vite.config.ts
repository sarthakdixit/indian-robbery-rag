import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Bound to localhost only — backend runs on 8000, frontend on 5173.
    port: 5173,
    strictPort: true,
    // Proxy /api/* through Vite's dev server so the browser doesn't see
    // CORS errors in development. In production (SWA), the SWA
    // Backend Linking does the same job.
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    // SWA serves the dist/ folder directly; no special tuning needed.
  },
});
