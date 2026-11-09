/**
 * Un recorrido de marketing: el lienzo, la prueba A/B con su ganador, quién
 * está dentro y qué se le ha programado (CRM-02.02.02.01, CRM-02.02.02.04,
 * CRM-02.02.02.05, CRM-02.02.02.09).
 *
 * **El lienzo genera los nodos.** Hasta el 09-11-2026 un recorrido se escribía
 * en JSON: tipo, `siguiente`, `rutas`, `variantes` y pesos a mano. Aquí se
 * añaden nodos por tipo, cada uno con sus campos —la plantilla de una acción,
 * los días de una espera, el comportamiento y las dos ramas de una decisión, las
 * variantes y sus pesos de una prueba—, sus salidas se eligen de un desplegable
 * y el diagrama se dibuja con el MISMO componente que el editor de procesos
 * (`Diagrama` y `grafo.ts`), con las posiciones guardadas dentro de cada nodo.
 *
 * **La prueba A/B enseña su resultado y su ganador.** Con la muestra mínima y
 * la significación —los dos, ajustes— la variante ganadora se aplica sola y el
 * tráfico nuevo va a ella; el panel dice la p, el mínimo y a dónde está yendo
 * la gente.
 *
 * **Por cuenta (ABM).** Con el interruptor puesto, la segunda persona de la
 * misma empresa no entra: el panel de inscribir lo dice con su motivo.
 *
 * Verificado pulsando el 09-11-2026: crear un recorrido desde «Nuevo», añadir
 * nodos en el lienzo, guardar, publicar, inscribir a dos contactos de la misma
 * cuenta con el recorrido por cuenta (el segundo sale «cuenta ya dentro»),
 * avanzar y ver el envío programado a su hora.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { Diagrama } from "@/componentes/Diagrama";
import { EnviosProgramados } from "@/componentes/EnviosDeMarketing";
import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { colocar, type Definicion, type Nodo, type Paso } from "@/lib/grafo";
import { cn } from "@/lib/utiles";

interface Variante {
  clave: string;
  peso: number;
  siguiente?: string;
}

interface NodoRecorrido {
  tipo: string;
  siguiente?: string;
  accion?: string;
  plantilla?: string;
  momento?: string;
  dias?: number;
  comportamiento?: string;
  espera_dias?: number;
  rutas?: Record<string, string>;
  variantes?: Variante[];
  ganadora?: string;
  pos?: { x: number; y: number };
  [clave: string]: unknown;
}

interface Ficha {
  id: string;
  clave: string;
  nombre: string;
  nodos: Record<string, NodoRecorrido>;
  inicio: string;
  por_cuenta: boolean;
  estado: string;
  version: number;
  inscritos: Record<string, number>;
  tipos: string[];
  comportamientos: string[];
}

const TIPOS = ["accion", "espera", "decision", "prueba", "fin"] as const;

/** El recorrido leído como una definición de `grafo.ts`: mismo dibujo que procesos. */
function comoDefinicion(
  nodos: Record<string, NodoRecorrido>,
  inicio: string,
): Definicion {
  const pasos: Record<string, Paso> = {};
  const posiciones: Record<string, { x: number; y: number }> = {};
  for (const [nombre, n] of Object.entries(nodos)) {
    const rutas: Record<string, string> = { ...(n.rutas ?? {}) };
    for (const v of n.variantes ?? []) {
      if (v.siguiente) rutas[`${v.clave} ${v.peso}%`] = v.siguiente;
    }
    pasos[nombre] = { tipo: n.tipo, siguiente: n.siguiente, rutas };
    if (n.pos) posiciones[nombre] = n.pos;
  }
  return { inicio, pasos, grafico: { posiciones } };
}

export function RecorridoDeMarketing() {
  const { id = "" } = useParams();
  if (id === "nuevo") return <AltaDeRecorrido />;
  return <FichaDeRecorrido id={id} />;
}

function AltaDeRecorrido() {
  const { t } = useTranslation();
  const navegar = useNavigate();
  const [clave, setClave] = useState("");
  const [nombre, setNombre] = useState("");
  const [porCuenta, setPorCuenta] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  async function crear() {
    try {
      const r = await llamar<{ id: string }>("/api/v1/recorridos", {
        metodo: "POST",
        cuerpo: {
          clave,
          nombre,
          por_cuenta: porCuenta,
          inicio: "inicio",
          // El esqueleto mínimo: una acción y un final. Lo demás se dibuja.
          nodos: {
            inicio: {
              tipo: "accion",
              accion: "email",
              siguiente: "fin",
              pos: { x: 40, y: 40 },
            },
            fin: { tipo: "fin", pos: { x: 260, y: 40 } },
          },
        },
      });
      navegar(`/m/campanas/recorrido/${r.datos.id}`);
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <>
      <CabeceraPagina
        titulo={t("mk.recorrido.nuevo")}
        entradilla={t("mk.recorrido.intro")}
        icono="route"
      />
      <section className="card max-w-xl p-4">
        <div className="grid gap-3">
          <label className="text-dato text-ink-muted">
            {t("mk.recorrido.clave")}
            <input
              className="input-base mt-1"
              value={clave}
              onChange={(e) => setClave(e.target.value)}
            />
          </label>
          <label className="text-dato text-ink-muted">
            {t("mk.recorrido.nombre")}
            <input
              className="input-base mt-1"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
            />
          </label>
          <label className="flex items-center gap-2 text-dato text-ink-muted">
            <input
              type="checkbox"
              checked={porCuenta}
              onChange={(e) => setPorCuenta(e.target.checked)}
            />
            {t("mk.recorrido.porCuenta")}
          </label>
          <div>
            <button
              type="button"
              className="btn-primary"
              disabled={!clave.trim() || !nombre.trim()}
              onClick={() => void crear()}
            >
              {t("mk.recorrido.crear")}
            </button>
          </div>
          {fallo ? <Fallo error={fallo} /> : null}
        </div>
      </section>
    </>
  );
}

function FichaDeRecorrido({ id }: { id: string }) {
  const { t } = useTranslation();
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [nodos, setNodos] = useState<Record<string, NodoRecorrido>>({});
  const [inicio, setInicio] = useState("");
  const [porCuenta, setPorCuenta] = useState(false);
  const [elegido, setElegido] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const [avisos, setAvisos] = useState<string[]>([]);
  const [recarga, setRecarga] = useState(0);

  const cargar = useCallback(() => {
    llamar<Ficha>(`/api/v1/recorridos/${id}/lienzo`)
      .then((r) => {
        if (!r.datos?.nodos) return;
        setFicha({
          ...r.datos,
          inscritos: r.datos.inscritos ?? {},
          comportamientos: r.datos.comportamientos ?? [],
        });
        setNodos(r.datos.nodos);
        setInicio(r.datos.inicio);
        setPorCuenta(r.datos.por_cuenta);
        setElegido((e) => e || r.datos.inicio);
      })
      .catch(setFallo);
  }, [id]);
  useEffect(cargar, [cargar]);

  const definicion = useMemo(
    () => comoDefinicion(nodos, inicio),
    [nodos, inicio],
  );
  const colocados = useMemo(() => colocar(definicion), [definicion]);

  function mover(nombre: string, dx: number, dy: number) {
    const actual = colocados.find((n) => n.nombre === nombre);
    if (!actual) return;
    cambiar(nombre, {
      pos: { x: Math.max(0, actual.x + dx), y: Math.max(0, actual.y + dy) },
    });
  }

  function cambiar(nombre: string, cambios: Partial<NodoRecorrido>) {
    setNodos((n) => ({ ...n, [nombre]: { ...n[nombre]!, ...cambios } }));
  }

  function anadir(tipo: string) {
    let i = 1;
    while (nodos[`${tipo}_${i}`]) i += 1;
    const nombre = `${tipo}_${i}`;
    const base: NodoRecorrido = { tipo };
    if (tipo === "accion") Object.assign(base, { accion: "email" });
    if (tipo === "espera") Object.assign(base, { dias: 1 });
    if (tipo === "decision")
      Object.assign(base, {
        comportamiento: "abrio",
        espera_dias: 3,
        rutas: { si: "", no: "" },
      });
    if (tipo === "prueba")
      Object.assign(base, {
        variantes: [
          { clave: "a", peso: 50, siguiente: "" },
          { clave: "b", peso: 50, siguiente: "" },
        ],
      });
    setNodos((n) => ({ ...n, [nombre]: base }));
    setElegido(nombre);
  }

  function quitar(nombre: string) {
    setNodos((n) => {
      const copia = { ...n };
      delete copia[nombre];
      return copia;
    });
    setElegido(inicio);
  }

  /** Lo que se guarda: sin salidas vacías, que el servidor leería como destino. */
  function limpio(): Record<string, NodoRecorrido> {
    const fuera: Record<string, NodoRecorrido> = {};
    for (const [nombre, n] of Object.entries(nodos)) {
      const copia: NodoRecorrido = { ...n };
      if (!copia.siguiente) delete copia.siguiente;
      if (copia.rutas)
        copia.rutas = Object.fromEntries(
          Object.entries(copia.rutas).filter(([, v]) => v),
        );
      if (copia.variantes)
        copia.variantes = copia.variantes.map((v) =>
          v.siguiente ? v : { clave: v.clave, peso: v.peso },
        );
      fuera[nombre] = copia;
    }
    return fuera;
  }

  async function guardar() {
    try {
      const posiciones = Object.fromEntries(
        colocados.map((n) => [n.nombre, { x: n.x, y: n.y }]),
      );
      const conPos = Object.fromEntries(
        Object.entries(limpio()).map(([k, v]) => [
          k,
          { ...v, pos: posiciones[k] ?? v.pos },
        ]),
      );
      const r = await llamar<{ avisos: string[]; estado: string }>(
        `/api/v1/recorridos/${id}/lienzo`,
        {
          metodo: "PUT",
          cuerpo: { nodos: conPos, inicio, por_cuenta: porCuenta },
        },
      );
      setAvisos(r.datos.avisos);
      setAviso(t("mk.recorrido.guardado"));
      setFallo(null);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function publicar() {
    try {
      const r = await llamar<{ version: number; avisos: string[] }>(
        `/api/v1/recorridos/${id}/publicar`,
        { metodo: "POST", cuerpo: {} },
      );
      setAvisos(r.datos.avisos);
      setAviso(t("mk.recorrido.publicado", { version: r.datos.version }));
      setFallo(null);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !ficha) return <Fallo error={fallo} />;
  if (!ficha) return <Cargando />;
  const nombres = Object.keys(nodos);
  const nodo = nodos[elegido];
  const pruebas = nombres.filter((n) => nodos[n]?.tipo === "prueba");

  return (
    <>
      <CabeceraPagina
        titulo={ficha.nombre}
        entradilla={t("mk.recorrido.intro")}
        icono="route"
        acciones={
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void guardar()}
            >
              {t("mk.recorrido.guardar")}
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => void publicar()}
            >
              {t("mk.recorrido.publicar")}
            </button>
          </div>
        }
      />
      <div role="status" className="mb-3">
        <p className="text-dato text-ink-muted">
          <span
            className={cn(
              "chip-dato mr-2",
              ficha.estado === "publicado" && "chip-dato--si",
            )}
          >
            {t(`mk.recorrido.estados.${ficha.estado}`, {
              defaultValue: ficha.estado,
            })}
          </span>
          {t("mk.recorrido.version", { version: ficha.version })} ·{" "}
          {t("mk.recorrido.dentro", {
            cuantos:
              (ficha.inscritos.activo ?? 0) + (ficha.inscritos.esperando ?? 0),
          })}
        </p>
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
        {avisos.map((a) => (
          <p key={a} className="text-rotulo text-warning">
            {a}
          </p>
        ))}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}

      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <section className="card p-4 lg:col-span-2">
          <h2 className="section-label mb-1">{t("mk.recorrido.lienzo")}</h2>
          <p className="mb-2 text-rotulo text-ink-faint">
            {t("mk.recorrido.lienzoAyuda")}
          </p>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="text-dato text-ink-muted">
              {t("mk.recorrido.anadir")}
            </span>
            {TIPOS.map((tipo) => (
              <button
                key={tipo}
                type="button"
                className="btn-secondary"
                onClick={() => anadir(tipo)}
              >
                {t(`mk.recorrido.tipos.${tipo}`)}
              </button>
            ))}
          </div>
          <div className="overflow-auto rounded-xl border border-ink-dim/60 bg-paper">
            <Diagrama
              definicion={definicion}
              nodos={colocados}
              rotulo={t("mk.recorrido.lienzo")}
              conEtiquetas
              pinta={(n: Nodo) => ({
                trazo:
                  n.nombre === elegido
                    ? "rgb(var(--accent))"
                    : n.esInicio
                      ? "rgb(var(--success))"
                      : "rgb(var(--ink-dim))",
                grosor: n.nombre === elegido || n.esInicio ? 2 : 1,
                lineas: [
                  n.nombre,
                  t(`mk.recorrido.tipos.${n.tipo}`, { defaultValue: n.tipo }),
                  ...(nodos[n.nombre]?.ganadora
                    ? [
                        t("mk.recorrido.ganadoraCorta", {
                          clave: nodos[n.nombre]!.ganadora,
                        }),
                      ]
                    : []),
                ],
              })}
            />
          </div>
          {/* Mover con el teclado, como en el editor de procesos. */}
          <div className="mt-2 flex flex-wrap gap-1">
            {colocados.map((n) => (
              <div
                key={n.nombre}
                className="flex items-center gap-1 text-rotulo text-ink-faint"
              >
                <button
                  type="button"
                  className={cn(
                    "chip-dato",
                    n.nombre === elegido && "chip-dato--si",
                  )}
                  onClick={() => setElegido(n.nombre)}
                >
                  {n.nombre}
                </button>
                {(
                  [
                    ["←", -40, 0],
                    ["→", 40, 0],
                    ["↑", 0, -30],
                    ["↓", 0, 30],
                  ] as const
                ).map(([signo, dx, dy]) => (
                  <button
                    key={signo}
                    type="button"
                    aria-label={`${t("mk.recorrido.mover")} ${n.nombre} ${signo}`}
                    onClick={() => mover(n.nombre, dx, dy)}
                    className="rounded border border-ink-dim/40 px-1 hover:bg-paper-light"
                  >
                    {signo}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </section>

        <section className="card p-4">
          <h2 className="section-label mb-2">{t("mk.recorrido.nodo")}</h2>
          <label className="mb-2 flex items-center gap-2 text-dato text-ink-muted">
            <input
              type="checkbox"
              checked={porCuenta}
              onChange={(e) => setPorCuenta(e.target.checked)}
            />
            {t("mk.recorrido.porCuenta")}
          </label>
          <label className="mb-3 block text-dato text-ink-muted">
            {t("mk.recorrido.inicio")}
            <select
              className="input-base mt-1"
              value={inicio}
              onChange={(e) => setInicio(e.target.value)}
            >
              {nombres.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          {nodo ? (
            <EditorDeNodo
              nombre={elegido}
              nodo={nodo}
              otros={nombres.filter((n) => n !== elegido)}
              comportamientos={ficha.comportamientos}
              alCambiar={(c) => cambiar(elegido, c)}
              alQuitar={() => quitar(elegido)}
            />
          ) : (
            <Vacio titulo={t("mk.recorrido.eligeNodo")} compacto />
          )}
        </section>
      </div>

      {pruebas.map((p) => (
        <ResultadoDePrueba
          key={p}
          recorridoId={id}
          nodo={p}
          recarga={recarga}
        />
      ))}

      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Inscribir
          recorridoId={id}
          porCuenta={ficha.por_cuenta}
          alCambiar={() => {
            setRecarga((n) => n + 1);
            cargar();
          }}
        />
        <Inscritos recorridoId={id} recarga={recarga} />
      </div>
      <EnviosProgramados origen="recorrido" origenId={id} recarga={recarga} />
    </>
  );
}

function EditorDeNodo({
  nombre,
  nodo,
  otros,
  comportamientos,
  alCambiar,
  alQuitar,
}: {
  nombre: string;
  nodo: NodoRecorrido;
  otros: string[];
  comportamientos: string[];
  alCambiar: (c: Partial<NodoRecorrido>) => void;
  alQuitar: () => void;
}) {
  const { t } = useTranslation();
  const [plantillas, setPlantillas] = useState<
    { clave: string; nombre: string }[]
  >([]);
  useEffect(() => {
    llamar<{ clave: string; nombre: string }[]>("/api/v1/correo/plantillas")
      .then((r) => setPlantillas(Array.isArray(r.datos) ? r.datos : []))
      .catch(() => setPlantillas([]));
  }, []);

  const destino = (
    valor: string | undefined,
    alElegir: (v: string) => void,
    rotulo: string,
  ) => (
    <label className="mt-2 block text-dato text-ink-muted">
      {rotulo}
      <select
        className="input-base mt-1"
        value={valor ?? ""}
        onChange={(e) => alElegir(e.target.value)}
      >
        <option value="">{t("mk.recorrido.ninguno")}</option>
        {otros.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div>
      <p className="text-dato text-ink">
        <span className="font-mono">{nombre}</span> ·{" "}
        {t(`mk.recorrido.tipos.${nodo.tipo}`, { defaultValue: nodo.tipo })}
      </p>
      {nodo.tipo === "accion" ? (
        <>
          <label className="mt-2 block text-dato text-ink-muted">
            {t("mk.recorrido.plantilla")}
            <select
              className="input-base mt-1"
              value={nodo.plantilla ?? ""}
              onChange={(e) => alCambiar({ plantilla: e.target.value })}
            >
              <option value="">{t("mk.recorrido.sinPlantilla")}</option>
              {plantillas.map((p) => (
                <option key={p.clave} value={p.clave}>
                  {p.nombre}
                </option>
              ))}
            </select>
          </label>
          <label className="mt-2 block text-dato text-ink-muted">
            {t("mk.recorrido.momento")}
            <select
              className="input-base mt-1"
              value={nodo.momento ?? "mejor"}
              onChange={(e) => alCambiar({ momento: e.target.value })}
            >
              <option value="mejor">{t("mk.recorrido.mejorHora")}</option>
              <option value="inmediato">{t("mk.recorrido.inmediato")}</option>
            </select>
          </label>
          {destino(
            nodo.siguiente,
            (v) => alCambiar({ siguiente: v }),
            t("mk.recorrido.siguiente"),
          )}
        </>
      ) : null}
      {nodo.tipo === "espera" ? (
        <>
          <label className="mt-2 block text-dato text-ink-muted">
            {t("mk.recorrido.dias")}
            <input
              type="number"
              min={1}
              className="input-base mt-1 w-24"
              value={nodo.dias ?? 1}
              onChange={(e) => alCambiar({ dias: Number(e.target.value) })}
            />
          </label>
          {destino(
            nodo.siguiente,
            (v) => alCambiar({ siguiente: v }),
            t("mk.recorrido.siguiente"),
          )}
        </>
      ) : null}
      {nodo.tipo === "decision" ? (
        <>
          <label className="mt-2 block text-dato text-ink-muted">
            {t("mk.recorrido.comportamiento")}
            <select
              className="input-base mt-1"
              value={nodo.comportamiento ?? ""}
              onChange={(e) => alCambiar({ comportamiento: e.target.value })}
            >
              {comportamientos.map((c) => (
                <option key={c} value={c}>
                  {t(`mk.recorrido.comportamientos.${c}`, { defaultValue: c })}
                </option>
              ))}
            </select>
          </label>
          <label className="mt-2 block text-dato text-ink-muted">
            {t("mk.recorrido.esperaDias")}
            <input
              type="number"
              min={1}
              className="input-base mt-1 w-24"
              value={nodo.espera_dias ?? 3}
              onChange={(e) =>
                alCambiar({ espera_dias: Number(e.target.value) })
              }
            />
          </label>
          {destino(
            nodo.rutas?.si,
            (v) => alCambiar({ rutas: { ...nodo.rutas, si: v } }),
            t("mk.recorrido.siSi"),
          )}
          {destino(
            nodo.rutas?.no,
            (v) => alCambiar({ rutas: { ...nodo.rutas, no: v } }),
            t("mk.recorrido.siNo"),
          )}
        </>
      ) : null}
      {nodo.tipo === "prueba" ? (
        <>
          {(nodo.variantes ?? []).map((v, i) => (
            <div
              key={i}
              className="mt-2 rounded-lg border border-ink-dim/40 p-2"
            >
              <div className="flex items-center gap-2">
                <input
                  className="input-base w-20"
                  aria-label={t("mk.recorrido.variante")}
                  value={v.clave}
                  onChange={(e) =>
                    alCambiar({
                      variantes: (nodo.variantes ?? []).map((x, j) =>
                        j === i ? { ...x, clave: e.target.value } : x,
                      ),
                    })
                  }
                />
                <input
                  type="number"
                  min={0}
                  max={100}
                  className="input-base w-20"
                  aria-label={t("mk.recorrido.peso")}
                  value={v.peso}
                  onChange={(e) =>
                    alCambiar({
                      variantes: (nodo.variantes ?? []).map((x, j) =>
                        j === i ? { ...x, peso: Number(e.target.value) } : x,
                      ),
                    })
                  }
                />
                <span className="text-rotulo text-ink-faint">%</span>
              </div>
              {destino(
                v.siguiente,
                (d) =>
                  alCambiar({
                    variantes: (nodo.variantes ?? []).map((x, j) =>
                      j === i ? { ...x, siguiente: d } : x,
                    ),
                  }),
                t("mk.recorrido.siguiente"),
              )}
            </div>
          ))}
          <button
            type="button"
            className="btn-link mt-2"
            onClick={() =>
              alCambiar({
                variantes: [
                  ...(nodo.variantes ?? []),
                  {
                    clave: String.fromCharCode(
                      97 + (nodo.variantes ?? []).length,
                    ),
                    peso: 0,
                  },
                ],
              })
            }
          >
            {t("mk.recorrido.otraVariante")}
          </button>
          <label className="mt-2 flex items-center gap-2 text-dato text-ink-muted">
            <input
              type="checkbox"
              checked={nodo.auto_ganador !== false}
              onChange={(e) => alCambiar({ auto_ganador: e.target.checked })}
            />
            {t("mk.recorrido.autoGanador")}
          </label>
        </>
      ) : null}
      <button type="button" className="btn-danger mt-3" onClick={alQuitar}>
        {t("mk.recorrido.quitar")}
      </button>
    </div>
  );
}

interface Prueba {
  variantes: {
    clave: string;
    personas: number;
    conversiones: number;
    tasa: number;
  }[];
  ganadora: string | null;
  concluyente: boolean;
  significativa: boolean;
  p_valor: number;
  alfa: number;
  minimo: number;
  ganadora_aplicada: string | null;
  aviso: string;
}

function ResultadoDePrueba({
  recorridoId,
  nodo,
  recarga,
}: {
  recorridoId: string;
  nodo: string;
  recarga: number;
}) {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Prueba | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  useEffect(() => {
    llamar<Prueba>(
      `/api/v1/recorridos/${recorridoId}/prueba/${encodeURIComponent(nodo)}`,
    )
      .then((r) => setDatos(Array.isArray(r.datos?.variantes) ? r.datos : null))
      .catch(setFallo);
  }, [recorridoId, nodo, recarga]);
  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">
        {t("mk.recorrido.prueba", { nodo })}
      </h2>
      {fallo ? <Fallo error={fallo} /> : null}
      {datos ? (
        <div role="status">
          <p className="text-dato text-ink">
            {datos.ganadora_aplicada
              ? t("mk.recorrido.yendoA", { clave: datos.ganadora_aplicada })
              : datos.ganadora
                ? t("mk.recorrido.ganadora", { clave: datos.ganadora })
                : t("mk.recorrido.sinGanadora")}
          </p>
          <p className="mb-2 text-rotulo text-ink-faint">
            {t("mk.recorrido.criterio", {
              minimo: datos.minimo,
              alfa: datos.alfa,
              p: datos.p_valor,
            })}{" "}
            {datos.aviso}
          </p>
          {datos.variantes.length ? (
            <Rejilla
              titulo={t("mk.recorrido.prueba", { nodo })}
              compacta
              cabeceras={[
                t("mk.recorrido.variante"),
                t("mk.recorrido.personas"),
                t("mk.recorrido.conversiones"),
                t("mk.recorrido.tasa"),
              ]}
            >
              {datos.variantes.map((v) => (
                <tr
                  key={v.clave}
                  className="border-b border-ink-dim/30 last:border-0"
                >
                  <Casilla>
                    <span
                      className={cn(
                        "chip-dato",
                        v.clave ===
                          (datos.ganadora_aplicada ?? datos.ganadora) &&
                          "chip-dato--si",
                      )}
                    >
                      {v.clave}
                    </span>
                  </Casilla>
                  <Casilla className="font-mono">{v.personas}</Casilla>
                  <Casilla className="font-mono">{v.conversiones}</Casilla>
                  <Casilla className="font-mono">{v.tasa} %</Casilla>
                </tr>
              ))}
            </Rejilla>
          ) : (
            <p className="text-rotulo text-ink-faint">
              {t("mk.recorrido.sinDatosPrueba")}
            </p>
          )}
        </div>
      ) : null}
    </section>
  );
}

interface Contacto {
  id: string;
  nombre_completo?: string;
  email?: string | null;
}

function Inscribir({
  recorridoId,
  porCuenta,
  alCambiar,
}: {
  recorridoId: string;
  porCuenta: boolean;
  alCambiar: () => void;
}) {
  const { t } = useTranslation();
  const [buscar, setBuscar] = useState("");
  const [contactos, setContactos] = useState<Contacto[]>([]);
  const [contacto, setContacto] = useState("");
  const [resultado, setResultado] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<{ items?: Contacto[] }>(
      `/api/v1/contacts?limite=20&buscar=${encodeURIComponent(buscar)}`,
      { signal: control.signal },
    )
      .then((r) => setContactos(r.datos?.items ?? []))
      .catch(() => undefined);
    return () => control.abort();
  }, [buscar]);

  async function entrar() {
    try {
      const r = await llamar<{ entro: boolean; motivo?: string }>(
        `/api/v1/recorridos/${recorridoId}/entrar`,
        { metodo: "POST", cuerpo: { objeto_id: contacto } },
      );
      setResultado(
        r.datos.entro
          ? t("mk.recorrido.entro")
          : t("mk.recorrido.noEntro", {
              motivo: t(`mk.recorrido.motivos.${r.datos.motivo}`, {
                defaultValue: r.datos.motivo ?? "",
              }),
            }),
      );
      setFallo(null);
      alCambiar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function avanzar() {
    try {
      const r = await llamar<{ movidos: unknown[]; omitidos: unknown[] }>(
        "/api/v1/recorridos/avanzar",
        { metodo: "POST", cuerpo: {} },
      );
      setResultado(
        t("mk.recorrido.avanzados", {
          movidos: r.datos.movidos.length,
          omitidos: r.datos.omitidos.length,
        }),
      );
      alCambiar();
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("mk.recorrido.inscribir")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {porCuenta
          ? t("mk.recorrido.inscribirPorCuenta")
          : t("mk.recorrido.inscribirAyuda")}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          className="input-base w-48"
          value={buscar}
          placeholder={t("mk.vista.buscarContacto")}
          aria-label={t("mk.vista.buscarContacto")}
          onChange={(e) => setBuscar(e.target.value)}
        />
        <select
          className="input-base w-auto"
          aria-label={t("mk.vista.contacto")}
          value={contacto}
          onChange={(e) => setContacto(e.target.value)}
        >
          <option value="">—</option>
          {contactos.map((c) => (
            <option key={c.id} value={c.id}>
              {c.nombre_completo} {c.email ? `· ${c.email}` : ""}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn-primary"
          disabled={!contacto}
          onClick={() => void entrar()}
        >
          {t("mk.recorrido.meter")}
        </button>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => void avanzar()}
        >
          {t("mk.recorrido.avanzar")}
        </button>
      </div>
      <div role="status">
        {resultado ? (
          <p className="mt-2 text-dato text-ink">{resultado}</p>
        ) : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}

interface Inscrito {
  id: string;
  objeto_id: string;
  cuenta_id: string | null;
  nodo_actual: string;
  estado: string;
  variantes: Record<string, string>;
  entro_at: string;
  motivo_salida: string | null;
}

function Inscritos({
  recorridoId,
  recarga,
}: {
  recorridoId: string;
  recarga: number;
}) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Inscrito[]>([]);
  useEffect(() => {
    llamar<Inscrito[]>(`/api/v1/recorridos/${recorridoId}/inscritos`)
      .then((r) => setFilas(Array.isArray(r.datos) ? r.datos : []))
      .catch(() => setFilas([]));
  }, [recorridoId, recarga]);
  return (
    <section className="card p-4">
      <h2 className="section-label mb-2">{t("mk.recorrido.inscritos")}</h2>
      {filas.length === 0 ? (
        <Vacio titulo={t("mk.recorrido.nadie")} compacto />
      ) : (
        <Rejilla
          titulo={t("mk.recorrido.inscritos")}
          compacta
          cabeceras={[
            t("mk.envios.persona"),
            t("mk.recorrido.cuenta"),
            t("mk.recorrido.nodo"),
            t("mk.envios.estado"),
            t("mk.recorrido.entroEl"),
          ]}
        >
          {filas.map((f) => (
            <tr key={f.id} className="border-b border-ink-dim/30 last:border-0">
              <Casilla className="font-mono text-rotulo">
                {f.objeto_id.slice(0, 8)}
              </Casilla>
              <Casilla className="font-mono text-rotulo">
                {f.cuenta_id ? f.cuenta_id.slice(0, 8) : "—"}
              </Casilla>
              <Casilla>
                {f.nodo_actual}
                {Object.entries(f.variantes).map(([n, v]) => (
                  <span key={n} className="chip-dato ml-1">
                    {n}: {v}
                  </span>
                ))}
              </Casilla>
              <Casilla>
                {t(`mk.recorrido.estadosInscrito.${f.estado}`, {
                  defaultValue: f.estado,
                })}
                {f.motivo_salida ? ` · ${f.motivo_salida}` : ""}
              </Casilla>
              <Casilla className="text-rotulo">{fechaHora(f.entro_at)}</Casilla>
            </tr>
          ))}
        </Rejilla>
      )}
    </section>
  );
}
