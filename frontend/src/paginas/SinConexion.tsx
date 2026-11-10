/**
 * Lo hecho sin conexión y sus conflictos (CRM-06.02.01.04).
 *
 * Lo que se guarda sin red se queda en el dispositivo (`lib/sinConexion.ts`) y
 * se envía al volver. Lo que no choca lo aplica el servidor; lo que choca —otra
 * persona cambió el mismo campo entre medias— llega aquí con los DOS valores,
 * y se decide campo a campo. Elegir uno automáticamente tira el trabajo de
 * alguien sin que se entere.
 *
 * Comprobado en el navegador el 09-11-2026: sin red se edita un contacto, la
 * franja dice «1 cambio pendiente», al volver la red se envía solo; y con el
 * mismo campo cambiado en el servidor entre medias, sale aquí el conflicto con
 * lo mío y lo suyo, y «Aplicar lo elegido» lo resuelve.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { fechaHora } from "@/lib/formato";
import {
  alCambiar,
  cola,
  descartar,
  resolver,
  sincronizar,
  type OperacionEncolada,
  type Resultado,
} from "@/lib/sinConexion";
import { cn } from "@/lib/utiles";

function valor(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

export function SinConexion() {
  const { t } = useTranslation();
  const [ops, setOps] = useState<OperacionEncolada[]>([]);
  const [enLinea, setEnLinea] = useState(() => navigator.onLine);
  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState<Resultado | null>(null);

  const leer = useCallback(() => {
    setEnLinea(navigator.onLine);
    void cola().then(setOps);
  }, []);
  useEffect(() => {
    leer();
    return alCambiar(leer);
  }, [leer]);

  async function enviar() {
    setEnviando(true);
    try {
      setResultado(await sincronizar());
    } finally {
      setEnviando(false);
    }
  }

  const conflictos = ops.filter((o) => o.estado === "conflicto");
  const resto = ops.filter((o) => o.estado !== "conflicto");

  return (
    <>
      <CabeceraPagina
        icono="cloud_off"
        titulo={t("sinConexion.titulo")}
        entradilla={t("sinConexion.entradilla")}
        acciones={
          <button
            type="button"
            className="btn-primary"
            disabled={!enLinea || enviando || !resto.length}
            onClick={() => void enviar()}
          >
            <Icono nombre="cloud_upload" tamano="sm" />
            {t("sinConexion.enviar")}
          </button>
        }
      />
      <div role="status" className="mb-3 text-dato">
        <p className={cn(enLinea ? "text-success" : "text-warning")}>
          {enLinea ? t("sinConexion.conRed") : t("sinConexion.sinRed")}
        </p>
        {resultado ? (
          <p className="text-ink-faint">
            {t("sinConexion.resultado", {
              enviadas: resultado.enviadas,
              conflictos: resultado.conflictos,
              rechazadas: resultado.rechazadas,
            })}
          </p>
        ) : null}
      </div>

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("sinConexion.conflictos")}</h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {t("sinConexion.conflictosAyuda")}
        </p>
        {conflictos.length === 0 ? (
          <Vacio titulo={t("sinConexion.sinConflictos")} compacto />
        ) : (
          <div className="space-y-4">
            {conflictos.map((op) => (
              <ResolverConflicto key={op.id_cliente} op={op} />
            ))}
          </div>
        )}
      </section>

      <section className="card p-4">
        <h2 className="section-label mb-1">{t("sinConexion.cola")}</h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {t("sinConexion.colaAyuda")}
        </p>
        {resto.length === 0 ? (
          <Vacio titulo={t("sinConexion.colaVacia")} compacto />
        ) : (
          <Rejilla
            titulo={t("sinConexion.cola")}
            cabeceras={[
              t("sinConexion.cuando"),
              t("sinConexion.que"),
              t("sinConexion.campos"),
              t("sinConexion.estado"),
              "",
            ]}
          >
            {resto.map((op) => (
              <tr
                key={op.id_cliente}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla enUnaLinea>{fechaHora(op.encolada_at)}</Casilla>
                <Casilla>
                  {t(`sinConexion.tipos.${op.tipo}`)} · {op.recurso}
                </Casilla>
                <Casilla>{Object.keys(op.campos).join(", ")}</Casilla>
                <Casilla>
                  <span
                    className={cn(
                      "chip-dato",
                      op.estado === "rechazada" && "chip-dato--mal",
                    )}
                  >
                    {t(`sinConexion.estados.${op.estado}`)}
                  </span>
                  {op.motivo ? (
                    <span className="ml-2 text-rotulo text-ink-faint">
                      {op.motivo}
                    </span>
                  ) : null}
                </Casilla>
                <Casilla className="text-right">
                  <button
                    type="button"
                    className="btn-link"
                    onClick={() => void descartar(op.id_cliente)}
                  >
                    {t("sinConexion.descartar")}
                  </button>
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        )}
      </section>
    </>
  );
}

function ResolverConflicto({ op }: { op: OperacionEncolada }) {
  const { t } = useTranslation();
  const choque = op.conflicto!;
  // Por defecto, NINGUNO elegido: decidir es de la persona, y un valor
  // preseleccionado se acepta sin leer.
  const [eleccion, setEleccion] = useState<Record<string, "mio" | "suyo">>({});
  const completo = choque.campos.every((c) => eleccion[c]);

  // Un borrado que chocó: otra persona cambió el registro después de que se
  // leyera. No hay campos que elegir; se pregunta si borrarlo igualmente.
  if (op.tipo === "borrar") {
    return (
      <div className="rounded border border-ink-dim/40 p-3">
        <p className="mb-2 text-dato">
          {op.recurso} · {fechaHora(op.encolada_at)}
        </p>
        <p className="text-dato text-ink-muted">
          {t("sinConexion.borradoEnConflicto")}
        </p>
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            className="btn-danger"
            onClick={() => void resolver(op, {}).then(() => sincronizar())}
          >
            {t("sinConexion.borrarIgualmente")}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => void descartar(op.id_cliente)}
          >
            {t("sinConexion.quedarmeConLoSuyo")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded border border-ink-dim/40 p-3">
      <p className="mb-2 text-dato">
        {op.recurso} · {fechaHora(op.encolada_at)}
      </p>
      <Rejilla
        titulo={t("sinConexion.conflictos")}
        acotada={false}
        cabeceras={[
          t("sinConexion.campo"),
          t("sinConexion.loMio"),
          t("sinConexion.loSuyo"),
        ]}
      >
        {choque.campos.map((campo) => (
          <tr key={campo} className="border-b border-ink-dim/30 last:border-0">
            <Casilla>{campo}</Casilla>
            {(["mio", "suyo"] as const).map((lado) => (
              <Casilla key={lado}>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name={`${op.id_cliente}-${campo}`}
                    checked={eleccion[campo] === lado}
                    onChange={() =>
                      setEleccion((e) => ({ ...e, [campo]: lado }))
                    }
                  />
                  <span>
                    {valor(
                      lado === "mio"
                        ? op.campos[campo]
                        : choque.valores_servidor[campo],
                    )}
                  </span>
                </label>
              </Casilla>
            ))}
          </tr>
        ))}
      </Rejilla>
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={!completo}
          onClick={() =>
            void resolver(
              op,
              Object.fromEntries(
                Object.entries(eleccion).map(([c, l]) => [c, l === "mio"]),
              ),
            ).then(() => sincronizar())
          }
        >
          {t("sinConexion.aplicar")}
        </button>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => void descartar(op.id_cliente)}
        >
          {t("sinConexion.quedarmeConLoSuyo")}
        </button>
      </div>
    </div>
  );
}
