/**
 * Una orden de trabajo: quién paga cada línea y qué se firmó
 * (CRM-04.04.01.02, CRM-04.04.01.06).
 *
 * **El reparto de cobertura va en tres cestas, no en dos.** Lo que paga el
 * cliente, lo que se le reclama al fabricante y lo que **no se sabe todavía**.
 * Fundir la tercera con cualquiera de las otras es facturar de más o perder
 * una reclamación, y las dos se descubren tarde: una en la factura del cliente
 * y la otra cuando la garantía ya ha vencido.
 *
 * **Y el parte dice si se tocó después de firmar.** El parte guarda una huella
 * de su contenido al firmarse; si ya no cuadra, alguien lo cambió después. Eso
 * convierte una firma del cliente en un papel sin valor, y no se nota mirando
 * el parte: se ve igual de completo.
 *
 * **Quién puede hacerla, con el porqué de los que no.** La lista de descartados
 * es la mitad del valor: «nadie disponible» no se puede accionar, y «los tres
 * con la competencia están fuera de zona» sí — se amplía la zona o se manda a
 * alguien a formarse.
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

interface Linea {
  id: string;
  tipo: string;
  concepto: string;
  cantidad: string;
  unidad: string | null;
  facturable: boolean;
  /** `null` es «no se sabe», y no se funde con ninguna de las otras dos. */
  cubierto_garantia: boolean | null;
  nota_cobertura: string | null;
}

interface Parte {
  resumen: string;
  diagnostico: string;
  checklist: unknown[];
  evidencias: unknown[];
  firmado: boolean;
  conforme: boolean | null;
  huella: string | null;
  /** La huella ya no cuadra: el parte se tocó después de firmar. */
  alterado_tras_firmar: boolean;
}

interface Orden {
  id: string;
  codigo: string;
  titulo: string;
  tipo: string;
  estado: string;
  tecnico_id: string | null;
  activo_id: string | null;
  cita_desde: string | null;
  minutos_trabajados: number;
  lineas: Linea[];
  a_facturar: number;
  a_garantia: number;
  /** La tercera cesta: ni facturado ni reclamado, pendiente de decidir. */
  sin_determinar: number;
  parte: Parte | null;
}

interface Descartado {
  tecnico_id: string;
  porque: string;
}

interface Candidatos {
  orden_id: string;
  competencias_requeridas: string[];
  aptos: { tecnico_id: string; nombre?: string }[];
  /** La mitad del valor: «nadie disponible» no se acciona, el porqué sí. */
  descartados: Descartado[];
  hay_candidatos: boolean;
}

export function OrdenDeTrabajo() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [orden, setOrden] = useState<Orden | null>(null);
  const [candidatos, setCandidatos] = useState<Candidatos | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const navegar = useNavigate();
  const modulo = moduloDe("campo");
  const recurso = modulo ? recursoDe(modulo, "ordenes-trabajo") : undefined;
  const { ruta, puedeEditar, puedeBorrar } = useEdicion(recurso, id);

  const cargar = useCallback(() => {
    const control = new AbortController();
    const { signal } = control;
    setFallo(null);
    llamar<Orden>(`/api/v1/ordenes-trabajo/${id}`, { signal })
      .then((r) => setOrden(r.datos))
      .catch(salvoCancelacion(setFallo));
    llamar<Candidatos>(`/api/v1/ordenes-trabajo/${id}/candidatos`, { signal })
      .then((r) => setCandidatos(r.datos))
      .catch(salvoCancelacion(() => setCandidatos(null)));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/m/campo");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !orden) return <Fallo error={fallo} reintentar={cargar} />;
  if (!orden) return <Cargando />;

  const parte = orden.parte;
  const descartados = candidatos?.descartados ?? [];

  return (
    <>
      <CabeceraPagina
        titulo={orden.titulo}
        icono="handyman"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <span className="chip-dato font-mono">{orden.codigo}</span>
            <span className="chip-dato">{orden.estado}</span>
            <span className="text-2xs text-ink-muted">
              {t("orden.trabajado", { minutos: orden.minutos_trabajados })}
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
          valores={orden as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      {/* Lo que invalida una firma, arriba del todo. */}
      {parte?.alterado_tras_firmar ? (
        <p className="card mb-4 border-danger/40 p-3 text-2xs text-danger" role="status">
          {t("orden.alterado")}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-4">
          <h2 className="text-sm font-medium text-ink">{t("orden.quienPaga")}</h2>
          <p className="mt-1 text-3xs text-ink-faint">{t("orden.porqueTresCestas")}</p>
          <p className="mt-2 font-mono text-2xs text-ink">
            {t("orden.cestas", {
              facturar: orden.a_facturar,
              garantia: orden.a_garantia,
            })}
          </p>
          {/* La tercera, aparte y señalada: es la que cuesta dinero si se
              funde con cualquiera de las otras dos. */}
          {orden.sin_determinar > 0 ? (
            <p className="mt-1 text-2xs text-warning">
              {t("orden.sinDeterminar", { cuantas: orden.sin_determinar })}
            </p>
          ) : null}
          <ul className="lista-acotada mt-2 flex flex-col gap-1 pr-1">
            {(orden.lineas ?? []).map((l) => (
              <li key={l.id} className="flex flex-wrap items-baseline gap-2">
                <span className="chip-dato">{l.tipo}</span>
                <span className="flex-1 text-2xs text-ink">{l.concepto}</span>
                <span className="font-mono text-3xs text-ink-muted">
                  {l.cantidad} {l.unidad ?? ""}
                </span>
                <span
                  className={
                    l.cubierto_garantia === null
                      ? "badge badge-aviso"
                      : "chip-dato"
                  }
                >
                  {t(
                    l.cubierto_garantia === null
                      ? "orden.porDecidir"
                      : l.cubierto_garantia
                        ? "orden.aGarantia"
                        : "orden.aFacturar",
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="card p-4">
          <h2 className="text-sm font-medium text-ink">{t("orden.parte")}</h2>
          {!parte ? (
            <Vacio titulo={t("orden.sinParte")} detalle={t("orden.sinParteDetalle")} />
          ) : (
            <>
              <p className="mt-2 text-2xs text-ink">{parte.resumen}</p>
              {parte.diagnostico ? (
                <p className="mt-1 text-2xs text-ink-muted">{parte.diagnostico}</p>
              ) : null}
              <p className="mt-2 font-mono text-3xs text-ink-muted">
                {t("orden.evidencias", {
                  checklist: (parte.checklist ?? []).length,
                  evidencias: (parte.evidencias ?? []).length,
                })}
              </p>
              {/* Firmado y conforme son dos cosas: un cliente puede firmar
                  que estuvimos y no estar conforme con el resultado. */}
              <p className="mt-1 text-2xs text-ink">
                {parte.firmado
                  ? parte.conforme === false
                    ? t("orden.firmadoNoConforme")
                    : t("orden.firmado")
                  : t("orden.sinFirmar")}
              </p>
            </>
          )}
        </section>

        <section className="card p-4 lg:col-span-2">
          <h2 className="text-sm font-medium text-ink">{t("orden.quienPuede")}</h2>
          <p className="mt-1 text-3xs text-ink-faint">{t("orden.porqueDescartados")}</p>
          {!candidatos ? (
            <Vacio titulo={t("orden.sinCandidatos")} detalle="" />
          ) : (
            <>
              <p className="mt-2 font-mono text-3xs text-ink-muted">
                {t("orden.competencias", {
                  competencias:
                    (candidatos.competencias_requeridas ?? []).join(", ") ||
                    t("orden.ninguna"),
                })}
              </p>
              {!candidatos.hay_candidatos ? (
                <p className="mt-1 text-2xs text-warning">{t("orden.nadieApto")}</p>
              ) : (
                <p className="mt-1 text-2xs text-ink">
                  {t("orden.aptos", { cuantos: (candidatos.aptos ?? []).length })}
                </p>
              )}
              {/* El porqué de cada descartado: es lo que se puede arreglar. */}
              {descartados.length > 0 ? (
                <ul className="lista-acotada mt-2 flex flex-col gap-1 pr-1">
                  {descartados.map((d, i) => (
                    <li key={`${d.tecnico_id}-${i}`} className="flex items-baseline gap-2">
                      <span className="font-mono text-3xs text-ink">{d.tecnico_id}</span>
                      <span className="flex-1 text-2xs text-ink-muted">{d.porque}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          )}
        </section>
      </div>

      {orden.activo_id ? (
        <p className="mt-4 text-2xs">
          <Link className="btn-link" to={`/m/campo/activo/${orden.activo_id}`}>
            {t("orden.verActivo")}
          </Link>
        </p>
      ) : null}
    </>
  );
}
