/**
 * El esquema de cada operación, sacado del OpenAPI (CRM-07.04.04.04).
 *
 * Los formularios de la aplicación se generan de aquí. La alternativa —escribir
 * a mano el formulario de cada recurso— produce dos definiciones del mismo
 * objeto que se separan en cuanto alguien añade un campo al servicio: el
 * formulario deja de ofrecerlo y nadie se entera hasta que falta el dato.
 *
 * Se lee el OpenAPI del **servicio dueño**, no uno agregado: cada servicio
 * publica el suyo y no hay ninguno que los junte, porque juntarlos obligaría a
 * resolver colisiones de nombres de esquema entre servicios que no se conocen.
 */

import { llamar } from "@/lib/api";
// Una sola `humanizar` en todo el front. Había dos, idénticas, en
// `formato.ts` y aquí: la de allí aprendió a escribir en castellano y la
// de aquí se quedó poniendo «Sector codigo» en los rótulos de formulario.
import { comoRotulo, humanizar } from "@/lib/formato";

export interface CampoEsquema {
  nombre: string;
  /**
   * Cómo se edita, no de qué tipo es en JSON.
   *
   * `etiquetas` y `lista_multiple` existen porque antes **todo lo que fuera
   * array o objeto se pintaba como un textarea de JSON**, y el resultado era
   * pedirle a una persona que escribiera `["a","b"]` a mano —o peor, que lo
   * separara por comas y esperara acertar—. Eso no es un formulario: es una
   * consola con otro nombre.
   */
  tipo:
    | "texto"
    | "texto_largo"
    | "numero"
    | "booleano"
    | "fecha"
    | "lista"
    | "lista_multiple"
    | "etiquetas"
    /**
     * Una lista de cosas con estructura: las líneas de una oferta, los campos
     * de una landing. Antes caían en `objeto` y se pintaban como un textarea
     * de JSON, es decir, se le pedía a quien hace un presupuesto que escribiera
     * `[{"referencia":"L1","precio_venta":1000,…}]` a mano y sin equivocarse.
     */
    | "lineas"
    | "objeto";
  obligatorio: boolean;
  titulo: string;
  descripcion: string;
  opciones: string[];
  maximo: number | null;
  formato: string;
  /** Columnas de cada línea, cuando el campo es una lista de cosas con estructura. */
  subcampos: CampoEsquema[];
  /**
   * A qué objeto apunta este campo, dicho por el servidor.
   *
   * Lo declara la columna y viaja en el contrato porque **no siempre se puede
   * adivinar del nombre**: `origen_id` y `destino_id` del mapa de personas
   * apuntan a contactos, y `anotada_por_id` a un usuario. Sin esto salían como
   * tres identificadores que nadie puede leer ni escribir.
   */
  referencia: string;
  /**
   * Este campo **es el cuerpo entero**, no una propiedad dentro de él.
   *
   * Hay operaciones cuyo cuerpo es un objeto abierto a propósito: «a qué
   * proveedor iría este encargo» lleva lo propio del sector (`bultos`,
   * `peso_kg`, `destino_cp`) y «a qué territorio va esta cuenta» lleva los
   * atributos que miren las reglas de cada instalación. Fijarles un modelo
   * sería estrechar algo que está abierto porque tiene que estarlo.
   *
   * Sin esto, esas operaciones salían con **cero campos**, y un botón sin
   * formulario mandaba `{}`: «a qué proveedor iría este encargo» sin encargo.
   * Medido el 04-11-2026: son 10 en toda la API, 5 de ellas simulaciones que
   * alguien quiere poder usar.
   */
  cuerpoEntero?: boolean;
}

interface Esquema {
  type?: string;
  /** A qué objeto apunta, si el servidor lo dice. */
  referencia?: string;
  properties?: Record<string, Esquema>;
  required?: string[];
  title?: string;
  description?: string;
  enum?: unknown[];
  maxLength?: number;
  format?: string;
  items?: Esquema;
  anyOf?: Esquema[];
  $ref?: string;
}

export interface Documento {
  paths?: Record<string, Record<string, unknown>>;
  components?: { schemas?: Record<string, Esquema> };
}

const cache = new Map<string, Promise<Documento>>();

export function contratoDe(servicio: string): Promise<Documento> {
  const existente = cache.get(servicio);
  if (existente) return existente;
  // Por `/contrato/{servicio}` y no por `/{servicio}/openapi.json`: el gateway
  // enruta por una lista blanca de prefijos y el nombre del servicio no está en
  // ella, así que aquello devolvía 404 siempre. El `catch` se lo tragaba y
  // todos los formularios de alta salían vacíos sin que nada lo dijera.
  const promesa = llamar<Documento>(`/api/v1/contrato/${servicio}`)
    .then((r) => r.datos)
    .catch(() => ({}) as Documento);
  cache.set(servicio, promesa);
  return promesa;
}

/**
 * ¿El servidor admite este método en esta ruta?
 *
 * Se pregunta al contrato en vez de declararlo en `modulos.ts` porque el
 * contrato es el que manda: una pantalla que ofrece un alta que la API no
 * acepta miente, y una que esconde un alta que la API sí acepta deja la
 * capacidad sin usar. Declararlo a mano garantizaba una de las dos, y el
 * recuento decía cuál: 64 listados tenían POST y ningún botón.
 */
export function admite(documento: Documento, ruta: string, metodo: string): boolean {
  const plantilla = plantillaDe(documento, ruta);
  return Boolean(plantilla && documento.paths?.[plantilla]?.[metodo.toLowerCase()]);
}

/**
 * Con qué plantilla del contrato se corresponde una ruta concreta.
 *
 * Buscar la ruta tal cual solo acierta cuando el listado no lleva ningún
 * parámetro dentro. `/sales/vocabularios/motivos_perdida` se declara como
 * `/sales/vocabularios/{nombre}`, y buscándola literalmente no aparecía: la
 * pantalla salía sin botón de alta y sin poder abrir una fila, aunque el
 * servidor admitiera las dos cosas.
 *
 * Se compara tramo a tramo y un tramo `{…}` vale por cualquiera. Entre varias
 * que encajen gana la que tenga menos parámetros, que es la más específica: con
 * `/tenants/{id}` y `/tenants/{slug}` da igual, pero con una ruta literal y una
 * con parámetro no, y quedarse con la del parámetro enseñaría el formulario
 * equivocado.
 */
export function plantillaDe(documento: Documento, ruta: string): string | null {
  const paths = documento.paths ?? {};
  if (paths[ruta]) return ruta;
  const tramos = (ruta.split("?")[0] ?? "").split("/");
  let mejor: string | null = null;
  let menos = Number.POSITIVE_INFINITY;
  for (const candidata of Object.keys(paths)) {
    const suyos = candidata.split("/");
    if (suyos.length !== tramos.length) continue;
    let parametros = 0;
    let encaja = true;
    for (let i = 0; i < suyos.length; i += 1) {
      const suyo = suyos[i] ?? "";
      if (suyo.startsWith("{") && suyo.endsWith("}")) parametros += 1;
      else if (suyo !== tramos[i]) {
        encaja = false;
        break;
      }
    }
    if (encaja && parametros < menos) {
      mejor = candidata;
      menos = parametros;
    }
  }
  return mejor;
}

/**
 * La ruta de la ficha de un listado, tal como la escribe el contrato.
 *
 * No se compone como `${listar}/{id}`: cada servicio nombra el parámetro por su
 * objeto —`{oportunidad_id}`, `{caso_id}`— y buscando `{id}` no se encontraba
 * ninguna. Eso se notaba al editar: el formulario salía sin campos, porque los
 * campos se leen del esquema de esa operación y la operación no aparecía.
 */
export function fichaDe(documento: Documento, listar: string): string | null {
  const base = plantillaDe(documento, listar) ?? listar;
  const patron = new RegExp(`^${base.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/\\{[a-z_]+\\}$`);
  for (const [ruta, operaciones] of Object.entries(documento.paths ?? {})) {
    // Con `get`: una ficha es algo que se **lee**. Sin comprobarlo, cualquier
    // ruta de un registro valía —`POST /duplicados/cola/{id}` es decidir una
    // pareja, no abrirla—, la fila se enlazaba y al pulsarla el servidor
    // contestaba 405 «método no permitido», que no le dice nada a nadie.
    if (patron.test(ruta) && operaciones.get) return ruta;
  }
  return null;
}

/**
 * Campos del cuerpo que espera una operación.
 *
 * Devuelve lista vacía cuando no hay esquema, y quien la use tiene que
 * enseñarlo: un formulario vacío presentado como «este recurso no pide nada»
 * haría crear registros incompletos sin que nadie lo notara.
 */
/**
 * El alta de una colección cuando el servidor la hace con `PUT` por clave.
 *
 * **Hay recursos que no se crean con un `POST` a la colección**: se escriben
 * con `PUT /coleccion/{codigo}`, que es un alta-o-actualización. El
 * descubrimiento sólo miraba el `POST`, así que esas pestañas salían sin
 * botón de «Nuevo» aunque el servidor las admitiera — y la que lo declaraba a
 * mano (`crear: "…/politicas-acceso/{nombre}"`) salía con botón y **un
 * formulario vacío**, porque no hay `POST` del que sacar los campos.
 *
 * Medido el 04-11-2026 recorriendo administrar: son cuatro —riesgos,
 * controles, reglas de segregación y políticas de acceso—. Un módulo de
 * gobierno en el que no se puede dar de alta un riesgo.
 *
 * Devuelve la plantilla y el nombre del parámetro, o `null` si no hay tal
 * cosa: lo que no se encuentra no se inventa.
 */
export function altaPorClave(
  documento: Documento,
  listar: string,
): { plantilla: string; clave: string } | null {
  const base = listar.split("?")[0]?.replace(/\/$/, "") ?? "";
  for (const [plantilla, ops] of Object.entries(documento.paths ?? {})) {
    if (!(ops as Record<string, unknown>)?.put) continue;
    const m = /^(.*)\/\{([^/}]+)\}$/.exec(plantilla);
    if (!m || m[1] !== base) continue;
    return { plantilla, clave: m[2]! };
  }
  return null;
}

export function camposDe(documento: Documento, ruta: string, metodo: string): CampoEsquema[] {
  const operacion = documento.paths?.[plantillaDe(documento, ruta) ?? ruta]?.[
    metodo.toLowerCase()
  ] as { requestBody?: { content?: Record<string, { schema?: Esquema }> } } | undefined;
  const bruto = operacion?.requestBody?.content?.["application/json"]?.schema;
  if (!bruto) return [];
  const esquema = resolver(documento, bruto);
  const propiedades = esquema.properties ?? {};
  const obligatorios = new Set(esquema.required ?? []);
  // Un objeto que no declara propiedades es un cuerpo abierto, no un cuerpo
  // vacío. Se pide como un campo, y quien lo reciba sabe que ese valor ES el
  // cuerpo. Devolver `[]` aquí es lo que hacía que la acción se ejecutara sin
  // datos sin que nadie pudiera dárselos.
  if (esquema.type === "object" && Object.keys(propiedades).length === 0) {
    return [
      {
        nombre: "datos",
        tipo: "objeto",
        obligatorio: true,
        titulo: humanizar(esquema.title ?? "datos"),
        descripcion: esquema.description ?? "",
        opciones: [],
        maximo: null,
        formato: "",
        subcampos: [],
        referencia: "",
        cuerpoEntero: true,
      },
    ];
  }
  return Object.entries(propiedades).map(([nombre, prop]) => {
    const p = resolver(documento, prop);
    const elemento = p.items ? resolver(documento, p.items) : undefined;
    return {
      nombre,
      tipo: tipoDe(p, elemento, nombre),
      obligatorio: obligatorios.has(nombre),
      // «Contacto», no «Contacto ID»: el campo se rellena eligiendo a alguien
      // por su nombre, y el identificador no lo ve nunca quien lo rellena.
      titulo: nombre.endsWith("_id")
        ? humanizar(p.title ?? nombre).replace(/\s+ID$/, "")
        : humanizar(p.title ?? nombre),
      descripcion: p.description ?? "",
      // Las opciones salen del propio campo o de los elementos de la lista: en
      // un array de enum, el `enum` está en `items`, y mirándolo solo en el
      // campo se perdían todas las listas de opciones múltiples.
      opciones: ((p.enum ?? elemento?.enum ?? []) as unknown[]).map(String),
      maximo: p.maxLength ?? null,
      formato: p.format ?? "",
      subcampos: subcamposDe(documento, elemento),
      referencia: p.referencia ?? "",
    };
  });
}

/**
 * El cuerpo que se manda, a partir de lo que el formulario recogió.
 *
 * Normalmente son los mismos valores. La excepción es la operación de cuerpo
 * abierto, donde el único campo **es** el cuerpo: mandar `{datos: {...}}` ahí
 * metería el encargo dentro de una llave que el servidor no espera.
 *
 * Vive aquí y no en quien llama porque son tres pantallas las que mandan
 * formularios del contrato, y la regla tiene que ser la misma en las tres.
 */
export function cuerpoDeLosValores(
  campos: CampoEsquema[],
  valores: Record<string, unknown>,
): unknown {
  const entero = campos.find((c) => c.cuerpoEntero);
  if (campos.length === 1 && entero) return valores[entero.nombre] ?? {};
  return valores;
}

/** Las columnas de una línea, sacadas del esquema de sus elementos. */
function subcamposDe(documento: Documento, elemento?: Esquema): CampoEsquema[] {
  if (!elemento || elemento.type !== "object" || !elemento.properties) return [];
  const obligatorios = new Set(elemento.required ?? []);
  return Object.entries(elemento.properties).map(([nombre, prop]) => {
    const p = resolver(documento, prop);
    const interno = p.items ? resolver(documento, p.items) : undefined;
    return {
      nombre,
      tipo: tipoDe(p, interno, nombre),
      obligatorio: obligatorios.has(nombre),
      titulo: humanizar(p.title ?? nombre),
      descripcion: p.description ?? "",
      opciones: ((p.enum ?? interno?.enum ?? []) as unknown[]).map(String),
      maximo: p.maxLength ?? null,
      formato: p.format ?? "",
      referencia: p.referencia ?? "",
      // Una sola vuelta: una línea dentro de una línea no se edita en una
      // tabla, se edita en su propia pantalla.
      subcampos: [],
    };
  });
}

function resolver(documento: Documento, esquema: Esquema): Esquema {
  let actual = esquema;
  // `$ref` y `anyOf` aparecen en cuanto un campo es opcional o referencia otro
  // modelo; sin desenvolverlos, la mitad de los campos salen como «objeto» y el
  // formulario los pinta como un textarea de JSON.
  for (let vuelta = 0; vuelta < 5; vuelta += 1) {
    if (actual.$ref) {
      const nombre = actual.$ref.split("/").pop() ?? "";
      actual = documento.components?.schemas?.[nombre] ?? {};
      continue;
    }
    if (actual.anyOf) {
      const util = actual.anyOf.find((o) => o.type !== "null") ?? actual.anyOf[0];
      if (!util) break;
      actual = { ...util, title: actual.title ?? util.title, description: actual.description };
      continue;
    }
    break;
  }
  return actual;
}

/**
 * Nombres de campo que de verdad llevan prosa.
 *
 * **Medido sobre el modelo el 26-10-2026**, no elegido a ojo: de las 229
 * columnas `Text` del producto —las que no tienen tope porque son un texto
 * largo de verdad—, estas raíces cubren 193, el 84 %. Lo que se queda fuera son
 * URLs, firmas y sellos, que es exactamente lo que **no** debe tener un área de
 * cinco líneas.
 *
 * Es una lista corta y se quedará corta: cuando aparezca un campo de prosa que
 * no case, lo que corresponde es añadir su raíz aquí **y decir cuántas columnas
 * pasa a cubrir**, no ensanchar la regla hasta que entre todo.
 */
const RAICES_DE_PROSA = [
  "descripcion",
  "motivo",
  "cuerpo",
  "nota",
  "notas",
  "comentario",
  "detalle",
  "mensaje",
  "resumen",
  "observacion",
  "observaciones",
  "justificacion",
  "resolucion",
  "porque",
  "explicacion",
  "causa",
  "solucion",
  "ayuda",
  "respuesta",
  "pregunta",
  "contenido",
  "conclusion",
  "recomendacion",
  "instrucciones",
];

/** Si el nombre del campo dice que lo que se escribe ahí es un texto largo. */
function esProsa(nombre: string): boolean {
  const n = nombre.toLowerCase();
  return RAICES_DE_PROSA.some((r) => n === r || n.startsWith(`${r}_`) || n.endsWith(`_${r}`));
}

function tipoDe(esquema: Esquema, elemento?: Esquema, nombre = ""): CampoEsquema["tipo"] {
  if (esquema.enum) return "lista";
  switch (esquema.type) {
    case "integer":
    case "number":
      return "numero";
    case "boolean":
      return "booleano";
    case "array":
      // Una lista de opciones cerradas se elige; una lista de textos se escribe
      // uno a uno. Las dos son listas y ninguna es JSON.
      if (elemento?.enum) return "lista_multiple";
      if (!elemento || elemento.type === "string" || elemento.type === "number") return "etiquetas";
      // Con estructura conocida se edita como una tabla de líneas; sin ella no
      // hay columnas que pintar y se queda en el editor genérico.
      return elemento.type === "object" && elemento.properties ? "lineas" : "objeto";
    case "object":
      return "objeto";
    default:
      if (esquema.format === "date" || esquema.format === "date-time") return "fecha";
      // **Una línea, salvo que algo diga que ahí va un texto largo.**
      //
      // Las dos reglas anteriores fallaron por el mismo motivo —decidir sobre
      // `maxLength`— y conviene dejar escrito por qué, porque es la trampa:
      //
      //   · «área cuando el tope pasa de 400» convertía `web` en un cuadro de
      //     cinco líneas, porque la columna es `String(500)`;
      //   · «área cuando NO hay tope» lo convertía casi todo. **Medido el
      //     26-10-2026 sobre el contrato de party: de 402 propiedades de
      //     texto, sólo 40 llevan `maxLength` — el 9 %.** Los esquemas de
      //     salida y los de actualización no lo propagan, así que `nombre`,
      //     `apellidos` o `tratamiento` salían como un área de cinco líneas.
      //
      // `maxLength` no sirve para decidir esto porque **casi nunca está**. Lo
      // que sí es señal es un tope grande de verdad cuando está —1.000 o más es
      // un motivo escrito, no un nombre— y, sobre todo, el nombre del campo.
      //
      // Y por defecto, una línea: un campo de prosa en una línea molesta; un
      // nombre de pila en un área de cinco líneas hace el formulario inusable.
      if (esquema.maxLength !== undefined && esquema.maxLength >= 1000) return "texto_largo";
      return esProsa(nombre) ? "texto_largo" : "texto";
  }
}


export interface Proposito {
  /** Una línea: para qué sirve esto. */
  resumen: string;
  /** El porqué, si el servicio lo explica. */
  detalle: string;
}

/**
 * Para qué sirve una pantalla, dicho por el servicio dueño — **cuando añade
 * algo**.
 *
 * Una pestaña que se llama «Duplicados» y enseña una caja de búsqueda no dice
 * qué hace: hay que probarla para averiguarlo, y probar una pantalla de
 * duplicados o de papelera da miedo. El servicio ya lo explica en su contrato
 * y aquí solo se enseña.
 *
 * Lo que no se miró hasta el 01-11-2026 fue **cuántas veces no añade nada**.
 * Medido sobre los 13 contratos de esta instalación:
 *
 * - **62 de 214** resúmenes repiten el nombre de la pestaña que hay tres
 *   centímetros más arriba: «Cuentas» → «Listar cuentas», «Subprocesadores» →
 *   «Listar subprocesadores».
 * - **131 de 835** descripciones son plantilla generada: «Paginado por cursor.
 *   Devuelve X del tenant en curso, de lo más reciente a lo más antiguo» o «El
 *   mismo listado… en filas planas para una hoja de cálculo».
 *
 * En «Cuentas y contactos» las dos caían a la vez y ocupaban 50 px de los 476
 * que había que bajar para ver el primer dato, diciendo «Listar cuentas» y
 * explicándole la estrategia de paginación a un comercial.
 *
 * Nada de esto se arregla con una lista de frases prohibidas: la plantilla
 * siguiente entra por donde la lista no mira. Las dos señales son estructurales
 * y se miden solas — que el resumen ya esté en el rótulo, y que la descripción
 * **se repita** dentro del mismo contrato.
 */
export function propositoDe(
  documento: Documento,
  ruta: string,
  metodo = "get",
  /** El rótulo que el usuario ya está leyendo encima: la pestaña. */
  rotulo = "",
): Proposito {
  const operacion = documento.paths?.[plantillaDe(documento, ruta) ?? ruta]?.[metodo] as
    | { summary?: string; description?: string }
    | undefined;
  // Sin el código de la capacidad: en el contrato sirve, en pantalla no.
  const resumen = comoRotulo(operacion?.summary);
  const detalle = (operacion?.description ?? "").split("\n\n")[0] ?? "";
  return {
    resumen: yaLoDiceElRotulo(resumen, rotulo) ? "" : resumen,
    // Sin el marcado de negrita del contrato: aquí no se pinta como markdown.
    detalle: esPlantilla(documento, detalle) ? "" : detalle.replace(/\*\*/g, "").trim(),
  };
}

/** Las palabras con contenido de un texto, sin tildes ni puntuación. */
function palabras(texto: string): string[] {
  return texto
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9 ]/g, " ")
    .split(/\s+/)
    .filter(Boolean);
}

// Verbos de listado y palabras de enlace: están en casi todos los resúmenes y
// no distinguen nada. Si se cuentan, «Listar cuentas» frente a la pestaña
// «Cuentas» parece que aporta un 50 % de información nueva, y no aporta
// ninguna.
const VACIAS = new Set(["listar", "ver", "consultar", "de", "del", "la", "el", "los", "las", "un", "una", "y", "en", "a"]);

/**
 * ¿El resumen dice algo que el rótulo de la pestaña no diga ya?
 *
 * Se compara por raíz de cuatro letras y no por igualdad: «Listar migraciones
 * de aislamiento» bajo la pestaña «Migraciones de aislamiento» es la misma
 * frase, y «Listar canales de chat» bajo «Canales de chat» también — pero
 * «Cumplimiento por proveedor» bajo «Encargos: cumplimiento por proveedor» no
 * coincide carácter a carácter y es igual de redundante.
 */
function yaLoDiceElRotulo(resumen: string, rotulo: string): boolean {
  if (!resumen || !rotulo) return false;
  const suyas = palabras(resumen).filter((p) => !VACIAS.has(p));
  if (suyas.length === 0) return true;
  const delRotulo = palabras(rotulo);
  return suyas.every((p) => delRotulo.some((r) => r.startsWith(p.slice(0, 4)) || p.startsWith(r.slice(0, 4))));
}

/** Cuántas descripciones casi iguales hay en un contrato, por párrafo. */
const gemelos = new WeakMap<Documento, Map<string, number>>();

/**
 * ¿Esta descripción es plantilla?
 *
 * Lo es si el **mismo contrato** la repite: un párrafo escrito a mano para una
 * pantalla no aparece en otras cuatro. Se comparan los conjuntos de palabras al
 * 80 % para que el nombre de la entidad —lo único que cambia entre
 * «Devuelve migraciones…» y «Devuelve declaraciones…»— no las separe.
 *
 * El umbral es 2 gemelos y no 1: dos pantallas hermanas pueden compartir una
 * explicación legítima, cinco no.
 */
function esPlantilla(documento: Documento, detalle: string): boolean {
  const limpio = detalle.replace(/\*\*/g, "").trim();
  if (limpio.length < 30) return false;

  let contados = gemelos.get(documento);
  if (!contados) {
    const parrafos: string[][] = [];
    for (const operaciones of Object.values(documento.paths ?? {})) {
      for (const op of Object.values(operaciones)) {
        const d = (op as { description?: string } | null)?.description;
        if (d) parrafos.push(palabras(d.split("\n\n")[0] ?? ""));
      }
    }
    contados = new Map();
    for (const p of parrafos) {
      const clave = p.join(" ");
      if (contados.has(clave)) continue;
      contados.set(clave, parrafos.filter((otro) => parecido(p, otro) >= 0.8).length - 1);
    }
    gemelos.set(documento, contados);
  }
  return (contados.get(palabras(limpio).join(" ")) ?? 0) >= 2;
}

/** Cuánto se solapan dos conjuntos de palabras, de 0 a 1. */
function parecido(a: string[], b: string[]): number {
  const A = new Set(a);
  const B = new Set(b);
  if (A.size === 0 || B.size === 0) return 0;
  let comunes = 0;
  for (const p of A) if (B.has(p)) comunes++;
  return comunes / Math.max(A.size, B.size);
}
