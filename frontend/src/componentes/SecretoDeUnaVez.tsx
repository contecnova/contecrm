/**
 * Lo que el servidor devuelve UNA sola vez al dar de alta algo: el secreto de
 * una clave de API.
 *
 * La pantalla de alta tiraba la respuesta y recargaba la lista, así que la
 * clave quedaba creada y su secreto —que no se puede volver a pedir: sólo se
 * guarda su hash— no lo veía nadie. Medido el 09-11-2026.
 *
 * Se enseña aquí, con el aviso de copiarlo, y **no se guarda en ninguna
 * parte**: vive en la memoria de la pantalla. Al cerrar el aviso, al recargar o
 * al irse, desaparece, que es lo que promete el servidor.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";

export function SecretoDeUnaVez({
  valores,
  alCerrar,
}: {
  valores: Record<string, string>;
  alCerrar: () => void;
}) {
  const { t } = useTranslation();
  const [copiado, setCopiado] = useState("");

  return (
    <div
      role="alert"
      className="mb-4 rounded-xl border border-warning/50 bg-paper p-4"
    >
      <p className="flex items-center gap-2 text-titulin font-medium text-ink">
        <Icono nombre="key" tamano="sm" />
        {t("modulo.unaVezTitulo")}
      </p>
      <p className="mt-1 text-dato text-warning">{t("modulo.unaVezAviso")}</p>
      {Object.entries(valores).map(([campo, valor]) => (
        <div key={campo} className="mt-3">
          <p className="section-label mb-1">{campo}</p>
          <div className="flex flex-wrap items-center gap-2">
            <code
              data-una-vez={campo}
              className="min-w-0 flex-1 break-all rounded border border-ink-dim/60 px-2 py-1 font-mono text-dato text-ink"
            >
              {valor}
            </code>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                // Sin portapapeles (contexto inseguro, permiso denegado) el
                // valor sigue a la vista y se puede seleccionar a mano.
                void navigator.clipboard
                  ?.writeText(valor)
                  .then(() => setCopiado(campo))
                  .catch(() => undefined);
              }}
            >
              <Icono
                nombre={copiado === campo ? "check" : "content_copy"}
                tamano="sm"
              />
              {copiado === campo ? t("errores.copiado") : t("errores.copiar")}
            </button>
          </div>
        </div>
      ))}
      <div className="mt-3">
        <button type="button" className="btn-primary" onClick={alCerrar}>
          {t("modulo.unaVezCerrar")}
        </button>
      </div>
    </div>
  );
}
