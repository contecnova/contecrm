/**
 * El marco de la aplicación: panel lateral, barra superior y contenido
 * (CRM-07.04.01.03).
 *
 * Con el sistema de diseño de la casa (CRM-07.04.01.02): los mismos tokens
 * `paper` / `ink` / `accent`, los mismos iconos de Material Symbols y el mismo
 * reparto de la pantalla que contecmind. Dos productos «parecidos» se separan a
 * la tercera pantalla que alguien añade, y quien usa los dos acaba notando que
 * cambia de herramienta.
 *
 * **Por qué cambió el reparto.** Esto era una barra horizontal con veintidós
 * enlaces que envolvían en tres líneas, sin iconos, sin agrupar y sin decir
 * dónde estabas. Una lista horizontal no escala pasados unos pocos elementos, y
 * este producto tiene veinticinco módulos más veinte pantallas fijas. El panel
 * a la izquierda permite agrupar y plegar, la barra superior dice dónde estás y
 * la paleta lleva a cualquier sitio escribiendo su nombre.
 */

import { Suspense, lazy, useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { BarraLateral } from "@/componentes/BarraLateral";
import { BarraSuperior } from "@/componentes/BarraSuperior";
import { llamar } from "@/lib/api";
import { ProveedorPanel } from "@/lib/panel";
import { ProveedorPermisos } from "@/lib/permisos";
import type { Sesion } from "@/lib/sesion";

/**
 * La paleta se carga cuando se abre, no al arrancar.
 *
 * Es la única pieza del marco que NO se ve nunca hasta que alguien la pide —con
 * Ctrl+K o pulsando el buscador—, y arrastra el índice de pantallas entero. En
 * el paquete de apertura son 8 kB que nadie usa para mirar sus casos, y el tope
 * de apertura está para que ese tipo de peso se note. Al abrirla se descarga en
 * una petición que ya va en paralelo con lo que se está escribiendo.
 */
const Paleta = lazy(() => import("@/componentes/Paleta").then((m) => ({ default: m.Paleta })));

export interface Props {
  sesion: Sesion | null;
  children: ReactNode;
}

export function Marco({ sesion, children }: Props) {
  const { t } = useTranslation();
  const [paleta, setPaleta] = useState(false);

  const salir = useCallback(async () => {
    // Se recarga en vez de vaciar el estado: es la única forma de estar seguro
    // de que no queda nada del usuario anterior en memoria.
    await llamar("/api/v1/sesion/salir", { metodo: "POST" }).catch(() => undefined);
    window.location.assign("/");
  }, []);

  // El atajo se escucha en la ventana y no en un campo: tiene que funcionar
  // esté donde esté el foco, que es justo lo que lo hace útil.
  useEffect(() => {
    function alTeclear(evento: KeyboardEvent) {
      if ((evento.metaKey || evento.ctrlKey) && evento.key.toLowerCase() === "k") {
        evento.preventDefault();
        setPaleta((v) => !v);
      }
    }
    window.addEventListener("keydown", alTeclear);
    return () => window.removeEventListener("keydown", alTeclear);
  }, []);

  return (
    <ProveedorPanel>
      <ProveedorPermisos sesion={sesion}>
      <div className="flex h-screen overflow-hidden bg-paper-dark">
        {/* Un salto al contenido es lo primero que necesita quien navega con
            teclado: sin él, cada página empieza por recorrer el menú entero. */}
        <a
          href="#contenido"
          className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-focus-ring focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-paper focus:shadow-elevation-3"
        >
          {t("app.saltarAlContenido")}
        </a>

        <BarraLateral sesion={sesion} alSalir={() => void salir()} />

        <div className="flex min-w-0 flex-1 flex-col">
          {/* La suplantación se dice SIEMPRE y en todas las pantallas. Un
              administrador que olvida que está viendo el CRM en nombre de otra
              persona toma decisiones sobre datos que no son los que cree. */}
          {sesion?.suplantado_por ? (
            <p className="bg-warning px-4 py-1 text-center text-2xs text-ink" role="status">
              {t("app.suplantado")}
            </p>
          ) : null}

          <BarraSuperior
            sesion={sesion}
            alSalir={() => void salir()}
            alAbrirPaleta={() => setPaleta(true)}
          />

          <main id="contenido" className="min-h-0 flex-1 overflow-y-auto">
            <div className="contenido-pagina">{children}</div>
          </main>
        </div>

        {/* Sin `fallback` visible: mientras llega no hay nada que enseñar, y un
            esqueleto parpadeando encima de la pantalla es peor que esperar los
            milisegundos que tarda. */}
        {paleta ? (
          <Suspense fallback={null}>
            <Paleta abierta alCerrar={() => setPaleta(false)} sesion={sesion} />
          </Suspense>
        ) : null}
      </div>
      </ProveedorPermisos>
    </ProveedorPanel>
  );
}
