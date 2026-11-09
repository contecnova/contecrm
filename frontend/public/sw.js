/*
 * Service worker de la aplicación (CRM-06.02.01.04, trabajar sin conexión).
 *
 * **Red primero, siempre.** Con red, cada petición va al servidor como si este
 * fichero no existiera; lo guardado SÓLO se sirve cuando la red falla. Un caché
 * que contesta antes que el servidor enseña datos viejos sin decirlo, y en un
 * CRM eso es llamar a un cliente por una oportunidad que ya se cerró.
 *
 * Qué se guarda: la aplicación (el documento, sus scripts y estilos) y las
 * LECTURAS de la API que devuelven JSON. Nada de lo que escribe: las
 * escrituras sin red las guarda la cola de `src/lib/sinConexion.ts`, que sabe
 * sobre qué versión se hicieron. Tampoco los flujos (`text/event-stream`), que
 * no terminan, ni las descargas.
 *
 * Lo servido desde aquí lleva `X-CRM-Sin-Conexion: 1`, para que quien lo pinte
 * pueda decir que no es de ahora.
 *
 * La clave de una lectura de la API lleva el cliente que se está mirando
 * (`X-CRM-Tenant-Mirado`): la misma URL devuelve cosas distintas según a quién
 * se mira, y servir la de otro sería enseñar los datos de otra empresa.
 */

const CACHE_APP = "crm-app-v1";
const CACHE_CONSULTADO = "crm-consultado-v1";
const PROPIOS = [CACHE_APP, CACHE_CONSULTADO];

self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches
      .open(CACHE_APP)
      .then((c) => c.add("/"))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches
      .keys()
      .then((claves) =>
        Promise.all(
          claves
            .filter((k) => k.startsWith("crm-") && !PROPIOS.includes(k))
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

function claveDe(peticion) {
  const url = new URL(peticion.url);
  const mirado = peticion.headers.get("X-CRM-Tenant-Mirado");
  if (mirado) url.searchParams.set("__mirado", mirado);
  return url.toString();
}

function guardable(respuesta, esApi) {
  if (!respuesta || !respuesta.ok || respuesta.status !== 200) return false;
  if (respuesta.redirected || respuesta.type === "opaque") return false;
  const tipo = respuesta.headers.get("Content-Type") || "";
  if (tipo.includes("text/event-stream")) return false;
  if (
    (respuesta.headers.get("Content-Disposition") || "").includes("attachment")
  )
    return false;
  return esApi ? tipo.includes("application/json") : true;
}

function marcada(respuesta) {
  const cabeceras = new Headers(respuesta.headers);
  cabeceras.set("X-CRM-Sin-Conexion", "1");
  return respuesta.blob().then(
    (cuerpo) =>
      new Response(cuerpo, {
        status: respuesta.status,
        statusText: respuesta.statusText,
        headers: cabeceras,
      }),
  );
}

self.addEventListener("fetch", (evento) => {
  const peticion = evento.request;
  if (peticion.method !== "GET") return;
  const url = new URL(peticion.url);
  if (url.origin !== self.location.origin) return;
  if ((peticion.headers.get("Accept") || "").includes("text/event-stream"))
    return;
  const esApi = url.pathname.startsWith("/api/");
  // También lo de Vite en desarrollo (`/@vite/client`, `/@react-refresh`):
  // cada módulo lo importa, y sin ello la aplicación no arranca sin red. Con
  // red no cambia nada, porque va a la red primero.

  const cacheNombre = esApi ? CACHE_CONSULTADO : CACHE_APP;
  const clave = esApi ? claveDe(peticion) : peticion.url;

  evento.respondWith(
    fetch(peticion)
      .then((respuesta) => {
        if (guardable(respuesta, esApi)) {
          const copia = respuesta.clone();
          evento.waitUntil(
            caches
              .open(cacheNombre)
              .then((c) => c.put(clave, copia))
              .catch(() => undefined),
          );
        }
        return respuesta;
      })
      .catch(async () => {
        const cache = await caches.open(cacheNombre);
        const guardada = await cache.match(clave);
        if (guardada) return marcada(guardada);
        // Una pantalla que no se abrió nunca: el documento de la aplicación,
        // que la pinta y dice que no hay red, en vez del dinosaurio.
        if (peticion.mode === "navigate") {
          const app = await caches.open(CACHE_APP);
          const raiz =
            (await app.match(peticion.url)) || (await app.match("/"));
          if (raiz) return raiz;
        }
        return Response.error();
      }),
  );
});

self.addEventListener("message", (evento) => {
  if (evento.data === "olvidar") void caches.delete(CACHE_CONSULTADO);
});
