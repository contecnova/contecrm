/**
 * La portada: **mi día**, no un menú.
 *
 * Enseña CRM-01.02.01.02 (el seguimiento de lo vencido, incluido lo delegado)
 * y CRM-03.02.02.07 (la cobertura del pipeline contra lo que toca cerrar).
 *
 * Antes esto listaba enlaces a pantallas y los contaba. Quien abre un CRM a
 * primera hora no viene a elegir pantalla: viene a saber qué tiene que hacer
 * hoy y qué se le está pasando. Una portada que es un índice obliga a
 * reconstruir esa respuesta a mano, abriendo tres pantallas y cruzándolas de
 * cabeza, todos los días.
 *
 * Tres bloques y en este orden, que es el de la urgencia:
 *
 *   1. **Lo que ya se pasó.** Va primero y en rojo porque es lo único que no
 *      admite espera. Incluye lo delegado: quien delega sigue siendo
 *      responsable, y sin eso la tarea desaparece de su vista en cuanto la
 *      pasa.
 *   2. **Lo de hoy.** Lo que vence antes de medianoche.
 *   3. **Mi embudo**, con lo que cierra esta semana al lado. Es la pregunta
 *      que se hace un comercial cada lunes.
 *
 * **Lo que no hay, a propósito:** ningún número sin su lista detrás. Una
 * portada de contadores obliga a buscar a qué se refieren, y entonces vuelve a
 * ser un índice con otra forma. Cada bloque enseña las primeras filas y lleva
 * a la pantalla donde está el resto.
 *
 * Y cuando no hay nada que hacer, lo dice. Un hueco en blanco se lee como «no
 * ha cargado».
 */

import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { AvisoDeRecorte, Error as Fallo } from "@/componentes/Estados";
import { filas, llamar, salvoCancelacion } from "@/lib/api";
import { listar, listarPagina, MAXIMO_POR_PAGINA } from "@/lib/listados";
import { ALTAS } from "@/lib/altas";
import { puede, type Sesion } from "@/lib/sesion";
import { localizacion } from "@/lib/formato";

interface Actividad {
  id: string;
  asunto: string;
  tipo?: string | null;
  vence_at?: string | null;
  cuenta_id?: string | null;
}

interface Oportunidad {
  id: string;
  nombre: string;
  importe?: number | string | null;
  fecha_cierre?: string | null;
  etapa_id?: string | null;
}

interface Etapa {
  id: string;
  nombre: string;
  orden?: number | null;
}

/** Una fila de `GET /aprobaciones/bandeja`: lo que me toca decidir a mí. */
interface PorDecidir {
  solicitud_id: string;
  titulo: string;
  etapa?: string | null;
  vence_at?: string | null;
  va_tarde?: boolean;
}

/**
 * La gráfica se carga aparte.
 *
 * El gate del tamaño del paquete lo pidió —130 kB contra un tope de 128— y
 * tiene razón: la portada es la primera pantalla, así que todo lo que importe
 * se descarga antes de ver nada. El embudo no hace falta para pintarla: los
 * datos con los que se dibuja llegan después de la primera petición, así que
 * diferirlo no retrasa nada que se vea.
 */
const Grafica = lazy(() =>
  import("@/componentes/graficas/Grafica").then((m) => ({
    default: m.Grafica,
  })),
);

/** El final del día de hoy, en ISO, para pedir «lo que vence antes de medianoche». */
function finDeHoy(): string {
  const d = new Date();
  d.setHours(23, 59, 59, 999);
  return d.toISOString();
}

/** El domingo de esta semana. La pregunta del lunes es «qué cierra esta semana». */
function finDeSemana(): string {
  const d = new Date();
  // 0 = domingo en JavaScript; se lleva al domingo siguiente sin pasarse.
  d.setDate(d.getDate() + ((7 - d.getDay()) % 7));
  return d.toISOString().slice(0, 10);
}

export function Inicio({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  const [vencidas, setVencidas] = useState<Actividad[] | null>(null);
  const [hoy, setHoy] = useState<Actividad[] | null>(null);
  const [cierran, setCierran] = useState<Oportunidad[] | null>(null);
  const [etapas, setEtapas] = useState<Etapa[]>([]);
  const [embudo, setEmbudo] = useState<Oportunidad[] | null>(null);
  // Si el servidor dijo que había más oportunidades que las de la página: el
  // embudo se dibuja sumando las que llegan, y sin decirlo se leía como el
  // importe total de quien tenga más de las que caben.
  const [embudoRecortado, setEmbudoRecortado] = useState(false);

  const [porDecidir, setPorDecidir] = useState<PorDecidir[] | null>(null);
  const [decidiendo, setDecidiendo] = useState("");
  const [falloDecision, setFalloDecision] = useState<unknown>(null);
  const veAprobaciones = puede(sesion, "aprobacion:read");
  const veActividades = puede(sesion, "activity:read");
  const veOportunidades = puede(sesion, "opportunity:read");

  useEffect(() => {
    if (!veActividades) {
      setVencidas([]);
      setHoy([]);
      return;
    }
    const control = new AbortController();
    const { signal } = control;
    // Las dos listas se piden por separado y no una filtrada en el navegador:
    // traerse todo para enseñar diez es traerse datos que no se van a enseñar,
    // y en una cuenta con mil actividades eso se nota en el primer pintado.
    llamar<Actividad[]>("/api/v1/activities/vencidas", { signal })
      .then((r) => setVencidas((r.datos || []).slice(0, 6)))
      .catch(salvoCancelacion(() => setVencidas([])));
    listar<Actividad>(
      `/api/v1/activities?mias=true&estado__en=pendiente,en_curso&vence_at__hasta=${encodeURIComponent(finDeHoy())}&limite=6`,
      { signal },
    )
      .then(setHoy)
      .catch(salvoCancelacion(() => setHoy([])));
    return () => control.abort();
  }, [veActividades]);

  useEffect(() => {
    if (!veOportunidades) {
      setCierran([]);
      setEmbudo([]);
      return;
    }
    const control = new AbortController();
    const { signal } = control;
    listar<Oportunidad>(
      `/api/v1/opportunities?mias=true&estado=abierta&fecha_cierre__hasta=${finDeSemana()}&limite=6`,
      { signal },
    )
      .then(setCierran)
      .catch(salvoCancelacion(() => setCierran([])));
    listarPagina<Oportunidad>(
      `/api/v1/opportunities?mias=true&estado=abierta&limite=${MAXIMO_POR_PAGINA}`,
      { signal },
    )
      .then((pagina) => {
        setEmbudo(pagina.filas);
        setEmbudoRecortado(pagina.siguiente !== "");
      })
      .catch(salvoCancelacion(() => setEmbudo([])));
    listar<{ etapas?: Etapa[] }>("/api/v1/pipelines", { signal })
      .then((lista) => {
        setEtapas(lista[0]?.etapas || []);
      })
      .catch(salvoCancelacion(() => setEtapas([])));
    return () => control.abort();
  }, [veOportunidades]);

  /**
   * Lo que espera MI decisión, en la portada y con los botones al lado.
   *
   * La bandeja existía, pero en Administrar › Procesos › «Me toca decidir», y
   * al abrir una aprobación el título era «Aprobaciones» y decidir estaba en
   * «Más». Medido el 10-11-2026 (tarea T12): diez clics y cuatro pantallas
   * para aprobar un descuento, desde un sitio al que un responsable no entra.
   * En Salesforce, «Elementos para aprobar» es un componente de la portada.
   */
  const cargarPorDecidir = useMemo(
    () => (signal?: AbortSignal) => {
      if (!veAprobaciones) {
        setPorDecidir([]);
        return;
      }
      llamar<PorDecidir[]>("/api/v1/aprobaciones/bandeja?limite=6", { signal })
        // `filas` y no `r.datos` a pelo: una respuesta con otra forma no puede
        // tumbar la portada entera, que es lo primero que se ve.
        .then((r) => setPorDecidir(filas<PorDecidir>(r.datos)))
        .catch(salvoCancelacion(() => setPorDecidir([])));
    },
    [veAprobaciones],
  );
  useEffect(() => {
    const control = new AbortController();
    cargarPorDecidir(control.signal);
    return () => control.abort();
  }, [cargarPorDecidir]);

  async function decidir(
    solicitudId: string,
    decision: "aprobar" | "rechazar",
  ) {
    setDecidiendo(solicitudId);
    setFalloDecision(null);
    try {
      await llamar(`/api/v1/aprobaciones/${solicitudId}/decidir`, {
        metodo: "POST",
        cuerpo: { decision },
      });
      cargarPorDecidir();
    } catch (error) {
      setFalloDecision(error);
    } finally {
      setDecidiendo("");
    }
  }

  // El embudo: importe por etapa, en el orden del pipeline y **no por importe**.
  // Ordenar por importe convierte un embudo en un ranking y se pierde lo único
  // que un embudo dice, que es dónde se atasca.
  const porEtapa = useMemo(() => {
    if (!embudo || etapas.length === 0) return [];
    const suma = new Map<string, number>();
    for (const o of embudo) {
      const clave = String(o.etapa_id || "");
      suma.set(clave, (suma.get(clave) || 0) + Number(o.importe || 0));
    }
    return etapas
      .slice()
      .sort((a, b) => (a.orden ?? 0) - (b.orden ?? 0))
      .map((e) => ({ etapa: e.nombre, importe: suma.get(e.id) || 0 }));
  }, [embudo, etapas]);

  const altas = ALTAS.filter((a) => puede(sesion, a.permiso));
  const cargando = vencidas === null || hoy === null;
  // Nada mío en NINGUNA de las cuatro: es lo que distingue «no tengo nada
  // asignado» de «hoy no me toca nada», que son dos respuestas distintas y
  // sólo una de ellas necesita explicación.
  const sinNadaMio =
    (vencidas?.length ?? 0) === 0 &&
    (hoy?.length ?? 0) === 0 &&
    (cierran?.length ?? 0) === 0 &&
    (embudo?.length ?? 0) === 0;

  return (
    <>
      {/* **Sin saludo.** Había un «Hola, {nombre}» con icono grande y un
          «Esto es lo que tienes hoy» debajo, y se comía la primera banda de la
          primera pantalla del producto para no decir nada que el usuario no
          supiera. Salesforce no saluda en su portada: va directo al contenido,
          y por eso su Inicio se lee como una herramienta y no como una
          bienvenida.

          El encabezado de primer nivel se queda —hace falta para navegar por
          encabezados— en el tamaño que le corresponde a una etiqueta de
          pantalla, no de titular. */}
      <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-rotulo font-semibold uppercase tracking-[0.055em] text-ink-faint">
          {t("nav.inicio")}
        </h1>
        {altas.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {altas.slice(0, 3).map((alta) => (
              <Link key={alta.a} to={alta.a} className="btn-secondary gap-1.5">
                <Icono nombre={alta.icono} tamano="sm" />
                <span>{t(alta.clave)}</span>
              </Link>
            ))}
          </div>
        ) : null}
      </header>

      {/* **Cuando no llevas nada tuyo, se dice una vez y se dice por qué.**
          Esta portada contesta «qué tengo yo hoy»: actividades mías, mis
          oportunidades que cierran, mi embudo. Para quien opera la plataforma
          —o para cualquiera que todavía no tenga nada asignado— las cuatro
          cajas salían vacías a la vez, cada una repitiendo que no hay nada.

          Cuatro «no hay nada» seguidos no se leen como «no te han asignado
          nada»: se leen como que el producto está vacío. Y es lo primero que
          ve quien entra con la cuenta del `.env`, que es justo la de
          plataforma. Medido el 01-11-2026: con esa cuenta, cero; entrando como
          un comercial, cuatro oportunidades cerrando esta semana con sus
          importes.

          Una línea arriba lo explica y lleva a lo que SÍ hay. No se esconden
          las cajas: la respuesta a «qué tengo hoy» sigue siendo «nada», y eso
          es verdad. Lo que faltaba era el porqué. */}
      {!cargando && sinNadaMio ? (
        <div className="card mb-4 flex flex-wrap items-center justify-between gap-3 border-accent/30 bg-accent/5 p-3">
          <p className="text-titulin text-ink">{t("inicio.nadaMio")}</p>
          {veOportunidades ? (
            <Link to="/m/oportunidades" className="btn-secondary shrink-0">
              {t("inicio.verDelEquipo")}
            </Link>
          ) : null}
        </div>
      ) : null}

      {cargando ? (
        <p className="text-dato text-ink-faint" role="status">
          {t("app.cargando")}
        </p>
      ) : (
        /* **Dos columnas de distinto peso, como Lightning**: el embudo y lo
           que cierra ocupan dos tercios porque son lo que se mira, y lo que
           reclama atención —vencido, para hoy— va en la columna estrecha de la
           derecha, que es donde Salesforce pone su asistente.

           Antes eran cuatro cajas iguales en una rejilla de 2×2, y con eso una
           lista de seis actividades pesaba en pantalla lo mismo que el embudo
           entero.

           `items-start`: sin él cada tarjeta se estira hasta la altura de la
           más alta de su fila, y un hueco así se lee como «falta algo». */
        <div className="grid items-start gap-4 lg:grid-cols-3">
          {/* `min-w-0`: sin él, un título largo de la bandeja —que se corta con
              puntos suspensivos— ensanchaba la columna hasta su texto entero
              y a 390 px todas las tarjetas se salían por la derecha. */}
          <div className="flex min-w-0 flex-col gap-4">
            {/* Lo que espera mi decisión: arriba, porque mientras no decido,
                otro está parado. */}
            {veAprobaciones ? (
              <Bloque
                titulo={t("inicio.porDecidir")}
                icono="approval"
                vacio={t("inicio.nadaPorDecidir")}
                ver={{
                  a: "/m/procesos?r=Me%20toca%20decidir",
                  texto: t("inicio.verTodas"),
                }}
                cuantos={porDecidir?.length ?? 0}
              >
                {(porDecidir || []).map((d) => (
                  <li key={d.solicitud_id} className="py-1.5">
                    <Link
                      to={`/m/procesos/aprobaciones/${d.solicitud_id}`}
                      className="block truncate text-dato text-accent hover:underline"
                      title={d.titulo}
                    >
                      {d.titulo || t("inicio.sinTitulo")}
                    </Link>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        className="btn-primary"
                        disabled={decidiendo === d.solicitud_id}
                        onClick={() => void decidir(d.solicitud_id, "aprobar")}
                        aria-label={t("inicio.aprobarEsto", {
                          titulo: d.titulo,
                        })}
                      >
                        {t("inicio.aprobar")}
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={decidiendo === d.solicitud_id}
                        onClick={() => void decidir(d.solicitud_id, "rechazar")}
                        aria-label={t("inicio.rechazarEsto", {
                          titulo: d.titulo,
                        })}
                      >
                        {t("inicio.rechazar")}
                      </button>
                      {d.va_tarde ? (
                        <span className="badge badge-danger">
                          {t("inicio.vaTarde")}
                        </span>
                      ) : null}
                    </div>
                  </li>
                ))}
              </Bloque>
            ) : null}
            {falloDecision ? <Fallo error={falloDecision} /> : null}

            {/* Lo que ya se pasó. Primero y aparte: es lo único que no espera. */}
            <Bloque
              titulo={t("inicio.vencidas")}
              icono="error"
              tono="peligro"
              vacio={t("inicio.nadaVencido")}
              ver={{ a: "/m/actividades", texto: t("inicio.verTodas") }}
              cuantos={vencidas?.length ?? 0}
            >
              {(vencidas || []).map((a) => (
                <FilaActividad key={a.id} actividad={a} atrasada />
              ))}
            </Bloque>

            <Bloque
              titulo={t("inicio.hoy")}
              icono="event"
              vacio={t("inicio.nadaHoy")}
              ver={{ a: "/m/actividades", texto: t("inicio.verTodas") }}
              cuantos={hoy?.length ?? 0}
            >
              {(hoy || []).map((a) => (
                <FilaActividad key={a.id} actividad={a} />
              ))}
            </Bloque>
          </div>

          {/* La columna ancha: el embudo y lo que cierra. Va DESPUÉS en el
              marcado y antes en pantalla (`order`), para que en móvil —una
              sola columna— lo primero siga siendo lo que urge. */}
          <div className="flex flex-col gap-4 lg:col-span-2 lg:-order-1">
            {veOportunidades ? (
              <>
                <Bloque
                  titulo={t("inicio.cierranEstaSemana")}
                  icono="flag"
                  vacio={t("inicio.nadaCierra")}
                  ver={{ a: "/embudo", texto: t("inicio.verEmbudo") }}
                  cuantos={cierran?.length ?? 0}
                >
                  {(cierran || []).map((o) => (
                    <li
                      key={o.id}
                      className="flex items-center justify-between gap-3 py-1"
                    >
                      {/* Con `title`: el nombre se corta —la caja es
                          estrecha a propósito, es un resumen— y cortado sin
                          forma de leerlo entero deja «Pendiente de
                          adjudicación…» sin decir de qué va. */}
                      <Link
                        to={`/m/oportunidades/oportunidad/${o.id}`}
                        className="min-w-0 truncate text-dato text-accent hover:underline"
                        title={o.nombre}
                      >
                        {o.nombre}
                      </Link>
                      <span className="shrink-0 font-mono text-rotulo text-ink-muted">
                        {Number(o.importe || 0).toLocaleString(localizacion())}
                      </span>
                    </li>
                  ))}
                </Bloque>

                {/* El embudo, dibujado. Era una de las pantallas que enseñaba
                  barras de `div` con el número al lado para todo. */}
                {porEtapa.length > 0 ? (
                  // Sin `fallback` visible: el hueco dura lo que tarda un
                  // fichero pequeño ya en caché, y un «cargando…» que parpadea
                  // molesta más de lo que informa.
                  <Suspense fallback={null}>
                    <Grafica
                      forma="embudo"
                      titulo={t("inicio.miEmbudo")}
                      datos={{
                        filas: porEtapa,
                        ejeX: "etapa",
                        rotuloX: t("inicio.etapa"),
                        series: [
                          { clave: "importe", rotulo: t("inicio.importe") },
                        ],
                      }}
                    />
                  </Suspense>
                ) : null}
                {porEtapa.length > 0 && embudoRecortado ? (
                  <AvisoDeRecorte cuantas={embudo?.length ?? 0} />
                ) : null}
              </>
            ) : null}
          </div>
        </div>
      )}
    </>
  );
}

function Bloque({
  titulo,
  icono,
  tono,
  vacio,
  ver,
  cuantos,
  children,
}: {
  titulo: string;
  icono: string;
  tono?: "peligro";
  vacio: string;
  ver: { a: string; texto: string };
  cuantos: number;
  children: React.ReactNode;
}) {
  return (
    <section className="card p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="inline-flex items-center gap-1.5 text-titulin font-medium text-ink">
          <Icono
            nombre={icono}
            tamano="sm"
            className={tono === "peligro" ? "text-danger" : "text-ink-muted"}
          />
          {titulo}
          {/* El número va pegado al rótulo, no suelto en una tarjeta aparte:
              un contador sin su lista obliga a buscar a qué se refiere. */}
          {cuantos > 0 ? (
            <span
              className={
                tono === "peligro" ? "badge badge-danger" : "badge badge-muted"
              }
            >
              {cuantos}
            </span>
          ) : null}
        </h2>
        <Link to={ver.a} className="btn-link shrink-0">
          {ver.texto}
        </Link>
      </div>
      {cuantos === 0 ? (
        // Decirlo, y no dejar un hueco: un bloque vacío se lee como «no ha
        // cargado», y entonces nadie se fía de los que sí tienen cosas.
        <p className="py-3 text-center text-rotulo text-ink-faint">{vacio}</p>
      ) : (
        <ul className="divide-y divide-ink-dim/30">{children}</ul>
      )}
    </section>
  );
}

function FilaActividad({
  actividad,
  atrasada,
}: {
  actividad: Actividad;
  atrasada?: boolean;
}) {
  const cuando = actividad.vence_at ? new Date(actividad.vence_at) : null;
  return (
    <li className="flex items-center justify-between gap-3 py-1">
      <Link
        to={`/m/actividades/actividad/${actividad.id}`}
        className="min-w-0 truncate text-dato text-accent hover:underline"
        title={actividad.asunto}
      >
        {actividad.asunto}
      </Link>
      {cuando ? (
        <span
          className={`shrink-0 text-rotulo ${atrasada ? "text-danger" : "text-ink-muted"}`}
          title={cuando.toLocaleString(localizacion())}
        >
          {cuando.toLocaleDateString(localizacion(), {
            day: "numeric",
            month: "short",
          })}
        </span>
      ) : null}
    </li>
  );
}
