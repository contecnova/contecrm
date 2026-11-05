/**
 * Una lección: todo lo que pasó en la oportunidad y el post-mortem.
 *
 * Arriba lo que se apartó de las ganadas, con su número; después el expediente
 * entero —recorrido, cambios de rumbo, presupuestos, competencia, decisores y
 * actividad— y al final el post-mortem: la IA lo propone con el expediente
 * delante y quien llevaba la oportunidad lo corrige y lo firma.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { DatosClave } from "@/componentes/DatosClave";
import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { Formulario } from "@/componentes/Formulario";
import { Icono } from "@/componentes/Icono";
import { ErrorApi, llamar, salvoCancelacion } from "@/lib/api";
import type { CampoEsquema } from "@/lib/contrato";
import { fecha, importe, rotuloDeOpcion } from "@/lib/formato";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";
import { cn } from "@/lib/utiles";

interface Paso {
  cuando: string | null;
  desde: string | null;
  hasta: string | null;
  dias_en_la_anterior: number | null;
  importe: number | null;
  fecha_prevista: string | null;
}

interface Expediente {
  oportunidad: {
    id: string;
    nombre: string;
    importe: number | null;
    moneda: string;
    motivo_perdida: string | null;
    nota_perdida: string | null;
    competidor_ganador: string | null;
    creada: string | null;
    cerrada: string | null;
    dias_abierta: number | null;
  };
  recorrido: Paso[];
  cambios_de_rumbo: Record<string, number | null>;
  presupuestos: {
    numero: string;
    estado: string;
    enviado_el: string | null;
    total: number | null;
    descuento_pct: number | null;
    margen_pct: number | null;
  }[];
  competencia: {
    nombre: string;
    fortalezas: string | null;
    debilidades: string | null;
    gano: boolean;
  }[];
  decisores: {
    contacto_id: string;
    nombre?: string | null;
    cargo?: string | null;
    rol: string;
    postura: number | null;
    motivo: string | null;
  }[];
  actividad: {
    leida: boolean;
    total?: number;
    por_tipo?: Record<string, number>;
    ultima?: string | null;
    dias_sin_contacto_al_cerrar?: number | null;
    ultimas?: { tipo?: string; asunto?: string; cuando?: string | null }[];
    porque?: string;
  };
  comparado_con_las_ganadas: {
    comparable: boolean;
    ganadas: number;
    porque?: string;
    mediana_dias_hasta_cerrar?: number | null;
    mediana_dias_por_etapa?: Record<string, number | null>;
    mediana_descuento_pct?: number | null;
  };
  senales: { factor: string; texto: string }[];
}

interface Leccion {
  id: string;
  oportunidad_id: string;
  titulo: string;
  resultado: string;
  motivo: string | null;
  estado: string;
  obligatoria: boolean;
  que_paso: string | null;
  senal_temprana: string | null;
  que_hariamos_distinto: string | null;
  factores: string[];
  propuesta_ia: {
    que_paso?: string;
    senal_temprana?: string;
    que_hariamos_distinto?: string;
    factores?: string[];
  } | null;
  firmada_at: string | null;
  expediente: Expediente;
  factores_posibles: string[];
}

/** Un panel de la ficha, con la misma forma que los de la oportunidad. */
function Panel({
  titulo,
  children,
  className,
}: {
  titulo: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("card p-4", className)}>
      <h2 className="section-label mb-1">{titulo}</h2>
      {children}
    </section>
  );
}

/** Una fila de un panel: etiqueta a la izquierda, lo demás al lado. */
function Fila({ children }: { children: ReactNode }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 py-1.5 text-dato">
      {children}
    </li>
  );
}

function campoTexto(
  nombre: string,
  titulo: string,
  obligatorio: boolean,
): CampoEsquema {
  return {
    nombre,
    tipo: "texto_largo",
    obligatorio,
    titulo,
    descripcion: "",
    opciones: [],
    maximo: null,
    formato: "",
    subcampos: [],
    referencia: "",
  } as CampoEsquema;
}

export function Leccion() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [leccion, setLeccion] = useState<Leccion | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);
  // El borrador que se enseña en el formulario, y una versión para que el
  // formulario vuelva a empezar con él cuando la IA propone uno nuevo.
  const [borrador, setBorrador] = useState<Record<string, unknown>>({});
  const [version, setVersion] = useState(0);
  const [trabajando, setTrabajando] = useState<"" | "proponer" | "firmar">("");
  const modulo = moduloDe("lecciones");
  const recurso = modulo ? recursoDe(modulo, "leccion") : undefined;

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<Leccion>(`/api/v1/lecciones/${id}`, { signal: control.signal })
      .then((r) => {
        setLeccion(r.datos);
        const p = r.datos.propuesta_ia ?? {};
        setBorrador({
          que_paso: r.datos.que_paso ?? p.que_paso ?? "",
          senal_temprana: r.datos.senal_temprana ?? p.senal_temprana ?? "",
          que_hariamos_distinto:
            r.datos.que_hariamos_distinto ?? p.que_hariamos_distinto ?? "",
          factores: r.datos.factores.length
            ? r.datos.factores
            : (p.factores ?? []),
        });
        setVersion((v) => v + 1);
      })
      .catch(
        salvoCancelacion((e) => setFallo(e instanceof ErrorApi ? e : null)),
      );
    return () => control.abort();
  }, [id]);
  useEffect(cargar, [cargar]);

  async function proponer() {
    setTrabajando("proponer");
    try {
      const r = await llamar<{
        propuesta: NonNullable<Leccion["propuesta_ia"]>;
      }>(`/api/v1/lecciones/${id}/proponer`, { metodo: "POST" });
      const p = r.datos.propuesta;
      setBorrador({
        que_paso: p.que_paso ?? "",
        senal_temprana: p.senal_temprana ?? "",
        que_hariamos_distinto: p.que_hariamos_distinto ?? "",
        factores: p.factores ?? [],
      });
      setVersion((v) => v + 1);
    } catch (e) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      setTrabajando("");
    }
  }

  async function firmar(valores: Record<string, unknown>) {
    setTrabajando("firmar");
    setBorrador(valores);
    try {
      await llamar(`/api/v1/lecciones/${id}/firmar`, {
        metodo: "POST",
        cuerpo: { factores: [], ...valores },
      });
      setFallo(null);
      cargar();
    } catch (e) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      setTrabajando("");
    }
  }

  if (fallo && !leccion) return <Fallo error={fallo} />;
  if (!leccion) return <Cargando />;
  const ex = leccion.expediente;
  const op = ex.oportunidad;
  const ref = ex.comparado_con_las_ganadas;
  const firmada = leccion.estado === "firmada";

  const perdida = leccion.resultado === "perdida";
  const campos: CampoEsquema[] = [
    campoTexto("que_paso", t("leccion.quePaso"), true),
    campoTexto("senal_temprana", t("leccion.senalTemprana"), false),
    // Obligatorio en las perdidas, como lo exige el servidor al firmar.
    campoTexto("que_hariamos_distinto", t("leccion.queHariamos"), perdida),
    {
      ...campoTexto("factores", t("leccion.factores"), false),
      tipo: "lista_multiple",
      opciones: leccion.factores_posibles,
    } as CampoEsquema,
  ];

  return (
    <>
      {/* La cabecera de todas las fichas: de dónde viene, qué es y sus datos
          clave, que son las columnas de la lista. */}
      <DatosClave
        recurso={recurso}
        tipo="leccion"
        nombre={op.nombre || leccion.titulo}
        fila={leccion as unknown as Record<string, unknown>}
        volverA={{ a: "/m/lecciones", titulo: modulo?.titulo ?? "", id }}
        distintivos={
          <>
            {/* El resultado no va aquí: es un dato clave y sale debajo. Sí lo
                que no dice ninguna columna: que la firma es obligatoria, y
                contra quién se perdió. */}
            {!firmada && leccion.obligatoria ? (
              <span className="chip-dato chip-dato--aviso">
                {t("leccion.firmaObligatoria")}
              </span>
            ) : null}
            {op.competidor_ganador ? (
              <span className="chip-dato">
                {t("leccion.gano")}: {op.competidor_ganador}
              </span>
            ) : null}
          </>
        }
        acciones={
          <Link
            to={`/m/oportunidades/oportunidad/${leccion.oportunidad_id}`}
            className="btn-secondary"
          >
            {t("leccion.verOportunidad")}
          </Link>
        }
      />

      <Panel
        titulo={t("leccion.senales")}
        className={cn("mb-4", ex.senales.length > 0 && "border-warning/50")}
      >
        {ex.senales.length === 0 ? (
          <p className="text-dato text-ink-muted">{t("leccion.sinSenales")}</p>
        ) : (
          <ul className="divide-y divide-ink-dim/30">
            {ex.senales.map((s, i) => (
              <Fila key={i}>
                <span className="chip-dato">{rotuloDeOpcion(s.factor)}</span>
                <span className="text-ink">{s.texto}</span>
              </Fila>
            ))}
          </ul>
        )}
        {op.nota_perdida ? (
          <p className="mt-2 border-t border-ink-dim/30 pt-2 text-dato text-ink">
            {op.nota_perdida}
          </p>
        ) : null}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel titulo={t("leccion.postmortem")} className="lg:col-span-2">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="text-rotulo text-ink-faint">
              {firmada
                ? t("leccion.firmadaPor", { fecha: fecha(leccion.firmada_at) })
                : t("leccion.postmortemDetalle")}
            </p>
            {!firmada ? (
              <button
                type="button"
                className="btn-secondary"
                disabled={trabajando !== ""}
                onClick={() => void proponer()}
              >
                <Icono nombre="auto_awesome" tamano="sm" />
                {trabajando === "proponer"
                  ? t("leccion.proponiendo")
                  : t("leccion.proponer")}
              </button>
            ) : null}
          </div>
          {firmada ? (
            <dl className="grid gap-x-6 gap-y-2 md:grid-cols-2">
              {(
                [
                  ["que_paso", "quePaso"],
                  ["senal_temprana", "senalTemprana"],
                  ["que_hariamos_distinto", "queHariamos"],
                ] as const
              ).map(([k, rotulo]) => (
                <div key={k}>
                  <dt className="text-rotulo text-ink-faint">
                    {t(`leccion.${rotulo}`)}
                  </dt>
                  <dd className="whitespace-pre-wrap text-dato text-ink">
                    {leccion[k] || "—"}
                  </dd>
                </div>
              ))}
              <div>
                <dt className="text-rotulo text-ink-faint">
                  {t("leccion.factores")}
                </dt>
                <dd className="mt-0.5 flex flex-wrap gap-1">
                  {leccion.factores.map((f) => (
                    <span key={f} className="chip-dato">
                      {rotuloDeOpcion(f)}
                    </span>
                  ))}
                </dd>
              </div>
            </dl>
          ) : (
            <>
              {/* Se anuncia: al pulsar «Proponer con IA» el formulario se rellena
                  solo, y quien no ve la pantalla tiene que enterarse. */}
              <p role="status" className="mb-2 text-rotulo text-ink-faint">
                {leccion.propuesta_ia || version > 1
                  ? t("leccion.propuestaIA")
                  : ""}
              </p>
              <Formulario
                key={version}
                campos={campos}
                valores={borrador}
                enviando={trabajando === "firmar"}
                textoEnviar={t("leccion.firmar")}
                alEnviar={(v) => void firmar(v)}
                fallo={fallo}
              />
            </>
          )}
        </Panel>

        <Panel titulo={t("leccion.recorrido")}>
          <ul className="divide-y divide-ink-dim/30">
            {ex.recorrido.map((p, i) => {
              const normal = p.desde
                ? ref.mediana_dias_por_etapa?.[p.desde]
                : null;
              const lento =
                normal != null &&
                p.dias_en_la_anterior != null &&
                p.dias_en_la_anterior >= 2 * normal;
              return (
                <Fila key={i}>
                  <span className="w-24 shrink-0 text-ink-faint">
                    {fecha(p.cuando)}
                  </span>
                  <span className="font-medium text-ink">{p.hasta ?? "—"}</span>
                  {p.dias_en_la_anterior != null ? (
                    <span
                      className={cn("chip-dato", lento && "chip-dato--aviso")}
                    >
                      {t("leccion.diasEn", {
                        n: p.dias_en_la_anterior,
                        etapa: p.desde ?? "",
                      })}
                    </span>
                  ) : null}
                  {normal != null ? (
                    <span className="text-rotulo text-ink-faint">
                      {t("leccion.enLasGanadas", { n: normal })}
                    </span>
                  ) : null}
                  {p.importe != null ? (
                    <span className="ml-auto text-ink-muted">
                      {importe(p.importe, op.moneda)}
                    </span>
                  ) : null}
                </Fila>
              );
            })}
          </ul>
          <ul className="mt-2 flex flex-wrap gap-2 border-t border-ink-dim/30 pt-2 text-rotulo">
            <li className="chip-dato">
              {t("leccion.fechaMovida")}:{" "}
              {ex.cambios_de_rumbo.veces_que_se_movio_la_fecha ?? 0}
            </li>
            <li className="chip-dato">
              {t("leccion.fechaRetrasada")}:{" "}
              {ex.cambios_de_rumbo.veces_que_se_retraso ?? 0}
            </li>
            <li className="chip-dato">
              {t("leccion.importeCambiado")}:{" "}
              {ex.cambios_de_rumbo.veces_que_cambio_el_importe ?? 0}
            </li>
          </ul>
        </Panel>

        <Panel titulo={t("leccion.ganadasRef")}>
          {ref.comparable ? (
            <ul className="divide-y divide-ink-dim/30">
              <Fila>
                <span className="text-ink-muted">
                  {t("leccion.sobreGanadas", { n: ref.ganadas })}
                </span>
              </Fila>
              <Fila>
                <span className="text-ink">
                  {t("leccion.medianaDias", {
                    n: ref.mediana_dias_hasta_cerrar ?? "—",
                  })}
                </span>
                <span className="chip-dato">
                  {t("leccion.estaTardo", { n: op.dias_abierta ?? "—" })}
                </span>
              </Fila>
              <Fila>
                <span className="text-ink">
                  {t("leccion.medianaDescuento", {
                    n: ref.mediana_descuento_pct ?? "—",
                  })}
                </span>
              </Fila>
            </ul>
          ) : (
            <p className="text-dato text-ink-muted">{ref.porque}</p>
          )}
        </Panel>

        <Panel titulo={t("leccion.presupuestos")}>
          {ex.presupuestos.length === 0 ? (
            <p className="text-dato text-ink-muted">
              {t("leccion.sinPresupuestos")}
            </p>
          ) : (
            <ul className="divide-y divide-ink-dim/30">
              {ex.presupuestos.map((p) => (
                <Fila key={p.numero}>
                  <span className="font-mono text-rotulo text-ink">
                    {p.numero}
                  </span>
                  <span className="chip-dato">{rotuloDeOpcion(p.estado)}</span>
                  <span className="text-ink-faint">{fecha(p.enviado_el)}</span>
                  {p.descuento_pct != null ? (
                    <span className="chip-dato">-{p.descuento_pct} %</span>
                  ) : null}
                  {p.margen_pct != null ? (
                    <span className="text-rotulo text-ink-faint">
                      {t("leccion.margen", { n: p.margen_pct })}
                    </span>
                  ) : null}
                  <span className="ml-auto text-ink">
                    {p.total != null ? importe(p.total, op.moneda) : "—"}
                  </span>
                </Fila>
              ))}
            </ul>
          )}
        </Panel>

        <Panel titulo={t("leccion.competencia")}>
          {ex.competencia.length === 0 ? (
            <p className="text-dato text-ink-muted">
              {t("leccion.sinCompetencia")}
            </p>
          ) : (
            <ul className="divide-y divide-ink-dim/30">
              {ex.competencia.map((c) => (
                <Fila key={c.nombre}>
                  <span className="font-medium text-ink">{c.nombre}</span>
                  {c.gano ? (
                    <span className="chip-dato chip-dato--mal">
                      {t("leccion.gano")}
                    </span>
                  ) : null}
                  {c.fortalezas ? (
                    <span className="w-full text-rotulo text-ink-muted">
                      + {c.fortalezas}
                    </span>
                  ) : null}
                  {c.debilidades ? (
                    <span className="w-full text-rotulo text-ink-muted">
                      − {c.debilidades}
                    </span>
                  ) : null}
                </Fila>
              ))}
            </ul>
          )}
        </Panel>

        <Panel titulo={t("leccion.decisores")}>
          {ex.decisores.length === 0 ? (
            <p className="text-dato text-ink-muted">
              {t("leccion.sinDecisores")}
            </p>
          ) : (
            <ul className="divide-y divide-ink-dim/30">
              {ex.decisores.map((d) => (
                <Fila key={d.contacto_id + d.rol}>
                  <Link
                    to={`/m/cuentas/contacto/${d.contacto_id}`}
                    className="font-medium text-accent hover:underline"
                  >
                    {/* Sin la clave, es un expediente congelado antes de que
                        guardara el nombre; con ella vacía, party no lo dio. */}
                    {d.nombre ||
                      t(
                        d.nombre === undefined
                          ? "leccion.verContacto"
                          : "leccion.sinNombre",
                      )}
                  </Link>
                  <span className="chip-dato">{rotuloDeOpcion(d.rol)}</span>
                  {d.cargo ? (
                    <span className="text-rotulo text-ink-faint">
                      {d.cargo}
                    </span>
                  ) : null}
                  {d.postura ? (
                    <span
                      className={cn(
                        "chip-dato",
                        d.postura < 0 ? "chip-dato--mal" : "chip-dato--si",
                      )}
                    >
                      {t(d.postura < 0 ? "leccion.enContra" : "leccion.aFavor")}
                    </span>
                  ) : null}
                  {d.motivo ? (
                    <span className="w-full text-rotulo text-ink-muted">
                      {d.motivo}
                    </span>
                  ) : null}
                </Fila>
              ))}
            </ul>
          )}
        </Panel>

        <Panel titulo={t("leccion.actividad")}>
          {!ex.actividad.leida || !ex.actividad.total ? (
            <p className="text-dato text-ink-muted">
              {ex.actividad.porque ?? t("leccion.sinActividad")}
            </p>
          ) : (
            <>
              <ul className="flex flex-wrap gap-2 text-rotulo">
                <li className="chip-dato">
                  {t("leccion.actividadTotal", { n: ex.actividad.total })}
                </li>
                {Object.entries(ex.actividad.por_tipo ?? {}).map(([k, n]) => (
                  <li key={k} className="chip-dato">
                    {rotuloDeOpcion(k)} {n}
                  </li>
                ))}
                {ex.actividad.dias_sin_contacto_al_cerrar != null ? (
                  <li
                    className={cn(
                      "chip-dato",
                      ex.actividad.dias_sin_contacto_al_cerrar >= 14 &&
                        "chip-dato--aviso",
                    )}
                  >
                    {t("leccion.diasSinContacto", {
                      n: ex.actividad.dias_sin_contacto_al_cerrar,
                    })}
                  </li>
                ) : null}
              </ul>
              <ul className="mt-2 divide-y divide-ink-dim/30">
                {(ex.actividad.ultimas ?? []).map((a, i) => (
                  <Fila key={i}>
                    <span className="w-24 shrink-0 text-ink-faint">
                      {fecha(a.cuando ?? null)}
                    </span>
                    <span className="chip-dato">
                      {rotuloDeOpcion(a.tipo ?? "")}
                    </span>
                    <span className="text-ink">{a.asunto}</span>
                  </Fila>
                ))}
              </ul>
            </>
          )}
        </Panel>
      </div>
    </>
  );
}
