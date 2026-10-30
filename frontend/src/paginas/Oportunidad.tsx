/**
 * La ficha de una oportunidad, con lo que hace falta para cerrarla
 * (CRM-03.01.01.05, CRM-03.01.01.06, CRM-03.01.01.08, CRM-03.01.01.10,
 * CRM-03.01.01.11, CRM-03.01.01.13, CRM-03.01.02.02, CRM-03.01.02.03,
 * CRM-03.01.02.05).
 *
 * Lo que había era la ficha genérica: un volcado de campos. Con eso delante no
 * se contesta «¿cómo vamos con esta venta?», que es para lo que se abre.
 *
 * Mismo reparto que la ficha de cliente, a propósito: arriba lo que identifica
 * y el estado, a la izquierda el dinero, a la derecha quién decide y de dónde
 * viene. Dos pantallas que enseñan el mismo tipo de cosa lo colocan igual, o
 * hay que volver a aprenderlas al cambiar de una a otra.
 *
 * **Tres de estos paneles enseñan cosas que se guardaban y no leía nadie.** El
 * reparto entre comerciales y las oportunidades relacionadas vivían en su
 * tabla, consultadas sólo por su propio escritor para reemplazar filas: se
 * podía declarar quién se lleva qué parte de una comisión y no había forma de
 * comprobarlo hasta que llegaba la liquidación.
 *
 * **Tres paneles más, del mismo registro y por eso aquí.** La metodología dice
 * qué falta para poder cerrar y cuál es el siguiente paso —una puntuación sin
 * el «lo que falta» al lado es una nota, no una guía—; el playbook dice qué
 * hacer en ESTA etapa, que es lo que convierte la metodología en trabajo; y el
 * plan conjunto con el cliente separa **lo retrasado nuestro de lo retrasado
 * suyo**, que es la única distinción que cambia a quién se llama.
 *
 * **Y el ARR no se calcula aquí.** Las líneas se mandan al servicio que sabe
 * qué cuenta como recurrente y qué no, y lo que vuelve se pinta. Calcularlo en
 * la pantalla dividiendo el total entre los años mete la implantación dentro y
 * la métrica con la que se valora la empresa sale inflada — y entonces hay dos
 * sitios donde se calcula, que acaban diciendo cosas distintas.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import {
  BotonesDeRegistro,
  ConfirmarBorrado,
  FormularioDeEdicion,
  useEdicion,
} from "@/componentes/Edicion";
import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { listar } from "@/lib/listados";
import { importe as comoImporte } from "@/lib/formato";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";

interface Oportunidad {
  id: string;
  codigo: string | null;
  nombre: string;
  cuenta_id: string | null;
  pipeline: string | null;
  etapa: string | null;
  importe: string;
  moneda: string;
  probabilidad: number;
  importe_ponderado: string;
  fecha_cierre: string | null;
  estado: string;
  categoria_forecast: string | null;
  etapa_desde: string | null;
  bloqueada: boolean;
}

interface Linea {
  id: string;
  descripcion: string;
  cantidad: string;
  precio_unitario: string;
  descuento_pct: string;
  total: string;
  /** `tipo_ingreso` en el servidor. Se llamaba `tipo` aquí y nadie lo mandaba. */
  tipo_ingreso?: string;
}

interface Metricas {
  arr: string;
  mrr: string;
  tcv: string;
  acv: string;
  puntual: string;
  hay_recurrente: boolean;
  porque: string;
  lo_que_no_cuenta_como_arr: string[];
}

interface Reparto {
  reparto: { usuario_id: string; papel: string; porcentaje: string; motivo: string }[];
  credito_total: string;
  credito_cuadra: boolean;
  porque_el_overlay_no_suma: string;
  relacionadas: { tipo: string; sentido: string; otra_id: string }[];
}

interface GrupoDeCompra {
  roles: Record<string, { contacto_id: string; postura: number; motivo: string; hablado: boolean }[]>;
  faltan_por_identificar: string[];
  clave_sin_hablar: string[];
  en_contra: number;
  completo: boolean;
  que_mirar: string;
}

interface Metodologia {
  id: string;
  clave: string;
  nombre: string;
  activa: boolean;
}

interface Evaluacion {
  puntuacion: number;
  criterios: number;
  cubiertos: number;
  /** Una puntuación sin esto al lado es una nota, no una guía. */
  lo_que_falta: string[];
  siguiente_paso: string;
  cualificada: boolean;
}

interface Playbook {
  clave: string;
  titulo: string;
  pasos: string[];
  por_que: string;
}

interface Plan {
  id: string;
  oportunidad_id: string;
  fecha_objetivo: string | null;
}

interface EstadoDelPlan {
  pasos: number;
  hechos: number;
  /** Las tres por separado: es lo único que cambia a quién se llama. */
  retrasados_nuestros: unknown[];
  retrasados_del_cliente: unknown[];
  retrasados_conjuntos: unknown[];
  compartido: boolean;
  visto_por_el_cliente: string | null;
  la_fecha_es_creible: boolean;
  que_significa: string;
  aviso: string;
}

interface CambioDePrevision {
  campo: string;
  anterior: string | null;
  nuevo: string | null;
  dias_deslizados: number | null;
  delta_importe: string | null;
  motivo: string | null;
  at: string;
}

export function Oportunidad() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [op, setOp] = useState<Oportunidad | null>(null);
  const [lineas, setLineas] = useState<Linea[]>([]);
  const [metricas, setMetricas] = useState<Metricas | null>(null);
  const [reparto, setReparto] = useState<Reparto | null>(null);
  const [grupo, setGrupo] = useState<GrupoDeCompra | null>(null);
  const [deslizamientos, setDeslizamientos] = useState<CambioDePrevision[]>([]);
  const [evaluacion, setEvaluacion] = useState<Evaluacion | null>(null);
  const [playbook, setPlaybook] = useState<Playbook | null>(null);
  const [plan, setPlan] = useState<EstadoDelPlan | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const navegar = useNavigate();
  /**
   * El mismo recurso que el listado, y no una ruta escrita a mano.
   *
   * Dos pantallas que enseñan el mismo registro tienen que escribirlo igual,
   * o una de las dos se queda atrás el día que cambie el contrato.
   */
  const modulo = moduloDe("oportunidades");
  const recurso = modulo ? recursoDe(modulo, "oportunidad") : undefined;
  const { ruta, puedeEditar, puedeBorrar } = useEdicion(recurso, id);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Oportunidad>(`/api/v1/opportunities/${id}`, { signal: control.signal })
      .then((r) => setOp(r.datos))
      .catch(salvoCancelacion(setFallo));

    // Cada panel con su propio fallo: que no responda el histórico de
    // previsión no puede dejar sin ver las líneas, que es a lo que se entra.
    listar<Linea>(`/api/v1/opportunities/${id}/lineas`, { signal: control.signal })
      .then((suyas) => {
        setLineas(suyas);
        // Las métricas las calcula el servicio que sabe qué es recurrente, con
        // las líneas de verdad. Sin líneas no se pregunta: contestaría ceros y
        // un ARR de cero se lee como «no factura», no como «no hay líneas».
        if (suyas.length > 0) {
          void llamar<Metricas>("/api/v1/ingresos/metricas", {
            metodo: "POST",
            cuerpo: { lineas: suyas },
            signal: control.signal,
          })
            .then((m) => setMetricas(m.datos))
            .catch(() => undefined);
        }
      })
      .catch(() => undefined);

    void llamar<Reparto>(`/api/v1/ingresos/de/${id}`, { signal: control.signal })
      .then((r) => setReparto(r.datos))
      .catch(() => undefined);
    void llamar<GrupoDeCompra>(`/api/v1/ingresos/grupo-compra/${id}`, {
      signal: control.signal,
    })
      .then((r) => setGrupo(r.datos))
      .catch(() => undefined);
    void llamar<CambioDePrevision[]>(
      `/api/v1/forecast/oportunidades/${id}/historial-prevision`,
      { signal: control.signal },
    )
      .then((r) => setDeslizamientos(r.datos))
      .catch(() => undefined);

    // La metodología ACTIVA, no una cualquiera: evaluar con una retirada daría
    // una puntuación contra criterios que ya no se aplican.
    void listar<Metodologia>("/api/v1/metodologias?activa=true", {
      signal: control.signal,
    })
      .then((metodologias) => {
        const activa = metodologias[0];
        if (!activa) return;
        void llamar<Evaluacion>(
          `/api/v1/metodologias/${activa.id}/oportunidad/${id}`,
          { signal: control.signal },
        )
          .then((r) => setEvaluacion(r.datos))
          .catch(() => undefined);
      })
      .catch(() => undefined);

    // El plan conjunto se busca por su oportunidad: puede no haberlo, y no
    // tenerlo es una respuesta —no se ha acordado nada con el cliente—.
    void listar<Plan>(`/api/v1/planes-conjuntos?oportunidad_id=${id}`, {
      signal: control.signal,
    })
      .then((planes) => {
        const suyo = planes[0];
        if (!suyo) return;
        void llamar<EstadoDelPlan>(`/api/v1/planes-conjuntos/${suyo.id}/estado`, {
          signal: control.signal,
        })
          .then((r) => setPlan(r.datos))
          .catch(() => undefined);
      })
      .catch(() => undefined);

    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  // El playbook de SU etapa, y en su propio efecto: uno genérico no es un
  // playbook, es una lista. Va aparte porque depende de la etapa, que llega
  // con la oportunidad — pedirlo dentro de `cargar` obligaría a pedir la
  // oportunidad dos veces.
  const etapa = op?.etapa ?? "";
  useEffect(() => {
    if (!etapa) return undefined;
    const control = new AbortController();
    void llamar<Playbook>(
      `/api/v1/metodologias/playbook?etapa=${encodeURIComponent(etapa)}`,
      { signal: control.signal },
    )
      .then((r) => setPlaybook(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, [etapa]);

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/m/oportunidades");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !op) return <Fallo error={fallo} reintentar={cargar} />;
  if (!op) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={op.nombre}
        icono="monetization_on"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            {op.codigo ? <span className="badge badge-muted">{op.codigo}</span> : null}
            <span className="chip-dato">{op.etapa ?? t("oportunidad.sinEtapa")}</span>
            <span className="chip-dato">{op.estado}</span>
            {op.categoria_forecast ? (
              <span className="chip-dato">{op.categoria_forecast}</span>
            ) : null}
            {op.bloqueada ? (
              <span className="chip-dato chip-dato--no">{t("oportunidad.bloqueada")}</span>
            ) : null}
          </span>
        }
      />

      {/* Editar y borrar primero: lo que más se busca en una ficha abierta es
          cambiar un dato que está mal. */}
      {!editando ? (
        <div className="mb-3">
          <BotonesDeRegistro
            puedeEditar={puedeEditar}
            puedeBorrar={puedeBorrar}
            alEditar={() => setEditando(true)}
            alBorrar={() => setConfirmando(true)}
          />
        </div>
      ) : null}

      {confirmando ? (
        <ConfirmarBorrado
          enviando={borrando}
          alBorrar={() => void borrar()}
          alCancelar={() => setConfirmando(false)}
        />
      ) : null}

      {editando && recurso ? (
        <FormularioDeEdicion
          recurso={recurso}
          ruta={ruta}
          valores={op as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      <section className="card mb-4 p-4">
        <p className="text-sm font-medium text-ink">
          {comoImporte(op.importe, op.moneda)} ·{" "}
          {t("oportunidad.ponderado", {
            valor: comoImporte(op.importe_ponderado, op.moneda),
            pct: op.probabilidad,
          })}
        </p>
        {op.fecha_cierre ? (
          <p className="mt-1 text-2xs text-ink-muted">
            {t("oportunidad.cierrePrevisto", { fecha: op.fecha_cierre })}
          </p>
        ) : null}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <LasLineas lineas={lineas} metricas={metricas} moneda={op.moneda} />
        <QuienDecide grupo={grupo} />
        <QuienSeLoLleva reparto={reparto} />
        <LoQueSeHaMovido cambios={deslizamientos} />
        <QueFaltaParaCerrar evaluacion={evaluacion} playbook={playbook} />
        <ElPlanConElCliente plan={plan} />
      </div>
    </>
  );
}

/**
 * Las líneas y lo que se puede decir de ellas (CRM-03.01.01.05, .01.06).
 *
 * El ARR va **con su porqué y con lo que ha dejado fuera**: «ARR 120.000» sin
 * decir que la implantación no cuenta es el número que acaba en una valoración
 * y nadie vuelve a mirar cómo se calculó.
 */
function LasLineas({
  lineas,
  metricas,
  moneda,
}: {
  lineas: Linea[];
  metricas: Metricas | null;
  moneda: string;
}) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.lineas")}</h2>
      {lineas.length === 0 ? (
        <Vacio titulo={t("oportunidad.sinLineas")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {lineas.map((l) => (
            <li key={l.id} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
              <span className="text-2xs font-medium text-ink">{l.descripcion}</span>
              <span className="text-3xs text-ink-faint">
                {t("oportunidad.porUnidad", {
                  cantidad: l.cantidad,
                  precio: comoImporte(l.precio_unitario, moneda),
                })}
              </span>
              {Number(l.descuento_pct) > 0 ? (
                <span className="chip-dato">-{l.descuento_pct} %</span>
              ) : null}
              <span className="text-2xs text-ink-muted">{comoImporte(l.total, moneda)}</span>
            </li>
          ))}
        </ul>
      )}

      {metricas ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-2">
          <h3 className="text-2xs font-medium text-ink">{t("oportunidad.metricas")}</h3>
          <ul className="mt-1 flex flex-wrap gap-2 text-3xs">
            <li className="chip-dato">ARR {comoImporte(metricas.arr, moneda)}</li>
            <li className="chip-dato">MRR {comoImporte(metricas.mrr, moneda)}</li>
            <li className="chip-dato">TCV {comoImporte(metricas.tcv, moneda)}</li>
            <li className="chip-dato">ACV {comoImporte(metricas.acv, moneda)}</li>
          </ul>
          {/* Lo que NO cuenta como ARR, dicho. Sin esto, el número se cita en
              un comité como si fuera todo lo que entra. */}
          {metricas.lo_que_no_cuenta_como_arr.length > 0 ? (
            <p className="mt-1 text-3xs text-ink-muted">
              {t("oportunidad.noCuentaComoArr", {
                tipos: metricas.lo_que_no_cuenta_como_arr.join(", "),
                puntual: comoImporte(metricas.puntual, moneda),
              })}
            </p>
          ) : null}
          <p className="mt-1 text-3xs text-ink-faint">{metricas.porque}</p>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Quién decide, y a quién no se ha visto (CRM-03.01.01.10).
 *
 * Lo útil no es la lista: es **lo que falta**. Una oportunidad sin decisor
 * identificado no está avanzada por mucho que el presupuesto esté mandado, y
 * un económico con el que nadie ha hablado es la razón más habitual de que un
 * cierre «seguro» se caiga la última semana.
 */
function QuienDecide({ grupo }: { grupo: GrupoDeCompra | null }) {
  const { t } = useTranslation();
  if (!grupo) return null;
  const roles = Object.entries(grupo.roles);

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.quienDecide")}</h2>
      {roles.length === 0 ? (
        <Vacio titulo={t("oportunidad.sinRoles")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {roles.map(([rol, gente]) => (
            <li key={rol} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
              <span className="text-2xs font-medium text-ink">{rol}</span>
              {gente.map((p) => (
                <span
                  key={p.contacto_id}
                  className={p.hablado ? "chip-dato chip-dato--si" : "chip-dato chip-dato--no"}
                >
                  {p.hablado ? t("oportunidad.hablado") : t("oportunidad.sinHablar")}
                  {p.postura < 0 ? ` · ${t("oportunidad.enContra")}` : ""}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
      {/* Lo que falta, en ámbar: es la mitad que hace útil este panel. */}
      <p
        className={
          grupo.completo ? "mt-2 text-2xs text-success" : "mt-2 text-2xs text-warning"
        }
      >
        {grupo.que_mirar}
      </p>
    </section>
  );
}

/**
 * Quién se lleva esto, y de dónde viene (CRM-03.01.01.08, CRM-03.01.01.11).
 *
 * Las dos cosas que se guardaban y no leía nadie. El crédito sale **con su
 * total y con si cuadra**: un reparto al 60/60 cuadra hacia arriba y el
 * descuadre lo encuentra finanzas tres meses después.
 */
function QuienSeLoLleva({ reparto }: { reparto: Reparto | null }) {
  const { t } = useTranslation();
  if (!reparto) return null;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.reparto")}</h2>
      {reparto.reparto.length === 0 ? (
        <Vacio titulo={t("oportunidad.sinReparto")} compacto />
      ) : (
        <>
          <ul className="divide-y divide-ink-dim/30">
            {reparto.reparto.map((p) => (
              <li
                key={`${p.usuario_id}-${p.papel}`}
                className="flex flex-wrap items-baseline gap-x-3 py-1.5"
              >
                <span className="text-2xs font-medium text-ink">{p.porcentaje} %</span>
                <span className="chip-dato">{p.papel}</span>
                {p.motivo ? (
                  <span className="text-3xs text-ink-faint">{p.motivo}</span>
                ) : null}
              </li>
            ))}
          </ul>
          <p
            className={
              reparto.credito_cuadra
                ? "mt-2 text-2xs text-ink-muted"
                : "mt-2 text-2xs text-danger"
            }
          >
            {t("oportunidad.creditoTotal", { total: reparto.credito_total })}
            {reparto.credito_cuadra ? "" : ` · ${t("oportunidad.noCuadra")}`}
          </p>
          <p className="mt-1 text-3xs text-ink-faint">{reparto.porque_el_overlay_no_suma}</p>
        </>
      )}

      {reparto.relacionadas.length > 0 ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-2">
          <h3 className="text-2xs font-medium text-ink">{t("oportunidad.relacionadas")}</h3>
          <ul className="mt-1 space-y-1">
            {reparto.relacionadas.map((r) => (
              <li key={`${r.tipo}-${r.otra_id}`} className="text-3xs text-ink-muted">
                <span className="chip-dato">{r.tipo}</span>{" "}
                {/* El sentido: sin él, «renovación» no dice si ésta es la que
                    se renueva o la que renueva a otra, que en el informe de
                    crecimiento son cosas opuestas. */}
                {t(`oportunidad.sentido.${r.sentido}`)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Lo que se ha movido: importe y fecha (CRM-03.01.01.13).
 *
 * Una oportunidad que ha cambiado tres veces de fecha no es la misma que una
 * que nunca se movió, aunque hoy tengan el mismo importe y la misma etapa. El
 * deslizamiento se anota **con su motivo**, que es lo que convierte un
 * histórico en algo que se puede discutir en un comité.
 */
function LoQueSeHaMovido({ cambios }: { cambios: CambioDePrevision[] }) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.movimientos")}</h2>
      {cambios.length === 0 ? (
        <Vacio titulo={t("oportunidad.sinMovimientos")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {cambios.map((c, i) => (
            <li key={`${c.campo}-${c.at}-${i}`} className="py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-2 text-2xs">
                <span className="font-medium text-ink">{c.campo}</span>
                <span className="text-ink-faint">{c.anterior ?? "—"}</span>
                <Icono nombre="arrow_forward" tamano="sm" />
                <span className="text-ink-muted">{c.nuevo ?? "—"}</span>
                {c.dias_deslizados ? (
                  <span className="chip-dato chip-dato--no">
                    {t("oportunidad.deslizada", { dias: c.dias_deslizados })}
                  </span>
                ) : null}
                {c.delta_importe ? (
                  <span className="chip-dato">{c.delta_importe}</span>
                ) : null}
              </div>
              {c.motivo ? (
                <p className="text-3xs text-ink-faint">{c.motivo}</p>
              ) : (
                /* Un movimiento sin motivo es el que no se puede discutir.
                   Decirlo es lo que hace que la próxima vez se escriba. */
                <p className="text-3xs text-warning">{t("oportunidad.sinMotivo")}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Qué falta para poder cerrar, y qué hacer ahora
 * (CRM-03.01.02.02, CRM-03.01.02.03).
 *
 * **La puntuación va con «lo que falta» al lado, nunca sola.** Un «62 sobre
 * 100» es una nota: no dice qué hacer, así que no cambia nada. La lista de
 * criterios sin cubrir sí, y es lo que convierte la metodología en trabajo.
 *
 * Y el playbook es el de ESTA etapa. Uno genérico no es un playbook, es una
 * lista de buenas intenciones; por eso el servidor devuelve también **por qué**
 * eligió ése, que es lo único que hace que alguien se fíe del siguiente.
 */
function QueFaltaParaCerrar({
  evaluacion,
  playbook,
}: {
  evaluacion: Evaluacion | null;
  playbook: Playbook | null;
}) {
  const { t } = useTranslation();
  if (!evaluacion && !playbook) {
    return (
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("oportunidad.queFalta")}</h2>
        <Vacio titulo={t("oportunidad.sinMetodologia")} compacto />
      </section>
    );
  }

  const faltan = evaluacion?.lo_que_falta ?? [];

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.queFalta")}</h2>
      {evaluacion ? (
        <>
          <p className="font-mono text-2xs text-ink">
            {t("oportunidad.cubiertos", {
              cubiertos: evaluacion.cubiertos,
              criterios: evaluacion.criterios,
              puntuacion: evaluacion.puntuacion,
            })}
          </p>
          <p
            className={
              evaluacion.cualificada
                ? "mt-1 text-2xs text-success"
                : "mt-1 text-2xs text-warning"
            }
          >
            {t(
              evaluacion.cualificada
                ? "oportunidad.cualificada"
                : "oportunidad.noCualificada",
            )}
          </p>
          {/* Lo que falta, enumerado. La nota sola no cambia nada. */}
          {faltan.length > 0 ? (
            <ul className="mt-2 flex flex-col gap-1">
              {faltan.map((x, i) => (
                <li key={i} className="text-2xs text-ink">
                  {x}
                </li>
              ))}
            </ul>
          ) : null}
          {evaluacion.siguiente_paso ? (
            <p className="mt-2 text-2xs text-ink">
              {t("oportunidad.siguientePaso", { paso: evaluacion.siguiente_paso })}
            </p>
          ) : null}
        </>
      ) : null}

      {playbook ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-2">
          <p className="text-2xs font-medium text-ink">{playbook.titulo}</p>
          {/* El porqué del playbook: uno que aparece sin explicación se
              ignora, y entonces da igual que esté. */}
          <p className="mt-1 text-3xs text-ink-faint">{playbook.por_que}</p>
          <ul className="mt-1 flex flex-col gap-1">
            {(playbook.pasos ?? []).map((paso, i) => (
              <li key={i} className="text-2xs text-ink-muted">
                {paso}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/**
 * El plan conjunto con el cliente (CRM-03.01.02.05).
 *
 * **Lo retrasado nuestro y lo retrasado suyo van por separado**, y es la única
 * distinción de este panel que cambia algo: si vamos tarde nosotros se empuja
 * dentro de casa, y si va tarde el cliente la conversación es con él. Juntos
 * son «el plan va mal», que no se acciona.
 *
 * **Y un plan que el cliente no ha visto no es un plan conjunto**: es una
 * lista nuestra con su nombre encima. Por eso `compartido` y
 * `visto_por_el_cliente` salen delante de los pasos.
 */
function ElPlanConElCliente({ plan }: { plan: EstadoDelPlan | null }) {
  const { t } = useTranslation();
  if (!plan) {
    return (
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("oportunidad.planConjunto")}</h2>
        {/* No tenerlo es una respuesta: no se ha acordado nada con el cliente. */}
        <Vacio titulo={t("oportunidad.sinPlan")} compacto />
      </section>
    );
  }

  const nuestros = plan.retrasados_nuestros ?? [];
  const suyos = plan.retrasados_del_cliente ?? [];
  const conjuntos = plan.retrasados_conjuntos ?? [];

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.planConjunto")}</h2>
      {/* Si el cliente no lo ha visto, lo demás importa menos. */}
      <p
        className={
          plan.compartido ? "text-2xs text-ink-muted" : "text-2xs text-warning"
        }
      >
        {plan.compartido
          ? plan.visto_por_el_cliente
            ? t("oportunidad.planVisto", {
                fecha: new Date(plan.visto_por_el_cliente).toLocaleDateString(),
              })
            : t("oportunidad.planCompartidoSinVer")
          : t("oportunidad.planSinCompartir")}
      </p>
      <p className="mt-2 font-mono text-2xs text-ink">
        {t("oportunidad.pasosDelPlan", { hechos: plan.hechos, pasos: plan.pasos })}
      </p>
      {/* Los tres retrasos por separado. */}
      {nuestros.length > 0 ? (
        <p className="mt-1 text-2xs text-danger">
          {t("oportunidad.retrasoNuestro", { cuantos: nuestros.length })}
        </p>
      ) : null}
      {suyos.length > 0 ? (
        <p className="mt-1 text-2xs text-warning">
          {t("oportunidad.retrasoDelCliente", { cuantos: suyos.length })}
        </p>
      ) : null}
      {conjuntos.length > 0 ? (
        <p className="mt-1 text-2xs text-warning">
          {t("oportunidad.retrasoConjunto", { cuantos: conjuntos.length })}
        </p>
      ) : null}
      {/* Y si la fecha de cierre ya no se la cree ni el plan, se dice. */}
      {!plan.la_fecha_es_creible ? (
        <p className="mt-2 text-2xs text-danger">{t("oportunidad.fechaNoCreible")}</p>
      ) : null}
      {plan.aviso ? (
        <p className="mt-1 text-3xs text-ink-faint">{plan.aviso}</p>
      ) : null}
    </section>
  );
}
