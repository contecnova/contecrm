import { defineConfig, devices } from "@playwright/test";

/**
 * Pruebas de pantalla del front oficial.
 *
 * El catálogo declara 53 capacidades de pantalla como hechas y **22 de las 27
 * pantallas no tenían ninguna prueba**. Esto empieza a cerrarlo.
 *
 * Dos decisiones que no son de gusto, las dos por avisos de contecpos, donde un
 * barrido llevaba 83 rutas en verde sin haber mirado una sola pantalla:
 *
 * **`reuseExistingServer: false`.** Reaprovechar un servidor de otra sesión mide
 * otra cosa: la versión que esté levantada, no la que acabas de construir. Y el
 * día que mide bien es casualidad.
 *
 * **Un solo navegador y sin reintentos.** Un reintento que arregla un fallo
 * esconde una pantalla que falla una de cada tres veces, y eso es exactamente lo
 * que un cliente nota y nosotros no.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: true,
  retries: 0,
  // Sin reintentos a propósito: un reintento que arregla un fallo esconde una
  // pantalla que falla una de cada tres veces, y eso es justo lo que nota un
  // cliente y nosotros no. Lo que no se comparte es la máquina — el gate se
  // declara exclusivo en `preflight.py`, con el motivo allí.
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4178",
    trace: "retain-on-failure",
    // El ancho estrecho es el caso que rompe: una tabla de doce columnas o un
    // componente de pestañas se desbordan aquí y no en un portátil.
    viewport: { width: 1280, height: 800 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // Sobre lo CONSTRUIDO y no sobre el servidor de desarrollo: lo que se
    // despliega es `dist`, y es donde aparecen los fallos de construcción.
    // `--host 127.0.0.1` explícito: sin él, `vite preview` escucha en
    // `localhost`, que en esta máquina resuelve a `::1`, y la comprobación
    // contra `127.0.0.1` no conecta nunca. Playwright se queda esperando los
    // tres minutos y dice «se agotó el tiempo del servidor», que manda a buscar
    // al sitio equivocado.
    command: "npm run build && npx vite preview --port 4178 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:4178/",
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
