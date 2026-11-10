/**
 * La renovación de este contrato (CRM-03.03.02.10).
 *
 * Gestión de renovaciones con alertas y embudo propio: al llegar el preaviso
 * se avisa y se abre una oportunidad de renovación en el embudo configurado
 * (`renovacion_embudo`), enlazada en las dos direcciones. Lo hace sola la
 * revisión periódica; aquí, «Revisar este contrato» la pide sólo para él
 * —`POST /contratos/revisar-renovaciones` con `contrato_id`— sin tocar los
 * demás, y se enseña la oportunidad abierta con su enlace.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { llamar } from "@/lib/api";
import { fecha } from "@/lib/formato";

interface Revision {
  revisados: number;
  no_revisados: { contrato_id: string; porque: string }[];
  avisados: { contrato_id: string; dias: number }[];
  renovados: { de: string; a: string }[];
  oportunidades: { contrato_id: string; oportunidad_id: string }[];
  embudo_no_encontrado: string | null;
}

export function RenovacionDeContrato({
  contratoId,
  contrato,
  alRevisar,
}: {
  contratoId: string;
  contrato: Record<string, unknown> | null;
  alRevisar: () => void;
}) {
  const { t } = useTranslation();
  const [revision, setRevision] = useState<Revision | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [trabajando, setTrabajando] = useState(false);

  const fin = typeof contrato?.fin === "string" ? contrato.fin : "";
  const preaviso = Number(contrato?.preaviso_dias ?? 0);
  const oportunidad =
    revision?.oportunidades.find((o) => o.contrato_id === contratoId)
      ?.oportunidad_id ??
    (typeof contrato?.oportunidad_renovacion_id === "string"
      ? contrato.oportunidad_renovacion_id
      : "");

  async function revisar() {
    setTrabajando(true);
    setFallo(null);
    try {
      const r = await llamar<Revision>(
        "/api/v1/contratos/revisar-renovaciones",
        { metodo: "POST", cuerpo: { contrato_id: contratoId } },
      );
      setRevision(r.datos);
      alRevisar();
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  const motivo = revision?.no_revisados.find(
    (n) => n.contrato_id === contratoId,
  )?.porque;

  return (
    <section className="card mb-4 p-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="section-label">{t("renovacionContrato.titulo")}</h2>
        <button
          type="button"
          className="btn-secondary"
          disabled={trabajando}
          onClick={() => void revisar()}
        >
          <Icono nombre="autorenew" tamano="sm" />
          {t("renovacionContrato.revisar")}
        </button>
      </div>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("renovacionContrato.ayuda")}
      </p>
      <p className="text-dato text-ink-muted">
        {fin
          ? t("renovacionContrato.vence", { fin: fecha(fin), dias: preaviso })
          : t("renovacionContrato.sinFin")}
        {contrato?.preaviso_dado ? (
          <span className="ml-2 chip-dato chip-dato--aviso">
            {t("renovacionContrato.preavisoDado")}
          </span>
        ) : null}
      </p>
      <div role="status" className="mt-2 text-dato">
        {oportunidad ? (
          <p>
            {t("renovacionContrato.oportunidad")}{" "}
            <Link
              className="text-accent hover:underline"
              to={`/abrir/oportunidad/${oportunidad}`}
            >
              {t("renovacionContrato.abrirOportunidad")}
            </Link>
          </p>
        ) : revision ? (
          <p className="text-ink-muted">
            {motivo
              ? t("renovacionContrato.noRevisado", { porque: motivo })
              : revision.embudo_no_encontrado
                ? t("renovacionContrato.sinEmbudo", {
                    clave: revision.embudo_no_encontrado,
                  })
                : t("renovacionContrato.aunNo")}
          </p>
        ) : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}
