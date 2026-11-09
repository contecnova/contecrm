/**
 * Una audiencia sincronizada con una plataforma publicitaria (CRM-02.01.01.09).
 *
 * Antes sólo se preparaba una lista troceada que no iba a ninguna parte. Aquí
 * se da de alta sobre un segmento y una conexión de integraciones —la
 * plataforma es configuración: tres operaciones declaradas, crear, añadir y
 * quitar—, se sincroniza y se ve **cada vuelta**: altas, bajas, quién se quedó
 * fuera por falta de consentimiento o por supresión, y el error si lo hubo.
 *
 * Verificado pulsando el 09-11-2026 contra un doble HTTP local de plataforma:
 * la primera vuelta crea la audiencia y sube a quien consintió; tras suprimir a
 * una persona, la siguiente vuelta manda su baja antes que ninguna alta.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { cn } from "@/lib/utiles";

interface Vuelta {
  id: string;
  at: string;
  ok: boolean;
  altas: number;
  bajas: number;
  en_el_segmento: number;
  sin_consentimiento: number;
  suprimidos: number;
  error: string | null;
  porque: string;
}

interface Ficha {
  id: string;
  nombre: string;
  segmento_id: string;
  conexion_id: string;
  finalidad: string;
  id_externo: string | null;
  estado: string;
  miembros: number;
  ultima_sync_at: string | null;
  ultimo_error: string | null;
  minimo: number;
  finalidad_exigida: string;
  historial: Vuelta[];
}

interface Opcion {
  id: string;
  nombre: string;
}

const TONO: Record<string, string> = {
  sincronizada: "chip-dato--si",
  error: "chip-dato--mal",
  pequena: "chip-dato--aviso",
};

export function AudienciaPublicitaria() {
  const { id = "" } = useParams();
  if (id === "nueva") return <AltaDeAudiencia />;
  return <FichaDeAudiencia id={id} />;
}

function AltaDeAudiencia() {
  const { t } = useTranslation();
  const navegar = useNavigate();
  const [segmentos, setSegmentos] = useState<Opcion[]>([]);
  const [conexiones, setConexiones] = useState<Opcion[]>([]);
  const [nombre, setNombre] = useState("");
  const [segmento, setSegmento] = useState("");
  const [conexion, setConexion] = useState("");
  const [finalidad, setFinalidad] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    // Las dos listas pueden venir paginadas o como lista: se aceptan las dos.
    const filas = (d: unknown): Opcion[] =>
      Array.isArray(d)
        ? (d as Opcion[])
        : (((d as { items?: Opcion[] } | null)?.items ?? []) as Opcion[]);
    llamar<unknown>("/api/v1/segmentos")
      .then((r) => setSegmentos(filas(r.datos)))
      .catch(() => setSegmentos([]));
    llamar<unknown>("/api/v1/integraciones/conexiones")
      .then((r) => setConexiones(filas(r.datos)))
      .catch(() => setConexiones([]));
  }, []);

  async function crear() {
    try {
      const r = await llamar<{ id: string }>(
        "/api/v1/audiencias-publicitarias",
        {
          metodo: "POST",
          cuerpo: {
            nombre,
            segmento_id: segmento,
            conexion_id: conexion,
            finalidad,
          },
        },
      );
      navegar(`/m/segmentos/audiencia_publicitaria/${r.datos.id}`);
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <>
      <CabeceraPagina
        titulo={t("mk.audiencia.nueva")}
        entradilla={t("mk.audiencia.intro")}
        icono="campaign"
      />
      <section className="card max-w-2xl p-4">
        <div className="grid gap-3">
          <label className="text-dato text-ink-muted">
            {t("mk.audiencia.nombre")}
            <input
              className="input-base mt-1"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
            />
          </label>
          <label className="text-dato text-ink-muted">
            {t("mk.audiencia.segmento")}
            <select
              className="input-base mt-1"
              value={segmento}
              onChange={(e) => setSegmento(e.target.value)}
            >
              <option value="">—</option>
              {segmentos.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.nombre}
                </option>
              ))}
            </select>
          </label>
          <label className="text-dato text-ink-muted">
            {t("mk.audiencia.plataforma")}
            <select
              className="input-base mt-1"
              value={conexion}
              onChange={(e) => setConexion(e.target.value)}
            >
              <option value="">—</option>
              {conexiones.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-rotulo text-ink-faint">
              {t("mk.audiencia.plataformaAyuda")}
            </span>
          </label>
          <label className="text-dato text-ink-muted">
            {t("mk.audiencia.finalidad")}
            <input
              className="input-base mt-1"
              value={finalidad}
              onChange={(e) => setFinalidad(e.target.value)}
            />
          </label>
          <div>
            <button
              type="button"
              className="btn-primary"
              disabled={!nombre.trim() || !segmento || !conexion}
              onClick={() => void crear()}
            >
              {t("mk.audiencia.crear")}
            </button>
          </div>
          {fallo ? <Fallo error={fallo} /> : null}
        </div>
      </section>
    </>
  );
}

function FichaDeAudiencia({ id }: { id: string }) {
  const { t } = useTranslation();
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [trabajando, setTrabajando] = useState(false);

  const cargar = useCallback(() => {
    llamar<Ficha>(`/api/v1/audiencias-publicitarias/${id}`)
      .then((r) => setFicha(Array.isArray(r.datos?.historial) ? r.datos : null))
      .catch(setFallo);
  }, [id]);
  useEffect(cargar, [cargar]);

  async function sincronizar() {
    setTrabajando(true);
    try {
      await llamar(`/api/v1/audiencias-publicitarias/${id}/sincronizar`, {
        metodo: "POST",
        cuerpo: {},
      });
      cargar();
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  if (fallo && !ficha) return <Fallo error={fallo} />;
  if (!ficha) return <Cargando />;
  return (
    <>
      <CabeceraPagina
        titulo={ficha.nombre}
        entradilla={t("mk.audiencia.intro")}
        icono="campaign"
        acciones={
          <button
            type="button"
            className="btn-primary"
            disabled={trabajando}
            onClick={() => void sincronizar()}
          >
            {trabajando
              ? t("mk.audiencia.sincronizando")
              : t("mk.audiencia.sincronizar")}
          </button>
        }
      />
      {fallo ? <Fallo error={fallo} /> : null}
      <section className="card mb-4 p-4" role="status">
        <h2 className="section-label mb-2">{t("mk.audiencia.estado")}</h2>
        <div className="flex flex-wrap items-center gap-3 text-dato">
          <span className={cn("chip-dato", TONO[ficha.estado] ?? "")}>
            {t(`mk.audiencia.estados.${ficha.estado}`, {
              defaultValue: ficha.estado,
            })}
          </span>
          <span>{t("mk.audiencia.miembros", { cuantos: ficha.miembros })}</span>
          <span className="text-ink-muted">
            {t("mk.audiencia.idExterno")}: {ficha.id_externo ?? "—"}
          </span>
          <span className="text-ink-muted">
            {t("mk.audiencia.ultima")}:{" "}
            {ficha.ultima_sync_at ? fechaHora(ficha.ultima_sync_at) : "—"}
          </span>
        </div>
        <p className="mt-2 text-rotulo text-ink-faint">
          {t("mk.audiencia.reglas", {
            minimo: ficha.minimo,
            finalidad: ficha.finalidad_exigida,
          })}
        </p>
        {ficha.ultimo_error ? (
          <p className="mt-1 text-dato text-danger">{ficha.ultimo_error}</p>
        ) : null}
      </section>
      <section className="card p-4">
        <h2 className="section-label mb-2">{t("mk.audiencia.historial")}</h2>
        {ficha.historial.length === 0 ? (
          <Vacio titulo={t("mk.audiencia.sinHistorial")} compacto />
        ) : (
          <Rejilla
            titulo={t("mk.audiencia.historial")}
            cabeceras={[
              t("mk.audiencia.cuando"),
              t("mk.audiencia.altas"),
              t("mk.audiencia.bajas"),
              t("mk.audiencia.enSegmento"),
              t("mk.audiencia.sinConsentimiento"),
              t("mk.audiencia.suprimidos"),
              t("mk.audiencia.resultado"),
            ]}
          >
            {ficha.historial.map((v) => (
              <tr
                key={v.id}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla>{fechaHora(v.at)}</Casilla>
                <Casilla className="font-mono">{v.altas}</Casilla>
                <Casilla className="font-mono">{v.bajas}</Casilla>
                <Casilla className="font-mono">{v.en_el_segmento}</Casilla>
                <Casilla className="font-mono">{v.sin_consentimiento}</Casilla>
                <Casilla className="font-mono">{v.suprimidos}</Casilla>
                <Casilla className="max-w-[24rem] text-rotulo">
                  <span
                    className={cn(
                      "chip-dato mr-1",
                      v.ok ? "chip-dato--si" : "chip-dato--mal",
                    )}
                  >
                    {v.ok ? t("mk.audiencia.ok") : t("mk.audiencia.fallo")}
                  </span>
                  {v.error ?? v.porque}
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        )}
      </section>
    </>
  );
}
