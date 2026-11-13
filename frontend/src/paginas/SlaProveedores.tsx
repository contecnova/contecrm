/**
 * El acuerdo de servicio del proveedor frente al que prometemos al cliente
 * (CRM-09.01.01.08).
 *
 * Hasta el 09-11-2026 la comparación existía como cálculo puro: el SLA del
 * proveedor lo tecleaba quien preguntaba, que es justo la creencia que había
 * que comprobar. Ahora se guarda el acuerdo de cada proveedor —los proveedores
 * son los de integración, los mismos a los que se mandan los encargos— y se
 * compara solo con lo que prometen los derechos de servicio que ese proveedor
 * da: lo que no se puede cumplir sale arriba, con el porqué.
 *
 * Tres preguntas, en el orden en que se hacen: qué prometemos que no se
 * sostiene; quién da cada derecho; y qué sostiene cada proveedor.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmarBorrado } from "@/componentes/Edicion";
import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { listar } from "@/lib/listados";

interface Problema {
  metrica: string;
  porque: string;
}

interface Fila {
  entitlement_id: string;
  entitlement: string;
  sla_clave: string | null;
  proveedor_clave: string;
  proveedor: string;
  proveedor_existe: boolean | null;
  prometido: Record<string, number>;
  del_proveedor: Record<string, number | string>;
  veredicto:
    "se_sostiene" | "no_se_sostiene" | "sin_acuerdo" | "sin_compromiso";
  problemas: Problema[];
  sin_declarar: string[];
}

interface Revision {
  revisados: number;
  no_se_sostienen: number;
  sin_acuerdo: number;
  horas_propias: number;
  integracion_respondio: boolean;
  proveedores: { clave: string; nombre: string; plazo_horas: number | null }[];
  filas: Fila[];
  hay_avisos: boolean;
}

interface Acuerdo {
  proveedor_clave: string;
  respuesta_h: number | null;
  resolucion_h: number | null;
  disponibilidad_pct: number | null;
  cobertura_horaria: string | null;
}

interface Derecho {
  id: string;
  clave: string;
  nombre: string;
  sla_clave: string | null;
  proveedor_clave: string | null;
}

const TONO: Record<Fila["veredicto"], string> = {
  se_sostiene: "chip-dato--si",
  no_se_sostiene: "chip-dato--mal",
  sin_acuerdo: "chip-dato--aviso",
  sin_compromiso: "",
};

function metricas(
  valores: Record<string, number | string>,
  t: (k: string, o: Record<string, unknown>) => string,
) {
  const partes = Object.entries(valores).map(([k, v]) =>
    t(`slaProveedores.metrica.${k}`, { v }),
  );
  return partes.length ? partes.join(" · ") : "—";
}

export function SlaProveedores() {
  const { t } = useTranslation();
  const [revision, setRevision] = useState<Revision | null>(null);
  const [acuerdos, setAcuerdos] = useState<Acuerdo[]>([]);
  const [derechos, setDerechos] = useState<Derecho[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState<Acuerdo | null>(null);
  // El proveedor cuyo acuerdo se va a quitar, mientras se pregunta.
  const [quitando, setQuitando] = useState("");
  const [borrando, setBorrando] = useState(false);

  const cargar = useCallback(() => {
    setFallo(null);
    llamar<Revision>("/api/v1/sla-proveedores/revision")
      .then((r) => setRevision(r.datos))
      .catch((e) => setFallo(e));
    llamar<Acuerdo[]>("/api/v1/sla-proveedores/acuerdos")
      .then((r) => setAcuerdos(Array.isArray(r.datos) ? r.datos : []))
      .catch(() => setAcuerdos([]));
    void listar<Derecho>("/api/v1/entitlements?limite=200")
      .then(setDerechos)
      .catch(() => setDerechos([]));
  }, []);
  useEffect(cargar, [cargar]);

  async function asignar(derecho: string, proveedor: string) {
    try {
      await llamar(
        `/api/v1/sla-proveedores/entitlements/${derecho}/proveedor`,
        {
          metodo: "PUT",
          cuerpo: { proveedor_clave: proveedor || null },
        },
      );
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function quitar(clave: string) {
    setBorrando(true);
    try {
      await llamar(
        `/api/v1/sla-proveedores/acuerdos/${encodeURIComponent(clave)}`,
        {
          metodo: "DELETE",
        },
      );
      setQuitando("");
      cargar();
    } catch (e) {
      setFallo(e);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !revision) return <Fallo error={fallo} reintentar={cargar} />;
  if (!revision) return <Cargando />;

  // Los proveedores de integración y los que sólo tienen acuerdo guardado: un
  // acuerdo de un proveedor que ya no existe se enseña igual, para quitarlo.
  const claves = [
    ...new Set([
      ...revision.proveedores.map((p) => p.clave),
      ...acuerdos.map((a) => a.proveedor_clave),
    ]),
  ].sort();
  const nombre = (c: string) =>
    revision.proveedores.find((p) => p.clave === c)?.nombre ?? c;
  const plazo = (c: string) =>
    revision.proveedores.find((p) => p.clave === c)?.plazo_horas ?? null;

  return (
    <>
      <CabeceraPagina
        titulo={t("slaProveedores.titulo")}
        entradilla={t("slaProveedores.entradilla", {
          horas: revision.horas_propias,
        })}
        icono="handshake"
      />

      {!revision.integracion_respondio ? (
        <p className="card mb-4 p-3 text-dato text-warning" role="status">
          {t("slaProveedores.sinIntegracion")}
        </p>
      ) : null}
      <p
        className={`card mb-4 p-3 text-dato ${revision.hay_avisos ? "text-danger" : "text-ink"}`}
        role="status"
      >
        {revision.revisados === 0
          ? t("slaProveedores.nadaQueRevisar")
          : revision.hay_avisos
            ? t("slaProveedores.avisos", {
                no: revision.no_se_sostienen,
                sin: revision.sin_acuerdo,
                n: revision.revisados,
              })
            : t("slaProveedores.todoBien", { n: revision.revisados })}
      </p>

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">{t("slaProveedores.revision")}</h2>
        {revision.filas.length === 0 ? (
          <Vacio titulo={t("slaProveedores.sinFilas")} compacto />
        ) : (
          <Rejilla
            titulo={t("slaProveedores.revision")}
            cabeceras={[
              t("slaProveedores.col.derecho"),
              t("slaProveedores.col.proveedor"),
              t("slaProveedores.col.prometido"),
              t("slaProveedores.col.sostiene"),
              t("slaProveedores.col.veredicto"),
              t("slaProveedores.col.porque"),
            ]}
          >
            {revision.filas.map((f) => (
              <tr key={f.entitlement_id}>
                <Casilla>{f.entitlement}</Casilla>
                <Casilla>
                  {f.proveedor}
                  {f.proveedor_existe === false ? (
                    <span className="chip-dato chip-dato--aviso ml-2">
                      {t("slaProveedores.noExiste")}
                    </span>
                  ) : null}
                </Casilla>
                <Casilla>{metricas(f.prometido, t)}</Casilla>
                <Casilla>{metricas(f.del_proveedor, t)}</Casilla>
                <Casilla enUnaLinea>
                  <span className={`chip-dato ${TONO[f.veredicto]}`}>
                    {t(`slaProveedores.veredicto.${f.veredicto}`)}
                  </span>
                </Casilla>
                <Casilla className="text-ink-muted">
                  {f.problemas.map((p) => (
                    <p key={p.metrica}>{p.porque}</p>
                  ))}
                  {f.sin_declarar.length ? (
                    <p>
                      {t("slaProveedores.sinDeclarar", {
                        que: f.sin_declarar
                          .map((m) => t(`slaProveedores.nombre.${m}`))
                          .join(", "),
                      })}
                    </p>
                  ) : null}
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        )}
      </section>

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">{t("slaProveedores.quienDa")}</h2>
        {derechos.length === 0 ? (
          <Vacio titulo={t("slaProveedores.sinDerechos")} compacto />
        ) : (
          <Rejilla
            titulo={t("slaProveedores.quienDa")}
            cabeceras={[
              t("slaProveedores.col.derecho"),
              t("slaProveedores.col.sla"),
              t("slaProveedores.col.proveedor"),
            ]}
          >
            {derechos.map((d) => (
              <tr key={d.id}>
                <Casilla>{d.nombre}</Casilla>
                <Casilla className="text-ink-muted">
                  {d.sla_clave ?? "—"}
                </Casilla>
                <Casilla>
                  <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
                    <span className="sr-only">
                      {t("slaProveedores.quienDaEste", { derecho: d.nombre })}
                    </span>
                    <select
                      className="input-base"
                      value={d.proveedor_clave ?? ""}
                      onChange={(e) => void asignar(d.id, e.target.value)}
                    >
                      <option value="">{t("slaProveedores.nosotros")}</option>
                      {claves.map((c) => (
                        <option key={c} value={c}>
                          {nombre(c)}
                        </option>
                      ))}
                    </select>
                  </label>
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        )}
      </section>

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">{t("slaProveedores.acuerdos")}</h2>
        {claves.length === 0 ? (
          <Vacio
            titulo={t("slaProveedores.sinProveedores")}
            detalle={t("slaProveedores.sinProveedoresDetalle")}
            compacto
          />
        ) : (
          <Rejilla
            titulo={t("slaProveedores.acuerdos")}
            cabeceras={[
              t("slaProveedores.col.proveedor"),
              t("slaProveedores.col.plazo"),
              t("slaProveedores.col.sostiene"),
              "",
            ]}
          >
            {claves.map((c) => {
              const a = acuerdos.find((x) => x.proveedor_clave === c);
              return (
                <tr key={c}>
                  <Casilla>{nombre(c)}</Casilla>
                  <Casilla enUnaLinea className="text-ink-muted">
                    {plazo(c) !== null
                      ? t("slaProveedores.horas", { v: plazo(c) })
                      : "—"}
                  </Casilla>
                  <Casilla>
                    {a
                      ? metricas(
                          Object.fromEntries(
                            Object.entries(a).filter(
                              ([k, v]) =>
                                k !== "proveedor_clave" &&
                                v !== null &&
                                k in VACIO,
                            ),
                          ) as Record<string, number | string>,
                          t,
                        )
                      : t("slaProveedores.sinAcuerdo")}
                  </Casilla>
                  <Casilla enUnaLinea>
                    <button
                      type="button"
                      className="btn-link"
                      onClick={() =>
                        setEditando(a ?? { ...VACIO, proveedor_clave: c })
                      }
                    >
                      {a
                        ? t("slaProveedores.cambiar")
                        : t("slaProveedores.anadir")}
                    </button>
                    {a ? (
                      <button
                        type="button"
                        className="btn-link ml-3"
                        onClick={() => setQuitando(c)}
                      >
                        {t("slaProveedores.quitar")}
                      </button>
                    ) : null}
                  </Casilla>
                </tr>
              );
            })}
          </Rejilla>
        )}
        {quitando ? (
          <div className="mt-3">
            <ConfirmarBorrado
              borrado={t("slaProveedores.quitarAcuerdo", {
                proveedor: nombre(quitando),
              })}
              aviso={t("slaProveedores.quitarAcuerdoAviso", {
                proveedor: nombre(quitando),
              })}
              enviando={borrando}
              alBorrar={() => void quitar(quitando)}
              alCancelar={() => setQuitando("")}
            />
          </div>
        ) : null}
        {editando ? (
          <EditarAcuerdo
            acuerdo={editando}
            nombre={nombre(editando.proveedor_clave)}
            alGuardar={() => {
              setEditando(null);
              cargar();
            }}
            alCerrar={() => setEditando(null)}
          />
        ) : null}
      </section>
      {fallo ? <Fallo error={fallo} /> : null}
    </>
  );
}

const VACIO: Acuerdo = {
  proveedor_clave: "",
  respuesta_h: null,
  resolucion_h: null,
  disponibilidad_pct: null,
  cobertura_horaria: null,
};

function EditarAcuerdo({
  acuerdo,
  nombre,
  alGuardar,
  alCerrar,
}: {
  acuerdo: Acuerdo;
  nombre: string;
  alGuardar: () => void;
  alCerrar: () => void;
}) {
  const { t } = useTranslation();
  const [a, setA] = useState(acuerdo);
  const [fallo, setFallo] = useState<unknown>(null);
  const numero = (v: string) => (v.trim() === "" ? null : Number(v));

  async function guardar() {
    try {
      await llamar(
        `/api/v1/sla-proveedores/acuerdos/${encodeURIComponent(a.proveedor_clave)}`,
        {
          metodo: "PUT",
          cuerpo: {
            respuesta_h: a.respuesta_h,
            resolucion_h: a.resolucion_h,
            disponibilidad_pct: a.disponibilidad_pct,
            cobertura_horaria: a.cobertura_horaria || null,
          },
        },
      );
      alGuardar();
    } catch (e) {
      setFallo(e);
    }
  }

  const campo = (k: "respuesta_h" | "resolucion_h" | "disponibilidad_pct") => (
    <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
      {t(`slaProveedores.campo.${k}`)}
      <input
        className="input-base"
        type="number"
        min={0}
        step="any"
        value={a[k] ?? ""}
        onChange={(e) => setA({ ...a, [k]: numero(e.target.value) })}
      />
    </label>
  );

  return (
    <div className="mt-4 border-t border-ink-dim pt-4">
      <h3 className="section-label mb-2">
        {t("slaProveedores.editar", { proveedor: nombre })}
      </h3>
      <div className="grid gap-3 md:grid-cols-4">
        {campo("respuesta_h")}
        {campo("resolucion_h")}
        {campo("disponibilidad_pct")}
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("slaProveedores.campo.cobertura_horaria")}
          <input
            className="input-base"
            value={a.cobertura_horaria ?? ""}
            placeholder="24x7"
            onChange={(e) => setA({ ...a, cobertura_horaria: e.target.value })}
          />
        </label>
      </div>
      <p className="mt-2 text-dato text-ink-muted">
        {t("slaProveedores.resolucionVacia")}
      </p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          className="btn-primary"
          onClick={() => void guardar()}
        >
          {t("slaProveedores.guardar")}
        </button>
        <button type="button" className="btn-secondary" onClick={alCerrar}>
          {t("slaProveedores.cancelar")}
        </button>
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
    </div>
  );
}
