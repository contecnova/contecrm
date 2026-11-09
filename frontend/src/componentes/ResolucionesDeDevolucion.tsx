/**
 * Las resoluciones de una devolución: reparar, sustituir o abonar, y anotar lo
 * que contestó quien factura (CRM-04.05.01.02).
 *
 * Resolver cuelga de la devolución y sale en sus acciones; confirmar el abono
 * cuelga de la RESOLUCIÓN (`/devoluciones/resoluciones/{id}/abono`), así que
 * la ficha genérica no llegaba nunca: el abono se quedaba en «solicitado» para
 * siempre aunque el ERP ya lo hubiera emitido. Aquí se ve cada resolución y,
 * en el abono pendiente, se anota si se emitió —con su referencia— o se
 * rechazó —con su motivo, que sin él se vuelve a mandar igual—.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";

interface Resolucion {
  id: string;
  tipo: string;
  a_cargo_de: string | null;
  importe: string | null;
  estado_abono: string | null;
  referencia_externa: string | null;
}

export function ResolucionesDeDevolucion({
  devolucionId,
}: {
  devolucionId: string;
}) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Resolucion[] | null>(null);
  const [abierta, setAbierta] = useState<string | null>(null);
  const [referencia, setReferencia] = useState("");
  const [motivo, setMotivo] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");

  const cargar = useCallback(() => {
    llamar<{ resoluciones: Resolucion[] }>(
      `/api/v1/devoluciones/${devolucionId}`,
    )
      .then((r) => setFilas(r.datos?.resoluciones ?? []))
      .catch((e) => setFallo(e));
  }, [devolucionId]);
  useEffect(cargar, [cargar]);

  async function anotar(id: string, confirmado: boolean) {
    setFallo(null);
    try {
      const r = await llamar<{ estado_abono: string }>(
        `/api/v1/devoluciones/resoluciones/${id}/abono`,
        {
          metodo: "POST",
          cuerpo: {
            confirmado,
            referencia: referencia.trim(),
            motivo: motivo.trim(),
          },
        },
      );
      setAviso(t("devolucion.abonoAnotado", { estado: r.datos.estado_abono }));
      setAbierta(null);
      setReferencia("");
      setMotivo("");
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  if (filas === null && !fallo) return null;

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-2">{t("devolucion.resoluciones")}</h2>
      {aviso ? (
        <p className="mb-2 text-dato text-ink" role="status">
          {aviso}
        </p>
      ) : null}
      {filas && filas.length === 0 ? (
        <p className="text-dato text-ink-muted">
          {t("devolucion.sinResoluciones")}
        </p>
      ) : null}
      {filas && filas.length > 0 ? (
        <Rejilla
          titulo={t("devolucion.resoluciones")}
          cabeceras={[
            t("devolucion.col.tipo"),
            t("devolucion.col.aCargo"),
            t("devolucion.col.importe"),
            t("devolucion.col.abono"),
            "",
          ]}
        >
          {filas.map((r) => (
            <tr key={r.id}>
              <Casilla>
                {t(`devolucion.tipo.${r.tipo}`, { defaultValue: r.tipo })}
              </Casilla>
              <Casilla className="text-ink-muted">
                {r.a_cargo_de ?? "—"}
              </Casilla>
              <Casilla enUnaLinea>{r.importe ?? "—"}</Casilla>
              <Casilla>
                {r.estado_abono ?? "—"}
                {r.referencia_externa ? ` · ${r.referencia_externa}` : ""}
              </Casilla>
              <Casilla enUnaLinea>
                {r.tipo === "abono" && r.estado_abono === "solicitado" ? (
                  <button
                    type="button"
                    className="btn-link"
                    onClick={() => setAbierta(abierta === r.id ? null : r.id)}
                  >
                    {t("devolucion.anotarAbono")}
                  </button>
                ) : null}
              </Casilla>
            </tr>
          ))}
        </Rejilla>
      ) : null}
      {abierta ? (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("devolucion.referencia")}
            <input
              className="input-base"
              value={referencia}
              onChange={(e) => setReferencia(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("devolucion.motivoRechazo")}
            <input
              className="input-base"
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
            />
          </label>
          <div className="flex gap-2 md:col-span-2">
            <button
              type="button"
              className="btn-primary"
              onClick={() => void anotar(abierta, true)}
            >
              {t("devolucion.confirmarAbono")}
            </button>
            <button
              type="button"
              className="btn-secondary"
              disabled={!motivo.trim()}
              onClick={() => void anotar(abierta, false)}
            >
              {t("devolucion.rechazarAbono")}
            </button>
          </div>
        </div>
      ) : null}
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}
