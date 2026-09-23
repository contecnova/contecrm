/**
 * El marco de la aplicación: navegación, cabecera y contenido
 * (CRM-07.04.01.03).
 *
 * Con el sistema de diseño de la casa (CRM-07.04.01.02): los mismos tokens
 * `paper` / `ink` / `accent` que contecmind, copiados tal cual. Dos paletas
 * «parecidas» se separan a la tercera pantalla que alguien añade, y quien usa
 * las dos soluciones acaba notando que cambia de producto.
 */

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

import { llamar } from "@/lib/api";
import { config } from "@/lib/config";
import { porGrupo, type Modulo } from "@/lib/modulos";
import type { Sesion } from "@/lib/sesion";
import { aplicarTema, temaActual } from "@/lib/tema";

export interface Props {
  sesion: Sesion | null;
  children: ReactNode;
}

export function Marco({ sesion, children }: Props) {
  const { t } = useTranslation();

  async function salir() {
    // Se recarga en vez de vaciar el estado: es la única forma de estar seguro
    // de que no queda nada del usuario anterior en memoria.
    await llamar("/api/v1/sesion/salir", { metodo: "POST" }).catch(() => undefined);
    window.location.assign("/");
  }

  return (
    <div className="flex min-h-full flex-col bg-paper-dark">
      {/* Un salto al contenido es lo primero que necesita quien navega con
          teclado: sin él, cada página empieza por recorrer el menú entero. */}
      <a
        href="#contenido"
        className="sr-only focus:not-sr-only focus:absolute focus:z-focus-ring focus:m-2 focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-paper"
      >
        {t("app.saltarAlContenido")}
      </a>

      {/* La suplantación se dice SIEMPRE y en todas las pantallas. Un
          administrador que olvida que está viendo el CRM en nombre de otra
          persona toma decisiones sobre datos que no son los que cree. */}
      {sesion?.suplantado_por ? (
        <p className="bg-warning px-4 py-1 text-center text-2xs text-ink" role="status">
          {t("app.suplantado")}
        </p>
      ) : null}

      {/* En móvil la cabecera se apila en vez de encogerse: una barra con seis
          enlaces a 360 px o desborda o los deja de 8 px, y las dos cosas son
          peores que dos líneas (CRM-07.04.01.08). */}
      <header className="flex flex-col gap-2 border-b border-ink-dim/60 bg-paper px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
        {config().logotipo ? (
          <img src={config().logotipo} alt={config().nombre} className="h-6" />
        ) : (
          <span className="font-medium text-ink">{config().nombre}</span>
        )}
        <nav aria-label="Principal" className="flex flex-wrap gap-1">
          <Enlace a="/" texto={t("nav.inicio")} />
          {/* Los módulos salen de la declaración de cobertura, no de una lista
              aparte: dos listas que tienen que coincidir acaban no
              coincidiendo, y la que se queda corta es siempre el menú. */}
          {[...porGrupo()].map(([grupo, modulos]) => (
            <Grupo key={grupo} nombre={grupo} modulos={modulos} />
          ))}
          <Enlace a="/administracion" texto={t("nav.consola")} />
          <Enlace a="/estado" texto={t("nav.estado")} />
          <Enlace a="/cobertura" texto={t("nav.cobertura")} />
          <Enlace a="/procesos" texto={t("nav.procesos")} />
          <Enlace a="/cuadros" texto={t("nav.cuadros")} />
          <Enlace a="/casos" texto={t("nav.casos")} />
          <Enlace a="/consola-agente" texto={t("nav.consolaAgente")} />
          <Enlace a="/conocimiento" texto={t("nav.conocimiento")} />
          <Enlace a="/marketing" texto={t("nav.marketing")} />
          <Enlace a="/explotacion" texto={t("nav.explotacion")} />
          <Enlace a="/recorrido" texto={t("nav.recorrido")} />
          <Enlace a="/proveedores" texto={t("nav.proveedores")} />
          <Enlace a="/coste" texto={t("nav.coste")} />
          <Enlace a="/inteligencia" texto={t("nav.inteligencia")} />
          <Enlace a="/puesto" texto={t("nav.puesto")} />
          <Enlace a="/alm" texto={t("nav.alm")} />
          <Enlace a="/rendimiento" texto={t("nav.rendimiento")} />
          <Enlace a="/suite" texto={t("nav.suite")} />
          {/* La ayuda va la última y siempre visible: se busca justo cuando uno
              está atascado, y esconderla en un menú es esconderla. */}
          <Enlace a="/ayuda" texto={t("nav.ayuda")} />
        </nav>
        <div className="flex items-center gap-3 sm:ml-auto">
          <button
            type="button"
            onClick={() => aplicarTema(temaActual() === "oscuro" ? "claro" : "oscuro")}
            className="rounded-lg px-2 py-1 text-2xs text-ink-muted hover:bg-paper-light"
          >
            {t("app.tema")}
          </button>
          {sesion ? (
            <span className="text-2xs text-ink-faint">{sesion.nombre || sesion.email}</span>
          ) : null}
          {sesion ? (
            <button
              type="button"
              onClick={salir}
              className="rounded-lg px-2 py-1 text-2xs text-ink-muted hover:bg-paper-light"
            >
              {t("app.cerrarSesion")}
            </button>
          ) : null}
        </div>
      </header>

      <main id="contenido" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        {children}
      </main>
    </div>
  );
}

function Grupo({ nombre, modulos }: { nombre: string; modulos: Modulo[] }) {
  // Un desplegable nativo y no uno a medida: el nativo ya sabe de teclado, de
  // lectores de pantalla y de cerrarse al perder el foco, y una réplica hecha a
  // mano tarda meses en llegar a eso.
  return (
    <details className="relative">
      <summary className="cursor-pointer list-none rounded-lg px-3 py-1.5 text-xs text-ink-muted hover:bg-paper-light">
        {nombre}
      </summary>
      <div className="absolute z-popover mt-1 flex min-w-48 flex-col rounded-xl border border-ink-dim/60 bg-paper p-1 shadow-popover">
        {modulos.map((m) => (
          <Enlace key={m.ruta} a={`/m/${m.ruta}`} texto={m.titulo} />
        ))}
      </div>
    </details>
  );
}

function Enlace({ a, texto }: { a: string; texto: string }) {
  return (
    <NavLink
      to={a}
      end={a === "/"}
      className={({ isActive }) =>
        `rounded-lg px-3 py-1.5 text-xs ${
          isActive ? "bg-paper-light text-ink" : "text-ink-muted hover:bg-paper-light"
        }`
      }
    >
      {texto}
    </NavLink>
  );
}
