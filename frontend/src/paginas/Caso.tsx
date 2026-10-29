/**
 * Un caso: con qué tiene que ver, cómo va su reloj y cómo acabó
 * (CRM-04.01.01.03, CRM-04.01.01.04, CRM-04.01.01.09, CRM-04.01.01.10).
 *
 * La bandeja dice qué atender primero; abrir un caso es otra cosa. Lo que se
 * necesita delante es **de qué cliente es, sobre qué producto o activo, de
 * quién cuelga y cuánto queda**, y la ficha genérica enseñaba una lista de
 * campos con seis UUID sueltos.
 *
 * Tres decisiones:
 *
 * **Los dos incumplimientos van separados.** Incumplir la primera respuesta y
 * incumplir la resolución son dos conversaciones distintas con el cliente, y
 * sumarlos en un «SLA incumplido» hace que la primera —que es la que todavía
 * se puede salvar— no se mire.
 *
 * **El reloj parado se dice.** Un caso que lleva seis días esperando al
 * cliente no lleva seis días sin atenderse, y en una lista se ven igual.
 *
 * **Y un caso cerrado pendiente de que el cliente lo dé por bueno NO está
 * cerrado.** Es la mitad que casi nunca se publica, y la que hace que un
 * informe de cierres diga lo que no es.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  BotonesDeRegistro,
  ConfirmarBorrado,
  FormularioDeEdicion,
  useEdicion,
} from "@/componentes/Edicion";
import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";

interface Sla {
  clave: string | null;
  version: number | null;
  vence_primera_respuesta_at: string | null;
  vence_resolucion_at: string | null;
  primera_respuesta_at: string | null;
  pausa_acumulada_s: number;
  incumplio_primera_respuesta: boolean;
  incumplio_resolucion: boolean;
}

interface Arbol {
  caso: string;
  padre: string | null;
  hijos: { id: string; asunto: string; estado: string }[];
  colgados_del_maestro: { id: string; asunto: string; estado: string }[];
  duplicado_de: string | null;
}

interface Cierre {
  motivo: string | null;
  resolucion: string | null;
  validacion_cliente: string | null;
  reaperturas: number;
  cerrado_at: string | null;
  resuelto_at: string | null;
}

interface Caso {
  id: string;
  codigo: string | null;
  asunto: string;
  descripcion: string | null;
  estado: string;
  prioridad: string;
  severidad: string;
  clasificacion?: string | null;
  relacionado_con: Record<string, string | null>;
  cierre: Cierre;
  sla: Sla;
  relaciones: Arbol;
  historial: { tipo: string; detalle: Record<string, unknown>; at: string }[];
}

/** A qué pantalla lleva cada relación. Lo que no tiene ficha no se enlaza. */
const ADONDE: Record<string, string | null> = {
  cuenta_id: "/m/cuentas/cuenta/",
  contacto_id: "/m/cuentas/contacto/",
  producto_id: null,
  activo_id: null,
  contrato_id: null,
  pedido_id: null,
};

export function Caso() {
  const { id = "" } = useParams();
  const [caso, setCaso] = useState<Caso | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const navegar = useNavigate();
  // El mismo recurso que el listado: dos pantallas que enseñan el mismo
  // registro tienen que escribirlo por la misma ruta y el mismo contrato.
  const modulo = moduloDe("casos");
  const recurso = modulo ? recursoDe(modulo, "caso") : undefined;
  const { ruta, puedeEditar, puedeBorrar } = useEdicion(recurso, id);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Caso>(`/api/v1/casos/${id}`, { signal: control.signal })
      .then((r) => setCaso(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/m/casos");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !caso) return <Fallo error={fallo} reintentar={cargar} />;
  if (!caso) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={caso.asunto}
        icono="support_agent"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            {caso.codigo ? <span className="badge badge-muted">{caso.codigo}</span> : null}
            <span className="chip-dato">{caso.estado}</span>
            <span className="chip-dato">{caso.prioridad}</span>
            <span className="chip-dato">{caso.severidad}</span>
            {caso.clasificacion ? (
              <span className="text-2xs text-ink-muted">{caso.clasificacion}</span>
            ) : null}
          </span>
        }
      />

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
          valores={caso as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      {caso.descripcion ? (
        <p className="card mb-4 p-3 text-2xs text-ink-muted">{caso.descripcion}</p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <ConQueTieneQueVer relaciones={caso.relacionado_con} />
        <ElReloj sla={caso.sla} />
        <DeQuienCuelga arbol={caso.relaciones} />
        <ComoAcabo cierre={caso.cierre} />
      </div>

      <ElHistorial eventos={caso.historial} />
    </>
  );
}

/**
 * Con qué tiene que ver (CRM-04.01.01.03).
 *
 * Los seis, no sólo el cliente: un caso sobre un activo instalado se atiende
 * distinto que uno sobre un pedido, y sin el activo hay que preguntárselo al
 * cliente, que ya lo dijo al abrirlo.
 */
function ConQueTieneQueVer({
  relaciones,
}: {
  relaciones: Record<string, string | null>;
}) {
  const { t } = useTranslation();
  const puestas = Object.entries(relaciones ?? {}).filter(([, v]) => v);

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("caso.relacionado")}</h2>
      {puestas.length === 0 ? (
        <Vacio titulo={t("caso.sinRelaciones")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {puestas.map(([clave, valor]) => {
            const adonde = ADONDE[clave];
            return (
              <li key={clave} className="flex items-baseline justify-between gap-3 py-1.5">
                <span className="text-3xs text-ink-faint">{t(`caso.rel.${clave}`)}</span>
                {/* Sólo se enlaza lo que TIENE ficha: un enlace a una pantalla
                    que no existe parece que algo se ha roto. */}
                {adonde ? (
                  <Link to={`${adonde}${valor}`} className="text-2xs text-ink hover:underline">
                    {t("caso.abrir")}
                  </Link>
                ) : (
                  <span className="text-2xs text-ink-muted">{String(valor).slice(0, 8)}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/**
 * El reloj, con los dos incumplimientos por separado (CRM-04.01.02.03).
 *
 * Y la pausa: un caso que lleva seis días esperando al cliente no lleva seis
 * días sin atenderse, y en una lista se ven igual.
 */
function ElReloj({ sla }: { sla: Sla }) {
  const { t } = useTranslation();
  if (!sla?.clave) {
    return (
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("caso.reloj")}</h2>
        <Vacio titulo={t("caso.sinSla")} compacto />
      </section>
    );
  }

  const horasEnPausa = Math.round((sla.pausa_acumulada_s ?? 0) / 360) / 10;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("caso.reloj")}</h2>
      <p className="text-3xs text-ink-faint">
        {t("caso.sla", { clave: sla.clave, version: sla.version })}
      </p>
      <ul className="mt-2 space-y-1 text-2xs">
        <li className={sla.incumplio_primera_respuesta ? "text-danger" : "text-ink-muted"}>
          {sla.incumplio_primera_respuesta
            ? t("caso.incumplioPrimera")
            : t("caso.primeraVence", { cuando: sla.vence_primera_respuesta_at ?? "—" })}
        </li>
        <li className={sla.incumplio_resolucion ? "text-danger" : "text-ink-muted"}>
          {sla.incumplio_resolucion
            ? t("caso.incumplioResolucion")
            : t("caso.resolucionVence", { cuando: sla.vence_resolucion_at ?? "—" })}
        </li>
      </ul>
      {horasEnPausa > 0 ? (
        <p className="mt-2 text-3xs text-warning">
          {t("caso.enPausa", { horas: horasEnPausa })}
        </p>
      ) : null}
    </section>
  );
}

/**
 * De quién cuelga y qué cuelga de él (CRM-04.01.01.04).
 *
 * Un caso duplicado que no dice de cuál lo es obliga a buscarlo, y mientras
 * tanto se contesta dos veces al mismo cliente.
 */
function DeQuienCuelga({ arbol }: { arbol: Arbol }) {
  const { t } = useTranslation();
  const hijos = arbol?.hijos ?? [];
  const colgados = arbol?.colgados_del_maestro ?? [];
  const nada = !arbol?.padre && !arbol?.duplicado_de && hijos.length === 0 && colgados.length === 0;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("caso.jerarquia")}</h2>
      {nada ? (
        <Vacio titulo={t("caso.sinJerarquia")} compacto />
      ) : (
        <ul className="space-y-1 text-2xs">
          {arbol.padre ? (
            <li>
              <Link to={`/m/casos/caso/${arbol.padre}`} className="text-ink hover:underline">
                {t("caso.cuelgaDe")}
              </Link>
            </li>
          ) : null}
          {arbol.duplicado_de ? (
            <li className="text-warning">
              <Link
                to={`/m/casos/caso/${arbol.duplicado_de}`}
                className="hover:underline"
              >
                {t("caso.duplicadoDe")}
              </Link>
            </li>
          ) : null}
          {[...hijos, ...colgados].map((h) => (
            <li key={h.id} className="flex flex-wrap items-baseline gap-x-2">
              <Link to={`/m/casos/caso/${h.id}`} className="text-ink hover:underline">
                {h.asunto}
              </Link>
              <span className="chip-dato">{h.estado}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Cómo acabó (CRM-04.01.01.09, CRM-04.01.01.10).
 *
 * **Cerrado y pendiente de que el cliente lo dé por bueno no es cerrado.** Es
 * la mitad que casi nunca se publica, y la que hace que un informe de cierres
 * diga lo que no es. Y las reaperturas van con el cierre: un caso cerrado tres
 * veces no es un caso resuelto.
 */
function ComoAcabo({ cierre }: { cierre: Cierre }) {
  const { t } = useTranslation();
  if (!cierre?.motivo && !cierre?.cerrado_at && !cierre?.reaperturas) {
    return (
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("caso.cierre")}</h2>
        <Vacio titulo={t("caso.sinCerrar")} compacto />
      </section>
    );
  }

  const aFaltaDeCliente =
    cierre.validacion_cliente != null && cierre.validacion_cliente !== "aceptado";

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("caso.cierre")}</h2>
      {aFaltaDeCliente ? (
        <p className="mb-2 text-2xs text-warning">
          {t("caso.pendienteDelCliente", { estado: cierre.validacion_cliente })}
        </p>
      ) : null}
      {cierre.motivo ? <span className="chip-dato">{cierre.motivo}</span> : null}
      {cierre.resolucion ? (
        <p className="mt-1 text-2xs text-ink-muted">{cierre.resolucion}</p>
      ) : null}
      {cierre.reaperturas > 0 ? (
        <p className="mt-2 text-2xs text-danger">
          {t("caso.reaperturas", { cuantas: cierre.reaperturas })}
        </p>
      ) : null}
    </section>
  );
}

/**
 * Lo que le ha pasado, en orden (CRM-04.01.01.10).
 *
 * Es la trazabilidad de la reapertura y de todo lo demás: se escribía desde el
 * primer día y la ficha genérica la pintaba como un campo más.
 */
function ElHistorial({
  eventos,
}: {
  eventos: { tipo: string; detalle: Record<string, unknown>; at: string }[];
}) {
  const { t } = useTranslation();
  const todos = eventos ?? [];

  return (
    <section className="card mt-4 p-4">
      <h2 className="section-label mb-1">{t("caso.historial")}</h2>
      {todos.length === 0 ? (
        <Vacio titulo={t("caso.sinHistorial")} compacto />
      ) : (
        <ol className="lista-acotada divide-y divide-ink-dim/30 pr-1">
          {todos.map((e, i) => (
            <li key={`${e.tipo}-${e.at}-${i}`} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
              <span className="text-2xs font-medium text-ink">{e.tipo}</span>
              <time className="text-3xs text-ink-faint" dateTime={e.at}>
                {e.at.slice(0, 16).replace("T", " ")}
              </time>
              {Object.entries(e.detalle ?? {}).map(([k, v]) => (
                <span key={k} className="text-3xs text-ink-muted">
                  {k}: {String(v)}
                </span>
              ))}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
