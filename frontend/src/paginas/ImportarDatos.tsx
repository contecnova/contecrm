/**
 * Importar cuentas y contactos: mapear, simular, importar y revertir
 * (CRM-07.01.01.08, CRM-00.04.03.08).
 *
 * El servidor ya validaba antes de escribir y simulaba por defecto, pero sólo
 * para cuentas y sin pantalla: había que montar el JSON a mano. Y lo que se
 * pide el día después —«el fichero de ayer venía mal, quita lo que metió»— no
 * existía. Esta pantalla son los cuatro pasos, en orden:
 *
 * 1. **Subir el CSV** y elegir qué se importa. El fichero se lee aquí, con su
 *    separador —el `;` de Excel en español o la `,`—, para poder enseñar sus
 *    columnas antes de mandar nada.
 * 2. **Mapear**: a qué campo va cada columna, con un desplegable que ofrece
 *    los de serie **y los campos propios** que el cliente le ha añadido al
 *    objeto (CRM-00.04.03.08). Lo que casa por nombre se propone solo; lo que
 *    no, se queda en «No importar» y se ve.
 * 3. **Simular**, con el informe fila a fila: qué haría con cada una —crear,
 *    completar, omitir porque ya existe— y por qué falla la que falla.
 * 4. **Importar** y, desde el historial, **revertir** una importación entera:
 *    lo creado a la papelera y lo actualizado a su valor anterior. Se simula
 *    también, y si algo se ha tocado después de importarlo se dice y no se
 *    pisa sin que se pida.
 *
 * Comprobado en el navegador el 09-11-2026 con un CSV de contactos con `;`:
 * simular (2 se crean, 1 falla por el nombre), importar y revertir desde el
 * historial —los dos contactos a la papelera—. Los campos propios, en las
 * pruebas: este tenant no tiene ninguno en contactos.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { ErrorApi, llamar, salvoCancelacion } from "@/lib/api";
import { claveDeCabecera, leerCsv, type Csv } from "@/lib/csv";
import { humanizar } from "@/lib/formato";
import { usePersonas, nombreDe } from "@/lib/personas";

const OBJETOS = ["cuenta", "contacto"] as const;

interface CampoImportable {
  nombre: string;
  titulo: string;
  tipo: string;
  obligatorio: boolean;
  propio: boolean;
}

interface Informe {
  total: number;
  creados: number;
  actualizados: number;
  omitidos: number;
  fallidos: number;
  errores: {
    fila: number;
    motivo: string;
    errores?: string[];
    detalle?: string;
  }[];
  errores_no_mostrados?: number;
  previsualizacion?: { fila: number; accion: string; motivo?: string }[];
  importacion?: Importacion;
}

interface Importacion {
  id: string;
  objeto: string;
  fichero: string;
  por: string | null;
  creados: number;
  actualizados: number;
  fallidos: number;
  created_at: string | null;
  revertida_at: string | null;
}

interface Reversion {
  simulado: boolean;
  borrados: number;
  restaurados: number;
  ya_no_estaban: number;
  conflictos: { id: string; accion: string; campos: string[] }[];
}

/** Qué campo se propone para cada columna: el que se llama igual. */
export function mapeoInicial(
  cabeceras: string[],
  campos: CampoImportable[],
): Record<number, string> {
  const salida: Record<number, string> = {};
  cabeceras.forEach((cabecera, i) => {
    const clave = claveDeCabecera(cabecera);
    const campo = campos.find(
      (c) =>
        claveDeCabecera(c.nombre) === clave ||
        claveDeCabecera(c.titulo) === clave,
    );
    if (campo) salida[i] = campo.nombre;
  });
  return salida;
}

/** Las filas del fichero como objetos, con los campos de destino y sin vacíos. */
export function filasMapeadas(
  csv: Csv,
  mapeo: Record<number, string>,
): Record<string, string>[] {
  return csv.filas.map((fila) => {
    const salida: Record<string, string> = {};
    for (const [indice, campo] of Object.entries(mapeo)) {
      const valor = (fila[Number(indice)] ?? "").trim();
      if (campo && valor) salida[campo] = valor;
    }
    return salida;
  });
}

export function ImportarDatos() {
  const { t } = useTranslation();
  const personas = usePersonas();
  const [objeto, setObjeto] = useState<string>("cuenta");
  const [campos, setCampos] = useState<CampoImportable[] | null>(null);
  const [csv, setCsv] = useState<Csv | null>(null);
  const [fichero, setFichero] = useState("");
  const [mapeo, setMapeo] = useState<Record<number, string>>({});
  const [actualizar, setActualizar] = useState(false);
  const [informe, setInforme] = useState<Informe | null>(null);
  const [simulado, setSimulado] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [historial, setHistorial] = useState<Importacion[] | null>(null);

  useEffect(() => {
    const control = new AbortController();
    setCampos(null);
    llamar<{ campos: CampoImportable[] }>(
      `/api/v1/party-admin/importaciones/campos?objeto=${encodeURIComponent(objeto)}`,
      { signal: control.signal },
    )
      .then((r) => setCampos(r.datos.campos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [objeto]);

  const cargarHistorial = useCallback(() => {
    llamar<Importacion[]>("/api/v1/party-admin/importaciones")
      .then((r) => setHistorial(r.datos))
      .catch(() => setHistorial([]));
  }, []);
  useEffect(cargarHistorial, [cargarHistorial]);

  // Al cambiar de objeto o de fichero, el mapeo se vuelve a proponer y lo
  // simulado deja de valer: era de otro fichero o de otro objeto.
  useEffect(() => {
    if (csv && campos) setMapeo(mapeoInicial(csv.cabeceras, campos));
    setInforme(null);
    setSimulado(false);
  }, [csv, campos]);

  const faltan = useMemo(
    () =>
      (campos ?? [])
        .filter(
          (c) => c.obligatorio && !Object.values(mapeo).includes(c.nombre),
        )
        .map((c) => (c.propio ? c.titulo : humanizar(c.titulo))),
    [campos, mapeo],
  );

  async function leer(archivo: File | undefined) {
    if (!archivo) return;
    setFallo(null);
    setFichero(archivo.name);
    setCsv(leerCsv(await archivo.text()));
  }

  async function lanzar(simular: boolean) {
    if (!csv) return;
    setEnviando(true);
    setFallo(null);
    try {
      const r = await llamar<Informe>("/api/v1/party-admin/importaciones", {
        metodo: "POST",
        cuerpo: {
          objeto,
          filas: filasMapeadas(csv, mapeo),
          simular,
          actualizar,
          fichero,
        },
      });
      setInforme(r.datos);
      setSimulado(simular);
      if (!simular) cargarHistorial();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  // Fila a fila: lo que haría con las buenas y por qué fallan las malas, en el
  // orden del fichero, que es el que tiene delante quien lo corrige.
  const porFila = useMemo(() => {
    if (!informe) return [];
    const filas = [
      ...(informe.previsualizacion ?? []).map((p) => ({
        fila: p.fila,
        accion: p.accion,
        motivo: p.motivo ?? "",
      })),
      ...informe.errores.map((e) => ({
        fila: e.fila,
        accion: "falla",
        motivo: (e.errores ?? []).join(" · ") || e.detalle || e.motivo,
      })),
    ];
    return filas.sort((a, b) => a.fila - b.fila);
  }, [informe]);

  const columnaNombre = useMemo(() => {
    const i = Object.entries(mapeo).find(([, c]) => c === "nombre")?.[0];
    return i === undefined ? -1 : Number(i);
  }, [mapeo]);

  return (
    <>
      <CabeceraPagina
        icono="upload_file"
        titulo={t("importar.titulo")}
        entradilla={t("importar.entradilla")}
      />

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">{t("importar.paso1")}</h2>
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label htmlFor="importar-objeto" className="label-base">
              {t("importar.queImportas")}
            </label>
            <select
              id="importar-objeto"
              value={objeto}
              onChange={(e) => setObjeto(e.target.value)}
              className="input-base"
            >
              {OBJETOS.map((o) => (
                <option key={o} value={o}>
                  {t(`importar.objetos.${o}`)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="importar-fichero" className="label-base">
              {t("importar.fichero")}
            </label>
            <input
              id="importar-fichero"
              type="file"
              accept=".csv,text/csv,text/plain"
              onChange={(e) => void leer(e.target.files?.[0])}
              className="input-base"
            />
          </div>
        </div>
        {csv ? (
          <p className="mt-2 text-rotulo text-ink-faint" role="status">
            {t("importar.leido", {
              fichero,
              filas: csv.filas.length,
              columnas: csv.cabeceras.length,
            })}
          </p>
        ) : null}
      </section>

      {fallo ? (
        <div className="mb-4">
          <Fallo error={fallo} />
        </div>
      ) : null}

      {csv && campos ? (
        <section className="card mb-4 p-4">
          <h2 className="section-label mb-1">{t("importar.paso2")}</h2>
          <p className="mb-2 text-rotulo text-ink-faint">
            {t("importar.mapeoAyuda")}
          </p>
          <Rejilla
            titulo={t("importar.paso2")}
            cabeceras={[
              t("importar.columna"),
              t("importar.ejemplo"),
              t("importar.destino"),
            ]}
          >
            {csv.cabeceras.map((cabecera, i) => (
              <tr
                key={`${cabecera}-${i}`}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla>{cabecera || t("importar.sinCabecera")}</Casilla>
                <Casilla className="text-ink-muted">
                  {csv.filas[0]?.[i] ?? ""}
                </Casilla>
                <Casilla>
                  <label className="sr-only" htmlFor={`importar-destino-${i}`}>
                    {t("importar.destinoDe", { columna: cabecera })}
                  </label>
                  <select
                    id={`importar-destino-${i}`}
                    value={mapeo[i] ?? ""}
                    onChange={(e) =>
                      setMapeo((previo) => {
                        const siguiente = { ...previo };
                        if (e.target.value) siguiente[i] = e.target.value;
                        else delete siguiente[i];
                        return siguiente;
                      })
                    }
                    className="input-sm"
                  >
                    <option value="">{t("importar.noImportar")}</option>
                    {campos.map((c) => (
                      <option key={c.nombre} value={c.nombre}>
                        {c.propio
                          ? t("importar.campoPropio", { campo: c.titulo })
                          : humanizar(c.titulo)}
                        {c.obligatorio ? " *" : ""}
                      </option>
                    ))}
                  </select>
                </Casilla>
              </tr>
            ))}
          </Rejilla>
          {faltan.length > 0 ? (
            <p className="mt-2 text-dato text-warning" role="status">
              {t("importar.faltan", { campos: faltan.join(", ") })}
            </p>
          ) : null}
          <label className="mt-3 inline-flex items-center gap-2 text-dato text-ink">
            <input
              type="checkbox"
              checked={actualizar}
              onChange={(e) => {
                setActualizar(e.target.checked);
                setSimulado(false);
                setInforme(null);
              }}
              className="h-3.5 w-3.5 rounded border-ink-dim accent-accent"
            />
            {t("importar.completarExistentes")}
          </label>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary"
              disabled={enviando || faltan.length > 0}
              onClick={() => void lanzar(true)}
            >
              {t("importar.simular")}
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={enviando || !simulado || faltan.length > 0}
              onClick={() => void lanzar(false)}
              title={simulado ? "" : t("importar.primeroSimula")}
            >
              {t("importar.importar")}
            </button>
          </div>
        </section>
      ) : null}

      {informe ? (
        <section className="card mb-4 p-4" role="status">
          <h2 className="section-label mb-1">
            {simulado
              ? t("importar.informeSimulado")
              : t("importar.informeHecho")}
          </h2>
          <p className="text-dato text-ink">
            {t("importar.resumen", {
              total: informe.total,
              creados: informe.creados,
              actualizados: informe.actualizados,
              omitidos: informe.omitidos,
              fallidos: informe.fallidos,
            })}
          </p>
          {informe.importacion ? (
            <p className="mt-1 text-rotulo text-ink-faint">
              {t("importar.sePuedeRevertir")}
            </p>
          ) : null}
          {porFila.length > 0 ? (
            <div className="mt-3">
              <Rejilla
                titulo={t("importar.porFila")}
                cabeceras={[
                  t("importar.fila"),
                  t("importar.nombre"),
                  t("importar.queHaria"),
                  t("importar.motivo"),
                ]}
              >
                {porFila.slice(0, 500).map((f) => (
                  <tr
                    key={`${f.fila}-${f.accion}`}
                    className="border-b border-ink-dim/30 last:border-0"
                  >
                    <Casilla enUnaLinea>{f.fila}</Casilla>
                    <Casilla>
                      {columnaNombre >= 0
                        ? (csv?.filas[f.fila - 1]?.[columnaNombre] ?? "")
                        : ""}
                    </Casilla>
                    <Casilla enUnaLinea>
                      <span
                        className={
                          f.accion === "falla"
                            ? "chip-dato chip-dato--mal"
                            : "chip-dato"
                        }
                      >
                        {t(`importar.acciones.${f.accion}`, {
                          defaultValue: f.accion,
                        })}
                      </span>
                    </Casilla>
                    <Casilla className="text-ink-muted">{f.motivo}</Casilla>
                  </tr>
                ))}
              </Rejilla>
              {informe.errores_no_mostrados ? (
                <p className="mt-1 text-rotulo text-ink-faint">
                  {t("importar.noMostrados", {
                    cuantos: informe.errores_no_mostrados,
                  })}
                </p>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}

      <Historial
        historial={historial}
        nombreDe={(id) => nombreDe(personas, id)}
        alCambiar={cargarHistorial}
      />
    </>
  );
}

/** Las importaciones hechas, y deshacer una entera. */
function Historial({
  historial,
  nombreDe: nombre,
  alCambiar,
}: {
  historial: Importacion[] | null;
  nombreDe: (id: unknown) => string;
  alCambiar: () => void;
}) {
  const { t } = useTranslation();
  const [revirtiendo, setRevirtiendo] = useState<Importacion | null>(null);
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("importar.historial")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("importar.historialAyuda")}
      </p>
      {historial === null ? (
        <Cargando />
      ) : historial.length === 0 ? (
        <Vacio titulo={t("importar.sinHistorial")} compacto />
      ) : (
        <Rejilla
          titulo={t("importar.historial")}
          cabeceras={[
            t("importar.cuando"),
            t("importar.que"),
            t("importar.fichero"),
            t("importar.quien"),
            t("importar.resultado"),
            "",
          ]}
        >
          {historial.map((h) => (
            <tr key={h.id} className="border-b border-ink-dim/30 last:border-0">
              <Casilla enUnaLinea>
                {(h.created_at ?? "").slice(0, 16).replace("T", " ")}
              </Casilla>
              <Casilla enUnaLinea>
                {t(`importar.objetos.${h.objeto}`, { defaultValue: h.objeto })}
              </Casilla>
              <Casilla>{h.fichero || "—"}</Casilla>
              <Casilla enUnaLinea>{h.por ? nombre(h.por) : "—"}</Casilla>
              <Casilla enUnaLinea>
                {t("importar.resultadoCorto", {
                  creados: h.creados,
                  actualizados: h.actualizados,
                  fallidos: h.fallidos,
                })}
              </Casilla>
              <Casilla enUnaLinea>
                {h.revertida_at ? (
                  <span className="chip-dato chip-dato--aviso">
                    {t("importar.revertida", {
                      cuando: h.revertida_at.slice(0, 10),
                    })}
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setRevirtiendo(h)}
                  >
                    {t("importar.revertir")}
                  </button>
                )}
              </Casilla>
            </tr>
          ))}
        </Rejilla>
      )}
      {revirtiendo ? (
        <Revertir
          key={revirtiendo.id}
          importacion={revirtiendo}
          alTerminar={() => {
            setRevirtiendo(null);
            alCambiar();
          }}
          alCancelar={() => setRevirtiendo(null)}
        />
      ) : null}
    </section>
  );
}

/** Revertir: simular primero, y confirmar con motivo. */
function Revertir({
  importacion,
  alTerminar,
  alCancelar,
}: {
  importacion: Importacion;
  alTerminar: () => void;
  alCancelar: () => void;
}) {
  const { t } = useTranslation();
  const [plan, setPlan] = useState<Reversion | null>(null);
  const [motivo, setMotivo] = useState("");
  const [forzar, setForzar] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const ruta = `/api/v1/party-admin/importaciones/${encodeURIComponent(importacion.id)}/revertir`;

  useEffect(() => {
    const control = new AbortController();
    llamar<Reversion>(ruta, {
      metodo: "POST",
      cuerpo: { simular: true, forzar: true },
      signal: control.signal,
    })
      .then((r) => setPlan(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [ruta]);

  async function confirmar() {
    setEnviando(true);
    setFallo(null);
    try {
      await llamar(ruta, {
        metodo: "POST",
        cuerpo: { simular: false, forzar, motivo },
      });
      alTerminar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  const conflictos = plan?.conflictos.length ?? 0;
  return (
    <div className="mt-3 rounded-lg border border-warning/40 bg-warning/5 p-3">
      <h3 className="text-dato font-medium text-ink">
        {t("importar.revertirTitulo", {
          fichero: importacion.fichero || importacion.id,
        })}
      </h3>
      {!plan && !fallo ? <Cargando /> : null}
      {plan ? (
        <>
          <p className="mt-1 text-dato text-ink" role="status">
            {t("importar.revertirPlan", {
              borrados: plan.borrados,
              restaurados: plan.restaurados,
              ya: plan.ya_no_estaban,
            })}
          </p>
          {conflictos > 0 ? (
            <>
              <p className="mt-1 text-dato text-warning">
                {t("importar.revertirConflictos", { cuantos: conflictos })}
              </p>
              <label className="mt-1 inline-flex items-center gap-2 text-dato text-ink">
                <input
                  type="checkbox"
                  checked={forzar}
                  onChange={(e) => setForzar(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-ink-dim accent-accent"
                />
                {t("importar.revertirForzar")}
              </label>
            </>
          ) : null}
          <div className="mt-2 max-w-xl">
            <label htmlFor="revertir-motivo" className="label-base">
              {t("importar.motivoRevertir")}
            </label>
            <input
              id="revertir-motivo"
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              className="input-base"
            />
          </div>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className="btn-danger"
              disabled={
                enviando ||
                motivo.trim().length < 5 ||
                (conflictos > 0 && !forzar)
              }
              onClick={() => void confirmar()}
            >
              {t("importar.confirmarRevertir")}
            </button>
            <button type="button" className="btn-ghost" onClick={alCancelar}>
              {t("modulo.cancelar")}
            </button>
          </div>
        </>
      ) : null}
      {fallo ? (
        <p className="mt-2 text-dato text-danger" role="status">
          {fallo instanceof ErrorApi
            ? fallo.explicacion || fallo.titulo
            : String(fallo)}
        </p>
      ) : null}
    </div>
  );
}
