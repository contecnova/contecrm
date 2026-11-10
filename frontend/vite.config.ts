import react from "@vitejs/plugin-react";
import { createHash } from "node:crypto";
import { readdirSync, statSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { build, defineConfig, type Plugin } from "vite";

/**
 * `/embebido.js` en el servidor de desarrollo (CRM-00.02.03.05).
 *
 * El componente incrustable tiene su propia construcción
 * (`vite.embebido.config.ts`) y en la imagen lo sirve nginx en esa misma ruta.
 * En la pila local no lo servía nadie: se podía construir y no había dirección
 * desde la que pegarlo en una web. Aquí se construye al pedirlo —y otra vez
 * sólo si su código ha cambiado— con la misma configuración que la imagen, así
 * que lo que se prueba en local es lo que se publica.
 *
 * Las cabeceras son las de nginx salvo la caché: aquí `no-cache` con `ETag`,
 * para que un cambio se vea al recargar; allí una hora. Las dos sin
 * credenciales: se carga desde webs ajenas y no tiene nada que ver con la
 * sesión de la consola.
 */
function servirEmbebido(): Plugin {
  const carpeta = fileURLToPath(new URL("./src/embebido", import.meta.url));
  let hecho: { huella: string; codigo: string; etag: string } | null = null;

  const huellaDelCodigo = () =>
    readdirSync(carpeta)
      .map((f) => `${f}:${statSync(`${carpeta}/${f}`).mtimeMs}`)
      .join("|");

  async function construir(): Promise<{ codigo: string; etag: string }> {
    const huella = huellaDelCodigo();
    if (hecho?.huella === huella) return hecho;
    const salida = await build({
      configFile: fileURLToPath(new URL("./vite.embebido.config.ts", import.meta.url)),
      logLevel: "silent",
      build: { write: false },
    });
    const lotes = Array.isArray(salida) ? salida : [salida];
    const trozo = lotes
      .flatMap((l) => ("output" in l ? l.output : []))
      .find((o) => o.type === "chunk" && o.fileName === "embebido.js");
    if (!trozo || trozo.type !== "chunk") throw new Error("embebido.js no se ha construido");
    const etag = `"${createHash("sha256").update(trozo.code).digest("hex").slice(0, 16)}"`;
    hecho = { huella, codigo: trozo.code, etag };
    return hecho;
  }

  return {
    name: "contecrm-embebido",
    apply: "serve",
    configureServer(servidor) {
      servidor.middlewares.use("/embebido.js", (pet, res, siguiente) => {
        if (pet.method !== "GET" && pet.method !== "HEAD") return siguiente();
        construir()
          .then(({ codigo, etag }) => {
            res.setHeader("Access-Control-Allow-Origin", "*");
            res.setHeader("Cross-Origin-Resource-Policy", "cross-origin");
            res.setHeader("X-Content-Type-Options", "nosniff");
            res.setHeader("Cache-Control", "no-cache");
            res.setHeader("ETag", etag);
            if (pet.headers["if-none-match"] === etag) {
              res.statusCode = 304;
              res.end();
              return;
            }
            res.setHeader("Content-Type", "text/javascript; charset=utf-8");
            res.end(pet.method === "HEAD" ? undefined : codigo);
          })
          .catch(siguiente);
      });
    },
  };
}

// La dirección del gateway NO se compila: se lee en ejecución de `/config.json`
// (ver `src/lib/config.ts`). Aquí solo se declara el proxy del servidor de
// desarrollo, para que en local no haga falta CORS.
export default defineConfig({
  plugins: [react(), servirEmbebido()],
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
