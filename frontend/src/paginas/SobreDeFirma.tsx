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
import { Icono } from "@/componentes/Icono";
import { DatosClave } from "@/componentes/DatosClave";
import { DetallesDelRegistro } from "@/componentes/DetallesDelRegistro";
import { PestanasDeFicha } from "@/componentes/PestanasDeFicha";
import { llamar, salvoCancelacion } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { useSuperficie } from "@/lib/permisos";
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
  eventos: {
    tipo: string;
    descripcion: string | null;
    firmante: string | null;
  }[];
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
  const { ruta, puedeEditar, puedeBorrar, borrado } = useEdicion(recurso, id);
  // Las mismas dos pestañas que las demás fichas: «Relacionado» es lo que
  // esta pantalla ya enseñaba y «Detalles» son los campos del registro, que
  // hasta hoy sólo se leían entrando a editar.
  const [pestana, setPestana] = useState<"relacionado" | "detalles">(
    "relacionado",
  );

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
      <DatosClave
        recurso={recurso}
        tipo="sobre_firma"
        // Las insignias llevan sólo lo que NO es columna preferida del
        // recurso: ésas salen como dato clave aquí mismo, y escribirlas
        // además como insignia las pone dos veces en el mismo panel.
        nombre={evidencia.referencia ?? t("sobre.sinReferencia")}
        fila={evidencia as unknown as Record<string, unknown>}
        volverA={{ a: "/m/operacion", titulo: modulo?.titulo ?? "", id }}
        acciones={
          !editando ? (
            <BotonesDeRegistro
              puedeEditar={puedeEditar}
              puedeBorrar={puedeBorrar}
              borrado={borrado}
              alEditar={() => setEditando(true)}
              alBorrar={() => setConfirmando(true)}
            />
          ) : null
        }
      />

      {!editando ? (
        <AccionesDelSobre id={id} estado={evidencia.estado} alHacer={cargar} />
      ) : null}

      {confirmando ? (
        <ConfirmarBorrado
          borrado={borrado}
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

      {!editando ? (
        <PestanasDeFicha
          tipo="sobre_firma"
          id={id ?? ""}

          etiqueta={t("ficha.secciones")}
          pestanas={[
            { clave: "relacionado", nombre: t("ficha.relacionado") },
            { clave: "detalles", nombre: t("ficha.detalles") },
          ]}
          activa={pestana}
          alElegir={(clave) => setPestana(clave as "relacionado" | "detalles")}
        />
      ) : null}

      <div className="mt-4">
        {editando || pestana === "relacionado" ? (
          <>
            {/* El veredicto, arriba. Una firma sin los dos hashes no se puede
            verificar, y el estado pone «firmado» igual. */}
            <p
              className={
                evidencia.verificable
                  ? "card mb-4 border-success/40 p-3 text-dato text-success"
                  : "card mb-4 border-danger/40 p-3 text-dato text-danger"
              }
            >
              {evidencia.verificable
                ? t("sobre.verificable")
                : t("sobre.noVerificable")}
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
                        <div className="flex flex-wrap items-baseline gap-x-3 text-dato">
                          <span className="font-medium text-ink">
                            {f.nombre || f.email}
                          </span>
                          <span className="chip-dato">{f.papel}</span>
                          <span
                            className={
                              f.estado === "firmado"
                                ? "chip-dato chip-dato--si"
                                : "chip-dato"
                            }
                          >
                            {f.estado}
                          </span>
                        </div>
                        {/* Cómo se le identificó: una firma sin identificación es
                        una casilla marcada por alguien con acceso al correo. */}
                        {f.identificacion ? (
                          <p className="text-rotulo text-ink-faint">
                            {t("sobre.identificado", {
                              como: f.identificacion,
                            })}
                          </p>
                        ) : (
                          <p className="text-rotulo text-warning">
                            {t("sobre.sinIdentificar")}
                          </p>
                        )}
                        {f.motivo_rechazo ? (
                          <p className="text-rotulo text-danger">
                            {f.motivo_rechazo}
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                )}
              </section>

              <section className="card p-4">
                <h2 className="section-label mb-1">{t("sobre.prueba")}</h2>
                <dl className="space-y-1 text-rotulo">
                  <Dato
                    clave={t("sobre.selloTiempo")}
                    valor={evidencia.sello_tiempo}
                  />
                  <Dato
                    clave={t("sobre.hashEnviado")}
                    valor={evidencia.hash_enviado}
                  />
                  <Dato
                    clave={t("sobre.hashFirmado")}
                    valor={evidencia.hash_firmado}
                  />
                  <Dato
                    clave={t("sobre.certificado")}
                    valor={evidencia.certificado_id}
                  />
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
                    <li
                      key={`${e.tipo}-${i}`}
                      className="flex flex-wrap items-baseline gap-x-3 py-1.5"
                    >
                      <span className="text-dato font-medium text-ink">
                        {e.tipo}
                      </span>
                      {e.firmante ? (
                        <span className="text-rotulo text-ink-faint">
                          {e.firmante}
                        </span>
                      ) : null}
                      {e.descripcion ? (
                        <span className="text-rotulo text-ink-muted">
                          {e.descripcion}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </>
        ) : (
          <DetallesDelRegistro
            ruta={ruta}
            objeto="sobre_firma"
            servicio={recurso?.servicio ?? ""}
            id={id}
          />
        )}
      </div>
    </>
  );
}

/** Lo que se puede hacer con el sobre en su estado, y en ninguno más. */
const ACCIONES_POR_ESTADO: Record<string, Accion[]> = {
  borrador: ["enviar", "cancelar"],
  enviado: ["recordar", "cancelar"],
  en_curso: ["recordar", "cancelar"],
  completado: ["archivar"],
};

type Accion = "enviar" | "recordar" | "cancelar" | "archivar";

/**
 * Mandar, recordar, cancelar y archivar el firmado (CRM-06.01.02.11).
 *
 * Las cuatro rutas existían y la ficha sólo cargaba la evidencia: un sobre
 * preparado se quedaba en borrador para siempre salvo que alguien llamara a la
 * API. Se ofrecen **según el estado**, que es lo que decide el servidor: un
 * «Enviar» sobre un sobre ya enviado contesta 409, y ofrecerlo enseña a
 * desconfiar de los botones.
 *
 * Mandar pide confirmar: le llega un correo al cliente y no se deshace. Y lo
 * que contesta cada acción se dice aquí —a quién se recordó, hasta cuándo
 * vale—, porque «hecho» sin más no deja saber si salió.
 */
function AccionesDelSobre({
  id,
  estado,
  alHacer,
}: {
  id: string;
  estado: string;
  alHacer: () => void;
}) {
  const { t } = useTranslation();
  const { tiene } = useSuperficie();
  const [abierta, setAbierta] = useState<Accion | null>(null);
  const [motivo, setMotivo] = useState("");
  const [firmado, setFirmado] = useState("");
  const [certificado, setCertificado] = useState("");
  const [sello, setSello] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  const posibles = ACCIONES_POR_ESTADO[estado] ?? [];
  if (!tiene("firma:write") || (posibles.length === 0 && !resultado)) {
    return null;
  }

  const ICONOS: Record<Accion, string> = {
    enviar: "send",
    recordar: "notifications_active",
    cancelar: "cancel",
    archivar: "inventory_2",
  };

  async function hacer(accion: Accion) {
    setEnviando(true);
    setFallo(null);
    setResultado("");
    const base = `/api/v1/firma/sobres/${id}`;
    try {
      if (accion === "enviar") {
        const r = await llamar<{ estado: string; caduca_at: string }>(
          `${base}/enviar`,
          { metodo: "POST" },
        );
        setResultado(
          t("sobre.acciones.enviado", {
            estado: r.datos.estado,
            caduca: fechaHora(r.datos.caduca_at),
          }),
        );
      } else if (accion === "recordar") {
        const r = await llamar<{ recordados: string[]; medible: boolean }>(
          `${base}/recordar`,
          { metodo: "POST", cuerpo: {} },
        );
        setResultado(
          r.datos.recordados.length
            ? t("sobre.acciones.recordado", {
                quienes: r.datos.recordados.join(", "),
              })
            : t("sobre.acciones.nadieQueRecordar"),
        );
      } else if (accion === "cancelar") {
        await llamar(`${base}/cancelar`, {
          metodo: "POST",
          cuerpo: { motivo: motivo.trim() },
        });
        setResultado(t("sobre.acciones.cancelado"));
      } else {
        const r = await llamar<{ enlazados: string[]; sin_origen: boolean }>(
          `${base}/archivar-firmado`,
          {
            metodo: "POST",
            cuerpo: {
              documento_firmado_id: firmado.trim(),
              certificado_id: certificado.trim(),
              sello_tiempo: sello.trim(),
            },
          },
        );
        setResultado(
          r.datos.sin_origen
            ? t("sobre.acciones.archivadoSinOrigen")
            : t("sobre.acciones.archivado", { n: r.datos.enlazados.length }),
        );
      }
      setAbierta(null);
      setMotivo("");
      alHacer();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="card mb-4 p-4" aria-labelledby="acciones-sobre">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="acciones-sobre" className="section-label">
          {t("sobre.acciones.titulo")}
        </h2>
        <div className="flex flex-wrap gap-2">
          {posibles.map((accion) => (
            <button
              key={accion}
              type="button"
              className={
                accion === "cancelar" ? "btn-secondary" : "btn-primary"
              }
              disabled={enviando}
              onClick={() =>
                // Recordar no pide nada más; el resto se confirma o se rellena.
                accion === "recordar" ? void hacer(accion) : setAbierta(accion)
              }
            >
              <Icono nombre={ICONOS[accion]} tamano="sm" />
              {t(`sobre.acciones.${accion}`)}
            </button>
          ))}
        </div>
      </div>

      {abierta === "enviar" ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <p className="text-dato text-ink">
            {t("sobre.acciones.confirmarEnvio")}
          </p>
          <button
            type="button"
            className="btn-primary"
            disabled={enviando}
            onClick={() => void hacer("enviar")}
          >
            {t("sobre.acciones.siEnviar")}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setAbierta(null)}
          >
            {t("sobre.acciones.volver")}
          </button>
        </div>
      ) : null}

      {abierta === "cancelar" ? (
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("sobre.acciones.motivo")}
            <input
              className="input-base w-72"
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn-primary"
            disabled={!motivo.trim() || enviando}
            onClick={() => void hacer("cancelar")}
          >
            {t("sobre.acciones.siCancelar")}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setAbierta(null)}
          >
            {t("sobre.acciones.volver")}
          </button>
        </div>
      ) : null}

      {abierta === "archivar" ? (
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("sobre.acciones.documentoFirmado")}
            <input
              className="input-base"
              value={firmado}
              onChange={(e) => setFirmado(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("sobre.acciones.certificado")}
            <input
              className="input-base"
              value={certificado}
              onChange={(e) => setCertificado(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("sobre.acciones.sello")}
            <input
              className="input-base"
              value={sello}
              onChange={(e) => setSello(e.target.value)}
            />
          </label>
          <div className="flex gap-2 md:col-span-3">
            <button
              type="button"
              className="btn-primary"
              disabled={!firmado.trim() || enviando}
              onClick={() => void hacer("archivar")}
            >
              {t("sobre.acciones.archivar")}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setAbierta(null)}
            >
              {t("sobre.acciones.volver")}
            </button>
          </div>
        </div>
      ) : null}

      <div role="status" className="mt-2">
        {resultado ? (
          <p className="text-dato text-success">{resultado}</p>
        ) : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
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
