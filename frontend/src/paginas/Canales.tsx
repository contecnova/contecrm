/**
 * Por qué canales se le puede escribir a alguien, y con qué reglas
 * (CRM-02.03.02.01, CRM-02.03.02.02, CRM-02.03.02.03, CRM-02.03.02.04,
 * CRM-02.03.02.05, CRM-02.03.02.07).
 *
 * Los canales estaban declarados y el consentimiento se guardaba por canal y
 * por destino, y no había ninguna pantalla que contestara la pregunta de
 * antes de mandar nada: **«¿se le puede escribir a esta persona por aquí?»**.
 *
 * Y es una pregunta con cinco respuestas distintas, no una:
 *
 * **El consentimiento es por canal y por destino, no global.** Alguien puede
 * haber aceptado el correo y no el SMS, y tratarlo como una sola casilla es
 * lo que convierte una baja en una denuncia.
 *
 * **En WhatsApp manda la ventana de 24 horas.** Fuera de ella sólo sale una
 * plantilla aprobada, y el estado de aprobación lo pone el proveedor y no
 * nosotros: mandar una no aprobada no falla, el proveedor la descarta en
 * silencio — así que se corta antes de salir y aquí se dice.
 *
 * **La baja se da con una palabra, y cada canal tiene la suya.** Enseñarla es
 * parte de poder usar el canal: quien escribe el mensaje tiene que poner esa
 * palabra dentro.
 *
 * **Y el calentamiento de un dominio nuevo frena.** Una IP que manda cien mil
 * el primer día se quema, y quemarla cuesta semanas en las que no llega nada
 * por ese dominio — ni las campañas ni las facturas, que comparten
 * reputación. Cuando hay tope, sale el tope.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { listar } from "@/lib/listados";

interface Canal {
  id: string;
  clave: string;
  nombre: string;
  /** email | sms | whatsapp | push | rcs */
  tipo: string;
  activo: boolean;
  /** La palabra con la que alguien se da de baja por este canal. */
  como_se_da_de_baja: string;
}

interface Comprobacion {
  se_puede_mandar: boolean;
  /** El porqué, uno por regla que lo impide. */
  motivos: string[];
  canal: string;
  /** WhatsApp fuera de la ventana: sólo plantilla aprobada. */
  necesita_plantilla: boolean;
  ventana_abierta: boolean;
  como_se_da_de_baja: string;
  /** `null` si el dominio no está calentando: quien pinta no sabe de eso. */
  calentamiento: { tope_hoy?: number; dia?: number } | null;
}

export function Canales() {
  const { t } = useTranslation();
  const [canales, setCanales] = useState<Canal[] | null>(null);
  const [canal, setCanal] = useState("");
  const [destino, setDestino] = useState("");
  const [resultado, setResultado] = useState<Comprobacion | null>(null);
  const [comprobando, setComprobando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    listar<Canal>("/api/v1/canales-marketing", { signal: control.signal })
      .then(setCanales)
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  async function comprobar() {
    if (!canal || !destino.trim()) return;
    setComprobando(true);
    setFallo(null);
    try {
      const r = await llamar<Comprobacion>(
        `/api/v1/canales-marketing/comprobar?canal=${encodeURIComponent(canal)}&destino=${encodeURIComponent(destino)}`,
      );
      setResultado(r.datos);
    } catch (error) {
      setFallo(error);
    } finally {
      setComprobando(false);
    }
  }

  if (fallo && !canales) return <Fallo error={fallo} reintentar={cargar} />;

  return (
    <>
      <CabeceraPagina
        titulo={t("canalesmk.titulo")}
        icono="forum"
        entradilla={t("canalesmk.entradilla")}
      />

      <section className="card mb-4 p-4">
        <h2 className="text-sm font-medium text-ink">{t("canalesmk.comprobar")}</h2>
        <p className="mt-1 text-3xs text-ink-faint">{t("canalesmk.porqueComprobar")}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select
            className="input-base"
            value={canal}
            aria-label={t("canalesmk.canal")}
            onChange={(e) => setCanal(e.target.value)}
          >
            <option value="">{t("canalesmk.elegirCanal")}</option>
            {(canales ?? []).map((c) => (
              <option key={c.id} value={c.clave}>
                {c.nombre}
              </option>
            ))}
          </select>
          <input
            className="input-base"
            value={destino}
            aria-label={t("canalesmk.destino")}
            placeholder={t("canalesmk.destino")}
            onChange={(e) => setDestino(e.target.value)}
          />
          <button
            type="button"
            className="btn-secundario"
            disabled={!canal || !destino.trim() || comprobando}
            onClick={() => void comprobar()}
          >
            {comprobando ? t("canalesmk.comprobando") : t("canalesmk.ver")}
          </button>
        </div>

        {resultado ? (
          <div className="mt-3" role="status" aria-live="polite">
            <p
              className={
                resultado.se_puede_mandar
                  ? "text-2xs text-success"
                  : "text-2xs text-danger"
              }
            >
              {resultado.se_puede_mandar
                ? t("canalesmk.siSePuede")
                : t("canalesmk.noSePuede")}
            </p>
            {/* Los motivos, uno por regla. «No se puede» a secas deja a quien
                escribe el mensaje sin saber qué arreglar. */}
            <ul className="mt-1 flex flex-col gap-1">
              {(resultado.motivos ?? []).map((m, i) => (
                <li key={i} className="text-2xs text-ink">
                  {m}
                </li>
              ))}
            </ul>
            {/* La ventana de WhatsApp: fuera de ella sólo plantilla aprobada,
                y mandar una no aprobada no falla — el proveedor la descarta. */}
            {resultado.necesita_plantilla ? (
              <p className="mt-1 text-2xs text-warning">{t("canalesmk.necesitaPlantilla")}</p>
            ) : null}
            {resultado.como_se_da_de_baja ? (
              <p className="mt-1 text-2xs text-ink-muted">
                {t("canalesmk.bajaCon", { palabra: resultado.como_se_da_de_baja })}
              </p>
            ) : null}
            {/* El tope de calentamiento sólo cuando lo hay: `null` significa
                que ese dominio no está calentando, no que el tope sea cero. */}
            {resultado.calentamiento ? (
              <p className="mt-1 font-mono text-2xs text-warning">
                {t("canalesmk.calentando", {
                  tope: resultado.calentamiento.tope_hoy ?? "—",
                })}
              </p>
            ) : null}
          </div>
        ) : null}
      </section>

      <section>
        <h2 className="text-sm font-medium text-ink">{t("canalesmk.declarados")}</h2>
        {!canales || canales.length === 0 ? (
          <Vacio titulo={t("canalesmk.sinCanales")} detalle={t("canalesmk.sinCanalesDetalle")} />
        ) : (
          <ul className="lista-acotada mt-2 flex flex-col gap-2 pr-1">
            {canales.map((c) => (
              <li key={c.id} className="card flex flex-wrap items-baseline gap-2 p-3">
                <span className="flex-1 text-sm text-ink">{c.nombre}</span>
                <span className="chip-dato">{c.tipo}</span>
                <span className={c.activo ? "badge badge-muted" : "badge badge-aviso"}>
                  {t(c.activo ? "canalesmk.activo" : "canalesmk.apagado")}
                </span>
                {/* La palabra de baja va en la lista, no escondida: quien
                    escribe el mensaje tiene que ponerla dentro. */}
                <span className="w-full font-mono text-3xs text-ink-faint">
                  {c.como_se_da_de_baja
                    ? t("canalesmk.sedaDeBajaCon", { palabra: c.como_se_da_de_baja })
                    : t("canalesmk.sinFormaDeBaja")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
