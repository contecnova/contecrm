/**
 * Telefonía: el perfil conectado y las llamadas registradas
 * (CRM-04.02.01.05, CRM-03.03.01.05).
 *
 * Hasta el 09-11-2026 la telefonía eran funciones puras y no se había
 * registrado nunca una llamada. Aquí se conecta sobre una conexión de
 * Integraciones —originar y transferir son operaciones declaradas en ella, y
 * el aviso de la centralita se lee con el mapeo del conector— y se ve cada
 * llamada: quién llamó, cómo terminó, cuánto duró, lo que recogió el IVR, su
 * grabación y la actividad que quedó en la ficha.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import {
  AvisoDeRecorte,
  Cargando,
  Error as Fallo,
  FalloCompacto,
  Vacio,
} from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { listar } from "@/lib/listados";

interface Perfil {
  conectado: boolean;
  porque?: string;
  conexion_id?: string;
  nombre?: string;
  operaciones?: Record<string, boolean>;
  webhook?: Record<string, unknown>;
  falta?: string[];
}

interface Llamada {
  id: string;
  sentido: string;
  numero: string;
  estado: string;
  resultado: string | null;
  duracion_s: number;
  inicio_at: string | null;
  contacto_id: string | null;
  cuenta_id: string | null;
  identificacion: { nombre?: string };
  ivr: Record<string, unknown>;
  grabacion_url: string | null;
  actividad_id: string | null;
  registro_error: string | null;
  error: string | null;
  transferencias: { a: string }[];
}

const EJEMPLO = {
  mapeo: {
    id_externo: "call_id",
    evento: "event",
    numero: ["from", "caller"],
    duracion_s: "duration",
    grabacion: "recording_url",
    ivr: "ivr_data",
    agente: "agent",
  },
  transformar: {
    evento: [
      {
        f: "mapa",
        arg: { RINGING: "entrante", ANSWERED: "contestada", HANGUP: "colgada" },
      },
    ],
  },
};

export function Telefonia() {
  const { t } = useTranslation();
  const [perfil, setPerfil] = useState<Perfil | null>(null);
  const [llamadas, setLlamadas] = useState<Llamada[] | null>(null);
  // Cuántas hay en total, y si el listado no se pudo traer. Antes un fallo
  // dejaba la lista vacía, que se leía como «no hay llamadas» (COB-16).
  const [total, setTotal] = useState(0);
  const [falloLlamadas, setFalloLlamadas] = useState<unknown>(null);
  const [conexiones, setConexiones] = useState<
    { id: string; nombre: string }[]
  >([]);
  const [conexion, setConexion] = useState("");
  const [webhook, setWebhook] = useState(JSON.stringify(EJEMPLO, null, 2));
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");

  const cargar = useCallback(() => {
    llamar<Perfil>("/api/v1/telefonia/perfil")
      .then((r) => {
        setPerfil(r.datos);
        if (r.datos.conexion_id) setConexion(r.datos.conexion_id);
        if (r.datos.webhook && Object.keys(r.datos.webhook).length > 0)
          setWebhook(JSON.stringify(r.datos.webhook, null, 2));
      })
      .catch((e) => setFallo(e));
    setFalloLlamadas(null);
    llamar<{ llamadas: Llamada[]; total: number }>(
      "/api/v1/telefonia/llamadas?limite=50",
    )
      .then((r) => {
        setLlamadas(r.datos.llamadas ?? []);
        setTotal(r.datos.total ?? 0);
      })
      .catch((e: unknown) => setFalloLlamadas(e));
  }, []);
  useEffect(cargar, [cargar]);
  useEffect(() => {
    void listar<{ id: string; nombre: string }>(
      "/api/v1/integraciones/conexiones",
    )
      .then(setConexiones)
      .catch(() => setConexiones([]));
  }, []);

  async function guardar(e: FormEvent) {
    e.preventDefault();
    setFallo(null);
    setAviso("");
    let cuerpo: unknown;
    try {
      cuerpo = JSON.parse(webhook);
    } catch {
      setAviso(t("telefonia.jsonMal"));
      return;
    }
    try {
      const r = await llamar<Perfil>("/api/v1/telefonia/perfil", {
        metodo: "PUT",
        cuerpo: { conexion_id: conexion, webhook: cuerpo },
      });
      setPerfil(r.datos);
      setAviso(t("telefonia.guardado"));
    } catch (err) {
      setFallo(err);
    }
  }

  if (fallo && !perfil) return <Fallo error={fallo} reintentar={cargar} />;
  if (!perfil) return <Cargando />;

  return (
    <div>
      <CabeceraPagina
        titulo={t("telefonia.titulo")}
        entradilla={t("telefonia.entradilla")}
        icono="call"
      />

      <section className="card mb-4 p-4">
        <h2 className="section-label">{t("telefonia.perfil")}</h2>
        <p role="status" className="mt-1 text-dato text-ink">
          {perfil.conectado
            ? t("telefonia.conectada", { nombre: perfil.nombre })
            : perfil.porque}
        </p>
        {perfil.operaciones ? (
          <ul className="mt-2 flex flex-wrap gap-1">
            {Object.entries(perfil.operaciones).map(([k, v]) => (
              <li
                key={k}
                className={`chip-dato ${v ? "chip-dato--si" : "chip-dato--mal"}`}
              >
                {k}: {v ? t("telefonia.declarada") : t("telefonia.falta")}
              </li>
            ))}
          </ul>
        ) : null}
        {perfil.falta && perfil.falta.length > 0 ? (
          <p className="mt-2 text-rotulo text-danger">
            {t("telefonia.queFalta", { que: perfil.falta.join("; ") })}
          </p>
        ) : null}
        <form className="mt-3 grid gap-3" onSubmit={guardar}>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("telefonia.conexion")}
            <select
              className="input-base"
              required
              value={conexion}
              onChange={(e) => setConexion(e.target.value)}
            >
              <option value="">{t("telefonia.elige")}</option>
              {conexiones.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("telefonia.webhook")}
            <textarea
              className="input-base font-mono"
              rows={10}
              value={webhook}
              onChange={(e) => setWebhook(e.target.value)}
            />
          </label>
          <p className="text-rotulo text-ink-faint">
            {t("telefonia.ayudaWebhook")}
          </p>
          <div className="flex gap-2">
            <button type="submit" className="btn-primary" disabled={!conexion}>
              {t("telefonia.guardar")}
            </button>
          </div>
          {aviso ? (
            <p role="status" className="text-rotulo text-ink">
              {aviso}
            </p>
          ) : null}
          {fallo ? <Fallo error={fallo} /> : null}
        </form>
      </section>

      <section className="card mb-4 p-4">
        <h2 className="section-label">{t("telefonia.llamadas")}</h2>
        {falloLlamadas ? (
          <FalloCompacto
            error={falloLlamadas}
            que={t("telefonia.llamadas")}
            reintentar={cargar}
          />
        ) : !llamadas ? (
          <Cargando />
        ) : null}
        {llamadas && llamadas.length === 0 ? (
          <Vacio titulo={t("telefonia.sinLlamadas")} compacto />
        ) : null}
        {llamadas && llamadas.length > 0 ? (
          <Rejilla
            titulo={t("telefonia.llamadas")}
            cabeceras={[
              t("telefonia.cuando"),
              t("telefonia.sentido"),
              t("telefonia.quien"),
              t("telefonia.resultado"),
              t("telefonia.duracion"),
              t("telefonia.ivr"),
              t("telefonia.grabacion"),
              t("telefonia.actividad"),
            ]}
          >
            {llamadas.map((l) => (
              <tr key={l.id}>
                <Casilla enUnaLinea>
                  {l.inicio_at ? fechaHora(l.inicio_at) : ""}
                </Casilla>
                <Casilla>{t(`telefonia.sentidos.${l.sentido}`)}</Casilla>
                <Casilla>
                  {l.contacto_id ? (
                    <Link to={`/abrir/contacto/${l.contacto_id}`}>
                      {l.identificacion?.nombre ?? l.numero}
                    </Link>
                  ) : l.cuenta_id ? (
                    <Link to={`/abrir/cuenta/${l.cuenta_id}`}>
                      {l.identificacion?.nombre ?? l.numero}
                    </Link>
                  ) : (
                    l.numero
                  )}
                  {l.transferencias?.length ? (
                    <span className="block text-rotulo text-ink-muted">
                      {t("telefonia.transferida", {
                        a: l.transferencias.map((x) => x.a).join(", "),
                      })}
                    </span>
                  ) : null}
                </Casilla>
                <Casilla>
                  {l.resultado ?? l.estado}
                  {l.error ? (
                    <span className="block text-rotulo text-danger">
                      {l.error}
                    </span>
                  ) : null}
                </Casilla>
                <Casilla enUnaLinea>
                  {t("telefonia.segundos", { n: l.duracion_s })}
                </Casilla>
                <Casilla>
                  {Object.entries(l.ivr ?? {})
                    .map(([k, v]) => `${k}: ${String(v)}`)
                    .join(" · ")}
                </Casilla>
                <Casilla>
                  {l.grabacion_url ? (
                    <a
                      href={l.grabacion_url}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      {t("telefonia.escuchar")}
                    </a>
                  ) : null}
                </Casilla>
                <Casilla>
                  {l.actividad_id ? (
                    <Link to={`/abrir/actividad/${l.actividad_id}`}>
                      {t("telefonia.verActividad")}
                    </Link>
                  ) : l.registro_error ? (
                    <span className="text-rotulo text-danger">
                      {l.registro_error}
                    </span>
                  ) : (
                    <span className="text-rotulo text-ink-faint">
                      {t("telefonia.sinActividad")}
                    </span>
                  )}
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        ) : null}
        {llamadas && total > llamadas.length ? (
          <AvisoDeRecorte cuantas={llamadas.length} />
        ) : null}
      </section>
    </div>
  );
}
