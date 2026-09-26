import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the API runs at localhost:8000 (docker-compose.override.yml exposes it).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
