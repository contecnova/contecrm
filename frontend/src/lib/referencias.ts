/**
 * Los campos que apuntan a otro registro, y dónde se buscan.
 *
 * `cuenta_id` no es un texto: es un cliente. Pedirle a una persona que escriba
 * `01a0cd8c-880c-7f85-96bc-0f01dce176a2` no es un formulario, es un volcado de
 * la base de datos con una etiqueta encima — y es lo que hacía el formulario de
 * «convertir un lead», que es una de las acciones más frecuentes de un CRM.
 *
 * **De dónde sale la correspondencia.** No de una tabla nueva: los recursos ya
 * declaran su `objeto` —`cuenta`, `contacto`, `oportunidad`— porque de ahí
 * salen las fichas. `cuenta_id` quita el sufijo, busca el recurso cuyo objeto
 * es `cuenta` y usa su ruta de listado. Una segunda tabla de correspondencias
 * se separaría de la primera en cuanto alguien añadiera un objeto.
 */

import { MODULOS, type Recurso } from "@/lib/modulos";

/** El objeto al que apunta un campo, si apunta a alguno: `cuenta_id` → `cuenta`. */
export function objetoDe(campo: string): string | null {
  const m = /^(.+)_id$/.exec(campo);
  return m?.[1] ?? null;
}

/**
 * El recurso donde se buscan los valores de este campo.
 *
 * Devuelve `null` cuando no hay ninguno: `owner_id` apunta a un usuario y los
 * usuarios no son un objeto con ficha en el catálogo del front. Ahí se deja el
 * campo como estaba en vez de inventar un buscador que no busca nada.
 */
export function recursoDeReferencia(campo: string): Recurso | null {
  const objeto = objetoDe(campo);
  if (!objeto) return null;
  for (const modulo of MODULOS) {
    for (const recurso of modulo.recursos) {
      if (recurso.objeto === objeto) return recurso;
    }
  }
  return null;
}
