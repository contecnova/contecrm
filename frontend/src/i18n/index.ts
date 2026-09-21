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

export async function iniciarI18n(idioma: string): Promise<void> {
  await i18next.use(initReactI18next).init({
    lng: (IDIOMAS as readonly string[]).includes(idioma) ? idioma : "es",
    fallbackLng: "es",
    resources: { es: { translation: es } },
    interpolation: { escapeValue: false },
  });
}

export default i18next;
