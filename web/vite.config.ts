import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
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
