/**
 * Modelos predictivos entrenados con el histórico del CRM
 * (CRM-02.01.02.02, CRM-05.02.01.02, CRM-05.02.01.03, CRM-02.01.01.08).
 *
 * Antes «entrenar» era teclear pesos en un formulario genérico de «Gobierno de
 * la IA». Aquí se entrena de verdad: el servidor lee el histórico del CRM, mide
 * contra el periodo más reciente que el modelo no ha visto y **no publica lo
 * que no supera el mínimo** —y lo dice, con el número—. Se ve cada versión con
 * sus métricas, se programa el reentreno y se crea un segmento en marketing
 * con los mejor puntuados.
 *
 * Verificado en el navegador el 09-11-2026 contra el tenant de la plataforma:
 * propensión publicada (AUC 0,64 en 107 casos apartados), cierre, importe y
 * fecha entrenados y NO publicados por no llegar al mínimo, y leads y
 * siguiente oferta sin datos bastantes, dicho así en cada tarjeta.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { useFocoDeConfirmacion } from "@/lib/foco";
import { cifra, fechaHora } from "@/lib/formato";
import { usePuedeOperar } from "@/lib/permisos";
import { cn } from "@/lib/utiles";

interface Version {
  id: string;
  tipo: string;
  version: number;
  estado: string;
  origen: string;
  metricas: Record<string, number | null>;
  ejemplos: number;
  ventana: string;
  entrenado_at: string | null;
  notas: string;
}

interface Programacion {
  tipo: string;
  activa: boolean;
  cada_dias: number;
  ultima_at: string | null;
  proxima_at: string | null;
  ultimo_resultado: string;
}

interface Resultado {
  tipo: string;
  entrenado: boolean;
  publicado: boolean;
  version?: number;
  porque: string[];
  metricas?: Record<string, number | null>;
  casos: number;
  entreno?: number;
  validacion?: number;
  corte?: string | null;
  avisos?: string[];
  leidos?: Record<string, number | boolean>;
}

/** Lo que contesta `POST /ia/modelos/{tipo}/versiones/{version}/activar`. */
interface Activacion {
  tipo: string;
  version: number;
  comparacion: {
    habia_anterior: boolean;
    metrica?: string;
    anterior?: number;
    nueva?: number;
    mejora?: boolean;
    /** Vacío si mejora; si no, la frase del servidor que lo dice. */
    aviso?: string;
  };
}

const rutaDeActivar = (tipo: string, version: number) =>
  `/api/v1/ia/modelos/${encodeURIComponent(tipo)}/versiones/${version}/activar`;

interface SegmentoCreado {
  creado: boolean;
  segmento_id?: string;
  previstos?: number;
  congelados?: number;
  candidatos: number;
  aviso?: string;
  porque?: string;
}

const TONO: Record<string, string> = {
  activa: "chip-dato--si",
  descartada: "chip-dato--mal",
  retirada: "",
  evaluada: "chip-dato--aviso",
};

/** La métrica que decide, en una línea: AUC, error medio o acierto. */
function medida(m: Record<string, number | null> | undefined): string {
  if (!m) return "";
  if (m.auc != null) return `AUC ${cifra(Number(m.auc))}`;
  if (m.mae != null)
    return `MAE ${cifra(m.mae)} · mediana ${cifra(m.mae_mediana)} · ${m.mejora_pct ?? 0} %`;
  if (m.acierto_top != null)
    return `top ${Math.round(Number(m.acierto_top) * 100)} % · popularidad ${Math.round(Number(m.acierto_popularidad ?? 0) * 100)} %`;
  return "";
}

export function ModelosPredictivos() {
  const { t } = useTranslation();
  const [versiones, setVersiones] = useState<Version[] | null>(null);
  const [tipos, setTipos] = useState<Record<string, string>>({});
  const [cadaDias, setCadaDias] = useState<number | null>(null);
  const [programas, setProgramas] = useState<Programacion[]>([]);
  const [resultados, setResultados] = useState<Record<string, Resultado>>({});
  const [entrenando, setEntrenando] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  // Activar una versión, o volver a una anterior (auditoría 13-11-2026,
  // COB-3). El servidor lo hacía —exige métricas y contesta con la
  // comparación— y ninguna pantalla llegaba: una versión nueva que puntuaba
  // peor sólo se podía retirar llamando a la API a mano.
  const puedeOperar = usePuedeOperar();
  const [aActivar, setAActivar] = useState<Version | null>(null);
  const [activada, setActivada] = useState<Activacion | null>(null);
  const avisoDeActivada = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // La fila desde la que se pidió puede haberse ido —ya no se ofrece
    // activar la que puntúa—, así que el foco va a lo que ha pasado.
    if (activada) avisoDeActivada.current?.focus();
  }, [activada]);

  const cargar = useCallback(() => {
    llamar<{
      versiones: Version[];
      entrenables: Record<string, string>;
      reentreno_dias?: number;
    }>("/api/v1/ia/predictivo/versiones")
      .then((r) => {
        setVersiones(r.datos.versiones);
        setTipos(r.datos.entrenables);
        setCadaDias(r.datos.reentreno_dias ?? null);
      })
      .catch(setFallo);
    llamar<Programacion[]>("/api/v1/ia/predictivo/programaciones")
      .then((r) => setProgramas(Array.isArray(r.datos) ? r.datos : []))
      .catch(() => setProgramas([]));
  }, []);
  useEffect(cargar, [cargar]);

  async function entrenar(tipo: string) {
    setEntrenando(tipo);
    try {
      const r = await llamar<Resultado>(
        `/api/v1/ia/predictivo/${tipo}/entrenar`,
        { metodo: "POST" },
      );
      setResultados((x) => ({ ...x, [tipo]: r.datos }));
      setFallo(null);
      cargar();
    } catch (e) {
      setFallo(e);
    } finally {
      setEntrenando("");
    }
  }

  async function programar(tipo: string, activa: boolean) {
    try {
      await llamar(`/api/v1/ia/predictivo/${tipo}/programacion`, {
        metodo: "PUT",
        cuerpo: { activa },
      });
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !versiones) return <Fallo error={fallo} reintentar={cargar} />;
  if (!versiones) return <Cargando />;

  const nombreDe = (tipo: string) =>
    t(`prediccion.tipos.${tipo}`, { defaultValue: tipo });
  const activaDe = (tipo: string) =>
    versiones.find((v) => v.tipo === tipo && v.estado === "activa");
  // Lo que se ofrece: cualquier versión que no sea la que puntúa y que ya
  // tenga métricas. Una «entrenando» no tiene con qué compararse y el
  // servidor la rechazaría.
  const activable = (v: Version) =>
    v.estado !== "activa" &&
    v.estado !== "entrenando" &&
    puedeOperar("POST", rutaDeActivar(v.tipo, v.version));
  const algunaActivable = versiones.some(activable);

  return (
    <>
      <CabeceraPagina
        icono="model_training"
        titulo={t("modelosPredictivos.titulo")}
        entradilla={t("modelosPredictivos.entradilla")}
      />
      {fallo ? <Fallo error={fallo} /> : null}

      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        {Object.entries(tipos).map(([tipo, objeto]) => {
          const activa = versiones.find(
            (v) => v.tipo === tipo && v.estado === "activa",
          );
          const ultima = versiones.find((v) => v.tipo === tipo);
          const prog = programas.find((p) => p.tipo === tipo);
          const res = resultados[tipo];
          return (
            <section key={tipo} className="card p-4">
              <div className="mb-2 flex items-baseline justify-between gap-2">
                <h2 className="section-label">
                  {t(`prediccion.tipos.${tipo}`)}
                </h2>
                <span className="text-rotulo text-ink-faint">
                  {t("modelosPredictivos.sobre", {
                    objeto: t(`modelosPredictivos.objetos.${objeto}`),
                  })}
                </span>
              </div>
              <p className="mb-2 text-rotulo text-ink-muted">
                {t(`modelosPredictivos.que.${tipo}`)}
              </p>
              <div role="status" className="flex flex-col gap-1 text-dato">
                {activa && activa.origen === "historico" ? (
                  <p className="text-ink">
                    <span className="chip-dato chip-dato--si mr-2">
                      v{activa.version}
                    </span>
                    {t("modelosPredictivos.publicada", {
                      medida: medida(activa.metricas),
                      muestras: activa.metricas.muestras ?? 0,
                    })}
                  </p>
                ) : activa ? (
                  <p className="text-ink-muted">
                    <span className="chip-dato chip-dato--aviso mr-2">
                      v{activa.version}
                    </span>
                    {t("modelosPredictivos.declarada")}
                  </p>
                ) : (
                  <p className="text-ink-muted">
                    {t("modelosPredictivos.sinPublicar")}
                  </p>
                )}
                {ultima &&
                ultima !== activa &&
                ultima.origen === "historico" ? (
                  <p className="text-rotulo text-ink-faint">
                    {t("modelosPredictivos.ultimaVersion", {
                      version: ultima.version,
                      estado: t(`modelosPredictivos.estados.${ultima.estado}`, {
                        defaultValue: ultima.estado,
                      }),
                      notas: ultima.notas,
                    })}
                  </p>
                ) : null}
                {res ? <ResultadoDeEntreno r={res} /> : null}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  className="btn-primary"
                  disabled={entrenando !== ""}
                  onClick={() => void entrenar(tipo)}
                >
                  <Icono nombre="model_training" tamano="sm" />
                  {entrenando === tipo
                    ? t("modelosPredictivos.entrenando")
                    : t("modelosPredictivos.entrenar")}
                </button>
                <label className="flex items-center gap-2 text-rotulo text-ink-muted">
                  <input
                    type="checkbox"
                    checked={Boolean(prog?.activa)}
                    onChange={(e) => void programar(tipo, e.target.checked)}
                  />
                  {t("modelosPredictivos.programar", {
                    dias: prog?.cada_dias ?? cadaDias ?? "—",
                  })}
                </label>
              </div>
              {prog?.activa ? (
                <p className="mt-1 text-rotulo text-ink-faint">
                  {t("modelosPredictivos.proxima", {
                    cuando: fechaHora(prog.proxima_at),
                  })}
                  {prog.ultimo_resultado
                    ? ` · ${t("modelosPredictivos.ultimoResultado", { texto: prog.ultimo_resultado })}`
                    : ""}
                </p>
              ) : null}
            </section>
          );
        })}
      </div>

      <SegmentoPredictivo />

      <section className="card mt-4 p-4">
        <h2 className="section-label mb-1">
          {t("modelosPredictivos.versiones")}
        </h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {t("modelosPredictivos.versionesAyuda")}
        </p>
        {activada ? (
          <div
            ref={avisoDeActivada}
            tabIndex={-1}
            role="status"
            className="mb-3 rounded-lg border border-success/40 bg-success/5 p-3 text-dato"
          >
            <p className="text-success">
              {t("modelosPredictivos.activada", {
                modelo: nombreDe(activada.tipo),
                version: activada.version,
              })}
            </p>
            {/* Activar algo peor es legítimo —a veces se prefiere un modelo
                más simple—, pero tiene que verse: el servidor lo dice y aquí
                se enseña tal cual. */}
            {activada.comparacion.aviso ? (
              <p className="mt-1 text-warning">{activada.comparacion.aviso}</p>
            ) : null}
          </div>
        ) : null}
        {aActivar ? (
          <ConfirmarActivacion
            version={aActivar}
            actual={activaDe(aActivar.tipo)}
            nombre={nombreDe(aActivar.tipo)}
            alCancelar={() => setAActivar(null)}
            alActivar={(r) => {
              setAActivar(null);
              setActivada(r);
              cargar();
            }}
          />
        ) : null}
        {versiones.length === 0 ? (
          <Vacio titulo={t("modelosPredictivos.sinVersiones")} compacto />
        ) : (
          <Rejilla
            titulo={t("modelosPredictivos.versiones")}
            cabeceras={[
              t("modelosPredictivos.col.modelo"),
              t("modelosPredictivos.col.version"),
              t("modelosPredictivos.col.estado"),
              t("modelosPredictivos.col.origen"),
              t("modelosPredictivos.col.medida"),
              t("modelosPredictivos.col.ejemplos"),
              t("modelosPredictivos.col.ventana"),
              t("modelosPredictivos.col.entrenado"),
              // La columna sólo si hay algo que hacer en ella: sin permiso,
              // una casilla vacía en cada fila no dice nada.
              ...(algunaActivable ? [t("modelosPredictivos.col.accion")] : []),
            ]}
          >
            {versiones.map((v) => (
              <tr
                key={v.id}
                className="border-b border-ink-dim/30 last:border-0"
                title={v.notas}
              >
                <Casilla>
                  {t(`prediccion.tipos.${v.tipo}`, { defaultValue: v.tipo })}
                </Casilla>
                <Casilla className="text-center">v{v.version}</Casilla>
                <Casilla>
                  <span className={cn("chip-dato", TONO[v.estado] ?? "")}>
                    {t(`modelosPredictivos.estados.${v.estado}`, {
                      defaultValue: v.estado,
                    })}
                  </span>
                </Casilla>
                <Casilla>
                  {t(`modelosPredictivos.origenes.${v.origen}`, {
                    defaultValue: v.origen,
                  })}
                </Casilla>
                <Casilla>{medida(v.metricas)}</Casilla>
                <Casilla className="text-right">{cifra(v.ejemplos)}</Casilla>
                <Casilla>{v.ventana}</Casilla>
                <Casilla>{fechaHora(v.entrenado_at)}</Casilla>
                {algunaActivable ? (
                  <Casilla>
                    {activable(v) ? (
                      <BotonDeActivar
                        version={v}
                        actual={activaDe(v.tipo)}
                        nombre={nombreDe(v.tipo)}
                        alPulsar={() => {
                          setActivada(null);
                          setAActivar(v);
                        }}
                      />
                    ) : null}
                  </Casilla>
                ) : null}
              </tr>
            ))}
          </Rejilla>
        )}
      </section>
    </>
  );
}

/**
 * «Activar» o «Volver a esta»: lo segundo cuando la versión es anterior a la
 * que puntúa, porque eso es lo que se está haciendo —deshacer un cambio— y
 * quien lo busca lo busca con esas palabras.
 */
function BotonDeActivar({
  version,
  actual,
  nombre,
  alPulsar,
}: {
  version: Version;
  actual: Version | undefined;
  nombre: string;
  alPulsar: () => void;
}) {
  const { t } = useTranslation();
  const atras = actual !== undefined && version.version < actual.version;
  return (
    <button
      type="button"
      className="btn-ghost"
      aria-label={t(
        atras
          ? "modelosPredictivos.volverAVersion"
          : "modelosPredictivos.activarVersion",
        { modelo: nombre, version: version.version },
      )}
      onClick={alPulsar}
    >
      <Icono nombre={atras ? "undo" : "play_arrow"} tamano="sm" />
      {t(atras ? "modelosPredictivos.volverAEsta" : "modelosPredictivos.activar")}
    </button>
  );
}

/**
 * La pregunta antes de cambiar el modelo que puntúa para todo el mundo, con
 * lo que se gana o se pierde a la vista: la medida de la que puntúa ahora al
 * lado de la de ésta. Y lo que la hace sospechosa —no superó el mínimo, o es
 * de pesos tecleados—, dicho antes y no después.
 */
function ConfirmarActivacion({
  version,
  actual,
  nombre,
  alCancelar,
  alActivar,
}: {
  version: Version;
  actual: Version | undefined;
  nombre: string;
  alCancelar: () => void;
  alActivar: (r: Activacion) => void;
}) {
  const { t } = useTranslation();
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const cancelar = useRef<HTMLButtonElement>(null);
  // El foco entra en «Cancelar» y vuelve al botón de la fila al cerrar
  // (auditoría 13-11-2026, UX-7).
  useFocoDeConfirmacion(cancelar);
  const titulo = t("modelosPredictivos.confirmarTitulo", {
    modelo: nombre,
    version: version.version,
  });

  async function activar() {
    setEnviando(true);
    setFallo(null);
    try {
      const r = await llamar<Activacion>(
        rutaDeActivar(version.tipo, version.version),
        { metodo: "POST" },
      );
      alActivar(r.datos);
    } catch (e) {
      // Aquí y no arriba: el motivo —«no se activa un modelo sin sus
      // métricas»— tiene que salir junto a la pregunta que lo provocó.
      setFallo(e);
      setEnviando(false);
    }
  }

  return (
    <div
      role="alertdialog"
      aria-label={titulo}
      className="mb-3 flex flex-col gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-dato"
    >
      <p className="font-medium text-ink">{titulo}</p>
      <p className="text-ink-muted">
        {actual
          ? t("modelosPredictivos.confirmarConActual", {
              actual: actual.version,
            })
          : t("modelosPredictivos.confirmarSinActual")}
      </p>
      {actual ? (
        <p className="font-mono text-rotulo text-ink">
          {t("modelosPredictivos.comparacion", {
            actual: actual.version,
            medidaActual: medida(actual.metricas) || "—",
            medida: medida(version.metricas) || "—",
          })}
        </p>
      ) : null}
      {version.estado === "descartada" ? (
        <p className="text-warning">{t("modelosPredictivos.noSuperoMinimo")}</p>
      ) : null}
      {version.origen !== "historico" ? (
        <p className="text-warning">{t("modelosPredictivos.esDeclarada")}</p>
      ) : null}
      {fallo ? <Fallo error={fallo} /> : null}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={enviando}
          onClick={() => void activar()}
        >
          {enviando
            ? t("modelosPredictivos.activando")
            : t("modelosPredictivos.siActivar", { version: version.version })}
        </button>
        <button
          ref={cancelar}
          type="button"
          className="btn-secondary"
          onClick={alCancelar}
        >
          {t("modulo.cancelar")}
        </button>
      </div>
    </div>
  );
}

function ResultadoDeEntreno({ r }: { r: Resultado }) {
  const { t } = useTranslation();
  return (
    <div
      className={cn(
        "mt-2 rounded-lg border p-3",
        r.publicado
          ? "border-success/40 bg-success/5"
          : "border-warning/40 bg-warning/5",
      )}
    >
      <p className="font-medium text-ink">
        {!r.entrenado
          ? t("modelosPredictivos.noEntrenado")
          : r.publicado
            ? t("modelosPredictivos.siPublicado", { version: r.version })
            : t("modelosPredictivos.noPublicado", { version: r.version })}
      </p>
      {r.porque.map((p) => (
        <p key={p} className="text-ink-muted">
          {p}
        </p>
      ))}
      {r.entrenado ? (
        <p className="text-rotulo text-ink-faint">
          {t("modelosPredictivos.reparto", {
            casos: r.casos,
            entreno: r.entreno,
            validacion: r.validacion,
            corte: r.corte ?? "—",
          })}
          {r.metricas ? ` · ${medida(r.metricas)}` : ""}
        </p>
      ) : (
        <p className="text-rotulo text-ink-faint">
          {t("modelosPredictivos.casos", { casos: r.casos })}
        </p>
      )}
      {(r.avisos ?? []).map((a) => (
        <p key={a} className="text-rotulo text-warning">
          {a}
        </p>
      ))}
    </div>
  );
}

function SegmentoPredictivo() {
  const { t } = useTranslation();
  const [criterio, setCriterio] = useState("propension");
  const [minimo, setMinimo] = useState("0.5");
  const [tope, setTope] = useState("");
  const [nombre, setNombre] = useState("");
  const [creado, setCreado] = useState<SegmentoCreado | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [enviando, setEnviando] = useState(false);

  async function crear() {
    setEnviando(true);
    setFallo(null);
    try {
      const r = await llamar<SegmentoCreado>("/api/v1/ia/predictivo/segmento", {
        metodo: "POST",
        cuerpo: {
          criterio,
          minimo: Number(minimo) || 0,
          tope: tope ? Number(tope) : null,
          nombre,
        },
      });
      setCreado(r.datos);
    } catch (e) {
      setFallo(e);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("modelosPredictivos.segmento")}</h2>
      <p className="mb-3 text-rotulo text-ink-faint">
        {t("modelosPredictivos.segmentoAyuda")}
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("modelosPredictivos.criterio")}
          <select
            className="input-base"
            value={criterio}
            onChange={(e) => setCriterio(e.target.value)}
          >
            {["propension", "valor_esperado", "scoring_lead"].map((c) => (
              <option key={c} value={c}>
                {t(`modelosPredictivos.criterios.${c}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("modelosPredictivos.minimo")}
          <input
            className="input-base w-32"
            type="number"
            step="any"
            min="0"
            value={minimo}
            onChange={(e) => setMinimo(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("modelosPredictivos.tope")}
          <input
            className="input-base w-24"
            type="number"
            min="1"
            value={tope}
            onChange={(e) => setTope(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("modelosPredictivos.nombre")}
          <input
            className="input-base w-64"
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="btn-primary"
          disabled={enviando}
          onClick={() => void crear()}
        >
          <Icono nombre="group_add" tamano="sm" />
          {t("modelosPredictivos.crearSegmento")}
        </button>
      </div>
      <div role="status" className="mt-3 text-dato">
        {fallo ? <Fallo error={fallo} /> : null}
        {creado && !creado.creado ? (
          <p className="text-ink-muted">{creado.porque}</p>
        ) : null}
        {creado?.creado ? (
          <>
            <p className="text-success">
              {t("modelosPredictivos.segmentoCreado", {
                previstos: creado.previstos,
                congelados: creado.congelados,
                candidatos: creado.candidatos,
              })}{" "}
              <Link
                className="text-accent hover:underline"
                to={`/m/segmentos/segmento/${creado.segmento_id}`}
              >
                {t("modelosPredictivos.abrirSegmento")}
              </Link>
            </p>
            {creado.aviso ? (
              <p className="text-warning">{creado.aviso}</p>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}
