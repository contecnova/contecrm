/**
 * Trabajar sin conexión (CRM-06.02.01.04).
 *
 * Medido el 09-11-2026: el servidor sabía detectar un conflicto
 * (`POST /api/v1/:servicio/movil/sincronizar`) y el front no tenía nada sin
 * conexión. Sin red, guardar daba «No se ha podido contactar con el servidor»
 * y lo escrito se perdía al cerrar la pestaña.
 *
 * Tres piezas, y las tres **sólo actúan cuando falla la red**:
 *
 * - El service worker (`/sw.js`) guarda la aplicación y lo consultado, y lo
 *   sirve cuando no hay red. Con red va SIEMPRE a la red primero: un caché que
 *   contesta antes que el servidor enseña datos viejos sin decirlo.
 * - La cola, en IndexedDB: lo que se guarda sin red se queda en el
 *   dispositivo con la versión sobre la que se hizo y lo que se leyó antes.
 * - El envío al volver: por la ruta de sincronización de cada servicio, que
 *   aplica lo que no choca y devuelve los conflictos con lo que hay en el
 *   servidor. Esos los resuelve una persona en «Sin conexión».
 *
 * **Nada se descarta solo.** Lo que falla se queda en la cola con su motivo;
 * tirarlo convierte un problema de red en una pérdida de datos que se descubre
 * semanas después.
 */

import { config } from "@/lib/config";

/** El caché de lo consultado. Lo comparte con `public/sw.js`. */
export const CACHE_CONSULTADO = "crm-consultado-v1";
const BD = "contecrm-sin-conexion";
const ALMACEN = "cola";
const EVENTO = "crm-sin-conexion";

export type EstadoOperacion =
  "pendiente" | "conflicto" | "rechazada" | "enviando";

export interface Conflicto {
  campos: string[];
  /** Lo que hay ahora en el servidor en los campos que chocan. */
  valores_servidor: Record<string, unknown>;
  version_servidor: number;
}

export interface OperacionEncolada {
  id_cliente: string;
  usuario: string;
  tipo: "crear" | "actualizar" | "borrar";
  metodo: string;
  /** La ruta tal cual se pidió: `/api/v1/contacts/…`. */
  ruta: string;
  recurso: string;
  registro_id: string | null;
  servicio: string;
  version_base: number | null;
  /** Lo que se leyó antes de cambiarlo: la base de la fusión de tres puntos. */
  campos_base: Record<string, unknown>;
  campos: Record<string, unknown>;
  encolada_at: string;
  estado: EstadoOperacion;
  motivo?: string;
  conflicto?: Conflicto;
}

/** Dónde vive la cola. IndexedDB en el navegador; en memoria en las pruebas. */
export interface AlmacenCola {
  todas(): Promise<OperacionEncolada[]>;
  poner(op: OperacionEncolada): Promise<void>;
  quitar(id: string): Promise<void>;
}

function abrir(): Promise<IDBDatabase> {
  return new Promise((ok, mal) => {
    const peticion = indexedDB.open(BD, 1);
    peticion.onupgradeneeded = () =>
      peticion.result.createObjectStore(ALMACEN, { keyPath: "id_cliente" });
    peticion.onsuccess = () => ok(peticion.result);
    peticion.onerror = () => mal(peticion.error);
  });
}

async function enTransaccion<T>(
  modo: IDBTransactionMode,
  hacer: (almacen: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const bd = await abrir();
  try {
    return await new Promise<T>((ok, mal) => {
      const peticion = hacer(
        bd.transaction(ALMACEN, modo).objectStore(ALMACEN),
      );
      peticion.onsuccess = () => ok(peticion.result);
      peticion.onerror = () => mal(peticion.error);
    });
  } finally {
    bd.close();
  }
}

export const almacenIndexedDb: AlmacenCola = {
  todas: () => enTransaccion("readonly", (a) => a.getAll()),
  poner: async (op) => {
    await enTransaccion("readwrite", (a) => a.put(op));
  },
  quitar: async (id) => {
    await enTransaccion("readwrite", (a) => a.delete(id));
  },
};

let almacen: AlmacenCola = almacenIndexedDb;
let usuarioActual = "";

/** Para las pruebas: la cola en memoria. */
export function usarAlmacen(otro: AlmacenCola): void {
  almacen = otro;
}

/**
 * Quién está trabajando. La cola es de una persona: lo que encoló otra en el
 * mismo navegador no se envía con esta sesión, porque se escribiría con la
 * identidad de quien no lo hizo.
 */
export function fijarUsuario(id: string): void {
  const cambia = id !== usuarioActual;
  usuarioActual = id;
  if (cambia && id && typeof navigator !== "undefined" && navigator.onLine)
    void sincronizar();
  if (cambia) avisar();
}

function avisar(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(EVENTO));
}

/** Se suscribe a los cambios de la cola. Devuelve cómo darse de baja. */
export function alCambiar(hacer: () => void): () => void {
  window.addEventListener(EVENTO, hacer);
  window.addEventListener("online", hacer);
  window.addEventListener("offline", hacer);
  return () => {
    window.removeEventListener(EVENTO, hacer);
    window.removeEventListener("online", hacer);
    window.removeEventListener("offline", hacer);
  };
}

export async function cola(): Promise<OperacionEncolada[]> {
  try {
    const todas = await almacen.todas();
    return (
      todas
        // Sin saber quién está dentro no se enseña ni se envía nada.
        .filter((op) => usuarioActual && op.usuario === usuarioActual)
        .sort((a, b) => a.encolada_at.localeCompare(b.encolada_at))
    );
  } catch {
    return [];
  }
}

const RE_REGISTRO =
  /^\/api\/v1\/([a-z0-9_-]+)\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;
const RE_COLECCION = /^\/api\/v1\/([a-z0-9_-]+)$/i;

/**
 * Qué servicio guarda una colección, según lo que declara cada pestaña.
 * Vacío si no se sabe: entonces se repite la petición por su ruta con
 * `If-Match`, que también detecta el choque, aunque no por campo.
 */
async function servicioDe(recurso: string): Promise<string> {
  try {
    const { RECURSOS_POR_MODULO } = await import("@/lib/recursos");
    for (const recursos of Object.values(RECURSOS_POR_MODULO)) {
      for (const r of recursos) {
        if (r.listar === `/api/v1/${recurso}` && r.servicio) return r.servicio;
      }
    }
  } catch {
    // Sin la tabla, se usa la ruta de siempre.
  }
  return "";
}

/** La clave con que el service worker guarda una lectura. */
export function claveDeCache(url: string, mirado: string): string {
  const u = new URL(url, location.origin);
  if (mirado) u.searchParams.set("__mirado", mirado);
  return u.toString();
}

/** Lo último leído de un registro, si el service worker lo guardó. */
async function leidoAntes(
  ruta: string,
  mirado: string,
): Promise<{ datos: Record<string, unknown>; version: number | null } | null> {
  try {
    if (typeof caches === "undefined") return null;
    const cache = await caches.open(CACHE_CONSULTADO);
    const r = await cache.match(
      claveDeCache(`${config().apiBase}${ruta}`, mirado),
    );
    if (!r) return null;
    return {
      datos: (await r.json()) as Record<string, unknown>,
      version: versionDe(r.headers.get("ETag")),
    };
  } catch {
    return null;
  }
}

export function versionDe(etag: string | null | undefined): number | null {
  if (!etag) return null;
  const n = Number(etag.replace(/^W\//, "").replace(/"/g, ""));
  return Number.isFinite(n) ? n : null;
}

/**
 * Guarda en la cola una escritura que no pudo salir por falta de red.
 *
 * Devuelve `false` si no se puede encolar con garantías: una acción que no es
 * crear, editar ni borrar un registro, o una edición de la que no se sabe sobre qué
 * versión se hizo — sin eso no se puede detectar un conflicto y el cambio de
 * otra persona desaparecería sin rastro. Entonces sigue el error de siempre.
 */
export async function encolar(peticion: {
  metodo: string;
  ruta: string;
  cuerpo: unknown;
  version?: string;
  idempotencia: string;
  mirado: string;
}): Promise<boolean> {
  const metodo = peticion.metodo.toUpperCase();
  const deRegistro = RE_REGISTRO.exec(peticion.ruta);
  // Borrar no lleva cuerpo: lo que se borra lo dice la ruta.
  const borra = metodo === "DELETE" && Boolean(deRegistro);
  const campos =
    peticion.cuerpo && typeof peticion.cuerpo === "object"
      ? (peticion.cuerpo as Record<string, unknown>)
      : borra
        ? {}
        : null;
  if (!campos || !usuarioActual) return false;
  const deColeccion = RE_COLECCION.exec(peticion.ruta);
  let op: OperacionEncolada;
  const comun = {
    id_cliente: peticion.idempotencia,
    usuario: usuarioActual,
    metodo,
    ruta: peticion.ruta,
    campos,
    encolada_at: new Date().toISOString(),
    estado: "pendiente" as const,
  };
  if (deRegistro && (metodo === "PATCH" || metodo === "PUT")) {
    const leido = await leidoAntes(peticion.ruta, peticion.mirado);
    const version = versionDe(peticion.version) ?? leido?.version ?? null;
    if (version === null) return false;
    // Sólo lo que de verdad cambió. Un formulario manda el registro entero, y
    // reenviarlo pisaría con valores viejos lo que otra persona cambió en los
    // campos que aquí ni se tocaron.
    const base: Record<string, unknown> = {};
    const cambios: Record<string, unknown> = {};
    for (const [c, v] of Object.entries(campos)) {
      if (leido && c in leido.datos) {
        if (JSON.stringify(leido.datos[c]) === JSON.stringify(v)) continue;
        base[c] = leido.datos[c];
      }
      cambios[c] = v;
    }
    // Nada que enviar: no hay nada que perder.
    if (!Object.keys(cambios).length) return true;
    op = {
      ...comun,
      campos: cambios,
      tipo: "actualizar",
      recurso: deRegistro[1] ?? "",
      registro_id: deRegistro[2] ?? null,
      servicio: await servicioDe(deRegistro[1] ?? ""),
      version_base: version,
      campos_base: base,
    };
  } else if (borra && deRegistro) {
    // Borrar sin red (CRM-06.02.01.04). Con la versión leída, si la hay: al
    // volver, si otra persona cambió el registro entre medias, el servidor
    // contesta con un choque y se pregunta antes de borrar lo que no se vio.
    // Sin versión se borra igual: va a la papelera y se recupera desde allí.
    const leido = await leidoAntes(peticion.ruta, peticion.mirado);
    op = {
      ...comun,
      campos: {},
      tipo: "borrar",
      recurso: deRegistro[1] ?? "",
      registro_id: deRegistro[2] ?? null,
      servicio: "",
      version_base: versionDe(peticion.version) ?? leido?.version ?? null,
      campos_base: {},
    };
  } else if (deColeccion && metodo === "POST") {
    op = {
      ...comun,
      tipo: "crear",
      recurso: deColeccion[1] ?? "",
      registro_id: null,
      servicio: "",
      version_base: null,
      campos_base: {},
    };
  } else {
    return false;
  }
  try {
    await almacen.poner(op);
  } catch {
    return false;
  }
  avisar();
  return true;
}

export async function descartar(id: string): Promise<void> {
  await almacen.quitar(id);
  avisar();
}

/**
 * Resuelve un conflicto campo a campo: `true` es quedarse con lo mío.
 *
 * Lo que se elige del servidor sale del cambio; lo mío se vuelve a enviar
 * sobre la versión que hay AHORA y con lo que hay ahora como base, así que ya
 * no choca. Si todo se queda como en el servidor, no hay nada que enviar.
 */
export async function resolver(
  op: OperacionEncolada,
  quedarmeConLoMio: Record<string, boolean>,
): Promise<void> {
  const choque = op.conflicto;
  if (!choque) return;
  // Un borrado que chocó no tiene campos que elegir: resolverlo es decidir
  // borrar igualmente, sobre la versión que hay ahora.
  if (op.tipo === "borrar") {
    await almacen.poner({
      ...op,
      version_base: choque.version_servidor,
      estado: "pendiente",
      conflicto: undefined,
      motivo: undefined,
    });
    avisar();
    return;
  }
  const campos: Record<string, unknown> = {};
  const base: Record<string, unknown> = { ...op.campos_base };
  for (const [c, v] of Object.entries(op.campos)) {
    if (choque.campos.includes(c)) {
      if (!quedarmeConLoMio[c]) continue;
      base[c] = choque.valores_servidor[c];
    }
    campos[c] = v;
  }
  if (!Object.keys(campos).length) {
    await descartar(op.id_cliente);
    return;
  }
  await almacen.poner({
    ...op,
    campos,
    campos_base: base,
    version_base: choque.version_servidor,
    estado: "pendiente",
    conflicto: undefined,
    motivo: undefined,
  });
  avisar();
}

type Enviar = (
  ruta: string,
  init: {
    metodo: string;
    cuerpo?: unknown;
    cabeceras?: Record<string, string>;
  },
) => Promise<{ ok: boolean; estado: number; datos: unknown }>;

/** El envío de verdad, sin pasar por `llamar`: si fallara la red, volvería a encolar. */
const enviarPorRed: Enviar = async (ruta, init) => {
  const r = await fetch(`${config().apiBase}${ruta}`, {
    method: init.metodo,
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(init.cabeceras ?? {}),
    },
    body: init.cuerpo === undefined ? undefined : JSON.stringify(init.cuerpo),
  });
  // Un servicio caído o reiniciándose (5xx) no es un rechazo: lo que se
  // mandaba sigue pendiente, como si no hubiera red.
  if (r.status >= 500) throw new Error(`servicio no disponible: ${r.status}`);
  const texto = await r.text();
  let datos: unknown = null;
  try {
    datos = texto ? JSON.parse(texto) : null;
  } catch {
    datos = { detail: texto.slice(0, 300) };
  }
  return { ok: r.ok, estado: r.status, datos };
};

function motivoDe(datos: unknown): string {
  const d = datos as { detail?: unknown; title?: unknown } | null;
  return String(d?.detail ?? d?.title ?? "");
}

export interface Resultado {
  enviadas: number;
  conflictos: number;
  rechazadas: number;
  sinRed: boolean;
}

let enCurso: Promise<Resultado> | null = null;

/**
 * Envía la cola. Una sola pasada a la vez: dos pasadas solapadas mandarían la
 * misma operación dos veces (el servidor lo aguanta por la clave de
 * idempotencia, pero la pantalla contaría doble).
 */
export function sincronizar(enviar: Enviar = enviarPorRed): Promise<Resultado> {
  enCurso ??= pasada(enviar)
    .then((res) => {
      // Al volver la red, la primera petición falla a menudo —la conexión aún
      // no está— o el servicio se está reiniciando. Se reintenta solo: sin
      // esto, lo pendiente esperaba al siguiente corte de red para subir.
      if (res.sinRed && navigator.onLine)
        setTimeout(
          () => void sincronizar(enviar),
          config().sinConexionReintentoMs,
        );
      return res;
    })
    .finally(() => {
      enCurso = null;
      avisar();
    });
  return enCurso;
}

async function pasada(enviar: Enviar): Promise<Resultado> {
  const res: Resultado = {
    enviadas: 0,
    conflictos: 0,
    rechazadas: 0,
    sinRed: false,
  };
  const pendientes = (await cola()).filter((op) => op.estado === "pendiente");
  if (!pendientes.length) return res;

  const marcar = async (
    op: OperacionEncolada,
    cambios: Partial<OperacionEncolada>,
  ) => {
    await almacen.poner({ ...op, ...cambios });
  };

  /** Por la ruta de siempre, con `If-Match`: el servidor dice si chocó. */
  const porSuRuta = async (op: OperacionEncolada, version: number | null) => {
    const borra = op.tipo === "borrar";
    const r = await enviar(op.ruta, {
      metodo: op.metodo,
      cuerpo: borra ? undefined : op.campos,
      cabeceras: {
        "Idempotency-Key": op.id_cliente,
        ...(version !== null ? { "If-Match": `W/"${version}"` } : {}),
      },
    });
    if (r.ok || (borra && (r.estado === 404 || r.estado === 410))) {
      // Borrar lo que ya no está consigue lo que se pedía: no es un rechazo.
      await almacen.quitar(op.id_cliente);
      res.enviadas += 1;
    } else if (r.estado === 409 || r.estado === 412) {
      // Chocó con un cambio de otra persona. Se lee lo que hay para que la
      // pantalla enseñe los dos valores, no sólo la palabra «conflicto».
      const actual = await enviar(op.ruta, { metodo: "GET" });
      const datos = (actual.datos ?? {}) as Record<string, unknown>;
      await marcar(op, {
        estado: "conflicto",
        conflicto: {
          campos: Object.keys(op.campos),
          valores_servidor: Object.fromEntries(
            Object.keys(op.campos).map((c) => [c, datos[c]]),
          ),
          version_servidor: Number(datos.version ?? version ?? 0),
        },
      });
      res.conflictos += 1;
    } else {
      await marcar(op, { estado: "rechazada", motivo: motivoDe(r.datos) });
      res.rechazadas += 1;
    }
  };

  try {
    for (const op of pendientes.filter(
      (o) => o.tipo === "crear" || o.tipo === "borrar" || !o.servicio,
    )) {
      await porSuRuta(op, op.version_base);
    }

    const porServicio = new Map<string, OperacionEncolada[]>();
    for (const op of pendientes)
      if (op.tipo === "actualizar" && op.servicio)
        porServicio.set(op.servicio, [
          ...(porServicio.get(op.servicio) ?? []),
          op,
        ]);

    for (const [servicio, ops] of porServicio) {
      const r = await enviar(`/api/v1/${servicio}/movil/sincronizar`, {
        metodo: "POST",
        cuerpo: {
          aplicar: true,
          operaciones: ops.map((op) => ({
            id_cliente: op.id_cliente,
            tipo: op.tipo,
            recurso: op.recurso,
            registro_id: op.registro_id,
            version_base: op.version_base,
            campos_base: op.campos_base,
            campos: op.campos,
            encolada_at: op.encolada_at,
          })),
        },
      });
      if (!r.ok) {
        for (const op of ops)
          await marcar(op, { estado: "rechazada", motivo: motivoDe(r.datos) });
        res.rechazadas += ops.length;
        continue;
      }
      const plan = (r.datos as { plan?: Record<string, unknown>[] }).plan ?? [];
      for (const entrada of plan) {
        const op = ops.find((o) => o.id_cliente === entrada.id_cliente);
        if (!op) continue;
        switch (entrada.accion) {
          case "aplicada":
            await almacen.quitar(op.id_cliente);
            res.enviadas += 1;
            break;
          case "aplicar_por_su_ruta":
          case "aplicar":
            await porSuRuta(
              op,
              Number(entrada.version_actual ?? op.version_base),
            );
            break;
          case "otro_servicio":
            await porSuRuta(op, op.version_base);
            break;
          case "conflicto":
            await marcar(op, {
              estado: "conflicto",
              conflicto: {
                campos: (entrada.campos as string[]) ?? [],
                valores_servidor:
                  (entrada.valores_servidor as Record<string, unknown>) ?? {},
                version_servidor: Number(entrada.version_servidor ?? 0),
              },
            });
            res.conflictos += 1;
            break;
          default:
            await marcar(op, {
              estado: "rechazada",
              motivo: String(entrada.porque ?? entrada.accion ?? ""),
            });
            res.rechazadas += 1;
        }
      }
    }
  } catch {
    // Se fue la red a mitad, o el servicio no contesta: lo que no se envió
    // sigue pendiente.
    res.sinRed = true;
  }
  return res;
}

/**
 * Registra el service worker y la sincronización al volver la red.
 *
 * El service worker es de red primero también en desarrollo: con Vite
 * levantado, cada petición va al servidor como siempre y lo guardado sólo se
 * usa cuando la red falla.
 */
export function iniciarSinConexion(): void {
  if (typeof window === "undefined") return;
  if ("serviceWorker" in navigator) {
    // Sin service worker (contexto no seguro, navegador que lo bloquea) la
    // aplicación funciona igual con red; lo único que se pierde es trabajar
    // sin ella, y eso no es un fallo que enseñar al arrancar.
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  }
  // La primera pasada la lanza `fijarUsuario`, cuando ya se sabe quién entró.
  window.addEventListener("online", () => void sincronizar());
  // La pantalla «Sin conexión» se carga aparte, al abrirla. Sin pedirla antes
  // con red, sin red no se podía abrir —justo cuando hace falta—: medido el
  // 10-11-2026, «Failed to fetch dynamically imported module». Se pide aquí
  // con red y el service worker la guarda con el resto de la aplicación.
  if (navigator.onLine)
    void import("@/paginas/SinConexion").catch(() => undefined);
}

/**
 * Al salir: se olvida lo consultado. El caché del dispositivo es de quien
 * entró, y el siguiente que entre en este navegador no tiene por qué verlo.
 */
export async function olvidarLoConsultado(): Promise<void> {
  try {
    if (typeof caches !== "undefined") await caches.delete(CACHE_CONSULTADO);
  } catch {
    // Si no se puede, el service worker lo sustituye en la siguiente lectura.
  }
}
