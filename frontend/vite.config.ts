import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5273,
    // IPv4 target on purpose — "localhost" resolves to ::1 first on Windows
    proxy: { "/api": "http://127.0.0.1:8100" },
  },
  test: { environment: "jsdom", globals: true },
});
