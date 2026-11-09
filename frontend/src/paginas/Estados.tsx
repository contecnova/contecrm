/**
 * Los estados de cada objeto, configurados por la empresa (CRM-00.04.01.07).
 *
 * Pedido el 09-11-2026: «definir los estados, cómo se llaman, qué tipos hay o
 * cuántos hay; todo configurable por administradores». Aquí se renombran, se
 * ordenan y se colorean, se añaden los propios —diciendo qué significan— y se
 * decide a cuáles se puede pasar desde cada uno. Los de fábrica no se borran:
 * se desactivan. Lo valida el servidor y lo dice campo a campo.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { humanizar, rotuloDeOpcion } from "@/lib/formato";
import { cn } from "@/lib/utiles";

// Los servicios que pueden declarar máquinas. Se pregunta a todos y se queda
// con los que tienen alguna: así un objeto nuevo con estados sale solo.
const SERVICIOS = [
  "sales",
  "party",
  "service",
  "marketing",
  "integration",
  "automation",
  "orchestrator",
  "identity",
  "metadata",
  "analytics",
];

interface Estado {
  clave: string;
  nombre: string;
  color: string;
  orden: number;
  significado: string;
  final: boolean;
  activo: boolean;
}

interface Configuracion {
  objeto: string;
  de_fabrica: boolean;
  inicial: string;
  estados: Estado[];
  transiciones: Record<string, string[]>;
  exigen_motivo: string[];
  significados_obligatorios: string[];
  fabrica?: Configuracion;
}

interface Objeto {
  servicio: string;
  objeto: string;
}

export function Estados() {
  const { t } = useTranslation();
  const [objetos, setObjetos] = useState<Objeto[] | null>(null);
  const [elegido, setElegido] = useState<Objeto | null>(null);

  useEffect(() => {
    const control = new AbortController();
    void Promise.all(
      SERVICIOS.map((servicio) =>
        llamar<{ items: { objeto: string }[] }>(`/api/v1/${servicio}/estados`, {
          signal: control.signal,
        })
          .then((r) =>
            (r.datos?.items ?? []).map((i) => ({ servicio, objeto: i.objeto })),
          )
          .catch(() => [] as Objeto[]),
      ),
    ).then((listas) => {
      if (control.signal.aborted) return;
      const todos = listas.flat();
      setObjetos(todos);
      setElegido((e) => e ?? todos[0] ?? null);
    });
    return () => control.abort();
  }, []);

  if (!objetos) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        icono="rule"
        titulo={t("estadosConf.titulo")}
        entradilla={t("estadosConf.entradilla")}
      />
      {objetos.length === 0 ? (
        <Vacio titulo={t("estadosConf.ninguno")} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[14rem_1fr]">
          <nav className="card p-2" aria-label={t("estadosConf.objetos")}>
            <ul>
              {objetos.map((o) => (
                <li key={`${o.servicio}-${o.objeto}`}>
                  <button
                    type="button"
                    onClick={() => setElegido(o)}
                    aria-current={elegido?.objeto === o.objeto}
                    className={cn(
                      "block w-full rounded px-3 py-1.5 text-left text-titulin",
                      elegido?.objeto === o.objeto
                        ? "bg-accent/10 font-semibold text-accent"
                        : "text-ink hover:bg-paper-light",
                    )}
                  >
                    {humanizar(o.objeto)}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          {elegido ? <Editor key={elegido.objeto} objeto={elegido} /> : null}
        </div>
      )}
    </>
  );
}

function Editor({ objeto }: { objeto: Objeto }) {
  const { t } = useTranslation();
  const ruta = `/api/v1/${objeto.servicio}/estados/${objeto.objeto}`;
  const [conf, setConf] = useState<Configuracion | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [guardando, setGuardando] = useState(false);
  const [aviso, setAviso] = useState("");

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<Configuracion>(ruta, { signal: control.signal })
      .then((r) => setConf(r.datos))
      .catch(salvoCancelacion((e) => setFallo(e)));
    return () => control.abort();
  }, [ruta]);
  useEffect(cargar, [cargar]);

  if (fallo && !conf) return <Fallo error={fallo} />;
  if (!conf) return <Cargando />;

  const significados = Array.from(
    new Set((conf.fabrica?.estados ?? conf.estados).map((e) => e.significado)),
  );
  const deFabrica = new Set((conf.fabrica?.estados ?? []).map((e) => e.clave));
  const ordenados = [...conf.estados].sort((a, b) => a.orden - b.orden);

  function cambia(clave: string, cambio: Partial<Estado>) {
    setConf(
      (c) =>
        c && {
          ...c,
          estados: c.estados.map((e) =>
            e.clave === clave ? { ...e, ...cambio } : e,
          ),
        },
    );
  }

  function mueve(clave: string, paso: -1 | 1) {
    const lista = [...ordenados];
    const i = lista.findIndex((e) => e.clave === clave);
    const j = i + paso;
    if (i < 0 || j < 0 || j >= lista.length) return;
    [lista[i], lista[j]] = [lista[j]!, lista[i]!];
    setConf(
      (c) => c && { ...c, estados: lista.map((e, k) => ({ ...e, orden: k })) },
    );
  }

  function alterna(desde: string, hasta: string) {
    setConf((c) => {
      if (!c) return c;
      const actuales = new Set(c.transiciones[desde] ?? []);
      if (actuales.has(hasta)) actuales.delete(hasta);
      else actuales.add(hasta);
      return {
        ...c,
        transiciones: { ...c.transiciones, [desde]: [...actuales] },
      };
    });
  }

  function anade() {
    const base = `estado_${conf!.estados.length + 1}`;
    setConf(
      (c) =>
        c && {
          ...c,
          estados: [
            ...c.estados,
            {
              clave: base,
              nombre: "",
              color: "",
              orden: c.estados.length,
              significado: significados[0] ?? "",
              final: false,
              activo: true,
            },
          ],
        },
    );
  }

  async function guardar() {
    setGuardando(true);
    setAviso("");
    try {
      const r = await llamar<Configuracion>(ruta, {
        metodo: "PUT",
        cuerpo: {
          estados: conf!.estados,
          inicial: conf!.inicial,
          transiciones: conf!.transiciones,
          exigen_motivo: conf!.exigen_motivo,
        },
      });
      setFallo(null);
      setConf((c) => c && { ...r.datos, fabrica: c.fabrica });
      setAviso(t("estadosConf.guardado"));
    } catch (e) {
      setFallo(e);
    } finally {
      setGuardando(false);
    }
  }

  async function aFabrica() {
    setGuardando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      setFallo(null);
      setAviso(t("estadosConf.restaurado"));
      cargar();
    } catch (e) {
      setFallo(e);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div className="space-y-4">
      <section className="card p-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="section-label">
            {t("estadosConf.estadosDe", { objeto: humanizar(objeto.objeto) })}
          </h2>
          <span
            className={cn("chip-dato", conf.de_fabrica ? "" : "chip-dato--si")}
          >
            {t(
              conf.de_fabrica ? "estadosConf.deFabrica" : "estadosConf.propia",
            )}
          </span>
        </div>
        <p className="mb-3 text-rotulo text-ink-faint">
          {t("estadosConf.obligatorios", {
            lista: conf.significados_obligatorios
              .map(rotuloDeOpcion)
              .join(", "),
          })}
        </p>
        <Rejilla
          titulo={t("estadosConf.estadosDe", {
            objeto: humanizar(objeto.objeto),
          })}
          acotada={false}
          cabeceras={[
            t("estadosConf.orden"),
            t("estadosConf.clave"),
            t("estadosConf.nombre"),
            t("estadosConf.color"),
            t("estadosConf.significa"),
            t("estadosConf.final"),
            t("estadosConf.activo"),
            t("estadosConf.motivo"),
          ]}
        >
          {ordenados.map((e, i) => {
            const propio = !deFabrica.has(e.clave);
            return (
              <tr key={e.clave} className="border-t border-ink-dim/30">
                <Casilla enUnaLinea>
                  <button
                    type="button"
                    className="btn-link"
                    disabled={i === 0}
                    onClick={() => mueve(e.clave, -1)}
                    aria-label={t("estadosConf.subir", { estado: e.clave })}
                  >
                    <Icono nombre="arrow_upward" tamano="sm" />
                  </button>
                  <button
                    type="button"
                    className="btn-link"
                    disabled={i === ordenados.length - 1}
                    onClick={() => mueve(e.clave, 1)}
                    aria-label={t("estadosConf.bajar", { estado: e.clave })}
                  >
                    <Icono nombre="arrow_downward" tamano="sm" />
                  </button>
                </Casilla>
                <Casilla>
                  {propio ? (
                    <input
                      className="input-base font-mono"
                      value={e.clave}
                      aria-label={t("estadosConf.clave")}
                      onChange={(ev) =>
                        cambia(e.clave, { clave: ev.target.value })
                      }
                    />
                  ) : (
                    <span className="font-mono text-rotulo text-ink-muted">
                      {e.clave}
                    </span>
                  )}
                </Casilla>
                <Casilla>
                  <input
                    className="input-base"
                    value={e.nombre}
                    placeholder={rotuloDeOpcion(e.clave)}
                    aria-label={t("estadosConf.nombreDe", {
                      estado: e.clave,
                    })}
                    onChange={(ev) =>
                      cambia(e.clave, { nombre: ev.target.value })
                    }
                  />
                </Casilla>
                <Casilla>
                  <input
                    type="color"
                    className="h-8 w-10 rounded border border-ink-dim/60 bg-paper"
                    value={e.color}
                    aria-label={t("estadosConf.colorDe", {
                      estado: e.clave,
                    })}
                    onChange={(ev) =>
                      cambia(e.clave, { color: ev.target.value })
                    }
                  />
                </Casilla>
                <Casilla>
                  {propio ? (
                    <select
                      className="input-base"
                      value={e.significado}
                      aria-label={t("estadosConf.significaDe", {
                        estado: e.clave,
                      })}
                      onChange={(ev) =>
                        cambia(e.clave, { significado: ev.target.value })
                      }
                    >
                      {significados.map((s) => (
                        <option key={s} value={s}>
                          {rotuloDeOpcion(s)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="chip-dato">
                      {rotuloDeOpcion(e.significado)}
                    </span>
                  )}
                </Casilla>
                <Casilla className="text-center">
                  <input
                    type="checkbox"
                    checked={e.final}
                    aria-label={t("estadosConf.finalDe", {
                      estado: e.clave,
                    })}
                    onChange={(ev) =>
                      cambia(e.clave, { final: ev.target.checked })
                    }
                    className="h-4 w-4 accent-accent"
                  />
                </Casilla>
                <Casilla className="text-center">
                  <input
                    type="checkbox"
                    checked={e.activo}
                    aria-label={t("estadosConf.activoDe", {
                      estado: e.clave,
                    })}
                    onChange={(ev) =>
                      cambia(e.clave, { activo: ev.target.checked })
                    }
                    className="h-4 w-4 accent-accent"
                  />
                </Casilla>
                <Casilla className="text-center">
                  <input
                    type="checkbox"
                    checked={conf.exigen_motivo.includes(e.clave)}
                    aria-label={t("estadosConf.motivoDe", {
                      estado: e.clave,
                    })}
                    onChange={(ev) =>
                      setConf(
                        (c) =>
                          c && {
                            ...c,
                            exigen_motivo: ev.target.checked
                              ? [...c.exigen_motivo, e.clave]
                              : c.exigen_motivo.filter((x) => x !== e.clave),
                          },
                      )
                    }
                    className="h-4 w-4 accent-accent"
                  />
                </Casilla>
              </tr>
            );
          })}
        </Rejilla>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button type="button" className="btn-secondary" onClick={anade}>
            <Icono nombre="add" tamano="sm" />
            {t("estadosConf.anadir")}
          </button>
          <label className="flex items-center gap-2 text-dato text-ink-muted">
            {t("estadosConf.inicial")}
            <select
              className="input-base w-auto"
              value={conf.inicial}
              onChange={(ev) =>
                setConf((c) => c && { ...c, inicial: ev.target.value })
              }
            >
              {ordenados
                .filter((e) => e.activo)
                .map((e) => (
                  <option key={e.clave} value={e.clave}>
                    {e.nombre || rotuloDeOpcion(e.clave)}
                  </option>
                ))}
            </select>
          </label>
        </div>
      </section>

      <section className="card p-4">
        <h2 className="section-label mb-1">{t("estadosConf.transiciones")}</h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {t("estadosConf.transicionesAyuda")}
        </p>
        <Rejilla
          titulo={t("estadosConf.transiciones")}
          acotada={false}
          cabeceras={[
            t("estadosConf.desdeHasta"),
            ...ordenados.map((h) => h.nombre || rotuloDeOpcion(h.clave)),
          ]}
        >
          {ordenados.map((d) => (
            <tr key={d.clave} className="border-t border-ink-dim/30">
              <Casilla className="font-medium text-ink">
                {d.nombre || rotuloDeOpcion(d.clave)}
              </Casilla>
              {ordenados.map((h) => (
                <Casilla key={h.clave} className="text-center">
                  {d.clave === h.clave ? (
                    <span className="text-ink-faint">—</span>
                  ) : (
                    <input
                      type="checkbox"
                      checked={(conf.transiciones[d.clave] ?? []).includes(
                        h.clave,
                      )}
                      aria-label={t("estadosConf.deA", {
                        desde: d.clave,
                        hasta: h.clave,
                      })}
                      onChange={() => alterna(d.clave, h.clave)}
                      className="h-4 w-4 accent-accent"
                    />
                  )}
                </Casilla>
              ))}
            </tr>
          ))}
        </Rejilla>
      </section>

      <div role="status" className="space-y-2">
        {fallo ? <Fallo error={fallo} /> : null}
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={guardando}
          onClick={() => void guardar()}
        >
          {t("estadosConf.guardar")}
        </button>
        {!conf.de_fabrica ? (
          <button
            type="button"
            className="btn-secondary"
            disabled={guardando}
            onClick={() => void aFabrica()}
          >
            {t("estadosConf.volverAFabrica")}
          </button>
        ) : null}
      </div>
    </div>
  );
}
