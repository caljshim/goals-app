import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  // The browser never receives this development token. Vite adds it while
  // proxying /api requests to the local backend.
  const apiKey = loadEnv(mode, process.cwd(), "").APP_API_KEY?.trim();
  return {
    plugins: [react()],
    server: {
      port: 5273,
      // IPv4 target on purpose — "localhost" resolves to ::1 first on Windows
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8100",
          headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : undefined,
        },
      },
    },
    test: { environment: "jsdom", globals: true },
  };
});
