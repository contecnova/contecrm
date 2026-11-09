/**
 * El editor de una tabla de decisión (CRM-00.03.02.10).
 *
 * Constaba hecho y no se podía usar: la API existía —guardar por clave,
 * validar, evaluar con explicación— y la pantalla era la ficha genérica, que
 * edita con PATCH lo que se guarda entero con PUT y pinta las reglas, que son
 * estructura, como una caja de texto. Una tabla de decisión es para que la
 * cambie negocio sin escribir código; con una caja de JSON, no la cambia nadie.
 *
 * Aquí: las columnas de entrada y de salida, una rejilla con una fila por regla
 * —una casilla por entrada y otra por salida—, y los tres botones que importan:
 * «Validar» (huecos, solapes, reglas que nunca casarán), «Probar» con unos
 * datos —sobre la tabla tal como está en pantalla, sin guardarla— y «Guardar».
 *
 * Los valores se editan como texto y se convierten AL ENVIAR, según el tipo de
 * la columna: convertir mientras se teclea rompe el «1.» de quien escribe 1,5.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { ErrorApi, llamar } from "@/lib/api";
import { cn } from "@/lib/utiles";

// ── El formato de la API (services/orchestrator/decision.py) ──────────────

const POLITICAS = [
  "primera",
  "unica",
  "prioridad",
  "cualquiera",
  "todas",
] as const;
const TIPOS = ["numero", "texto", "booleano", "lista", "fecha"] as const;
const OPERADORES = [
  "=",
  "!=",
  ">",
  ">=",
  "<",
  "<=",
  "en",
  "contiene",
  "vacio",
  "no_vacio",
];
const SIN_VALOR = new Set(["vacio", "no_vacio"]);

interface Columna {
  clave: string;
  etiqueta?: string;
  expresion?: string;
  tipo?: string | null;
}

interface ReglaApi {
  nombre?: string;
  condiciones?: { entrada: string; op?: string; valor?: unknown }[];
  salidas?: Record<string, unknown>;
  prioridad?: number | null;
}

interface TablaApi {
  clave: string;
  nombre: string;
  politica: string;
  activa: boolean;
  entradas: Columna[];
  salidas: Columna[];
  reglas: ReglaApi[];
}

interface Analisis {
  solapes: { reglas: string[]; motivo: string }[];
  inalcanzables: { regla: string; tapada_por: string; motivo: string }[];
  huecos: { entrada: string; desde: number | null; hasta: number | null }[];
  sin_red_de_seguridad: boolean;
  indecidibles: string[];
}

interface Evaluacion {
  salidas: Record<string, unknown>;
  entradas: Record<string, unknown>;
  por_defecto: boolean;
  reglas: {
    indice: number;
    nombre: string;
    caso: boolean;
    fallo_en?: {
      entrada: string;
      operador: string;
      esperado: unknown;
      encontrado: unknown;
    };
    salidas?: Record<string, unknown>;
  }[];
}

// ── El modelo de la pantalla ──────────────────────────────────────────────

interface CondicionUI {
  op: string;
  valor: string;
}

interface ReglaUI {
  id: string;
  nombre: string;
  prioridad: string;
  condiciones: Record<string, CondicionUI[]>;
  salidas: Record<string, string>;
}

let contador = 0;
const nuevoId = () => `r${++contador}`;

function aTexto(valor: unknown): string {
  if (valor === null || valor === undefined) return "";
  if (Array.isArray(valor)) return valor.map(aTexto).join(", ");
  return String(valor);
}

/** De texto al valor que espera la API, según el tipo de la columna. */
export function aValor(texto: string, tipo?: string | null): unknown {
  const t = texto.trim();
  if (t.startsWith("@")) return t; // referencia a otra variable del contexto
  if (tipo === "booleano") return t === "true" || t === "sí" || t === "si";
  if (tipo === "lista") return t ? t.split(",").map((x) => x.trim()) : [];
  const esNumero = /^-?\d+([.,]\d+)?$/.test(t);
  if (tipo === "numero" || (!tipo && esNumero)) {
    const n = Number(t.replace(",", "."));
    return Number.isNaN(n) ? t : n;
  }
  return t;
}

function reglaDesdeApi(r: ReglaApi): ReglaUI {
  const condiciones: Record<string, CondicionUI[]> = {};
  for (const c of r.condiciones ?? []) {
    (condiciones[c.entrada] ??= []).push({
      op: c.op ?? "=",
      valor: aTexto(c.valor),
    });
  }
  const salidas: Record<string, string> = {};
  for (const [k, v] of Object.entries(r.salidas ?? {})) salidas[k] = aTexto(v);
  return {
    id: nuevoId(),
    nombre: r.nombre ?? "",
    prioridad:
      r.prioridad === null || r.prioridad === undefined
        ? ""
        : String(r.prioridad),
    condiciones,
    salidas,
  };
}

/** La tabla de la pantalla, en la forma de la API. */
export function aTablaApi(
  base: { nombre: string; politica: string; activa: boolean },
  entradas: Columna[],
  salidas: Columna[],
  reglas: ReglaUI[],
): Omit<TablaApi, "clave"> {
  const tipoDe = (cols: Columna[], clave: string) =>
    cols.find((c) => c.clave === clave)?.tipo ?? null;
  return {
    nombre: base.nombre,
    politica: base.politica,
    activa: base.activa,
    entradas: entradas.map((c) => ({ ...c, tipo: c.tipo || null })),
    salidas: salidas.map((c) => ({ ...c, tipo: c.tipo || null })),
    reglas: reglas.map((r) => {
      const regla: ReglaApi = {
        nombre: r.nombre,
        condiciones: entradas.flatMap((e) =>
          (r.condiciones[e.clave] ?? []).map((c) => ({
            entrada: e.clave,
            op: c.op,
            valor: SIN_VALOR.has(c.op)
              ? null
              : c.op === "en"
                ? c.valor
                    .split(",")
                    .map((x) => aValor(x, tipoDe(entradas, e.clave)))
                    .filter((x) => x !== "")
                : aValor(c.valor, tipoDe(entradas, e.clave)),
          })),
        ),
        salidas: Object.fromEntries(
          salidas
            .filter((s) => (r.salidas[s.clave] ?? "").trim() !== "")
            .map((s) => [s.clave, aValor(r.salidas[s.clave] ?? "", s.tipo)]),
        ),
      };
      if (r.prioridad.trim() !== "") regla.prioridad = Number(r.prioridad);
      return regla;
    }),
  };
}

/** Pone un valor en `variables` siguiendo la expresión `@a.b.c` de la columna. */
function ponerEn(
  variables: Record<string, unknown>,
  expresion: string,
  valor: unknown,
) {
  if (!expresion.startsWith("@")) return;
  const partes = expresion.slice(1).split(".");
  let actual = variables;
  partes.forEach((parte, i) => {
    if (i === partes.length - 1) actual[parte] = valor;
    else {
      if (typeof actual[parte] !== "object" || actual[parte] === null)
        actual[parte] = {};
      actual = actual[parte] as Record<string, unknown>;
    }
  });
}

function aClave(texto: string): string {
  return (
    texto
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 60) || ""
  );
}

/** Mientras se teclea: sólo lo que admite una clave, sin recortar los bordes
 * (recortarlos impediría escribir `descuento_pct`, que pasa por `descuento_`). */
function limpiarClave(texto: string): string {
  return texto
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9_]+/g, "_")
    .slice(0, 120);
}

const VOLVER = `/m/procesos?r=${encodeURIComponent("Tablas de decisión")}`;

// ── La pantalla ───────────────────────────────────────────────────────────

export function TablaDeDecision() {
  const { t } = useTranslation();
  const { clave: claveRuta } = useParams();
  const navegar = useNavigate();
  const nueva = !claveRuta;

  const [cargada, setCargada] = useState(nueva);
  const [fallo, setFallo] = useState<unknown>(null);
  const [clave, setClave] = useState(claveRuta ?? "");
  const [nombre, setNombre] = useState("");
  const [politica, setPolitica] = useState<string>("primera");
  const [activa, setActiva] = useState(true);
  const [entradas, setEntradas] = useState<Columna[]>(
    nueva
      ? [
          {
            clave: "importe",
            etiqueta: "Importe",
            expresion: "@importe",
            tipo: "numero",
          },
        ]
      : [],
  );
  const [salidas, setSalidas] = useState<Columna[]>(
    nueva ? [{ clave: "aprobador", etiqueta: "Aprobador", tipo: "texto" }] : [],
  );
  const [reglas, setReglas] = useState<ReglaUI[]>(
    nueva
      ? [
          {
            id: nuevoId(),
            nombre: "",
            prioridad: "",
            condiciones: {},
            salidas: {},
          },
        ]
      : [],
  );

  const [problemas, setProblemas] = useState<string[] | null>(null);
  const [analisis, setAnalisis] = useState<Analisis | null>(null);
  const [aviso, setAviso] = useState("");
  const [datosPrueba, setDatosPrueba] = useState<Record<string, string>>({});
  const [resultado, setResultado] = useState<Evaluacion | null>(null);
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    if (nueva) return;
    llamar<TablaApi>(
      `/api/v1/tablas-decision/${encodeURIComponent(claveRuta!)}`,
    )
      .then((r) => {
        const d = r.datos;
        setClave(d.clave);
        setNombre(d.nombre);
        setPolitica(d.politica || "primera");
        setActiva(d.activa);
        setEntradas(d.entradas ?? []);
        setSalidas(d.salidas ?? []);
        setReglas((d.reglas ?? []).map(reglaDesdeApi));
        setCargada(true);
      })
      .catch((e) => setFallo(e));
  }, [nueva, claveRuta]);

  const tabla = useMemo(
    () => aTablaApi({ nombre, politica, activa }, entradas, salidas, reglas),
    [nombre, politica, activa, entradas, salidas, reglas],
  );

  // Cualquier cambio deja viejos el análisis y la prueba: enseñarlos sobre una
  // tabla distinta de la que se ve diría cosas de otra tabla.
  useEffect(() => {
    setAnalisis(null);
    setProblemas(null);
    setResultado(null);
  }, [tabla]);

  function recogerProblemas(e: unknown): boolean {
    if (e instanceof ErrorApi) {
      const det = e.detalle as { problemas?: string[] } | null;
      if (det?.problemas?.length) {
        setProblemas(det.problemas);
        return true;
      }
    }
    return false;
  }

  async function validar() {
    setOcupado(true);
    setAviso("");
    setFallo(null);
    try {
      const r = await llamar<{
        valida: boolean;
        problemas: string[];
        analisis: Analisis | null;
      }>("/api/v1/tablas-decision/validar", { metodo: "POST", cuerpo: tabla });
      setProblemas(r.datos.problemas);
      setAnalisis(r.datos.analisis);
      setAviso(
        r.datos.valida
          ? t("tablasDecision.validada")
          : t("tablasDecision.conProblemas"),
      );
    } catch (e) {
      if (!recogerProblemas(e)) setFallo(e);
    } finally {
      setOcupado(false);
    }
  }

  async function probar() {
    setOcupado(true);
    setAviso("");
    setFallo(null);
    const variables: Record<string, unknown> = {};
    for (const e of entradas) {
      const texto = datosPrueba[e.clave] ?? "";
      if (texto.trim() === "") continue;
      ponerEn(variables, e.expresion ?? "", aValor(texto, e.tipo));
    }
    try {
      const r = await llamar<Evaluacion>("/api/v1/tablas-decision/probar", {
        metodo: "POST",
        cuerpo: { tabla, variables },
      });
      setResultado(r.datos);
    } catch (e) {
      if (!recogerProblemas(e)) setFallo(e);
    } finally {
      setOcupado(false);
    }
  }

  async function guardar() {
    setOcupado(true);
    setAviso("");
    setFallo(null);
    try {
      const r = await llamar<{ clave: string; analisis: Analisis }>(
        `/api/v1/tablas-decision/${encodeURIComponent(clave)}`,
        { metodo: "PUT", cuerpo: tabla },
      );
      setProblemas([]);
      setAnalisis(r.datos.analisis);
      setAviso(t("tablasDecision.guardada"));
      if (nueva)
        navegar(
          `/m/procesos/tablas-decision/${encodeURIComponent(r.datos.clave)}`,
        );
    } catch (e) {
      if (!recogerProblemas(e)) setFallo(e);
    } finally {
      setOcupado(false);
    }
  }

  // ── Columnas ──
  function cambiarColumna(
    tipo: "entradas" | "salidas",
    i: number,
    cambio: Partial<Columna>,
  ) {
    const lista = tipo === "entradas" ? entradas : salidas;
    const antes = lista[i]?.clave ?? "";
    const siguiente = lista.map((c, j) => (j === i ? { ...c, ...cambio } : c));
    (tipo === "entradas" ? setEntradas : setSalidas)(siguiente);
    // Renombrar una columna arrastra sus casillas: es el error más frecuente al
    // editar una tabla, y dejaría reglas apuntando a un nombre que ya no existe.
    if (cambio.clave !== undefined && cambio.clave !== antes) {
      const nuevo = cambio.clave;
      setReglas((rs) =>
        rs.map((r) => {
          const mapa =
            tipo === "entradas" ? { ...r.condiciones } : { ...r.salidas };
          if (antes in mapa) {
            (mapa as Record<string, unknown>)[nuevo] = (
              mapa as Record<string, unknown>
            )[antes];
            delete (mapa as Record<string, unknown>)[antes];
          }
          return tipo === "entradas"
            ? { ...r, condiciones: mapa as Record<string, CondicionUI[]> }
            : { ...r, salidas: mapa as Record<string, string> };
        }),
      );
    }
  }

  function quitarColumna(tipo: "entradas" | "salidas", i: number) {
    const lista = tipo === "entradas" ? entradas : salidas;
    const clave = lista[i]?.clave ?? "";
    (tipo === "entradas" ? setEntradas : setSalidas)(
      lista.filter((_, j) => j !== i),
    );
    setReglas((rs) =>
      rs.map((r) => {
        if (tipo === "entradas") {
          const condiciones = { ...r.condiciones };
          delete condiciones[clave];
          return { ...r, condiciones };
        }
        const salidasDeLaRegla = { ...r.salidas };
        delete salidasDeLaRegla[clave];
        return { ...r, salidas: salidasDeLaRegla };
      }),
    );
  }

  function anadirColumna(tipo: "entradas" | "salidas") {
    const lista = tipo === "entradas" ? entradas : salidas;
    let n = lista.length + 1;
    const base = tipo === "entradas" ? "entrada" : "salida";
    while (lista.some((c) => c.clave === `${base}_${n}`)) n++;
    const col: Columna =
      tipo === "entradas"
        ? {
            clave: `${base}_${n}`,
            etiqueta: "",
            expresion: `@${base}_${n}`,
            tipo: "texto",
          }
        : { clave: `${base}_${n}`, etiqueta: "", tipo: "texto" };
    (tipo === "entradas" ? setEntradas : setSalidas)([...lista, col]);
  }

  // ── Reglas ──
  function cambiarRegla(id: string, cambio: (r: ReglaUI) => ReglaUI) {
    setReglas((rs) => rs.map((r) => (r.id === id ? cambio(r) : r)));
  }
  function mover(i: number, paso: number) {
    setReglas((rs) => {
      const j = i + paso;
      if (j < 0 || j >= rs.length) return rs;
      const copia = [...rs];
      const [a, b] = [copia[i], copia[j]];
      if (!a || !b) return rs;
      copia[i] = b;
      copia[j] = a;
      return copia;
    });
  }

  if (fallo && !cargada) return <Fallo error={fallo} />;
  if (!cargada) return <Cargando />;

  const puedeGuardar = Boolean(clave.trim()) && !ocupado;
  const conPrioridad = politica === "prioridad";

  return (
    <>
      <CabeceraPagina
        icono="table_chart"
        titulo={nueva ? t("tablasDecision.nueva") : nombre || clave}
        entradilla={t("tablasDecision.entradilla")}
        acciones={
          <>
            <Link className="btn-secondary" to={VOLVER}>
              <Icono nombre="arrow_back" tamano="sm" />
              {t("tablasDecision.volver")}
            </Link>
            <button
              type="button"
              className="btn-secondary"
              disabled={ocupado}
              onClick={() => void validar()}
            >
              <Icono nombre="rule" tamano="sm" />
              {t("tablasDecision.validar")}
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={!puedeGuardar}
              onClick={() => void guardar()}
            >
              <Icono nombre="save" tamano="sm" />
              {t("tablasDecision.guardar")}
            </button>
          </>
        }
      />
      <div role="status" className="mb-3">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}

      {/* ── Datos generales ── */}
      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">{t("tablasDecision.general")}</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("tablasDecision.nombre")}
            <input
              className="input-base"
              value={nombre}
              onChange={(e) => {
                setNombre(e.target.value);
                if (nueva) setClave(aClave(e.target.value));
              }}
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("tablasDecision.clave")}
            <input
              className="input-base font-mono"
              value={clave}
              disabled={!nueva}
              onChange={(e) => setClave(limpiarClave(e.target.value))}
            />
            <span className="text-ink-faint">
              {nueva
                ? t("tablasDecision.claveAyuda")
                : t("tablasDecision.claveFija")}
            </span>
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("tablasDecision.politica")}
            <select
              className="input-base"
              value={politica}
              onChange={(e) => setPolitica(e.target.value)}
            >
              {POLITICAS.map((p) => (
                <option key={p} value={p}>
                  {t(`tablasDecision.politicas.${p}`)}
                </option>
              ))}
            </select>
            <span className="text-ink-faint">
              {t(`tablasDecision.politicasAyuda.${politica}`)}
            </span>
          </label>
        </div>
        <label className="mt-3 flex items-center gap-2 text-dato text-ink">
          <input
            type="checkbox"
            checked={activa}
            onChange={(e) => setActiva(e.target.checked)}
          />
          {t("tablasDecision.activa")}
        </label>
      </section>

      {/* ── Columnas ── */}
      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        {(["entradas", "salidas"] as const).map((tipo) => {
          const lista = tipo === "entradas" ? entradas : salidas;
          return (
            <section key={tipo} className="card p-4">
              <h2 className="section-label mb-1">
                {t(`tablasDecision.${tipo}`)}
              </h2>
              <p className="mb-2 text-rotulo text-ink-faint">
                {t(`tablasDecision.${tipo}Ayuda`)}
              </p>
              <Rejilla
                titulo={t(`tablasDecision.${tipo}`)}
                compacta
                cabeceras={[
                  t("tablasDecision.columnaClave"),
                  t("tablasDecision.columnaEtiqueta"),
                  ...(tipo === "entradas"
                    ? [t("tablasDecision.columnaExpresion")]
                    : []),
                  t("tablasDecision.columnaTipo"),
                  "",
                ]}
              >
                {lista.map((c, i) => (
                  <tr key={i}>
                    <Casilla>
                      <input
                        className="input-base font-mono"
                        aria-label={t("tablasDecision.columnaClave")}
                        value={c.clave}
                        onChange={(e) =>
                          cambiarColumna(tipo, i, {
                            clave: limpiarClave(e.target.value),
                          })
                        }
                      />
                    </Casilla>
                    <Casilla>
                      <input
                        className="input-base"
                        aria-label={t("tablasDecision.columnaEtiqueta")}
                        value={c.etiqueta ?? ""}
                        onChange={(e) =>
                          cambiarColumna(tipo, i, { etiqueta: e.target.value })
                        }
                      />
                    </Casilla>
                    {tipo === "entradas" ? (
                      <Casilla>
                        <input
                          className="input-base font-mono"
                          aria-label={t("tablasDecision.columnaExpresion")}
                          placeholder="@oportunidad.importe"
                          value={c.expresion ?? ""}
                          onChange={(e) =>
                            cambiarColumna(tipo, i, {
                              expresion: e.target.value,
                            })
                          }
                        />
                      </Casilla>
                    ) : null}
                    <Casilla>
                      <select
                        className="input-base min-w-[8rem]"
                        aria-label={t("tablasDecision.columnaTipo")}
                        value={c.tipo ?? ""}
                        onChange={(e) =>
                          cambiarColumna(tipo, i, {
                            tipo: e.target.value || null,
                          })
                        }
                      >
                        <option value="">{t("tablasDecision.sinTipo")}</option>
                        {TIPOS.map((x) => (
                          <option key={x} value={x}>
                            {t(`tablasDecision.tipos.${x}`)}
                          </option>
                        ))}
                      </select>
                    </Casilla>
                    <Casilla>
                      <button
                        type="button"
                        className="btn-link text-danger"
                        aria-label={t("tablasDecision.quitarColumna", {
                          clave: c.clave,
                        })}
                        onClick={() => quitarColumna(tipo, i)}
                      >
                        <Icono nombre="delete" tamano="sm" />
                      </button>
                    </Casilla>
                  </tr>
                ))}
              </Rejilla>
              <button
                type="button"
                className="btn-secondary mt-2"
                onClick={() => anadirColumna(tipo)}
              >
                <Icono nombre="add" tamano="sm" />
                {t(`tablasDecision.anadir_${tipo}`)}
              </button>
            </section>
          );
        })}
      </div>

      {/* ── Reglas ── */}
      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("tablasDecision.reglas")}</h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {t("tablasDecision.reglasAyuda")}
        </p>
        <Rejilla
          titulo={t("tablasDecision.reglas")}
          cabeceras={[
            "#",
            t("tablasDecision.reglaNombre"),
            ...entradas.map((e) => (
              <span key={`e-${e.clave}`} title={e.expresion}>
                {t("tablasDecision.si", { columna: e.etiqueta || e.clave })}
              </span>
            )),
            ...salidas.map((s) => (
              <span key={`s-${s.clave}`}>
                {t("tablasDecision.entonces", {
                  columna: s.etiqueta || s.clave,
                })}
              </span>
            )),
            ...(conPrioridad ? [t("tablasDecision.prioridad")] : []),
            "",
          ]}
        >
          {reglas.map((r, i) => {
            const acerto = resultado?.reglas.find((x) => x.indice === i);
            return (
              <tr
                key={r.id}
                className={cn(acerto?.caso && "bg-success/10")}
                aria-label={t("tablasDecision.reglaN", { n: i + 1 })}
              >
                <Casilla enUnaLinea className="text-ink-muted">
                  {i + 1}
                </Casilla>
                <Casilla className="min-w-[10rem]">
                  <input
                    className="input-base"
                    aria-label={t("tablasDecision.reglaNombre")}
                    placeholder={t("tablasDecision.reglaN", { n: i + 1 })}
                    value={r.nombre}
                    onChange={(e) =>
                      cambiarRegla(r.id, (x) => ({
                        ...x,
                        nombre: e.target.value,
                      }))
                    }
                  />
                </Casilla>
                {entradas.map((e) => (
                  <Casilla key={e.clave} className="min-w-[12rem]">
                    <CeldaCondicion
                      columna={e.etiqueta || e.clave}
                      condiciones={r.condiciones[e.clave] ?? []}
                      alCambiar={(conds) =>
                        cambiarRegla(r.id, (x) => ({
                          ...x,
                          condiciones: { ...x.condiciones, [e.clave]: conds },
                        }))
                      }
                    />
                  </Casilla>
                ))}
                {salidas.map((s) => (
                  <Casilla key={s.clave} className="min-w-[9rem]">
                    <input
                      className="input-base"
                      aria-label={t("tablasDecision.salidaDe", {
                        columna: s.etiqueta || s.clave,
                        n: i + 1,
                      })}
                      value={r.salidas[s.clave] ?? ""}
                      onChange={(ev) =>
                        cambiarRegla(r.id, (x) => ({
                          ...x,
                          salidas: { ...x.salidas, [s.clave]: ev.target.value },
                        }))
                      }
                    />
                  </Casilla>
                ))}
                {conPrioridad ? (
                  <Casilla className="w-24">
                    <input
                      type="number"
                      className="input-base"
                      aria-label={t("tablasDecision.prioridad")}
                      value={r.prioridad}
                      onChange={(ev) =>
                        cambiarRegla(r.id, (x) => ({
                          ...x,
                          prioridad: ev.target.value,
                        }))
                      }
                    />
                  </Casilla>
                ) : null}
                <Casilla enUnaLinea>
                  <button
                    type="button"
                    className="btn-link"
                    disabled={i === 0}
                    aria-label={t("tablasDecision.subir")}
                    onClick={() => mover(i, -1)}
                  >
                    <Icono nombre="arrow_upward" tamano="sm" />
                  </button>
                  <button
                    type="button"
                    className="btn-link"
                    disabled={i === reglas.length - 1}
                    aria-label={t("tablasDecision.bajar")}
                    onClick={() => mover(i, 1)}
                  >
                    <Icono nombre="arrow_downward" tamano="sm" />
                  </button>
                  <button
                    type="button"
                    className="btn-link text-danger"
                    aria-label={t("tablasDecision.quitarRegla", { n: i + 1 })}
                    onClick={() =>
                      setReglas((rs) => rs.filter((x) => x.id !== r.id))
                    }
                  >
                    <Icono nombre="delete" tamano="sm" />
                  </button>
                </Casilla>
              </tr>
            );
          })}
        </Rejilla>
        <button
          type="button"
          className="btn-secondary mt-2"
          onClick={() =>
            setReglas((rs) => [
              ...rs,
              {
                id: nuevoId(),
                nombre: "",
                prioridad: "",
                condiciones: {},
                salidas: {},
              },
            ])
          }
        >
          <Icono nombre="add" tamano="sm" />
          {t("tablasDecision.anadirRegla")}
        </button>
      </section>

      {/* ── Validación ── */}
      {problemas || analisis ? (
        <section className="card mb-4 p-4">
          <h2 className="section-label mb-2">{t("tablasDecision.analisis")}</h2>
          {problemas && problemas.length > 0 ? (
            <>
              <p className="mb-1 font-medium text-danger">
                {t("tablasDecision.problemas")}
              </p>
              <ul className="lista-acotada mb-3 list-disc pl-5 text-dato text-ink">
                {problemas.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </>
          ) : null}
          {analisis ? <InformeDeAnalisis analisis={analisis} /> : null}
        </section>
      ) : null}

      {/* ── Probar ── */}
      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("tablasDecision.probar")}</h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {t("tablasDecision.probarAyuda")}
        </p>
        <div className="grid gap-3 md:grid-cols-3">
          {entradas.map((e) => (
            <label
              key={e.clave}
              className="flex flex-col gap-1 text-rotulo text-ink-muted"
            >
              {e.etiqueta || e.clave}
              {e.tipo === "booleano" ? (
                <select
                  className="input-base"
                  aria-label={e.etiqueta || e.clave}
                  value={datosPrueba[e.clave] ?? ""}
                  onChange={(ev) =>
                    setDatosPrueba((d) => ({
                      ...d,
                      [e.clave]: ev.target.value,
                    }))
                  }
                >
                  <option value="">—</option>
                  <option value="true">{t("tablasDecision.verdadero")}</option>
                  <option value="false">{t("tablasDecision.falso")}</option>
                </select>
              ) : (
                <input
                  className="input-base"
                  aria-label={e.etiqueta || e.clave}
                  inputMode={e.tipo === "numero" ? "decimal" : undefined}
                  value={datosPrueba[e.clave] ?? ""}
                  onChange={(ev) =>
                    setDatosPrueba((d) => ({
                      ...d,
                      [e.clave]: ev.target.value,
                    }))
                  }
                />
              )}
            </label>
          ))}
        </div>
        <button
          type="button"
          className="btn-secondary mt-3"
          disabled={ocupado || entradas.length === 0}
          onClick={() => void probar()}
        >
          <Icono nombre="play_arrow" tamano="sm" />
          {t("tablasDecision.probarBoton")}
        </button>
        {resultado ? (
          <ResultadoDePrueba
            resultado={resultado}
            salidas={salidas}
            politica={politica}
          />
        ) : null}
      </section>
    </>
  );
}

function CeldaCondicion({
  columna,
  condiciones,
  alCambiar,
}: {
  columna: string;
  condiciones: CondicionUI[];
  alCambiar: (c: CondicionUI[]) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-1">
      {condiciones.length === 0 ? (
        <span className="text-rotulo text-ink-faint">
          {t("tablasDecision.cualquiera")}
        </span>
      ) : null}
      {condiciones.map((c, i) => (
        <div key={i} className="flex items-center gap-1">
          <select
            className="input-base w-[5.5rem] shrink-0"
            aria-label={t("tablasDecision.operadorDe", { columna })}
            value={c.op}
            onChange={(e) =>
              alCambiar(
                condiciones.map((x, j) =>
                  j === i ? { ...x, op: e.target.value } : x,
                ),
              )
            }
          >
            {OPERADORES.map((op) => (
              <option key={op} value={op}>
                {t(`tablasDecision.operadores.${op}`)}
              </option>
            ))}
          </select>
          {SIN_VALOR.has(c.op) ? null : (
            <input
              className="input-base min-w-0"
              aria-label={t("tablasDecision.valorDe", { columna })}
              value={c.valor}
              onChange={(e) =>
                alCambiar(
                  condiciones.map((x, j) =>
                    j === i ? { ...x, valor: e.target.value } : x,
                  ),
                )
              }
            />
          )}
          <button
            type="button"
            className="btn-link text-danger"
            aria-label={t("tablasDecision.quitarCondicion")}
            onClick={() => alCambiar(condiciones.filter((_, j) => j !== i))}
          >
            <Icono nombre="close" tamano="sm" />
          </button>
        </div>
      ))}
      <button
        type="button"
        className="btn-link self-start text-rotulo"
        aria-label={t("tablasDecision.anadirCondicionEn", { columna })}
        onClick={() => alCambiar([...condiciones, { op: "=", valor: "" }])}
      >
        {condiciones.length === 0
          ? t("tablasDecision.anadirCondicion")
          : t("tablasDecision.yAdemas")}
      </button>
    </div>
  );
}

function rango(desde: number | null, hasta: number | null): string {
  return `${desde === null ? "−∞" : desde} … ${hasta === null ? "+∞" : hasta}`;
}

function InformeDeAnalisis({ analisis }: { analisis: Analisis }) {
  const { t } = useTranslation();
  const limpia =
    analisis.huecos.length === 0 &&
    analisis.solapes.length === 0 &&
    analisis.inalcanzables.length === 0;
  return (
    <div className="space-y-2 text-dato">
      {limpia ? (
        <p className="text-success">{t("tablasDecision.sinAvisos")}</p>
      ) : null}
      {analisis.huecos.length > 0 ? (
        <div>
          <p className="font-medium text-ink">
            {t("tablasDecision.huecos", { count: analisis.huecos.length })}
          </p>
          <ul className="list-disc pl-5 text-ink-muted">
            {analisis.huecos.map((h, i) => (
              <li key={i}>
                {t("tablasDecision.hueco", {
                  entrada: h.entrada,
                  rango: rango(h.desde, h.hasta),
                })}
              </li>
            ))}
          </ul>
          {analisis.sin_red_de_seguridad ? (
            <p className="text-danger">{t("tablasDecision.sinRed")}</p>
          ) : null}
        </div>
      ) : null}
      {analisis.solapes.length > 0 ? (
        <div>
          <p className="font-medium text-ink">
            {t("tablasDecision.solapes", { count: analisis.solapes.length })}
          </p>
          <ul className="list-disc pl-5 text-ink-muted">
            {analisis.solapes.map((s, i) => (
              <li key={i}>
                {s.reglas.join(" ↔ ")}: {s.motivo}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {analisis.inalcanzables.length > 0 ? (
        <div>
          <p className="font-medium text-ink">
            {t("tablasDecision.inalcanzables", {
              count: analisis.inalcanzables.length,
            })}
          </p>
          <ul className="list-disc pl-5 text-ink-muted">
            {analisis.inalcanzables.map((x, i) => (
              <li key={i}>
                {t("tablasDecision.tapada", {
                  regla: x.regla,
                  por: x.tapada_por,
                })}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {analisis.indecidibles.length > 0 ? (
        <p className="text-rotulo text-ink-faint">
          {t("tablasDecision.indecidibles", {
            lista: analisis.indecidibles.join(", "),
          })}
        </p>
      ) : null}
    </div>
  );
}

function ResultadoDePrueba({
  resultado,
  salidas,
  politica,
}: {
  resultado: Evaluacion;
  salidas: Columna[];
  politica: string;
}) {
  const { t } = useTranslation();
  const casadas = resultado.reglas.filter((r) => r.caso);
  return (
    <div className="mt-4 space-y-3" role="status">
      <div>
        <p className="section-label mb-1">{t("tablasDecision.salio")}</p>
        {Object.keys(resultado.salidas).length === 0 ? (
          <p className="text-dato text-ink-muted">
            {t("tablasDecision.nadaSalio")}
          </p>
        ) : (
          <ul className="text-dato text-ink">
            {Object.entries(resultado.salidas).map(([k, v]) => (
              <li key={k}>
                <span className="text-ink-muted">
                  {salidas.find((s) => s.clave === k)?.etiqueta || k}:
                </span>{" "}
                <strong>{aTexto(v)}</strong>
              </li>
            ))}
          </ul>
        )}
        <p className="text-rotulo text-ink-faint">
          {resultado.por_defecto
            ? t("tablasDecision.porDefecto")
            : t("tablasDecision.acertaron", {
                lista: casadas
                  .map((r) => `${r.indice + 1}. ${r.nombre}`)
                  .join(", "),
                politica: t(`tablasDecision.politicasAyuda.${politica}`),
              })}
        </p>
      </div>
      <div>
        <p className="section-label mb-1">{t("tablasDecision.porQue")}</p>
        <Rejilla
          titulo={t("tablasDecision.porQue")}
          compacta
          cabeceras={[
            "#",
            t("tablasDecision.reglaNombre"),
            t("tablasDecision.resultado"),
            t("tablasDecision.explicacion"),
          ]}
        >
          {resultado.reglas.map((r) => (
            <tr key={r.indice}>
              <Casilla enUnaLinea>{r.indice + 1}</Casilla>
              <Casilla>{r.nombre}</Casilla>
              <Casilla enUnaLinea>
                <span
                  className={cn("chip-dato", r.caso ? "chip-dato--si" : "")}
                >
                  {r.caso
                    ? t("tablasDecision.caso")
                    : t("tablasDecision.noCaso")}
                </span>
              </Casilla>
              <Casilla className="text-ink-muted">
                {r.fallo_en
                  ? t("tablasDecision.falloEn", {
                      entrada: r.fallo_en.entrada,
                      operador: r.fallo_en.operador,
                      esperado: aTexto(r.fallo_en.esperado),
                      encontrado:
                        r.fallo_en.encontrado === null ||
                        r.fallo_en.encontrado === undefined
                          ? t("tablasDecision.vacio")
                          : aTexto(r.fallo_en.encontrado),
                    })
                  : r.caso
                    ? t("tablasDecision.cumpleTodas")
                    : ""}
              </Casilla>
            </tr>
          ))}
        </Rejilla>
      </div>
    </div>
  );
}
