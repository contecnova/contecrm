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
  tipo: "texto" | "numero" | "booleano" | "fecha" | "lista" | "objeto";
  obligatorio: boolean;
  titulo: string;
  descripcion: string;
  opciones: string[];
  maximo: number | null;
  formato: string;
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
  // El gateway no publica el OpenAPI de los servicios de detrás; se pide al
  // servicio por su propia ruta a través del proxy.
  const promesa = llamar<Documento>(`/api/v1/${servicio}/openapi.json`)
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
    return {
      nombre,
      tipo: tipoDe(p),
      obligatorio: obligatorios.has(nombre),
      titulo: p.title ?? nombre,
      descripcion: p.description ?? "",
      opciones: (p.enum ?? []).map(String),
      maximo: p.maxLength ?? null,
      formato: p.format ?? "",
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

function tipoDe(esquema: Esquema): CampoEsquema["tipo"] {
  if (esquema.enum) return "lista";
  switch (esquema.type) {
    case "integer":
    case "number":
      return "numero";
    case "boolean":
      return "booleano";
    case "array":
    case "object":
      return "objeto";
    default:
      return esquema.format === "date" || esquema.format === "date-time" ? "fecha" : "texto";
  }
}
