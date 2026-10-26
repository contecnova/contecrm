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

/**
 * La marca del tenant, aplicada encima de la del despliegue (CRM-07.04.01.04).
 *
 * `config.json` da la marca del **despliegue**, y sirve para la pantalla de
 * entrada: ahí todavía no se sabe de qué tenant es quien mira. Pero la marca es
 * **por tenant** —el catálogo lo dice así— y el servidor la guarda: nombre,
 * logotipo, favicon y colores.
 *
 * El front no la leía: dos tenants en la misma instalación compartían la marca
 * del fichero de despliegue. Medido el 26-10-2026.
 *
 * Se aplica **sólo cuando está activa**, que es lo que decide el servidor: una
 * marca a medias pisando la del despliegue es justo lo que el diagnóstico de
 * esa misma ruta existe para evitar — si se anuncia y el correo sale con el
 * dominio del fabricante, la conversación que sigue no es sobre el correo.
 */
export async function aplicarMarcaDelTenant(): Promise<boolean> {
  try {
    const { datos } = await llamar<{ aplicable?: Record<string, string> }>("/api/v1/marca");
    const marca = datos?.aplicable ?? {};
    if (!marca.nombre_producto && !marca.color_principal && !marca.logo_url) return false;

    if (marca.nombre_producto) document.title = marca.nombre_producto;
    // El acento se escribe sobre la MISMA variable del sistema de diseño, igual
    // que la del despliegue: así llega a todo lo que ya usa `bg-accent` sin
    // repasar la aplicación.
    const rgb = aRgb(marca.color_principal ?? "");
    if (rgb) {
      document.documentElement.style.setProperty("--accent", rgb);
      document.documentElement.style.setProperty("--accent-text", rgb);
    }
    return true;
  } catch {
    // Sin marca del tenant se queda la del despliegue. Una pantalla sin color
    // de acento es peor que una con el color de la casa.
    return false;
  }
}

/** `#1b6ef3` → `27 110 243`, que es como lo quieren las variables CSS. */
function aRgb(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec((hex || "").trim());
  if (!m) return "";
  const n = parseInt(m[1] ?? "0", 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}
