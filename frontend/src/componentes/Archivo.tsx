/**
 * El archivo de histórico: archivar por criterio y leer lo archivado
 * (CRM-07.03.01.02).
 *
 * Hasta el 09-11-2026 la única ruta de archivo planificaba sobre filas
 * tecleadas y no movía nada, así que nunca se archivaba y no había archivo que
 * consultar. Aquí van las dos mitades: el panel de cada servicio —qué clases de
 * dato tiene, a partir de cuántos días se archiva cada una, cuánto movería hoy,
 * simular y archivar— y lo archivado de un registro, que se ve desde su ficha.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar, salvoCancelacion } from "@/lib/api";
import { cifra, fecha, fechaHora, humanizar } from "@/lib/formato";
import { useSuperficie } from "@/lib/permisos";

interface ClaseArchivable {
  clase: string;
  descripcion: string;
  tabla: string;
  campo_fecha: string;
  dias: number;
  corte: string;
  candidatas: number;
}

interface FilaArchivada {
  clase: string;
  tabla: string;
  registro_id: string;
  fecha_original: string | null;
  archivada_at: string;
  contenido: Record<string, unknown>;
}

interface Consulta {
  hay_archivo: boolean;
  filas: FilaArchivada[];
  cuantas: number;
  hay_mas: boolean;
}

interface Informe {
  clase: string;
  candidatas: number;
  archivadas: number;
  simulado: boolean;
  bajo_bloqueo_legal: number;
  corte: string;
}

/** El panel de un servicio: sus clases, su criterio y el botón de archivar. */
export function ArchivoDelServicio({
  servicio,
  puedeVer,
}: {
  servicio: string;
  puedeVer: boolean;
}) {
  const { t } = useTranslation();
  const [clases, setClases] = useState<ClaseArchivable[] | null>(null);
  const [hayArchivo, setHayArchivo] = useState(true);
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const [dias, setDias] = useState<Record<string, string>>({});
  const [buscar, setBuscar] = useState("");
  const [encontradas, setEncontradas] = useState<Consulta | null>(null);

  const base = `/api/v1/${servicio}/volumen/archivo`;

  const cargar = useCallback(() => {
    if (!puedeVer) return undefined;
    const control = new AbortController();
    setClases(null);
    setFallo(null);
    setEncontradas(null);
    llamar<{ hay_archivo: boolean; clases: ClaseArchivable[] }>(
      `${base}/clases`,
      { signal: control.signal },
    )
      .then((r) => {
        setHayArchivo(r.datos.hay_archivo);
        setClases(r.datos.clases);
        setDias(
          Object.fromEntries(
            r.datos.clases.map((c) => [c.clase, String(c.dias)]),
          ),
        );
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [base, puedeVer]);

  useEffect(cargar, [cargar]);

  async function fijar(clase: string) {
    setAviso("");
    try {
      const valor = Number(dias[clase]);
      await llamar(`${base}/clases/${clase}`, {
        metodo: "PUT",
        cuerpo: { dias: valor > 0 ? valor : null },
      });
      setAviso(t("archivo.criterioGuardado", { clase: humanizar(clase) }));
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function archivar(clase: string, simular: boolean) {
    setAviso("");
    try {
      const r = await llamar<Informe>(`${base}/archivar`, {
        metodo: "POST",
        cuerpo: { clase, simular },
      });
      setAviso(
        simular
          ? t("archivo.simulado", {
              n: r.datos.candidatas,
              corte: fecha(r.datos.corte),
            })
          : t("archivo.archivadas", {
              n: r.datos.archivadas,
              bloqueo: r.datos.bajo_bloqueo_legal,
            }),
      );
      if (!simular) cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function consultar() {
    const id = buscar.trim();
    const parametros = new URLSearchParams({ limite: "50" });
    if (id) parametros.set("relacionado_con", id);
    try {
      const r = await llamar<Consulta>(`${base}?${parametros.toString()}`);
      setEncontradas(r.datos);
    } catch (e) {
      setFallo(e);
    }
  }

  if (!puedeVer) return null;
  return (
    <section className="card mb-4 p-4">
      <h3 className="section-label">{t("archivo.titulo")}</h3>
      <p className="mb-2 mt-0.5 text-rotulo text-ink-faint">
        {t("archivo.ayuda")}
      </p>
      <div role="status" className="mb-2">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {!clases && !fallo ? <Cargando /> : null}
      {clases && !hayArchivo ? (
        <Vacio titulo={t("archivo.sinArchivo", { servicio })} compacto />
      ) : null}
      {clases && hayArchivo ? (
        <>
          <Rejilla
            titulo={t("archivo.titulo")}
            cabeceras={[
              t("archivo.clase"),
              t("archivo.dias"),
              t("archivo.corte"),
              t("archivo.candidatas"),
              "",
            ]}
          >
            {clases.map((c) => (
              <tr
                key={c.clase}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla className="min-w-[14rem]">
                  <span className="text-ink">{humanizar(c.clase)}</span>
                  <p className="text-rotulo text-ink-faint">{c.descripcion}</p>
                </Casilla>
                <Casilla>
                  <span className="flex items-center gap-1">
                    <input
                      type="number"
                      min={1}
                      className="input-base w-24"
                      aria-label={t("archivo.diasDe", {
                        clase: humanizar(c.clase),
                      })}
                      value={dias[c.clase] ?? ""}
                      onChange={(e) =>
                        setDias((d) => ({ ...d, [c.clase]: e.target.value }))
                      }
                    />
                    <button
                      type="button"
                      className="btn-ghost"
                      title={t("archivo.guardarCriterio")}
                      aria-label={t("archivo.guardarCriterio")}
                      onClick={() => void fijar(c.clase)}
                    >
                      <Icono nombre="save" tamano="sm" />
                    </button>
                  </span>
                </Casilla>
                <Casilla>{fecha(c.corte)}</Casilla>
                <Casilla className="text-right">{cifra(c.candidatas)}</Casilla>
                <Casilla>
                  <span className="flex gap-1">
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => void archivar(c.clase, true)}
                    >
                      {t("archivo.simular")}
                    </button>
                    <button
                      type="button"
                      className="btn-primary"
                      disabled={c.candidatas === 0}
                      onClick={() => void archivar(c.clase, false)}
                    >
                      <Icono nombre="archive" tamano="sm" />
                      {t("archivo.archivar")}
                    </button>
                  </span>
                </Casilla>
              </tr>
            ))}
          </Rejilla>

          <h4 className="section-label mb-1 mt-4">{t("archivo.consultar")}</h4>
          <div className="flex flex-wrap items-center gap-2">
            <input
              className="input-base min-w-[20rem]"
              placeholder={t("archivo.buscarAyuda")}
              aria-label={t("archivo.buscarAyuda")}
              value={buscar}
              onChange={(e) => setBuscar(e.target.value)}
            />
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void consultar()}
            >
              <Icono nombre="search" tamano="sm" />
              {t("archivo.consultar")}
            </button>
          </div>
          {encontradas ? <FilasArchivadas consulta={encontradas} /> : null}
        </>
      ) : null}
    </section>
  );
}

function FilasArchivadas({
  consulta,
  alDevolver,
}: {
  consulta: Consulta;
  alDevolver?: (fila: FilaArchivada) => void;
}) {
  const { t } = useTranslation();
  if (consulta.cuantas === 0)
    return <Vacio titulo={t("archivo.nada")} compacto />;
  return (
    <>
      <ul className="mt-2 divide-y divide-ink-dim/30">
        {consulta.filas.map((f) => (
          <li key={f.registro_id} className="py-1.5">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="chip-dato">{humanizar(f.clase)}</span>
              <span className="text-titulo text-ink">
                {String(
                  f.contenido.nombre ??
                    f.contenido.asunto ??
                    f.contenido.titulo ??
                    f.registro_id,
                )}
              </span>
              <span className="text-rotulo text-ink-muted">
                {t("archivo.deCuando", {
                  original: f.fecha_original ? fecha(f.fecha_original) : "—",
                  archivada: fechaHora(f.archivada_at),
                })}
              </span>
              {alDevolver ? (
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => alDevolver(f)}
                >
                  <Icono nombre="unarchive" tamano="sm" />
                  {t("archivo.devolver")}
                </button>
              ) : null}
            </div>
            <details className="mt-1">
              <summary className="cursor-pointer text-rotulo text-ink-faint">
                {t("archivo.contenido")}
              </summary>
              <dl className="mt-1 grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-3 text-rotulo">
                {Object.entries(f.contenido)
                  .filter(([, v]) => v !== null && v !== "")
                  .map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-ink-muted">{humanizar(k)}</dt>
                      <dd className="break-all text-ink">
                        {typeof v === "object" ? JSON.stringify(v) : String(v)}
                      </dd>
                    </div>
                  ))}
              </dl>
            </details>
          </li>
        ))}
      </ul>
      {consulta.hay_mas ? (
        <p className="mt-1 text-rotulo text-ink-muted">{t("archivo.hayMas")}</p>
      ) : null}
    </>
  );
}

/**
 * Lo archivado de un registro, en su ficha: lo que colgaba de él —las
 * actividades de hace cuatro años de una cuenta— o el propio registro, si es
 * él el archivado (entonces la ficha no lo encuentra en la tabla viva y esto
 * dice dónde está y deja devolverlo).
 */
export function ArchivadoDelRegistro({
  servicio,
  id,
}: {
  servicio: string;
  id: string;
}) {
  const { t } = useTranslation();
  const { tiene } = useSuperficie();
  const puedeVer = tiene("admin:read");
  const [consulta, setConsulta] = useState<Consulta | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");

  const cargar = useCallback(() => {
    if (!puedeVer || !servicio || !id) return undefined;
    const control = new AbortController();
    llamar<Consulta>(
      `/api/v1/${servicio}/volumen/archivo?relacionado_con=${encodeURIComponent(id)}&limite=50`,
      { signal: control.signal },
    )
      .then((r) => setConsulta(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [servicio, id, puedeVer]);

  useEffect(cargar, [cargar]);

  async function devolver(fila: FilaArchivada) {
    try {
      await llamar(
        `/api/v1/${servicio}/volumen/desarchivar/${fila.registro_id}`,
        { metodo: "POST" },
      );
      setAviso(t("archivo.devuelto"));
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  // Un servicio sin archivo no tiene nada que enseñar aquí, y decirlo en cada
  // ficha sería ruido.
  if (!puedeVer || !consulta?.hay_archivo) {
    return fallo ? <Fallo error={fallo} /> : null;
  }
  return (
    <section className="card p-4" aria-label={t("archivo.delRegistro")}>
      <h3 className="section-label mb-1">
        {t("archivo.delRegistro")} · {cifra(consulta.cuantas)}
      </h3>
      <div role="status">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      <FilasArchivadas consulta={consulta} alDevolver={devolver} />
    </section>
  );
}
