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
  /**
   * Solo la puede hacer quien opera la plataforma.
   *
   * No es un permiso y por eso va aparte: el administrador de una empresa
   * tiene `tenant:read` y aun así recibe 403 al listar tenants. Sin esta
   * marca, el menú le enseñaba «Tenants y unidades» entero, y al abrirlo lo
   * único que decía era que no es para él.
   */
  solo_plataforma: boolean;
  /**
   * Devuelve muchos registros, no uno.
   *
   * Es lo que distingue una **sub-colección** —las direcciones de una cuenta,
   * que se listan y se dan de alta— de una **vista**, como la 360 de la cuenta
   * o a quién llamar de un proveedor. Sin distinguirlas, la ficha pintaba las
   * dos como un panel plegable con una lista dentro, y el de la vista decía
   * «Nada todavía» para siempre — que se lee como un dato que falta y no como
   * algo que nunca fue una lista.
   */
  devuelve_lista?: boolean;
  /**
   * Hace falta darle algo por la URL además de los tramos de la ruta.
   *
   * «A quién puedo contactar» exige la finalidad y el canal; «la ruta del
   * técnico», el día. Pedidas sin eso responden 422, y la ficha las pintaba
   * como un panel que **siempre** da error — no como una pregunta a la que
   * falta contestar.
   */
  exige_datos?: boolean;
  /**
   * Si hay que mandarle un cuerpo, además de llamarla.
   *
   * Otra pregunta que `exige_datos`, que mira los parámetros de la URL. Es la
   * que decide si una operación de colección puede ofrecerse como **botón**:
   * una que pide cuerpo y se llama vacía contesta 422.
   */
  exige_cuerpo?: boolean;
  servicio: string;
}

export interface Superficie {
  consultado_at: string;
  servicios: string[];
  servicios_sin_contestar: string[];
  completa: boolean;
  /**
   * Qué objetos admiten adjuntos, comentarios y documentos.
   *
   * No se puede deducir de las operaciones: esas rutas son `/adjuntos/{objeto}`
   * y aparecen una sola vez, con el objeto sin resolver. Sin esto la ficha
   * pedía las tres para **cualquier** registro y recibía 404 en 81 de 85, tres
   * peticiones fallidas por ficha abierta y tres pestañas que no podían
   * funcionar.
   */
  objetos?: {
    adjuntos: string[];
    comentarios: string[];
    documentos: string[];
    /**
     * A qué se le puede apuntar una llamada, una reunión, una nota o un correo.
     *
     * El campo `objeto` de una actividad es polimórfico y el servidor no
     * rechaza nada, así que sin esta lista la ficha los ofrecía sobre los 52
     * tipos de registro que declara el front: «Llamada» sobre un calendario
     * laboral, «Correo» sobre una entrada de papelera. Ofrecer lo que no tiene
     * sentido hace dudar de lo que sí lo tiene.
     */
    actividades?: string[];
  };
  total: number;
  administracion: number;
  operaciones: Operacion[];
}

export async function cargarSuperficie(
  signal?: AbortSignal,
): Promise<Superficie> {
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
  // ── Y EL QUE SE REPITE, CON SU APELLIDO ──────────────────────────────
  //
  // El nombre sale de la etiqueta del contrato, y hay etiquetas que usan los
  // doce servicios: «papelera», «ajustes». Agrupar está bien —son doce áreas
  // distintas, cada una con sus cuatro operaciones— pero en pantalla salían
  // **doce entradas llamadas igual**, imposibles de distinguir sin pulsarlas
  // una a una. Medido el 04-11-2026 en `/administracion`: doce «papelera 4» y
  // dos «ajustes 2» seguidas.
  //
  // Se apellidan **sólo las que chocan**: poner el servicio a todas haría más
  // largo y más ruidoso lo que ya se distinguía solo.
  const cuantas = new Map<string, number>();
  for (const area of porRecurso.values()) {
    cuantas.set(area.nombre, (cuantas.get(area.nombre) ?? 0) + 1);
  }
  for (const area of porRecurso.values()) {
    if ((cuantas.get(area.nombre) ?? 0) > 1) {
      area.nombre = `${area.nombre} · ${area.recurso}`;
    }
  }
  return [...porRecurso.values()].sort((a, b) =>
    a.nombre.localeCompare(b.nombre, "es"),
  );
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
  return area.operaciones.find(
    (o) => o.metodo === "GET" && !o.ruta.includes("{"),
  );
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
  esDePlataforma = false,
): Set<string> {
  const permitidas = new Set<string>();
  if (!superficie) return permitidas;
  for (const operacion of superficie.operaciones) {
    if (operacion.metodo.toUpperCase() !== "GET") continue;
    // Lo de plataforma no entra si no se opera la plataforma, tenga el permiso
    // que tenga: es la única forma de que el menú no ofrezca lo que va a
    // contestar 403.
    if (operacion.solo_plataforma && !esDePlataforma) continue;
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
  const tramos = limpia.split("/");
  for (const p of permitidas) {
    if (p === limpia || p.startsWith(`${limpia}/`)) return true;
    // Y por tramos, con los parámetros como comodín: la pestaña de un
    // vocabulario pide `/sales/vocabularios/motivos_perdida` y la superficie
    // publica `/sales/vocabularios/{nombre}`. Sólo por prefijo no casaba, y
    // las pestañas de los vocabularios se escondían en cuanto llegaba la
    // superficie (medido el 10-11-2026: «Factores de una lección» y las cinco
    // de vocabularios nuevos, en pantalla de la primera pestaña del módulo).
    const suyos = p.split("/");
    if (
      suyos.length === tramos.length &&
      suyos.every((t, i) => t === tramos[i] || /^\{[^}]+\}$/.test(t))
    ) {
      return true;
    }
  }
  return false;
}

/**
 * ¿Puede esta sesión hacer esta operación sobre esta ruta concreta?
 *
 * La superficie publica las rutas con sus parámetros —`/api/v1/accounts/{id}`—
 * y el front tiene rutas con valores dentro. Se comparan tramo a tramo: los
 * literales tienen que coincidir y los parámetros aceptan cualquier cosa.
 *
 * Esto es lo que permite que la ficha ofrezca «editar» y «eliminar» **solo
 * donde el servidor los admite y a quien se los admite**, sin una segunda lista
 * de permisos en el front que se separaría de la del servidor en silencio.
 */
export function operacionPermitida(
  superficie: Superficie | null,
  metodo: string,
  ruta: string,
  puede: (permiso: string | null) => boolean,
): boolean {
  const operacion = operacionDe(superficie, metodo, ruta);
  return operacion ? puede(operacion.permiso) : false;
}

/** La operación publicada que contesta a ese método sobre esa ruta concreta. */
export function operacionDe(
  superficie: Superficie | null,
  metodo: string,
  ruta: string,
): Operacion | undefined {
  if (!superficie) return undefined;
  const tramos = (ruta.split("?")[0] ?? ruta).split("/");
  return superficie.operaciones.find((operacion) => {
    if (operacion.metodo.toUpperCase() !== metodo.toUpperCase()) return false;
    const patron = operacion.ruta.split("/");
    if (patron.length !== tramos.length) return false;
    return patron.every((p, i) => p.startsWith("{") || p === tramos[i]);
  });
}
