/**
 * El panel de GRC: qué no cuadra hoy, y de qué no se sabe nada
 * (CRM-07.03.02.03, CRM-07.03.02.04, CRM-07.03.02.05, CRM-07.03.02.07,
 * CRM-07.03.02.08, CRM-07.03.02.10).
 *
 * El módulo genérico lista riesgos y controles. Un GRC que sólo lista es un
 * archivo: lo que lo convierte en herramienta son las tres preguntas que una
 * lista no contesta.
 *
 * **«¿Está en verde porque cumple o porque no hay nada con que comprobarlo?»**
 * Las dos se pintan igual y significan lo contrario. Por eso el panel trae
 * `medible` y `porque`, y por eso aquí un panel sin controles ni evaluaciones
 * NO sale verde: sale diciendo que no se puede medir. Y la cobertura sólo
 * aparece cuando hay con qué: un 0 % y un «no se ha podido medir» se leen
 * igual y son lo contrario.
 *
 * **«¿Qué capacidades del producto no tiene nadie vigiladas?»** El informe de
 * cobertura lo contesta contra el catálogo entero, por identificador, y de
 * paso saca los controles que apuntan a capacidades que **no existen**: un
 * control sobre un identificador inventado consta como cobertura y no cubre
 * nada, que es la peor de las dos formas de no estar cubierto.
 *
 * **«Enséñame ISO 27001 A.9»** y, al revés, «¿qué obligaciones responde esta
 * capacidad?». El mapeo se recorre en los dos sentidos porque las dos
 * preguntas se hacen: una la hace el auditor y la otra el que va a tocar el
 * código.
 *
 * Lo urgente va arriba y **con su porqué**, no con un color: «control evaluado
 * como no efectivo» no mueve a nadie; «está declarado y no protege: peor que
 * no tenerlo, porque consta» sí.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";

interface Urgente {
  que: string;
  por_que_urge: string;
  orden: number;
  inherente?: number | null;
}

interface Panel {
  generado_at: string;
  riesgos_abiertos: number;
  controles_activos: number;
  controles_evaluados: number;
  /** Sólo cuando hay con qué medir: un 0 % y un «no se sabe» son lo contrario. */
  cobertura_pct: number | null;
  lo_que_urge: Urgente[];
  medible: boolean;
  porque: string;
  todo_en_orden: boolean;
}

interface Cobertura {
  medible: boolean;
  motivo?: string;
  alcance?: string;
  capacidades?: number;
  con_control?: number;
  sin_control?: number;
  pct?: number;
  por_seccion?: Record<string, { total: number; con_control: number; pct: number }>;
  capacidades_sin_control?: string[];
  /** Controles que apuntan a un identificador que no está en el catálogo. */
  controles_sobre_capacidades_inexistentes?: { control: string; capacidad: string }[];
}

interface ControlDeMarco {
  codigo: string;
  nombre: string;
  activo: boolean;
  capacidades: { id: string; titulo: string }[];
  ultima_evaluacion: { resultado?: string; evaluado_at?: string } | null;
}

type Marcos = Record<string, { referencias: Record<string, { controles: ControlDeMarco[] }> }>;

export function Gobierno() {
  const { t } = useTranslation();
  const [panel, setPanel] = useState<Panel | null>(null);
  const [cobertura, setCobertura] = useState<Cobertura | null>(null);
  const [marcos, setMarcos] = useState<Marcos>({});
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    const { signal } = control;
    setFallo(null);
    Promise.all([
      llamar<Panel>("/api/v1/grc/panel", { signal }),
      llamar<Cobertura>("/api/v1/grc/cobertura?solo_hechas=true", { signal }),
      llamar<Marcos>("/api/v1/grc/marcos", { signal }),
    ])
      .then(([p, c, m]) => {
        setPanel(p.datos);
        setCobertura(c.datos);
        setMarcos(m.datos ?? {});
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!panel) return <Cargando />;

  const urgente = panel.lo_que_urge ?? [];
  const huerfanos = cobertura?.controles_sobre_capacidades_inexistentes ?? [];
  const porSeccion = Object.entries(cobertura?.por_seccion ?? {});

  return (
    <>
      <CabeceraPagina
        titulo={t("grc.titulo")}
        icono="verified_user"
        entradilla={t("grc.entradilla")}
      />

      {/* Un panel vacío en verde es el que más tranquiliza y el que peor
          informa: no dice que se cumpla, dice que no hay con qué comprobarlo. */}
      {!panel.medible ? (
        <p className="card mb-4 border-warning/40 p-3 text-2xs text-warning" role="status">
          {panel.porque}
        </p>
      ) : null}

      <div className="mb-4 grid gap-3 sm:grid-cols-4">
        <div className="card p-3">
          <p className="text-3xs text-ink-muted">{t("grc.cobertura")}</p>
          <p className="font-mono text-lg text-ink">
            {panel.cobertura_pct === null
              ? t("grc.sinMedir")
              : t("grc.pct", { pct: panel.cobertura_pct })}
          </p>
        </div>
        <div className="card p-3">
          <p className="text-3xs text-ink-muted">{t("grc.riesgosAbiertos")}</p>
          <p className="font-mono text-lg text-ink">{panel.riesgos_abiertos}</p>
        </div>
        <div className="card p-3">
          <p className="text-3xs text-ink-muted">{t("grc.controlesActivos")}</p>
          <p className="font-mono text-lg text-ink">{panel.controles_activos}</p>
        </div>
        <div className="card p-3">
          <p className="text-3xs text-ink-muted">{t("grc.controlesEvaluados")}</p>
          <p className="font-mono text-lg text-ink">{panel.controles_evaluados}</p>
        </div>
      </div>

      <div className="flex flex-col gap-6">
        <section>
          <h2 className="text-sm font-medium text-ink">{t("grc.urgente")}</h2>
          {urgente.length === 0 ? (
            <Vacio
              titulo={t(panel.medible ? "grc.nadaUrgente" : "grc.nadaQueMirar")}
              detalle=""
            />
          ) : (
            <ul className="lista-acotada mt-2 flex flex-col gap-2 pr-1">
              {urgente.map((u, i) => (
                <li key={`${u.que}-${i}`} className="card p-3">
                  <p className="text-2xs text-ink">{u.que}</p>
                  {/* El porqué y no un color: «no efectivo» no mueve a nadie. */}
                  <p className="mt-1 text-3xs text-ink-muted">{u.por_que_urge}</p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h2 className="text-sm font-medium text-ink">{t("grc.informeCobertura")}</h2>
          {!cobertura?.medible ? (
            <p className="mt-2 text-2xs text-ink-muted">
              {cobertura?.motivo || t("grc.sinCobertura")}
            </p>
          ) : (
            <>
              <p className="mt-1 text-3xs text-ink-faint">
                {t("grc.alcance", {
                  alcance: cobertura.alcance,
                  capacidades: cobertura.capacidades,
                  con: cobertura.con_control,
                  sin: cobertura.sin_control,
                })}
              </p>
              {/* Un control sobre una capacidad que no existe consta como
                  cobertura y no cubre nada: es peor que no tener control. */}
              {huerfanos.length > 0 ? (
                <p className="mt-2 text-2xs text-warning">
                  {t("grc.huerfanos", { cuantos: huerfanos.length })}
                </p>
              ) : null}
              {porSeccion.length > 0 ? (
                <ul className="lista-acotada mt-2 flex flex-col gap-1 pr-1">
                  {porSeccion.map(([seccion, datos]) => (
                    <li key={seccion} className="flex items-baseline gap-2">
                      <span className="flex-1 text-2xs text-ink">{seccion}</span>
                      <span className="font-mono text-3xs text-ink-muted">
                        {t("grc.deTotal", {
                          con: datos.con_control,
                          total: datos.total,
                          pct: datos.pct,
                        })}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          )}
        </section>

        <section>
          <h2 className="text-sm font-medium text-ink">{t("grc.marcos")}</h2>
          <p className="mt-1 text-3xs text-ink-faint">{t("grc.porqueMarcos")}</p>
          {Object.keys(marcos).length === 0 ? (
            <Vacio titulo={t("grc.sinMarcos")} detalle="" />
          ) : (
            <ul className="lista-acotada mt-2 flex flex-col gap-3 pr-1">
              {Object.entries(marcos).map(([marco, nodo]) => (
                <li key={marco} className="card p-3">
                  <p className="text-2xs font-medium text-ink">{marco}</p>
                  <ul className="mt-1 flex flex-col gap-1">
                    {Object.entries(nodo.referencias ?? {}).map(([referencia, datos]) => (
                      <li key={referencia}>
                        <span className="chip-dato font-mono">{referencia || "—"}</span>{" "}
                        {(datos.controles ?? []).map((c) => (
                          <span key={c.codigo} className="text-3xs text-ink-muted">
                            {t("grc.control", {
                              codigo: c.codigo,
                              capacidades: (c.capacidades ?? []).length,
                              resultado:
                                c.ultima_evaluacion?.resultado ?? t("grc.sinEvaluar"),
                            })}{" "}
                          </span>
                        ))}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
