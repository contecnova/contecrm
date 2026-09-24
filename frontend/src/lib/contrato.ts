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

interface Documento {
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
export function camposDe(documento: Documento, ruta: string, metodo: string): CampoEsquema[] {
  const operacion = documento.paths?.[plantillaDe(documento, ruta) ?? ruta]?.[
    metodo.toLowerCase()
  ] as { requestBody?: { content?: Record<string, { schema?: Esquema }> } } | undefined;
  const bruto = operacion?.requestBody?.content?.["application/json"]?.schema;
  if (!bruto) return [];
  const esquema = resolver(documento, bruto);
  const propiedades = esquema.properties ?? {};
  const obligatorios = new Set(esquema.required ?? []);
  return Object.entries(propiedades).map(([nombre, prop]) => {
    const p = resolver(documento, prop);
    const elemento = p.items ? resolver(documento, p.items) : undefined;
    return {
      nombre,
      tipo: tipoDe(p, elemento),
      obligatorio: obligatorios.has(nombre),
      titulo: humanizar(p.title ?? nombre),
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

/** Las columnas de una línea, sacadas del esquema de sus elementos. */
function subcamposDe(documento: Documento, elemento?: Esquema): CampoEsquema[] {
  if (!elemento || elemento.type !== "object" || !elemento.properties) return [];
  const obligatorios = new Set(elemento.required ?? []);
  return Object.entries(elemento.properties).map(([nombre, prop]) => {
    const p = resolver(documento, prop);
    const interno = p.items ? resolver(documento, p.items) : undefined;
    return {
      nombre,
      tipo: tipoDe(p, interno),
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

function tipoDe(esquema: Esquema, elemento?: Esquema): CampoEsquema["tipo"] {
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
      // Un campo sin tope de longitud suele ser una descripción o unas notas:
      // en una línea de una sola altura no se ve lo que se escribe.
      return esquema.maxLength && esquema.maxLength > 400 ? "texto_largo" : "texto";
  }
}

/**
 * El nombre del campo, escrito como se lee.
 *
 * El contrato trae `sector_codigo` y `facturacion_anual`, que son nombres de
 * campo, no rótulos. Se transforma con una regla y no con una tabla de
 * traducciones: una tabla se queda corta al primer campo nuevo, y entonces
 * conviven rótulos bonitos con rótulos en crudo, que es peor que tenerlos todos
 * en crudo.
 */
export function humanizar(nombre: string): string {
  const limpio = nombre.replace(/_/g, " ").trim();
  return limpio.charAt(0).toUpperCase() + limpio.slice(1);
}

export interface Proposito {
  /** Una línea: para qué sirve esto. */
  resumen: string;
  /** El porqué, si el servicio lo explica. */
  detalle: string;
}

/**
 * Para qué sirve una pantalla, dicho por el servicio dueño.
 *
 * Una pestaña que se llama «Duplicados» y enseña una caja de búsqueda no dice
 * qué hace: hay que probarla para averiguarlo, y probar una pantalla de
 * duplicados o de papelera da miedo. El servicio ya lo explica en su contrato
 * —«Lo mismo que hace el alta, pero sin crear nada»— y aquí solo se enseña.
 *
 * Se recorta el primer párrafo: las descripciones del contrato razonan la
 * decisión entera y eso es para quien integra, no para quien abre la pantalla.
 */
export function propositoDe(documento: Documento, ruta: string, metodo = "get"): Proposito {
  const operacion = documento.paths?.[plantillaDe(documento, ruta) ?? ruta]?.[metodo] as
    | { summary?: string; description?: string }
    | undefined;
  const detalle = (operacion?.description ?? "").split("\n\n")[0] ?? "";
  return {
    resumen: operacion?.summary ?? "",
    // Sin el marcado de negrita del contrato: aquí no se pinta como markdown.
    detalle: detalle.replace(/\*\*/g, "").trim(),
  };
}
