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
    // Si el puerto está ocupado, FALLAR en vez de moverse a otro.
    //
    // Por defecto Vite se cambia al siguiente libre y lo dice en una línea de
    // su registro. El arranque imprime el puerto del `.env`, así que lo que se
    // anuncia y lo que escucha dejan de coincidir: se va a la URL, no carga, y
    // se busca el problema en el sitio equivocado. Medido el 26-10-2026 con
    // dos instancias a la vez: la segunda se fue al 15174 y el arranque seguía
    // diciendo 15173.
    //
    // Fallando se ve lo que pasa de verdad —que ya hay algo en ese puerto— y
    // se arregla en diez segundos.
    strictPort: true,
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
    // `e2e/` es de Playwright, no de vitest: sus ficheros importan `test` de
    // `@playwright/test`, que no es el de aquí. Sin excluirlos, vitest los
    // recoge y el gate del front falla por recoger pruebas que no le tocan.
    exclude: ["node_modules/**", "dist/**", "e2e/**"],
  },
});
