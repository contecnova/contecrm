/**
 * El calendario: el mes de uno, no otra lista (CRM-07.04.03.08).
 *
 * **El hueco, medido el 03-11-2026** comparando con Salesforce. El catálogo
 * declara hecha la capacidad «Actividades e interacciones: **agenda**, tareas,
 * delegación, recordatorios y cronología unificada», y lo que había eran tres
 * listados —Plantillas, Recurrencias y Actividades—. Una agenda no es una
 * lista ordenada por fecha: la pregunta de una agenda es **«¿qué tengo el
 * jueves?»** y **«¿qué semana tengo cargada?»**, y las dos se contestan viendo
 * los días unos al lado de otros. Allí el calendario es una pestaña propia
 * desde el primer día.
 *
 * No hace falta nada nuevo en el servidor: `/api/v1/activities` ya acepta
 * rangos (`vence_at__desde`, `vence_at__hasta`), `mias` y `tipo`. Era una
 * capacidad **escrita y sin enchufar**.
 *
 * **Lo que esta pantalla no hace es mentir sobre el día.** Una actividad puede
 * tener principio (`inicio_at`) —una reunión, una visita— o sólo vencimiento
 * (`vence_at`) —una tarea, una llamada por devolver—. Ponerlas todas en la
 * misma casilla sin decir cuál es cuál hace creer que la tarea «ocurre» ese
 * día, cuando lo que pasa es que **se acaba el plazo**. Las que sólo tienen
 * vencimiento van marcadas.
 *
 * Y si el mes trae más de lo que cabe en las páginas que se piden, **se dice**:
 * un calendario al que le faltan actividades y no avisa es peor que no tenerlo,
 * porque se usa para decidir que hay hueco.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { fecha as comoFecha, localizacion } from "@/lib/formato";
import { cn } from "@/lib/utiles";

interface Actividad {
  id: string;
  tipo: string;
  asunto: string;
  estado: string;
  prioridad: string;
  cuenta_id: string | null;
  objeto: string | null;
  objeto_id: string | null;
  vence_at: string | null;
  inicio_at: string | null;
  fin_at: string | null;
}

interface Pagina {
  items: Actividad[];
  siguiente: string | null;
  hay_mas: boolean;
}

/**
 * Cuántas páginas se piden como mucho.
 *
 * El servidor tope a 200 por página, así que son 1.000 actividades en un mes.
 * Pedirlas todas sin tope convertiría un mes muy cargado en una pantalla que
 * no termina de cargar; quedarse en una página sin decirlo enseñaría un mes a
 * medias con la cara de estar entero. Se piden cinco y, si aún hay más, se
 * avisa.
 */
const PAGINAS = 5;

/** Cuántas caben en una casilla antes de resumir en «+n». */
const POR_DIA = 3;

/** El icono de cada tipo de actividad, para reconocerla sin leer. */
const ICONO: Record<string, string> = {
  tarea: "task_alt",
  llamada: "call",
  reunion: "groups",
  nota: "sticky_note_2",
  visita: "pin_drop",
  correo: "mail",
};

/** El día de una actividad: cuando empieza si empieza, y si no cuando vence. */
function diaDe(a: Actividad): string {
  const cuando = a.inicio_at ?? a.vence_at;
  if (!cuando) return "";
  const d = new Date(cuando);
  if (Number.isNaN(d.getTime())) return "";
  // En local y no en UTC: una reunión de las 00:30 en Madrid cae el día
  // anterior si se corta la cadena ISO, y entonces la casilla miente.
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function clave(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

/**
 * El lunes de la semana en la que cae el día 1.
 *
 * La semana empieza en lunes porque es lo que dice el calendario de aquí. No
 * se deduce del `locale` a mano —`Intl.Locale.weekInfo` no lo trae todavía en
 * todos los navegadores y adivinarlo por el idioma falla en inglés de Reino
 * Unido—, así que va escrito y dicho.
 */
function primerDiaDeLaRejilla(ano: number, mes: number): Date {
  const primero = new Date(ano, mes, 1);
  const dia = primero.getDay(); // 0 = domingo
  const atras = (dia + 6) % 7;
  return new Date(ano, mes, 1 - atras);
}

export function Calendario() {
  const { t } = useTranslation();
  const hoy = useMemo(() => new Date(), []);
  const [ano, setAno] = useState(hoy.getFullYear());
  const [mes, setMes] = useState(hoy.getMonth());
  const [soloMias, setSoloMias] = useState(false);
  const [datos, setDatos] = useState<Actividad[] | null>(null);
  const [faltan, setFaltan] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [abierto, setAbierto] = useState<string>("");

  const dias = useMemo(() => {
    const inicio = primerDiaDeLaRejilla(ano, mes);
    // Seis semanas siempre: con cinco, un mes que empieza en domingo y tiene
    // 31 días deja el último fuera de la rejilla sin que se note.
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(inicio);
      d.setDate(inicio.getDate() + i);
      return d;
    });
  }, [ano, mes]);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    setDatos(null);
    setFaltan(false);
    // **El rango es el de la REJILLA, no el del mes.** Pidiendo sólo el mes,
    // las casillas de los días de antes y de después salían vacías con la
    // misma cara que un día sin nada: no es que no hubiera actividades el 31
    // de octubre, es que no se habían preguntado. Una casilla vacía que en
    // realidad es «no mirado» es justo lo que no puede hacer un calendario,
    // porque se usa para decidir que hay hueco. Visto en el navegador el
    // 03-11-2026.
    const desde = primerDiaDeLaRejilla(ano, mes);
    const hasta = new Date(desde);
    hasta.setDate(desde.getDate() + 42);
    (async () => {
      const juntas: Actividad[] = [];
      let cursor = "";
      let quedaba = false;
      for (let i = 0; i < PAGINAS; i += 1) {
        const parametros = new URLSearchParams({
          vence_at__desde: desde.toISOString(),
          vence_at__hasta: hasta.toISOString(),
          limite: "200",
        });
        if (soloMias) parametros.set("mias", "true");
        if (cursor) parametros.set("cursor", cursor);
        const { datos: pagina } = await llamar<Pagina>(
          `/api/v1/activities?${parametros.toString()}`,
          { signal: control.signal },
        );
        juntas.push(...(pagina.items ?? []));
        quedaba = Boolean(pagina.hay_mas);
        if (!quedaba || !pagina.siguiente) break;
        cursor = pagina.siguiente;
      }
      setDatos(juntas);
      setFaltan(quedaba);
    })().catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [ano, mes, soloMias]);

  useEffect(cargar, [cargar]);

  /**
   * ¿Distingue algo el reloj?
   *
   * Marca las que **sólo vencen**, y eso sólo informa si hay también de las
   * otras. Visto en el navegador el 03-11-2026: ninguna actividad del mes
   * traía `inicio_at`, así que el reloj salía en las ciento y pico y no
   * separaba nada — una marca que llevan todos es decoración, no un dato. Se
   * mide sobre lo que ha llegado, no se supone.
   */
  const hayDeLasDos = useMemo(() => {
    const lista = datos ?? [];
    return (
      lista.some((a) => a.inicio_at) && lista.some((a) => !a.inicio_at && a.vence_at)
    );
  }, [datos]);

  const porDia = useMemo(() => {
    const mapa = new Map<string, Actividad[]>();
    for (const a of datos ?? []) {
      const d = diaDe(a);
      if (!d) continue;
      mapa.set(d, [...(mapa.get(d) ?? []), a]);
    }
    return mapa;
  }, [datos]);

  const nombreDelMes = useMemo(
    () =>
      new Intl.DateTimeFormat(localizacion(), {
        month: "long",
        year: "numeric",
      }).format(new Date(ano, mes, 1)),
    [ano, mes],
  );

  const nombresDeDia = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(localizacion(), { weekday: "short" });
    // Desde un lunes conocido, para que la cabecera case con la rejilla.
    return Array.from({ length: 7 }, (_, i) => fmt.format(new Date(2024, 0, 1 + i)));
  }, []);

  function mover(cuantos: number) {
    const d = new Date(ano, mes + cuantos, 1);
    setAno(d.getFullYear());
    setMes(d.getMonth());
    setAbierto("");
  }

  const delDiaAbierto = abierto ? (porDia.get(abierto) ?? []) : [];

  return (
    <>
      <CabeceraPagina
        titulo={t("calendario.titulo")}
        icono="calendar_month"
        entradilla={t("calendario.entradilla")}
        acciones={
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setSoloMias((v) => !v)}
              className={cn("btn-secondary", soloMias && "bg-accent/10 text-accent")}
              aria-pressed={soloMias}
            >
              {t("calendario.soloMias")}
            </button>
            <button
              type="button"
              onClick={() => {
                setAno(hoy.getFullYear());
                setMes(hoy.getMonth());
                setAbierto("");
              }}
              className="btn-secondary"
            >
              {t("calendario.hoy")}
            </button>
            <button
              type="button"
              onClick={() => mover(-1)}
              className="btn-icon text-ink-muted hover:bg-paper-light hover:text-ink"
              aria-label={t("calendario.mesAnterior")}
            >
              <Icono nombre="chevron_left" tamano="sm" />
            </button>
            <button
              type="button"
              onClick={() => mover(1)}
              className="btn-icon text-ink-muted hover:bg-paper-light hover:text-ink"
              aria-label={t("calendario.mesSiguiente")}
            >
              <Icono nombre="chevron_right" tamano="sm" />
            </button>
          </div>
        }
      />

      {/* `first-letter` y no `capitalize`: con `capitalize` salía «Noviembre
          De 2026», porque pone en mayúscula CADA palabra. */}
      <p className="mb-3 text-grande font-medium text-ink first-letter:uppercase">
        {nombreDelMes}
      </p>

      {/* Un mes recortado se dice. Un calendario al que le faltan actividades
          y no avisa es peor que no tenerlo: se usa para decidir que hay
          hueco. */}
      {faltan ? (
        <p className="card mb-3 border-warning/40 p-3 text-dato text-warning" role="status">
          {t("calendario.faltan", { cuantas: datos?.length ?? 0 })}
        </p>
      ) : null}

      {fallo ? (
        <Fallo error={fallo} reintentar={cargar} />
      ) : !datos ? (
        <Cargando />
      ) : (
        <>
          <div className="card overflow-hidden p-0">
            <div className="grid grid-cols-7 border-b border-ink-dim/60">
              {nombresDeDia.map((n) => (
                <div
                  key={n}
                  className="section-label px-2 py-1.5 text-center"
                >
                  {n}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-7">
              {dias.map((d) => {
                const k = clave(d);
                const suyas = porDia.get(k) ?? [];
                const deOtroMes = d.getMonth() !== mes;
                const esHoy = k === clave(hoy);
                return (
                  <div
                    key={k}
                    className={cn(
                      "min-h-[104px] border-b border-r border-ink-dim/40 p-1.5",
                      deOtroMes && "bg-paper-dark",
                    )}
                  >
                    <div className="mb-1 flex items-center justify-between">
                      <span
                        className={cn(
                          "text-rotulo",
                          deOtroMes ? "text-ink-faint" : "text-ink-muted",
                          esHoy &&
                            "inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1 font-bold text-paper",
                        )}
                      >
                        {d.getDate()}
                      </span>
                      {suyas.length > POR_DIA ? (
                        <button
                          type="button"
                          onClick={() => setAbierto(abierto === k ? "" : k)}
                          className="btn-link text-rotulo"
                        >
                          {t("calendario.masDelDia", {
                            cuantas: suyas.length - POR_DIA,
                          })}
                        </button>
                      ) : null}
                    </div>
                    <ul className="flex flex-col gap-0.5">
                      {suyas.slice(0, POR_DIA).map((a) => (
                        <li key={a.id}>
                          <Enlace a={a} t={t} marcarVencimiento={hayDeLasDos} />
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          </div>

          {/* El día entero, debajo: una casilla de 104px no da para ocho
              reuniones, y recortar sin dónde verlas enteras es esconderlas. */}
          {abierto ? (
            <section className="card mt-3 p-3">
              <h2 className="mb-2 text-titulo font-medium text-ink">
                {comoFecha(abierto)}
              </h2>
              <ul className="flex flex-col gap-1">
                {delDiaAbierto.map((a) => (
                  <li key={a.id}>
                    <Enlace a={a} t={t} ancho marcarVencimiento={hayDeLasDos} />
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {porDia.size === 0 ? (
            <Vacio
              compacto
              titulo={t("calendario.ningunaEsteMes")}
              detalle={
                soloMias
                  ? t("calendario.ningunaMiaPorque")
                  : t("calendario.ningunaPorque")
              }
            />
          ) : null}
        </>
      )}
    </>
  );
}

/**
 * Una actividad dentro de su día.
 *
 * El icono dice de qué va sin leer, y el reloj marca las que **sólo vencen**:
 * una tarea no «ocurre» ese día, se le acaba el plazo, y mezclarlas sin
 * distinguir hace creer que el día está más ocupado de lo que está.
 */
function Enlace({
  a,
  t,
  ancho,
  marcarVencimiento,
}: {
  a: Actividad;
  t: (clave: string, datos?: Record<string, unknown>) => string;
  ancho?: boolean;
  /** Sólo cuando en lo que se enseña hay de las dos clases. */
  marcarVencimiento: boolean;
}) {
  const soloVence = marcarVencimiento && !a.inicio_at && Boolean(a.vence_at);
  const destino =
    a.cuenta_id !== null
      ? `/m/cuentas/cuenta/${a.cuenta_id}`
      : `/m/actividades?buscar=${encodeURIComponent(a.asunto)}`;
  return (
    <Link
      to={destino}
      title={a.asunto}
      className={cn(
        "flex items-center gap-1 rounded px-1 py-0.5 text-rotulo text-ink hover:bg-paper-light",
        a.estado === "completada" && "text-ink-faint line-through",
        ancho && "text-dato",
      )}
    >
      <Icono
        nombre={ICONO[a.tipo] ?? "event"}
        tamano="sm"
        className="shrink-0 text-ink-faint"
      />
      {/* Las que sólo vencen van marcadas, y con texto para el lector de
          pantalla: un icono a secas es `aria-hidden` y no dice nada a quien
          no lo ve. */}
      {soloVence ? (
        <>
          <Icono nombre="schedule" tamano="sm" className="shrink-0 text-warning" />
          <span className="sr-only">{t("calendario.soloVence")}</span>
        </>
      ) : null}
      {/* Con `title`: el asunto se corta —y tiene que cortarse, una celda de
          calendario no da para más— pero cortado y sin forma de leerlo entero
          deja «Repaso de incidencias abiertas — Tecnologías…» sin decir de qué
          cliente es, que es justo lo que se mira. */}
      <span className="truncate" title={a.asunto}>
        {a.asunto}
      </span>
    </Link>
  );
}
