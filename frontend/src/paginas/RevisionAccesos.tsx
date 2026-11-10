/**
 * Revisión periódica de accesos: lanzar campañas y ver cómo van
 * (CRM-07.03.02.15).
 *
 * Medido el 09-11-2026: no había revisión de accesos. Un rol se da con un
 * motivo y se queda para siempre, aunque el motivo deje de existir. Aquí se
 * lanza una campaña con su plazo: cada responsable recibe en su bandeja de
 * aprobaciones los accesos de su gente y confirma o retira cada uno; lo
 * retirado se quita en el momento, y lo no contestado a tiempo se marca y se
 * avisa.
 *
 * El resultado es la evidencia del control `REC-ACCESOS` del GRC, y el enlace
 * va en los dos sentidos: de aquí al control y del control aquí.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { listar } from "@/lib/listados";
import { usePuedeOperar } from "@/lib/permisos";
import { cn } from "@/lib/utiles";

interface Campana {
  id: string;
  nombre: string;
  estado: "abierta" | "cerrada";
  plazo_at: string;
  fuera_de_plazo: boolean;
  cerrada_at: string | null;
  total: number;
  confirmados: number;
  retirados: number;
  pendientes: number;
  vencidas: number;
  responsables: number;
}

interface Revision {
  id: string;
  usuario: string;
  responsable: string;
  tipo: string;
  valor: string;
  decision: string;
  comentario: string;
  vencida: boolean;
}

interface Usuario {
  id: string;
  nombre: string;
  email: string;
}

const TONO: Record<string, string> = {
  confirmado: "chip-dato--si",
  retirado: "chip-dato--mal",
  pendiente: "",
};

export function RevisionAccesos() {
  const { t } = useTranslation();
  const puede = usePuedeOperar();
  const [campanas, setCampanas] = useState<Campana[] | null>(null);
  const [ultima, setUltima] = useState<Campana | null>(null);
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [abierta, setAbierta] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const [nombre, setNombre] = useState("");
  const [plazo, setPlazo] = useState("");
  const [revisor, setRevisor] = useState("");

  const cargar = useCallback(() => {
    llamar<Campana[]>("/api/v1/recertificacion/campanas")
      .then((r) => setCampanas(Array.isArray(r.datos) ? r.datos : []))
      .catch((e) => setFallo(e));
    // Lo mismo que lee el control de accesos del GRC: la última cerrada.
    llamar<{ ultima_cerrada: Campana | null }>(
      "/api/v1/recertificacion/resumen",
    )
      .then((r) => setUltima(r.datos.ultima_cerrada ?? null))
      .catch(() => setUltima(null));
  }, []);
  useEffect(cargar, [cargar]);
  useEffect(() => {
    void listar<Usuario>("/api/v1/usuarios?limite=200")
      .then(setUsuarios)
      .catch(() => setUsuarios([]));
  }, []);

  const lanzarPermitido = puede("POST", "/api/v1/recertificacion/campanas");

  async function lanzar() {
    try {
      const r = await llamar<Campana>("/api/v1/recertificacion/campanas", {
        metodo: "POST",
        cuerpo: {
          nombre,
          plazo_dias: plazo ? Number(plazo) : null,
          revisor_por_defecto: revisor || null,
        },
      });
      setAviso(
        t("revisionAccesos.lanzada", {
          total: r.datos.total,
          responsables: r.datos.responsables,
          plazo: r.datos.plazo_at,
        }),
      );
      setNombre("");
      setFallo(null);
      setAbierta(r.datos.id);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function postear(ruta: string, texto: string) {
    try {
      await llamar(ruta, { metodo: "POST" });
      setAviso(texto);
      setFallo(null);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !campanas) return <Fallo error={fallo} reintentar={cargar} />;
  if (!campanas) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        icono="how_to_reg"
        titulo={t("revisionAccesos.titulo")}
        entradilla={t("revisionAccesos.entradilla")}
        acciones={
          <Link
            to="/controles-grc?control=REC-ACCESOS"
            className="btn-secondary"
          >
            <Icono nombre="fact_check" tamano="sm" />
            {t("revisionAccesos.control")}
          </Link>
        }
      />
      <div role="status" className="mb-3">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
        {fallo ? <Fallo error={fallo} /> : null}
      </div>
      <p className="mb-4 text-dato text-ink-muted">
        {ultima
          ? t("revisionAccesos.loQueLeeElGrc", {
              nombre: ultima.nombre,
              fecha: (ultima.cerrada_at ?? "").slice(0, 10),
              confirmados: ultima.confirmados,
              retirados: ultima.retirados,
              vencidas: ultima.vencidas,
            })
          : t("revisionAccesos.grcSinCampana")}
      </p>

      {lanzarPermitido ? (
        <section className="card mb-4 p-4">
          <h2 className="section-label mb-1">{t("revisionAccesos.nueva")}</h2>
          <p className="mb-2 text-rotulo text-ink-faint">
            {t("revisionAccesos.nuevaAyuda")}
          </p>
          <div className="grid gap-3 md:grid-cols-4">
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
              {t("revisionAccesos.nombre")}
              <input
                className="input-base"
                value={nombre}
                placeholder={t("revisionAccesos.nombreEjemplo")}
                onChange={(e) => setNombre(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("revisionAccesos.plazo")}
              <input
                type="number"
                min={1}
                max={365}
                className="input-base"
                value={plazo}
                placeholder={t("revisionAccesos.plazoDefecto")}
                onChange={(e) => setPlazo(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("revisionAccesos.revisor")}
              <select
                className="input-base"
                value={revisor}
                onChange={(e) => setRevisor(e.target.value)}
              >
                <option value="">{t("revisionAccesos.revisorYo")}</option>
                {usuarios.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.nombre || u.email}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button
            type="button"
            className="btn-primary mt-3"
            disabled={!nombre.trim()}
            onClick={() => void lanzar()}
          >
            <Icono nombre="send" tamano="sm" />
            {t("revisionAccesos.lanzar")}
          </button>
        </section>
      ) : null}

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">{t("revisionAccesos.campanas")}</h2>
        {campanas.length === 0 ? (
          <Vacio compacto titulo={t("revisionAccesos.sinCampanas")} />
        ) : (
          <Rejilla
            titulo={t("revisionAccesos.campanas")}
            cabeceras={[
              t("revisionAccesos.campana"),
              t("revisionAccesos.plazoCol"),
              t("revisionAccesos.avance"),
              t("revisionAccesos.vencidas"),
              "",
            ]}
          >
            {campanas.map((c) => (
              <tr
                key={c.id}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla className="min-w-[14rem]">
                  <button
                    type="button"
                    className="text-left text-ink hover:text-accent hover:underline"
                    onClick={() => setAbierta(abierta === c.id ? "" : c.id)}
                  >
                    {c.nombre}
                  </button>{" "}
                  <span
                    className={cn(
                      "chip-dato",
                      c.estado === "cerrada" ? "" : "chip-dato--aviso",
                    )}
                  >
                    {t(`revisionAccesos.estados.${c.estado}`)}
                  </span>
                </Casilla>
                <Casilla>
                  <span className={cn(c.fuera_de_plazo && "text-danger")}>
                    {c.plazo_at}
                  </span>
                </Casilla>
                <Casilla className="tabular-nums">
                  {t("revisionAccesos.avanceTexto", {
                    confirmados: c.confirmados,
                    retirados: c.retirados,
                    pendientes: c.pendientes,
                    responsables: c.responsables,
                  })}
                </Casilla>
                <Casilla className="text-right tabular-nums">
                  {c.vencidas ? (
                    <span className="chip-dato chip-dato--mal">
                      {c.vencidas}
                    </span>
                  ) : (
                    0
                  )}
                </Casilla>
                <Casilla className="text-right">
                  {c.estado === "abierta" && lanzarPermitido ? (
                    <span className="flex justify-end gap-2">
                      <button
                        type="button"
                        className="btn-link"
                        onClick={() =>
                          void postear(
                            "/api/v1/recertificacion/vencidas",
                            t("revisionAccesos.avisadas"),
                          )
                        }
                      >
                        {t("revisionAccesos.avisar")}
                      </button>
                      <button
                        type="button"
                        className="btn-link"
                        onClick={() =>
                          void postear(
                            `/api/v1/recertificacion/campanas/${c.id}/cerrar`,
                            t("revisionAccesos.cerrada", { nombre: c.nombre }),
                          )
                        }
                      >
                        {t("revisionAccesos.cerrar")}
                      </button>
                    </span>
                  ) : null}
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        )}
      </section>

      {abierta ? <DetalleCampana key={abierta} id={abierta} /> : null}
    </>
  );
}

function DetalleCampana({ id }: { id: string }) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Revision[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    llamar<{ revisiones: Revision[] }>(`/api/v1/recertificacion/campanas/${id}`)
      .then((r) => setFilas(r.datos.revisiones ?? []))
      .catch((e) => setFallo(e));
  }, [id]);

  if (fallo) return <Fallo error={fallo} />;
  if (!filas) return <Cargando />;
  // Por responsable: la campaña es de cada responsable, y así se ve quién
  // tiene lo suyo sin contestar.
  const porResponsable = new Map<string, Revision[]>();
  for (const f of filas)
    porResponsable.set(f.responsable, [
      ...(porResponsable.get(f.responsable) ?? []),
      f,
    ]);

  return (
    <section className="card p-4">
      <h2 className="section-label mb-2">{t("revisionAccesos.detalle")}</h2>
      <div className="flex flex-col gap-4">
        {[...porResponsable.entries()].map(([responsable, suyas]) => (
          <div key={responsable}>
            <p className="mb-1 text-dato font-medium text-ink">
              {t("revisionAccesos.responsable", {
                nombre: responsable || "—",
                n: suyas.filter((s) => s.decision === "pendiente").length,
              })}
            </p>
            <ul className="lista-acotada divide-y divide-ink-dim/30">
              {suyas.map((r) => (
                <li
                  key={r.id}
                  className="flex flex-wrap items-baseline gap-x-2 py-1.5 text-dato"
                >
                  <span className="text-ink">{r.usuario}</span>
                  <span className="chip-dato">
                    {t(`revisionAccesos.tipos.${r.tipo}`)}: {r.valor}
                  </span>
                  <span className={cn("chip-dato", TONO[r.decision] ?? "")}>
                    {t(`revisionAccesos.decisiones.${r.decision}`)}
                  </span>
                  {r.vencida ? (
                    <span className="chip-dato chip-dato--mal">
                      {t("revisionAccesos.fueraDePlazo")}
                    </span>
                  ) : null}
                  {r.comentario ? (
                    <span className="text-rotulo text-ink-faint">
                      {r.comentario}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
