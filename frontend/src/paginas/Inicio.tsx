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
import { CabeceraPagina } from "@/componentes/Pagina";
import { filas, llamar, salvoCancelacion } from "@/lib/api";
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
  import("@/componentes/graficas/Grafica").then((m) => ({ default: m.Grafica })),
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
    llamar<unknown>(
      `/api/v1/activities?mias=true&estado__en=pendiente,en_curso&vence_at__hasta=${encodeURIComponent(finDeHoy())}&limite=6`,
      { signal },
    )
      .then((r) => setHoy(filas<Actividad>(r.datos)))
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
    llamar<unknown>(
      `/api/v1/opportunities?mias=true&estado=abierta&fecha_cierre__hasta=${finDeSemana()}&limite=6`,
      { signal },
    )
      .then((r) => setCierran(filas<Oportunidad>(r.datos)))
      .catch(salvoCancelacion(() => setCierran([])));
    llamar<unknown>("/api/v1/opportunities?mias=true&estado=abierta&limite=200", { signal })
      .then((r) => setEmbudo(filas<Oportunidad>(r.datos)))
      .catch(salvoCancelacion(() => setEmbudo([])));
    llamar<unknown>("/api/v1/pipelines", { signal })
      .then((r) => {
        const lista = filas<{ etapas?: Etapa[] }>(r.datos);
        setEtapas(lista[0]?.etapas || []);
      })
      .catch(salvoCancelacion(() => setEtapas([])));
    return () => control.abort();
  }, [veOportunidades]);

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

  return (
    <>
      <CabeceraPagina
        titulo={t("inicio.saludo", { nombre: sesion?.nombre || sesion?.email || "" })}
        entradilla={t("inicio.miDia")}
        icono="today"
        acciones={
          altas.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {altas.slice(0, 3).map((alta) => (
                <Link key={alta.a} to={alta.a} className="btn-secondary gap-1.5">
                  <Icono nombre={alta.icono} tamano="sm" />
                  <span>{t(alta.clave)}</span>
                </Link>
              ))}
            </div>
          ) : null
        }
      />

      {cargando ? (
        <p className="text-2xs text-ink-faint" role="status">
          {t("app.cargando")}
        </p>
      ) : (
        // `items-start`: sin él, cada tarjeta se estira hasta la altura de la
        // más alta de su fila, y la de «cierran esta semana» quedaba medio
        // vacía al lado del embudo. Un hueco así se lee como «falta algo».
        <div className="grid items-start gap-4 lg:grid-cols-2">
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
                  <li key={o.id} className="flex items-center justify-between gap-3 py-1">
                    <Link
                      to={`/m/oportunidades/oportunidad/${o.id}`}
                      className="min-w-0 truncate text-2xs text-accent hover:underline"
                    >
                      {o.nombre}
                    </Link>
                    <span className="shrink-0 font-mono text-3xs text-ink-muted">
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
                    series: [{ clave: "importe", rotulo: t("inicio.importe") }],
                  }}
                />
                </Suspense>
              ) : null}
            </>
          ) : null}
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
        <h2 className="inline-flex items-center gap-1.5 text-xs font-medium text-ink">
          <Icono
            nombre={icono}
            tamano="sm"
            className={tono === "peligro" ? "text-danger" : "text-ink-muted"}
          />
          {titulo}
          {/* El número va pegado al rótulo, no suelto en una tarjeta aparte:
              un contador sin su lista obliga a buscar a qué se refiere. */}
          {cuantos > 0 ? (
            <span className={tono === "peligro" ? "badge badge-danger" : "badge badge-muted"}>
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
        <p className="py-3 text-center text-3xs text-ink-faint">{vacio}</p>
      ) : (
        <ul className="divide-y divide-ink-dim/30">{children}</ul>
      )}
    </section>
  );
}

function FilaActividad({ actividad, atrasada }: { actividad: Actividad; atrasada?: boolean }) {
  const cuando = actividad.vence_at ? new Date(actividad.vence_at) : null;
  return (
    <li className="flex items-center justify-between gap-3 py-1">
      <Link
        to={`/m/actividades/actividad/${actividad.id}`}
        className="min-w-0 truncate text-2xs text-accent hover:underline"
      >
        {actividad.asunto}
      </Link>
      {cuando ? (
        <span
          className={`shrink-0 text-3xs ${atrasada ? "text-danger" : "text-ink-muted"}`}
          title={cuando.toLocaleString(localizacion())}
        >
          {cuando.toLocaleDateString(localizacion(), { day: "numeric", month: "short" })}
        </span>
      ) : null}
    </li>
  );
}
