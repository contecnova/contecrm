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
}

interface Resultado {
  nombre: string;
  columnas: string[];
  filas: unknown[][];
  truncado?: boolean;
  campos_retirados?: string[];
}

interface InformeListado {
  id: string;
  clave: string;
}

/** Cómo se dibuja cada tipo de componente. La tabla es el suelo: siempre se lee. */
const FORMA: Record<string, string> = {
  kpi: "kpi_card",
  gauge: "kpi_card",
  grafico: "bar_chart",
  embudo: "funnel_chart",
  mapa: "bar_chart",
  tabla: "table",
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

  return (
    <article className="rounded-lg border border-ink-dim/40 bg-paper-light p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm text-ink">{componente.titulo ?? componente.informe ?? componente.tipo}</h2>
        <span className="text-3xs uppercase text-ink-faint">{componente.tipo}</span>
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
          <RespuestaAnalitica payload={payload} />
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
  const tipo = FORMA[componente.tipo] ?? "table";

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
