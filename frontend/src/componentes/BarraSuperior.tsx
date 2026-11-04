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

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router-dom";

import { AvisoDeChat } from "@/componentes/AvisoDeChat";
import { Icono } from "@/componentes/Icono";
import { Notificaciones } from "@/componentes/Notificaciones";
import { llamar, mirarTenant, tenantMirado } from "@/lib/api";
import { ALTAS } from "@/lib/altas";
import { humanizar } from "@/lib/formato";
import { MODULOS, grupoDelModulo, porGrupoVisible } from "@/lib/modulos";
import {
  AYUDA,
  EN_LA_BARRA,
  ambitoDelCamino,
  entradaVisible,
  menuDe,
  todasLasEntradas,
} from "@/lib/navegacion";
import { useVisibilidad } from "@/lib/permisos";
import { usePanel } from "@/lib/panel";
import type { Sesion } from "@/lib/sesion";
import { puede } from "@/lib/sesion";
import { elegirDensidad, type Densidad } from "@/lib/densidad";
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
  conPanel = false,
}: {
  sesion: Sesion | null;
  alSalir: () => void;
  alAbrirPaleta: () => void;
  /**
   * Si hay un panel lateral que plegar.
   *
   * **Sólo lo hay en configuración.** El árbol vive ahí —es donde se recorre
   * una lista larga buscando un ajuste— y trabajando no se pinta: la
   * navegación son las pestañas de arriba. El botón de las tres rayas, en
   * cambio, se pintaba SIEMPRE, en la esquina de arriba a la izquierda, que es
   * el sitio donde se busca la navegación principal.
   *
   * Medido el 04-11-2026 pulsándolo: en una pantalla de trabajo, `aside` 0→0 y
   * el ancho del contenido 1440→1440 px. No hacía nada, y uno se queda
   * dudando si es él. En configuración sí: 1440→1218.
   */
  conPanel?: boolean;
}) {
  const { t } = useTranslation();
  const panel = usePanel();
  const ubicacion = useLocation();
  // **Sin miga de pan cuando la barra de aplicación ya dice dónde estás.**
  // Con el armazón nuevo, en un listado salía tres veces lo mismo en la misma
  // pantalla: la pestaña subrayada en la barra, la miga aquí arriba y el
  // título de la página. Tres rótulos iguales no orientan más que uno; ocupan
  // el sitio del buscador y hacen que la pantalla parezca improvisada.
  //
  // En configuración sí se queda: ahí no hay barra de aplicación, hay un árbol
  // a la izquierda, y la miga es lo único que dice en qué rama estás.
  const enConfiguracion =
    ambitoDelCamino(ubicacion.pathname, grupoDelModulo) === "administrar";
  const migas = enConfiguracion ? derivarMigas(ubicacion.pathname, t) : [];

  // A qué pantalla lleva el engranaje: la **primera que esta persona puede
  // ver** en configuración, no una fija. Un enlace fijo mandaría a quien no
  // tiene ese permiso a una pantalla vacía, que es la peor bienvenida posible.
  const visibilidad = useVisibilidad();
  const destinoDeConfiguracion = useMemo(() => {
    const areas = menuDe(
      porGrupoVisible(sesion, visibilidad),
      (e) => entradaVisible(sesion, e),
      "administrar",
    );
    return areas[0]?.entradas[0]?.a ?? null;
  }, [sesion, visibilidad]);

  const [tema, setTema] = useState<Tema>(() => temaActual());
  const [densidad, setDensidad] = useState<Densidad>(
    () => (document.documentElement.dataset.densidad as Densidad) || "compacta",
  );
  const [menuAbierto, setMenuAbierto] = useState(false);
  const [crearAbierto, setCrearAbierto] = useState(false);
  const [ayudaAbierta, setAyudaAbierta] = useState(false);
  const crearRef = useRef<HTMLDivElement>(null);
  const ayudaRef = useRef<HTMLDivElement>(null);
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

  const inicial = (sesion?.nombre || sesion?.email || "?")
    .charAt(0)
    .toUpperCase();
  // Solo las altas que esta persona puede hacer. Un menú de creación con
  // opciones que responden «no tienes permiso» es peor que no tenerlo.
  const altas = ALTAS.filter((a) => puede(sesion, a.permiso));

  useEffect(() => {
    if (!crearAbierto) return;
    function fuera(evento: MouseEvent) {
      if (
        crearRef.current &&
        !crearRef.current.contains(evento.target as Node)
      ) {
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

  // Lo mismo para la interrogación. Dos efectos y no uno compartido: el que
  // los juntara tendría que decidir cuál cerrar, y cerrar los dos al pulsar
  // dentro de uno es justo lo que no se quiere.
  useEffect(() => {
    if (!ayudaAbierta) return;
    function fuera(evento: MouseEvent) {
      if (ayudaRef.current && !ayudaRef.current.contains(evento.target as Node)) {
        setAyudaAbierta(false);
      }
    }
    function tecla(evento: KeyboardEvent) {
      if (evento.key === "Escape") setAyudaAbierta(false);
    }
    window.addEventListener("mousedown", fuera);
    window.addEventListener("keydown", tecla);
    return () => {
      window.removeEventListener("mousedown", fuera);
      window.removeEventListener("keydown", tecla);
    };
  }, [ayudaAbierta]);

  // La densidad se lee del documento y no de un estado propio: quien la fija al
  // arrancar es `App`, con lo que dice el perfil. Un `useState` con su propio
  // valor inicial pintaría el botón diciendo «compacta» mientras la página ya
  // está en cómoda, que es el desajuste clásico de tener la verdad en dos
  // sitios.
  function cambiarDensidad() {
    const siguiente: Densidad = densidad === "comoda" ? "compacta" : "comoda";
    setDensidad(siguiente);
    // Se pinta ya y se guarda después: esperar a la red para mover la interfaz
    // hace que el botón parezca roto en una conexión lenta. Si el guardado
    // falla, lo que se pierde es que no sobreviva a la recarga — no la sesión.
    void elegirDensidad(siguiente).catch(() => undefined);
  }

  function cambiarTema() {
    const siguiente: Tema = tema === "oscuro" ? "claro" : "oscuro";
    aplicarTema(siguiente);
    setTema(siguiente);
  }

  return (
    <header className="sticky top-0 z-popover flex h-[var(--barra-h)] items-center gap-3 border-b border-ink-dim/60 bg-paper pl-5 pr-6">
      {conPanel ? (
      <button
        type="button"
        onClick={panel.alternar}
        className="btn-icon shrink-0 text-ink-muted hover:bg-paper-light hover:text-ink"
        aria-label={t("nav.alternarPanel")}
        aria-expanded={panel.abierto}
      >
        <Icono nombre="menu" />
      </button>
      ) : null}

      {/* `flex-1` y no sólo `shrink`: la miga tiene que poder **crecer** hasta
          lo que haya libre. Con el buscador puesto a `mx-auto`, todo el hueco
          sobrante de la barra se convertía en margen suyo y la miga se quedaba
          con lo mínimo — medido a 1440×900 en la ficha de una cuenta,
          «In… > Cuentas y… > C…»: el nombre del registro, que es lo único que
          dice dónde estás, reducido a **una letra** con 200 px libres al lado.

          Con tope, porque la miga tampoco puede comerse el buscador: a partir
          de 32rem vuelve a recortarse, que es lo que tiene que pasar cuando de
          verdad no cabe. */}
      {/* Y si no hay migas, **no hay `<nav>`**. Fuera de Configuración la
          lista está vacía, así que quedaba un landmark de navegación sin nada
          dentro: un lector de pantalla anuncia una región de navegación y no
          hay dónde ir. Medido el 02-11-2026 — además tumbaba el barrido de
          pantallas, que esperaba a que el primer `nav` se viera y el primero
          era éste. */}
      {migas.length > 0 ? (
        <nav
          aria-label={t("nav.migas")}
          className="flex min-w-0 max-w-[32rem] shrink items-center gap-2 text-titulo"
        >
          {migas.map((miga, i) => (
            <span
              key={`${miga.rotulo}-${i}`}
              className="flex min-w-0 items-center gap-2"
            >
              {i > 0 ? (
                <Icono
                  nombre="chevron_right"
                  tamano="sm"
                  className="text-ink-faint"
                />
              ) : null}
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
                    i === migas.length - 1
                      ? "font-semibold text-ink"
                      : "font-medium text-ink-muted",
                  )}
                >
                  {miga.rotulo}
                </span>
              )}
            </span>
          ))}
        </nav>
      ) : null}

      <button
        type="button"
        onClick={alAbrirPaleta}
        className="ml-auto hidden h-10 min-w-0 max-w-md flex-1 basis-64 items-center gap-2 rounded-full bg-paper-light px-4 text-titulo text-ink-faint transition-colors hover:bg-paper-lighter md:flex"
        aria-label={t("nav.abrirPaleta")}
      >
        <Icono nombre="search" tamano="sm" className="text-ink-muted" />
        <span className="flex-1 truncate text-left">
          {t("nav.buscarPlaceholder")}
        </span>
        <kbd className="shrink-0 rounded border border-ink-dim/60 bg-paper px-1.5 py-0.5 font-mono text-rotulo text-ink-muted">
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

      {/* De quién son los datos que se están viendo. Sólo sale a quien opera
          la plataforma, que es el único que puede mirar otro cliente, y sale
          SIEMPRE que hay uno elegido: una consola que enseña datos de un
          cliente sin decir cuál es cómo se contesta un correo mirando la ficha
          de otro. */}
      {sesion?.es_admin_plataforma ? <QueCliente sesion={sesion} /> : null}

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
                <p className="px-3 py-2 text-rotulo uppercase tracking-wide text-ink-faint">
                  {t("nav.crearQue")}
                </p>
                {altas.map((alta) => (
                  <Link
                    key={alta.a}
                    role="menuitem"
                    to={alta.a}
                    onClick={() => setCrearAbierto(false)}
                    className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-titulo text-ink hover:bg-paper-light"
                  >
                    <Icono
                      nombre={alta.icono}
                      tamano="sm"
                      className="text-ink-muted"
                    />
                    {t(alta.clave)}
                  </Link>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {/* Nexus. Va de icono en la barra y no de entrada en el menú por lo
            mismo que el chat: no trata de un dominio —se le pregunta por
            cuentas, por casos o por facturación desde el mismo sitio— y se
            abre desde donde uno esté, sin volver a un menú. */}
        {puede(sesion, "ia:usar") ? (
          <Link
            to="/preguntar"
            className="btn-icon text-ink-muted hover:bg-paper-light hover:text-ink"
            aria-label={t("nav.nexus")}
            title={t("nav.nexus")}
          >
            <Icono nombre="smart_toy" />
          </Link>
        ) : null}

        <AvisoDeChat />

        {/* Las menciones y lo que se sigue. Son personales y no de un dominio
            —te mencionan en una cuenta, en una oportunidad y en un caso, y se
            sigue lo mismo—, así que viven aquí y no en el menú de un área.

            Se pintan de `EN_LA_BARRA` y no a mano: «/menciones» llevaba
            exenta del guardián de caminos con el motivo «tiene su icono fijo
            en la barra de arriba» y ese icono **no existía**. Estaba escrita,
            enrutada y sin un solo enlace en todo el front. */}
        {EN_LA_BARRA.map((entrada) => (
          <Link
            key={entrada.a}
            to={entrada.a}
            className="btn-icon text-ink-muted hover:bg-paper-light hover:text-ink"
            aria-label={t(entrada.clave)}
            title={t(entrada.clave)}
          >
            <Icono nombre={entrada.icono} />
          </Link>
        ))}

        {/* **La puerta de la configuración.** Antes vivía en la barra lateral,
            en el interruptor «Trabajar / Administrar». Al quitar la barra del
            trabajo diario, ese interruptor se fue con ella y la configuración
            se quedó **sin ninguna forma de llegar**: el rediseño la habría
            escondido entera, que es el fallo que más fácil se cuela al ordenar
            un menú.

            Es un engranaje y está donde lo pone Salesforce, por lo mismo que
            el resto: quien ya usa un CRM lo busca ahí.

            Sólo sale a quien tiene algo que configurar. Ofrecer una puerta que
            lleva a una pantalla vacía es peor que no ofrecerla. */}
        {destinoDeConfiguracion ? (
          <Link
            to={enConfiguracion ? "/" : destinoDeConfiguracion}
            className="btn-icon text-ink-muted hover:bg-paper-light hover:text-ink"
            aria-label={t(
              enConfiguracion
                ? "app.salirDeConfiguracion"
                : "app.irAConfiguracion",
            )}
            title={t(
              enConfiguracion
                ? "app.salirDeConfiguracion"
                : "app.irAConfiguracion",
            )}
            aria-current={enConfiguracion ? "page" : undefined}
          >
            <Icono nombre={enConfiguracion ? "work" : "settings"} />
          </Link>
        ) : null}

        {/* **La interrogación.** «Ayuda», «Recorrido guiado» y «Cobertura»
            estaban dentro de la configuración, en la misma rama que «Usuarios
            y permisos»: quien busca ayuda no entra a configurar para
            encontrarla, y quien configura se las topa en medio. Hablan del
            producto, no del cliente.

            Va donde la pone Salesforce —detrás del engranaje, en ese orden—
            y por lo mismo: quien ya usa un CRM la busca ahí. */}
        <div className="relative" ref={ayudaRef}>
          <button
            type="button"
            onClick={() => setAyudaAbierta((v) => !v)}
            className="btn-icon text-ink-muted hover:bg-paper-light hover:text-ink"
            aria-haspopup="menu"
            aria-expanded={ayudaAbierta}
            aria-label={t("nav.ayuda")}
            title={t("nav.ayuda")}
          >
            <Icono nombre="help" />
          </button>
          {ayudaAbierta ? (
            <div
              role="menu"
              aria-label={t("nav.ayuda")}
              className="absolute right-0 z-popover mt-2 w-60 animate-fade-in rounded-xl border border-ink-dim/60 bg-paper p-1 shadow-elevation-3"
            >
              {AYUDA.map((entrada) => (
                <Link
                  key={entrada.a}
                  role="menuitem"
                  to={entrada.a}
                  onClick={() => setAyudaAbierta(false)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-titulo text-ink hover:bg-paper-light"
                >
                  <Icono
                    nombre={entrada.icono}
                    tamano="sm"
                    className="text-ink-muted"
                  />
                  {t(entrada.clave)}
                </Link>
              ))}
            </div>
          ) : null}
        </div>

        {/* Densidad. Al lado del tema porque son la misma clase de cosa para
            quien mira —cómo se ve esto—, aunque por dentro una viva en el
            navegador y la otra en el perfil. Separarlas en dos sitios obligaría
            a explicar esa diferencia, que no le importa a nadie. */}
        <button
          type="button"
          onClick={cambiarDensidad}
          className="btn-icon text-ink-muted hover:bg-paper-light hover:text-ink"
          aria-label={t("app.densidad")}
          title={t(
            densidad === "comoda"
              ? "app.densidadCompacta"
              : "app.densidadComoda",
          )}
          aria-pressed={densidad === "compacta"}
        >
          <Icono
            nombre={densidad === "comoda" ? "density_large" : "density_small"}
          />
        </button>

        {/* Los avisos, antes del tema y la densidad: lo que se mira quince
            veces al día va donde se busca sin pensar, y el tema se toca una
            vez en la vida. */}
        <Notificaciones />

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
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-titulo font-bold text-paper shadow-elevation-1 transition-shadow hover:shadow-elevation-2"
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
                  <p className="text-dato text-ink-muted">
                    {t("nav.sesionDe")}
                  </p>
                  <p
                    className="truncate text-titulin font-medium text-ink"
                    title={sesion.email}
                  >
                    {sesion.email}
                  </p>
                  {/* Los roles viven aquí y no en la portada. Son identidad
                      —«qué puedo hacer»—, no trabajo del día, y en la portada
                      ocupaban el sitio de lo que sí vence hoy. Siguen estando
                      porque explican por qué alguien no ve una pantalla: sin
                      ellos, «no me aparece» no tiene respuesta. */}
                  {sesion.roles.length > 0 ? (
                    <p className="mt-1 flex flex-wrap gap-1">
                      {sesion.roles.map((rol) => (
                        <span key={rol} className="badge badge-muted">
                          {rol}
                        </span>
                      ))}
                    </p>
                  ) : (
                    <p className="mt-1 text-rotulo text-warning">
                      {t("inicio.sinRoles")}
                    </p>
                  )}
                </div>
              ) : null}
              <Link
                role="menuitem"
                to="/puesto"
                onClick={() => setMenuAbierto(false)}
                className="inline-flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-titulo text-ink hover:bg-paper-light"
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
                className="inline-flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-titulo text-danger hover:bg-danger/10"
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
export function derivarMigas(
  camino: string,
  t: (clave: string) => string,
): Miga[] {
  const raiz: Miga = { rotulo: t("nav.inicio"), a: "/" };
  if (camino === "/") return [{ rotulo: t("nav.inicio") }];

  const partes = camino.split("/").filter(Boolean);
  if (partes[0] === "m" && partes[1]) {
    const modulo = MODULOS.find((m) => m.ruta === partes[1]);
    const rotulo = modulo?.titulo ?? partes[1];
    // Ficha: `/m/:ruta/:tipo/:id`. Se enseña el tipo y no el identificador —un
    // UUID en la miga de pan no le dice nada a nadie— y escrito como se lee,
    // no en minúscula como viene en la ruta.
    if (!partes[2]) return [raiz, { rotulo, a: `/m/${partes[1]}` }];
    // **Sin «Inicio» en la ficha.** La barra está llena de verdad: medido a
    // 1440×900, los únicos 92 px «libres» son los huecos entre controles, así
    // que los tres tramos no caben y se recortaban los TRES —
    // «In… > Cuentas y… > C…»—, dejando el último, que es el que dice dónde
    // estás, en una letra. «Inicio» está en todas las migas, no distingue
    // ninguna pantalla de otra y al logo de la esquina se llega igual: es lo
    // primero que sobra cuando hay que elegir qué se recorta.
    return [{ rotulo, a: `/m/${partes[1]}` }, { rotulo: humanizar(partes[2]) }];
  }

  const entrada = todasLasEntradas().find((e) => e.a === camino);
  // Sin entrada declarada se usa el último tramo del camino. No es bonito,
  // pero es honesto: una miga vacía diría que no estás en ningún sitio.
  const ultimo = partes[partes.length - 1] ?? camino;
  return [raiz, { rotulo: entrada ? t(entrada.clave) : ultimo }];
}

/**
 * El selector de cliente, para quien opera la plataforma.
 *
 * Hasta el 27-10-2026 no hacía falta porque las pantallas de negocio enseñaban
 * **todos los clientes a la vez**, sin decirlo: 97 de cada 100 cuentas eran de
 * otro. Ahora se ve uno cada vez y se sabe cuál, que es lo que permite trabajar
 * sin contestarle a un cliente mirando la ficha de otro.
 *
 * Cuando se está mirando a otro, el selector va **en color de aviso**: es un
 * estado del que hay que acordarse de salir, y un desplegable gris más en una
 * barra llena no se recuerda.
 */
function QueCliente({ sesion }: { sesion: Sesion }) {
  const { t } = useTranslation();
  const [tenants, setTenants] = useState<
    { id: string; nombre: string }[] | null
  >(null);
  const [elegido, setElegido] = useState(() => tenantMirado());

  useEffect(() => {
    const control = new AbortController();
    // La lista de clientes es de plataforma, así que se pide con lo que ya
    // concede el propio permiso. Si no se puede, el selector no sale: ofrecer
    // un desplegable vacío es ofrecer algo que no hace nada.
    void llamar<{ items: { id: string; nombre: string; slug?: string }[] }>(
      "/api/v1/tenants?limite=200",
      { signal: control.signal },
    )
      .then((r) =>
        setTenants(
          (r.datos.items ?? []).map((x) => ({ id: x.id, nombre: x.nombre })),
        ),
      )
      .catch(() => setTenants([]));
    return () => control.abort();
  }, []);

  if (!tenants?.length) return null;

  function cambiar(id: string) {
    mirarTenant(id);
    setElegido(id);
    // Se recarga a propósito: media pantalla con los datos de un cliente y la
    // otra media con los del anterior es peor que esperar un segundo.
    window.location.reload();
  }

  const mirandoAOtro = Boolean(elegido) && elegido !== sesion.tenant_id;

  return (
    <label
      className={`ml-auto hidden shrink-0 items-center gap-2 rounded-full px-3 py-1 text-dato md:flex ${
        mirandoAOtro ? "bg-warning/15 text-warning" : "text-ink-muted"
      }`}
    >
      <span className="sr-only">{t("nav.queCliente")}</span>
      <Icono nombre={mirandoAOtro ? "visibility" : "domain"} tamano="sm" />
      <select
        value={elegido || sesion.tenant_id || ""}
        onChange={(e) => cambiar(e.target.value)}
        className="bg-transparent text-dato outline-none"
        aria-label={t("nav.queCliente")}
      >
        {tenants.map((x) => (
          <option key={x.id} value={x.id}>
            {x.nombre}
          </option>
        ))}
      </select>
    </label>
  );
}
