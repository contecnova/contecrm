/**
 * Anotar una llamada, un correo o una nota sin salir de la ficha.
 *
 * Es el gesto más repetido de un CRM: acabas de hablar con el cliente y lo
 * apuntas. Aquí obligaba a irse a la pantalla de Actividades, dar de alta, y
 * **acordarse de poner a mano el identificador del cliente** para que quedara
 * colgado de él. Eso no lo hace nadie dos veces: se deja de apuntar, y un CRM
 * en el que no se apunta lo que pasa deja de servir para nada.
 *
 * Los tipos salen del contrato (`enum` del campo `tipo`), no de una lista
 * escrita aquí: si el servicio añade uno, aparece solo.
 *
 * **Se queda en la ficha y refresca la línea de tiempo.** Mandar a otra
 * pantalla después de apuntar una llamada rompe justo lo que se estaba
 * haciendo, que es mirar al cliente.
 */

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { llamar } from "@/lib/api";
import { camposDe, contratoDe } from "@/lib/contrato";

/** Los que se apuntan sobre la marcha. El resto se dan de alta por su pantalla. */
const RAPIDOS = ["llamada", "email", "nota", "reunion"] as const;

const ICONO: Record<string, string> = {
  llamada: "call",
  email: "mail",
  nota: "sticky_note_2",
  reunion: "groups",
  visita: "directions_car",
  tarea: "task_alt",
};

export function RegistrarActividad({
  objeto,
  objetoId,
  alRegistrar,
}: {
  /** `cuenta`, `contacto`, `oportunidad`… lo que dice de qué cuelga. */
  objeto: string;
  objetoId: string;
  alRegistrar: () => void;
}) {
  const { t } = useTranslation();
  const [tipos, setTipos] = useState<string[]>([...RAPIDOS]);
  const [tipo, setTipo] = useState<string | null>(null);
  const [asunto, setAsunto] = useState("");
  const [cuerpo, setCuerpo] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const asuntoRef = useRef<HTMLInputElement>(null);

  // El foco se lleva al campo al elegir el tipo, pero con `focus()` y no con
  // `autoFocus`: `autoFocus` se dispara al montar y mueve el foco de quien esté
  // navegando con teclado por otra parte de la página sin haberlo pedido.
  useEffect(() => {
    if (tipo) asuntoRef.current?.focus();
  }, [tipo]);

  // Los tipos que admite el servidor, por si añade o quita alguno.
  useEffect(() => {
    let vivo = true;
    void contratoDe("party").then((documento) => {
      const campos = camposDe(documento, "/api/v1/activities", "post");
      const declarados = campos.find((c) => c.nombre === "tipo")?.opciones ?? [];
      if (vivo && declarados.length > 0) {
        setTipos(declarados.filter((d) => (RAPIDOS as readonly string[]).includes(d)));
      }
    });
    return () => {
      vivo = false;
    };
  }, []);

  async function registrar() {
    if (!tipo || !asunto.trim()) return;
    setEnviando(true);
    try {
      await llamar("/api/v1/activities", {
        metodo: "POST",
        cuerpo: {
          tipo,
          asunto: asunto.trim(),
          cuerpo: cuerpo.trim() || undefined,
          // De qué cuelga, puesto solo. Es lo que antes había que teclear a
          // mano —el identificador del cliente— y lo que hacía que nadie
          // apuntara nada.
          objeto,
          objeto_id: objetoId,
        },
      });
      setTipo(null);
      setAsunto("");
      setCuerpo("");
      setFallo(null);
      alRegistrar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="mb-3">
      <div className="flex flex-wrap gap-2">
        {tipos.map((x) => (
          <button
            key={x}
            type="button"
            onClick={() => setTipo(tipo === x ? null : x)}
            className={`inline-flex items-center gap-1.5 ${tipo === x ? "btn-primary" : "btn-secondary"}`}
          >
            <Icono nombre={ICONO[x] ?? "edit_note"} tamano="sm" />
            {t(`actividad.${x}`, { defaultValue: x })}
          </button>
        ))}
      </div>

      {tipo ? (
        <form
          className="mt-3 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            void registrar();
          }}
        >
          <div>
            <label htmlFor="actividad-asunto" className="label-base">
              {t("actividad.asunto")}
            </label>
            <input
              id="actividad-asunto"
              ref={asuntoRef}
              value={asunto}
              onChange={(e) => setAsunto(e.target.value)}
              required
              className="input-base"
              placeholder={t(`actividad.ejemplo.${tipo}`, { defaultValue: "" })}
            />
          </div>
          <div>
            <label htmlFor="actividad-cuerpo" className="label-base">
              {t("actividad.notas")}
            </label>
            <textarea
              id="actividad-cuerpo"
              rows={3}
              value={cuerpo}
              onChange={(e) => setCuerpo(e.target.value)}
              className="input-base"
            />
          </div>
          <div className="flex gap-2">
            <button type="submit" disabled={enviando} className="btn-primary">
              {enviando ? t("app.cargando") : t("actividad.guardar")}
            </button>
            <button type="button" onClick={() => setTipo(null)} className="btn-secondary">
              {t("modulo.cancelar")}
            </button>
          </div>
        </form>
      ) : null}

      {fallo ? (
        <div className="mt-2">
          <Fallo error={fallo} />
        </div>
      ) : null}
    </div>
  );
}
