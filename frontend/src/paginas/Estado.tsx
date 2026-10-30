/**
 * La página de estado del tenant (CRM-00.06.01.06, CRM-00.01.06.03,
 * CRM-00.01.06.04, CRM-00.01.06.05).
 *
 * Enseña además CRM-00.06.01.04 (el objetivo de servicio comprometido por tier
 * y el presupuesto de error gastado), CRM-00.06.01.05 (el alertado con su
 * runbook enlazado) y CRM-00.06.02.07 (si el sistema está en modo degradado:
 * la lectura sigue y la escritura no).

 * Enseña también los compromisos de servicio del tenant —RPO, RTO,
 * disponibilidad— junto a lo medido (CRM-07.04.03.30): un compromiso escrito en
 * un contrato que nadie compara con la realidad no lo comprueba nadie.
 *
 * **Dos cosas que el sistema hacía y no enseñaba.** La presión: cuando un
 * servicio va apretado se aplaza lo que no es crítico, y eso explica por qué
 * algo tarda hoy y ayer no — sin verlo, se busca la causa en el sitio
 * equivocado. Y el freno automático: a un tenant que se sale de su patrón se
 * le baja la cuota, se aplicaba en el proxy de cada petición y **no había
 * ninguna ruta que dijera a quién**. Un cliente podía llevar horas a un cuarto
 * de su cuota, con sus integraciones reintentando más fuerte, y para
 * averiguarlo había que leer los registros.
 *
 * La compone el gateway juntando lo que publica cada servicio sobre sus propios
 * componentes. Aquí solo se pinta: si esta pantalla dedujera el estado general
 * a partir de los componentes, habría dos definiciones de «va bien» y se
 * separarían.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";

interface Componente {
  servicio: string;
  componente: string;
  estado: string;
  detalle?: string;
}

interface Respuesta {
  estado: string;
  consultado_at: string;
  componentes: Componente[];
}

const COLOR: Record<string, string> = {
  ok: "text-success",
  degradado: "text-warning",
  caido: "text-danger",
};

// El estado global va como insignia y no como texto de color: un párrafo en
// rojo bajo el título se lee como un aviso cualquiera, y una insignia con
// relleno se ve antes que el propio título — que es lo que hace falta cuando
// algo está caído. El color solo, además, no basta: la palabra va dentro.
const INSIGNIA: Record<string, string> = {
  ok: "badge-success",
  degradado: "badge-warning",
  caido: "badge-danger",
};

interface Compromiso {
  metrica: string;
  que_es: string;
  comprometido: number;
  unidad: string;
  medido: number | null;
  como_se_mide: string;
}

interface Compromisos {
  tier: string;
  compromisos: Compromiso[];
}

/** `GET /estado/slo`: el objetivo por servicio y el presupuesto de error. */
interface Slo {
  tier: string;
  servicios_medibles: number;
  sin_medicion: string[];
  presupuesto_agotado_en: string[];
  se_puede_desplegar: boolean;
  que_significa: string;
  servicios: {
    servicio: string;
    objetivo_pct: number;
    latencia_objetivo_ms: number;
    presupuesto_minutos: number;
    aviso?: string;
  }[];
}

/** `GET /estado/consumo`: cuánto se lleva gastado de lo contratado. */
interface Consumo {
  metricas: { metrica: string; consumido: number; por_modulo: Record<string, number> }[];
}

/** `GET /estado/contratos`: si lo que un servicio promete llega de verdad. */
interface Contratos {
  en_verde: boolean;
  incumplimientos: unknown[];
  sin_respuesta: string[];
  servicios: { servicio: string; cobertura_pct: number; incumplimientos: unknown[] }[];
}

/** `GET /estado/consultas-degradadas`: lo que va más lento de lo que debería. */
interface Presion {
  medible: boolean;
  presion: number | null;
  /** El que peor va: lo que se aplaza depende de él, no de la media. */
  peor: string | null;
  servicios: { servicio: string; presion?: number; legible?: boolean }[];
  sin_respuesta: string[];
  que_significa: string;
  aviso: string;
  la_interfaz?: unknown;
}

interface Frenado {
  tenant_id: string;
  frenado: boolean;
  /** 0,75 · 0,5 · 0,25 de su cuota. */
  factor_de_cuota: number;
  hasta?: string | null;
  quedan_segundos?: number | null;
  motivo: string;
  /** Por debajo del mínimo no se evalúa a nadie, y eso explica un «todavía no». */
  ventanas_observadas: number;
  escalon: number;
}

interface Frenados {
  observados: Frenado[];
  frenados: number;
  minimo_ventanas: number;
  porque_solo_estos: string;
}

interface Degradadas {
  aviso: string;
  sin_respuesta: string[];
  servicios: { servicio: string; consultas: unknown[] }[];
}

export function Estado() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Respuesta | null>(null);
  const [compromisos, setCompromisos] = useState<Compromisos | null>(null);
  const [slo, setSlo] = useState<Slo | null>(null);
  const [consumo, setConsumo] = useState<Consumo | null>(null);
  const [contratos, setContratos] = useState<Contratos | null>(null);
  const [degradadas, setDegradadas] = useState<Degradadas | null>(null);
  const [presion, setPresion] = useState<Presion | null>(null);
  const [frenados, setFrenados] = useState<Frenados | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Respuesta>("/api/v1/estado", { signal: control.signal })
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    // Los compromisos se piden aparte y su fallo NO tumba la página: el estado
    // de los componentes es lo urgente cuando algo va mal, y perderlo porque no
    // se pudo leer un número de contrato sería el peor momento para perderlo.
    llamar<Compromisos>("/api/v1/compromisos", { signal: control.signal })
      .then((r) => setCompromisos(r.datos))
      .catch(() => undefined);
    // Y lo demás que esta página dice enseñar desde que se escribió —el
    // objetivo de servicio y el presupuesto de error (CRM-00.06.01.04)— más lo
    // que se pregunta al lado: cuánto se lleva gastado de lo contratado, si lo
    // que un servicio promete llega de verdad, y qué va más lento de lo que
    // debería. Las cuatro estaban servidas y ninguna se pedía.
    //
    // Cada una con su fallo: que no se pueda leer el consumo no puede dejar
    // sin ver qué componente está caído, que es lo urgente cuando algo va mal.
    llamar<Slo>("/api/v1/estado/slo", { signal: control.signal })
      .then((r) => setSlo(r.datos))
      .catch(() => undefined);
    llamar<Consumo>("/api/v1/estado/consumo", { signal: control.signal })
      .then((r) => setConsumo(r.datos))
      .catch(() => undefined);
    llamar<Contratos>("/api/v1/estado/contratos", { signal: control.signal })
      .then((r) => setContratos(r.datos))
      .catch(() => undefined);
    llamar<Presion>("/api/v1/estado/presion", { signal: control.signal })
      .then((r) => setPresion(r.datos))
      .catch(() => undefined);
    llamar<Frenados>("/api/v1/estado/frenados", { signal: control.signal })
      .then((r) => setFrenados(r.datos))
      .catch(() => undefined);
    llamar<Degradadas>("/api/v1/estado/consultas-degradadas", { signal: control.signal })
      .then((r) => setDegradadas(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  if (fallo) return <Fallo error={fallo} />;
  if (!datos) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("estado.titulo")}
        icono="monitor_heart"
        acciones={
          <span className={`badge ${INSIGNIA[datos.estado] ?? "badge-muted"}`}>
            {datos.estado}
          </span>
        }
      />
      <Rejilla
        className="mt-4"
        cabeceras={[
          t("estado.servicio"),
          t("estado.componente"),
          t("estado.situacion"),
          t("estado.detalle"),
        ]}
      >
        {datos.componentes.map((c) => (
          <tr
            key={`${c.servicio}:${c.componente}`}
            className="border-b border-ink-dim/30 last:border-0"
          >
            <Casilla className="text-ink-muted">{c.servicio}</Casilla>
            <Casilla className="text-ink">{c.componente}</Casilla>
            <Casilla className={`${COLOR[c.estado] ?? "text-ink-muted"}`}>
              {c.estado}
            </Casilla>
            <Casilla className="text-2xs text-ink-faint">
              {c.detalle ?? "—"}
            </Casilla>
          </tr>
        ))}
      </Rejilla>

      {/*
        `compromisos?.compromisos?.length` y no solo `compromisos`: la petición
        se protege de FALLAR —su error no tumba la página, que es lo correcto—
        y no de **responder con otra forma**. Con una respuesta sin la lista,
        esta pantalla reventaba al pintar y la frontera se llevaba la página
        entera... que es justo la página de estado, la que se mira cuando algo
        va mal. Medido el 05-10-2026 con la prueba de contenido de pantallas.
      */}
      {compromisos?.compromisos?.length ? (
        <>
          <h2 className="mt-8 text-sm font-medium text-ink">
            {t("estado.compromisos")} · {compromisos.tier}
          </h2>
          <p className="mt-1 text-2xs text-ink-faint">
            {t("estado.compromisosIntro")}
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {compromisos.compromisos.map((c) => (
              <div
                key={c.metrica}
                className="rounded-xl border border-ink-dim/60 bg-paper p-4"
              >
                <p className="text-xs text-ink">{c.metrica}</p>
                <p className="mt-1 text-3xs text-ink-faint">{c.que_es}</p>
                <p className="mt-3 text-2xs text-ink-muted">
                  {t("estado.comprometido")}:{" "}
                  <span className="text-ink">
                    {c.comprometido} {c.unidad}
                  </span>
                </p>
                <p className="text-2xs text-ink-muted">
                  {t("estado.medido")}:{" "}
                  {/* Lo que no se puede medir se dice. Un cero aquí se leería
                      como «se cumple», que es la lectura contraria a la real. */}
                  {c.medido === null ? (
                    <span className="text-warning">{t("estado.noSeMide")}</span>
                  ) : (
                    <span
                      className={
                        c.medido > c.comprometido
                          ? "text-danger"
                          : "text-success"
                      }
                    >
                      {c.medido} {c.unidad}
                    </span>
                  )}
                </p>
                <p className="mt-2 text-3xs text-ink-faint">{c.como_se_mide}</p>
              </div>
            ))}
          </div>
        </>
      ) : null}

      {/* El presupuesto de error, y lo PRIMERO que decide: si hoy se puede
          desplegar. Un objetivo de servicio que no cambia ninguna decisión es
          un número de informe; éste dice cuándo toca parar de añadir y
          arreglar lo que falla.

          Y los cuatro paneles de aquí abajo comprueban la LISTA, no el objeto:
          es la misma lección que ya estaba escrita unas líneas más arriba para
          los compromisos y que volví a saltarme. Protegerse de que la petición
          FALLE no protege de que conteste con otra forma, y entonces esta
          pantalla —la que se mira justo cuando algo va mal— se cae entera al
          pintar. Lo cazaron sus propias pruebas. */}
      {slo?.servicios?.length ? (
        <>
          <h2 className="mt-8 text-sm font-medium text-ink">{t("estado.slo")}</h2>
          <p
            className={`mt-1 text-2xs ${
              slo.se_puede_desplegar === false ? "text-danger" : "text-ink-muted"
            }`}
            role="status"
          >
            {slo.que_significa ?? ""}
          </p>
          {/* Lo que NO se mide va delante y aparte: un servicio sin medición
              no está en verde, está sin mirar, y contarlo con los que cumplen
              es cómo un panel dice que todo va bien sobre media flota. */}
          {slo.sin_medicion?.length ? (
            <p className="mt-1 text-3xs text-warning">
              {t("estado.sinMedicion", { cuantos: slo.sin_medicion.length })}:{" "}
              {slo.sin_medicion.join(", ")}
            </p>
          ) : null}
          <ul className="mt-3 flex flex-wrap gap-2">
            {slo.servicios.map((s) => (
              <li
                key={s.servicio}
                className={`rounded-lg border px-3 py-2 ${
                  (slo.presupuesto_agotado_en ?? []).includes(s.servicio)
                    ? "border-danger/60 bg-danger/5"
                    : "border-ink-dim/60 bg-paper"
                }`}
              >
                <p className="text-2xs text-ink">{s.servicio}</p>
                <p className="text-3xs text-ink-faint">
                  {t("estado.objetivo", {
                    objetivo: s.objetivo_pct,
                    minutos: s.presupuesto_minutos,
                  })}
                </p>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {/* Lo que se lleva gastado de lo contratado. Con el reparto por módulo:
          «vais por el 80 %» no dice qué hacer; «el 80 % es almacenamiento de
          servicio» sí. */}
      {consumo?.metricas?.length ? (
        <>
          <h2 className="mt-8 text-sm font-medium text-ink">{t("estado.consumo")}</h2>
          <ul className="mt-2 divide-y divide-ink-dim/30">
            {consumo.metricas.map((m) => (
              <li key={m.metrica} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
                <span className="text-xs text-ink">{m.metrica}</span>
                <span className="text-sm font-medium text-ink">{m.consumido}</span>
                <span className="text-3xs text-ink-faint">
                  {Object.entries(m.por_modulo ?? {})
                    .filter(([, v]) => v > 0)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {/* Dos preguntas que sólo se hacen cuando algo huele mal, y que hasta
          ahora no tenían dónde hacerse: si lo que un servicio promete en sus
          eventos llega de verdad, y qué consultas van más lentas de lo que
          deberían. */}
      {contratos?.servicios || degradadas?.servicios ? (
        <>
          <h2 className="mt-8 text-sm font-medium text-ink">{t("estado.entreServicios")}</h2>
          {contratos?.servicios ? (
            <p className="mt-1 text-2xs text-ink-muted">
              {contratos.en_verde
                ? t("estado.contratosEnVerde")
                : t("estado.contratosRotos", {
                    cuantos: (contratos.incumplimientos ?? []).length,
                  })}
              {(contratos.sin_respuesta ?? []).length > 0
                ? ` · ${t("estado.sinRespuesta", {
                    cuantos: contratos.sin_respuesta.length,
                  })}`
                : ""}
            </p>
          ) : null}
          {degradadas?.servicios ? (
            <p className="mt-1 text-2xs text-ink-muted">
              {t("estado.degradadas", {
                cuantas: degradadas.servicios.reduce(
                  (n, s) => n + (s.consultas ?? []).length,
                  0,
                ),
              })}
              {degradadas.aviso ? ` · ${degradadas.aviso}` : ""}
            </p>
          ) : null}
        </>
      ) : null}

      <LaPresion presion={presion} />
      <LosFrenados frenados={frenados} />
    </>
  );
}

/**
 * Cuánto se está aplazando, y por culpa de quién (CRM-00.01.06.03, .04).
 *
 * Lo que se aplaza **no depende de la media, depende del que peor va**: con
 * un servicio ahogado y trece holgados, la media sale tranquila y lo no
 * crítico se está difiriendo igual. Por eso sale `peor` al lado del número.
 *
 * Y un servicio que no contesta no cuenta como holgado: sale aparte, porque
 * «nadie va apretado» y «no he podido preguntar a tres» se leen igual.
 */
function LaPresion({ presion }: { presion: Presion | null }) {
  const { t } = useTranslation();
  if (!presion) return null;
  const mudos = presion.sin_respuesta ?? [];
  return (
    <section className="card mt-4 p-4">
      <h2 className="text-sm font-medium text-ink">{t("estado.presion")}</h2>
      {!presion.medible ? (
        <p className="mt-2 text-2xs text-warning">
          {presion.aviso || t("estado.presionNoMedible")}
        </p>
      ) : (
        <>
          <p className="mt-2 font-mono text-lg text-ink">
            {t("estado.presionEs", { presion: presion.presion })}
          </p>
          {/* El que peor va, al lado: es quien decide lo que se aplaza. */}
          <p className="mt-1 text-2xs text-ink">
            {presion.peor
              ? t("estado.peorServicio", { servicio: presion.peor })
              : t("estado.nadieApretado")}
          </p>
          {presion.que_significa ? (
            <p className="mt-1 text-3xs text-ink-faint">{presion.que_significa}</p>
          ) : null}
        </>
      )}
      {mudos.length > 0 ? (
        <p className="mt-2 text-2xs text-warning">
          {t("estado.presionSinRespuesta", { cuantos: mudos.length })}
        </p>
      ) : null}
    </section>
  );
}

/**
 * A quién le ha bajado la cuota el freno automático (CRM-00.01.06.05).
 *
 * Esto se aplicaba y **no se veía**. Un cliente a un cuarto de su cuota, con
 * sus integraciones reintentando más fuerte porque les llega un 429, y la
 * única forma de enterarse era leer los registros del gateway.
 *
 * Se enseña también **cuántas ventanas se llevan observadas** de cada uno:
 * por debajo del mínimo no se evalúa a nadie, así que uno que está disparado
 * puede no salir frenado todavía — y eso, sin decirlo, parece un fallo del
 * freno.
 */
function LosFrenados({ frenados }: { frenados: Frenados | null }) {
  const { t } = useTranslation();
  if (!frenados) return null;
  const observados = frenados.observados ?? [];
  return (
    <section className="card mt-4 p-4">
      <h2 className="text-sm font-medium text-ink">{t("estado.frenados")}</h2>
      {/* Lo que ve ESTE proceso: con varias réplicas cada una tiene su parte,
          y una lista corta no significa que no haya nadie frenado. */}
      <p className="mt-1 text-3xs text-ink-faint">{frenados.porque_solo_estos}</p>
      {observados.length === 0 ? (
        <p className="mt-2 text-2xs text-ink-muted">{t("estado.nadieObservado")}</p>
      ) : (
        <ul className="lista-acotada mt-2 flex flex-col gap-1 pr-1">
          {observados.map((f) => (
            <li key={f.tenant_id} className="flex flex-wrap items-baseline gap-2">
              <span className="font-mono text-3xs text-ink">{f.tenant_id}</span>
              {f.frenado ? (
                <span className="badge badge-aviso">
                  {t("estado.aCuota", { pct: Math.round(f.factor_de_cuota * 100) })}
                </span>
              ) : (
                <span className="chip-dato">
                  {t("estado.observado", {
                    ventanas: f.ventanas_observadas,
                    minimo: frenados.minimo_ventanas,
                  })}
                </span>
              )}
              {f.frenado && f.motivo ? (
                <span className="w-full text-3xs text-ink-muted">{f.motivo}</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
