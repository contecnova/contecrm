/**
 * El consumo, hacia facturación (CRM-00.01.06.07).
 *
 * El consumo se medía y se enseñaba, y no salía de la pantalla: para cobrar por
 * uso había que copiar los números a mano cada mes (medido el 09-11-2026).
 * Aquí se toma un corte —lo que lleva gastado la empresa en cada módulo, en
 * formato neutro: periodo, módulo, métrica, cantidad, unidad y tope—, se
 * descarga en CSV o JSON, y se manda al sistema de facturación configurado
 * como un webhook de la casa (firmado). Cada corte dice cómo fue su envío:
 * enviado con el código que contestó, fallido con el porqué, o sin destino.
 * Los cortes periódicos los toma una tarea si el ajuste lo enciende.
 *
 * Comprobado el 09-11-2026 contra un doble HTTP del sistema de cobro: el corte
 * viaja firmado en JSON o CSV con las cabeceras configuradas, un 422 queda
 * «fallido» con su porqué, sin URL queda «sin destino», un módulo caído deja
 * el corte incompleto y no en cero, y la tarea manda el corte al cerrar el
 * periodo.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { cn } from "@/lib/utiles";

interface Destino {
  configurado: boolean;
  maquina: string;
  formato: string;
  periodica: boolean;
  max_intentos: number;
  columnas: string[];
}

interface Corte {
  id: string;
  periodo: string;
  origen: "manual" | "programado";
  filas: number;
  completo: boolean;
  no_leidos: string[];
  estado_envio: "pendiente" | "enviado" | "fallido" | "sin_destino" | "abierto";
  intentos: number;
  ultimo_error: string;
  respuesta_codigo: number | null;
  enviado_at: string | null;
  tomado_at: string | null;
}

const TONO: Record<Corte["estado_envio"], string> = {
  enviado: "chip-dato--si",
  fallido: "chip-dato--mal",
  sin_destino: "chip-dato--aviso",
  pendiente: "",
  abierto: "",
};

export function ConsumoAFacturacion() {
  const { t } = useTranslation();
  const [destino, setDestino] = useState<Destino | null>(null);
  const [cortes, setCortes] = useState<Corte[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    llamar<Destino>("/api/v1/facturacion/destino")
      .then((r) => setDestino(r.datos))
      .catch((e) => setFallo(e));
    llamar<{ cortes: Corte[] }>("/api/v1/facturacion/cortes")
      .then((r) => setCortes(r.datos.cortes ?? []))
      .catch((e) => setFallo(e));
  }, []);
  useEffect(cargar, [cargar]);

  async function tomar(enviar: boolean) {
    setOcupado(true);
    try {
      const r = await llamar<Corte>("/api/v1/facturacion/cortes", {
        metodo: "POST",
        cuerpo: { enviar },
      });
      setAviso(
        t(`consumoFacturacion.estados.${r.datos.estado_envio}`) +
          " · " +
          t("consumoFacturacion.tomado", { periodo: r.datos.periodo }),
      );
      cargar();
    } catch (e) {
      setFallo(e);
    } finally {
      setOcupado(false);
    }
  }

  async function enviar(c: Corte) {
    try {
      const r = await llamar<Corte>(
        `/api/v1/facturacion/cortes/${c.id}/enviar`,
        { metodo: "POST" },
      );
      setAviso(t(`consumoFacturacion.estados.${r.datos.estado_envio}`));
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function descargar(c: Corte, formato: "csv" | "json") {
    try {
      const r = await llamar<{
        fichero: string;
        tipo: string;
        contenido: string;
      }>(`/api/v1/facturacion/cortes/${c.id}/exportar?formato=${formato}`);
      const url = URL.createObjectURL(
        new Blob([r.datos.contenido], { type: r.datos.tipo }),
      );
      const enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = r.datos.fichero;
      enlace.click();
      URL.revokeObjectURL(url);
      setAviso(
        t("consumoFacturacion.descargado", { fichero: r.datos.fichero }),
      );
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !cortes) return <Fallo error={fallo} />;
  if (!cortes || !destino) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        icono="receipt_long"
        titulo={t("consumoFacturacion.titulo")}
        entradilla={t("consumoFacturacion.entradilla")}
        acciones={
          <>
            <button
              type="button"
              className="btn-secondary"
              disabled={ocupado}
              onClick={() => void tomar(false)}
            >
              <Icono nombre="add_chart" tamano="sm" />
              {t("consumoFacturacion.tomar")}
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={ocupado}
              onClick={() => void tomar(true)}
            >
              <Icono nombre="send" tamano="sm" />
              {t("consumoFacturacion.tomarYEnviar")}
            </button>
          </>
        }
      />
      <div role="status" className="mb-3">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">
          {t("consumoFacturacion.destino")}
        </h2>
        <p className="text-dato text-ink">
          {destino.configurado
            ? t("consumoFacturacion.destinoConfigurado", {
                maquina: destino.maquina,
                formato: destino.formato,
              })
            : t("consumoFacturacion.sinDestino")}
        </p>
        <p className="text-rotulo text-ink-faint">
          {destino.periodica
            ? t("consumoFacturacion.periodicaSi", {
                n: destino.max_intentos,
              })
            : t("consumoFacturacion.periodicaNo")}
        </p>
        <p className="text-rotulo text-ink-faint">
          {t("consumoFacturacion.columnas", {
            columnas: destino.columnas.join(", "),
          })}
        </p>
      </section>

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">{t("consumoFacturacion.cortes")}</h2>
        {cortes.length === 0 ? (
          <Vacio titulo={t("consumoFacturacion.sinCortes")} compacto />
        ) : (
          <Rejilla
            titulo={t("consumoFacturacion.cortes")}
            cabeceras={[
              t("consumoFacturacion.periodo"),
              t("consumoFacturacion.tomadoEl"),
              t("consumoFacturacion.origen"),
              t("consumoFacturacion.filas"),
              t("consumoFacturacion.envio"),
              "",
            ]}
          >
            {cortes.map((c) => (
              <tr
                key={c.id}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla enUnaLinea className="font-medium text-ink">
                  {c.periodo}
                </Casilla>
                <Casilla enUnaLinea>{fechaHora(c.tomado_at)}</Casilla>
                <Casilla>
                  {t(`consumoFacturacion.origenes.${c.origen}`)}
                </Casilla>
                <Casilla>
                  {c.filas}
                  {c.completo ? null : (
                    <span
                      className="chip-dato chip-dato--aviso ml-2"
                      title={c.no_leidos.join(", ")}
                    >
                      {t("consumoFacturacion.incompleto", {
                        modulos: c.no_leidos.join(", "),
                      })}
                    </span>
                  )}
                </Casilla>
                <Casilla>
                  <span className={cn("chip-dato", TONO[c.estado_envio])}>
                    {t(`consumoFacturacion.estados.${c.estado_envio}`)}
                  </span>
                  {c.respuesta_codigo ? (
                    <span className="ml-2 text-rotulo text-ink-faint">
                      HTTP {c.respuesta_codigo}
                    </span>
                  ) : null}
                  {c.ultimo_error ? (
                    <p className="text-rotulo text-ink-faint">
                      {c.ultimo_error}
                    </p>
                  ) : null}
                  {c.intentos ? (
                    <p className="text-rotulo text-ink-faint">
                      {t("consumoFacturacion.intentos", { count: c.intentos })}
                    </p>
                  ) : null}
                </Casilla>
                <Casilla>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => void descargar(c, "csv")}
                    >
                      <Icono nombre="download" tamano="sm" />
                      {t("consumoFacturacion.csv")}
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => void descargar(c, "json")}
                    >
                      <Icono nombre="download" tamano="sm" />
                      {t("consumoFacturacion.json")}
                    </button>
                    {c.estado_envio !== "abierto" ? (
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => void enviar(c)}
                      >
                        <Icono nombre="send" tamano="sm" />
                        {c.estado_envio === "enviado"
                          ? t("consumoFacturacion.reenviar")
                          : t("consumoFacturacion.enviar")}
                      </button>
                    ) : null}
                  </div>
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        )}
      </section>
    </>
  );
}
