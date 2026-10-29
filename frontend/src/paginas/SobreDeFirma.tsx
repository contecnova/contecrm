/**
 * Un sobre de firma: quién firma, en qué orden y si la firma es defendible
 * (CRM-06.01.02.01, CRM-06.01.02.07).
 *
 * El listado enseñaba el estado y la referencia. Delante de un sobre la
 * pregunta no es si está firmado: es **si esa firma se sostiene** el día que
 * alguien la discuta.
 *
 * Por eso el panel que manda es el de la evidencia, y dentro de él
 * `verificable`: una firma a la que le falta el hash de lo enviado o el de lo
 * firmado **no se puede verificar**, y eso no se nota mirando el estado —pone
 * «firmado» igual—. Es la diferencia entre un documento firmado y un documento
 * que parece firmado.
 *
 * **Y el nivel eIDAS va delante.** Una firma simple y una cualificada valen lo
 * mismo en la pantalla y no valen lo mismo ante un juez, y el que la manda
 * elige el nivel al configurar la regla, no al firmar.
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

interface Firmante {
  nombre: string;
  email: string;
  papel: string;
  identificacion: string | null;
  estado: string;
  firmado_at: string | null;
  motivo_rechazo: string | null;
}

interface Evidencia {
  referencia: string | null;
  proveedor: string | null;
  nivel: string | null;
  estado: string;
  documento_id: string | null;
  documento_firmado_id: string | null;
  certificado_id: string | null;
  sello_tiempo: string | null;
  hash_enviado: string | null;
  hash_firmado: string | null;
  /** Lo único que dice si esta firma se sostiene al discutirla. */
  verificable: boolean;
  firmantes: Firmante[];
  eventos: { tipo: string; descripcion: string | null; firmante: string | null }[];
}

export function SobreDeFirma() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [evidencia, setEvidencia] = useState<Evidencia | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const navegar = useNavigate();
  // La edición existía en la ficha genérica y no se pierde al traerse el
  // sobre a su propia pantalla: el contrato publica `PATCH`, y quitarla aquí
  // sería retirar algo que funcionaba sin que nadie lo decidiera.
  const modulo = moduloDe("operacion");
  const recurso = modulo ? recursoDe(modulo, "sobre_firma") : undefined;
  const { ruta, puedeEditar, puedeBorrar } = useEdicion(recurso, id);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Evidencia>(`/api/v1/firma/sobres/${id}/evidencia`, {
      signal: control.signal,
    })
      .then((r) => setEvidencia(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/m/operacion");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !evidencia) return <Fallo error={fallo} reintentar={cargar} />;
  if (!evidencia) return <Cargando />;

  const firmantes = evidencia.firmantes ?? [];
  const eventos = evidencia.eventos ?? [];

  return (
    <>
      <CabeceraPagina
        titulo={evidencia.referencia ?? t("sobre.sinReferencia")}
        icono="draw"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <span className="chip-dato">{evidencia.estado}</span>
            {/* El nivel eIDAS delante: una simple y una cualificada valen lo
                mismo en pantalla y no valen lo mismo ante un juez. */}
            {evidencia.nivel ? (
              <span className="badge badge-muted">{evidencia.nivel}</span>
            ) : null}
            {evidencia.proveedor ? (
              <span className="text-2xs text-ink-muted">{evidencia.proveedor}</span>
            ) : null}
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
          valores={evidencia as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      {/* El veredicto, arriba. Una firma sin los dos hashes no se puede
          verificar, y el estado pone «firmado» igual. */}
      <p
        className={
          evidencia.verificable
            ? "card mb-4 border-success/40 p-3 text-2xs text-success"
            : "card mb-4 border-danger/40 p-3 text-2xs text-danger"
        }
      >
        {evidencia.verificable ? t("sobre.verificable") : t("sobre.noVerificable")}
      </p>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-4">
          <h2 className="section-label mb-1">{t("sobre.firmantes")}</h2>
          {firmantes.length === 0 ? (
            <Vacio titulo={t("sobre.sinFirmantes")} compacto />
          ) : (
            <ol className="divide-y divide-ink-dim/30">
              {firmantes.map((f, i) => (
                <li key={`${f.email}-${i}`} className="py-1.5">
                  <div className="flex flex-wrap items-baseline gap-x-3 text-2xs">
                    <span className="font-medium text-ink">{f.nombre || f.email}</span>
                    <span className="chip-dato">{f.papel}</span>
                    <span
                      className={
                        f.estado === "firmado" ? "chip-dato chip-dato--si" : "chip-dato"
                      }
                    >
                      {f.estado}
                    </span>
                  </div>
                  {/* Cómo se le identificó: una firma sin identificación es
                      una casilla marcada por alguien con acceso al correo. */}
                  {f.identificacion ? (
                    <p className="text-3xs text-ink-faint">
                      {t("sobre.identificado", { como: f.identificacion })}
                    </p>
                  ) : (
                    <p className="text-3xs text-warning">{t("sobre.sinIdentificar")}</p>
                  )}
                  {f.motivo_rechazo ? (
                    <p className="text-3xs text-danger">{f.motivo_rechazo}</p>
                  ) : null}
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="card p-4">
          <h2 className="section-label mb-1">{t("sobre.prueba")}</h2>
          <dl className="space-y-1 text-3xs">
            <Dato clave={t("sobre.selloTiempo")} valor={evidencia.sello_tiempo} />
            <Dato clave={t("sobre.hashEnviado")} valor={evidencia.hash_enviado} />
            <Dato clave={t("sobre.hashFirmado")} valor={evidencia.hash_firmado} />
            <Dato clave={t("sobre.certificado")} valor={evidencia.certificado_id} />
            <Dato
              clave={t("sobre.documentoFirmado")}
              valor={evidencia.documento_firmado_id}
            />
          </dl>
        </section>
      </div>

      <section className="card mt-4 p-4">
        <h2 className="section-label mb-1">{t("sobre.eventos")}</h2>
        {eventos.length === 0 ? (
          <Vacio titulo={t("sobre.sinEventos")} compacto />
        ) : (
          <ol className="lista-acotada divide-y divide-ink-dim/30 pr-1">
            {eventos.map((e, i) => (
              <li key={`${e.tipo}-${i}`} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
                <span className="text-2xs font-medium text-ink">{e.tipo}</span>
                {e.firmante ? (
                  <span className="text-3xs text-ink-faint">{e.firmante}</span>
                ) : null}
                {e.descripcion ? (
                  <span className="text-3xs text-ink-muted">{e.descripcion}</span>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>
    </>
  );
}

/** Un dato de la prueba, que si falta se dice en vez de dejar el hueco. */
function Dato({ clave, valor }: { clave: string; valor: string | null }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-ink-faint">{clave}</dt>
      <dd className={valor ? "truncate text-ink-muted" : "text-warning"}>
        {valor ?? t("sobre.falta")}
      </dd>
    </div>
  );
}
