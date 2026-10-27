/**
 * La conversación, con todo lo que el cliente ha hablado con nosotros
 * (CRM-04.02.02.01, CRM-04.02.02.02, CRM-04.02.01.03).
 *
 * **Existía el destino y no existía la pantalla.** La cola de la consola de
 * agente enlazaba a `/m/conversaciones/conversacion/{id}` desde el primer día,
 * y ese módulo no existe: quien pulsaba una conversación de la cola llegaba a
 * «no existe». Responder, cambiar de canal y escalar a una persona estaban
 * publicados —y probados— sin un solo botón que los llamara.
 *
 * Tres decisiones, y las tres son de usabilidad, no de implementación:
 *
 * **El hilo es el del CLIENTE, no el de esta conversación.** Se pide el
 * historial por contacto o por identidad externa, que trae todo lo hablado por
 * cualquier canal ordenado por tiempo. Enseñar sólo los mensajes de esta
 * conversación es lo que hace que el agente pregunte tres veces lo mismo a
 * quien escribió el lunes por correo, llamó el martes y abrió un chat hoy.
 *
 * **No agrupado por canal.** Agrupar reproduce el problema que la
 * omnicanalidad viene a quitar; el canal va como etiqueta en cada mensaje.
 *
 * **La nota interna se ve distinta y se dice que es interna**, porque es lo
 * único que separa una nota de una respuesta mandada al cliente. Y no cuenta
 * como primera respuesta: eso lo decide el servidor, aquí sólo se rotula.
 *
 * Lo que se puede hacer depende del permiso, no de la pantalla: sin
 * `case:write` el hilo se lee y no hay caja de respuesta. Esconder el botón no
 * es la seguridad —el servidor decide— pero enseñar lo que va a dar 403 es
 * hacerle perder el tiempo a quien lo pulsa.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { ErrorApi, llamar } from "@/lib/api";
import { puede, type Sesion } from "@/lib/sesion";

/** Los canales que admite el servidor. Mandar uno que no está da 422. */
const CANALES = ["correo", "formulario", "chat", "social", "api", "telefono", "portal"] as const;

interface Conversacion {
  id: string;
  canal_actual: string;
  asunto: string | null;
  estado: string;
  contacto_id: string | null;
  identidad_externa: string | null;
  atendida_por_bot: boolean;
  caso_id: string | null;
}

interface Mensaje {
  at: string;
  canal: string;
  direccion: string;
  interno: boolean;
  asunto: string | null;
  cuerpo: string;
  conversacion_id: string;
  caso_id: string | null;
}

export function Conversacion({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [conversacion, setConversacion] = useState<Conversacion | null>(null);
  const [hilo, setHilo] = useState<Mensaje[] | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);
  // Lo que acaba de pasar, dicho con palabras. Sin esto, quien no ve la
  // pantalla pulsa «responder» y no se entera de si salió o no: el mensaje
  // aparece al final de un hilo largo, fuera de donde está su foco.
  const [aviso, setAviso] = useState("");

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<Conversacion>(`/api/v1/conversaciones/${id}`, { signal: control.signal })
      .then(async (r) => {
        setConversacion(r.datos);
        // El historial **exige** un cliente: sin contacto ni identidad externa
        // responde 422. Una conversación anónima tiene hilo propio y nada más,
        // y eso se dice en vez de enseñar un error.
        const quien = r.datos.contacto_id
          ? `contacto_id=${encodeURIComponent(r.datos.contacto_id)}`
          : r.datos.identidad_externa
            ? `identidad=${encodeURIComponent(r.datos.identidad_externa)}`
            : "";
        if (!quien) {
          setHilo([]);
          return;
        }
        const h = await llamar<Mensaje[]>(`/api/v1/conversaciones/historial?${quien}`, {
          signal: control.signal,
        });
        setHilo(Array.isArray(h.datos) ? h.datos : []);
      })
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  async function accion(ruta: string, cuerpo: Record<string, unknown>) {
    setEnviando(true);
    setAviso("");
    try {
      await llamar(`/api/v1/conversaciones/${id}/${ruta}`, { metodo: "POST", cuerpo });
      setAviso(t(`conversacion.hecho.${ruta}`));
      cargar();
    } catch (e: unknown) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      setEnviando(false);
    }
  }

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!conversacion || !hilo) return <Cargando />;

  const puedeEscribir = puede(sesion, "case:write");

  return (
    <div className="flex flex-col gap-4">
      <CabeceraPagina
        titulo={conversacion.asunto || t("conversacion.sinAsunto")}
        entradilla={t("conversacion.entradilla")}
        icono="forum"
      />

      <div className="flex flex-wrap items-center gap-2 text-3xs text-ink-muted">
        <span className="badge badge-accent">{conversacion.canal_actual}</span>
        <span>{conversacion.estado}</span>
        {conversacion.atendida_por_bot ? (
          <span className="badge">{t("conversacion.porBot")}</span>
        ) : null}
      </div>

      {/* El resultado de pulsar algo se anuncia: es una región viva, así que
          quien usa lector de pantalla lo oye donde está, sin ir a buscarlo al
          final del hilo. */}
      <p role="status" aria-live="polite" className="text-3xs text-success">
        {aviso}
      </p>

      {hilo.length === 0 ? (
        <Vacio titulo={t("conversacion.sinHilo")} detalle={t("conversacion.sinHiloDetalle")} />
      ) : (
        <ol className="flex flex-col gap-2">
          {hilo.map((m, i) => (
            <li
              key={`${m.conversacion_id}:${m.at}:${i}`}
              className={`rounded-lg border p-3 ${
                m.interno
                  ? "border-warning/40 bg-warning/5"
                  : m.direccion === "entrante"
                    ? "border-ink-dim/40 bg-paper-light"
                    : "border-accent/40"
              }`}
            >
              <div className="flex flex-wrap items-baseline gap-x-2 text-3xs text-ink-muted">
                <span className="badge badge-accent">{m.canal}</span>
                <span>{t(`conversacion.${m.direccion === "entrante" ? "delCliente" : "nuestro"}`)}</span>
                {/* Que una nota es interna se dice con palabras y no sólo con
                    un color: quien no distingue los dos amarillos la manda. */}
                {m.interno ? <span className="text-warning">{t("conversacion.interna")}</span> : null}
                <span className="ml-auto font-mono">{m.at.slice(0, 16).replace("T", " ")}</span>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-2xs text-ink">{m.cuerpo}</p>
            </li>
          ))}
        </ol>
      )}

      {puedeEscribir ? (
        <Responder enviando={enviando} alEnviar={accion} />
      ) : (
        <p className="text-3xs text-ink-faint">{t("conversacion.soloLectura")}</p>
      )}
    </div>
  );
}

/** Responder, cambiar de canal y escalar: lo que se hace desde aquí. */
function Responder({
  enviando,
  alEnviar,
}: {
  enviando: boolean;
  alEnviar: (ruta: string, cuerpo: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation();
  const [cuerpo, setCuerpo] = useState("");
  const [interno, setInterno] = useState(false);
  const [canal, setCanal] = useState("");
  const [motivo, setMotivo] = useState("");

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-ink-dim/40 p-3">
      <label className="flex flex-col gap-1">
        <span className="text-3xs text-ink-muted">{t("conversacion.respuesta")}</span>
        <textarea
          rows={3}
          value={cuerpo}
          onChange={(e) => setCuerpo(e.target.value)}
          className="input-base"
        />
      </label>
      <label className="flex items-center gap-2 text-3xs text-ink-muted">
        <input type="checkbox" checked={interno} onChange={(e) => setInterno(e.target.checked)} />
        {t("conversacion.esNotaInterna")}
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={enviando || cuerpo.trim() === ""}
          onClick={() => {
            alEnviar("responder", { cuerpo, interno });
            setCuerpo("");
          }}
        >
          {t(interno ? "conversacion.dejarNota" : "conversacion.responder")}
        </button>
        {/* Escalar reusa el cuerpo como motivo: pedir el motivo en otra caja
            hace que quien ya lo ha escrito lo escriba dos veces. */}
        <button
          type="button"
          className="btn-secondary"
          disabled={enviando || cuerpo.trim() === ""}
          onClick={() => {
            alEnviar("escalar-a-humano", { motivo: cuerpo });
            setCuerpo("");
          }}
        >
          {t("conversacion.escalar")}
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-2 border-t border-ink-dim/30 pt-3">
        <label className="flex flex-col gap-1">
          <span className="text-3xs text-ink-muted">{t("conversacion.cambiarCanal")}</span>
          <select value={canal} onChange={(e) => setCanal(e.target.value)} className="input-base">
            <option value="">{t("conversacion.elegirCanal")}</option>
            {CANALES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-3xs text-ink-muted">{t("conversacion.motivo")}</span>
          <input value={motivo} onChange={(e) => setMotivo(e.target.value)} className="input-base" />
        </label>
        <button
          type="button"
          className="btn-secondary"
          disabled={enviando || canal === ""}
          onClick={() => {
            alEnviar("transferir", { canal, motivo });
            setCanal("");
            setMotivo("");
          }}
        >
          {t("conversacion.transferir")}
        </button>
      </div>
      {/* Cambiar de canal NO abre una conversación nueva: el hilo se conserva.
          Decirlo aquí evita que nadie abra una «por si acaso». */}
      <p className="text-3xs text-ink-faint">{t("conversacion.transferirDetalle")}</p>
    </div>
  );
}
