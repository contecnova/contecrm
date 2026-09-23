/**
 * La ficha de un cliente, con la forma que tiene en el mercado.
 *
 * Salesforce y HubSpot llevan años convergiendo en el mismo reparto, y no por
 * copiarse: es lo que hace falta para trabajar con un cliente delante.
 *
 *   · Arriba, lo que identifica al cliente y **las acciones** que se hacen con
 *     él. Salesforce lo llama «highlights panel» y lo deja fijo al desplazar.
 *   · A la izquierda, los datos.
 *   · En el centro, **la línea de tiempo**: lo que ha pasado, en orden. Es la
 *     columna ancha porque es lo que se mira: quién llamó, qué se acordó, qué
 *     queda pendiente.
 *   · A la derecha, **lo relacionado**: contactos, oportunidades, casos.
 *
 * Lo que había antes era una ficha genérica que servía para cualquier objeto:
 * un volcado de campos y cuatro pestañas de adjuntos. Eso es un inspector de
 * registros, no la ficha de un cliente — con ella delante, un comercial no
 * puede contestar «¿cómo vamos con este cliente?», que es para lo que abre el
 * CRM.
 *
 * **Lo que no se sabe se dice.** Si la proyección de métricas no tiene el dato
 * de facturación, se escribe que no lo tiene: «cero incidencias» y «no tenemos
 * el dato de incidencias» se pintan igual y significan lo contrario.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { filas, llamar, salvoCancelacion } from "@/lib/api";
import { escalar, humanizar, importe } from "@/lib/formato";

interface Contacto360 {
  id: string;
  nombre: string;
  cargo: string | null;
  email: string | null;
  rol: string | null;
  principal: boolean;
  no_contactar: boolean;
}

interface Hito {
  tipo: string;
  asunto?: string;
  titulo?: string;
  momento?: string;
  fecha?: string;
  created_at?: string;
  [k: string]: unknown;
}

interface Metrica {
  clave: string;
  valor: string;
  unidad: string;
  moneda?: string | null;
  de_hace_dias: number;
  fresca: boolean;
  origen: string;
}

interface Vista360 {
  cuenta: {
    id: string;
    nombre: string;
    estado: string;
    roles: string[];
    sector: { esquema: string | null; codigo: string | null };
    calidad: { puntuacion: number; faltan: string[] };
    owner_id: string | null;
  };
  identificadores: { tipo: string; valor: string; verificado?: boolean }[];
  direcciones: Record<string, unknown>[];
  contactos: Contacto360[];
  timeline: Hito[];
  metricas: {
    metricas?: Metrica[];
    sin_dato?: string[];
    caducadas?: string[];
    completo?: boolean;
    que_significa?: string;
  };
}

interface Oportunidad {
  id: string;
  nombre: string;
  importe: string | number;
  moneda: string;
  estado: string;
  fecha_cierre: string | null;
}

interface Caso {
  id: string;
  codigo: string | null;
  asunto: string;
  estado: string;
  prioridad: string;
}

export function Cuenta() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [vista, setVista] = useState<Vista360 | null>(null);
  const [oportunidades, setOportunidades] = useState<Oportunidad[]>([]);
  const [casos, setCasos] = useState<Caso[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(
    (signal?: AbortSignal) => {
      llamar<Vista360>(`/api/v1/accounts/${id}/360`, { signal })
        .then((r) => setVista(r.datos))
        .catch(salvoCancelacion(setFallo));
      // Oportunidades y casos viven en otros servicios: se piden aparte y **su
      // fallo no tumba la ficha**. Que no responda soporte no puede dejar sin
      // ver los datos del cliente.
      // `estado=` vacío a propósito: la API filtra por abiertas de serie, y en
      // la ficha de un cliente eso esconde justo lo que se ganó con él. «Cómo
      // vamos con este cliente» incluye lo cerrado.
      llamar<unknown>(`/api/v1/opportunities?cuenta_id=${id}&estado=&limite=20`, { signal })
        .then((r) => setOportunidades(filas<Oportunidad>(r.datos)))
        .catch(() => undefined);
      llamar<unknown>(`/api/v1/casos?cuenta_id=${id}&limite=20`, { signal })
        .then((r) => setCasos(filas<Caso>(r.datos)))
        .catch(() => undefined);
    },
    [id],
  );

  useEffect(() => {
    const control = new AbortController();
    cargar(control.signal);
    return () => control.abort();
  }, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={() => cargar()} />;
  if (!vista) return <Cargando />;

  const { cuenta, contactos, timeline, identificadores, metricas } = vista;
  const nif = identificadores.find((i) => i.tipo === "nif")?.valor;

  return (
    <>
      <CabeceraPagina
        titulo={cuenta.nombre}
        icono="domain"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <span className="badge badge-muted">{cuenta.estado}</span>
            {cuenta.roles.map((r) => (
              <span key={r} className="chip-dato chip-dato--si">
                {r}
              </span>
            ))}
            {nif ? <span className="text-2xs text-ink-faint">{nif}</span> : null}
          </span>
        }
        acciones={
          <>
            <Link to={`/m/actividades?r=Actividades&nuevo=1`} className="btn-secondary">
              {t("cuenta.nuevaActividad")}
            </Link>
            <Link to={`/m/oportunidades?r=Oportunidades&nuevo=1`} className="btn-primary">
              {t("cuenta.nuevaOportunidad")}
            </Link>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)_minmax(0,19rem)]">
        {/* ── Datos ──────────────────────────────────────────────────── */}
        <aside className="space-y-4">
          <section className="card p-4">
            <h2 className="section-label mb-3">{t("cuenta.datos")}</h2>
            <dl className="space-y-2">
              <Dato clave="sector" valor={cuenta.sector.codigo} />
              <Dato clave="estado" valor={cuenta.estado} />
              {identificadores.map((i) => (
                <Dato key={i.valor} clave={i.tipo} valor={i.valor} />
              ))}
            </dl>
          </section>

          <section className="card p-4">
            <h2 className="section-label mb-2">{t("cuenta.calidad")}</h2>
            <p className="text-sm font-medium text-ink">{cuenta.calidad.puntuacion} / 100</p>
            {cuenta.calidad.faltan.length > 0 ? (
              <>
                {/* Qué falta, por su nombre. Una puntuación sin el detalle no
                    dice qué hay que hacer para subirla. */}
                <p className="mt-2 text-3xs text-ink-faint">{t("cuenta.faltan")}</p>
                <ul className="mt-1 flex flex-wrap gap-1">
                  {cuenta.calidad.faltan.map((f) => (
                    <li key={f} className="chip-dato">
                      {humanizar(f)}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </section>

          <section className="card p-4">
            <h2 className="section-label mb-2">{t("cuenta.metricas")}</h2>
            <Metricas datos={metricas} />
          </section>
        </aside>

        {/* ── Lo que ha pasado ───────────────────────────────────────── */}
        <section className="card p-4" aria-labelledby="cuenta-timeline">
          <h2 id="cuenta-timeline" className="section-label mb-3">
            {t("cuenta.timeline")}
          </h2>
          {timeline.length === 0 ? (
            <Vacio
              compacto
              icono="history"
              titulo={t("cuenta.sinTimeline")}
            />
          ) : (
            <ol className="relative space-y-4 border-l border-ink-dim/60 pl-4">
              {timeline.map((h, i) => (
                <li key={i} className="relative">
                  <span
                    aria-hidden
                    className="absolute -left-[1.4rem] top-1.5 h-2 w-2 rounded-full bg-accent"
                  />
                  <p className="text-xs text-ink">
                    {String(h.asunto ?? h.titulo ?? h.tipo ?? "")}
                  </p>
                  <p className="mt-0.5 text-3xs text-ink-faint">
                    {humanizar(String(h.tipo ?? ""))}
                    {h.momento || h.fecha || h.created_at
                      ? ` · ${escalar(h.momento ?? h.fecha ?? h.created_at)}`
                      : ""}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </section>

        {/* ── Lo relacionado ─────────────────────────────────────────── */}
        <aside className="space-y-4">
          <Relacionados
            titulo={t("cuenta.contactos")}
            icono="person"
            vacio={t("cuenta.sinContactos")}
            cuantos={contactos.length}
          >
            {contactos.map((c) => (
              <li key={c.id} className="py-1.5">
                <p className="truncate text-xs text-ink">{c.nombre}</p>
                <p className="truncate text-3xs text-ink-faint">
                  {[c.cargo, c.email].filter(Boolean).join(" · ") || "—"}
                </p>
                {c.no_contactar ? (
                  <span className="badge badge-warning mt-1">{t("cuenta.noContactar")}</span>
                ) : null}
              </li>
            ))}
          </Relacionados>

          <Relacionados
            titulo={t("cuenta.oportunidades")}
            icono="trending_up"
            vacio={t("cuenta.sinOportunidades")}
            cuantos={oportunidades.length}
          >
            {oportunidades.map((o) => (
              <li key={o.id} className="py-1.5">
                <Link
                  to={`/m/oportunidades/oportunidad/${o.id}`}
                  className="block truncate text-xs text-accent hover:underline"
                >
                  {o.nombre}
                </Link>
                <p className="flex items-center gap-1.5 text-3xs text-ink-faint">
                  {importe(o.importe, o.moneda)}
                  <span
                    className={
                      o.estado === "ganada"
                        ? "badge badge-success"
                        : o.estado === "perdida"
                          ? "badge badge-danger"
                          : "badge badge-muted"
                    }
                  >
                    {o.estado}
                  </span>
                </p>
              </li>
            ))}
          </Relacionados>

          <Relacionados
            titulo={t("cuenta.casos")}
            icono="confirmation_number"
            vacio={t("cuenta.sinCasos")}
            cuantos={casos.length}
          >
            {casos.map((c) => (
              <li key={c.id} className="py-1.5">
                <p className="truncate text-xs text-ink">{c.asunto}</p>
                <p className="text-3xs text-ink-faint">
                  {[c.codigo, c.estado, c.prioridad].filter(Boolean).join(" · ")}
                </p>
              </li>
            ))}
          </Relacionados>
        </aside>
      </div>
    </>
  );
}

function Dato({ clave, valor }: { clave: string; valor: unknown }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-3xs text-ink-faint">{humanizar(clave)}</dt>
      <dd className="truncate text-2xs text-ink">
        {valor ? escalar(valor, clave) : <span className="text-ink-faint">{t("cuenta.sinDato")}</span>}
      </dd>
    </div>
  );
}

function Relacionados({
  titulo,
  icono,
  vacio,
  cuantos,
  children,
}: {
  titulo: string;
  icono: string;
  vacio: string;
  cuantos: number;
  children: React.ReactNode;
}) {
  return (
    <section className="card p-4">
      <h2 className="section-label mb-2 flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5">
          <Icono nombre={icono} tamano="sm" />
          {titulo}
        </span>
        <span className="text-ink-faint">{cuantos}</span>
      </h2>
      {cuantos === 0 ? (
        <p className="py-2 text-3xs text-ink-faint">{vacio}</p>
      ) : (
        <ul className="divide-y divide-ink-dim/30">{children}</ul>
      )}
    </section>
  );
}

/**
 * Las métricas, distinguiendo el cero del «no lo sé».
 *
 * «Cero incidencias» y «no tenemos el dato de incidencias» se pintan igual en
 * un panel y significan lo contrario: uno es un cliente tranquilo y el otro una
 * integración caída. El servidor ya los separa; aquí se respeta.
 */
function Metricas({ datos }: { datos: Vista360["metricas"] }) {
  const { t } = useTranslation();
  const metricas = datos.metricas ?? [];
  const sinDato = datos.sin_dato ?? [];

  if (metricas.length === 0 && sinDato.length === 0) {
    return <p className="text-3xs text-ink-faint">{t("cuenta.sinMetricas")}</p>;
  }
  return (
    <>
      <dl className="space-y-2">
        {metricas.map((m) => (
          <div key={m.clave} className="flex items-baseline justify-between gap-3">
            <dt className="shrink-0 text-3xs text-ink-faint">{humanizar(m.clave)}</dt>
            <dd className="truncate text-2xs text-ink">
              {m.unidad === "moneda" ? importe(m.valor, m.moneda ?? "EUR") : escalar(m.valor)}
              {m.fresca ? null : (
                <span className="ml-1 text-3xs text-warning" title={t("cuenta.caducada")}>
                  ({t("cuenta.deHace", { dias: m.de_hace_dias })})
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {sinDato.length > 0 ? (
        <p className="mt-3 text-3xs text-ink-faint">
          {t("cuenta.sinDatoDe", { metricas: sinDato.map(humanizar).join(", ") })}
        </p>
      ) : null}
    </>
  );
}
