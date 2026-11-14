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

import { esCancelacion } from "@/lib/cancelacion";
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
    /**
     * Qué campo no vale y por qué, cuando el servidor lo dice.
     *
     * **Se perdía.** La API contesta un 422 con `errors: [{campo, mensaje}]`
     * —«definicion: Field required»— y este constructor se quedaba sólo con
     * el título, «Los datos enviados no son válidos». Así que el formulario
     * enseñaba esa frase y escondía lo único accionable detrás de «Detalle
     * técnico»: quien da de alta un segmento ve que no vale y no sabe qué
     * campo. Medido el 03-11-2026 creando uno.
     */
    readonly campos: { campo: string; mensaje: string }[] = [],
    /**
     * El identificador de la petición que falló (CRM-00.02.04.07).
     *
     * Es lo que cierra el círculo del soporte: el servidor lo pone en el
     * cuerpo del error y en `X-Request-Id`, el mismo que queda en su log y en
     * el audit trail. Se perdía aquí, así que la persona que llamaba a soporte
     * no tenía nada que pegar y la búsqueda empezaba por «¿a qué hora fue?».
     */
    readonly requestId: string = "",
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
  /**
   * `false` para lo que se hace solo, sin que nadie lo pida —apuntar un
   * «visto»—: sin red se pierde y ya, en vez de encolarse como si fuera un
   * cambio de la persona (CRM-06.02.01.04).
   */
  encolable?: boolean;
  /** Interno: ya se pidió volver a verificarse para esta llamada. */
  sinReverificar?: boolean;
  /**
   * `true` para lo que se abre desde un enlace de correo sin haber entrado
   * —confirmar un alta, canjear el enlace del portal de partner—: la llamada
   * sale **sin cookie**. Con la de una sesión caducada en el navegador, el
   * gateway contestaría «tu sesión ha caducado» a quien no necesita ninguna.
   */
  sinCookie?: boolean;
}

/**
 * Quién pide volver a verificarse cuando una operación sensible lo exige
 * (CRM-00.05.01.18). Lo registra el diálogo del marco; devuelve `true` si la
 * persona se ha verificado y la operación se puede repetir.
 *
 * **No existía, ni en el servidor ni aquí.** Crear una clave de API, exportar
 * media base o borrar en bloque contestaban «vuelve a verificarte» y cada
 * pantalla lo enseñaba como un error —«hazlo desde tu perfil»—, sin camino:
 * había que salir y volver a entrar (medido el 10-11-2026). Ahora la llamada
 * se para, se pide el código y se repite una vez.
 */
let reverificar: (() => Promise<boolean>) | null = null;
export function registrarReverificacion(
  pedir: (() => Promise<boolean>) | null,
): void {
  reverificar = pedir;
}

/** Para lo que no pasa por `llamar` (la descarga de un fichero). */
export function pedirReverificacion(): Promise<boolean> {
  return reverificar ? reverificar() : Promise.resolve(false);
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
  /**
   * Campos que vienen TAPADOS, no en claro (`X-Campos-Enmascarados`).
   *
   * Aparte de los retenidos, porque no son lo mismo y la diferencia es justo
   * la que importa: un campo retenido **no viene**, y el hueco se ve; uno
   * enmascarado **viene** y tiene la forma de un dato —«··············tora»
   * ocupa el sitio de un nombre—, así que sin decirlo nadie puede notar que lo
   * que lee no es el valor.
   *
   * Se descubrió el 29-10-2026 con el agente autónomo, que contestó que tres
   * cuentas se llamaban «··············tora», «··cosa» y «·············elta».
   * Le pasa igual a la pantalla y a cualquier integración.
   */
  enmascarados: string[];
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
  fichero: File | Blob | null,
  campos: Record<string, string> = {},
): Promise<T> {
  const cuerpo = new FormData();
  // Sin fichero también: un formulario que admite el audio O su texto.
  if (fichero) cuerpo.append("fichero", fichero);
  for (const [clave, valor] of Object.entries(campos))
    cuerpo.append(clave, valor);

  const respuesta = await conRed(() =>
    fetch(`${config().apiBase}${ruta}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: cuerpo,
      credentials: "include",
    }),
  );
  const texto = await respuesta.text();
  const datos = texto ? seguroJson(texto) : null;
  if (!respuesta.ok)
    throw problema(
      respuesta.status,
      datos,
      respuesta.headers.get("X-Request-Id"),
    );
  return datos as T;
}

/**
 * Qué cliente se está mirando, cuando quien mira opera la plataforma.
 *
 * Vive aquí y en `sessionStorage` por una razón: es una elección de la
 * **pestaña del navegador**, no del usuario ni del servidor. Recargar la
 * mantiene —si no, cada F5 devolvería a quien está revisando un cliente a su
 * propio tenant a mitad de trabajo— y cerrarla la olvida, que es lo correcto
 * para algo que da acceso a datos de otro.
 *
 * No concede nada por sí sola: el servidor sólo la mira si quien la manda es
 * administrador de plataforma. Mandarla siendo otro no hace nada.
 */
const CLAVE_MIRADO = "crm.tenant_mirado";

export function tenantMirado(): string {
  try {
    return sessionStorage.getItem(CLAVE_MIRADO) ?? "";
  } catch {
    // Ventana privada, almacenamiento bloqueado: se mira el propio tenant,
    // que es lo seguro.
    return "";
  }
}

export function mirarTenant(id: string): void {
  try {
    if (id) sessionStorage.setItem(CLAVE_MIRADO, id);
    else sessionStorage.removeItem(CLAVE_MIRADO);
  } catch {
    // Si no se puede guardar, no se finge que se ha cambiado.
  }
}

export async function llamar<T = unknown>(
  ruta: string,
  opciones: Opciones = {},
): Promise<Respuesta<T>> {
  const metodo = (opciones.metodo ?? "GET").toUpperCase();
  const cabeceras: Record<string, string> = { Accept: "application/json" };

  // El cliente que se está mirando, si hay uno elegido. Va en TODAS las
  // llamadas: con ella sólo en algunas, media pantalla hablaría de un cliente
  // y la otra media del propio, que es peor que no poder mirar.
  const mirado = tenantMirado();
  if (mirado) cabeceras["X-CRM-Tenant-Mirado"] = mirado;

  if (opciones.cuerpo !== undefined)
    cabeceras["Content-Type"] = "application/json";
  if (opciones.version) cabeceras["If-Match"] = opciones.version;
  if (ESCRITURAS.has(metodo)) {
    cabeceras["Idempotency-Key"] = opciones.idempotencia ?? crypto.randomUUID();
  }

  const respuesta = await conRed(() =>
    fetch(`${config().apiBase}${ruta}`, {
      method: metodo,
      headers: cabeceras,
      body:
        opciones.cuerpo === undefined
          ? undefined
          : JSON.stringify(opciones.cuerpo),
      // La sesión va en cookie, nunca en un almacén que pueda leer un script
      // (CRM-07.04.02.03): un XSS con el token en `localStorage` es una sesión
      // robada; con cookie `HttpOnly`, no.
      credentials: opciones.sinCookie ? "omit" : "include",
      signal: opciones.signal,
    }),
  ).catch(async (error: unknown) => {
    // Sin red, crear o editar un registro se guarda en el dispositivo y se
    // envía al volver (CRM-06.02.01.04). Se dice con su propio código: no es
    // «no hay servidor», es «guardado aquí, pendiente de subir».
    if (
      error instanceof ErrorApi &&
      error.codigo === "sin_red" &&
      ESCRITURAS.has(metodo) &&
      opciones.encolable !== false
    ) {
      const { encolar } = await import("@/lib/sinConexion");
      const encolada = await encolar({
        metodo,
        ruta,
        cuerpo: opciones.cuerpo,
        version: opciones.version,
        idempotencia: cabeceras["Idempotency-Key"] ?? crypto.randomUUID(),
        mirado,
      });
      if (encolada) throw new ErrorApi(0, "encolada_sin_conexion", "", null);
    }
    throw error;
  });

  if (respuesta.status === 204) {
    return {
      datos: undefined as T,
      version: null,
      retenidos: [],
      enmascarados: [],
    };
  }

  const texto = await respuesta.text();
  const cuerpo = texto ? seguroJson(texto) : null;

  if (!respuesta.ok) {
    const error = problema(
      respuesta.status,
      cuerpo,
      respuesta.headers.get("X-Request-Id"),
    );
    if (
      error.codigo === "stepup.requerido" &&
      reverificar &&
      !opciones.sinReverificar &&
      (await reverificar())
    ) {
      // La misma operación, con la misma clave de idempotencia: si la primera
      // llegó a hacer algo, la segunda no lo repite.
      return llamar<T>(ruta, {
        ...opciones,
        idempotencia: cabeceras["Idempotency-Key"],
        sinReverificar: true,
      });
    }
    throw error;
  }

  return {
    datos: cuerpo as T,
    version: respuesta.headers.get("ETag"),
    retenidos: lista(respuesta.headers.get("X-Campos-Retenidos")),
    enmascarados: lista(respuesta.headers.get("X-Campos-Enmascarados")),
  };
}

/** Una cabecera de nombres separados por coma, como lista limpia. */
function lista(cabecera: string | null): string[] {
  return (cabecera ?? "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);
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

/**
 * Un fallo de red **se marca como tal**, en vez de llegar como un `TypeError`
 * pelado.
 *
 * Sin esto, `fetch` rechaza con un `TypeError` indistinguible de cualquier
 * otro error de JavaScript, y la pantalla de error decidía así: «si no es un
 * `ErrorApi`, es que no hay red». De modo que **un fallo al pintar se
 * anunciaba como "No se ha podido contactar con el servidor"**.
 *
 * Eso no es un matiz: es un diagnóstico que manda a mirar al sitio
 * equivocado. Medido el 01-11-2026 en la ficha de una oportunidad, que llevaba
 * rota quién sabe cuánto: la pantalla entera era una caja roja diciendo que no
 * había servidor, y lo que pasaba es que el front pintaba un objeto donde
 * esperaba un texto. Diez minutos mirando la red.
 *
 * El estado 0 es el convenio de «la petición no llegó a salir».
 */
async function conRed(hacer: () => Promise<Response>): Promise<Response> {
  try {
    return await hacer();
  } catch (error) {
    // Una cancelación NO es un fallo de red: tiene su propio tratamiento en
    // `salvoCancelacion`, y convertirla aquí lo rompería.
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ErrorApi(
      0,
      "sin_red",
      "",
      null,
      String((error as Error)?.message ?? error),
    );
  }
}

export function problema(
  estado: number,
  cuerpo: unknown,
  cabecera: string | null = null,
): ErrorApi {
  const p = (cuerpo ?? {}) as Record<string, unknown>;
  return new ErrorApi(
    estado,
    String(p.error_code ?? p.type ?? ""),
    String(p.title ?? p.detail ?? ""),
    p.detalle ?? p.detail ?? null,
    String(p.detail ?? ""),
    camposDelError(p.errors),
    // El del cuerpo primero: es el que el servicio escribió en su log. La
    // cabecera, si el cuerpo no lo trae —una página de error de un proxy—; y
    // si llegaran varias juntas, la primera.
    String(p.request_id ?? "") || ((cabecera ?? "").split(",")[0] ?? "").trim(),
  );
}

/**
 * Los campos que el servidor señala, limpios de lo que no se lee.
 *
 * El `campo` viene como lo nombra el validador —`query.desde`, `body.nombre`,
 * `definicion`— y lo que el formulario conoce es el nombre a secas. Se queda
 * el último tramo, que es el del campo.
 */
function camposDelError(crudo: unknown): { campo: string; mensaje: string }[] {
  if (!Array.isArray(crudo)) return [];
  const salida: { campo: string; mensaje: string }[] = [];
  for (const fila of crudo) {
    if (!fila || typeof fila !== "object") continue;
    const f = fila as Record<string, unknown>;
    const campo =
      String(f.campo ?? f.loc ?? "")
        .split(".")
        .pop() ?? "";
    const mensaje = String(f.mensaje ?? f.msg ?? f.motivo ?? "");
    if (campo && mensaje) salida.push({ campo, mensaje });
  }
  return salida;
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
    const arrays = Object.values(datos as Record<string, unknown>).filter(
      Array.isArray,
    );
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
    if (esCancelacion(error)) return;
    manejar(error);
  };
}

