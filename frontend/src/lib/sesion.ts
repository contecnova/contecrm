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

import { ErrorApi, llamar } from "@/lib/api";

/** Tal como lo devuelve `GET /api/v1/auth/me`. */
export interface Yo {
  usuario: {
    id: string;
    email: string;
    nombre: string;
    es_plataforma: boolean;
  };
  tenant_id: string | null;
  roles: string[];
  permisos: string[];
  suplantado_por: string | null;
  suplantado_por_email?: string | null;
  motivo_suplantacion?: string | null;
  suplantacion_caduca_at?: string | null;
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
  /**
   * Y con qué motivo, quién y hasta cuándo (CRM-00.01.02.06). Es lo que dice
   * la franja: «Estás dentro como X por soporte: motivo».
   */
  suplantacion?: {
    por_email: string | null;
    motivo: string | null;
    caduca_at: string | null;
  } | null;
}

/**
 * Lo que se sabe de quién entra: la sesión, que no hay, o que no se ha podido
 * preguntar.
 *
 * **Son tres cosas y antes eran dos.** `cargarSesion` se tragaba cualquier
 * error y devolvía «no hay sesión», así que un 502 —el gateway caído, el
 * contenedor reiniciándose, el túnel cortado— salía exactamente igual que no
 * haber entrado: la pantalla de entrada, con su formulario, invitando a
 * teclear una contraseña en un sistema que no puede contestar. Y al enviarla,
 * otro error opaco.
 *
 * «No hay sesión» y «el sistema no responde» se leen igual y significan lo
 * contrario. El segundo no se arregla escribiendo la contraseña otra vez.
 */
export type Entrada =
  | { estado: "dentro"; sesion: Sesion }
  | { estado: "fuera" }
  | { estado: "caido"; error: unknown };

export async function cargarEntrada(signal?: AbortSignal): Promise<Entrada> {
  try {
    const { datos } = await llamar<Yo>("/api/v1/auth/me", { signal });
    return {
      estado: "dentro",
      sesion: {
        usuario_id: datos.usuario.id,
        nombre: datos.usuario.nombre,
        email: datos.usuario.email,
        tenant_id: datos.tenant_id,
        roles: datos.roles,
        permisos: datos.permisos,
        es_admin_plataforma: datos.usuario.es_plataforma,
        suplantado_por: datos.suplantado_por,
        suplantacion: datos.suplantado_por
          ? {
              por_email: datos.suplantado_por_email ?? null,
              motivo: datos.motivo_suplantacion ?? null,
              caduca_at: datos.suplantacion_caduca_at ?? null,
            }
          : null,
      },
    };
  } catch (error) {
    // 401 y 403 son «no has entrado», que es la pantalla de entrada y no un
    // error que enseñar. Lo demás —502, 503, un fallo de red, un 500— es que
    // no se ha podido preguntar, y eso sí se dice.
    const estado = error instanceof ErrorApi ? error.estado : 0;
    if (estado === 401 || estado === 403) return { estado: "fuera" };
    return { estado: "caido", error };
  }
}

/**
 * Sólo la sesión, para quien no necesita distinguir por qué no la hay.
 *
 * La usan las pantallas que ya están dentro —el panel de rendimiento, por
 * ejemplo—: ahí un fallo al preguntar quién eres lo recoge el propio estado de
 * la pantalla, y traer las tres respuestas obligaría a cada una a decidir lo
 * mismo. Quien SÍ tiene que distinguirlas es el arranque, y usa `cargarEntrada`.
 */
export async function cargarSesion(
  signal?: AbortSignal,
): Promise<Sesion | null> {
  const entrada = await cargarEntrada(signal);
  return entrada.estado === "dentro" ? entrada.sesion : null;
}

/**
 * Si la sesión concede el permiso, expandiendo comodines.
 *
 * Se expanden igual que en el servidor (`*:*`, `objeto:*`, `*:accion`): una
 * interfaz que no los expandiera escondería media aplicación al administrador,
 * que es justo quien los tiene.
 */
export function puede(
  sesion: Sesion | null,
  permiso: string | null | undefined,
): boolean {
  if (!permiso) return true;
  if (!sesion) return false;
  if (sesion.es_admin_plataforma) return true;
  const concedidos = new Set(sesion.permisos);
  if (concedidos.has("*:*") || concedidos.has(permiso)) return true;
  const [objeto = "", accion = ""] = permiso.split(":");
  return concedidos.has(`${objeto}:*`) || concedidos.has(`*:${accion}`);
}

/**
 * Salir de la suplantación y volver a la sesión propia (CRM-00.01.02.06).
 *
 * Son dos pasos y no uno porque el refresco propio sólo viaja a
 * `/sesion/renovar`: `volver` cierra en identidad la sesión de soporte y borra
 * sus cookies, y `renovar` saca un token propio nuevo con el refresco que no
 * se tocó al entrar. Se recarga la página entera después: lo que hay en
 * memoria es de la otra persona.
 */
export async function volverASesionPropia(): Promise<void> {
  await llamar("/api/v1/sesion/volver", { metodo: "POST" });
  // Si renovar falla, la sesión de soporte ya está cerrada: al recargar, sin
  // token propio, se llega a la pantalla de entrada, que es lo correcto. Un
  // error aquí sólo dejaría a quien pulsó dentro de la sesión de otro.
  await llamar("/api/v1/sesion/renovar", { metodo: "POST" }).catch(
    () => undefined,
  );
  window.location.assign("/");
}
