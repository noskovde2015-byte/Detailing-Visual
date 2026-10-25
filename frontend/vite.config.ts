/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // Куда проксировать /api в режиме разработки. Через прокси фронт и API живут на
  // одном адресе: cookie авторизации работают без CORS и SameSite=None.
  const apiTarget = env.VITE_API_PROXY_TARGET ?? "http://localhost:8001";

  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": { target: apiTarget, changeOrigin: false },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: false,
    },
  };
});
