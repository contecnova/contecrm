/**
 * La superficie: lo que el CRM sabe hacer, leído del contrato.
 *
 * Es la pieza que hace comprobable la promesa de que la consola de
 * administración está replicada al 100 % por API (CRM-07.01.01.01): el menú,
 * los formularios y las tablas de la consola se construyen a partir de esto,
 * así que **no puede existir una acción de consola que no sea una llamada
 * publicada**. No por disciplina: por construcción.
 *
 * Lo agrega el gateway (`GET /api/v1/superficie`) juntando la de los diez
 * servicios. Quien la consume está fuera y no conoce —ni debe conocer— cómo
 * está repartido el sistema por dentro.
 */

import { llamar } from "@/lib/api";

export interface Operacion {
  metodo: string;
  ruta: string;
  resumen: string;
  etiquetas: string[];
  permiso: string | null;
  administracion: boolean;
  servicio: string;
}

export interface Superficie {
  consultado_at: string;
  servicios: string[];
  servicios_sin_contestar: string[];
  completa: boolean;
  total: number;
  administracion: number;
  operaciones: Operacion[];
}

export async function cargarSuperficie(signal?: AbortSignal): Promise<Superficie> {
  const { datos } = await llamar<Superficie>("/api/v1/superficie", { signal });
  return datos;
}

export interface Area {
  /** Etiqueta con la que el servicio rotula sus operaciones. */
  nombre: string;
  /** Recurso de la ruta: `tenants`, `usuarios`… Es lo que se lista. */
  recurso: string;
  servicio: string;
  operaciones: Operacion[];
}

/**
 * Agrupa las operaciones de administración en áreas navegables.
 *
 * Se agrupa por **recurso de la ruta** y no por etiqueta: dos servicios pueden
 * rotular parecido —«ajustes» y «configuración»— y acabarían en el mismo menú
 * apuntando a sitios distintos. El recurso es lo que de verdad identifica qué
 * se está administrando.
 */
export function areasDeAdministracion(superficie: Superficie): Area[] {
  const porRecurso = new Map<string, Area>();
  for (const operacion of superficie.operaciones) {
    if (!operacion.administracion) continue;
    const recurso = recursoDe(operacion.ruta);
    if (!recurso) continue;
    const area = porRecurso.get(recurso) ?? {
      nombre: operacion.etiquetas[0] ?? recurso,
      recurso,
      servicio: operacion.servicio,
      operaciones: [],
    };
    area.operaciones.push(operacion);
    porRecurso.set(recurso, area);
  }
  return [...porRecurso.values()].sort((a, b) => a.nombre.localeCompare(b.nombre, "es"));
}

/** `/api/v1/tenants/{id}/unidades` → `tenants`. */
export function recursoDe(ruta: string): string {
  const partes = ruta.split("/").filter(Boolean);
  // `api`, `v1`, recurso…
  return partes.length >= 3 ? (partes[2] ?? "") : "";
}

/**
 * La operación que LISTA un área, si la hay.
 *
 * Es un `GET` sin parámetros en la ruta: `/api/v1/tenants` sí,
 * `/api/v1/tenants/{tenant_id}` no. Distinguirlas es lo que permite pintar una
 * tabla sin pedirle al usuario que invente un identificador.
 */
export function operacionDeListado(area: Area): Operacion | undefined {
  return area.operaciones.find((o) => o.metodo === "GET" && !o.ruta.includes("{"));
}

/** Operaciones que cambian algo, que son las que se ofrecen como acciones. */
export function acciones(area: Area): Operacion[] {
  return area.operaciones.filter((o) => o.metodo !== "GET");
}

/**
 * Qué rutas puede llamar esta sesión, según lo que declara el servidor.
 *
 * El menú necesita saber si alguien puede abrir un módulo **antes** de
 * ofrecérselo. La alternativa era declarar el permiso de cada uno de los ciento
 * doce recursos en `modulos.ts`, es decir, una segunda lista de permisos que
 * tendría que coincidir con la del servidor — y que se separaría de ella en
 * cuanto alguien cambiara un permiso en el backend, sin que nada lo avisara.
 *
 * Aquí no hay segunda lista: se pregunta al servidor qué exige cada operación
 * y se compara con lo que esta sesión tiene. Si el servidor cambia de opinión,
 * el menú cambia con él.
 */
export function rutasPermitidas(
  superficie: Superficie | null,
  puede: (permiso: string | null) => boolean,
): Set<string> {
  const permitidas = new Set<string>();
  if (!superficie) return permitidas;
  for (const operacion of superficie.operaciones) {
    if (operacion.metodo.toUpperCase() !== "GET") continue;
    if (puede(operacion.permiso)) permitidas.add(operacion.ruta);
  }
  return permitidas;
}

/**
 * ¿Está permitida esta ruta concreta?
 *
 * La superficie publica las rutas con sus parámetros —`/api/v1/tenants/{id}`—
 * y el front declara rutas literales. Se compara por prefijo de recurso, que es
 * lo que de verdad determina el permiso: todas las operaciones de `/tenants`
 * exigen lo mismo.
 */
export function rutaPermitida(permitidas: Set<string>, ruta: string): boolean {
  const limpia = ruta.split("?")[0] ?? ruta;
  if (permitidas.has(limpia)) return true;
  for (const p of permitidas) {
    if (p === limpia || p.startsWith(`${limpia}/`)) return true;
  }
  return false;
}
