/**
 * Lo que se puede HACER con un registro, sacado de lo que publica el servidor.
 *
 * Un CRM no son listados: son acciones sobre registros. Convertir un lead,
 * moverlo de etapa, escalar un caso, reabrirlo, fusionar duplicados, pedir una
 * aprobación. La API publica **144** de estas sobre un registro, y el front no
 * ofrecía ninguna:
 * se podía listar y crear, y nada más. Con eso no se cierra un ciclo de trabajo
 * completo, solo se mira.
 *
 * Escribirlas a mano —un botón por acción, ciento cuarenta y cuatro veces— habría
 * garantizado dos cosas: que la mitad no se escribiera nunca y que la otra
 * mitad se quedara desfasada. Así que se hace como los listados y los
 * formularios: **se leen del contrato**. La superficie dice qué operaciones hay
 * sobre cada ruta y qué permiso exige cada una; el OpenAPI dice qué campos pide
 * cada una. De ahí sale el botón y de ahí sale su formulario.
 *
 * Una acción nueva en el servidor aparece sola en la ficha. Eso es lo que hace
 * que esto no vuelva a quedarse atrás.
 */

import { comoRotulo } from "@/lib/formato";
import type { Operacion, Superficie } from "@/lib/superficie";

export interface Accion {
  /** Ruta real, con el identificador ya puesto. */
  ruta: string;
  /** Ruta con `{param}`, que es como la nombra el OpenAPI. */
  plantilla: string;
  metodo: string;
  /** Lo que hace, dicho por el propio servidor. */
  nombre: string;
  permiso: string | null;
  /** El último tramo: `convertir`, `descartar`, `etapa`… */
  clave: string;
  /** Frase corta bajo el botón, para lo que no se adivina por el rótulo. */
  detalle?: string;
}

const PARAMETRO = /\{[^}]+\}/g;

/**
 * Las acciones que admite este registro.
 *
 * **Solo las de un parámetro.** `/accounts/{cuenta_id}/equipo/{miembro_id}`
 * actúa sobre un miembro del equipo, no sobre la cuenta: ofrecerla aquí pediría
 * un identificador que quien mira la ficha no tiene.
 *
 * **Y solo `POST`.** `PATCH` y `DELETE` sobre el propio registro ya los ofrece
 * la ficha como editar y eliminar; repetirlos aquí sería el mismo botón dos
 * veces con dos nombres.
 */
export function accionesDe(
  superficie: Superficie | null,
  rutaBase: string,
  id: string,
  puede: (permiso: string | null) => boolean,
): Accion[] {
  if (!superficie) return [];
  const tramosBase = rutaBase.split("/");
  const salida: Accion[] = [];

  for (const operacion of superficie.operaciones as Operacion[]) {
    if (operacion.metodo.toUpperCase() !== "POST") continue;
    const tramos = operacion.ruta.split("/");
    // Un tramo más que la colección, y ese tramo es el parámetro del registro:
    // `/api/v1/leads` + `/{lead_id}` + `/convertir`.
    if (tramos.length !== tramosBase.length + 2) continue;
    if (!tramos[tramosBase.length]?.startsWith("{")) continue;
    if ((operacion.ruta.match(PARAMETRO) ?? []).length !== 1) continue;
    if (tramos.slice(0, tramosBase.length).join("/") !== rutaBase) continue;
    if (!puede(operacion.permiso)) continue;

    const clave = tramos[tramos.length - 1] ?? "";
    salida.push({
      ruta: operacion.ruta.replace(PARAMETRO, id),
      plantilla: operacion.ruta,
      metodo: operacion.metodo,
      // El resumen lo escribe el servicio dueño: «Convertir un lead en
      // oportunidad». Inventar aquí un rótulo a partir de la ruta daría
      // «Convertir» a secas y perdería la mitad de lo que dice.
      nombre: comoRotulo(operacion.resumen) || clave,
      permiso: operacion.permiso,
      clave,
    });
  }
  return salida.sort((a, b) => a.nombre.localeCompare(b.nombre, "es"));
}

/**
 * Lo que se puede hacer con un registro **que no tiene ficha**.
 *
 * Una ficha es algo que se lee: sin `GET /coleccion/{id}` no la hay, y todo lo
 * que la ficha ofrece —acciones, editar, quitar— se quedaba sin sitio. Medido
 * el 05-11-2026 sobre las pestañas declaradas: **dieciséis** tenían
 * operaciones sobre sus filas y ninguna puerta. No se podía revocar una clave
 * de API, cerrar una sesión, quitar un dispositivo de confianza ni levantar
 * una supresión desde ninguna pantalla, con el servidor admitiéndolo todo.
 *
 * Con esto, cada fila lleva su menú: las acciones `POST`, editar (`PATCH`, o
 * `PUT` si es lo único que hay) y quitar (`DELETE`), cada una con el permiso
 * que pide. `campo` es la columna de la fila que va en la ruta: `{x_id}` es el
 * identificador de siempre; `{clave}`, `{codigo}` o `{nombre}`, esa columna.
 */
export interface OperacionesDeRegistro {
  campo: string;
  editar: Operacion | null;
  quitar: Operacion | null;
  acciones: Operacion[];
}

export function operacionesDeRegistro(
  superficie: Superficie | null,
  rutaBase: string,
  puede: (permiso: string | null) => boolean,
): OperacionesDeRegistro | null {
  if (!superficie) return null;
  const base = (rutaBase.split("?")[0] ?? rutaBase).split("/");
  let parametro = "";
  let patch: Operacion | null = null;
  let put: Operacion | null = null;
  let quitar: Operacion | null = null;
  const acciones: Operacion[] = [];
  for (const operacion of superficie.operaciones as Operacion[]) {
    const tramos = operacion.ruta.split("/");
    if (tramos.length < base.length + 1 || tramos.length > base.length + 2) continue;
    if (tramos.slice(0, base.length).join("/") !== base.join("/")) continue;
    const suyo = tramos[base.length] ?? "";
    if (!suyo.startsWith("{")) continue;
    if ((operacion.ruta.match(PARAMETRO) ?? []).length !== 1) continue;
    if (!puede(operacion.permiso)) continue;
    const metodo = operacion.metodo.toUpperCase();
    const sobreElRegistro = tramos.length === base.length + 1;
    if (sobreElRegistro && metodo === "PATCH") patch = operacion;
    else if (sobreElRegistro && metodo === "PUT") put = operacion;
    else if (sobreElRegistro && metodo === "DELETE") quitar = operacion;
    else if (metodo === "POST") acciones.push(operacion);
    else continue;
    parametro = suyo.slice(1, -1);
  }
  const editar = patch ?? put;
  if (!editar && !quitar && acciones.length === 0) return null;
  return {
    campo: /(^|_)id$/.test(parametro) ? "id" : parametro,
    editar,
    quitar,
    acciones: acciones.sort((a, b) =>
      comoRotulo(a.resumen).localeCompare(comoRotulo(b.resumen), "es"),
    ),
  };
}

/** Una operación de la fila, como acción con su ruta ya puesta. */
export function comoAccionDeFila(operacion: Operacion, valor: string): Accion {
  const tramos = operacion.ruta.split("/");
  const ultimo = tramos[tramos.length - 1] ?? "";
  return {
    ruta: operacion.ruta.replace(PARAMETRO, encodeURIComponent(valor)),
    plantilla: operacion.ruta,
    metodo: operacion.metodo.toUpperCase(),
    nombre: comoRotulo(operacion.resumen) || ultimo,
    permiso: operacion.permiso,
    // Sin tramo propio —`POST /x/{id}` o el `DELETE`— no hay clave que lo
    // diga: la marca de irreversible la pone quien lo pinta.
    clave: ultimo.startsWith("{") ? "" : ultimo,
  };
}

/**
 * Las acciones que actúan sobre la COLECCIÓN entera, deducidas del contrato.
 *
 * **Se declaraban a mano, y una lista a mano siempre se queda corta.** El
 * comentario que las declaraba decía que no se podían deducir: «una acción de
 * fila cuelga del identificador y la superficie la delata sola, pero “cargar
 * el almacén” es hermana del listado». Medido el 29-10-2026: **hay 102 POST
 * colgando de una colección sin ningún parámetro en la ruta, y la lista a mano
 * tenía 4**. Trece de ellas no piden cuerpo —son «haz ahora el trabajo que
 * toca»— y ninguna tenía botón en ninguna pantalla. Entre ellas, «he perdido
 * el portátil», que revoca todos los dispositivos de confianza.
 *
 * **Sólo las que no piden cuerpo obligatorio.** Las otras ochenta y nueve
 * necesitan que alguien rellene algo —declarar una regla, ingerir un evento,
 * personalizar una plantilla— y un botón que las llamara vacías contestaría
 * 422. Eso no es una acción: es un formulario, y un formulario inventado desde
 * la ruta se equivoca de campos.
 *
 * Lo que sigue declarándose a mano son **las excepciones**, no la norma: las
 * que piden cuerpo y aun así tienen sentido como botón porque el cuerpo es
 * fijo. Van en `Recurso.acciones` con su motivo.
 */
export function accionesDeColeccion(
  superficie: Superficie | null,
  rutaBase: string,
  puede: (permiso: string | null) => boolean,
): Accion[] {
  if (!superficie) return [];
  const base = rutaBase.split("/");
  const salida: Accion[] = [];

  for (const operacion of superficie.operaciones as Operacion[]) {
    if (operacion.metodo.toUpperCase() !== "POST") continue;
    // Sin NINGÚN parámetro: con uno, actúa sobre un registro y su sitio es la
    // ficha, no la cabecera del listado.
    if (PARAMETRO.test(operacion.ruta)) {
      PARAMETRO.lastIndex = 0;
      continue;
    }
    PARAMETRO.lastIndex = 0;
    const tramos = operacion.ruta.split("/");
    // Uno o DOS tramos más que la colección.
    //
    // Era sólo uno, con este motivo: «con dos —`/sagas/plantillas/clonar`— ya
    // es otra cosa dentro de otra cosa». Suena razonable y **lo midió nadie**.
    // Medido el 05-11-2026 sobre los trece contratos: hay **12 acciones de dos
    // tramos sin parámetro que no alcanza ninguna pantalla**, y tres de ellas
    // son capacidades del catálogo declaradas hechas —instalar una plantilla
    // de automatizaciones, clonar una plantilla de flujo y simular qué pasa
    // con lo que está en vuelo al publicar—. «Otra cosa dentro de otra cosa»
    // describe la ruta, no lo que hace: todas actúan sobre la colección de la
    // pestaña, igual que las de un tramo.
    //
    // Lo que sigue excluido es lo que lleva PARÁMETRO: eso cuelga de un
    // registro y su sitio es la ficha, donde hay identificador.
    const extra = tramos.length - base.length;
    if (extra !== 1 && extra !== 2) continue;
    if (tramos.slice(0, base.length).join("/") !== rutaBase) continue;
    // Un POST a la colección sin tramo extra es el ALTA, que ya tiene su
    // botón; esto exige el tramo, así que no puede colarse.
    //
    // **Pedir cuerpo no descalifica: pide formulario.** Antes se descartaban
    // las dos cosas con el mismo motivo —«un botón que siempre da 422 es peor
    // que no tener botón»—, que vale para una y no para la otra.
    //
    // Medido el 04-11-2026 sobre los trece contratos: de las 98 acciones de
    // colección que caen en una pantalla de módulo se ofrecían **14**. De las
    // 84 descartadas, 71 son rutas distintas y **50 no aparecen en ningún
    // fichero del front**: no las alcanzaba nadie, ni por aquí ni por una
    // pantalla propia. «A qué proveedor iría este encargo», «Comprobar un
    // contenido antes de mandarlo», «Qué faltaría si se generase ahora»,
    // «Dónde duele si un proveedor falla mañana». Las otras 21 sí tienen
    // pantalla escrita a mano —«Qué pasaría si se publicara el mapa» la tiene
    // en Territorios— y por eso el número que importa es 50, no 84.
    //
    // El formulario no hay que inventarlo: la ficha ya lo hace para las
    // acciones de un registro, sacando los campos del `requestBody` del
    // OpenAPI. Son el mismo mecanismo y el mismo componente.
    //
    // `exige_datos` SÍ sigue descartando, y por el motivo original: son
    // parámetros de la URL, el formulario se saca del cuerpo, y una acción así
    // saldría con el formulario vacío y contestaría 422. Medido: de las 84,
    // 83 son sólo cuerpo y **una** pide además parámetro. Esa una se queda
    // fuera a sabiendas, no por descuido.
    if (operacion.exige_datos) continue;
    if (!puede(operacion.permiso)) continue;

    const clave = tramos[tramos.length - 1] ?? "";
    salida.push({
      ruta: operacion.ruta,
      plantilla: operacion.ruta,
      metodo: operacion.metodo,
      // El rótulo lo escribe el servicio dueño: «He perdido el portátil» dice
      // lo que hace mejor que «revocar-todos».
      nombre: comoRotulo(operacion.resumen) || clave,
      permiso: operacion.permiso,
      clave,
    });
  }
  return salida.sort((a, b) => a.nombre.localeCompare(b.nombre, "es"));
}

export interface SubColeccion {
  /** Último tramo: `lineas`, `equipo`, `direcciones`… */
  clave: string;
  /** Ruta real con el identificador del padre puesto. */
  ruta: string;
  /** Ruta con `{param}`, como la nombra el OpenAPI. */
  plantilla: string;
  /** Lo que es, dicho por el propio servidor. */
  nombre: string;
  /** Si se pueden añadir elementos. */
  alta: { plantilla: string; nombre: string } | null;
  /** Lo que se puede hacer con cada elemento. */
  acciones: AccionHija[];
  /** Si se puede quitar un elemento. */
  borrable: boolean;
}

export interface AccionHija {
  /** Ruta con los dos `{param}`, como la nombra el OpenAPI. */
  plantilla: string;
  metodo: string;
  nombre: string;
  clave: string;
}

/**
 * Lo que cuelga de un registro: sus líneas, su equipo, sus direcciones.
 *
 * Son **196** en el sistema, y con ellas las 44 acciones que actúan sobre un
 * hijo —quitar a alguien del equipo de cuenta, verificar un identificador,
 * geocodificar una dirección—. Ninguna se alcanzaba: la ficha solo enseñaba los
 * campos del propio registro, así que la mitad de lo que un CRM guarda sobre un
 * cliente no se podía ni ver ni tocar.
 *
 * Igual que las acciones: salen del contrato. Un hijo nuevo en el servidor
 * aparece solo.
 */
export function subColeccionesDe(
  superficie: Superficie | null,
  rutaBase: string,
  id: string,
  puede: (permiso: string | null) => boolean,
): SubColeccion[] {
  if (!superficie) return [];
  const base = rutaBase.split("/");
  const porClave = new Map<string, SubColeccion>();

  for (const operacion of superficie.operaciones as Operacion[]) {
    const tramos = operacion.ruta.split("/");
    if (tramos.length !== base.length + 2) continue;
    if (!tramos[base.length]?.startsWith("{")) continue;
    const clave = tramos[base.length + 1] ?? "";
    if (!clave || clave.startsWith("{")) continue;
    if (tramos.slice(0, base.length).join("/") !== rutaBase) continue;

    const metodo = operacion.metodo.toUpperCase();
    if (metodo === "GET") {
      if (!puede(operacion.permiso)) continue;
      // Solo lo que devuelve MUCHOS es una sub-colección. Lo que devuelve un
      // objeto —la vista 360 de la cuenta, a quién llamar de un proveedor— es
      // una vista, y pintada como panel salía siempre con «Nada todavía»:
      // un panel que nunca puede tener contenido parece un dato que falta.
      if (operacion.devuelve_lista === false) continue;
      // Ni lo que necesita que alguien conteste algo antes: pedido sin eso
      // responde 422, y como panel salía siempre en error.
      if (operacion.exige_datos) continue;
      porClave.set(clave, {
        clave,
        ruta: operacion.ruta.replace(PARAMETRO, id),
        plantilla: operacion.ruta,
        nombre: comoRotulo(operacion.resumen) || clave,
        alta: null,
        acciones: [],
        borrable: false,
      });
    }
  }

  // El alta y las acciones sobre cada hijo, en una segunda pasada: el panel solo
  // existe si se puede listar, y sin panel no hay dónde ponerlas.
  for (const operacion of superficie.operaciones as Operacion[]) {
    const tramos = operacion.ruta.split("/");
    if (tramos.slice(0, base.length).join("/") !== rutaBase) continue;
    if (!tramos[base.length]?.startsWith("{")) continue;
    const clave = tramos[base.length + 1] ?? "";
    const panel = porClave.get(clave);
    if (!panel) continue;
    const metodo = operacion.metodo.toUpperCase();

    if (tramos.length === base.length + 2 && metodo === "POST" && puede(operacion.permiso)) {
      panel.alta = { plantilla: operacion.ruta, nombre: comoRotulo(operacion.resumen) || clave };
      continue;
    }
    // Sobre un hijo: `/X/{id}/Y/{hijo}` y `/X/{id}/Y/{hijo}/accion`.
    if (tramos.length < base.length + 3) continue;
    if (!tramos[base.length + 2]?.startsWith("{")) continue;
    if (!puede(operacion.permiso)) continue;

    if (tramos.length === base.length + 3) {
      if (metodo === "DELETE") panel.borrable = true;
      continue;
    }
    if (tramos.length === base.length + 4 && metodo !== "GET") {
      panel.acciones.push({
        plantilla: operacion.ruta,
        metodo,
        nombre: comoRotulo(operacion.resumen) || (tramos[base.length + 3] ?? ""),
        clave: tramos[base.length + 3] ?? "",
      });
    }
  }

  return [...porClave.values()].sort((a, b) => a.nombre.localeCompare(b.nombre, "es"));
}
