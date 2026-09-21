import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

// La dirección del gateway NO se compila: se lee en ejecución de `/config.json`
// (ver `src/lib/config.ts`). Aquí solo se declara el proxy del servidor de
// desarrollo, para que en local no haga falta CORS.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.GATEWAY_URL ?? "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/pruebas/preparar.ts"],
  },
});
