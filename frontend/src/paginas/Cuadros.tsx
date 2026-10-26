/**
 * Cuadros de mando (CRM-05.01.02.01, CRM-05.01.02.02, CRM-05.01.02.03).
 *
 * **Cada componente EJECUTA su informe y se pinta.** Esta pantalla enseñaba solo
 * el título de cada componente y su tipo: una rejilla de cajas con una etiqueta
 * dentro y nada más. No era un cuadro de mando, era su índice. Quien la abría
 * veía seis recuadros vacíos y concluía, con razón, que no funcionaba.
 *
 * Se dibuja con el MISMO componente que pinta las respuestas de la explotación
 * (`RespuestaAnalitica`). Dos pantallas que enseñan la misma cifra tienen que
 * colocarla igual: con dos dibujantes distintos, la misma suma sale con dos
 * formatos y quien la ve duda de cuál es la buena.
 *
 * Los tipos de componente se piden al servidor, **no se escriben aquí**: dos
 * listas que tienen que coincidir acaban no coincidiendo, y la que se queda corta
 * es siempre la del front.
 *
 * El filtro de arriba es del cuadro entero y llega a todos los componentes menos
 * a los que se declaran inmunes. Y de cada componente se puede bajar al detalle:
 * un cuadro del que no se puede bajar obliga a rehacer la consulta a mano en otra
 * pantalla, y ahí ya no coinciden los números.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { ErrorApi, llamar } from "@/lib/api";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Medidor } from "@/componentes/graficas/Medidor";
import { RespuestaAnalitica, type Payload } from "@/componentes/RespuestaAnalitica";

interface Componente {
  informe?: string;
  tipo: string;
  titulo?: string;
  ignora_filtros?: boolean;
  metrica?: string;
  dimension?: string;
  texto?: string;
  limite?: number;
  /**
   * Forma de un gráfico: `barras`, `lineas` o `area`.
   *
   * La elige quien monta el cuadro. El catálogo del servidor prometía «barras,
   * líneas o áreas» desde el principio y aquí se dibujaban las tres como
   * barras: una serie temporal salía como un bosque de barras, que es la forma
   * de no ver una tendencia.
   */
  forma?: string;
  /** La meta de un `gauge`. Sin ella no hay medidor, sólo una cifra. */
  objetivo?: number;
}

interface Resultado {
  nombre: string;
  columnas: string[];
  filas: unknown[][];
  truncado?: boolean;
  campos_retirados?: string[];
  /**
   * El resultado no es el informe que se definió, y el servidor dice por qué.
   *
   * `aviso_datos` es «el objeto se lee incompleto porque su listado no pagina»
   * y `aviso_plan` es «el motor ha devuelto más columnas de las que este
   * informe sabe nombrar», que significa que las cabeceras pueden no
   * corresponder con los datos. Los dos venían en la respuesta y **no se
   * pintaban en ninguna parte**: la cifra salía con su cara de cifra buena y el
   * motivo se quedaba en el JSON, que es exactamente igual que no decirlo.
   */
  incompleto?: boolean;
  aviso_datos?: string;
  aviso_plan?: string;
}

interface InformeListado {
  id: string;
  clave: string;
}

/** Cómo se dibuja cada tipo de componente. La tabla es el suelo: siempre se lee. */
const FORMA: Record<string, string> = {
  kpi: "kpi_card",
  // `gauge` ya NO cae aquí: tiene su propio dibujo. Pintarlo como un KPI
  // perdía el objetivo, que es lo único que distingue un medidor de una cifra.
  grafico: "bar_chart",
  embudo: "funnel_chart",
  // Un mapa todavía no se dibuja como mapa. Cae a barras **y se dice**: una
  // barra por territorio es honesta —ordena y compara— mientras que un hueco
  // con el título puesto parece que no ha cargado.
  mapa: "bar_chart",
  tabla: "table",
};

/**
 * La cifra de un payload de KPI, para el medidor.
 *
 * Se saca del payload ya calculado y no se vuelve a sumar aquí: dos sumas de
 * lo mismo en dos sitios acaban dando dos cifras, y entonces nadie sabe cuál
 * es la buena.
 */
function valorDe(payload: Payload): number {
  const fila = (payload.data ?? [])[0] ?? {};
  const clave = payload.series?.[0]?.key ?? Object.keys(fila)[0] ?? "";
  const bruto = fila[clave];
  return typeof bruto === "number" ? bruto : Number(bruto ?? 0);
}

/** La forma que pide el componente, traducida al tipo que entiende la gráfica. */
const DE_FORMA: Record<string, string> = {
  barras: "bar_chart",
  lineas: "line_chart",
  area: "area_chart",
};

interface Cuadro {
  id: string;
  clave: string;
  nombre: string;
  descripcion: string;
  componentes: Componente[];
  por_defecto: boolean;
  propio: boolean;
}

export function Cuadros() {
  const { t } = useTranslation();
  const [cuadros, setCuadros] = useState<Cuadro[] | null>(null);
  const [abierto, setAbierto] = useState<string | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<Cuadro[]>("/api/v1/cuadros-mando", { signal: control.signal })
      .then((r) => {
        setCuadros(r.datos);
        const defecto = r.datos.find((c) => c.por_defecto) ?? r.datos[0];
        setAbierto(defecto ? defecto.id : null);
      })
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!cuadros) return <Cargando />;
  if (cuadros.length === 0)
    return (
      <div className="p-4">
        <Vacio titulo={t("cuadros.ninguno")} detalle={t("cuadros.ningunoDetalle")} />
      </div>
    );

  // El `find` puede no encontrar nada y `cuadros[0]` puede ser `undefined` para
  // TypeScript aunque ya sepamos que la lista no está vacía. Se resuelve con una
  // guarda explícita en vez de con `!`: la aserción calla al compilador y deja
  // la pantalla en blanco el día que la lista llegue vacía por otra vía.
  const actual = cuadros.find((c) => c.id === abierto) ?? cuadros[0];
  if (!actual) return <Cargando />;

  return (
    <div className="flex flex-col gap-4">
      <CabeceraPagina
        titulo={t("cuadros.titulo")}
        icono="dashboard"
        acciones={
          <>
            <label htmlFor="cuadros-elegir" className="sr-only">
              {t("cuadros.elegir")}
            </label>
            <select
              id="cuadros-elegir"
              value={actual.id}
              onChange={(e) => setAbierto(e.target.value)}
              className="input-sm"
            >
              {cuadros.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre}
                </option>
              ))}
            </select>
          </>
        }
      />

      {actual.descripcion ? (
        <p className="max-w-prose text-2xs text-ink-muted">{actual.descripcion}</p>
      ) : null}

      {actual.componentes.length === 0 ? (
        <Vacio titulo={t("cuadros.sinComponentes")} detalle={t("cuadros.sinComponentesDetalle")} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {actual.componentes.map((c, i) => (
            <ComponenteDelCuadro key={`${c.tipo}-${i}`} componente={c} />
          ))}
        </div>
      )}
    </div>
  );
}


/**
 * Un componente del cuadro: ejecuta su informe y lo pinta.
 *
 * El informe se referencia por su CLAVE —así el cuadro se puede copiar entre
 * instalaciones— y se ejecuta por su identificador, así que hace falta la lista
 * para traducir uno en otro. Se pide una vez por componente y el navegador la
 * cachea; pedirla en el padre y pasarla obligaría a que el cuadro entero
 * esperara a la más lenta.
 */
function ComponenteDelCuadro({ componente }: { componente: Componente }) {
  const { t } = useTranslation();
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [informeId, setInformeId] = useState("");
  const [bajando, setBajando] = useState(false);
  // Qué ha pasado con la descarga. Un fichero que se baja no cambia nada en la
  // pantalla, así que quien no la ve no se entera de si ha salido o no.
  const [bajado, setBajado] = useState("");

  useEffect(() => {
    if (!componente.informe) return;
    const control = new AbortController();
    (async () => {
      try {
        const lista = await llamar<InformeListado[]>("/api/v1/informes", {
          signal: control.signal,
        });
        const informe = lista.datos.find((x) => x.clave === componente.informe);
        if (!informe) {
          // Se dice CUÁL falta, no «no se pudo cargar»: un cuadro que apunta a un
          // informe borrado es un problema de configuración, y con el nombre
          // delante se arregla en un minuto.
          setFallo(new Error(t("cuadros.informeNoExiste", { clave: componente.informe })));
          return;
        }
        const r = await llamar<Resultado>(`/api/v1/informes/${informe.id}/ejecutar`, {
          metodo: "POST",
          cuerpo: {},
          signal: control.signal,
        });
        setResultado(r.datos);
        setInformeId(informe.id);
      } catch (e) {
        setFallo(e);
      }
    })();
    return () => control.abort();
  }, [componente.informe, t]);

  const payload = useMemo<Payload | null>(
    () => (resultado ? aPayload(componente, resultado) : null),
    [componente, resultado],
  );

  /**
   * Baja el informe en CSV.
   *
   * Se pide al servidor y no se compone aquí con lo que ya está en pantalla: lo
   * de la pantalla puede venir recortado por el tope del componente, y un
   * fichero que se manda por correo con menos filas de las que hay es
   * exactamente el fallo que este sistema se pasa el día evitando.
   */
  const descargar = useCallback(async () => {
    if (!informeId) return;
    setBajando(true);
    try {
      const r = await llamar<{ export?: { contenido?: string } }>(
        `/api/v1/informes/${informeId}/ejecutar`,
        { metodo: "POST", cuerpo: { formato: "csv" } },
      );
      const contenido = r.datos.export?.contenido ?? "";
      const url = URL.createObjectURL(new Blob([contenido], { type: "text/csv;charset=utf-8" }));
      const enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = `${componente.informe ?? "informe"}.csv`;
      enlace.click();
      URL.revokeObjectURL(url);
      setBajado(t("cuadros.bajado", { filas: (contenido.split("\n").length || 1) - 2 }));
    } catch (e) {
      setFallo(e);
    } finally {
      setBajando(false);
    }
  }, [informeId, componente.informe, t]);

  return (
    <article className="rounded-lg border border-ink-dim/40 bg-paper-light p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm text-ink">{componente.titulo ?? componente.informe ?? componente.tipo}</h2>
        <span className="flex shrink-0 items-center gap-2">
          {/* La exportación existía en la API y no se podía pedir desde ninguna
              pantalla: había que llamarla a mano. Y llevaba tiempo rota —las
              filas son listas y el generador esperaba diccionarios—, cosa que
              nadie notó justamente porque no había por dónde pulsarla. */}
          {informeId ? (
            <button
              type="button"
              onClick={() => void descargar()}
              disabled={bajando}
              className="rounded border border-ink-dim/60 px-2 py-0.5 text-3xs text-ink-muted disabled:opacity-50"
            >
              {bajando ? t("cuadros.bajando") : t("cuadros.descargar")}
            </button>
          ) : null}
          <span className="text-3xs uppercase text-ink-faint">{componente.tipo}</span>
        </span>
      </div>
      {/* Que un componente ignore el filtro global se DICE: si no, quien cambia
          el trimestre y ve una cifra que no se mueve concluye que el filtro no
          funciona. */}
      {componente.ignora_filtros ? (
        <p className="mt-1 text-3xs text-ink-faint">{t("cuadros.ignoraFiltros")}</p>
      ) : null}

      {componente.tipo === "texto" ? (
        <p className="mt-2 text-2xs text-ink-muted">{componente.texto ?? ""}</p>
      ) : fallo ? (
        <Fallo error={fallo} />
      ) : !payload ? (
        <Cargando />
      ) : (
        <>
          {componente.tipo === "gauge" ? (
            // El medidor NO pasa por el payload analítico: lo que dibuja es una
            // cifra contra su meta, y el payload no sabe de metas. Pintarlo
            // como un KPI —que es lo que se hacía— perdía el objetivo, o sea
            // lo único que distingue un medidor de una cifra suelta.
            <Medidor
              titulo={componente.titulo ?? ""}
              valor={valorDe(payload)}
              objetivo={Number(componente.objetivo ?? 0)}
            />
          ) : (
            <RespuestaAnalitica payload={payload} />
          )}
          {/* Un informe cortado se dice. Leído como el total, se toman
              decisiones con la mitad de los datos. */}
          {resultado?.truncado ? (
            <p className="mt-2 text-3xs text-ink-faint">{t("cuadros.truncado")}</p>
          ) : null}
          {resultado?.campos_retirados?.length ? (
            <p className="mt-1 text-3xs text-ink-faint">
              {t("cuadros.camposRetirados", { campos: resultado.campos_retirados.join(", ") })}
            </p>
          ) : null}
          {/* Estos dos van con el texto normal y no en gris claro: no son una
              nota al pie, son la advertencia de que la cifra de arriba no
              contesta la pregunta que parece contestar. */}
          {resultado?.aviso_datos ? (
            <p className="mt-1 text-2xs text-ink-muted">{resultado.aviso_datos}</p>
          ) : null}
          {resultado?.aviso_plan ? (
            <p className="mt-1 text-2xs text-ink-muted">{resultado.aviso_plan}</p>
          ) : null}
          {/* Siempre en el árbol, aunque vacío: una región de estado que
              aparece a la vez que su texto puede no llegar a leerse. */}
          <p role="status" className="mt-1 text-3xs text-ink-faint">
            {bajado}
          </p>
        </>
      )}
    </article>
  );
}

/**
 * El resultado del informe, con la forma que sabe pintar `RespuestaAnalitica`.
 *
 * Las filas vienen como listas y no como objetos —pesan la mitad, y un informe
 * de cincuenta mil filas se nota— así que aquí se casan con sus nombres de
 * columna, que el servidor manda en el mismo orden.
 *
 * **Un KPI suma la columna de la métrica en vez de coger la primera fila.** Un
 * informe agrupado tiene una fila por grupo: enseñar la primera daría «19
 * oportunidades» cuando hay 91, y la cifra parecería correcta.
 */
function aPayload(componente: Componente, resultado: Resultado): Payload {
  const columnas = resultado.columnas ?? [];
  const data = (resultado.filas ?? []).map((fila) =>
    Object.fromEntries(columnas.map((c, i) => [c, fila[i]])),
  );
  // La forma que pide el componente manda sobre la de su tipo. Sin forma,
  // barras: es lo que había, y así un cuadro existente no cambia de dibujo
  // al desplegar esto.
  const tipo =
    (componente.forma ? DE_FORMA[componente.forma] : undefined) ??
    // El medidor usa el mismo cálculo que un KPI —sumar la métrica— y luego
    // lo dibuja distinto. Compartir el cálculo es lo que hace que la cifra del
    // medidor y la del KPI equivalente coincidan.
    (componente.tipo === "gauge" ? "kpi_card" : undefined) ??
    FORMA[componente.tipo] ??
    "table";

  if (tipo === "kpi_card") {
    const clave = componente.metrica ?? columnas[columnas.length - 1] ?? "";
    const total = data.reduce(
      (suma, fila) => suma + (typeof fila[clave] === "number" ? (fila[clave] as number) : 0),
      0,
    );
    return {
      type: "kpi_card",
      title: componente.titulo ?? resultado.nombre,
      data: [{ [clave]: total }],
      series: [{ key: clave }],
    };
  }

  return {
    type: tipo,
    title: componente.titulo ?? resultado.nombre,
    data,
    series: componente.metrica ? [{ key: componente.metrica }] : undefined,
    xAxis: componente.dimension ? { key: componente.dimension } : undefined,
  };
}
