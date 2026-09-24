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
/**
 * Campos que apuntan a una **persona** de la casa, aunque no lo digan.
 *
 * `owner_id` es quien lleva la cuenta, `responsable_id` quien responde,
 * `dueno_id` de quién es la métrica. Ninguno se llama `usuario_id`, así que la
 * regla del sufijo no los reconoce y salían como un identificador de treinta y
 * seis caracteres a la vista — que ni se lee ni se puede escribir.
 *
 * Es una lista corta y de presentación, no de negocio: lo que decide quién
 * puede ser cada uno lo sigue diciendo el servidor. Una columna puede además
 * declararlo ella misma (`info={"referencia": "usuario"}`), y eso manda.
 */
const SON_PERSONAS = new Set([
  "owner_id",
  "responsable_id",
  "dueno_id",
  "asignada_a",
  "asignado_a",
  "autor_id",
  "testigo_id",
  "decidido_por",
  "creado_por",
  "aprobado_por_id",
  "revisado_por_id",
  "propietario_id",
  "actua_como_id",
]);

/**
 * Campos que apuntan a **otro registro del mismo tipo**.
 *
 * El `padre_id` de una campaña es otra campaña; el `maestro_id` de un caso,
 * otro caso. No hay ningún objeto que se llame «padre», así que la regla del
 * sufijo no los reconoce y salían como un identificador a la vista. Se resuelve
 * contra el propio recurso, que es lo que son.
 */
const SON_DEL_MISMO_TIPO = new Set([
  "padre_id",
  "maestro_id",
  "caso_maestro_id",
  "original_id",
  "anterior_id",
  "renovado_de_id",
  "sustituye_a_id",
  "sustituido_por_id",
]);

export function recursoDeReferencia(
  campo: string,
  declarado = "",
  propio?: Recurso | null,
): Recurso | null {
  // Del mismo tipo: se devuelve el recurso desde el que se está editando.
  if (!declarado && propio && SON_DEL_MISMO_TIPO.has(campo)) return propio;
  // Lo que diga el servidor manda: hay campos que apuntan a un objeto que no
  // se adivina por el nombre —`origen_id` a un contacto, `anotada_por_id` a un
  // usuario— y ahí adivinar es no enseñar nada.
  const objeto = declarado || (SON_PERSONAS.has(campo) ? "usuario" : objetoDe(campo));
  if (!objeto) return null;
  for (const modulo of MODULOS) {
    for (const recurso of modulo.recursos) {
      if (recurso.objeto === objeto) return recurso;
    }
  }
  return null;
}
