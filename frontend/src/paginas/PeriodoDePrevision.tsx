/**
 * Un periodo de previsión: el número, quién lo tocó y por qué se movió
 * (CRM-03.02.01.03, CRM-03.02.01.04, CRM-03.02.01.05, CRM-03.02.01.08), y
 * cómo se reparte por el organigrama: comercial → equipo → región → compañía
 * (CRM-03.02.01.02).
 *
 * El módulo listaba los periodos y ahí se acababa. Y un periodo de previsión
 * es justo lo contrario de una fila: es **un número que alguien defiende en un
 * comité**, y lo que hace falta para defenderlo —quién lo ajustó y con qué
 * motivo, si esos ajustes acercaron o alejaron del real, qué se movió desde la
 * última foto— no se alcanzaba desde ninguna pantalla.
 *
 * Se abre por **clave** y no por identificador, como el objeto del modelo y
 * por lo mismo: sus rutas hijas se dirigen por la clave del periodo, y pasarles
 * el identificador las deja en 404.
 *
 * **Lo que no se ha podido convertir sale aparte y no cuenta como cero.** Un
 * total al que le faltan importes en silencio es peor que uno que avisa,
 * porque nadie lo cuestiona. El servidor lo dice y aquí se pinta pegado al
 * número, no en una esquina.
 *
 * **Y el acierto de los ajustes es el panel incómodo a propósito.** Un
 * responsable que ajusta siempre hacia arriba y acierta menos que el número
 * bruto está empeorando la previsión, y sin esta comparación nadie se entera
 * nunca — porque al cerrar el trimestre se mira el real contra el objetivo, no
 * contra lo que se habría previsto sin tocar.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Acciones } from "@/componentes/Acciones";
import { MenuDeAcciones } from "@/componentes/MenuDeAcciones";
import { CabeceraPagina } from "@/componentes/Pagina";
import { accionesDe, type Accion } from "@/lib/acciones";
import { useSuperficie } from "@/lib/permisos";
import { llamar, salvoCancelacion } from "@/lib/api";
import { importe as comoImporte, rotuloDeOpcion } from "@/lib/formato";
import { nombreDe, usePersonas } from "@/lib/personas";

interface Prevision {
  periodo: string;
  moneda: string;
  total: string;
  ponderado: string;
  compromiso: string;
  oportunidades: number;
  por_categoria: Record<
    string,
    { importe: string; ponderado: string; oportunidades: number }
  >;
  sin_tipo_de_cambio: unknown[];
  aviso: string;
}

interface Ajuste {
  id: string;
  ambito: string;
  categoria: string | null;
  bruto: string;
  ajustado: string;
  delta: string;
  motivo: string;
  por: string | null;
}

interface Acierto {
  medible: boolean;
  motivo?: string;
  real?: string;
  bruto?: string;
  ajustado?: string;
  error_sin_ajuste?: string;
  error_con_ajuste?: string;
}

interface Instantanea {
  id: string;
  etiqueta: string;
  tomada_at: string;
  moneda: string;
  totales: Record<string, string>;
}

interface Deslizamiento {
  periodo: string;
  oportunidades_con_cambio_de_fecha: number;
  empujadas: number;
  dias_empujados: number;
  empujadas_mas_de_una_vez: number;
  detalle: {
    oportunidad_id: string;
    nombre?: string;
    dias_netos: number;
    veces: number;
  }[];
}

interface NodoOrganigrama {
  id: string;
  nombre: string;
  usuario_id: string | null;
  nivel: "comercial" | "equipo" | "region" | "direccion";
  total: string;
  ponderado: string;
  compromiso: string;
  oportunidades: number;
  hijos: NodoOrganigrama[];
}

interface Organigrama {
  fuente: string;
  moneda: string;
  compania: Prevision;
  nodos: NodoOrganigrama[];
  fuera_del_organigrama: {
    usuario_id: string;
    total: string;
    oportunidades: number;
  }[];
  sin_asignar: string;
  sin_dueno: string;
  cuadra: boolean;
  aviso: string;
}

interface Desglose {
  por: string;
  moneda: string;
  grupos: Record<
    string,
    { importe: string; ponderado: string; lineas: number }
  >;
  grupos_sin_tipo_de_cambio: string[];
}

export function PeriodoDePrevision() {
  const { t } = useTranslation();
  const { clave = "" } = useParams();
  /**
   * Lo que se hace con el periodo: ajustar el número, tomar la foto, cerrarlo
   * y reabrirlo (CRM-03.02.01.03, .04, .09).
   *
   * El servidor lo admitía y la pantalla no lo ofrecía: el menú de la fila en
   * «Periodos» sólo traía «Abrir» y «Editar», porque las acciones de un
   * registro con ficha van en su ficha — y esta ficha no tenía ninguna. Visto
   * el 10-11-2026: no había forma de cerrar un trimestre ni de ajustar su
   * número desde el producto. «Jerarquía» no: es una consulta que esta misma
   * pantalla ya pinta.
   */
  const { superficie, tiene } = useSuperficie();
  const [accionAbierta, setAccionAbierta] = useState<Accion | null>(null);
  const acciones = accionesDe(
    superficie,
    "/api/v1/forecast/periodos",
    clave,
    tiene,
  ).filter((a) => a.clave !== "jerarquia");
  // En qué moneda se mira (CRM-03.02.01.07). El servidor convierte con el
  // cambio de la fecha; las monedas que se ofrecen son las que tienen cambio.
  const [moneda, setMoneda] = useState("");
  const [monedas, setMonedas] = useState<string[]>([]);
  useEffect(() => {
    const control = new AbortController();
    void llamar<{ desde_moneda: string; hasta_moneda: string }[]>(
      "/api/v1/monedas/cambios",
      { signal: control.signal },
    )
      .then((r) =>
        setMonedas(
          [
            ...new Set(
              (r.datos ?? []).flatMap((c) => [c.desde_moneda, c.hasta_moneda]),
            ),
          ].sort(),
        ),
      )
      .catch(() => undefined);
    return () => control.abort();
  }, []);
  const [prevision, setPrevision] = useState<Prevision | null>(null);
  const [ajustes, setAjustes] = useState<Ajuste[]>([]);
  const [acierto, setAcierto] = useState<Acierto | null>(null);
  const [fotos, setFotos] = useState<Instantanea[]>([]);
  const [deslizamiento, setDeslizamiento] = useState<Deslizamiento | null>(
    null,
  );
  const [desglose, setDesglose] = useState<Desglose | null>(null);
  const [por, setPor] = useState("familia");
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    // La ruta se escribe ENTERA en cada llamada, no compuesta de una variable.
    // No es repetición por gusto: el gate que exige que toda ruta de la que
    // una pantalla declara la forma esté recorrida por una prueba de servidor
    // lee el código, y de `${base}/ajustes` no puede saber qué ruta es. Un
    // contrato que no se puede leer no se puede vigilar.
    const suya = encodeURIComponent(clave);

    llamar<Prevision>(
      `/api/v1/forecast/periodos/${suya}${moneda ? `?moneda=${moneda}` : ""}`,
      {
        signal: control.signal,
      },
    )
      .then((r) => setPrevision(r.datos))
      .catch(salvoCancelacion(setFallo));

    // Cada panel con su fallo: que no haya ajustes no puede dejar sin ver el
    // número, que es a lo que se entra.
    void llamar<Ajuste[]>(`/api/v1/forecast/periodos/${suya}/ajustes`, {
      signal: control.signal,
    })
      .then((r) => setAjustes(r.datos))
      .catch(() => undefined);
    void llamar<Acierto>(`/api/v1/forecast/periodos/${suya}/acierto-ajustes`, {
      signal: control.signal,
    })
      .then((r) => setAcierto(r.datos))
      .catch(() => undefined);
    void llamar<Instantanea[]>(
      `/api/v1/forecast/periodos/${suya}/instantaneas`,
      {
        signal: control.signal,
      },
    )
      .then((r) => setFotos(r.datos))
      .catch(() => undefined);
    void llamar<Deslizamiento>(
      `/api/v1/forecast/periodos/${suya}/deslizamiento`,
      {
        signal: control.signal,
      },
    )
      .then((r) => setDeslizamiento(r.datos))
      .catch(() => undefined);

    return () => control.abort();
  }, [clave, moneda]);

  useEffect(cargar, [cargar]);

  // Los nombres de las categorías, los del tenant: el bloque pintaba la clave
  // —«commit», «pipeline»— al lado de un «Comprometido» bien escrito.
  const [nombresDeCategoria, setNombresDeCategoria] = useState<
    Record<string, string>
  >({});
  useEffect(() => {
    const control = new AbortController();
    void llamar<{ clave: string; nombre: string }[]>(
      "/api/v1/forecast/categorias",
      { signal: control.signal },
    )
      .then((r) =>
        setNombresDeCategoria(
          Object.fromEntries((r.datos ?? []).map((c) => [c.clave, c.nombre])),
        ),
      )
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  // El desglose se pide aparte porque depende de por qué se agrupa, y cambiar
  // de agrupación no tiene por qué recargar el resto de la pantalla.
  useEffect(() => {
    const control = new AbortController();
    llamar<Desglose>(
      `/api/v1/forecast/periodos/${encodeURIComponent(clave)}/desglose?por=${por}`,
      { signal: control.signal },
    )
      .then((r) => setDesglose(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, [clave, por]);

  if (fallo && !prevision) return <Fallo error={fallo} reintentar={cargar} />;
  if (!prevision) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={prevision.periodo}
        icono="insights"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            {monedas.length > 1 ? (
              <select
                aria-label={t("prevision.moneda")}
                className="input-base !w-auto"
                value={moneda || prevision.moneda}
                onChange={(e) => setMoneda(e.target.value)}
              >
                {monedas.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            ) : (
              <span className="chip-dato">{prevision.moneda}</span>
            )}
            <span className="text-dato text-ink-muted">
              {t("prevision.cuantas", { cuantas: prevision.oportunidades })}
            </span>
          </span>
        }
        acciones={
          acciones.length > 0 ? (
            <MenuDeAcciones
              etiqueta={t("acciones.titulo")}
              opciones={acciones.map((a) => ({
                clave: a.ruta,
                nombre: a.nombre,
                alElegir: () => setAccionAbierta(a),
              }))}
            />
          ) : undefined
        }
      />
      <Acciones
        acciones={acciones}
        servicio="sales"
        abierta={accionAbierta}
        alCambiarAbierta={setAccionAbierta}
        alTerminar={() => cargar()}
      />

      <section className="card mb-4 p-4">
        <p className="text-titulo font-medium text-ink">
          {t("prevision.total", {
            total: comoImporte(prevision.total, prevision.moneda),
            ponderado: comoImporte(prevision.ponderado, prevision.moneda),
          })}
        </p>
        <p className="mt-1 text-dato text-ink-muted">
          {t("prevision.compromiso", {
            valor: comoImporte(prevision.compromiso, prevision.moneda),
          })}
        </p>
        {/* El aviso va PEGADO al número, no en una esquina: un total al que le
            faltan importes en silencio es peor que uno que avisa, porque nadie
            lo cuestiona. */}
        {prevision.aviso ? (
          <p className="mt-2 text-dato text-warning">{prevision.aviso}</p>
        ) : null}

        <ul className="mt-3 divide-y divide-ink-dim/30">
          {Object.entries(prevision.por_categoria).map(([categoria, v]) => (
            <li
              key={categoria}
              className="flex flex-wrap items-baseline gap-x-3 py-1.5"
            >
              <span className="text-dato font-medium text-ink">
                {nombresDeCategoria[categoria] ?? categoria}
              </span>
              <span className="text-dato text-ink-muted">
                {comoImporte(v.importe, prevision.moneda)}
              </span>
              <span className="text-rotulo text-ink-faint">
                {t("prevision.ponderadoCorto", {
                  valor: comoImporte(v.ponderado, prevision.moneda),
                })}
              </span>
              <span className="text-rotulo text-ink-faint">
                {t("prevision.cuantas", { cuantas: v.oportunidades })}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <LosAjustes
          ajustes={ajustes}
          acierto={acierto}
          moneda={prevision.moneda}
        />
        <ElDesglose desglose={desglose} por={por} alCambiar={setPor} />
        <LaJerarquia clave={clave} />
        <LasFotos fotos={fotos} />
        <QueHaCambiado fotos={fotos} />
        <LoQueSeHaDeslizado deslizamiento={deslizamiento} />
      </div>
    </>
  );
}

/**
 * Los ajustes del responsable, y si acertaron (CRM-03.02.01.03).
 *
 * El ajuste solo no dice nada: lo que importa es si acercó al real. Un
 * responsable que ajusta siempre hacia arriba y acierta menos que el número
 * bruto está empeorando la previsión, y nadie se entera porque al cerrar se
 * compara el real con el objetivo, no con lo que se habría previsto sin tocar.
 */
function LosAjustes({
  ajustes,
  acierto,
  moneda,
}: {
  ajustes: Ajuste[];
  acierto: Acierto | null;
  moneda: string;
}) {
  const { t } = useTranslation();
  const mejoro =
    acierto?.medible &&
    Number(acierto.error_con_ajuste) < Number(acierto.error_sin_ajuste);

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("prevision.ajustes")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("prevision.ajustesAyuda")}
      </p>
      {ajustes.length === 0 ? (
        <Vacio titulo={t("prevision.sinAjustes")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {ajustes.map((a) => (
            <li key={a.id} className="py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-3 text-dato">
                <span className="font-medium text-ink">
                  {comoImporte(a.bruto, moneda)} →{" "}
                  {comoImporte(a.ajustado, moneda)}
                </span>
                <span
                  className={
                    Number(a.delta) >= 0
                      ? "chip-dato"
                      : "chip-dato chip-dato--no"
                  }
                >
                  {/* En el formato del resto de la pantalla: salía
                      «2000000.00» al lado de «2.000.000 €». */}
                  {Number(a.delta) > 0 ? "+" : ""}
                  {comoImporte(a.delta, moneda)}
                </span>
                <span className="text-rotulo text-ink-faint">
                  {rotuloDeOpcion(a.ambito)}
                </span>
                {a.categoria ? (
                  <span className="chip-dato">
                    {rotuloDeOpcion(a.categoria)}
                  </span>
                ) : null}
              </div>
              {/* El motivo es la mitad del ajuste: sin él no se puede juzgar. */}
              <p className="text-rotulo text-ink-muted">{a.motivo}</p>
            </li>
          ))}
        </ul>
      )}

      {acierto ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-2">
          <h3 className="text-dato font-medium text-ink">
            {t("prevision.acierto")}
          </h3>
          {!acierto.medible ? (
            <p className="text-rotulo text-ink-faint">{acierto.motivo}</p>
          ) : (
            <>
              <p className="mt-1 text-dato text-ink-muted">
                {t("prevision.contraReal", {
                  real: comoImporte(acierto.real ?? "0", moneda),
                  bruto: comoImporte(acierto.bruto ?? "0", moneda),
                  ajustado: comoImporte(acierto.ajustado ?? "0", moneda),
                })}
              </p>
              <p
                className={
                  mejoro
                    ? "mt-1 text-dato text-success"
                    : "mt-1 text-dato text-danger"
                }
              >
                {mejoro
                  ? t("prevision.ajustarAcerco", {
                      error: comoImporte(acierto.error_con_ajuste, moneda),
                    })
                  : t("prevision.ajustarAlejo", {
                      conAjuste: comoImporte(acierto.error_con_ajuste, moneda),
                      sinAjuste: comoImporte(acierto.error_sin_ajuste, moneda),
                    })}
              </p>
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}

/**
 * Por jerarquía: comercial → equipo → región → compañía (CRM-03.02.01.02).
 *
 * El servidor sabía calcularla desde el principio, pero pedía los nodos ya
 * resueltos —«este equipo son estos tres UUID»— y ninguna pantalla los tenía.
 * Ahora el árbol lo resuelve `sales` con lo que tiene: el **mapa de
 * territorios** o la **jerarquía de mando** que replica de identidad. Aquí se
 * elige cuál y se pinta.
 *
 * **Lo que no cuelga de ninguna rama sale aparte, con su importe y su dueño.**
 * El total de la compañía no se suma de los nodos: se calcula aparte, y la
 * diferencia es el agujero —alguien recién incorporado, una cartera
 * huérfana— que explica por qué las ramas no cuadran.
 */
function LaJerarquia({ clave }: { clave: string }) {
  const { t } = useTranslation();
  const personas = usePersonas();
  const [fuente, setFuente] = useState("territorios");
  const [datos, setDatos] = useState<Organigrama | null>(null);
  const [cargado, setCargado] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    setDatos(null);
    setCargado(false);
    setFallo(null);
    llamar<Organigrama>(
      `/api/v1/forecast/periodos/${encodeURIComponent(clave)}/organigrama?fuente=${fuente}`,
      { signal: control.signal },
    )
      // Una respuesta sin la forma esperada se trata como «sin organigrama»
      // y no tumba la pantalla: el número del periodo, que es a lo que se
      // entra, no puede depender de este panel.
      .then((r) => {
        setDatos(
          r.datos && Array.isArray(r.datos.nodos) && r.datos.compania
            ? r.datos
            : null,
        );
        setCargado(true);
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [clave, fuente]);

  const nombreDelNodo = (n: NodoOrganigrama) =>
    n.nombre || (n.usuario_id ? nombreDe(personas, n.usuario_id) : n.id);

  // Una función que pinta y no un componente: definido aquí dentro, un
  // componente sería un tipo nuevo en cada pintado y React desmontaría el
  // árbol entero cada vez.
  function rama(nodo: NodoOrganigrama, nivel: number) {
    return (
      <li key={nodo.id}>
        <div
          className="flex flex-wrap items-baseline gap-x-3 py-1.5"
          style={{ paddingLeft: `${nivel * 1.25}rem` }}
        >
          <span className="text-dato font-medium text-ink">
            {nombreDelNodo(nodo)}
          </span>
          <span className="chip-dato">
            {t(`prevision.niveles.${nodo.nivel}`)}
          </span>
          <span className="text-dato text-ink-muted">
            {comoImporte(nodo.total, datos?.moneda ?? "")}
          </span>
          <span className="text-rotulo text-ink-faint">
            {t("prevision.ponderadoCorto", {
              valor: comoImporte(nodo.ponderado, datos?.moneda ?? ""),
            })}
          </span>
          <span className="text-rotulo text-ink-faint">
            {t("prevision.cuantas", { cuantas: nodo.oportunidades })}
          </span>
        </div>
        {nodo.hijos.length > 0 ? (
          <ul className="divide-y divide-ink-dim/20">
            {nodo.hijos.map((h) => rama(h, nivel + 1))}
          </ul>
        ) : null}
      </li>
    );
  }

  return (
    <section className="card p-4 lg:col-span-2">
      <h2 className="section-label mb-1">{t("prevision.jerarquia")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("prevision.jerarquiaAyuda")}
      </p>
      <label htmlFor="jerarquia-fuente" className="text-dato text-ink-muted">
        {t("prevision.organigramaDe")}
        <select
          id="jerarquia-fuente"
          value={fuente}
          onChange={(e) => setFuente(e.target.value)}
          className="input-sm ml-2 inline-block w-auto"
        >
          <option value="territorios">{t("prevision.porTerritorios")}</option>
          <option value="mando">{t("prevision.porMando")}</option>
        </select>
      </label>
      {fallo ? (
        <div className="mt-2">
          <Fallo error={fallo} />
        </div>
      ) : !cargado ? (
        <Cargando />
      ) : !datos ? (
        <div className="mt-2">
          <Vacio titulo={t("prevision.sinOrganigrama")} compacto />
        </div>
      ) : (
        <div className="mt-2" role="status">
          <p className="text-dato text-ink">
            {t("prevision.compania", {
              total: comoImporte(datos.compania.total, datos.moneda),
              cuantas: datos.compania.oportunidades,
            })}
          </p>
          {datos.aviso ? (
            <p className="mt-1 text-rotulo text-warning">{datos.aviso}</p>
          ) : null}
          {datos.nodos.length === 0 ? (
            <div className="mt-2">
              <Vacio titulo={t("prevision.sinOrganigrama")} compacto />
            </div>
          ) : (
            <ul className="mt-2 divide-y divide-ink-dim/30">
              {datos.nodos.map((n) => rama(n, 0))}
            </ul>
          )}
          {!datos.cuadra ? (
            <div className="mt-3 border-t border-ink-dim/30 pt-2">
              <p className="text-dato text-warning">
                {t("prevision.fueraDelOrganigrama", {
                  importe: comoImporte(datos.sin_asignar, datos.moneda),
                })}
              </p>
              <ul className="mt-1 divide-y divide-ink-dim/30">
                {datos.fuera_del_organigrama.map((f) => (
                  <li
                    key={f.usuario_id}
                    className="flex flex-wrap items-baseline gap-x-3 py-1.5"
                  >
                    <span className="text-dato text-ink">
                      {nombreDe(personas, f.usuario_id)}
                    </span>
                    <span className="text-dato text-ink-muted">
                      {comoImporte(f.total, datos.moneda)}
                    </span>
                    <span className="text-rotulo text-ink-faint">
                      {t("prevision.cuantas", { cuantas: f.oportunidades })}
                    </span>
                  </li>
                ))}
              </ul>
              {Number(datos.sin_dueno) !== 0 ? (
                <p className="mt-1 text-dato text-ink-muted">
                  {t("prevision.sinDueno", {
                    importe: comoImporte(datos.sin_dueno, datos.moneda),
                  })}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

/**
 * Por producto, por familia o por tipo de ingreso (CRM-03.02.01.08).
 *
 * Lo que no se ha podido convertir se dice **por grupo**: un desglose en el
 * que falta una familia entera por un tipo de cambio que no estaba se lee como
 * «esa familia no vendió nada».
 */
function ElDesglose({
  desglose,
  por,
  alCambiar,
}: {
  desglose: Desglose | null;
  por: string;
  alCambiar: (v: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("prevision.desglose")}</h2>
      <label htmlFor="desglose-por" className="text-dato text-ink-muted">
        {t("prevision.agruparPor")}
        <select
          id="desglose-por"
          value={por}
          onChange={(e) => alCambiar(e.target.value)}
          className="input-sm ml-2 inline-block w-auto"
        >
          <option value="familia">{t("prevision.porFamilia")}</option>
          <option value="producto">{t("prevision.porProducto")}</option>
          <option value="tipo_ingreso">{t("prevision.porTipo")}</option>
        </select>
      </label>
      {!desglose || Object.keys(desglose.grupos).length === 0 ? (
        <div className="mt-2">
          <Vacio titulo={t("prevision.sinDesglose")} compacto />
        </div>
      ) : (
        <ul className="mt-2 divide-y divide-ink-dim/30">
          {Object.entries(desglose.grupos).map(([grupo, v]) => (
            <li
              key={grupo}
              className="flex flex-wrap items-baseline gap-x-3 py-1.5"
            >
              <span className="text-dato font-medium text-ink">{grupo}</span>
              <span className="text-dato text-ink-muted">
                {comoImporte(v.importe, desglose.moneda)}
              </span>
              <span className="text-rotulo text-ink-faint">
                {t("prevision.lineas", { cuantas: v.lineas })}
              </span>
            </li>
          ))}
        </ul>
      )}
      {desglose && desglose.grupos_sin_tipo_de_cambio.length > 0 ? (
        <p className="mt-2 text-rotulo text-warning">
          {t("prevision.gruposSinCambio", {
            grupos: desglose.grupos_sin_tipo_de_cambio.join(", "),
          })}
        </p>
      ) : null}
    </section>
  );
}

/**
 * Las fotos del periodo (CRM-03.02.01.04).
 *
 * Una previsión sin fotos no se puede comparar consigo misma, y «¿cómo
 * íbamos hace tres semanas?» es la pregunta de todos los lunes. Cada foto va
 * con **cuándo se tomó**: una etiqueta sin fecha no sirve para ordenar nada.
 */
function LasFotos({ fotos }: { fotos: Instantanea[] }) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("prevision.fotos")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("prevision.fotosAyuda")}
      </p>
      {fotos.length === 0 ? (
        <Vacio titulo={t("prevision.sinFotos")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {fotos.map((f) => {
            const total = Object.entries(f.totales ?? {})
              .filter(([k]) => !k.startsWith("_"))
              .reduce((n, [, v]) => n + Number(v), 0);
            return (
              <li
                key={f.id}
                className="flex flex-wrap items-baseline gap-x-3 py-1.5"
              >
                <span className="text-dato font-medium text-ink">
                  {f.etiqueta}
                </span>
                <time
                  className="text-rotulo text-ink-faint"
                  dateTime={f.tomada_at}
                >
                  {f.tomada_at.slice(0, 10)}
                </time>
                <span className="text-dato text-ink-muted">
                  {comoImporte(String(total), f.moneda)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

interface Tramo {
  cuantas: number;
  importe?: string;
  delta?: string;
}

interface Salto {
  moneda: string;
  variacion_total: string;
  entradas: Tramo;
  salidas: Tramo;
  ganadas: Tramo;
  perdidas: Tramo;
  deslizadas: Tramo;
  variacion_de_importe: Tramo;
}

/** Las causas, en el orden en que se cuentan en un comité. */
const CAUSAS = [
  "entradas",
  "ganadas",
  "perdidas",
  "salidas",
  "variacion_de_importe",
  "deslizadas",
] as const;

/**
 * Qué ha cambiado entre dos fotos, descompuesto.
 *
 * «Hemos bajado 300.000» no explica nada: puede ser una operación grande
 * perdida, tres que se han ido al trimestre siguiente o importes que bajan, y
 * cada una lleva a una conversación distinta. El servidor separa las causas;
 * aquí se eligen las dos fotos y se pinta cada causa con su número de
 * oportunidades al lado, que es lo que dice si el importe es una o veinte.
 *
 * Salir de la foto no es perderse, y se pinta aparte: mezclarlo inflaría la
 * tasa de pérdida.
 */
function QueHaCambiado({ fotos }: { fotos: Instantanea[] }) {
  const { t } = useTranslation();
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [salto, setSalto] = useState<Salto | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    if (!desde || !hasta || desde === hasta) {
      setSalto(null);
      return;
    }
    const control = new AbortController();
    setFallo(null);
    llamar<Salto>(
      `/api/v1/forecast/waterfall?desde=${encodeURIComponent(desde)}&hasta=${encodeURIComponent(hasta)}`,
      { signal: control.signal },
    )
      .then((r) => setSalto(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [desde, hasta]);

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("prevision.salto")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("prevision.saltoAyuda")}
      </p>
      {/* Con menos de dos fotos no hay nada que comparar, y se dice: un
          panel que no sale no le cuenta a nadie que existe. */}
      {fotos.length < 2 ? (
        <Vacio titulo={t("prevision.saltoFaltanFotos")} compacto />
      ) : null}
      <div className={fotos.length < 2 ? "hidden" : "flex flex-wrap gap-2"}>
        {(
          [
            ["saltoDesde", desde, setDesde],
            ["saltoHasta", hasta, setHasta],
          ] as const
        ).map(([clave, valor, poner]) => (
          <label key={clave} className="text-dato text-ink-muted">
            {t(`prevision.${clave}`)}
            <select
              className="input-base mt-1 w-auto"
              value={valor}
              onChange={(e) => poner(e.target.value)}
            >
              <option value="">—</option>
              {fotos.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.etiqueta} · {f.tomada_at.slice(0, 10)}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      {salto ? (
        <>
          <p className="mt-3 text-dato text-ink">
            {t("prevision.variacion", {
              importe: comoImporte(salto.variacion_total, salto.moneda),
            })}
          </p>
          <ul className="mt-2 divide-y divide-ink-dim/30">
            {CAUSAS.map((causa) => {
              const tramo = salto[causa];
              const cifra = tramo.importe ?? tramo.delta;
              return (
                <li
                  key={causa}
                  className="flex flex-wrap items-baseline gap-x-3 py-1.5"
                >
                  <span className="text-dato text-ink">
                    {t(`prevision.causas.${causa}`)}
                  </span>
                  <span className="chip-dato">
                    {t("prevision.oportunidadesN", { n: tramo.cuantas })}
                  </span>
                  {cifra !== undefined ? (
                    <span className="text-dato text-ink-muted">
                      {comoImporte(cifra, salto.moneda)}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </>
      ) : null}
    </section>
  );
}

/**
 * Cuánto se ha movido el periodo (CRM-03.02.01.05).
 *
 * **Lo que importa no es cuántas se movieron: es cuántas se han movido MÁS DE
 * UNA VEZ.** Una fecha que se empuja dos trimestres seguidos no es un retraso,
 * es una venta que no existe, y en el total de «oportunidades con cambio de
 * fecha» se confunde con la que se movió una semana.
 */
function LoQueSeHaDeslizado({
  deslizamiento,
}: {
  deslizamiento: Deslizamiento | null;
}) {
  const { t } = useTranslation();
  if (!deslizamiento) return null;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("prevision.deslizamiento")}</h2>
      {deslizamiento.oportunidades_con_cambio_de_fecha === 0 ? (
        <Vacio titulo={t("prevision.sinDeslizamiento")} compacto />
      ) : (
        <>
          <p className="text-dato text-ink">
            {t("prevision.empujadas", {
              cuantas: deslizamiento.empujadas,
              dias: deslizamiento.dias_empujados,
            })}
          </p>
          {deslizamiento.empujadas_mas_de_una_vez > 0 ? (
            <p className="mt-1 text-dato text-danger">
              {t("prevision.masDeUnaVez", {
                cuantas: deslizamiento.empujadas_mas_de_una_vez,
              })}
            </p>
          ) : null}
          <ul className="mt-2 divide-y divide-ink-dim/30">
            {deslizamiento.detalle.slice(0, 10).map((d, i) => (
              <li
                key={`${d.nombre ?? ""}-${i}`}
                className="flex flex-wrap items-baseline gap-x-3 py-1.5"
              >
                <Link
                  to={`/m/oportunidades/oportunidad/${d.oportunidad_id}`}
                  className="text-dato text-accent hover:underline"
                >
                  {d.nombre ?? "—"}
                </Link>
                <span className="chip-dato chip-dato--no">
                  {t("prevision.dias", { dias: d.dias_netos })}
                </span>
                {d.veces > 1 ? (
                  <span className="chip-dato chip-dato--no">
                    {t("prevision.veces", { veces: d.veces })}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
