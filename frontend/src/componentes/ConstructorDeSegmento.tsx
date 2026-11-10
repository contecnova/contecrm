/**
 * Las condiciones de un segmento, montadas con desplegables y con su tamaño a
 * la vista antes de guardar (CRM-02.01.01.01, .02 y .04).
 *
 * **Medido el 10-11-2026 en Marketing › Segmentos › Nuevo:** «Definición» salía
 * como un editor de clave y valor con un «Editar como JSON» debajo. Para hacer
 * «(A o B) y no C» había que escribir el árbol a mano sabiéndose los nombres
 * de los atributos y de los operadores, y el tamaño sólo se sabía después de
 * guardar. Quien hace marketing no escribe JSON.
 *
 * Tres decisiones:
 *
 * **Los atributos y los operadores los da el servidor**
 * (`GET /segmentos/atributos`): son los que sabe traducir a SQL y los que algo
 * rellena. Ofrecer uno que luego el guardado rechace, o uno que nunca casa con
 * nadie, es una trampa.
 *
 * **Grupos anidados con «todas», «alguna» o «ninguna».** Es la gramática del
 * motor (`y`, `o`, `no`) dicha como se piensa. «Ninguna» se guarda como
 * `no(o(...))`: el motor niega exactamente una condición.
 *
 * **La estimación es la del servidor, con el mismo código que el segmento
 * guardado** (`POST /segmentos/estimar`): bruto, alcanzables y cuántos caen
 * por supresión. Y al lado, de cuándo son los perfiles sobre los que cuenta:
 * un cero sobre una copia de hace un mes no es un cero.
 */

import { type ReactElement, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ErrorApi, llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";

type Modo = "y" | "o" | "ninguna";

interface Grupo {
  tipo: "grupo";
  modo: Modo;
  hijos: Nodo[];
}

interface Hoja {
  tipo: "condicion";
  atributo: string;
  operador: string;
  valor: unknown;
}

type Nodo = Grupo | Hoja;

interface Atributo {
  atributo: string;
  tipo: "texto" | "numero" | "fecha" | "booleano";
}

interface Catalogo {
  atributos: Atributo[];
  operadores: string[];
}

interface Estimacion {
  bruto: number;
  alcanzables: number;
  suprimidos: number;
  calculado_at: string;
}

export interface EstadoDePerfiles {
  objeto: string;
  perfiles: number;
  mas_antiguo_at: string | null;
  ultimo_at: string | null;
}

/** Los operadores con nombre de clave de texto: `>=` no es una clave legible. */
export const NOMBRE_DE_OPERADOR: Record<string, string> = {
  "=": "igual",
  "!=": "distinto",
  en: "en",
  no_en: "noEn",
  ">": "mayor",
  ">=": "mayorIgual",
  "<": "menor",
  "<=": "menorIgual",
  vacio: "vacio",
  no_vacio: "noVacio",
  hace_menos_de_dias: "haceMenosDeDias",
  hace_mas_de_dias: "haceMasDeDias",
};

const SIN_VALOR = new Set(["vacio", "no_vacio"]);
const DE_LISTA = new Set(["en", "no_en"]);
const DE_DIAS = new Set(["hace_menos_de_dias", "hace_mas_de_dias"]);

const OBJETOS = new Set(["contacto", "lead", "cuenta"]);

function hojaNueva(): Hoja {
  return { tipo: "condicion", atributo: "", operador: "=", valor: "" };
}

function desde(d: unknown, raiz = false): Nodo {
  if (!d || typeof d !== "object")
    return { tipo: "grupo", modo: "y", hijos: [] };
  const n = d as Record<string, unknown>;
  const hijos = Array.isArray(n.hijos) ? n.hijos : [];
  if (n.op === "no") {
    const dentro = hijos[0] as Record<string, unknown> | undefined;
    const lista =
      dentro && dentro.op === "o" && Array.isArray(dentro.hijos)
        ? dentro.hijos
        : dentro
          ? [dentro]
          : [];
    return {
      tipo: "grupo",
      modo: "ninguna",
      hijos: lista.map((h) => desde(h)),
    };
  }
  if (n.op === "y" || n.op === "o") {
    return { tipo: "grupo", modo: n.op, hijos: hijos.map((h) => desde(h)) };
  }
  const hoja: Hoja = {
    tipo: "condicion",
    atributo: String(n.atributo ?? ""),
    operador: String(n.operador ?? "="),
    valor: n.valor ?? "",
  };
  // La raíz es siempre un grupo: así se le puede añadir otra condición sin
  // tener que envolver a mano la que ya había.
  return raiz ? { tipo: "grupo", modo: "y", hijos: [hoja] } : hoja;
}

/** El árbol en la gramática del motor; `null` si aún no dice nada. */
function aDefinicion(n: Nodo): Record<string, unknown> | null {
  if (n.tipo === "condicion") {
    if (!n.atributo) return null;
    return SIN_VALOR.has(n.operador)
      ? { atributo: n.atributo, operador: n.operador }
      : { atributo: n.atributo, operador: n.operador, valor: n.valor };
  }
  const hijos = n.hijos
    .map(aDefinicion)
    .filter((h): h is Record<string, unknown> => h !== null);
  if (hijos.length === 0) return null;
  if (n.modo === "ninguna") return { op: "no", hijos: [{ op: "o", hijos }] };
  return { op: n.modo, hijos };
}

function cambiarEn(
  n: Nodo,
  ruta: number[],
  cambio: (n: Nodo) => Nodo | null,
): Nodo | null {
  if (ruta.length === 0) return cambio(n);
  if (n.tipo !== "grupo") return n;
  const [i, ...resto] = ruta;
  const hijos = n.hijos
    .map((h, j) => (j === i ? cambiarEn(h, resto, cambio) : h))
    .filter((h): h is Nodo => h !== null);
  return { ...n, hijos };
}

function leerValor(
  texto: string,
  tipo: Atributo["tipo"] | undefined,
  operador: string,
): unknown {
  if (DE_LISTA.has(operador)) {
    return texto
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) =>
        tipo === "numero" && /^-?\d+(\.\d+)?$/.test(s) ? Number(s) : s,
      );
  }
  if (DE_DIAS.has(operador) || tipo === "numero") {
    return texto.trim() === "" ? "" : Number(texto);
  }
  if (tipo === "booleano") return texto === "true";
  return texto;
}

function escribirValor(valor: unknown): string {
  if (Array.isArray(valor)) return valor.join(", ");
  if (valor === undefined || valor === null) return "";
  return String(valor);
}

/** De cuándo son los perfiles de un objeto, con el botón de ponerlos al día. */
export function PerfilesDeMarketing({ objeto }: { objeto: string }) {
  const { t } = useTranslation();
  const [estado, setEstado] = useState<EstadoDePerfiles[] | null>(null);
  const [sincronizando, setSincronizando] = useState(false);
  const [aviso, setAviso] = useState("");

  function cargar(signal?: AbortSignal) {
    llamar<EstadoDePerfiles[]>("/api/v1/segmentos/perfiles", { signal })
      .then((r) => setEstado(Array.isArray(r.datos) ? r.datos : null))
      .catch(() => setEstado(null));
  }

  useEffect(() => {
    const control = new AbortController();
    cargar(control.signal);
    return () => control.abort();
  }, []);

  async function sincronizar() {
    setSincronizando(true);
    setAviso("");
    try {
      const r = await llamar<
        Record<string, { leido: boolean; en_origen?: number }>
      >("/api/v1/segmentos/perfiles/sincronizar", { metodo: "POST" });
      const noLeidos = Object.entries(r.datos)
        .filter(([, v]) => !v.leido)
        .map(([k]) => t(`constructorSegmento.objeto.${k}`));
      setAviso(
        noLeidos.length > 0
          ? t("constructorSegmento.sincronizadoAMedias", {
              objetos: noLeidos.join(", "),
            })
          : t("constructorSegmento.sincronizado"),
      );
      cargar();
    } catch (error) {
      setAviso(
        error instanceof ErrorApi
          ? error.explicacion || error.titulo
          : String(error),
      );
    } finally {
      setSincronizando(false);
    }
  }

  const fila = estado?.find((e) => e.objeto === objeto);
  return (
    <div className="flex flex-wrap items-center gap-2 text-rotulo text-ink-faint">
      <span>
        {fila
          ? fila.ultimo_at
            ? t("constructorSegmento.perfiles", {
                cuantos: fila.perfiles,
                objeto: t(`constructorSegmento.objeto.${objeto}`),
                fecha: fechaHora(fila.mas_antiguo_at ?? fila.ultimo_at),
              })
            : t("constructorSegmento.sinPerfiles", {
                objeto: t(`constructorSegmento.objeto.${objeto}`),
              })
          : null}
      </span>
      <button
        type="button"
        className="btn-ghost"
        disabled={sincronizando}
        onClick={() => void sincronizar()}
      >
        {sincronizando
          ? t("constructorSegmento.sincronizando")
          : t("constructorSegmento.sincronizar")}
      </button>
      <span role="status" aria-live="polite">
        {aviso}
      </span>
    </div>
  );
}

/**
 * De qué otros segmentos se resta este: elegidos por su nombre.
 *
 * Era una caja de etiquetas que pedía identificadores: para excluir «clientes
 * activos» había que saberse su UUID. Sólo se ofrecen los del mismo objeto —
 * restar cuentas de una lista de contactos no resta a nadie—.
 */
export function ExclusionesDeSegmento({
  id,
  valor,
  alCambiar,
  objeto,
  ayuda,
}: {
  id: string;
  valor: unknown;
  alCambiar: (v: unknown) => void;
  objeto: string;
  ayuda?: string;
}) {
  const { t } = useTranslation();
  const [otros, setOtros] = useState<
    { id: string; nombre: string; objeto: string }[] | null
  >(null);
  const elegidos = new Set(Array.isArray(valor) ? valor.map(String) : []);

  useEffect(() => {
    const control = new AbortController();
    llamar<{ id: string; nombre: string; objeto: string }[]>(
      "/api/v1/segmentos",
      {
        signal: control.signal,
      },
    )
      .then((r) => setOtros(Array.isArray(r.datos) ? r.datos : []))
      .catch(() => {
        if (!control.signal.aborted) setOtros([]);
      });
    return () => control.abort();
  }, []);

  const delObjeto = (otros ?? []).filter((o) => o.objeto === objeto);
  return (
    <fieldset id={id} aria-describedby={ayuda} className="flex flex-col gap-1">
      {otros !== null && delObjeto.length === 0 ? (
        <p className="text-rotulo text-ink-faint">
          {t("constructorSegmento.sinOtros", {
            objeto: t(`constructorSegmento.objeto.${objeto}`, {
              defaultValue: objeto,
            }),
          })}
        </p>
      ) : null}
      {delObjeto.map((o) => (
        <label
          key={o.id}
          className="inline-flex items-center gap-2 text-dato text-ink"
        >
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-ink-dim accent-accent"
            checked={elegidos.has(o.id)}
            onChange={(e) => {
              const nuevo = new Set(elegidos);
              if (e.target.checked) nuevo.add(o.id);
              else nuevo.delete(o.id);
              alCambiar([...nuevo]);
            }}
          />
          {o.nombre}
        </label>
      ))}
    </fieldset>
  );
}

export function ConstructorDeSegmento({
  id,
  valor,
  alCambiar,
  objeto,
  excluye,
  ayuda,
}: {
  id: string;
  valor: unknown;
  alCambiar: (v: unknown) => void;
  /** Sobre qué se segmenta: contacto, lead o cuenta. */
  objeto: string;
  /** Los segmentos que se restan, para que la estimación los reste también. */
  excluye?: unknown;
  ayuda?: string;
}) {
  const { t } = useTranslation();
  const [arbol, setArbol] = useState<Nodo>(() => desde(valor, true));
  const [catalogo, setCatalogo] = useState<Catalogo | null>(null);
  const [estimacion, setEstimacion] = useState<Estimacion | null>(null);
  const [fallo, setFallo] = useState("");
  const [calculando, setCalculando] = useState(false);
  const valido = OBJETOS.has(objeto);

  useEffect(() => {
    if (!valido) {
      setCatalogo(null);
      return;
    }
    const control = new AbortController();
    llamar<Catalogo>(`/api/v1/segmentos/atributos?objeto=${objeto}`, {
      signal: control.signal,
    })
      .then((r) => setCatalogo(r.datos))
      .catch(() => {
        if (!control.signal.aborted) setCatalogo(null);
      });
    return () => control.abort();
  }, [objeto, valido]);

  const definicion = useMemo(() => aDefinicion(arbol), [arbol]);
  const restados = Array.isArray(excluye) ? excluye.map(String) : [];
  const clave = JSON.stringify([definicion, restados]);

  useEffect(() => {
    setEstimacion(null);
    setFallo("");
    if (!valido || !definicion) return;
    const control = new AbortController();
    // Se espera a que se deje de teclear: una petición por letra es contar
    // cien mil perfiles once veces para escribir «ingeniería».
    const espera = window.setTimeout(() => {
      setCalculando(true);
      llamar<Estimacion>("/api/v1/segmentos/estimar", {
        metodo: "POST",
        cuerpo: { objeto, definicion, excluye: restados },
        signal: control.signal,
      })
        .then((r) => setEstimacion(r.datos))
        .catch((e: unknown) => {
          if (control.signal.aborted) return;
          setFallo(
            e instanceof ErrorApi ? e.explicacion || e.titulo : String(e),
          );
        })
        .finally(() => {
          if (!control.signal.aborted) setCalculando(false);
        });
    }, 500);
    return () => {
      window.clearTimeout(espera);
      control.abort();
    };
    // `clave` resume la definición: el objeto nuevo en cada render no cuenta.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clave, objeto, valido]);

  function cambiar(ruta: number[], cambio: (n: Nodo) => Nodo | null) {
    const nuevo = cambiarEn(arbol, ruta, cambio) ?? {
      tipo: "grupo",
      modo: "y",
      hijos: [],
    };
    setArbol(nuevo);
    alCambiar(aDefinicion(nuevo) ?? {});
  }

  const tipoDe = (atributo: string) =>
    catalogo?.atributos.find((a) => a.atributo === atributo)?.tipo;

  const nombreDe = (atributo: string) => {
    const propio = atributo.split(".").slice(1).join(".");
    if (propio.startsWith("campos.")) return propio.slice("campos.".length);
    return t(`constructorSegmento.atributo.${propio}`, {
      defaultValue: propio,
    });
  };

  function pintar(n: Nodo, ruta: number[]): ReactElement {
    const sufijo = ruta.map((i) => i + 1).join(".") || "0";
    if (n.tipo === "condicion") {
      const tipo = tipoDe(n.atributo);
      return (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1.3fr)_auto]">
          <select
            className="input-base"
            aria-label={t("constructorSegmento.atributoDe", { numero: sufijo })}
            value={n.atributo}
            onChange={(e) =>
              cambiar(ruta, () => ({
                ...n,
                atributo: e.target.value,
                valor: "",
              }))
            }
          >
            <option value="">{t("constructorSegmento.elegirAtributo")}</option>
            {(catalogo?.atributos ?? []).map((a) => (
              <option key={a.atributo} value={a.atributo}>
                {nombreDe(a.atributo)}
              </option>
            ))}
          </select>
          <select
            className="input-base"
            aria-label={t("constructorSegmento.operadorDe", { numero: sufijo })}
            value={n.operador}
            onChange={(e) =>
              cambiar(ruta, () => ({
                ...n,
                operador: e.target.value,
                valor: "",
              }))
            }
          >
            {(catalogo?.operadores ?? [n.operador]).map((op) => (
              <option key={op} value={op}>
                {t(`constructorSegmento.op.${NOMBRE_DE_OPERADOR[op] ?? op}`, {
                  defaultValue: op,
                })}
              </option>
            ))}
          </select>
          {SIN_VALOR.has(n.operador) ? (
            <span className="hidden md:block" />
          ) : tipo === "booleano" && !DE_LISTA.has(n.operador) ? (
            <select
              className="input-base"
              aria-label={t("constructorSegmento.valorDe", { numero: sufijo })}
              value={String(n.valor === true)}
              onChange={(e) =>
                cambiar(ruta, () => ({
                  ...n,
                  valor: e.target.value === "true",
                }))
              }
            >
              <option value="true">{t("constructorSegmento.si")}</option>
              <option value="false">{t("constructorSegmento.no")}</option>
            </select>
          ) : (
            <input
              className="input-base"
              aria-label={t("constructorSegmento.valorDe", { numero: sufijo })}
              type={
                DE_DIAS.has(n.operador) ||
                (tipo === "numero" && !DE_LISTA.has(n.operador))
                  ? "number"
                  : tipo === "fecha" && !DE_LISTA.has(n.operador)
                    ? "date"
                    : "text"
              }
              placeholder={
                DE_LISTA.has(n.operador)
                  ? t("constructorSegmento.separadosPorComas")
                  : DE_DIAS.has(n.operador)
                    ? t("constructorSegmento.dias")
                    : ""
              }
              value={escribirValor(n.valor)}
              onChange={(e) =>
                cambiar(ruta, () => ({
                  ...n,
                  valor: leerValor(e.target.value, tipo, n.operador),
                }))
              }
            />
          )}
          <button
            type="button"
            className="btn-ghost"
            aria-label={t("constructorSegmento.quitarCondicion", {
              numero: sufijo,
            })}
            onClick={() => cambiar(ruta, () => null)}
          >
            {t("constructorSegmento.quitar")}
          </button>
        </div>
      );
    }
    return (
      <div
        className={
          ruta.length > 0
            ? "flex flex-col gap-2 rounded-lg border border-ink-dim/40 p-3"
            : "flex flex-col gap-2"
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-dato text-ink-muted">
            {t("constructorSegmento.quienCumpla")}
          </span>
          <select
            className="input-base w-auto"
            aria-label={t("constructorSegmento.modoDe", { numero: sufijo })}
            value={n.modo}
            onChange={(e) =>
              cambiar(ruta, () => ({ ...n, modo: e.target.value as Modo }))
            }
          >
            <option value="y">{t("constructorSegmento.modo.y")}</option>
            <option value="o">{t("constructorSegmento.modo.o")}</option>
            <option value="ninguna">
              {t("constructorSegmento.modo.ninguna")}
            </option>
          </select>
          <span className="text-dato text-ink-muted">
            {t("constructorSegmento.deEstas")}
          </span>
          {ruta.length > 0 ? (
            <button
              type="button"
              className="btn-ghost"
              aria-label={t("constructorSegmento.quitarGrupo", {
                numero: sufijo,
              })}
              onClick={() => cambiar(ruta, () => null)}
            >
              {t("constructorSegmento.quitar")}
            </button>
          ) : null}
        </div>
        {n.hijos.length === 0 ? (
          <p className="text-rotulo text-ink-faint">
            {t("constructorSegmento.vacio")}
          </p>
        ) : null}
        {n.hijos.map((h, i) => (
          <div key={i}>{pintar(h, [...ruta, i])}</div>
        ))}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() =>
              cambiar(ruta, (g) =>
                g.tipo === "grupo"
                  ? { ...g, hijos: [...g.hijos, hojaNueva()] }
                  : g,
              )
            }
          >
            {t("constructorSegmento.anadirCondicion")}
          </button>
          <button
            type="button"
            className="btn-ghost"
            onClick={() =>
              cambiar(ruta, (g) =>
                g.tipo === "grupo"
                  ? {
                      ...g,
                      hijos: [
                        ...g.hijos,
                        { tipo: "grupo", modo: "o", hijos: [hojaNueva()] },
                      ],
                    }
                  : g,
              )
            }
          >
            {t("constructorSegmento.anadirGrupo")}
          </button>
        </div>
      </div>
    );
  }

  if (!valido) {
    return (
      <p
        id={id}
        aria-describedby={ayuda}
        className="text-rotulo text-ink-faint"
      >
        {t("constructorSegmento.eligeObjeto")}
      </p>
    );
  }

  return (
    <div
      id={id}
      aria-describedby={ayuda}
      className="flex flex-col gap-3"
      data-testid="constructor-segmento"
    >
      {pintar(arbol, [])}
      <div
        className="rounded-lg border border-ink-dim/40 bg-paper-light p-3"
        role="status"
        aria-live="polite"
      >
        {fallo ? (
          <p className="text-dato text-danger">{fallo}</p>
        ) : estimacion ? (
          <>
            <p className="text-dato text-ink">
              {t("constructorSegmento.llegaria", {
                cuantos: estimacion.alcanzables,
                objeto: t(`constructorSegmento.objeto.${objeto}`),
              })}
            </p>
            <p className="mt-1 text-rotulo text-ink-muted">
              {t("constructorSegmento.desglose", {
                bruto: estimacion.bruto,
                suprimidos: estimacion.suprimidos,
              })}
            </p>
          </>
        ) : (
          <p className="text-rotulo text-ink-faint">
            {calculando
              ? t("constructorSegmento.calculando")
              : t("constructorSegmento.sinEstimacion")}
          </p>
        )}
        <div className="mt-2">
          <PerfilesDeMarketing objeto={objeto} />
        </div>
      </div>
    </div>
  );
}
