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
      nombre: operacion.resumen || clave,
      permiso: operacion.permiso,
      clave,
    });
  }
  return salida.sort((a, b) => a.nombre.localeCompare(b.nombre, "es"));
}
