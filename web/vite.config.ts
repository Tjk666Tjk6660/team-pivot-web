import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/login": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/me": "http://localhost:8000",
      "/logout": "http://localhost:8000",
      "/api": "http://localhost:8000",
    },
  },
});
