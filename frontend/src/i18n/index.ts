/**
 * Textos de la interfaz (CRM-07.04.01.05).
 *
 * Todo texto visible pasa por aquí, incluido el castellano: si el idioma base
 * se escribe suelto en los componentes, añadir el segundo obliga a repasar la
 * aplicación entera buscando cadenas, y siempre se queda alguna.
 */

import i18next from "i18next";
import { initReactI18next } from "react-i18next";

import es from "@/i18n/es";

export const IDIOMAS = ["es"] as const;
export type Idioma = (typeof IDIOMAS)[number];

/**
 * Los textos de las pantallas diferidas, cargados una sola vez.
 *
 * Se llama desde el `lazy` de cada pantalla, **antes** de resolverla: así no
 * hay instante en que una pantalla exista sin sus textos. La promesa se
 * guarda, así que abrir diez pantallas pide el trozo una vez.
 */
let textosDePantallas: Promise<void> | null = null;

export function cargarTextosDePantallas(): Promise<void> {
  textosDePantallas ??= import("@/i18n/es.pantallas").then(({ default: extra }) => {
    // `true, true`: profundo y sobrescribiendo. Sin lo primero, una sección
    // con subsecciones entra a medias; sin lo segundo, recargar en caliente
    // deja los de antes.
    i18next.addResourceBundle("es", "translation", extra, true, true);
  });
  return textosDePantallas;
}

/**
 * El `lang` del documento es el de los TEXTOS, no el de la localización del
 * tenant (auditoría 13-11-2026, UX-15).
 *
 * Lo ponía `fijarLocalizacion`, y un tenant en `pt-PT` dejaba marcado como
 * portugués un documento escrito en castellano: el lector de pantalla lo leía
 * con la fonética equivocada. Aquí se fija con el idioma que i18n ha
 * resuelto de verdad —uno de `IDIOMAS`—, y se vuelve a fijar si cambia.
 */
function marcarIdiomaDelDocumento(idioma: string): void {
  if (typeof document !== "undefined" && idioma)
    document.documentElement.lang = idioma;
}

export async function iniciarI18n(idioma: string): Promise<void> {
  i18next.off("languageChanged", marcarIdiomaDelDocumento);
  i18next.on("languageChanged", marcarIdiomaDelDocumento);
  await i18next.use(initReactI18next).init({
    lng: (IDIOMAS as readonly string[]).includes(idioma) ? idioma : "es",
    fallbackLng: "es",
    resources: { es: { translation: es } },
    interpolation: { escapeValue: false },
  });
  marcarIdiomaDelDocumento(i18next.resolvedLanguage ?? i18next.language);
}

export default i18next;
