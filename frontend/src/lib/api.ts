/**
 * El único sitio por el que este front habla con el CRM (CRM-07.04.02.06).
 *
 * Tres cosas que no son opcionales y por eso están aquí y no repartidas:
 *
 * **Los errores llegan como Problem Details (RFC 9457)** y se convierten en un
 * objeto con `codigo` y `detalle`. Sin eso, cada pantalla interpretaría el
 * cuerpo del error a su manera y el mensaje que ve el usuario dependería de
 * quién escribió la pantalla.
 *
 * **Las escrituras llevan clave de idempotencia** (CRM-07.04.02.06). Un `POST`
 * que se reintenta porque la red falló a mitad no puede crear dos registros, y
 * quien reintenta no es la persona: es el navegador, el móvil que recupera
 * cobertura o el propio usuario dando dos veces al botón.
 *
 * **La concurrencia se resuelve con `ETag`/`If-Match`.** Dos personas editando
 * la misma ficha tienen que enterarse, no pisarse. El conflicto llega como un
 * error 412 con su código, y la pantalla decide qué enseñar.
 *
 * Lo que este módulo NO hace, y es deliberado: no decide permisos, no calcula
 * nada de negocio y no guarda datos de negocio en el navegador. Hay un gate que
 * lo comprueba.
 */

import { config } from "@/lib/config";

export class ErrorApi extends Error {
  constructor(
    readonly estado: number,
    readonly codigo: string,
    readonly titulo: string,
    readonly detalle: unknown,
    /** La frase del servidor. En esta API está escrita para leerse, no para
     * depurar: «El motor analítico no pudo resolver el informe: …» dice qué
     * pasó y dónde mirar, y sustituirla por un texto genérico del front tira
     * justo lo que ayuda. */
    readonly explicacion: string = "",
  ) {
    super(titulo || `Error ${estado}`);
    this.name = "ErrorApi";
  }

  /** Si el registro ha cambiado debajo mientras se editaba.
   *
   * Por el CÓDIGO, no por el estado. Aquí valía cualquier 409, y 409 es el
   * conflicto genérico de esta API: lo usan «el motor no pudo resolver el
   * informe», «ese informe lo usa un cuadro» y «eso ya está en la papelera».
   * Los tres salían en pantalla como «alguien ha cambiado este registro
   * mientras lo editabas», que manda a recargar y volver a intentarlo — y
   * ninguno se arregla así. Se vio en el cuadro de mando: seis componentes con
   * un fallo del motor analítico, los seis diciendo que otro los había tocado.
   */
  get esConflictoDeVersion(): boolean {
    return this.estado === 412 || this.codigo === "conflicto_de_version";
  }

  /** Si lo impide una política de acceso, y no la falta de permiso del rol. */
  get esPoliticaDeAcceso(): boolean {
    return this.codigo === "abac.denegado";
  }
}

export interface Opciones {
  metodo?: string;
  cuerpo?: unknown;
  /** Versión que se está editando, para `If-Match`. */
  version?: string;
  /** Reutilizar una clave concreta al reintentar la MISMA operación. */
  idempotencia?: string;
  signal?: AbortSignal;
}

/** Métodos que crean o cambian algo, y por tanto necesitan protección. */
const ESCRITURAS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export interface Respuesta<T> {
  datos: T;
  /** Versión del recurso, para mandarla de vuelta al guardar. */
  version: string | null;
  /**
   * Campos que el servidor ha retenido por permisos (`X-Campos-Retenidos`).
   *
   * Se expone porque el usuario tiene que poder distinguir «este campo está
   * vacío» de «este campo no te lo doy»: son dos cosas distintas y llevan a
   * acciones distintas —rellenarlo o pedir acceso—.
   */
  retenidos: string[];
}

/**
 * Sube un fichero. Va aparte porque el cuerpo no es JSON.
 *
 * Se manda `FormData` **sin** fijar `Content-Type`: el navegador tiene que
 * ponerlo él con el separador del multipart, y fijarlo a mano produce un cuerpo
 * que el servidor no sabe partir — un fallo que se lee como «fichero corrupto»
 * y no como «cabecera mal puesta».
 */
export async function subir<T = unknown>(
  ruta: string,
  fichero: File,
  campos: Record<string, string> = {},
): Promise<T> {
  const cuerpo = new FormData();
  cuerpo.append("fichero", fichero);
  for (const [clave, valor] of Object.entries(campos)) cuerpo.append(clave, valor);

  const respuesta = await fetch(`${config().apiBase}${ruta}`, {
    method: "POST",
    headers: { Accept: "application/json", "Idempotency-Key": crypto.randomUUID() },
    body: cuerpo,
    credentials: "include",
  });
  const texto = await respuesta.text();
  const datos = texto ? seguroJson(texto) : null;
  if (!respuesta.ok) throw problema(respuesta.status, datos);
  return datos as T;
}

export async function llamar<T = unknown>(ruta: string, opciones: Opciones = {}): Promise<Respuesta<T>> {
  const metodo = (opciones.metodo ?? "GET").toUpperCase();
  const cabeceras: Record<string, string> = { Accept: "application/json" };

  if (opciones.cuerpo !== undefined) cabeceras["Content-Type"] = "application/json";
  if (opciones.version) cabeceras["If-Match"] = opciones.version;
  if (ESCRITURAS.has(metodo)) {
    cabeceras["Idempotency-Key"] = opciones.idempotencia ?? crypto.randomUUID();
  }

  const respuesta = await fetch(`${config().apiBase}${ruta}`, {
    method: metodo,
    headers: cabeceras,
    body: opciones.cuerpo === undefined ? undefined : JSON.stringify(opciones.cuerpo),
    // La sesión va en cookie, nunca en un almacén que pueda leer un script
    // (CRM-07.04.02.03): un XSS con el token en `localStorage` es una sesión
    // robada; con cookie `HttpOnly`, no.
    credentials: "include",
    signal: opciones.signal,
  });

  if (respuesta.status === 204) {
    return { datos: undefined as T, version: null, retenidos: [] };
  }

  const texto = await respuesta.text();
  const cuerpo = texto ? seguroJson(texto) : null;

  if (!respuesta.ok) {
    throw problema(respuesta.status, cuerpo);
  }

  return {
    datos: cuerpo as T,
    version: respuesta.headers.get("ETag"),
    retenidos: (respuesta.headers.get("X-Campos-Retenidos") ?? "")
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean),
  };
}

function seguroJson(texto: string): unknown {
  try {
    return JSON.parse(texto);
  } catch {
    // Un cuerpo que no es JSON casi siempre es una página de error de un proxy
    // por delante del gateway. Se devuelve como texto en vez de romper, para
    // que el mensaje que llegue diga algo.
    return { detail: texto.slice(0, 500) };
  }
}

function problema(estado: number, cuerpo: unknown): ErrorApi {
  const p = (cuerpo ?? {}) as Record<string, unknown>;
  return new ErrorApi(
    estado,
    String(p.error_code ?? p.type ?? ""),
    String(p.title ?? p.detail ?? ""),
    p.detalle ?? p.detail ?? null,
    String(p.detail ?? ""),
  );
}

/**
 * Las filas de una respuesta de listado, venga como venga.
 *
 * La API devuelve dos formas: unos extremos dan el array pelado y otros una
 * página `{items, siguiente, hay_mas}`. Que convivan las dos no es un
 * despiste puntual —la paginación por cursor se fue añadiendo por recursos— y
 * obligar a cada pantalla a saber cuál le toca garantiza que alguna se
 * equivoque. Cuando se equivoca no sale un error legible: sale
 * `datos.map is not a function` y **la pantalla entera se queda en blanco**.
 * Pasó en conocimiento y en marketing en cuanto sus extremos dejaron de dar
 * 405 y empezaron a devolver una página.
 *
 * Aquí se normaliza en un solo sitio. Y si llega algo que no es ninguna de las
 * dos cosas, se devuelve lista vacía en vez de reventar: una pantalla vacía es
 * recuperable, una pantalla en blanco no.
 */
export function filas<T>(datos: unknown): T[] {
  if (Array.isArray(datos)) return datos as T[];
  if (datos && typeof datos === "object") {
    const items = (datos as { items?: unknown }).items;
    if (Array.isArray(items)) return items as T[];
    // Y una tercera forma, que había que medir para verla: cuarenta extremos
    // devuelven su lista bajo **su propio nombre** —`{partners: […]}`,
    // `{ordenes: […]}`, `{fondos: […]}`—. El front solo entendía `items`, así
    // que esas cuarenta pantallas salían vacías tuvieran datos o no, y sin
    // decir por qué: no es un error, es una lista que nadie encuentra.
    //
    // Se coge cuando hay **una sola** propiedad que sea un array. Con dos no se
    // adivina —`{metricas: […], sin_dueno: […]}` podría ser cualquiera de las
    // dos— y elegir mal enseñaría una lista equivocada, que es peor que no
    // enseñar ninguna.
    const arrays = Object.values(datos as Record<string, unknown>).filter(Array.isArray);
    if (arrays.length === 1) return arrays[0] as T[];
  }
  return [];
}

/** El cursor de la página siguiente, o cadena vacía si no hay más. */
export function siguientePagina(datos: unknown): string {
  if (datos && typeof datos === "object") {
    const s = (datos as { siguiente?: unknown }).siguiente;
    if (typeof s === "string") return s;
  }
  return "";
}

/**
 * Un `catch` que no confunde «me han cancelado» con «el servidor no contesta».
 *
 * Cuando una pantalla se desmonta —o React vuelve a ejecutar el efecto, que en
 * desarrollo lo hace **siempre** dos veces— el `AbortController` cancela la
 * petición en vuelo. Eso llega al `catch` como un error, y las pantallas lo
 * pintaban como «No se ha podido contactar con el servidor»: un aviso rojo, en
 * grande, para algo que no ha fallado. La consola de administración lo enseñaba
 * en cada carga.
 *
 *     .catch(salvoCancelacion(setFallo))
 */
export function salvoCancelacion(manejar: (error: unknown) => void) {
  return (error: unknown) => {
    const cancelada =
      (error instanceof DOMException && error.name === "AbortError") ||
      (error instanceof Error && error.name === "AbortError");
    if (cancelada) return;
    manejar(error);
  };
}
