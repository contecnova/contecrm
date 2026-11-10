/**
 * Generar un documento desde la ficha del registro (CRM-06.01.01.06).
 *
 * Medido el 10-11-2026: la generación desde plantilla funcionaba, pero sólo
 * desde Operación, con los datos escritos a mano y saliendo texto. Aquí se
 * elige la plantilla, **el servidor rellena lo que el registro ya sabe** —el
 * registro, su cuenta, su contacto, sus líneas— y la persona sólo revisa y
 * completa lo que falte. Lo que falta se dice antes de generar, marcador por
 * marcador: un documento con un hueco callado se manda igual que uno completo.
 *
 * Sale un PDF con la marca y el idioma de la plantilla y queda **como adjunto
 * del registro**. Si el corpus documental responde, se archiva además allí; si
 * no, se dice por qué, sin tratarlo como un fallo: el documento ya está
 * guardado.
 *
 * Se esconde entero en los tipos de registro desde los que no se genera: la
 * lista la decide la configuración del servidor (`documento_fuentes`), no esta
 * pantalla.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { PanelRelacionado } from "@/componentes/PanelRelacionado";
import { ErrorApi, llamar, salvoCancelacion } from "@/lib/api";
import { config } from "@/lib/config";

interface PlantillaCorta {
  clave: string;
  nombre: string;
  tipo: string;
  idioma: string;
  marca: string;
  version: number;
  marcadores: string[];
}

interface Marcador {
  marcador: string;
  valor: string;
  origen: "registro" | "a_mano" | "falta";
  campo: string;
}

interface Preparado {
  plantilla: {
    clave: string;
    version: number;
    nombre: string;
    idioma: string;
    marca: string;
  };
  marcadores: Marcador[];
  faltan: string[];
  avisos: string[];
  lineas: number;
}

interface Generado {
  adjunto: { id: string; nombre: string; objeto: string; descargar: string };
  corpus: { archivado: boolean; motivo: string };
  aviso: string;
  avisos: string[];
}

export function GenerarDocumento({
  objeto,
  id,
  alGenerar,
}: {
  objeto: string;
  id: string;
  /** Para que la ficha recargue sus adjuntos: el PDF acaba de llegar ahí. */
  alGenerar?: () => void;
}) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const [lista, setLista] = useState<{
    admitido: boolean;
    plantillas: PlantillaCorta[];
  } | null>(null);
  const [clave, setClave] = useState("");
  const [preparado, setPreparado] = useState<Preparado | null>(null);
  const [valores, setValores] = useState<Record<string, string>>({});
  const [generado, setGenerado] = useState<Generado | null>(null);
  const [enCurso, setEnCurso] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<{ admitido: boolean; plantillas: PlantillaCorta[] }>(
      `/api/v1/plantillas-documento/para/${encodeURIComponent(objeto)}`,
      { signal: control.signal },
    )
      .then((r) => {
        setLista(r.datos);
        const [unica] = r.datos.plantillas;
        if (r.datos.plantillas.length === 1 && unica) setClave(unica.clave);
      })
      .catch(
        salvoCancelacion((e) => {
          // Sin permiso para generar, el panel no se pinta: no es un fallo de
          // la ficha, es que esta persona no cuelga documentos. Cualquier otro
          // error SÍ se enseña: esconderlo sería decir «aquí no se genera».
          if (e instanceof ErrorApi && e.estado === 403) {
            setLista({ admitido: false, plantillas: [] });
            return;
          }
          setLista({ admitido: true, plantillas: [] });
          setFallo(e);
        }),
      );
    return () => control.abort();
  }, [objeto]);

  async function preparar(elegida: string) {
    setEnCurso(true);
    setFallo(null);
    setGenerado(null);
    try {
      const r = await llamar<Preparado>(
        "/api/v1/plantillas-documento/desde-registro/preparar",
        {
          metodo: "POST",
          cuerpo: { clave: elegida, objeto, objeto_id: id },
        },
      );
      setPreparado(r.datos);
      setValores(
        Object.fromEntries(
          r.datos.marcadores.map((m) => [m.marcador, m.valor]),
        ),
      );
    } catch (e) {
      setFallo(e);
    } finally {
      setEnCurso(false);
    }
  }

  async function generar() {
    if (!preparado) return;
    setEnCurso(true);
    setFallo(null);
    // Sólo lo que la persona ha tocado: lo demás lo vuelve a leer el servidor
    // del registro, que es la fuente buena si alguien lo cambió entretanto.
    const aMano = Object.fromEntries(
      preparado.marcadores
        .filter((m) => (valores[m.marcador] ?? "") !== m.valor)
        .map((m) => [m.marcador, valores[m.marcador] ?? ""]),
    );
    try {
      const r = await llamar<Generado>(
        "/api/v1/plantillas-documento/desde-registro/generar",
        {
          metodo: "POST",
          cuerpo: {
            clave: preparado.plantilla.clave,
            objeto,
            objeto_id: id,
            datos: aMano,
          },
        },
      );
      setGenerado(r.datos);
      alGenerar?.();
    } catch (e) {
      setFallo(e);
    } finally {
      setEnCurso(false);
    }
  }

  if (lista && !lista.admitido) return null;

  const pendientes = preparado
    ? preparado.marcadores
        .filter((m) => !(valores[m.marcador] ?? "").trim())
        .map((m) => m.marcador)
    : [];

  return (
    <PanelRelacionado
      nombre={t("generarDocumento.titulo")}
      cuantos={lista?.plantillas.length}
      abierto={abierto}
      alAlternar={() => setAbierto((v) => !v)}
    >
      <div className="flex flex-col gap-3" data-testid="generar-documento">
        <p className="text-rotulo text-ink-faint">
          {t("generarDocumento.porque")}
        </p>
        {lista === null ? (
          <Cargando />
        ) : lista.plantillas.length === 0 ? (
          <Vacio
            compacto
            titulo={t("generarDocumento.sinPlantillas")}
            detalle={t("generarDocumento.sinPlantillasDetalle")}
          />
        ) : (
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex min-w-[14rem] flex-1 flex-col gap-1 text-rotulo text-ink-muted">
              {t("generarDocumento.plantilla")}
              <select
                className="input-base"
                value={clave}
                onChange={(e) => {
                  setClave(e.target.value);
                  setPreparado(null);
                  setGenerado(null);
                }}
              >
                <option value="">{t("generarDocumento.elegir")}</option>
                {lista.plantillas.map((p) => (
                  <option key={p.clave} value={p.clave}>
                    {t("generarDocumento.opcion", {
                      nombre: p.nombre,
                      idioma: p.idioma,
                      version: p.version,
                    })}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn-secondary"
              disabled={!clave || enCurso}
              onClick={() => void preparar(clave)}
            >
              <Icono nombre="auto_fix_high" tamano="sm" />
              {t("generarDocumento.rellenar")}
            </button>
          </div>
        )}

        {fallo ? <Fallo error={fallo} /> : null}

        {preparado ? (
          <div className="flex flex-col gap-2">
            <p className="text-dato text-ink-muted">
              {t("generarDocumento.conQueSale", {
                marca:
                  preparado.plantilla.marca ||
                  t("generarDocumento.marcaDelTenant"),
                idioma: preparado.plantilla.idioma,
                lineas: preparado.lineas,
              })}
            </p>
            {pendientes.length ? (
              <p
                role="status"
                className="flex items-start gap-1.5 text-dato text-warning"
              >
                <Icono nombre="warning" tamano="sm" />
                <span>
                  {t("generarDocumento.faltan", {
                    cuantos: pendientes.length,
                    cuales: pendientes.join(", "),
                  })}
                </span>
              </p>
            ) : (
              <p
                role="status"
                className="flex items-center gap-1.5 text-dato text-success"
              >
                <Icono nombre="check_circle" tamano="sm" />
                {t("generarDocumento.completo")}
              </p>
            )}
            {preparado.avisos.length ? (
              <ul className="list-disc pl-5 text-rotulo text-ink-faint">
                {preparado.avisos.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            ) : null}
            <ul className="flex flex-col gap-2">
              {preparado.marcadores.map((m) => {
                const vacio = !(valores[m.marcador] ?? "").trim();
                const tocado = (valores[m.marcador] ?? "") !== m.valor;
                return (
                  <li key={m.marcador} className="flex flex-col gap-1">
                    <label
                      htmlFor={`marcador-${m.marcador}`}
                      className="flex flex-wrap items-center gap-2 text-rotulo text-ink-muted"
                    >
                      <span className="font-mono">{`{{${m.marcador}}}`}</span>
                      {vacio ? (
                        <span className="badge badge-warning">
                          {t("generarDocumento.falta")}
                        </span>
                      ) : tocado ? (
                        <span className="badge badge-accent">
                          {t("generarDocumento.aMano")}
                        </span>
                      ) : m.campo ? (
                        <span className="truncate text-ink-faint">
                          {t("generarDocumento.delRegistro", {
                            campo: m.campo,
                          })}
                        </span>
                      ) : null}
                    </label>
                    <input
                      id={`marcador-${m.marcador}`}
                      className="input-base"
                      value={valores[m.marcador] ?? ""}
                      onChange={(e) =>
                        setValores((v) => ({
                          ...v,
                          [m.marcador]: e.target.value,
                        }))
                      }
                    />
                  </li>
                );
              })}
            </ul>
            <div>
              <button
                type="button"
                className="btn-primary"
                disabled={enCurso || pendientes.length > 0}
                onClick={() => void generar()}
              >
                <Icono nombre="picture_as_pdf" tamano="sm" />
                {enCurso
                  ? t("generarDocumento.generando")
                  : t("generarDocumento.generar")}
              </button>
            </div>
          </div>
        ) : null}

        {generado ? (
          <div className="flex flex-col gap-1" role="status" aria-live="polite">
            <p className="flex items-center gap-1.5 text-dato text-success">
              <Icono nombre="check_circle" tamano="sm" />
              <span>{t("generarDocumento.guardado")}</span>
              <a
                className="truncate text-accent hover:underline"
                href={`${config().apiBase}${generado.adjunto.descargar}`}
              >
                {generado.adjunto.nombre}
              </a>
            </p>
            {generado.corpus.archivado ? (
              <p className="text-rotulo text-ink-muted">
                {t("generarDocumento.archivado")}
              </p>
            ) : (
              <p className="text-rotulo text-ink-muted">
                {t("generarDocumento.sinArchivar", {
                  motivo: generado.corpus.motivo,
                })}
              </p>
            )}
          </div>
        ) : null}
      </div>
    </PanelRelacionado>
  );
}
