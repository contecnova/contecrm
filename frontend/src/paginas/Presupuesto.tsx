/**
 * Un presupuesto: qué cambió, quién tiene que aprobarlo y a qué margen sale
 * (CRM-03.03.02.04, CRM-03.03.02.05, CRM-03.03.02.06).
 *
 * El listado enseña número, estado y total. Delante de un presupuesto lo que
 * se decide es si se manda, y eso son tres preguntas que una lista no
 * contesta.
 *
 * **«¿Qué he cambiado respecto de la anterior?»** Un presupuesto se renegocia
 * por versiones, y la versión nueva no se compara con la vieja a ojo: el
 * servidor dice línea a línea qué se añadió, qué se quitó y qué cambió de
 * cantidad, con el total antes y después. Mandar la tercera versión sin saber
 * qué lleva distinto de la segunda es como se acaba regalando un descuento que
 * nadie aprobó.
 *
 * **«¿Hace falta que alguien lo apruebe?»** Y sobre todo **por qué**: el
 * servidor devuelve los motivos, el umbral de descuento y el margen mínimo. Un
 * «necesita aprobación» a secas se lee como burocracia; «el descuento del 32 %
 * pasa del 25 declarado» se lee como un dato y se discute con él.
 *
 * **«¿A qué margen sale?»** El margen va **al lado del descuento**, porque es
 * la pareja que decide: un 30 % de descuento sobre algo con 60 de margen y
 * sobre algo con 12 son dos conversaciones distintas, y en la lista los dos
 * son «30 %».
 *
 * Y el documento se ve **antes de mandarlo**: la plantilla, la marca y el
 * idioma salen de la configuración, y descubrir en el correo del cliente que
 * salió con la marca equivocada no tiene arreglo.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

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
import { escalar, fecha, importe } from "@/lib/formato";

interface Presupuesto {
  id: string;
  numero: string;
  version: number;
  titulo: string;
  estado: string;
  moneda: string;
  subtotal: string;
  descuento_total: string;
  total: string;
  margen_pct: number | null;
  valido_hasta: string | null;
  marca: string | null;
  idioma: string | null;
  motivo_aprobacion: string | null;
}

interface Politica {
  necesita_aprobacion: boolean;
  /** El porqué, que es lo que convierte el aviso en un dato discutible. */
  motivos: string[];
  descuento_maximo: number | null;
  margen_pct: number | null;
  umbral_descuento: number | null;
  margen_minimo: number | null;
}

interface Cambio {
  linea: string;
  cambio: string;
  total?: string;
  cantidad_antes?: string;
  cantidad_ahora?: string;
  total_antes?: string;
  total_ahora?: string;
}

interface Cambios {
  version: number;
  /** Una primera versión no tiene con qué compararse, y se dice. */
  primera: boolean;
  total_antes?: string;
  total_ahora?: string;
  cambios: Cambio[];
}

interface Documento {
  plantilla: string;
  marca: string | null;
  idioma: string;
  numero: string;
  version: number;
  fecha: string;
  valido_hasta: string | null;
  titulo: string;
  moneda: string;
  lineas: { descripcion?: string; total?: string }[];
  subtotal: string;
  descuento_total: string;
  total: string;
  notas: string;
  condiciones: string;
}

export function Presupuesto() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [presupuesto, setPresupuesto] = useState<Presupuesto | null>(null);
  const [politica, setPolitica] = useState<Politica | null>(null);
  const [cambios, setCambios] = useState<Cambios | null>(null);
  const [documento, setDocumento] = useState<Documento | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const navegar = useNavigate();
  // Se edita lo que acompaña al presupuesto —título, notas, condiciones, hasta
  // cuándo vale—, no sus líneas: el precio se renegocia sacando una VERSIÓN
  // nueva, que es lo que deja comparar la tercera con la segunda. Quién puede
  // tocar qué y en qué estado lo decide el servidor, no esta pantalla.
  const modulo = moduloDe("oportunidades");
  const recurso = modulo ? recursoDe(modulo, "presupuesto") : undefined;
  const { ruta, puedeEditar, puedeBorrar } = useEdicion(recurso, id);

  const cargar = useCallback(() => {
    const control = new AbortController();
    const { signal } = control;
    setFallo(null);
    llamar<Presupuesto>(`/api/v1/presupuestos/${id}`, { signal })
      .then((r) => setPresupuesto(r.datos))
      .catch(salvoCancelacion(setFallo));
    llamar<Politica>(`/api/v1/presupuestos/${id}/politica-descuento`, { signal })
      .then((r) => setPolitica(r.datos))
      .catch(salvoCancelacion(() => setPolitica(null)));
    llamar<Cambios>(`/api/v1/presupuestos/${id}/cambios`, { signal })
      .then((r) => setCambios(r.datos))
      .catch(salvoCancelacion(() => setCambios(null)));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  const verDocumento = useCallback(() => {
    void llamar<Documento>(`/api/v1/presupuestos/${id}/documento`)
      .then((r) => setDocumento(r.datos))
      .catch(() => setDocumento(null));
  }, [id]);

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/m/oportunidades");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !presupuesto) return <Fallo error={fallo} reintentar={cargar} />;
  if (!presupuesto) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={presupuesto.titulo || presupuesto.numero}
        icono="request_quote"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <span className="chip-dato font-mono">{presupuesto.numero}</span>
            <span className="chip-dato">{presupuesto.estado}</span>
            <span className="text-2xs text-ink-muted">
              {t("presupuesto.version", { version: presupuesto.version })}
            </span>
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
          valores={presupuesto as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      {/* El aviso de aprobación arriba y CON SUS MOTIVOS: a secas se lee como
          burocracia, con el motivo se lee como un dato y se discute con él. */}
      {politica?.necesita_aprobacion ? (
        <div className="card mb-4 border-warning/40 p-3" role="status">
          <p className="text-2xs text-warning">{t("presupuesto.necesitaAprobacion")}</p>
          <ul className="mt-1 flex flex-col gap-1">
            {(politica.motivos ?? []).map((m, i) => (
              <li key={i} className="text-2xs text-ink">
                {m}
              </li>
            ))}
          </ul>
          <p className="mt-1 font-mono text-3xs text-ink-muted">
            {t("presupuesto.umbrales", {
              umbral: politica.umbral_descuento ?? "—",
              minimo: politica.margen_minimo ?? "—",
            })}
          </p>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-4">
          <h2 className="text-sm font-medium text-ink">{t("presupuesto.numeros")}</h2>
          <p className="mt-2 font-mono text-lg text-ink">
            {importe(presupuesto.total, presupuesto.moneda)}
          </p>
          {/* El descuento y el margen juntos: un 30 % sobre 60 de margen y
              sobre 12 son dos conversaciones distintas, y en la lista los dos
              son «30 %». */}
          <p className="mt-1 font-mono text-2xs text-ink">
            {t("presupuesto.descuentoYMargen", {
              // Los dos por el formateador: la API manda los decimales como
              // cadena —`Numeric` en JSON es texto para no perder precisión—
              // y pintados tal cual salen «0.00» y «49.67».
              descuento: importe(presupuesto.descuento_total, presupuesto.moneda),
              margen:
                presupuesto.margen_pct === null
                  ? t("presupuesto.sinMargen")
                  : `${escalar(presupuesto.margen_pct)} %`,
            })}
          </p>
          {presupuesto.margen_pct === null ? (
            <p className="mt-1 text-3xs text-ink-faint">{t("presupuesto.porqueSinMargen")}</p>
          ) : null}
          {presupuesto.valido_hasta ? (
            <p className="mt-2 text-2xs text-ink-muted">
              {t("presupuesto.valido", {
                fecha: fecha(presupuesto.valido_hasta),
              })}
            </p>
          ) : null}
        </section>

        <section className="card p-4">
          <h2 className="text-sm font-medium text-ink">{t("presupuesto.queCambio")}</h2>
          <p className="mt-1 text-3xs text-ink-faint">{t("presupuesto.porqueCambios")}</p>
          {!cambios ? (
            <Vacio titulo={t("presupuesto.sinCambios")} detalle="" />
          ) : cambios.primera ? (
            <p className="mt-2 text-2xs text-ink-muted">{t("presupuesto.esLaPrimera")}</p>
          ) : (
            <>
              <p className="mt-2 font-mono text-2xs text-ink">
                {t("presupuesto.totalAntesDespues", {
                  antes: cambios.total_antes ?? "—",
                  ahora: cambios.total_ahora ?? "—",
                })}
              </p>
              <ul className="lista-acotada mt-2 flex flex-col gap-1 pr-1">
                {(cambios.cambios ?? []).map((c, i) => (
                  <li key={`${c.linea}-${i}`} className="flex items-baseline gap-2">
                    <span className="chip-dato">{c.cambio}</span>
                    <span className="flex-1 text-2xs text-ink">{c.linea}</span>
                    {c.cantidad_antes !== undefined ? (
                      <span className="font-mono text-3xs text-ink-muted">
                        {t("presupuesto.deA", {
                          antes: c.cantidad_antes,
                          ahora: c.cantidad_ahora,
                        })}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="card p-4 lg:col-span-2">
          <h2 className="text-sm font-medium text-ink">{t("presupuesto.documento")}</h2>
          <p className="mt-1 text-3xs text-ink-faint">{t("presupuesto.porqueDocumento")}</p>
          {!documento ? (
            <button type="button" className="btn-secundario mt-2" onClick={verDocumento}>
              {t("presupuesto.verDocumento")}
            </button>
          ) : (
            <div className="mt-2" role="status" aria-live="polite">
              {/* La marca y el idioma delante: descubrir en el correo del
                  cliente que salió con la marca equivocada no tiene arreglo. */}
              <p className="font-mono text-2xs text-ink">
                {t("presupuesto.conQueSale", {
                  plantilla: documento.plantilla,
                  marca: documento.marca ?? t("presupuesto.sinMarca"),
                  idioma: documento.idioma,
                })}
              </p>
              <p className="mt-1 text-3xs text-ink-muted">
                {t("presupuesto.lineasDelDocumento", {
                  cuantas: (documento.lineas ?? []).length,
                })}
              </p>
              {documento.condiciones ? (
                <p className="mt-2 text-3xs text-ink-faint">{documento.condiciones}</p>
              ) : null}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
