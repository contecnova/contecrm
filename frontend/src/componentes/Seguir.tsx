/**
 * Seguir un registro, desde el registro.
 *
 * **Estaba escrito y sin enchufar.** `/api/v1/seguimientos` existe desde hace
 * tiempo —suscribirse, dejar de hacerlo, saber quién sigue qué, y es lo que
 * decide a quién avisa el motor de notificaciones—, y en el front sólo salía
 * como una tabla en «Usuarios y permisos → Seguimientos»: se podía ver lo que
 * uno seguía y **no había forma de seguir ni de dejar de seguir nada**. En
 * Salesforce el botón vive en el panel de arriba de la ficha desde siempre, y
 * es de donde sale la mitad de lo que llega a las notificaciones.
 *
 * Medido el 03-11-2026 contra la instalación servida: pidiendo DELETE y luego
 * POST, el servidor devolvía la suscripción **silenciada** y contestaba 201.
 * Es decir: el botón habría dicho «siguiendo» y no habría llegado un aviso
 * nunca. Arreglado en `crmcore/datos/seguimiento.py` antes de poner el botón.
 *
 * **Al propietario no se le desuscribe, se le silencia** —no puede dejar de
 * ser responsable de su registro—, y eso se dice: un botón que vuelve solo a
 * «Siguiendo» sin explicarlo parece estropeado.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import { llamar, salvoCancelacion } from "@/lib/api";
import { conCursor, listarPagina, MAXIMO_POR_PAGINA } from "@/lib/listados";
import { cn } from "@/lib/utiles";

interface Seguimiento {
  id: string;
  objeto_tipo: string;
  objeto_id: string;
  motivo: string;
  silenciado: boolean;
}

export function Seguir({
  objetoTipo,
  objetoId,
}: {
  objetoTipo: string;
  objetoId: string;
}) {
  const { t } = useTranslation();
  const [suyo, setSuyo] = useState<Seguimiento | null>(null);
  // `null` hasta saberlo: con `false` de partida el botón diría «Seguir»
  // mientras se pregunta, y quien lo pulsara en ese hueco pediría seguir algo
  // que ya seguía.
  const [sabido, setSabido] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState("");

  const mirar = useCallback(() => {
    const control = new AbortController();
    // Filtrado por tipo en el servidor y comprobado aquí por identificador:
    // el extremo no admite `objeto_id`, así que la alternativa sería creer
    // que lo que vuelve es de este registro.
    //
    // **Siguiendo el cursor hasta encontrarlo.** Miraba sólo la primera
    // página: con más de doscientas cuentas seguidas, la doscientas una salía
    // como «no la sigues» y el primer clic contestaba que ya la seguía. Lo
    // normal es una vuelta; sólo quien sigue cientos paga más, y paga lo
    // justo para dar la respuesta correcta.
    const ruta = `/api/v1/seguimientos?objeto_tipo=${encodeURIComponent(objetoTipo)}&limite=${MAXIMO_POR_PAGINA}`;
    void (async () => {
      let cursor = "";
      do {
        const pagina = await listarPagina<Seguimiento>(
          cursor ? conCursor(ruta, cursor) : ruta,
          { signal: control.signal },
        );
        const hallado = pagina.filas.find((s) => s.objeto_id === objetoId);
        if (hallado) return hallado;
        cursor = pagina.siguiente;
      } while (cursor);
      return null;
    })()
      .then((hallado) => {
        setSuyo(hallado);
        setSabido(true);
      })
      .catch(
        salvoCancelacion(() => {
          // Que no se sabe se dice callando el botón: ofrecer «Seguir» cuando
          // no se ha podido preguntar hace que el primer clic conteste que ya
          // lo seguía.
          setSabido(false);
        }),
      );
    return () => control.abort();
  }, [objetoTipo, objetoId]);

  useEffect(mirar, [mirar]);

  const siguiendo = Boolean(suyo) && !suyo?.silenciado;

  async function alternar() {
    setEnviando(true);
    setFallo("");
    try {
      if (siguiendo) {
        await llamar(
          `/api/v1/seguimientos/${encodeURIComponent(objetoTipo)}/${encodeURIComponent(objetoId)}`,
          { metodo: "DELETE" },
        );
      } else {
        await llamar("/api/v1/seguimientos", {
          metodo: "POST",
          cuerpo: { objeto_tipo: objetoTipo, objeto_id: objetoId, motivo: "manual" },
        });
      }
      // Se vuelve a preguntar en vez de suponer el nuevo estado: al
      // propietario el servidor le silencia en lugar de desuscribirle, así
      // que suponer «ya no sigo» sería mentir en el único caso que importa.
      mirar();
    } catch {
      setFallo(t("seguir.noSePudo"));
    } finally {
      setEnviando(false);
    }
  }

  if (!sabido) return null;

  return (
    <div className="flex flex-col items-end">
      <button
        type="button"
        onClick={() => void alternar()}
        disabled={enviando}
        aria-pressed={siguiendo}
        className={cn("btn-secondary inline-flex items-center gap-1.5", siguiendo && "text-accent")}
        title={
          suyo?.motivo === "propietario"
            ? t("seguir.eresPropietario")
            : t(siguiendo ? "seguir.dejar" : "seguir.seguir")
        }
      >
        <Icono nombre={siguiendo ? "notifications_active" : "notifications"} tamano="sm" />
        {t(siguiendo ? "seguir.siguiendo" : "seguir.seguir")}
      </button>
      {/* Por qué el botón no se va del todo. Sin esto, el propietario que
          deja de seguir ve «Seguir» y, al mirar «Lo que sigo», su registro
          sigue ahí: parecería que no le ha hecho caso. */}
      {suyo?.motivo === "propietario" ? (
        <span className="mt-0.5 text-rotulo text-ink-faint">
          {t("seguir.eresPropietario")}
        </span>
      ) : null}
      {fallo ? (
        <span className="mt-0.5 text-rotulo text-danger" role="alert">
          {fallo}
        </span>
      ) : null}
    </div>
  );
}
