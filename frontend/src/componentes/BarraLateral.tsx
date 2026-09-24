/**
 * El panel de navegación (CRM-07.04.01.03).
 *
 * Mismo armazón que contecmind: marca arriba, pastillas de acceso rápido,
 * secciones plegables y pie con quién eres y por dónde salir.
 *
 * **Por qué a la izquierda y no arriba.** Antes esto era una barra horizontal
 * con veintidós enlaces que envolvían en tres líneas. Una lista horizontal deja
 * de funcionar pasados unos pocos elementos: no se puede agrupar, no se puede
 * plegar, no admite iconos sin duplicar la altura, y en cuanto envuelve, el
 * orden visual deja de significar nada. A la izquierda cabe la jerarquía real
 * del producto —módulos del catálogo, análisis, plataforma— y el contenido
 * recupera el ancho de la pantalla.
 *
 * **Los módulos salen del catálogo**, no de una lista escrita aquí. Dos listas
 * que tienen que coincidir acaban no coincidiendo, y la que se queda corta es
 * siempre el menú.
 */

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { config } from "@/lib/config";
import { porGrupoVisible } from "@/lib/modulos";
import {
  ACCESOS,
  AREAS,
  entradaVisible,
  menuDe,
  type AreaPintada,
  type Entrada,
} from "@/lib/navegacion";
import { usePanel } from "@/lib/panel";
import { usePermitidas } from "@/lib/permisos";
import type { Sesion } from "@/lib/sesion";
import { cn } from "@/lib/utiles";

const CLAVE_PLEGADAS = "contecrm.panel_plegadas";

/**
 * Por debajo de este ancho el panel se queda en raíl de iconos.
 *
 * Es el umbral de contecflow (1280px) y no un número redondo: un panel de 222px
 * en una pantalla de 1280 se lleva el 17 %, y en cuanto la tabla de la derecha
 * tiene ocho columnas aparece scroll horizontal. Plegado son 46px, el 3,6 %.
 *
 * El valor vive en `index.css` como `--panel-plegar` para que la medida y la
 * media query no puedan separarse; aquí se lee de ahí.
 */
function anchoDePliegue(): number {
  if (typeof window === "undefined") return 1280;
  const leido = getComputedStyle(document.documentElement).getPropertyValue("--panel-plegar");
  return Number.parseInt(leido, 10) || 1280;
}

/**
 * Plegado sí o no, siguiendo el ancho de la ventana.
 *
 * Al redimensionar manda la ventana, como en contecflow: quien estrecha la
 * ventana quiere sitio, y dejarle un panel de 222px porque lo desplegó hace una
 * hora es discutir con él. El botón sirve para la decisión puntual —ver los
 * rótulos un momento— y el siguiente cambio de tamaño la revoca.
 */
function usePlegado(): [boolean, () => void] {
  const [plegado, setPlegado] = useState(
    () => typeof window !== "undefined" && window.innerWidth < anchoDePliegue(),
  );
  useEffect(() => {
    function alRedimensionar() {
      setPlegado(window.innerWidth < anchoDePliegue());
    }
    window.addEventListener("resize", alRedimensionar);
    return () => window.removeEventListener("resize", alRedimensionar);
  }, []);
  return [plegado, useCallback(() => setPlegado((p) => !p), [])];
}

export function BarraLateral({ sesion, alSalir }: { sesion: Sesion | null; alSalir: () => void }) {
  const { t } = useTranslation();
  const { abierto, fijar } = usePanel();
  const permitidas = usePermitidas();
  const cerrarRef = useRef<HTMLButtonElement | null>(null);
  const [plegado, alternarPlegado] = usePlegado();

  // Qué secciones están plegadas. Se recuerda porque plegar es una decisión: a
  // quien no usa los módulos del catálogo no hay que devolvérselos desplegados
  // en cada recarga.
  const [plegadas, setPlegadas] = useState<Record<string, boolean>>(() => {
    try {
      const guardado = localStorage.getItem(CLAVE_PLEGADAS);
      return guardado ? (JSON.parse(guardado) as Record<string, boolean>) : {};
    } catch {
      return {};
    }
  });

  /**
   * Abre un área y **cierra las demás**.
   *
   * En acordeón y no libre: con siete áreas y todas desplegadas el panel es
   * una lista de cuarenta enlaces en la que hay que buscar, que es justo lo que
   * las áreas venían a evitar. Abriendo una se cierra lo anterior, así que lo
   * que se ve es siempre el sitio donde se está trabajando.
   *
   * Cerrar la que está abierta las deja todas cerradas, que es una vista
   * legítima: el panel se queda en siete rótulos y la pantalla entera para el
   * trabajo.
   */
  const alternar = useCallback((id: string) => {
    setPlegadas((previo) => {
      const abriendo = Boolean(previo[id]);
      const siguiente: Record<string, boolean> = {};
      for (const area of AREAS) siguiente[area.id] = true;
      if (abriendo) siguiente[id] = false;
      try {
        localStorage.setItem(CLAVE_PLEGADAS, JSON.stringify(siguiente));
      } catch {
        /* sin almacenamiento: no se recuerda, pero se pliega igual */
      }
      return siguiente;
    });
  }, []);

  // En móvil el panel tapa la pantalla, así que Escape tiene que cerrarlo y el
  // foco tiene que entrar dentro. En escritorio es una columna del diseño, no
  // una capa encima: ahí Escape no lo toca, o se cerraría solo al pulsarlo por
  // cualquier otro motivo.
  useEffect(() => {
    if (!abierto) return;
    const movil =
      typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches;
    if (!movil) return;
    cerrarRef.current?.focus();
    function alPulsar(evento: KeyboardEvent) {
      if (evento.key === "Escape") fijar(false);
    }
    window.addEventListener("keydown", alPulsar);
    return () => window.removeEventListener("keydown", alPulsar);
  }, [abierto, fijar]);

  // El menú enseña **solo lo que esta persona puede abrir**. Ofrecer lo que no
  // se puede hacer obliga a probarlo para descubrirlo, y lo que se descubre es
  // un error: el usuario acaba creyendo que el sistema está roto. Es lo que
  // hacen las herramientas del mercado —una pestaña sin acceso no se enseña— y
  // es lo que aquí no se hacía.
  // Una sola lista: los módulos del catálogo y las pantallas transversales
  // repartidos por dominio de negocio. Antes eran dos taxonomías en paralelo y
  // seis pantallas aparecían dos veces con el mismo nombre.
  const areas = useMemo(
    () => menuDe(porGrupoVisible(sesion, permitidas), (e) => entradaVisible(sesion, e)),
    [sesion, permitidas],
  );
  const accesos = useMemo(
    () => ACCESOS.filter((e) => entradaVisible(sesion, e)),
    [sesion],
  );

  return (
    <>
      {/* El fondo oscuro de móvil es un botón y no un `div`: así se cierra
          también con teclado y el lector lo anuncia como lo que es. */}
      {abierto ? (
        <button
          type="button"
          onClick={() => fijar(false)}
          aria-label={t("nav.cerrarPanel")}
          className="fixed inset-0 z-modal-bg cursor-default bg-ink/50 md:hidden"
        />
      ) : null}

      {/* 222px desplegado y 46px plegado, las medidas de contecflow. Antes eran
          288px fijos: un 30 % más de panel que la otra solución de la casa, y
          sin forma de recuperarlo en una pantalla estrecha.

          En móvil el panel es una capa encima y nunca se pliega: un raíl de
          iconos que tapa media pantalla no es un atajo, es un estorbo. */}
      <aside
        className={cn(
          "flex h-screen flex-col overflow-x-hidden border-r border-ink-dim/60 bg-paper-dark",
          "fixed inset-y-0 left-0 z-modal transition-[width,transform] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] md:relative md:z-auto",
          abierto ? "translate-x-0" : "hidden -translate-x-full",
          plegado ? "w-[var(--panel-w)] md:w-[var(--panel-w-plegado)]" : "w-[var(--panel-w)]",
        )}
      >
        {/* ── Marca ────────────────────────────────────────────────────── */}
        {/* Los mismos 48px de alto que la barra superior y la misma línea
            debajo: así las dos cabeceras casan y el ojo lee una sola banda
            horizontal en vez de dos escalones. Es la medida de contecflow. */}
        <div
          className={cn(
            "flex min-h-[var(--barra-h)] shrink-0 items-center justify-between gap-2 border-b border-ink-dim/60",
            plegado ? "px-2 md:justify-center" : "px-3",
          )}
        >
          {config().logotipo ? (
            <img
              src={config().logotipo}
              alt={config().nombre}
              className={cn("h-6", plegado && "md:h-7 md:w-7 md:object-contain")}
            />
          ) : (
            <span
              className={cn(
                "truncate font-semibold text-ink",
                plegado ? "text-sm md:hidden" : "text-sm",
              )}
            >
              {config().nombre}
            </span>
          )}
          {/* Plegado hace falta ALGO que ocupe el sitio de la marca, o la fila
              se queda vacía y el panel parece cortado. La inicial en un cuadro
              del acento es lo que hace contecflow. */}
          {plegado ? (
            <span
              aria-hidden
              className="hidden h-7 w-7 items-center justify-center rounded-md bg-accent text-3xs font-bold text-white md:flex"
            >
              {config().nombre.slice(0, 1).toUpperCase()}
            </span>
          ) : null}
          <button
            type="button"
            onClick={alternarPlegado}
            className="btn-icon hidden text-ink-faint hover:bg-paper-light hover:text-ink md:inline-flex"
            aria-label={t(plegado ? "nav.desplegarPanel" : "nav.plegarPanel")}
          >
            <Icono nombre={plegado ? "chevron_right" : "chevron_left"} tamano="sm" />
          </button>
          <button
            ref={cerrarRef}
            type="button"
            onClick={() => fijar(false)}
            className="btn-icon text-ink-muted hover:bg-paper-light hover:text-ink md:hidden"
            aria-label={t("nav.cerrarPanel")}
          >
            <Icono nombre="close" tamano="sm" />
          </button>
        </div>

        {/* ── Accesos rápidos ──────────────────────────────────────────── */}
        {/* Plegado pierden el rótulo pero no el sitio: son las cuatro pantallas
            a las que se vuelve todo el rato y tienen icono propio, así que en
            raíl siguen sirviendo. El rótulo lo da el `title`. */}
        <div className={cn("shrink-0", plegado ? "px-2 py-2 md:px-1.5" : "px-3 py-3")}>
          {plegado ? null : <p className="section-label mb-2">{t("nav.accesos")}</p>}
          <nav
            aria-label={t("nav.accesos")}
            className={cn("flex gap-1.5", plegado ? "flex-wrap md:flex-col md:items-center" : "flex-wrap")}
          >
            {accesos.map((entrada) => (
              <Pastilla key={entrada.a} entrada={entrada} plegado={plegado} />
            ))}
          </nav>
        </div>

        {/* ── Áreas ─────────────────────────────────────────────────────── */}
        <div className={cn("min-h-0 flex-1 overflow-y-auto pb-2", plegado && "md:overflow-visible")}>
          {areas.map((area) => (
            <Fragment key={area.id}>
              {/* Plegado, el raíl enseña el icono del ÁREA y no el de cada
                  pantalla, que es donde esto se aparta de contecflow. Allí cada
                  entrada tiene icono; aquí los veinticinco módulos del catálogo
                  no lo tienen, y ponerles uno sería inventarse veinticinco
                  símbolos que nadie ha elegido por lo que la pantalla hace.
                  Siete iconos de área que sí están escogidos orientan más que
                  veinticinco al azar, y el rótulo llega al pasar por encima. */}
              <AreaPlegada
                area={area}
                rotuloDe={(entrada) => (entrada.clave.includes(".") ? t(entrada.clave) : entrada.clave)}
                className={cn(plegado ? "hidden md:block" : "hidden")}
              />
              <div className={cn(plegado && "md:hidden")}>
                <Seccion
                  id={area.id}
                  icono={area.icono}
                  rotulo={t(area.clave)}
                  plegada={Boolean(plegadas[area.id])}
                  alAlternar={() => alternar(area.id)}
                >
                  {area.entradas.map((entrada) => (
                    <Enlace
                      key={entrada.a}
                      a={entrada.a}
                      // Los módulos traen su título ya escrito; las
                      // transversales, una clave de traducción. Se distingue
                      // por el punto.
                      rotulo={entrada.clave.includes(".") ? t(entrada.clave) : entrada.clave}
                    />
                  ))}
                </Seccion>
              </div>
            </Fragment>
          ))}
        </div>

        {/* ── Pie: quién eres y por dónde se sale ──────────────────────── */}
        {/* Plegado solo queda la puerta. El nombre y los roles son contexto, y
            un contexto que no se lee no es contexto: en 46px cabría recortado a
            cuatro letras, que es peor que no ponerlo. */}
        <div
          className={cn(
            "shrink-0 border-t border-ink-dim/60 py-3",
            plegado ? "px-4 md:flex md:justify-center md:px-1" : "px-3",
          )}
        >
          {plegado ? (
            <button
              type="button"
              onClick={alSalir}
              title={t("app.cerrarSesion")}
              className="btn-icon hidden text-ink-faint hover:bg-paper-light hover:text-ink md:inline-flex"
              aria-label={t("app.cerrarSesion")}
            >
              <Icono nombre="logout" tamano="sm" />
            </button>
          ) : null}
          <div className={cn(plegado && "md:hidden")}>
          {sesion ? (
            <p className="truncate text-2xs text-ink-muted" title={sesion.email}>
              {sesion.nombre || sesion.email}
            </p>
          ) : null}
          {sesion && sesion.roles.length > 0 ? (
            <p className="mt-0.5 truncate text-3xs text-ink-faint">{sesion.roles.join(", ")}</p>
          ) : null}
          <button
            type="button"
            onClick={alSalir}
            className="btn-link mt-2 inline-flex items-center gap-1.5 text-2xs"
          >
            <Icono nombre="logout" tamano="sm" />
            {t("app.cerrarSesion")}
          </button>
          </div>
        </div>
      </aside>
    </>
  );
}

function Seccion({
  id,
  rotulo,
  icono,
  plegada,
  alAlternar,
  children,
}: {
  id: string;
  rotulo: string;
  icono?: string;
  plegada: boolean;
  alAlternar: () => void;
  children: React.ReactNode;
}) {
  const idContenido = `seccion-${id}`;
  return (
    // Sin línea entre áreas: con siete, el menú era una rejilla de rayas y cada
    // área parecía una tabla. La separación la da el espacio, que basta.
    <section className="pt-1">
      <div className="flex items-center justify-between gap-2 px-1.5 pb-0.5 pt-2">
        <button
          type="button"
          onClick={alAlternar}
          aria-expanded={!plegada}
          aria-controls={idContenido}
          className="section-label flex min-w-0 flex-1 items-center gap-1.5 rounded-[5px] px-2 py-1.5 text-left transition-colors hover:text-ink-muted"
        >
          <Icono
            nombre="keyboard_arrow_down"
            tamano="sm"
            className={cn("transition-transform", plegada && "-rotate-90")}
          />
          {icono ? <Icono nombre={icono} tamano="sm" /> : null}
          <span className="truncate">{rotulo}</span>
        </button>
      </div>
      {/* Se desmonta al plegar en vez de esconderse con CSS: escondido con CSS
          sigue estando en el orden de tabulación, y quien navega con teclado
          recorre a ciegas una sección que no ve. */}
      {plegada ? null : (
        <nav id={idContenido} aria-label={rotulo} className="flex flex-col gap-px px-1 pb-1.5">
          {children}
        </nav>
      )}
    </section>
  );
}

function Pastilla({ entrada, plegado }: { entrada: Entrada; plegado: boolean }) {
  const { t } = useTranslation();
  const rotulo = t(entrada.clave);
  return (
    <NavLink
      to={entrada.a}
      end={entrada.a === "/"}
      title={plegado ? rotulo : undefined}
      // El `aria-label` NO es condicional: plegado el rótulo desaparece del
      // documento y el enlace se quedaría anunciado solo por su icono, que para
      // un lector de pantalla es nada.
      aria-label={rotulo}
      className={({ isActive }) =>
        cn(
          "pill inline-flex items-center gap-1.5",
          plegado && "md:h-8 md:w-8 md:justify-center md:gap-0 md:rounded-md md:px-0",
          isActive && "pill-active",
        )
      }
      aria-current={undefined}
    >
      <Icono nombre={entrada.icono} tamano="sm" />
      <span className={cn(plegado && "md:hidden")}>{rotulo}</span>
    </NavLink>
  );
}

/**
 * Un área en el raíl plegado: su icono, y al pasar por encima sus pantallas.
 *
 * Es el `nav-hover-preview` de contecflow. La alternativa —un `title` con los
 * nombres dentro— no se puede pulsar, así que plegado el panel dejaría de
 * navegar y solo serviría para saber qué hay; entonces no es un menú.
 *
 * El retardo de 150 ms al salir es suyo también, y no es un adorno: sin él, el
 * hueco de 6px entre el icono y el panel cierra la lista al cruzarlo con el
 * ratón, y nunca se llega al enlace.
 */
function AreaPlegada({
  area,
  rotuloDe,
  className,
}: {
  area: AreaPintada;
  rotuloDe: (entrada: Entrada) => string;
  className?: string;
}) {
  const { t } = useTranslation();
  const [abierta, setAbierta] = useState(false);
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rotulo = t(area.clave);

  const entrar = useCallback(() => {
    if (temporizador.current) clearTimeout(temporizador.current);
    setAbierta(true);
  }, []);
  const salir = useCallback(() => {
    temporizador.current = setTimeout(() => setAbierta(false), 150);
  }, []);
  useEffect(() => () => {
    if (temporizador.current) clearTimeout(temporizador.current);
  }, []);

  return (
    <div
      className={cn("relative px-1.5 py-0.5", className)}
      onPointerEnter={entrar}
      onPointerLeave={salir}
      onFocus={entrar}
      onBlur={salir}
    >
      <button
        type="button"
        title={rotulo}
        aria-label={rotulo}
        aria-expanded={abierta}
        onClick={() => setAbierta((a) => !a)}
        className={cn(
          "flex h-8 w-full items-center justify-center rounded-md text-ink-muted transition-colors",
          "hover:bg-paper-light hover:text-ink",
          abierta && "bg-paper-light text-ink",
        )}
      >
        <Icono nombre={area.icono} tamano="sm" />
      </button>
      {abierta ? (
        // 52px a la derecha: los 46 del raíl más 6 de aire, la medida de
        // contecflow.
        <div className="absolute left-[52px] top-0 z-popover min-w-[180px] rounded-md border border-ink-dim/60 bg-paper-light p-1.5 shadow-elevation-3">
          <p className="section-label px-2 pb-1 pt-0.5">{rotulo}</p>
          {area.entradas.map((entrada) => (
            <Enlace key={entrada.a} a={entrada.a} rotulo={rotuloDe(entrada)} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Enlace({ a, rotulo, icono }: { a: string; rotulo: string; icono?: string }) {
  return (
    <NavLink
      to={a}
      end={a === "/"}
      // Las medidas de contecflow, una a una: 28px de alto mínimo, 14px de
      // sangría a la izquierda —que es lo que alinea el rótulo con el del área,
      // no un número suelto—, radio 6 y peso 500. Y BORDE de 1px siempre, del
      // color del acento si está activo y transparente si no: sin el borde
      // transparente, el enlace activo mide 2px más que los demás y la lista
      // entera da un salto al moverse por ella.
      className={({ isActive }) =>
        cn(
          "flex min-h-[28px] items-center gap-2 rounded-sm border py-[5px] pl-[14px] pr-2",
          "text-sm-h font-medium transition-colors",
          isActive
            ? "border-accent/25 bg-accent/10 text-accent"
            : "border-transparent text-ink-muted hover:bg-paper-light hover:text-ink",
        )
      }
    >
      {({ isActive }) => (
        <>
          {icono ? <Icono nombre={icono} tamano="sm" relleno={isActive} /> : null}
          <span className="truncate">{rotulo}</span>
        </>
      )}
    </NavLink>
  );
}
