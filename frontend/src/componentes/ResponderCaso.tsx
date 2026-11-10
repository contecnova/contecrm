/**
 * Contestar al cliente desde su caso: el correo sale de verdad.
 *
 * Hasta el 10-11-2026 «responder» un caso era **apuntar** un correo en la
 * actividad: quedaba escrito que se había contestado y al cliente no le
 * llegaba nada (medido en la tarea T09). Ahora `POST /casos/{id}/responder`
 * lo manda por el canal de la casa —el correo transaccional, con la plantilla
 * de la empresa— y deja constancia en el caso, salga o no.
 *
 * **Lo que no sale se dice como no salido**, no con el «Hecho» verde de las
 * acciones genéricas: una respuesta que se cree mandada y no lo está es peor
 * que una que falla a la vista. Por eso tiene su formulario y no el genérico
 * del contrato.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { llamar, salvoCancelacion } from "@/lib/api";

interface Respuesta {
  enviado: boolean;
  motivo: string;
  para: string;
  asunto: string;
  plantilla_de_serie: boolean;
}

export function ResponderCaso({
  casoId,
  contactoId,
  alTerminar,
  alCancelar,
}: {
  casoId: string;
  /** El contacto del caso: su correo es el «Para» de entrada. */
  contactoId?: string | null;
  alTerminar: () => void;
  alCancelar: () => void;
}) {
  const { t } = useTranslation();
  const [para, setPara] = useState("");
  const [asunto, setAsunto] = useState("");
  const [mensaje, setMensaje] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [hecho, setHecho] = useState<Respuesta | null>(null);

  // A quién va, a la vista: mandar al correo del contacto sin enseñarlo es
  // mandar a ciegas.
  useEffect(() => {
    if (!contactoId) return;
    const control = new AbortController();
    llamar<{ email?: string | null }>(`/api/v1/contacts/${contactoId}`, {
      signal: control.signal,
    })
      .then((r) => setPara((actual) => actual || (r.datos?.email ?? "")))
      // Sin el contacto se escribe a mano: no se bloquea el formulario.
      .catch(salvoCancelacion(() => undefined));
    return () => control.abort();
  }, [contactoId]);

  async function enviar() {
    setEnviando(true);
    setFallo(null);
    setHecho(null);
    try {
      const r = await llamar<Respuesta>(`/api/v1/casos/${casoId}/responder`, {
        metodo: "POST",
        cuerpo: {
          mensaje: mensaje.trim(),
          para: para.trim(),
          asunto: asunto.trim(),
        },
      });
      setHecho(r.datos);
      if (r.datos.enviado) setMensaje("");
      alTerminar();
    } catch (e) {
      setFallo(e);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="card mb-4 p-4" aria-label={t("caso.responder.titulo")}>
      <h2 className="section-label mb-2">{t("caso.responder.titulo")}</h2>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("caso.responder.para")}
          <input
            type="email"
            className="input-base"
            value={para}
            placeholder={t("caso.responder.paraAyuda")}
            onChange={(e) => setPara(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("caso.responder.asunto")}
          <input
            className="input-base"
            value={asunto}
            placeholder={t("caso.responder.asuntoAyuda")}
            onChange={(e) => setAsunto(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
          {t("caso.responder.mensaje")}
          <textarea
            className="input-base"
            rows={5}
            value={mensaje}
            onChange={(e) => setMensaje(e.target.value)}
          />
        </label>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={!mensaje.trim() || enviando}
          onClick={() => void enviar()}
        >
          {enviando ? t("caso.responder.enviando") : t("caso.responder.enviar")}
        </button>
        <button type="button" className="btn-secondary" onClick={alCancelar}>
          {t("caso.cancelar")}
        </button>
      </div>
      {hecho ? (
        hecho.enviado ? (
          <p
            className="mt-3 inline-flex items-center gap-1.5 text-dato text-success"
            role="status"
          >
            <Icono nombre="check_circle" tamano="sm" />
            {t(
              hecho.plantilla_de_serie
                ? "caso.responder.enviadaDeSerie"
                : "caso.responder.enviada",
              { para: hecho.para },
            )}
          </p>
        ) : (
          <p
            className="mt-3 inline-flex items-start gap-1.5 text-dato text-warning"
            role="alert"
          >
            <Icono nombre="warning" tamano="sm" />
            {t("caso.responder.noSalio", { motivo: hecho.motivo })}
          </p>
        )
      ) : null}
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}
