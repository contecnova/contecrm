/**
 * Quién manda hoy sobre este objeto, con TODAS sus reglas juntas
 * (CRM-00.03.01.07).
 *
 * Va en la ficha de una regla de convivencia porque es la pregunta que se hace
 * al escribirla: una regla sola no dice si gana. Gana la de menor prioridad que
 * encaje, y sin ninguna manda el heredado; esto lo resuelve el servidor con las
 * reglas activas del objeto, y aquí sólo se pinta. Las condiciones se evalúan
 * sin un registro concreto, y se dice: con un registro real puede ganar otra.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";

interface QuienManda {
  objeto: string;
  dueno: string;
  regla?: string;
  escribible_aqui: boolean;
  porque: string;
  por_defecto: boolean;
}

export function QuienMandaSobre({ objeto }: { objeto: string }) {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<QuienManda | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<QuienManda>(
      `/api/v1/convivencia/quien-manda?objeto=${encodeURIComponent(objeto)}`,
      { signal: control.signal },
    )
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [objeto]);

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">
        {t("quienManda.titulo", { objeto })}
      </h2>
      {fallo ? <Fallo error={fallo} /> : null}
      {datos ? (
        <>
          <p className="text-dato text-ink">
            {t("quienManda.manda", {
              dueno: t(`quienManda.duenos.${datos.dueno}`, {
                defaultValue: datos.dueno,
              }),
            })}{" "}
            <span
              className={`chip-dato ${datos.escribible_aqui ? "chip-dato--si" : "chip-dato--no"}`}
            >
              {datos.escribible_aqui
                ? t("quienManda.seEscribeAqui")
                : t("quienManda.noSeEscribeAqui")}
            </span>
          </p>
          <p className="mt-1 text-dato text-ink-muted">{datos.porque}</p>
          <p className="mt-1 text-rotulo text-ink-faint">
            {t("quienManda.sinRegistro")}
          </p>
        </>
      ) : null}
    </section>
  );
}
