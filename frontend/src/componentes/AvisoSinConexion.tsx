/**
 * La franja de «sin conexión» (CRM-06.02.01.04).
 *
 * Se pinta en TODAS las pantallas cuando no hay red o cuando hay cambios en el
 * dispositivo sin subir. Sin ella, quien trabaja sin red cree que lo que ve es
 * de ahora y que lo que guardó ya está en el servidor, y ninguna de las dos
 * cosas es verdad. Con red y la cola vacía no se pinta nada.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { alCambiar, cola, fijarUsuario } from "@/lib/sinConexion";

export function AvisoSinConexion({ usuario }: { usuario: string }) {
  const { t } = useTranslation();
  // La cola es de quien está dentro: se fija aquí, que es donde se sabe.
  useEffect(() => fijarUsuario(usuario), [usuario]);
  const [enLinea, setEnLinea] = useState(() => navigator.onLine);
  const [pendientes, setPendientes] = useState(0);
  const [conflictos, setConflictos] = useState(0);

  useEffect(() => {
    let vivo = true;
    const leer = () => {
      setEnLinea(navigator.onLine);
      void cola().then((ops) => {
        if (!vivo) return;
        setPendientes(ops.filter((o) => o.estado !== "conflicto").length);
        setConflictos(ops.filter((o) => o.estado === "conflicto").length);
      });
    };
    leer();
    const baja = alCambiar(leer);
    return () => {
      vivo = false;
      baja();
    };
  }, []);

  if (enLinea && !pendientes && !conflictos) return null;
  return (
    <div
      className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-warning px-4 py-1 text-center text-dato text-ink"
      role="status"
      data-sin-conexion
    >
      {!enLinea ? <span>{t("app.sinConexionAviso")}</span> : null}
      {pendientes ? (
        <span className="text-rotulo">
          {t("app.sinConexionPendientes", { count: pendientes, n: pendientes })}
        </span>
      ) : null}
      {conflictos ? (
        <span className="text-rotulo font-medium">
          {t("app.sinConexionConflictos", { count: conflictos, n: conflictos })}
        </span>
      ) : null}
      <Link
        to="/sin-conexion"
        className="rounded border border-ink/40 px-2 py-0.5 text-rotulo font-medium hover:bg-ink/10"
      >
        {t("app.sinConexionVer")}
      </Link>
    </div>
  );
}
