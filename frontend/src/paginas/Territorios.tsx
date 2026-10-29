/**
 * El mapa de territorios: qué pasaría si se publicara
 * (CRM-03.02.02.02, CRM-03.02.02.03, CRM-03.02.02.05).
 *
 * El módulo listaba los territorios y ahí se acababa. Y lo que de verdad se
 * hace con un mapa de territorios no es mirarlo: es **cambiarlo sin romper el
 * año de nadie**. Publicar y ver qué pasa significa que doscientas cuentas
 * cambian de dueño el lunes por la mañana, y deshacerlo no devuelve las
 * conversaciones que ya se tuvieron.
 *
 * Por eso el panel que manda es el simulador, y de lo que devuelve lo que
 * importa no son las que cambian: son **las que se quedan sin territorio** y
 * **los solapes**. Un solape —dos territorios con la misma prioridad— produce
 * una asignación que depende del orden alfabético, y nadie lo busca hasta que
 * dos comerciales discuten por una cuenta.
 *
 * **Y las excepciones caducan.** Una cuenta sacada de su territorio «hasta
 * marzo» vuelve sola en marzo, sin avisar a nadie: quien la llevaba se entera
 * por el pipeline. Las que vencen en treinta días o menos salen señaladas.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { listar } from "@/lib/listados";

interface Territorio {
  id: string;
  clave: string;
  nombre: string;
  prioridad: number;
  responsable_id: string | null;
  padre_id: string | null;
  criterios: { campo?: string; operador?: string; valor?: unknown }[];
}

interface Simulacion {
  cuentas: number;
  cambian: { cuenta: string; de: string | null; a: string }[];
  se_quedan: number;
  sin_territorio: { cuenta: string }[] | string[];
  solapes: { cuenta: string; territorios: string[]; por_que: string }[];
  seguro_publicar: boolean;
}

interface Consecucion {
  cuotas: {
    sujeto: string;
    tipo: string;
    metrica: string;
    objetivo: string;
    objetivo_sin_prorratear: string;
    prorrateado: boolean;
    logrado: string;
    pct: number | null;
    falta: string;
  }[];
  medible: boolean;
  aviso: string;
}

interface Excepciones {
  excepciones: {
    id: string;
    cuenta_id: string;
    territorio_id: string;
    motivo: string;
    hasta: string | null;
    permanente: boolean;
    dias_para_vencer: number | null;
  }[];
  cuantas: number;
  vencen_pronto: number;
  que_significa: string;
}

export function Territorios() {
  const { t } = useTranslation();
  const [territorios, setTerritorios] = useState<Territorio[]>([]);
  const [excepciones, setExcepciones] = useState<Excepciones | null>(null);
  const [simulacion, setSimulacion] = useState<Simulacion | null>(null);
  const [consecucion, setConsecucion] = useState<Consecucion | null>(null);
  const [simulando, setSimulando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    listar<Territorio>("/api/v1/territorios?limite=100", { signal: control.signal })
      .then(setTerritorios)
      .catch(salvoCancelacion(setFallo));
    void llamar<Excepciones>("/api/v1/territorios/excepciones", {
      signal: control.signal,
    })
      .then((r) => setExcepciones(r.datos))
      .catch(() => undefined);
    // Las cuotas van aquí y no en otra pantalla: el territorio decide de quién
    // es una cuenta y la cuota decide cuánto tiene que vender quien lo lleva.
    // Mirar una sin la otra es cómo se reparte un mapa que nadie puede cumplir.
    void llamar<Consecucion>("/api/v1/cuotas/consecucion", {
      signal: control.signal,
    })
      .then((r) => setConsecucion(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  /**
   * Simular con las cuentas de verdad.
   *
   * Las manda la pantalla porque el servicio de territorios **no lee la tabla
   * de cuentas**: vive en otro servicio y ninguno lee el esquema de otro. Así
   * que se piden aquí y se mandan con los atributos que miran los criterios.
   */
  async function simular() {
    setSimulando(true);
    setAviso("");
    try {
      const cuentas = await listar<Record<string, unknown>>(
        "/api/v1/accounts?limite=200&estado=",
      );
      const r = await llamar<Simulacion>("/api/v1/territorios/simular", {
        metodo: "POST",
        cuerpo: { cuentas },
      });
      setSimulacion(r.datos);
      setAviso(t("territorios.simulado", { cuantas: cuentas.length }));
    } catch (error) {
      setFallo(error);
    } finally {
      setSimulando(false);
    }
  }

  if (fallo && territorios.length === 0) {
    return <Fallo error={fallo} reintentar={cargar} />;
  }

  return (
    <>
      <CabeceraPagina
        titulo={t("territorios.titulo")}
        icono="map"
        entradilla={t("territorios.intro")}
      />

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("territorios.queSiPublico")}</h2>
        <p className="mb-2 text-3xs text-ink-faint">
          {t("territorios.queSiPublicoAyuda")}
        </p>
        <button
          type="button"
          className="btn btn-secundario"
          onClick={() => void simular()}
          disabled={simulando}
        >
          {simulando ? t("territorios.simulando") : t("territorios.simular")}
        </button>
        <p role="status" aria-live="polite" className="mt-2 text-2xs text-ink-muted">
          {aviso}
        </p>

        {simulacion ? (
          <div className="mt-2">
            <p className="text-2xs text-ink">
              {t("territorios.resultado", {
                cambian: simulacion.cambian.length,
                quedan: simulacion.se_quedan,
              })}
            </p>
            {/* Lo que NO encaja va primero y en color: una cuenta sin dueño es
                un problema que hay que ver, no un hueco que se rellena solo. */}
            {simulacion.sin_territorio.length > 0 ? (
              <p className="mt-1 text-2xs text-warning">
                {t("territorios.sinTerritorio", {
                  cuantas: simulacion.sin_territorio.length,
                })}
              </p>
            ) : null}
            {simulacion.solapes.length > 0 ? (
              <>
                <p className="mt-1 text-2xs text-danger">
                  {t("territorios.solapes", { cuantos: simulacion.solapes.length })}
                </p>
                <ul className="mt-1 space-y-1">
                  {simulacion.solapes.slice(0, 5).map((s, i) => (
                    <li key={`${s.cuenta}-${i}`} className="text-3xs text-ink-muted">
                      <span className="font-medium text-ink">{s.cuenta}</span>{" "}
                      {s.territorios.join(" · ")} — {s.por_que}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            <p
              className={
                simulacion.seguro_publicar
                  ? "mt-2 text-2xs text-success"
                  : "mt-2 text-2xs text-danger"
              }
            >
              {simulacion.seguro_publicar
                ? t("territorios.seguro")
                : t("territorios.noSeguro")}
            </p>
          </div>
        ) : null}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <ElMapa territorios={territorios} />
        <LasExcepciones excepciones={excepciones} />
        <LasCuotas consecucion={consecucion} />
      </div>
    </>
  );
}

/**
 * Los territorios con su prioridad y sus criterios.
 *
 * **La prioridad va delante del nombre** porque es lo que decide los empates,
 * y dos territorios con la misma prioridad son el solape que el simulador
 * señala: verlo aquí es lo que permite arreglarlo antes de simular.
 */
function ElMapa({ territorios }: { territorios: Territorio[] }) {
  const { t } = useTranslation();
  const repetidas = new Set(
    territorios
      .map((x) => x.prioridad)
      .filter((p, i, todas) => todas.indexOf(p) !== i),
  );

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("territorios.mapa")}</h2>
      {territorios.length === 0 ? (
        <Vacio titulo={t("territorios.sinTerritorios")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {territorios.map((x) => (
            <li key={x.id} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
              <span
                className={
                  repetidas.has(x.prioridad)
                    ? "chip-dato chip-dato--no"
                    : "chip-dato"
                }
              >
                {x.prioridad}
              </span>
              <span className="text-2xs font-medium text-ink">{x.nombre}</span>
              <span className="text-3xs text-ink-faint">{x.clave}</span>
              <span className="text-3xs text-ink-muted">
                {t("territorios.criterios", { cuantos: x.criterios.length })}
              </span>
            </li>
          ))}
        </ul>
      )}
      {repetidas.size > 0 ? (
        <p className="mt-2 text-3xs text-danger">
          {t("territorios.prioridadRepetida", {
            cuantas: repetidas.size,
          })}
        </p>
      ) : null}
    </section>
  );
}

/**
 * Las excepciones, y cuándo dejan de aplicarse (CRM-03.02.02.02).
 *
 * Se declaraban y no se podían listar: el resolutor las leía al asignar —así
 * que funcionaban— y ninguna ruta las devolvía. «¿Por qué esta cuenta es de
 * Ana y no de la zona norte?» sólo se contestaba mirando la base de datos.
 *
 * Y lo que de verdad hacía falta es **cuándo vencen**: una excepción que
 * caduca mueve una cuenta de dueño sin avisar a nadie.
 */
function LasExcepciones({ excepciones }: { excepciones: Excepciones | null }) {
  const { t } = useTranslation();
  if (!excepciones) return null;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("territorios.excepciones")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">
        {t("territorios.excepcionesAyuda")}
      </p>
      {excepciones.excepciones.length === 0 ? (
        <Vacio titulo={t("territorios.sinExcepciones")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {excepciones.excepciones.map((e) => (
            <li key={e.id} className="py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-3 text-2xs">
                <span className="font-medium text-ink">{e.cuenta_id.slice(0, 8)}</span>
                {e.permanente ? (
                  <span className="chip-dato">{t("territorios.permanente")}</span>
                ) : (
                  <span
                    className={
                      (e.dias_para_vencer ?? 999) <= 30
                        ? "chip-dato chip-dato--no"
                        : "chip-dato"
                    }
                  >
                    {t("territorios.vence", { dias: e.dias_para_vencer })}
                  </span>
                )}
              </div>
              {/* El motivo es obligatorio al declararla: una excepción sin
                  motivo es indistinguible de un error de configuración. */}
              <p className="text-3xs text-ink-muted">{e.motivo}</p>
            </li>
          ))}
        </ul>
      )}
      <p
        className={
          excepciones.vencen_pronto > 0
            ? "mt-2 text-2xs text-warning"
            : "mt-2 text-3xs text-ink-faint"
        }
      >
        {excepciones.que_significa}
      </p>
    </section>
  );
}

/**
 * Las cuotas y su prorrateo (CRM-03.02.02.05).
 *
 * **Quien entra el día 20 no tiene la cuota entera**, y medirle contra ella es
 * garantizarle que no la cumple. El prorrateo existe por eso, y el objetivo
 * sin prorratear va al lado a propósito: es el número del plan, el que está
 * en la hoja de alguien, y sin los dos delante parece que uno de los dos está
 * mal.
 *
 * Igual al revés: quien se va a mitad de periodo tampoco arrastra el objetivo
 * completo, y su equipo lo hereda si nadie lo mira.
 */
function LasCuotas({ consecucion }: { consecucion: Consecucion | null }) {
  const { t } = useTranslation();
  if (!consecucion) return null;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("territorios.cuotas")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">{t("territorios.cuotasAyuda")}</p>
      {!consecucion.medible ? (
        <p className="text-2xs text-ink-muted">{consecucion.aviso}</p>
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {consecucion.cuotas.map((c) => (
            <li key={`${c.sujeto}-${c.metrica}`} className="py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-3 text-2xs">
                <span className="font-medium text-ink">{c.sujeto.slice(0, 8)}</span>
                <span className="chip-dato">{c.metrica}</span>
                <span className="text-ink-muted">
                  {t("territorios.logradoDe", {
                    logrado: c.logrado,
                    objetivo: c.objetivo,
                  })}
                </span>
                {c.pct !== null ? (
                  <span className="text-3xs text-ink-faint">{c.pct} %</span>
                ) : null}
              </div>
              {/* El objetivo del PLAN al lado del efectivo: sin los dos, uno de
                  los dos números parece equivocado. */}
              {c.prorrateado ? (
                <p className="text-3xs text-warning">
                  {t("territorios.prorrateada", {
                    plan: c.objetivo_sin_prorratear,
                  })}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
