/**
 * Clasificación TCSEC de la instalación (CRM-07.03.02.11).
 *
 * Pedido el 09-11-2026 («un GRC que pueda llegar a tener un TCSEC como los de
 * Infor»). Qué nivel alcanza la instalación, requisito a requisito: los que se
 * miden, medidos en el momento sobre el sistema; los que sólo puede afirmar una
 * persona, atestiguados aquí con su evidencia —quedan como evaluación de un
 * control del GRC—, y el informe para auditoría que se descarga.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { usePuedeOperar } from "@/lib/permisos";
import { cn } from "@/lib/utiles";

interface Requisito {
  clave: string;
  nivel: string;
  titulo: string;
  exige: string;
  como: "automatico" | "atestiguado";
  estado: "cumple" | "no_cumple" | "sin_medir" | "no_implementado";
  detalle: string;
  datos: Record<string, unknown>;
}

interface Evaluacion {
  generado_at: string;
  nivel: string;
  nombre_nivel: string;
  siguiente: string | null;
  falta_para_el_siguiente: string[];
  niveles: { nivel: string; nombre: string }[];
  requisitos: Requisito[];
}

const TONO: Record<Requisito["estado"], string> = {
  cumple: "chip-dato--si",
  no_cumple: "chip-dato--mal",
  sin_medir: "chip-dato--aviso",
  no_implementado: "chip-dato--mal",
};

const RESULTADOS = ["efectivo", "parcial", "inefectivo", "no_aplica"] as const;

export function Tcsec() {
  const { t } = useTranslation();
  const [ev, setEv] = useState<Evaluacion | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [midiendo, setMidiendo] = useState(false);
  const [aviso, setAviso] = useState("");
  // Desde el control del GRC se llega aquí con `?requisito=` (CRM-07.03.02.14).
  const [params] = useSearchParams();
  const elegido = params.get("requisito") ?? "";
  const puede = usePuedeOperar();

  const medir = useCallback(() => {
    setMidiendo(true);
    llamar<Evaluacion>("/api/v1/tcsec/evaluacion")
      .then((r) => {
        setEv(r.datos);
        setFallo(null);
      })
      .catch((e) => setFallo(e))
      .finally(() => setMidiendo(false));
  }, []);
  useEffect(medir, [medir]);
  useEffect(() => {
    if (ev && elegido)
      document
        .getElementById(`requisito-${elegido}`)
        ?.scrollIntoView({ block: "center" });
  }, [ev, elegido]);

  async function descargar() {
    try {
      const r = await llamar<{ fichero: string; contenido: string }>(
        "/api/v1/tcsec/informe",
      );
      const url = URL.createObjectURL(
        new Blob([r.datos.contenido], { type: "text/markdown;charset=utf-8" }),
      );
      const enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = r.datos.fichero;
      enlace.click();
      URL.revokeObjectURL(url);
      setAviso(t("tcsec.descargado", { fichero: r.datos.fichero }));
    } catch (e) {
      setFallo(e);
    }
  }

  // Lo medido queda como evidencia de los controles TCSEC del GRC
  // (CRM-07.03.02.14): la medida de esta pantalla no se guarda sola.
  async function alGrc() {
    try {
      const r = await llamar<{
        controles: number;
        por_resultado: Record<string, number>;
      }>("/api/v1/grc/controles/evaluar-automaticos?origen=tcsec", {
        metodo: "POST",
      });
      setAviso(t("tcsec.enElGrc", { n: r.datos.controles }));
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !ev) return <Fallo error={fallo} />;
  if (!ev) return <Cargando />;

  const alcanzado = ev.niveles.findIndex((n) => n.nivel === ev.nivel);

  return (
    <>
      <CabeceraPagina
        icono="verified_user"
        titulo={t("tcsec.titulo")}
        entradilla={t("tcsec.entradilla")}
        acciones={
          <>
            <button
              type="button"
              className="btn-secondary"
              disabled={midiendo}
              onClick={medir}
            >
              <Icono nombre="refresh" tamano="sm" />
              {midiendo ? t("tcsec.midiendo") : t("tcsec.medir")}
            </button>
            {puede("POST", "/api/v1/grc/controles/evaluar-automaticos") ? (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => void alGrc()}
              >
                <Icono nombre="fact_check" tamano="sm" />
                {t("tcsec.dejarEnGrc")}
              </button>
            ) : null}
            <button
              type="button"
              className="btn-primary"
              onClick={() => void descargar()}
            >
              <Icono nombre="download" tamano="sm" />
              {t("tcsec.descargar")}
            </button>
          </>
        }
      />
      <div role="status" className="mb-3">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">{t("tcsec.nivel")}</h2>
        <ol className="flex flex-wrap gap-2" aria-label={t("tcsec.escala")}>
          {ev.niveles.map((n, i) => (
            <li
              key={n.nivel}
              aria-current={n.nivel === ev.nivel ? "step" : undefined}
              className={cn(
                "chip-dato",
                i <= alcanzado ? "chip-dato--si" : "",
                n.nivel === ev.nivel && "font-semibold",
              )}
              title={n.nombre}
            >
              {n.nivel} · {n.nombre}
            </li>
          ))}
        </ol>
        <p className="mt-3 text-dato text-ink">
          {t("tcsec.alcanzado", { nivel: ev.nivel, nombre: ev.nombre_nivel })}
          {ev.siguiente
            ? " " +
              t("tcsec.falta", {
                siguiente: ev.siguiente,
                count: ev.falta_para_el_siguiente.length,
              })
            : null}
        </p>
        <p className="text-rotulo text-ink-faint">
          {t("tcsec.medidoEl", {
            fecha: fechaHora(ev.generado_at),
          })}
        </p>
      </section>

      {ev.niveles.slice(1).map((n) => {
        const suyos = ev.requisitos.filter((r) => r.nivel === n.nivel);
        if (suyos.length === 0) return null;
        return (
          <section key={n.nivel} className="card mb-4 p-4">
            <h2 className="section-label mb-2">
              {n.nivel} · {n.nombre}
            </h2>
            <ul className="divide-y divide-ink-dim/30">
              {suyos.map((r) => (
                <FilaRequisito
                  key={r.clave}
                  r={r}
                  falta={
                    (n.nivel === ev.siguiente &&
                      ev.falta_para_el_siguiente.includes(r.clave)) ||
                    r.clave === elegido
                  }
                  alCambiar={medir}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </>
  );
}

function FilaRequisito({
  r,
  falta,
  alCambiar,
}: {
  r: Requisito;
  falta: boolean;
  alCambiar: () => void;
}) {
  const { t } = useTranslation();
  const [abierta, setAbierta] = useState(false);
  const [resultado, setResultado] = useState<string>("efectivo");
  const [evidencia, setEvidencia] = useState("");
  const [plan, setPlan] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const evidenciaPrevia =
    r.como === "atestiguado" ? String(r.datos.evidencia ?? "") : "";

  async function guardar() {
    try {
      await llamar(`/api/v1/tcsec/requisitos/${r.clave}/atestacion`, {
        metodo: "PUT",
        cuerpo: { resultado, evidencia, plan_accion: plan },
      });
      setAbierta(false);
      setEvidencia("");
      setPlan("");
      setFallo(null);
      alCambiar();
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <li
      id={`requisito-${r.clave}`}
      className={cn("py-3 text-dato", falta && "bg-paper-light/40")}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className={cn("chip-dato", TONO[r.estado])}>
              {t(`tcsec.estados.${r.estado}`)}
            </span>
            <span className="font-medium text-ink">{r.titulo}</span>
            <span className="text-rotulo text-ink-faint">
              {r.clave} ·{" "}
              {r.como === "automatico"
                ? t("tcsec.medido")
                : t("tcsec.atestiguado")}
            </span>
            {/* Su control en el GRC, con la evidencia que deja al evaluarse. */}
            <Link
              to={`/controles-grc?control=TCSEC-${r.clave}`}
              className="btn-link text-rotulo"
            >
              {t("tcsec.suControl", { codigo: `TCSEC-${r.clave}` })}
            </Link>
          </div>
          <p className="text-rotulo text-ink-faint">{r.exige}</p>
          <p className="mt-0.5 text-ink-muted">{r.detalle}</p>
          {evidenciaPrevia ? (
            <p className="text-rotulo text-ink-faint">
              {t("tcsec.evidencia")}: {evidenciaPrevia}
            </p>
          ) : null}
        </div>
        {r.como === "atestiguado" ? (
          <button
            type="button"
            className="btn-secondary shrink-0"
            onClick={() => setAbierta((v) => !v)}
          >
            {t("tcsec.atestiguar")}
          </button>
        ) : null}
      </div>
      {abierta ? (
        <div className="mt-2 grid gap-2 md:grid-cols-[12rem_1fr]">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("tcsec.resultado")}
            <select
              className="input-base"
              value={resultado}
              onChange={(e) => setResultado(e.target.value)}
            >
              {RESULTADOS.map((x) => (
                <option key={x} value={x}>
                  {t(`tcsec.resultados.${x}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("tcsec.evidencia")}
            <input
              className="input-base"
              value={evidencia}
              placeholder={t("tcsec.evidenciaAyuda")}
              onChange={(e) => setEvidencia(e.target.value)}
            />
          </label>
          {resultado !== "efectivo" && resultado !== "no_aplica" ? (
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
              {t("tcsec.plan")}
              <input
                className="input-base"
                value={plan}
                onChange={(e) => setPlan(e.target.value)}
              />
            </label>
          ) : null}
          <div className="md:col-span-2">
            <button
              type="button"
              className="btn-primary"
              disabled={!evidencia.trim()}
              onClick={() => void guardar()}
            >
              {t("tcsec.guardar")}
            </button>
          </div>
          {fallo ? (
            <div className="md:col-span-2">
              <Fallo error={fallo} />
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
