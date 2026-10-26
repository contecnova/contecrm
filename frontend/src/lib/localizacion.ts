/**
 * La localización del tenant, leída del servidor (CRM-07.04.01.05).
 *
 * El CRM es headless y por eso la jerarquía la resuelve **el servidor**: si
 * cada frontend la resolviera por su cuenta, la web y el móvil acabarían
 * escribiendo la misma fecha de dos maneras. `GET /api/v1/localizacion`
 * devuelve lo ya resuelto —global → tier → tenant → unidad → usuario— con
 * ejemplos que son el contrato: un cliente puede comprobar que formatea igual
 * que el servidor sin reimplementar nada.
 *
 * Esa ruta existía y **el front no la leía**: tenía `"es-ES"` escrito a mano en
 * dieciséis sitios de cinco ficheros, y los formateadores creados como
 * constantes de módulo, o sea construidos al importar y por tanto imposibles de
 * cambiar. Medido el 26-10-2026.
 */

import { llamar } from "@/lib/api";
import { fijarLocalizacion } from "@/lib/formato";

/** Lo que devuelve la ruta. Sólo lo que esta capa necesita. */
interface Localizacion {
  idioma: string;
  zona_horaria: string;
  moneda_funcional: string;
}

/**
 * Pide la localización y la aplica. **No lanza.**
 *
 * Que no lance es la decisión: se llama en el arranque, antes de que haya
 * sesión en muchos casos, y una pantalla en blanco porque no se pudo leer un
 * formato de fecha sería peor que un número con la coma en otro sitio. Si
 * falla, se queda el respaldo y los formateadores se rehacen la próxima vez.
 */
export async function aplicarLocalizacion(): Promise<string> {
  try {
    const { datos } = await llamar<Localizacion>("/api/v1/localizacion");
    // El idioma del tenant es `es`, `pt`… y `Intl` entiende tanto eso como
    // `es-ES`: se pasa tal cual y se deja que el navegador resuelva la región.
    const idioma = (datos?.idioma ?? "").trim();
    if (idioma) fijarLocalizacion(idioma);
    return idioma;
  } catch {
    return "";
  }
}
