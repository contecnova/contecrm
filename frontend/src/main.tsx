/**
 * Arranque de la aplicación de referencia (CRM-07.04.01.01).
 *
 * Mismo stack que el resto de soluciones de la casa: React, Vite, TypeScript y
 * Tailwind. No por gusto: una segunda cadena de construcción es una segunda
 * cosa que mantener, actualizar y auditar.
 */

import "@fontsource/geist/400.css";
import "@fontsource/geist/500.css";
import "@fontsource/geist/600.css";
import "@fontsource/roboto-mono/400.css";
import "@material-symbols/font-400/outlined.css";
import "@/index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "@/App";
import { iniciarI18n } from "@/i18n";
import { aplicarMarca, cargarConfig } from "@/lib/config";

async function arrancar() {
  // La configuración se lee ANTES de montar nada: si la aplicación se monta
  // primero, la primera llamada a la API sale con la base por defecto y falla
  // en cualquier instalación que no sirva el front desde el mismo origen.
  const config = await cargarConfig();
  aplicarMarca(config);
  await iniciarI18n(navigator.language?.slice(0, 2) || config.idioma);

  const raiz = document.getElementById("root");
  if (!raiz) throw new Error("Falta el elemento #root");
  createRoot(raiz).render(
    <StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </StrictMode>,
  );
}

void arrancar();
