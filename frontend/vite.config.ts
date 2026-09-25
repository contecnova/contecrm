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
    // El puerto y el destino del proxy salen del MISMO sitio que los del resto
    // de la instalación: el `.env` de la raíz, que es quien decide dónde escucha
    // cada cosa (`FRONT_PORT`, `GATEWAY_PORT`).
    //
    // Estaban escritos aquí —5173 y 8080, los valores de manual de Vite y del
    // gateway— y en esta instalación son 15173 y 18080, porque conviven tres
    // productos de la casa en la misma máquina. O sea que `npm run dev` a secas
    // abría un front en otro puerto que proxiaba a un gateway que no existe, y
    // el único que funcionaba era el que alguien había arrancado a mano con las
    // variables puestas en su terminal. Al reiniciar la máquina, eso se pierde.
    port: Number(process.env.FRONT_PORT ?? 15173),
    proxy: {
      "/api": {
        target:
          process.env.GATEWAY_URL ?? `http://localhost:${process.env.GATEWAY_PORT ?? 18080}`,
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
