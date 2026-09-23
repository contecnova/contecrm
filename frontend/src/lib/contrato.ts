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
}

interface Esquema {
  type?: string;
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
 * Campos del cuerpo que espera una operación.
 *
 * Devuelve lista vacía cuando no hay esquema, y quien la use tiene que
 * enseñarlo: un formulario vacío presentado como «este recurso no pide nada»
 * haría crear registros incompletos sin que nadie lo notara.
 */
export function camposDe(documento: Documento, ruta: string, metodo: string): CampoEsquema[] {
  const operacion = documento.paths?.[ruta]?.[metodo.toLowerCase()] as
    | { requestBody?: { content?: Record<string, { schema?: Esquema }> } }
    | undefined;
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
  const operacion = documento.paths?.[ruta]?.[metodo] as
    | { summary?: string; description?: string }
    | undefined;
  const detalle = (operacion?.description ?? "").split("\n\n")[0] ?? "";
  return {
    resumen: operacion?.summary ?? "",
    // Sin el marcado de negrita del contrato: aquí no se pinta como markdown.
    detalle: detalle.replace(/\*\*/g, "").trim(),
  };
}
