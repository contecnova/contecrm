/**
 * La paleta de comandos (⌘K / Ctrl+K).
 *
 * Con veinticinco módulos y veinte pantallas fijas, navegar hasta una pantalla
 * son tres clics; escribir su nombre es uno. La paleta no sustituye al menú:
 * el menú es para descubrir qué hay, la paleta para volver a algo que ya se
 * sabe que existe.
 *
 * Busca sobre **lo que se ve**, no sobre el camino: nadie recuerda que las
 * cuentas viven en `/m/cuentas`, pero todo el mundo recuerda «cuentas». Y
 * también sobre el grupo del catálogo, porque «ventas» tiene que traer las
 * pantallas de ventas aunque ninguna se llame así.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { MODULOS, recursoVisible } from "@/lib/modulos";
import { VISIBILIDAD } from "@/lib/visibilidad";
import { entradaVisible, iconoDeGrupo, todasLasEntradas } from "@/lib/navegacion";
import { usePermitidas } from "@/lib/permisos";
import type { Sesion } from "@/lib/sesion";
import { cn } from "@/lib/utiles";

interface Destino {
  a: string;
  rotulo: string;
  grupo: string;
  icono: string;
}

/** Normaliza para comparar: sin acentos y en minúsculas. */
function normalizar(texto: string): string {
  return texto
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
}

export function Paleta({
  abierta,
  alCerrar,
  sesion,
}: {
  abierta: boolean;
  alCerrar: () => void;
  sesion: Sesion | null;
}) {
  const { t } = useTranslation();
  const navegar = useNavigate();
  const permitidas = usePermitidas();
  const [consulta, setConsulta] = useState("");
  const [indice, setIndice] = useState(0);
  const campoRef = useRef<HTMLInputElement>(null);
  const listaRef = useRef<HTMLUListElement>(null);

  const destinos = useMemo<Destino[]>(() => {
    // Se filtra con el mismo criterio que el menú. Encontrar por búsqueda una
    // pantalla que el menú esconde es peor que no esconderla: parece que el
    // sistema se contradice, y al abrirla sale un error.
    const fijas: Destino[] = todasLasEntradas()
      .filter((e) => entradaVisible(sesion, e))
      .map((e) => ({
        a: e.a,
        rotulo: t(e.clave),
        grupo: t("nav.grupoPantallas"),
        icono: e.icono,
      }));
    // Con el resumen de visibilidad y no con la tabla entera: la paleta vive
    // en el marco, así que lo que importe viaja en el paquete de apertura. Lo
    // único que necesita es decidir si el módulo se ofrece.
    const modulos: Destino[] = MODULOS.filter((m) =>
      (VISIBILIDAD[m.ruta] ?? []).some((pe) =>
        recursoVisible(sesion, { listar: pe.r, permiso: pe.p, solo_plataforma: pe.sp }, permitidas),
      ),
    ).map((m) => ({
      a: `/m/${m.ruta}`,
      rotulo: m.titulo,
      grupo: m.grupo,
      icono: iconoDeGrupo(m.grupo),
    }));
    return [...fijas, ...modulos];
  }, [t, sesion, permitidas]);

  const resultados = useMemo(() => {
    const aguja = normalizar(consulta.trim());
    if (!aguja) return destinos;
    return destinos.filter(
      (d) => normalizar(d.rotulo).includes(aguja) || normalizar(d.grupo).includes(aguja),
    );
  }, [consulta, destinos]);

  // Al abrir se limpia y se enfoca. Conservar la consulta anterior parece
  // cómodo y no lo es: se abre la paleta para ir a otro sitio, no al mismo.
  useEffect(() => {
    if (!abierta) return;
    setConsulta("");
    setIndice(0);
    // El foco se pide en el siguiente cuadro: en el mismo, el campo todavía no
    // está en el documento y la llamada no hace nada.
    const id = window.requestAnimationFrame(() => campoRef.current?.focus());
    return () => window.cancelAnimationFrame(id);
  }, [abierta]);

  useEffect(() => {
    setIndice(0);
  }, [consulta]);

  // El elemento marcado se trae a la vista al moverse con el teclado. Sin esto,
  // en una lista de cuarenta destinos la selección se va fuera de la ventana y
  // parece que las flechas no hacen nada.
  useEffect(() => {
    const marcado = listaRef.current?.children[indice] as HTMLElement | undefined;
    marcado?.scrollIntoView({ block: "nearest" });
  }, [indice]);

  if (!abierta) return null;

  function alTeclear(evento: React.KeyboardEvent) {
    if (evento.key === "Escape") {
      evento.preventDefault();
      alCerrar();
      return;
    }
    if (evento.key === "ArrowDown") {
      evento.preventDefault();
      setIndice((i) => (resultados.length === 0 ? 0 : (i + 1) % resultados.length));
      return;
    }
    if (evento.key === "ArrowUp") {
      evento.preventDefault();
      setIndice((i) =>
        resultados.length === 0 ? 0 : (i - 1 + resultados.length) % resultados.length,
      );
      return;
    }
    if (evento.key === "Enter") {
      evento.preventDefault();
      const elegido = resultados[indice];
      if (elegido) {
        navegar(elegido.a);
        alCerrar();
      }
    }
  }

  return (
    <div className="fixed inset-0 z-command flex items-start justify-center p-4 pt-24">
      <button
        type="button"
        onClick={alCerrar}
        aria-label={t("nav.cerrarPaleta")}
        className="fixed inset-0 cursor-default bg-ink/50"
      />
      {/* `dialog` con `aria-modal` para que el lector anuncie que lo de detrás
          queda fuera; sin eso, se sigue leyendo la página entera por debajo. */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("nav.abrirPaleta")}
        className="relative w-full max-w-xl animate-fade-in overflow-hidden rounded-2xl border border-ink-dim/60 bg-paper shadow-elevation-3"
      >
        <div className="flex items-center gap-2 border-b border-ink-dim/60 px-4">
          <Icono nombre="search" className="text-ink-muted" />
          <label htmlFor="paleta-consulta" className="sr-only">
            {t("nav.buscarPlaceholder")}
          </label>
          <input
            id="paleta-consulta"
            ref={campoRef}
            value={consulta}
            onChange={(e) => setConsulta(e.target.value)}
            onKeyDown={alTeclear}
            placeholder={t("nav.buscarPlaceholder")}
            className="h-12 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
            autoComplete="off"
            aria-controls="paleta-resultados"
            aria-activedescendant={resultados[indice] ? `paleta-op-${indice}` : undefined}
          />
          <kbd className="rounded border border-ink-dim/60 bg-paper-light px-1.5 py-0.5 font-mono text-3xs text-ink-muted">
            Esc
          </kbd>
        </div>

        {resultados.length === 0 ? (
          <p className="px-4 py-8 text-center text-xs text-ink-faint" role="status">
            {t("nav.sinResultados", { consulta })}
          </p>
        ) : (
          <ul
            id="paleta-resultados"
            ref={listaRef}
            className="max-h-80 overflow-y-auto p-1"
            aria-label={t("nav.resultados")}
          >
            {resultados.map((destino, i) => (
              <li key={`${destino.a}-${i}`} id={`paleta-op-${i}`}>
                <button
                  type="button"
                  onClick={() => {
                    navegar(destino.a);
                    alCerrar();
                  }}
                  onMouseEnter={() => setIndice(i)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors",
                    i === indice ? "bg-paper-light text-ink" : "text-ink-muted hover:bg-paper-light",
                  )}
                >
                  <Icono nombre={destino.icono} tamano="sm" className="text-ink-faint" />
                  <span className="flex-1 truncate">{destino.rotulo}</span>
                  <span className="shrink-0 text-3xs text-ink-faint">{destino.grupo}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
