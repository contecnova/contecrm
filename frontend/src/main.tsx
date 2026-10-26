/**
 * Arranque de la aplicación de referencia (CRM-07.04.01.01).
 *
 * Mismo stack que el resto de soluciones de la casa: React, Vite, TypeScript y
 * Tailwind. No por gusto: una segunda cadena de construcción es una segunda
 * cosa que mantener, actualizar y auditar.
 */

// Las mismas que carga contecmind, y en sus mismos pesos (29-09-2026).
//
// La lista de `fontFamily` empieza por «Google Sans Text», que es lo que pone
// contecmind, pero NINGUNO de los dos productos la tiene: es propietaria de
// Google y su propio comentario lo dice. Lo que renderizan los dos de verdad
// es **Geist**, que es la siguiente de la lista y sí está cargada. Dejar la
// lista sin cargar Geist habría hecho que el navegador cayera a la del sistema
// y que las dos aplicaciones se vieran distintas mientras el fichero decía que
// eran iguales.
//
// Se cargan los pesos 300 a 800 porque son los que carga contecmind: con menos,
// el navegador sintetiza los que falten y el trazo no es el mismo.
import "@fontsource/geist/300.css";
import "@fontsource/geist/400.css";
import "@fontsource/geist/500.css";
import "@fontsource/geist/600.css";
import "@fontsource/geist/700.css";
import "@fontsource/geist/800.css";
// Roboto Mono, la monoespaciada de contecmind. Antes era Geist Mono, la de
// contecflow.
import "@fontsource/roboto-mono/400.css";
import "@fontsource/roboto-mono/500.css";
import "@material-symbols/font-400/outlined.css";
import "@/index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "@/App";
import { iniciarI18n } from "@/i18n";
import { aplicarMarca, cargarConfig } from "@/lib/config";
import { aplicarLocalizacion } from "@/lib/localizacion";

async function arrancar() {
  // La configuración se lee ANTES de montar nada: si la aplicación se monta
  // primero, la primera llamada a la API sale con la base por defecto y falla
  // en cualquier instalación que no sirva el front desde el mismo origen.
  const config = await cargarConfig();
  aplicarMarca(config);
  await iniciarI18n(navigator.language?.slice(0, 2) || config.idioma);

  // La localización del TENANT, resuelta por el servidor (CRM-07.04.01.05).
  //
  // `GET /api/v1/localizacion` resuelve la jerarquía global → tier → tenant →
  // unidad → usuario y existe desde hace tiempo; el front no la leía y tenía
  // `"es-ES"` escrito a mano en dieciséis sitios, así que un tenant en
  // Portugal o en México veía sus números escritos como en España.
  //
  // **No bloquea el arranque.** Si la petición falla —o todavía no hay
  // sesión— se monta igual con el respaldo: una pantalla en blanco porque no
  // se pudo leer un formato de fecha sería peor que un número con la coma en
  // otro sitio. Cuando llega, los formateadores se rehacen.
  //
  // Se intenta aquí y **se vuelve a intentar al haber sesión** (en `App`): en
  // el arranque puede no haberla todavía, y entonces esta llamada no devuelve
  // nada útil.
  void aplicarLocalizacion();

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
