import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Subpath deploy: the app is served under a path prefix (e.g. /alert-hub) so it
// can share a host with Grafana. Build-time (baked into asset URLs); same value
// dev+prod. Default "/" = local dev/test at root.
const base = process.env.VITE_BASE_PATH || "/";
const prefix = base === "/" ? "" : base.replace(/\/+$/, ""); // "/alert-hub" | ""
const apiProxyPath = `${prefix}/api`;

export default defineConfig({
  base,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Split heavy vendor libs out of the app/entry chunk so the initial
        // load is small and vendor chunks cache across deploys. Monaco only
        // ships in the /rules route chunk (lazy), but isolate it regardless.
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (id.includes("monaco-editor")) return "monaco";
          if (/[\\/]react(-dom|-router-dom)?[\\/]/.test(id)) return "react-vendor";
          if (id.includes("@tanstack")) return "query";
          if (id.includes("@radix-ui")) return "radix";
          if (id.includes("i18next")) return "i18n";
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Mirror the ingress: strip the prefix before forwarding to the backend
      // (backend routes stay at /api/v1). At base "/" this is just "/api".
      [apiProxyPath]: {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: prefix ? (p) => p.slice(prefix.length) : undefined,
      },
    },
  },
});
