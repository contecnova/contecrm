/**
 * Una tabla que se pinta de datos que no se conocen de antemano.
 *
 * La consola se construye leyendo el contrato, así que las columnas salen de lo
 * que devuelve la API y no de una lista escrita a mano. Las decisiones:
 *
 * **Las columnas salen de la unión de las claves de todas las filas**, no de la
 * primera. Con la primera, un registro que trae un campo opcional lo pierde y
 * el usuario nunca sabe que existe.
 *
 * **El rótulo de la columna se escribe como se lee.** La API devuelve
 * `sector_codigo` y `facturacion_anual`, y eso es el nombre del campo, no el de
 * la columna. Se transforma con una regla —guiones bajos a espacios y la
 * primera en mayúscula— y no con una lista de traducciones por campo: una lista
 * así se queda corta en cuanto se añade un campo, y entonces conviven columnas
 * bonitas con columnas en crudo, que es peor que tenerlas todas en crudo.
 *
 * **Se eligen las columnas.** Un listado de clientes con las veinte columnas
 * del modelo no se lee: hay que desplazarse en horizontal para llegar al
 * teléfono. Quien mira elige cuáles quiere y se le recuerdan — es lo que hacen
 * las vistas de lista de Salesforce y el «editar columnas» de HubSpot, y por el
 * mismo motivo: las columnas útiles dependen de para qué se mire la lista.
 *
 * **Una columna vacía en TODAS las filas no se pinta, y se dice cuántas se han
 * escondido.** Esconderlas en silencio sería ocultar que el campo existe; no
 * esconderlas deja una tabla de veinte columnas con guiones donde hay tres con
 * datos, y ahí no se lee nada.
 *
 * **Los objetos y las listas se enseñan como JSON, no como `[object Object]`.**
 * Es feo y es honesto: un valor compuesto que se pinta mal parece un valor
 * vacío.
 *
 * **Las celdas no parten la línea.** Un identificador partido en cuatro líneas
 * estira la fila entera y hace ilegible el resto. En pantalla estrecha la tabla
 * se desplaza en horizontal (CRM-07.04.01.08): una tabla de doce columnas
 * apretada en 360 px no se lee; una que se desplaza, sí, y quien mira decide
 * qué mira.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { MenuDeAcciones, type OpcionDeMenu } from "@/componentes/MenuDeAcciones";
import type { CampoEsquema } from "@/lib/contrato";
import { CeldaEditable } from "@/componentes/CeldaEditable";
import { Casilla, Rejilla } from "@/componentes/Rejilla";

import {
  escalar,
  esIdentificadorTecnico,
  humanizar,
  localizacion,
  tieneDato,
  trozos,
  UUID,
} from "@/lib/formato";
import { cn } from "@/lib/utiles";

export interface Props {
  /**
   * Las filas tal y como llegan de la API. Pueden no ser objetos: hay extremos
   * que devuelven una lista de textos —los motivos de pérdida admitidos, por
   * ejemplo— y eso también es un listado legítimo.
   */
  filas: unknown[];
  /** Columnas en orden. Si no se pasan, salen de las filas. */
  columnas?: string[];
  titulo?: string;
  /** Si se pasa, la primera celda de cada fila enlaza a su ficha. */
  enlace?: (fila: Record<string, unknown>) => string | null;
  /**
   * Cuántas columnas se enseñan de entrada cuando el recurso no declara cuáles.
   *
   * Seis, no todas: un listado que nace con veinte columnas obliga a desplazarse
   * en horizontal antes de leer nada, y quien llega no sabe que puede quitarlas.
   */
  porDefecto?: number;
  /**
   * Con qué nombre se recuerda la elección de columnas. Sin él no se recuerda:
   * dos tablas distintas no pueden compartir preferencia.
   */
  recuerdaComo?: string;
  /**
   * Lo que va a la izquierda de la fila de herramientas: normalmente el
   * recuento de filas.
   */
  encabezado?: ReactNode;
  /**
   * Lo que va a la **derecha** del botón de columnas, en esa misma fila.
   *
   * Existe para que el selector de vista —listado, tarjetas, columnas— salga
   * siempre en el mismo sitio y siempre a la derecha del de columnas. Antes lo
   * pintaba la pantalla por su cuenta, en una fila propia encima de esta, así
   * que los dos grupos de controles aparecían uno debajo del otro y cambiaban
   * de orden según la vista.
   */
  acciones?: ReactNode;
  /**
   * Lo que va **entre la barra de herramientas y la tabla**.
   *
   * Para el formulario de alta: su botón vive en la barra, y un formulario que
   * se abre por encima de su propio botón empuja el botón hacia abajo mientras
   * lo miras. Sin esta ranura el botón necesitaba una fila para él solo —52 px
   * en todas las listas, medidos a 1440×900— para poder tener el formulario
   * debajo.
   */
  antes?: ReactNode;
  /**
   * Esta tabla **es** la pantalla: se recorre con la página, sin barra propia.
   *
   * Lo decide quien la coloca, porque es lo único que lo sabe: la misma tabla
   * sirve para el listado de un módulo —donde no hay nada a lo que dejar
   * sitio— y para un panel dentro de un cuadro de mando, donde sí lo hay.
   */
  ocupaLaPantalla?: boolean;
  /**
   * La tabla va pegada a una cabecera que está encima: su barra de
   * herramientas pasa a ser la franja del medio de una sola tarjeta, en vez
   * de un bloque suelto entre dos recuadros.
   */
  pegada?: boolean;
  /**
   * El menú del final de cada fila: lo que se puede hacer con ESE registro
   * sin abrirlo.
   *
   * En Lightning cada fila lleva un `⌄` ahí, y es donde la gente va a buscar
   * «editar» — no al nombre, que abre. Aquí no había nada: para cambiar un
   * dato había que abrir la ficha, encontrar el botón y volver.
   *
   * Lo da quien coloca la tabla, porque qué se puede hacer con una fila
   * depende del recurso y del permiso, y eso la tabla no lo sabe.
   */
  accionesDeFila?: (fila: Record<string, unknown>) => OpcionDeMenu[];
  /**
   * Con qué columnas y en qué orden empieza, cuando esta persona todavía no
   * ha elegido nada para esta clave.
   *
   * Lo trae una vista de lista guardada. **Sólo siembra**: en cuanto alguien
   * toca las columnas, manda su elección — una vista compartida que te
   * devolviera sus columnas cada vez que entras haría imposible mirarla a tu
   * manera, que es por lo que la gente deja de usar las vistas de otros.
   */
  columnasIniciales?: string[];
  ordenInicial?: Orden;
  /**
   * Editar una celda en la propia lista.
   *
   * `esquemaDeCampo` dice qué campos se pueden tocar y con qué control —lo
   * sabe el contrato, no la tabla—, y `alEditarCelda` guarda. Sin los dos, la
   * tabla no ofrece el lápiz: ofrecer editar algo que el servidor va a
   * rechazar es peor que no ofrecerlo.
   */
  esquemaDeCampo?: (campo: string) => CampoEsquema | undefined;
  alEditarCelda?: (fila: Record<string, unknown>, campo: string, valor: unknown) => Promise<void>;
}

const CLAVE_COLUMNAS = "contecrm.columnas";

/**
 * Qué columnas hay puestas ahora mismo para esa clave.
 *
 * Exportada porque al guardar una VISTA DE LISTA hay que llevarse las columnas
 * que hay en pantalla, y leerlas por segunda vez desde la pantalla sería tener
 * dos lecturas del mismo almacenamiento que se separan a la primera
 * corrección.
 */
export function leerElegidas(recuerdaComo?: string): string[] | null {
  if (!recuerdaComo) return null;
  try {
    const crudo = localStorage.getItem(`${CLAVE_COLUMNAS}.${recuerdaComo}`);
    const lista = crudo ? (JSON.parse(crudo) as unknown) : null;
    return Array.isArray(lista) ? lista.map(String) : null;
  } catch {
    return null;
  }
}

/** Por qué columna se ordena y en qué sentido. `null` es «como vino». */
export type Orden = { columna: string; sentido: "asc" | "desc" } | null;

const CLAVE_ORDEN = "contecrm.orden";

/** Lo mismo con el orden. Ver `leerElegidas`. */
export function leerOrden(recuerdaComo?: string): Orden {
  if (!recuerdaComo) return null;
  try {
    const crudo = localStorage.getItem(`${CLAVE_ORDEN}.${recuerdaComo}`);
    if (!crudo) return null;
    const v = JSON.parse(crudo) as Orden;
    return v && typeof v.columna === "string" && (v.sentido === "asc" || v.sentido === "desc")
      ? v
      : null;
  } catch {
    return null;
  }
}

function guardarOrden(recuerdaComo: string | undefined, orden: Orden): void {
  if (!recuerdaComo) return;
  try {
    const clave = `${CLAVE_ORDEN}.${recuerdaComo}`;
    if (orden) localStorage.setItem(clave, JSON.stringify(orden));
    else localStorage.removeItem(clave);
  } catch {
    /* sin almacenamiento: el orden vale para esta pantalla */
  }
}

/**
 * Comparar dos celdas **según lo que son**, no como texto.
 *
 * Ordenar alfabéticamente una columna de importes pone «1.000» antes que
 * «900», y una de fechas en ISO funciona por casualidad mientras nadie cambie
 * el formato. Las dos son el mismo error: tratar el dato por cómo se escribe.
 *
 * Los decimales llegan como cadena desde la API —`Numeric` en JSON es texto
 * para no perder precisión—, así que un número puede venir de las dos formas y
 * hay que reconocerlo aquí.
 *
 * El texto se compara con `localeCompare` y no con `<`: con `<`, «Ávila» cae
 * detrás de «Zamora» porque compara puntos de código, y en castellano eso está
 * mal en todas las listas de nombres.
 */
function comparar(a: unknown, b: unknown): number {
  // Lo que falta va SIEMPRE al final, suba o baje el orden: una columna
  // ordenada que empieza por diez guiones no enseña nada de lo que se pidió.
  const faltaA = !tieneDato(a);
  const faltaB = !tieneDato(b);
  if (faltaA || faltaB) return faltaA && faltaB ? 0 : faltaA ? 1 : -1;

  if (typeof a === "boolean" || typeof b === "boolean") {
    return Number(Boolean(b)) - Number(Boolean(a));
  }

  const numA = typeof a === "number" ? a : Number(String(a));
  const numB = typeof b === "number" ? b : Number(String(b));
  const esNumero =
    !Number.isNaN(numA) && !Number.isNaN(numB) && String(a).trim() !== "" && String(b).trim() !== "";
  if (esNumero) return numA - numB;

  const fechaA = Date.parse(String(a));
  const fechaB = Date.parse(String(b));
  if (!Number.isNaN(fechaA) && !Number.isNaN(fechaB) && ISO.test(String(a)) && ISO.test(String(b))) {
    return fechaA - fechaB;
  }

  return String(a).localeCompare(String(b), localizacion(), { numeric: true });
}

const ISO = /^\d{4}-\d{2}-\d{2}/;

/** Las filas en el orden pedido. Sin orden, tal y como vinieron. */
function ordenar(
  filas: Record<string, unknown>[],
  orden: Orden,
): Record<string, unknown>[] {
  if (!orden) return filas;
  // Copia: ordenar en el sitio mutaría lo que trajo quien llama, y esta tabla
  // recibe las filas de un `useState` de la pantalla de arriba.
  const copia = [...filas];
  const signo = orden.sentido === "desc" ? -1 : 1;
  copia.sort((x, y) => {
    const a = x[orden.columna];
    const b = y[orden.columna];
    // Lo que falta se queda al final **en los dos sentidos**, así que se
    // decide antes de aplicar el signo. Invirtiendo el array entero —que es
    // como estaba— los huecos se iban al principio en cuanto se pulsaba por
    // segunda vez, y una columna ordenada que empieza por tres guiones no
    // enseña nada de lo que se pidió.
    const faltaA = !tieneDato(a);
    const faltaB = !tieneDato(b);
    if (faltaA || faltaB) return faltaA && faltaB ? 0 : faltaA ? 1 : -1;
    return signo * comparar(a, b);
  });
  return copia;
}

export function Tabla({
  filas: filasCrudas,
  columnas,
  titulo,
  enlace,
  porDefecto = 6,
  recuerdaComo,
  encabezado,
  acciones,
  antes,
  ocupaLaPantalla = false,
  pegada = false,
  accionesDeFila,
  columnasIniciales,
  ordenInicial,
  esquemaDeCampo,
  alEditarCelda,
}: Props) {
  const { t } = useTranslation();
  const filas = useMemo(() => normalizar(filasCrudas), [filasCrudas]);
  const pedidas = columnas ?? columnasDe(filas);
  // Con dato en alguna fila. Una columna vacía en todas es ruido.
  const disponibles = pedidas.filter((c) =>
    filas.some((fila) => tieneDato(fila[c])),
  );

  const [elegidas, setElegidas] = useState<string[] | null>(
    () => leerElegidas(recuerdaComo) ?? (columnasIniciales?.length ? columnasIniciales : null),
  );
  const [eligiendo, setEligiendo] = useState(false);
  // Por qué columna se ordena, y en qué sentido. `null` es «como vino»: el
  // orden del servidor, que suele ser el relevante —lo más reciente, lo que
  // más urge— y que no hay que perder sólo por ofrecer ordenar.
  const [orden, setOrden] = useState<Orden>(() => leerOrden(recuerdaComo) ?? ordenInicial ?? null);

  // Al cambiar de clave —otra pestaña, otra vista guardada— se vuelve a
  // sembrar: sin esto, abrir una vista con sus propias columnas seguiría
  // enseñando las de la anterior, porque el estado se inicializa una vez.
  useEffect(() => {
    setElegidas(leerElegidas(recuerdaComo) ?? (columnasIniciales?.length ? columnasIniciales : null));
    setOrden(leerOrden(recuerdaComo) ?? ordenInicial ?? null);
    // `columnasIniciales` y `ordenInicial` NO entran en las dependencias: los
    // reconstruye quien llama en cada pintado, así que entrarían siempre y
    // esto pisaría la elección de quien acaba de tocar una columna.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recuerdaComo]);

  function alternarOrden(columna: string) {
    setOrden((previo) => {
      const siguiente: Orden =
        previo?.columna !== columna
          ? { columna, sentido: "asc" }
          : previo.sentido === "asc"
            ? { columna, sentido: "desc" }
            // Tercer clic: se vuelve al orden del servidor. Sin esta vuelta,
            // una vez ordenas no hay forma de recuperar el orden que traía.
            : null;
      guardarOrden(recuerdaComo, siguiente);
      return siguiente;
    });
  }

  // De entrada, las que el recurso declara como preferidas —o las primeras—,
  // no todas: `columnas` llega con las preferidas delante.
  const visibles = useMemo(() => {
    const guardadas = elegidas?.filter((c) => disponibles.includes(c));
    if (guardadas && guardadas.length > 0) return guardadas;
    // Los identificadores técnicos no entran de entrada: una columna de UUID
    // ocupa el ancho de tres columnas útiles y no dice nada. Siguen estando en
    // el selector para quien los necesite.
    const utiles = disponibles.filter((c) => !esIdentificadorTecnico(c));
    return (utiles.length > 0 ? utiles : disponibles).slice(
      0,
      Math.max(1, porDefecto),
    );
  }, [elegidas, disponibles, porDefecto]);

  function alternarColumna(columna: string) {
    const siguientes = visibles.includes(columna)
      ? visibles.filter((c) => c !== columna)
      : [...disponibles.filter((c) => visibles.includes(c) || c === columna)];
    setElegidas(siguientes);
    if (!recuerdaComo) return;
    try {
      localStorage.setItem(
        `${CLAVE_COLUMNAS}.${recuerdaComo}`,
        JSON.stringify(siguientes),
      );
    } catch {
      /* sin almacenamiento: la elección vale para esta sesión */
    }
  }

  const cabeceras = visibles;
  const escondidas = disponibles.length - cabeceras.length;

  // Buscar DENTRO de la lista. Lightning lo tiene en todas y aquí no estaba:
  // con cincuenta filas delante, encontrar «Metalúrgica» obligaba a recorrer
  // la columna a ojo o a montar un filtro por campo.
  //
  // Busca en lo que está CARGADO, y el recuento lo dice —«12 de 50»—: decir
  // «12 elementos» a secas haría creer que no hay más, y lo que no se ha
  // traído no se ha mirado. Ésa es la diferencia entre un buscador y un
  // filtro del servidor, y callarla es lo que convierte una ayuda en una
  // trampa.
  const [busqueda, setBusqueda] = useState("");
  const filasBuscadas = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    if (!q) return filas;
    return filas.filter((f) =>
      Object.values(f).some((v) => tieneDato(v) && String(v).toLowerCase().includes(q)),
    );
  }, [filas, busqueda]);
  const filasOrdenadas = useMemo(() => ordenar(filasBuscadas, orden), [filasBuscadas, orden]);

  const hayQueElegir = disponibles.length > cabeceras.length || elegidas;

  return (
    <div>
      {hayQueElegir || encabezado || acciones ? (
        <div
          className={cn(
            "flex items-center justify-between gap-2",
            pegada
              ? "border-x border-ink-dim/50 bg-paper px-3 py-2"
              : "mb-2",
          )}
        >
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            {encabezado}
            {/* **La línea de Lightning**: cuántos elementos y por qué están
                ordenados. Es información que la tabla ya tiene y que nadie
                enseñaba: con cincuenta filas delante, «¿por qué sale esto
                primero?» es la pregunta inmediata, y se contestaba sólo si uno
                se fijaba en la flecha de la cabecera.

                Va aquí y no en la pantalla porque el orden lo lleva la tabla:
                pedírselo a quien la coloca obligaría a sacar ese estado fuera
                para enseñar un texto. */}
            {ocupaLaPantalla ? (
              <p className="text-3xs text-ink-faint" role="status">
                {busqueda.trim()
                  ? t("tabla.cuantosDeCuantos", {
                      cuantos: filasOrdenadas.length,
                      total: filas.length,
                    })
                  : t("tabla.cuantosElementos", { count: filasOrdenadas.length })}
                {orden ? (
                  <>
                    {" · "}
                    {t(orden.sentido === "asc" ? "tabla.ordenadoAsc" : "tabla.ordenadoDesc", {
                      columna: humanizar(orden.columna),
                    })}
                  </>
                ) : null}
              </p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {ocupaLaPantalla ? (
              <>
                <label className="sr-only" htmlFor="buscar-en-la-lista">
                  {t("tabla.buscarEnLaLista")}
                </label>
                <input
                  id="buscar-en-la-lista"
                  type="search"
                  value={busqueda}
                  onChange={(e) => setBusqueda(e.target.value)}
                  placeholder={t("tabla.buscarEnLaLista")}
                  className="input-base w-48"
                />
              </>
            ) : null}
            {hayQueElegir ? (
              <button
                type="button"
                onClick={() => setEligiendo((v) => !v)}
                aria-expanded={eligiendo}
                className="btn-secondary inline-flex items-center gap-1.5"
              >
                <Icono nombre="view_column" tamano="sm" />
                {t("tabla.columnas", {
                  visibles: cabeceras.length,
                  total: disponibles.length,
                })}
              </button>
            ) : null}
            {acciones}
          </div>
        </div>
      ) : null}

      {eligiendo ? (
        <fieldset className="card mb-2 p-3">
          <legend className="sr-only">{t("tabla.elegirColumnas")}</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {disponibles.map((c) => (
              <label
                key={c}
                className="inline-flex items-center gap-1.5 text-2xs text-ink"
              >
                <input
                  type="checkbox"
                  checked={cabeceras.includes(c)}
                  onChange={() => alternarColumna(c)}
                  className="h-3.5 w-3.5 rounded border-ink-dim accent-accent"
                />
                {humanizar(c)}
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}

      {antes}

      {/* El armazón es el mismo que el de las tablas de forma fija —estado,
          rendimiento, despliegue—: estaba copiado cinco veces y ya había
          empezado a separarse en el tamaño de letra y en el tono de las
          celdas. */}
      {/* Buscar y no encontrar nada se dice. Una tabla con cabecera y sin
          filas se lee como que algo se ha roto, no como que no hay ninguna que
          case — y encima se pierde el único dato que ayuda, que es que SÍ hay
          cincuenta cargadas y ninguna lleva eso. */}
      {busqueda.trim() && filasOrdenadas.length === 0 ? (
        <p
          className={cn(
            "text-2xs text-ink-faint",
            pegada ? "rounded-b border-x border-b border-ink-dim/50 bg-paper px-3 py-6 text-center" : "py-4",
          )}
          role="status"
        >
          {t("tabla.nadaConEso", { que: busqueda.trim(), total: filas.length })}
        </p>
      ) : (
      <Rejilla
        acotada={!ocupaLaPantalla}
        pegada={pegada}
        titulo={titulo}
        cabeceras={[
          ...cabeceras.map((c) => (
          <button
            key={c}
            type="button"
            title={c}
            onClick={() => alternarOrden(c)}
            // `aria-sort` va en la celda, pero la celda la pone `Rejilla`; el
            // botón declara su estado para que un lector de pantalla lo diga
            // al llegar, que es cuando hace falta.
            aria-label={
              orden?.columna === c
                ? t(orden.sentido === "asc" ? "tabla.ordenAsc" : "tabla.ordenDesc", {
                    columna: humanizar(c),
                  })
                : t("tabla.ordenarPor", { columna: humanizar(c) })
            }
            className="inline-flex items-center gap-0.5 hover:text-ink"
          >
            {humanizar(c)}
            {orden?.columna === c ? (
              <Icono
                nombre={orden.sentido === "asc" ? "arrow_upward" : "arrow_downward"}
                tamano="sm"
              />
            ) : null}
          </button>
          )),
          // La columna del menú no lleva rótulo visible —en Lightning tampoco—
          // pero sí nombre accesible: sin él se anuncia como «columna 5» y no
          // dice qué hay dentro.
          ...(accionesDeFila
            ? [
                <span key="__acciones" className="sr-only">
                  {t("tabla.accionesDeFila")}
                </span>,
              ]
            : []),
        ]}
      >
        <>
          {filasOrdenadas.map((fila, i) => (
            <tr
              key={clave(fila, i)}
              className="border-b border-ink-dim/30 last:border-0 hover:bg-paper-light"
            >
              {cabeceras.map((c, columna) => {
                const destino = columna === 0 && enlace ? enlace(fila) : null;
                const editable = esquemaDeCampo?.(c);
                // La primera columna NO se edita en línea: lleva el enlace que
                // abre el registro, y meter un lápiz al lado del nombre pone
                // dos acciones distintas a tres píxeles una de otra.
                if (editable && alEditarCelda && columna > 0) {
                  return (
                    <Casilla key={c} enUnaLinea>
                      <CeldaEditable
                        valor={fila[c]}
                        campo={c}
                        esquema={editable}
                        alGuardar={(v) => alEditarCelda(fila, c, v)}
                      >
                        <Celda valor={fila[c]} campo={c} />
                      </CeldaEditable>
                    </Casilla>
                  );
                }
                return (
                  <Casilla key={c} enUnaLinea>
                    {destino ? (
                      // Enlace de contenido, no de acción: `btn-link` es un
                      // micro-enlace monoespaciado en mayúsculas, y el nombre
                      // de una cuenta puesto ahí deja de parecer un nombre.
                      <Link
                        to={destino}
                        className="text-accent hover:underline"
                      >
                        <Celda valor={fila[c]} campo={c} />
                      </Link>
                    ) : (
                      <Celda valor={fila[c]} campo={c} />
                    )}
                  </Casilla>
                );
              })}
              {accionesDeFila ? (
                <Casilla enUnaLinea>
                  <div className="flex justify-end">
                    <MenuDeAcciones
                      opciones={accionesDeFila(fila)}
                      etiqueta={t("tabla.accionesDeFila")}
                      soloIcono
                      haciaLaIzquierda
                      clase="btn-icon !h-7 !w-7 text-ink-muted hover:bg-paper-light hover:text-ink"
                    />
                  </div>
                </Casilla>
              ) : null}
            </tr>
          ))}
        </>
      </Rejilla>
      )}
      {escondidas > 0 ? (
        <p className="mt-1.5 text-3xs text-ink-faint">
          {t("tabla.masColumnas", { count: escondidas })}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Deja cada fila como un objeto, venga como venga.
 *
 * Una lista de textos —`["competencia", "sin_presupuesto", …]`— es una
 * respuesta perfectamente normal, y aquí llegaba a `Object.keys("competencia")`,
 * que devuelve `["0","1","2",…]`. El resultado era una tabla con una columna
 * **por cada letra** y una letra en cada celda: la pantalla de motivos de
 * pérdida se leía en vertical, carácter a carácter. Información verdadera y
 * completamente inutilizable, que es la peor forma de estar mal.
 */
export function normalizar(filas: unknown[]): Record<string, unknown>[] {
  return filas.map((fila) =>
    fila !== null && typeof fila === "object" && !Array.isArray(fila)
      ? (fila as Record<string, unknown>)
      : { valor: fila },
  );
}

export function columnasDe(filas: Record<string, unknown>[]): string[] {
  const vistas = new Set<string>();
  for (const fila of filas)
    for (const clave of Object.keys(fila)) vistas.add(clave);
  return [...vistas];
}

/**
 * Lo que se pinta en una celda.
 *
 * Devuelve nodos y no texto: un objeto de interruptores se lee como etiquetas
 * —qué está encendido y qué no—, no como `{"procesos":true,"webhooks":true,…`
 * recortado a la mitad. Eso último es información verdadera e inutilizable:
 * nadie lee un JSON de un vistazo, y recortado ni siquiera entero.
 */
export function Celda({ valor, campo }: { valor: unknown; campo: string }) {
  if (!tieneDato(valor)) {
    const vacio =
      Array.isArray(valor) || (typeof valor === "object" && valor !== null);
    // Se distingue «no hay dato» de «la lista está vacía»: parece lo mismo y no
    // lo es —lo primero puede ser un fallo de carga y lo segundo es un hecho—.
    return (
      <span
        className="text-ink-faint"
        title={vacio ? "Lista vacía" : "Sin dato"}
      >
        —
      </span>
    );
  }

  const compuesto =
    Array.isArray(valor) || (valor !== null && typeof valor === "object");
  if (compuesto) {
    const piezas = trozos(valor, campo);
    const visibles = piezas.slice(0, 3);
    return (
      <span className="inline-flex flex-wrap items-center gap-1">
        {visibles.map((t, i) => (
          <span
            key={i}
            className={`chip-dato ${t.apagado ? "chip-dato--no" : "chip-dato--si"}`}
          >
            {t.texto}
          </span>
        ))}
        {piezas.length > visibles.length ? (
          <span
            className="text-3xs text-ink-faint"
            title={piezas.map((t) => t.texto).join(" · ")}
          >
            +{piezas.length - visibles.length}
          </span>
        ) : null}
      </span>
    );
  }

  const texto = escalar(valor, campo);
  if (typeof valor === "string" && UUID.test(valor)) {
    // Ocho caracteres bastan para distinguir dos filas; treinta y seis de
    // hexadecimal no se leen, no se recuerdan y no se comparan de un vistazo.
    return (
      <span className="font-mono text-3xs text-ink-muted" title={valor}>
        {valor.slice(0, 8)}…
      </span>
    );
  }
  return (
    <span title={texto.length > 60 ? texto : undefined}>
      {texto.length > 60 ? `${texto.slice(0, 60)}…` : texto}
    </span>
  );
}

function clave(fila: Record<string, unknown>, i: number): string {
  const id = fila.id ?? fila.codigo ?? fila.clave ?? fila.nombre;
  return typeof id === "string" || typeof id === "number"
    ? String(id)
    : String(i);
}
