/**
 * Densidad de la interfaz: cuánto cabe en pantalla.
 *
 * **Vive en el perfil, no en el navegador**, y esa es toda la diferencia con el
 * tema claro/oscuro. El tema depende de la pantalla y de la luz de la sala, así
 * que tiene sentido que sea de este navegador. La densidad depende de la vista
 * y del trabajo de quien mira: quien la pone cómoda en su portátil la quiere
 * cómoda también en el ordenador del cliente, y en el del compañero cuando
 * entra con su cuenta.
 *
 * Por eso sale de `/mis-preferencias`, que resuelve la cadena de siempre
 * —usuario → unidad → empresa → el defecto del despliegue, `UI_DENSIDAD`—.
 *
 * **Lo que esto NO hace, y es deliberado: no guarda nada al arrancar.** La
 * tentación es escribir el valor por defecto en cuanto se monta, «para tenerlo
 * ya». Eso entierra el ajuste del administrador para siempre: a partir del
 * primer arranque cada persona tiene un valor propio idéntico al defecto, y el
 * día que la empresa cambie el suyo no le cambia a nadie. Sólo se escribe
 * cuando alguien elige, que es cuando hay algo que decir.
 */

import { llamar } from "@/lib/api";

export type Densidad = "compacta" | "comoda";

/** El defecto del producto si el servidor todavía no ha contestado. */
const MIENTRAS_LLEGA: Densidad = "compacta";

function esDensidad(valor: unknown): valor is Densidad {
  return valor === "compacta" || valor === "comoda";
}

/**
 * Pinta la densidad en el documento.
 *
 * Va en `data-densidad` del `<html>` y no en una clase porque `.dark` ya usa la
 * clase: son dos ejes independientes —hay quien quiere oscuro y compacto, y
 * quien quiere claro y cómodo— y mezclarlos en el mismo atributo obliga a
 * conocer uno para cambiar el otro.
 */
export function aplicarDensidad(densidad: Densidad): void {
  document.documentElement.dataset.densidad = densidad;
}

/**
 * La que le toca a quien ha entrado.
 *
 * Si la llamada falla se devuelve el defecto y **no se escribe nada**: una
 * preferencia no puede tumbar la aplicación, y tampoco puede inventarse un
 * valor que luego parezca elegido.
 */
export async function densidadDelPerfil(): Promise<Densidad> {
  try {
    const r = await llamar<Record<string, { valor?: unknown }>>("/api/v1/mis-preferencias");
    const valor = r.datos?.ui_densidad?.valor;
    return esDensidad(valor) ? valor : MIENTRAS_LLEGA;
  } catch {
    return MIENTRAS_LLEGA;
  }
}

/**
 * Guarda la elección de quien la hace, en su ámbito.
 *
 * El ámbito no viaja aquí: lo pone el servidor a partir de quien llama. Si lo
 * mandara el cliente, cualquiera cambiaría la densidad de toda la empresa.
 */
export async function elegirDensidad(densidad: Densidad): Promise<void> {
  aplicarDensidad(densidad);
  await llamar("/api/v1/mis-preferencias/ui_densidad", {
    metodo: "PUT",
    cuerpo: { valor: densidad },
  });
}
