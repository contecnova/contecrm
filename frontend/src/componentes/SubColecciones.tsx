/**
 * Lo que cuelga de un registro, con sus altas y sus acciones.
 *
 * Las líneas de un presupuesto, el equipo de una cuenta, sus direcciones, sus
 * identificadores fiscales. Son **196** en el sistema y no se alcanzaba
 * ninguna: la ficha enseñaba los campos del propio registro y nada más, así que
 * la mitad de lo que un CRM guarda sobre un cliente no se podía ver ni tocar.
 *
 * Con ellas vienen las 44 acciones que actúan sobre un hijo —quitar a alguien
 * del equipo, verificar un identificador, geocodificar una dirección—, que
 * tampoco se alcanzaban porque no había dónde pulsarlas.
 *
 * Todo sale del contrato, igual que los listados y las acciones del registro:
 * la superficie dice qué cuelga de esta ruta y qué permiso exige cada cosa, y
 * el OpenAPI de qué se compone el alta. Un hijo nuevo en el servidor aparece
 * solo.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { Formulario } from "@/componentes/Formulario";
import { Icono } from "@/componentes/Icono";
import { filas, llamar, salvoCancelacion } from "@/lib/api";
import type { SubColeccion } from "@/lib/acciones";
import { camposDe, contratoDe, type CampoEsquema } from "@/lib/contrato";
import { escalar, esIdentificadorTecnico, humanizar, nombreDelRegistro } from "@/lib/formato";

export function SubColecciones({
  paneles,
  servicio,
  id,
}: {
  paneles: SubColeccion[];
  servicio: string;
  /** Identificador del registro padre, para componer las rutas de los hijos. */
  id: string;
}) {
  if (paneles.length === 0) return null;
  return (
    <div className="mt-4 space-y-3">
      {paneles.map((panel) => (
        <Panel key={panel.clave} panel={panel} servicio={servicio} idPadre={id} />
      ))}
    </div>
  );
}

function Panel({
  panel,
  servicio,
  idPadre,
}: {
  panel: SubColeccion;
  servicio: string;
  idPadre: string;
}) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const [elementos, setElementos] = useState<Record<string, unknown>[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [anadiendo, setAnadiendo] = useState(false);
  const [campos, setCampos] = useState<CampoEsquema[] | null>(null);
  const [enviando, setEnviando] = useState(false);

  const cargar = useCallback(
    (signal?: AbortSignal) => {
      llamar<unknown>(panel.ruta, { signal })
        .then((r) => setElementos(filas<Record<string, unknown>>(r.datos)))
        .catch(salvoCancelacion(setFallo));
    },
    [panel.ruta],
  );

  // Se carga solo al abrir: una ficha con ocho paneles haría ocho llamadas
  // antes de que nadie mire ninguna.
  useEffect(() => {
    if (!abierto) return;
    const control = new AbortController();
    cargar(control.signal);
    return () => control.abort();
  }, [abierto, cargar]);

  useEffect(() => {
    if (!anadiendo || !panel.alta) return;
    let vivo = true;
    setCampos(null);
    void contratoDe(servicio).then((documento) => {
      if (vivo) setCampos(camposDe(documento, panel.alta!.plantilla, "post"));
    });
    return () => {
      vivo = false;
    };
  }, [anadiendo, panel.alta, servicio]);

  async function anadir(valores: Record<string, unknown>) {
    setEnviando(true);
    try {
      await llamar(panel.ruta, { metodo: "POST", cuerpo: valores });
      setAnadiendo(false);
      cargar();
      setFallo(null);
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  /** La ruta real de un hijo, sustituyendo los dos parámetros por sus valores. */
  function rutaHija(plantilla: string, idHijo: string): string {
    let primero = true;
    return plantilla.replace(/\{[^}]+\}/g, () => {
      const valor = primero ? idPadre : idHijo;
      primero = false;
      return valor;
    });
  }

  async function sobreHijo(plantilla: string, metodo: string, idHijo: string) {
    setEnviando(true);
    try {
      await llamar(rutaHija(plantilla, idHijo), { metodo: metodo as "POST" });
      cargar();
      setFallo(null);
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  const cuantos = elementos?.length;

  return (
    <section className="card">
      <button
        type="button"
        onClick={() => setAbierto((v) => !v)}
        aria-expanded={abierto}
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left"
      >
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink">
          <Icono
            nombre="keyboard_arrow_down"
            tamano="sm"
            className={abierto ? "" : "-rotate-90"}
          />
          {panel.nombre}
        </span>
        {cuantos !== undefined ? (
          <span className="text-3xs text-ink-faint">{cuantos}</span>
        ) : null}
      </button>

      {abierto ? (
        <div className="border-t border-ink-dim/30 px-4 py-3">
          {fallo ? (
            <div className="mb-3">
              <Fallo error={fallo} reintentar={() => cargar()} />
            </div>
          ) : null}

          {panel.alta ? (
            <div className="mb-3">
              {anadiendo ? (
                <>
                  {campos ? (
                    <Formulario
                      campos={campos}
                      enviando={enviando}
                      textoEnviar={panel.alta.nombre}
                      alEnviar={(v) => void anadir(v)}
                    />
                  ) : (
                    <Cargando />
                  )}
                  <button
                    type="button"
                    onClick={() => setAnadiendo(false)}
                    className="btn-link mt-2"
                  >
                    {t("modulo.cancelar")}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => setAnadiendo(true)}
                  className="btn-secondary inline-flex items-center gap-1.5"
                >
                  <Icono nombre="add" tamano="sm" />
                  {panel.alta.nombre}
                </button>
              )}
            </div>
          ) : null}

          {elementos === null ? (
            <Cargando />
          ) : elementos.length === 0 ? (
            <p className="py-2 text-3xs text-ink-faint">{t("subcoleccion.vacia")}</p>
          ) : (
            <ul className="divide-y divide-ink-dim/30">
              {elementos.map((e, i) => {
                const idHijo = String(e.id ?? "");
                const titulo = nombreDelRegistro(e) || idHijo.slice(0, 8);
                const detalle = Object.entries(e)
                  .filter(([k, v]) => !esIdentificadorTecnico(k) && v !== null && v !== "")
                  .slice(0, 3)
                  .map(([k, v]) =>
                    `${humanizar(k)}: ${typeof v === "object" ? "…" : escalar(v, k)}`,
                  )
                  .join(" · ");
                return (
                  <li key={idHijo || i} className="flex items-start justify-between gap-3 py-2">
                    <div className="min-w-0">
                      <p className="truncate text-2xs text-ink">{titulo}</p>
                      {detalle ? (
                        <p className="truncate text-3xs text-ink-faint">{detalle}</p>
                      ) : null}
                    </div>
                    {idHijo ? (
                      <div className="flex shrink-0 flex-wrap gap-1">
                        {panel.acciones.map((a) => (
                          <button
                            key={a.clave}
                            type="button"
                            disabled={enviando}
                            onClick={() => void sobreHijo(a.plantilla, a.metodo, idHijo)}
                            className="btn-secondary"
                            title={a.nombre}
                          >
                            {a.nombre}
                          </button>
                        ))}
                        {panel.borrable ? (
                          <button
                            type="button"
                            disabled={enviando}
                            onClick={() => {
                              // Se pregunta: quitar a alguien del equipo de una
                              // cuenta o una línea de un presupuesto no se
                              // deshace desde aquí.
                              if (window.confirm(t("subcoleccion.confirmarQuitar"))) {
                                void sobreHijo(
                                  `${panel.plantilla}/{hijo}`,
                                  "DELETE",
                                  idHijo,
                                );
                              }
                            }}
                            className="btn-danger"
                          >
                            {t("subcoleccion.quitar")}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}
