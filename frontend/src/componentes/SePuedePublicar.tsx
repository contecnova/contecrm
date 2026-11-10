/**
 * Si lo que se está aprobando se puede publicar ya, y qué falta.
 *
 * Va en la ficha del activo de marketing: cada paso de aprobación dice qué
 * decidió UNA persona, y lo que se pregunta delante del activo es si el
 * conjunto está listo. Un rechazo vale para el conjunto —los pasos siguientes no se
 * piden—, y un aprobado sin haber visto los cambios se dice aparte, porque es
 * una firma sobre algo que ya no es lo que se firmó.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";

interface Estado {
  se_puede_publicar: boolean;
  porque: string;
  pendientes?: string[];
  rechazado_en?: { paso: string; motivo: string }[];
  aprobados_sin_mirar_cambios?: string[];
}

export function SePuedePublicar({
  objeto,
  objetoId,
  version,
}: {
  objeto: string;
  objetoId: string;
  version: number;
}) {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Estado | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    const consulta = new URLSearchParams({
      objeto,
      objeto_id: objetoId,
      version: String(version),
    });
    llamar<Estado>(
      `/api/v1/activos-marketing/aprobaciones/estado?${consulta}`,
      {
        signal: control.signal,
      },
    )
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [objeto, objetoId, version]);

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">
        {t("sePuedePublicar.titulo", { version })}
      </h2>
      {fallo ? <Fallo error={fallo} /> : null}
      {datos ? (
        <>
          <p
            className={`text-dato ${datos.se_puede_publicar ? "text-success" : "text-warning"}`}
          >
            {datos.se_puede_publicar
              ? t("sePuedePublicar.si")
              : t("sePuedePublicar.no")}
          </p>
          <p className="mt-1 text-dato text-ink-muted">{datos.porque}</p>
          {datos.pendientes?.length ? (
            <p className="mt-1 text-rotulo text-ink">
              {t("sePuedePublicar.pendientes", {
                pasos: datos.pendientes.join(", "),
              })}
            </p>
          ) : null}
          {datos.aprobados_sin_mirar_cambios?.length ? (
            <p className="mt-1 text-rotulo text-warning">
              {t("sePuedePublicar.sinMirar", {
                pasos: datos.aprobados_sin_mirar_cambios.join(", "),
              })}
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
