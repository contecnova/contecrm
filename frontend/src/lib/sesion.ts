/**
 * Quién soy y qué puedo, según el servidor (CRM-07.04.02.05).
 *
 * **La interfaz no decide permisos** (CRM-07.04.02.05). Esto no es un detalle
 * de estilo: si el front decidiera, bastaría con abrir las herramientas del
 * navegador para «concederse» una acción, y además la respuesta a «¿por qué no
 * puedo?» dependería de dos implementaciones que se separan con el tiempo.
 *
 * Lo que hace este módulo es leer lo que el servidor dice —permisos efectivos y
 * capacidades del plan— y usarlo para **no ofrecer** lo que no se puede hacer.
 * Ofrecerlo y que falle es peor experiencia, pero no es un agujero; decidirlo
 * aquí sí lo sería.
 */

import { llamar } from "@/lib/api";

/** Tal como lo devuelve `GET /api/v1/auth/me`. */
export interface Yo {
  usuario: { id: string; email: string; nombre: string; es_plataforma: boolean };
  tenant_id: string | null;
  roles: string[];
  permisos: string[];
  suplantado_por: string | null;
}

export interface Sesion {
  usuario_id: string;
  nombre: string;
  email: string;
  tenant_id: string | null;
  roles: string[];
  permisos: string[];
  es_admin_plataforma: boolean;
  /** Quién está actuando en nombre de este usuario, si alguien lo está. */
  suplantado_por: string | null;
}

export async function cargarSesion(signal?: AbortSignal): Promise<Sesion | null> {
  try {
    const { datos } = await llamar<Yo>("/api/v1/auth/me", { signal });
    return {
      usuario_id: datos.usuario.id,
      nombre: datos.usuario.nombre,
      email: datos.usuario.email,
      tenant_id: datos.tenant_id,
      roles: datos.roles,
      permisos: datos.permisos,
      es_admin_plataforma: datos.usuario.es_plataforma,
      suplantado_por: datos.suplantado_por,
    };
  } catch {
    // Sin sesión no es un error que haya que enseñar: es la pantalla de
    // entrada.
    return null;
  }
}

/**
 * Si la sesión concede el permiso, expandiendo comodines.
 *
 * Se expanden igual que en el servidor (`*:*`, `objeto:*`, `*:accion`): una
 * interfaz que no los expandiera escondería media aplicación al administrador,
 * que es justo quien los tiene.
 */
export function puede(sesion: Sesion | null, permiso: string | null | undefined): boolean {
  if (!permiso) return true;
  if (!sesion) return false;
  if (sesion.es_admin_plataforma) return true;
  const concedidos = new Set(sesion.permisos);
  if (concedidos.has("*:*") || concedidos.has(permiso)) return true;
  const [objeto = "", accion = ""] = permiso.split(":");
  return concedidos.has(`${objeto}:*`) || concedidos.has(`*:${accion}`);
}
