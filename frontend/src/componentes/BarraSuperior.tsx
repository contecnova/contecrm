/**
 * La barra superior: dónde estás, buscar, tema y quién eres (CRM-07.04.01.03).
 *
 * Mismo reparto que en contecmind, y cada pieza está por un motivo concreto:
 *
 * **La miga de pan** porque el panel lateral dice a dónde se puede ir, no dónde
 * se está. En una ficha de tres niveles —módulo, registro, pestaña— sin miga no
 * hay forma de volver al listado salvo con el botón atrás del navegador.
 *
 * **El buscador** porque con veinticinco módulos y veinte pantallas fijas,
 * llegar navegando cuesta tres clics y saber el nombre cuesta uno.
 *
 * **El menú del usuario** y no un botón de salir suelto: un clic en el avatar
 * que cierra la sesión al instante es una trampa, y se pulsa sin querer.
 */

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router-dom";

import { AvisoDeChat } from "@/componentes/AvisoDeChat";
import { Icono } from "@/componentes/Icono";
import { ALTAS } from "@/lib/altas";
import { humanizar } from "@/lib/formato";
import { MODULOS } from "@/lib/modulos";
import { todasLasEntradas } from "@/lib/navegacion";
import { usePanel } from "@/lib/panel";
import type { Sesion } from "@/lib/sesion";
import { puede } from "@/lib/sesion";
import { aplicarTema, temaActual, type Tema } from "@/lib/tema";
import { cn, teclaAtajo } from "@/lib/utiles";

export interface Miga {
  rotulo: string;
  a?: string;
}

export function BarraSuperior({
  sesion,
  alSalir,
  alAbrirPaleta,
}: {
  sesion: Sesion | null;
  alSalir: () => void;
  alAbrirPaleta: () => void;
}) {
  const { t } = useTranslation();
  const panel = usePanel();
  const ubicacion = useLocation();
  const migas = derivarMigas(ubicacion.pathname, t);

  const [tema, setTema] = useState<Tema>(() => temaActual());
  const [menuAbierto, setMenuAbierto] = useState(false);
  const [crearAbierto, setCrearAbierto] = useState(false);
  const crearRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const avatarRef = useRef<HTMLButtonElement>(null);

  // El menú se cierra al pulsar fuera y con Escape, y el foco vuelve al avatar.
  // Sin devolver el foco, quien navega con teclado lo pierde y vuelve a empezar
  // desde el principio del documento.
  useEffect(() => {
    if (!menuAbierto) return;
    function alPulsarFuera(evento: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(evento.target as Node)) {
        setMenuAbierto(false);
      }
    }
    function alTeclear(evento: KeyboardEvent) {
      if (evento.key === "Escape") {
        setMenuAbierto(false);
        avatarRef.current?.focus();
      }
    }
    window.addEventListener("mousedown", alPulsarFuera);
    window.addEventListener("keydown", alTeclear);
    return () => {
      window.removeEventListener("mousedown", alPulsarFuera);
      window.removeEventListener("keydown", alTeclear);
    };
  }, [menuAbierto]);

  const inicial = (sesion?.nombre || sesion?.email || "?").charAt(0).toUpperCase();
  // Solo las altas que esta persona puede hacer. Un menú de creación con
  // opciones que responden «no tienes permiso» es peor que no tenerlo.
  const altas = ALTAS.filter((a) => puede(sesion, a.permiso));

  useEffect(() => {
    if (!crearAbierto) return;
    function fuera(evento: MouseEvent) {
      if (crearRef.current && !crearRef.current.contains(evento.target as Node)) {
        setCrearAbierto(false);
      }
    }
    function tecla(evento: KeyboardEvent) {
      if (evento.key === "Escape") setCrearAbierto(false);
    }
    window.addEventListener("mousedown", fuera);
    window.addEventListener("keydown", tecla);
    return () => {
      window.removeEventListener("mousedown", fuera);
      window.removeEventListener("keydown", tecla);
    };
  }, [crearAbierto]);

  function cambiarTema() {
    const siguiente: Tema = tema === "oscuro" ? "claro" : "oscuro";
    aplicarTema(siguiente);
    setTema(siguiente);
  }

  return (
    <header className="sticky top-0 z-popover flex h-14 items-center gap-3 border-b border-ink-dim/60 bg-paper px-4">
      <button
        type="button"
        onClick={panel.alternar}
        className="btn-icon shrink-0 text-ink-muted hover:bg-paper-light hover:text-ink"
        aria-label={t("nav.alternarPanel")}
        aria-expanded={panel.abierto}
      >
        <Icono nombre="menu" />
      </button>

      <nav
        aria-label={t("nav.migas")}
        className="flex min-w-0 shrink items-center gap-2 text-sm"
      >
        {migas.map((miga, i) => (
          <span key={`${miga.rotulo}-${i}`} className="flex min-w-0 items-center gap-2">
            {i > 0 ? <Icono nombre="chevron_right" tamano="sm" className="text-ink-faint" /> : null}
            {miga.a && i < migas.length - 1 ? (
              <Link
                to={miga.a}
                title={miga.rotulo}
                className="truncate font-medium text-ink-muted transition-colors hover:text-ink"
              >
                {miga.rotulo}
              </Link>
            ) : (
              <span
                title={miga.rotulo}
                className={cn(
                  "truncate",
                  i === migas.length - 1 ? "font-semibold text-ink" : "font-medium text-ink-muted",
                )}
              >
                {miga.rotulo}
              </span>
            )}
          </span>
        ))}
      </nav>

      <button
        type="button"
        onClick={alAbrirPaleta}
        className="mx-auto hidden h-10 max-w-md flex-1 items-center gap-2 rounded-full bg-paper-light px-4 text-sm text-ink-faint transition-colors hover:bg-paper-lighter md:flex"
        aria-label={t("nav.abrirPaleta")}
      >
        <Icono nombre="search" tamano="sm" className="text-ink-muted" />
        <span className="flex-1 truncate text-left">{t("nav.buscarPlaceholder")}</span>
        <kbd className="shrink-0 rounded border border-ink-dim/60 bg-paper px-1.5 py-0.5 font-mono text-3xs text-ink-muted">
          {teclaAtajo()}
        </kbd>
      </button>

      {/* En móvil no cabe el buscador entero, pero sí su icono: quitarlo del
          todo dejaría la búsqueda accesible solo por un atajo de teclado que en
          un teléfono no existe. */}
      <button
        type="button"
        onClick={alAbrirPaleta}
        className="btn-icon ml-auto text-ink-muted hover:bg-paper-light hover:text-ink md:hidden"
        aria-label={t("nav.abrirPaleta")}
      >
        <Icono nombre="search" />
      </button>

      <div className="flex shrink-0 items-center gap-1">
        {/* Dar de alta, siempre a la vista. Sin esto, la única forma de crear
            algo es entrar en la pantalla correcta y localizar un botón dentro,
            y eso no lo adivina nadie: es lo primero que echa en falta quien
            abre el producto. Salesforce, HubSpot y Dynamics lo resuelven igual
            y por el mismo motivo. */}
        {altas.length > 0 ? (
          <div className="relative mr-1" ref={crearRef}>
            <button
              type="button"
              onClick={() => setCrearAbierto((v) => !v)}
              className="btn-primary inline-flex items-center gap-1.5"
              aria-haspopup="menu"
              aria-expanded={crearAbierto}
            >
              <Icono nombre="add" tamano="sm" />
              <span className="hidden sm:inline">{t("nav.crear")}</span>
            </button>
            {crearAbierto ? (
              <div
                role="menu"
                aria-label={t("nav.crearQue")}
                className="absolute right-0 z-popover mt-2 w-60 animate-fade-in rounded-xl border border-ink-dim/60 bg-paper p-1 shadow-elevation-3"
              >
                <p className="px-3 py-2 text-3xs uppercase tracking-wide text-ink-faint">
                  {t("nav.crearQue")}
                </p>
                {altas.map((alta) => (
                  <Link
                    key={alta.a}
                    role="menuitem"
                    to={alta.a}
                    onClick={() => setCrearAbierto(false)}
                    className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-ink hover:bg-paper-light"
                  >
                    <Icono nombre={alta.icono} tamano="sm" className="text-ink-muted" />
                    {t(alta.clave)}
                  </Link>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        <AvisoDeChat />

        <button
          type="button"
          onClick={cambiarTema}
          className="btn-icon text-ink-muted hover:bg-paper-light hover:text-ink"
          aria-label={t("app.tema")}
          title={t("app.tema")}
        >
          <Icono nombre={tema === "oscuro" ? "dark_mode" : "light_mode"} />
        </button>

        <div className="relative ml-1" ref={menuRef}>
          <button
            ref={avatarRef}
            type="button"
            onClick={() => setMenuAbierto((v) => !v)}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-sm font-bold text-paper shadow-elevation-1 transition-shadow hover:shadow-elevation-2"
            aria-haspopup="menu"
            aria-expanded={menuAbierto}
            aria-label={t("nav.menuUsuario")}
            title={sesion?.email || ""}
          >
            {inicial}
          </button>
          {menuAbierto ? (
            <div
              role="menu"
              aria-label={t("nav.menuUsuario")}
              className="absolute right-0 z-popover mt-2 w-64 animate-fade-in rounded-xl border border-ink-dim/60 bg-paper p-1 shadow-elevation-3"
            >
              {sesion ? (
                <div className="mb-1 border-b border-ink-dim/30 px-3 py-2">
                  <p className="text-2xs text-ink-muted">{t("nav.sesionDe")}</p>
                  <p className="truncate text-xs font-medium text-ink" title={sesion.email}>
                    {sesion.email}
                  </p>
                </div>
              ) : null}
              <Link
                role="menuitem"
                to="/puesto"
                onClick={() => setMenuAbierto(false)}
                className="inline-flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-ink hover:bg-paper-light"
              >
                <Icono nombre="person" tamano="sm" />
                {t("nav.puesto")}
              </Link>
              <button
                role="menuitem"
                type="button"
                onClick={() => {
                  setMenuAbierto(false);
                  alSalir();
                }}
                className="inline-flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-danger hover:bg-danger/10"
              >
                <Icono nombre="logout" tamano="sm" />
                {t("app.cerrarSesion")}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}

/**
 * De dónde sale la miga de pan: del camino, y para los módulos, del catálogo.
 *
 * Un módulo se pinta como `/m/cuentas`, y «cuentas» no es lo que se ve en el
 * menú. Traducirlo mirando la declaración de módulos evita la incoherencia de
 * que la miga diga una cosa y el menú otra para la misma pantalla.
 */
export function derivarMigas(camino: string, t: (clave: string) => string): Miga[] {
  const raiz: Miga = { rotulo: t("nav.inicio"), a: "/" };
  if (camino === "/") return [{ rotulo: t("nav.inicio") }];

  const partes = camino.split("/").filter(Boolean);
  if (partes[0] === "m" && partes[1]) {
    const modulo = MODULOS.find((m) => m.ruta === partes[1]);
    const rotulo = modulo?.titulo ?? partes[1];
    const migas: Miga[] = [raiz, { rotulo, a: `/m/${partes[1]}` }];
    // Ficha: `/m/:ruta/:tipo/:id`. Se enseña el tipo y no el identificador —un
    // UUID en la miga de pan no le dice nada a nadie— y escrito como se lee,
    // no en minúscula como viene en la ruta.
    if (partes[2]) migas.push({ rotulo: humanizar(partes[2]) });
    return migas;
  }

  const entrada = todasLasEntradas().find((e) => e.a === camino);
  // Sin entrada declarada se usa el último tramo del camino. No es bonito,
  // pero es honesto: una miga vacía diría que no estás en ningún sitio.
  const ultimo = partes[partes.length - 1] ?? camino;
  return [raiz, { rotulo: entrada ? t(entrada.clave) : ultimo }];
}
