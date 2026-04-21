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
      "/login": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000",
      "/me": "http://127.0.0.1:8000",
      "/logout": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
    },
  },
});
