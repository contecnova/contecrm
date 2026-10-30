/**
 * Qué se ha hecho sobre los datos de un cliente, y qué pasaría si se hiciera
 * (CRM-00.01.03.02, CRM-00.01.03.03, CRM-00.01.03.06, CRM-00.01.03.10).
 *
 * Clonar un tenant, fusionar dos o partir uno son las operaciones más
 * peligrosas del producto: sacan los datos de un cliente de donde están
 * protegidos. Por eso el producto obliga a **simular antes de ejecutar** —una
 * operación que simula y ejecuta a la vez no es una simulación— y guarda de
 * cada una su plan y sus conflictos, con el motivo escrito en el modelo: «es
 * lo que alguien tiene que leer ANTES de aprobar».
 *
 * Y no había ninguna pantalla ni ninguna ruta que las listara. Se leían por
 * identificador, así que sólo podía volver a una quien se hubiera guardado el
 * id de la respuesta: nadie podía contestar **«¿qué se ha hecho sobre este
 * cliente?»**.
 *
 * Las migraciones de modalidad sí se listaban, y lo que faltaba era enseñarlas:
 * abrir una pone los datos del cliente en solo lectura, y eso no estaba en
 * ninguna pantalla.
 *
 * **Lo que separa esta pantalla de un listado es el estado.** Una operación
 * «simulada» no ha movido nada y una «ejecutada» sí, y en una lista las dos
 * ocupan una línea igual. Aquí lo simulado va aparte de lo hecho, y una
 * migración con la ventana de solo lectura abierta sale la primera: mientras
 * esté abierta, ese cliente no puede escribir.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { salvoCancelacion } from "@/lib/api";
import { listar } from "@/lib/listados";
import { fecha, fechaHora } from "@/lib/formato";

interface Operacion {
  id: string;
  /** clonado | fusion | escision */
  tipo: string;
  uso: string;
  /** simulada | ejecutada | fallida */
  estado: string;
  origen_id: string | null;
  destino_id: string | null;
  bloques: string[];
  plan: { recuentos?: Record<string, number>; avisos?: string[] };
  conflictos: unknown[];
  motivo_fin: string;
  created_at: string;
  terminada_at: string | null;
}

interface Migracion {
  id: string;
  desde: string;
  hacia: string;
  /** planificada | en_ventana | verificada | cerrada | revertida */
  estado: string;
  ventana_minutos: number;
  solo_lectura_desde: string | null;
  solo_lectura_hasta: string | null;
  diferencias: unknown[];
  motivo_fin: string;
  created_at: string;
  terminada_at: string | null;
}

interface Perfil {
  clave: string;
  nombre: string;
  descripcion: string;
}

function filasDe(plan: Operacion["plan"]): number {
  return Object.values(plan?.recuentos ?? {}).reduce((a, b) => a + (b ?? 0), 0);
}

export function CicloDeVidaDelCliente() {
  const { t } = useTranslation();
  const [operaciones, setOperaciones] = useState<Operacion[]>([]);
  const [migraciones, setMigraciones] = useState<Migracion[]>([]);
  const [perfiles, setPerfiles] = useState<Perfil[]>([]);
  const [cargado, setCargado] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    const { signal } = control;
    setFallo(null);
    Promise.all([
      listar<Operacion>("/api/v1/ciclo-vida/operaciones?limite=100", { signal }),
      listar<Migracion>("/api/v1/aislamiento/migraciones?limite=100", { signal }),
      listar<Perfil>("/api/v1/ciclo-vida/perfiles", { signal }),
    ])
      .then(([o, m, p]) => {
        setOperaciones(o);
        setMigraciones(m);
        setPerfiles(p);
        setCargado(true);
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;

  const hechas = operaciones.filter((o) => o.estado !== "simulada");
  const simuladas = operaciones.filter((o) => o.estado === "simulada");
  // Una ventana de solo lectura abierta es lo único de esta pantalla que pasa
  // AHORA MISMO: mientras esté abierta, ese cliente no puede escribir.
  const abiertas = migraciones.filter((m) => m.estado === "en_ventana");

  return (
    <>
      <CabeceraPagina
        titulo={t("ciclovida.titulo")}
        icono="swap_horiz"
        entradilla={t("ciclovida.entradilla")}
      />

      {abiertas.length > 0 ? (
        <p className="card mb-4 border-warning/40 p-3 text-2xs text-warning" role="status">
          {t("ciclovida.ventanaAbierta", { cuantas: abiertas.length })}
        </p>
      ) : null}

      <div className="flex flex-col gap-6">
        <section>
          <h2 className="text-sm font-medium text-ink">{t("ciclovida.hechas")}</h2>
          <p className="mt-1 text-3xs text-ink-faint">{t("ciclovida.porqueHechas")}</p>
          {hechas.length === 0 ? (
            <Vacio titulo={t("ciclovida.sinHechas")} detalle="" />
          ) : (
            <ul className="lista-acotada mt-2 flex flex-col gap-2 pr-1">
              {hechas.map((o) => (
                <li key={o.id} className="card p-3">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="chip-dato">{o.tipo}</span>
                    <span className="flex-1 text-2xs text-ink">{o.uso}</span>
                    <span
                      className={
                        o.estado === "fallida" ? "badge badge-aviso" : "badge badge-muted"
                      }
                    >
                      {o.estado}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-3xs text-ink-muted">
                    {t("ciclovida.movio", {
                      bloques: (o.bloques ?? []).length,
                      filas: filasDe(o.plan),
                    })}
                  </p>
                  {/* El motivo del final va entero: «fallida» sin el porqué
                      obliga a abrir el registro por la API para saber qué pasó. */}
                  {o.motivo_fin ? (
                    <p className="mt-1 text-2xs text-ink">{o.motivo_fin}</p>
                  ) : null}
                  {(o.conflictos ?? []).length > 0 ? (
                    <p className="mt-1 text-2xs text-warning">
                      {t("ciclovida.conflictos", { cuantos: o.conflictos.length })}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h2 className="text-sm font-medium text-ink">{t("ciclovida.simuladas")}</h2>
          {/* Aparte de las hechas a propósito: una simulada NO ha movido nada,
              y en una lista corrida las dos ocupan una línea igual. */}
          <p className="mt-1 text-3xs text-ink-faint">{t("ciclovida.porqueSimuladas")}</p>
          {simuladas.length === 0 ? (
            <Vacio titulo={t("ciclovida.sinSimuladas")} detalle="" />
          ) : (
            <ul className="lista-acotada mt-2 flex flex-col gap-2 pr-1">
              {simuladas.map((o) => (
                <li key={o.id} className="card p-3">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="chip-dato">{o.tipo}</span>
                    <span className="flex-1 text-2xs text-ink">{o.uso}</span>
                    <span className="font-mono text-3xs text-ink-faint">
                      {fecha(o.created_at)}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-3xs text-ink-muted">
                    {t("ciclovida.sacaria", {
                      bloques: (o.bloques ?? []).length,
                      filas: filasDe(o.plan),
                    })}
                  </p>
                  {(o.plan?.avisos ?? []).map((aviso, i) => (
                    <p key={i} className="mt-1 text-2xs text-warning">
                      {aviso}
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h2 className="text-sm font-medium text-ink">{t("ciclovida.migraciones")}</h2>
          <p className="mt-1 text-3xs text-ink-faint">{t("ciclovida.porqueMigraciones")}</p>
          {migraciones.length === 0 ? (
            <Vacio titulo={t("ciclovida.sinMigraciones")} detalle="" />
          ) : (
            <ul className="lista-acotada mt-2 flex flex-col gap-2 pr-1">
              {migraciones.map((m) => (
                <li key={m.id} className="card p-3">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-mono text-2xs text-ink">
                      {t("ciclovida.deA", { desde: m.desde, hacia: m.hacia })}
                    </span>
                    <span className="flex-1" />
                    <span
                      className={
                        m.estado === "en_ventana" ? "badge badge-aviso" : "badge badge-muted"
                      }
                    >
                      {m.estado}
                    </span>
                  </div>
                  {/* La ventana con sus horas: «10 minutos» no dice si cae en
                      hora punta del cliente, y eso es lo que se negocia. */}
                  <p className="mt-1 font-mono text-3xs text-ink-muted">
                    {m.solo_lectura_desde
                      ? t("ciclovida.ventanaDesde", {
                          desde: fechaHora(m.solo_lectura_desde),
                          minutos: m.ventana_minutos,
                        })
                      : t("ciclovida.ventanaPrevista", { minutos: m.ventana_minutos })}
                  </p>
                  {/* Las diferencias de la verificación: una migración
                      «verificada» con diferencias no está bien, está medida. */}
                  {(m.diferencias ?? []).length > 0 ? (
                    <p className="mt-1 text-2xs text-warning">
                      {t("ciclovida.diferencias", { cuantas: m.diferencias.length })}
                    </p>
                  ) : null}
                  {m.motivo_fin ? (
                    <p className="mt-1 text-2xs text-ink">{m.motivo_fin}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h2 className="text-sm font-medium text-ink">{t("ciclovida.perfiles")}</h2>
          <p className="mt-1 text-3xs text-ink-faint">{t("ciclovida.porquePerfiles")}</p>
          {!cargado || perfiles.length === 0 ? (
            <Vacio titulo={t("ciclovida.sinPerfiles")} detalle="" />
          ) : (
            <ul className="lista-acotada mt-2 flex flex-col gap-2 pr-1">
              {perfiles.map((p) => (
                <li key={p.clave} className="card p-3">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="flex-1 text-2xs text-ink">{p.nombre}</span>
                    <span className="chip-dato font-mono">{p.clave}</span>
                  </div>
                  {p.descripcion ? (
                    <p className="mt-1 text-3xs text-ink-muted">{p.descripcion}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
