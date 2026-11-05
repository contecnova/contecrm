/**
 * Una pantalla de módulo: listado, alta y ficha, de cualquier recurso.
 *
 * Una sola pantalla para todos los módulos y no treinta escritas a mano. No es
 * pereza: treinta pantallas son treinta sitios donde el mismo fallo se arregla
 * una vez y sigue en las otras veintinueve, y treinta sitios donde alguien
 * olvida la paginación, el aviso de campos retenidos o la clave de
 * idempotencia. Lo que cada módulo declara es **qué** se enseña; el **cómo** es
 * uno solo.
 *
 * Las columnas salen de lo que devuelve la API y los formularios del OpenAPI,
 * así que un campo nuevo en el servicio aparece aquí sin tocar nada.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";

import {
  Cargando,
  Error as Fallo,
  Retenidos,
  Vacio,
} from "@/componentes/Estados";
import { Exportar } from "@/componentes/Exportar";
import {
  Agrupado,
  Etiquetas,
  SelectorVista,
  Tarjetas,
  campoDeAgrupacion,
  esVocabulario,
  vistaPorDefecto,
  vistaRecordada,
  type Vista,
} from "@/componentes/Vistas";
import { Formulario } from "@/componentes/Formulario";
import { Filtros } from "@/componentes/Filtros";
import { Tabla, leerElegidas, leerOrden } from "@/componentes/Tabla";
import {
  borrarVista,
  guardarVista,
  vistaDeEntrada,
  vistasDe,
  type VistaDeLista,
} from "@/lib/vistasDeLista";
import { llamar } from "@/lib/api";
import {
  escalar,
  esIdentificadorTecnico,
  humanizar,
  nombreDelRegistro,
} from "@/lib/formato";
import {
  comoQuery,
  leerFiltros,
  parametroDe,
  type Filtro,
} from "@/lib/filtros";
import {
  admite,
  altaPorClave,
  camposDe,
  contratoDe,
  fichaDe,
  propositoDe,
  type CampoEsquema,
  type Proposito,
} from "@/lib/contrato";
import { Acciones } from "@/componentes/Acciones";
import {
  accionesDeColeccion,
  comoAccionDeFila,
  operacionesDeRegistro,
  type Accion,
} from "@/lib/acciones";
import { FormularioDeEdicion } from "@/componentes/Edicion";
import type { OpcionDeMenu } from "@/componentes/MenuDeAcciones";
import {
  moduloDe,
  objetoDe,
  recursoVisible,
  type Recurso,
} from "@/lib/modulos";
import { pestanaPrincipal, recursosDe } from "@/lib/recursos";
import { puede, type Sesion } from "@/lib/sesion";
import { comoFilas } from "@/paginas/Consola";
import { useSuperficie, useVisibilidad } from "@/lib/permisos";
import { CabeceraDeLista } from "@/componentes/CabeceraDeLista";
import { colorDeModulo, iconoDeGrupo } from "@/lib/navegacion";

/**
 * Los campos del alta por clave: los del cuerpo, con la clave delante.
 *
 * La clave viaja en la URL y **por eso no suele estar en el esquema del
 * cuerpo**, así que hay que añadirla o el formulario no puede decir a qué
 * código se da de alta.
 *
 * **Pero a veces sí está**: `PUT /politicas-acceso/{nombre}` tiene además un
 * `nombre` en el cuerpo. Añadirla sin mirar dejaba dos campos con el mismo
 * `id` en el DOM —dos `#campo-nombre`—, que rompe la etiqueta y el
 * `aria-describedby` y hace que el segundo sea inalcanzable con teclado.
 * Cazado al dar de alta una política el 04-11-2026.
 *
 * Cuando ya está, se usa el del cuerpo y sólo se marca obligatorio: sin
 * valor no se puede construir la URL.
 */
function camposConLaClave(delCuerpo: CampoEsquema[], clave: string): CampoEsquema[] {
  const existente = delCuerpo.find((c) => c.nombre === clave);
  if (existente) {
    return delCuerpo.map((c) => (c.nombre === clave ? { ...c, obligatorio: true } : c));
  }
  return [
    {
      nombre: clave,
      titulo: humanizar(clave),
      tipo: "texto",
      obligatorio: true,
      descripcion: "",
      opciones: [],
      maximo: null,
      formato: "",
      subcampos: [],
      referencia: "",
    } satisfies CampoEsquema,
    ...delCuerpo,
  ];
}

export function Modulo({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  const { ruta = "" } = useParams();
  const [parametros, setParametros] = useSearchParams();
  const modulo = moduloDe(ruta);
  // ── Las vistas de lista guardadas ──────────────────────────────────
  //
  // Una vista es el recorte con nombre de este listado. Los filtros ya viven
  // en la URL, así que aplicar una vista es **poner sus parámetros**: lo que
  // se guarda es exactamente lo que se puede pegar en un chat, y no una
  // segunda forma de decir lo mismo.
  const [vistas, setVistas] = useState<VistaDeLista[]>([]);
  const [vistaActiva, setVistaActiva] = useState<VistaDeLista | null>(null);
  const [guardandoVista, setGuardandoVista] = useState(false);
  const [nombreDeLaVista, setNombreDeLaVista] = useState("");
  const [vistaParaTodos, setVistaParaTodos] = useState(false);
  const [falloDeVista, setFalloDeVista] = useState("");

  // `?r=Cuentas` elige la pestaña. Lo usa el botón «Crear» de la barra para
  // llevar directamente al alta que se ha pedido: sin esto caería en la primera
  // pestaña del módulo, que puede no ser la del recurso que se quiere crear.
  const pedido = parametros.get("r");
  // Sin `?r=`, la pestaña que el módulo DECLARA como suya, no la que esté
  // escrita primero: ese orden lo puso el catálogo y abría «Campañas» en la
  // papelera y «Casos» en un informe que pide fechas antes de enseñar nada.
  const porNombre = recursosDe(ruta ?? "").findIndex(
    (r) => r.nombre === pedido,
  );
  const inicial = porNombre >= 0 ? porNombre : pestanaPrincipal(ruta ?? "");
  const [activo, setActivo] = useState(inicial);
  // El recurso que se está mirando. Hace falta aquí arriba porque las vistas
  // de lista son suyas: una vista guardada en «Cuentas» no tiene sentido en
  // «Visitas», aunque las dos vivan en el mismo módulo.
  const recursoActivo = recursosDe(ruta ?? "")[activo];
  // La clave con la que se recuerdan columnas y orden incluye la VISTA: cada
  // una se mira a su manera, y sin esto abrir «Las mías» devolvía las columnas
  // de «Todo». Sin vista, la clave es la de siempre.
  const recuerdaComo = `${ruta}.${recursoActivo?.nombre ?? ""}${
    vistaActiva ? `.${vistaActiva.id}` : ""
  }`;
  const visibilidad = useVisibilidad();
  /**
   * Las pestañas que esta persona puede abrir, con la papelera al final.
   *
   * Se filtran igual que los módulos del menú, y no se filtraban: al
   * administrador de una empresa se le enseñaba la pestaña «Tenants», que es
   * de quien opera la plataforma, y al abrirla lo único que decía era que no
   * es para él. Ofrecer lo que no se puede hacer obliga a probarlo para
   * descubrirlo, y lo que se descubre es un error.
   *
   * Se conserva el índice original porque es lo que identifica al recurso
   * activo.
   */
  const pestañas = useMemo(
    () =>
      recursosDe(ruta ?? "")
        .map((r, i) => ({ r, i }))
        .filter(({ r }) => recursoVisible(sesion, r, visibilidad))
        // La principal primero y la papelera al final; en medio, el orden del
        // catálogo. Abrir por la pestaña buena y pintarla la cuarta deja a
        // quien mira buscando en cuál está: en «Casos» salía tras tres
        // informes.
        .sort(
          (a, b) =>
            Number(Boolean(a.r.icono)) - Number(Boolean(b.r.icono)) ||
            Number(Boolean(b.r.principal)) - Number(Boolean(a.r.principal)),
        ),
    [ruta, sesion, visibilidad],
  );

  useEffect(() => setActivo(inicial), [ruta, inicial]);

  // La lista de capacidades que enseña este módulo se trae aparte: son 180
  // identificadores que crecen en cada bloque y que sólo se pintan aquí, en un
  // desplegable cerrado. En `modulos.ts` viajaban en el módulo de entrada —el
  // que se descarga antes de pintar nada— porque al marco también le hace
  // falta ese fichero. Si no llega, la cabecera se queda sin la lista y la
  // pantalla funciona igual: es trazabilidad, no contenido.
  const [capacidades, setCapacidades] = useState<readonly string[]>([]);
  useEffect(() => {
    let vigente = true;
    void import("@/lib/capacidades").then((m) => {
      if (vigente) setCapacidades(m.CAPACIDADES_POR_MODULO[ruta ?? ""] ?? []);
    });
    return () => {
      vigente = false;
    };
  }, [ruta]);

  // Si la activa no es visible —porque se llegó con `?r=` a una que no toca, o
  // porque la superficie llegó después—, se cae a la primera que sí lo es.
  useEffect(() => {
    if (pestañas.length > 0 && !pestañas.some(({ i }) => i === activo)) {
      setActivo(pestañas[0]!.i);
    }
  }, [pestañas, activo]);

  // Se piden al cambiar de recurso. Si hay una marcada por defecto, se aplica
  // **sólo cuando la URL no trae ya filtros**: llegar por un enlace con un
  // recorte dentro y que la pantalla lo pisara con la vista de entrada haría
  // inútil compartir un listado filtrado.
  useEffect(() => {
    let vivo = true;
    setVistaActiva(null);
    void vistasDe(recursoActivo?.listar ?? "").then((suyas) => {
      if (!vivo) return;
      setVistas(suyas);
      const entrada = vistaDeEntrada(suyas);
      const yaHayFiltros = [...parametros.keys()].some(
        (k) => k !== "r" && k !== "nuevo",
      );
      if (entrada && !yaHayFiltros) aplicarVista(entrada);
    });
    return () => {
      vivo = false;
    };
    // `parametros` y `aplicarVista` quedan fuera a propósito: esto corre al
    // cambiar de RECURSO, no cada vez que alguien toca un filtro.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recursoActivo?.listar ?? ""]);

  /** Aplicar una vista: sus filtros a la URL, y recordar cuál está puesta. */
  const aplicarVista = useCallback(
    (vista: VistaDeLista | null) => {
      setVistaActiva(vista);
      const siguientes = new URLSearchParams();
      const pestaña = parametros.get("r");
      if (pestaña) siguientes.set("r", pestaña);
      for (const [k, v] of Object.entries(vista?.filtros ?? {})) {
        if (typeof v === "string" || typeof v === "number")
          siguientes.set(k, String(v));
      }
      setParametros(siguientes, { replace: true });
    },
    [parametros, setParametros],
  );

  /** Lo que hay en pantalla ahora mismo, listo para guardarse. */
  const recorteActual = useCallback(() => {
    const filtrosActuales: Record<string, string> = {};
    for (const [k, v] of parametros.entries()) {
      if (k !== "r" && k !== "nuevo") filtrosActuales[k] = v;
    }
    return filtrosActuales;
  }, [parametros]);

  async function guardarLaVista() {
    const nombre = nombreDeLaVista.trim();
    if (!nombre) return;
    setFalloDeVista("");
    try {
      const nueva = await guardarVista({
        recurso: recursoActivo?.listar ?? "",
        nombre,
        filtros: recorteActual(),
        // Las columnas y el orden que hay puestos, para que quien abra esta
        // vista por primera vez la vea como la dejó quien la guardó.
        columnas: leerElegidas(recuerdaComo) ?? [],
        orden: leerOrden(recuerdaComo),
        compartida: vistaParaTodos,
      });
      setVistas((previas) => [...previas, nueva]);
      setVistaActiva(nueva);
      setGuardandoVista(false);
      setNombreDeLaVista("");
      setVistaParaTodos(false);
    } catch (error) {
      setFalloDeVista(error instanceof Error ? error.message : String(error));
    }
  }

  async function borrarLaVista(vista: VistaDeLista) {
    const pregunta = vista.compartida
      ? t("vistas.confirmarBorradoCompartida", { nombre: vista.nombre })
      : t("vistas.confirmarBorrado", { nombre: vista.nombre });
    if (!window.confirm(pregunta)) return;
    try {
      await borrarVista(vista.id);
      setVistas((previas) => previas.filter((v) => v.id !== vista.id));
      if (vistaActiva?.id === vista.id) aplicarVista(null);
    } catch (error) {
      setFalloDeVista(error instanceof Error ? error.message : String(error));
    }
  }

  // Grande: cuando el módulo no existe, este vacío ES la pantalla.
  if (!modulo) return <Vacio />;
  const pestanas_ = recursosDe(ruta ?? "");
  const recurso = pestanas_[activo] ?? pestanas_[0];

  return (
    <>
      {/* La cabecera de un listado, con la forma de Lightning: el módulo
          arriba en pequeño y la pestaña que se está mirando debajo en grande,
          con un desplegable. Antes era un título y una tira de hasta trece
          pestañas que en Explotación caía en dos filas.

          La trazabilidad sigue entera —identificador del catálogo, sección y
          capacidades— y sigue plegada a la derecha. Lo que no vuelve es
          `CRM-07.04.03.07 · sección 1.1` de subtítulo. */}
      <CabeceraDeLista
        icono={iconoDeGrupo(modulo.grupo)}
        color={colorDeModulo(modulo.ruta)}
        modulo={modulo.titulo}
        recursos={pestanas_}
        activo={activo}
        alElegir={setActivo}
        vistas={vistas}
        vistaActiva={vistaActiva}
        alElegirVista={aplicarVista}
        alGuardarVista={() => {
          // Se propone el nombre de la vista que hay puesta: lo normal es
          // guardar una variante de la que se estaba mirando.
          setNombreDeLaVista(
            vistaActiva ? `${vistaActiva.nombre} (copia)` : "",
          );
          setVistaParaTodos(false);
          setFalloDeVista("");
          setGuardandoVista(true);
        }}
        alBorrarVista={(v) => void borrarLaVista(v)}
        // La lista es UNA tarjeta: cabecera, barra y tabla pegadas. Siempre,
        // y lo de debajo se encarga de cerrarla — en tabla lo hace la propia
        // tabla y en las demás vistas el recuadro que las envuelve.
        pegada
        trazabilidad={
          <details className="text-right">
            <summary className="cursor-pointer text-rotulo text-ink-faint">
              {t("modulo.trazabilidad")}
            </summary>
            <p className="mt-1 font-mono text-rotulo text-ink-faint">
              {modulo.capacidad} · {t("modulo.seccion")} {modulo.seccion}
            </p>
            {capacidades.length > 0 ? (
              <ul
                aria-label={t("modulo.capacidades", {
                  count: capacidades.length,
                })}
                className="mt-1 flex max-w-md flex-wrap justify-end gap-x-3 gap-y-1 font-mono text-rotulo text-ink-faint"
              >
                {capacidades.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            ) : null}
          </details>
        }
      />
      {/* Guardar la vista. Es un panel y no un `prompt()` del navegador: hay
          que decidir DOS cosas —cómo se llama y quién la ve— y la segunda es
          la que no se puede preguntar con un cuadro de texto. Una vista
          guardada «para mí» que luego resulta que la ve todo el mundo es la
          clase de sorpresa que hace desconfiar de la función entera. */}
      {guardandoVista ? (
        <div className="card mb-3 border-accent/30 bg-accent/5 p-3">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              void guardarLaVista();
            }}
          >
            <label className="flex min-w-60 flex-col gap-1">
              <span className="label-base">{t("vistas.comoSeLlama")}</span>
              <input
                // El foco se pone al abrir y NO con `autoFocus`: el panel
                // aparece al pulsar, así que el foco va donde se acaba de
                // pedir. `autoFocus` lo pondría también al montar la pantalla,
                // que es otra cosa y es la que molesta.
                ref={(e) => e?.focus()}
                value={nombreDeLaVista}
                onChange={(e) => setNombreDeLaVista(e.target.value)}
                className="input-base"
              />
            </label>
            <label className="mb-1.5 flex items-center gap-2 text-titulin text-ink">
              <input
                type="checkbox"
                checked={vistaParaTodos}
                onChange={(e) => setVistaParaTodos(e.target.checked)}
                className="h-3.5 w-3.5 rounded-sm border-ink-dim accent-accent"
              />
              {t("vistas.paraTodos")}
            </label>
            <button
              type="submit"
              className="btn-primary mb-1"
              disabled={!nombreDeLaVista.trim()}
            >
              {t("modulo.guardar")}
            </button>
            <button
              type="button"
              className="btn-secondary mb-1"
              onClick={() => setGuardandoVista(false)}
            >
              {t("modulo.cancelar")}
            </button>
          </form>
          {falloDeVista ? (
            <p className="mt-2 text-dato text-danger" role="alert">
              {t("vistas.noSeGuardo", { motivo: falloDeVista })}
            </p>
          ) : null}
        </div>
      ) : null}

      {recurso ? (
        /* La `key` NO es decorativa: sin ella React reutiliza esta misma
           instancia al cambiar de módulo o de pestaña, y con ella se quedan
           **el formulario de alta abierto**, el término de búsqueda y el rango
           de fechas de la pantalla anterior.

           Lo que se veía: pulsar «crear» en Cuentas, irse a Casos sin cerrar, y
           seguir en modo alta ahí y en todas las siguientes hasta darle a
           cancelar en alguna. Un formulario que aparece solo encima de otra
           pantalla no se lee como un estado heredado: se lee como un error. */
        <RecursoVista
          key={`${ruta}:${recurso.nombre}`}
          recurso={recurso}
          sesion={sesion}
          ruta={ruta}
          abrirAlta={parametros.get("nuevo") === "1"}
          recuerdaColumnasComo={recuerdaComo}
          columnasDeLaVista={vistaActiva?.columnas}
          ordenDeLaVista={vistaActiva?.orden ?? null}
        />
      ) : (
        <Vacio />
      )}
    </>
  );
}


/**
 * Las listas de la respuesta que NO son el listado principal.
 *
 * Vacío en el caso normal —un array suelto, `items`, o una sola propiedad que
 * sea lista—, que es el de más de doscientas pestañas. Sólo devuelve algo
 * cuando la respuesta trae varias, que es cuando hay algo que enseñar aparte.
 */
export function otrasListas(
  datos: unknown,
  clavePrincipal?: string,
): { clave: string; filas: Record<string, unknown>[] }[] {
  if (!datos || typeof datos !== "object" || Array.isArray(datos)) return [];
  const objeto = datos as Record<string, unknown>;
  if (Array.isArray(objeto.items)) return [];
  const listas = Object.entries(objeto).filter(([, v]) => Array.isArray(v));
  if (listas.length < 2) return [];
  // La principal es la declarada; si no hay declaración, la primera — que es
  // también la que `comoFilas` no sabría elegir, así que al menos lo de abajo
  // se enseña entero mientras alguien decide cuál manda.
  const principal = clavePrincipal || listas[0]?.[0];
  return listas
    .filter(([clave]) => clave !== principal)
    .map(([clave, valor]) => ({
      clave,
      filas: (valor as unknown[]).filter(
        (f): f is Record<string, unknown> => Boolean(f) && typeof f === "object",
      ),
    }))
    .filter((l) => l.filas.length > 0);
}

function RecursoVista({
  recurso: declarado,
  sesion,
  ruta,
  abrirAlta = false,
  recuerdaColumnasComo,
  columnasDeLaVista,
  ordenDeLaVista,
}: {
  recurso: Recurso;
  sesion: Sesion | null;
  ruta: string;
  /** Se llega con el formulario ya abierto desde el botón «Crear». */
  abrirAlta?: boolean;
  /** Con qué clave se recuerdan columnas y orden. La decide la pantalla. */
  recuerdaColumnasComo: string;
  /** Columnas y orden que trae la vista guardada, para sembrar la tabla. */
  columnasDeLaVista?: string[];
  ordenDeLaVista?: { columna: string; sentido: "asc" | "desc" } | null;
}) {
  const { t } = useTranslation();
  /**
   * Qué servicio se está mirando, cuando la misma colección está en varios.
   *
   * Las políticas de retención, los trabajos de fondo o los vocabularios los
   * publica cada servicio en su prefijo. La pestaña apuntaba a uno y se
   * llamaba «Retención»: quien la abría creía ver todas las políticas del
   * sistema y veía las de un servicio. Con el selector, una pestaña enseña
   * todos y ninguno queda escondido.
   */
  const [servicioElegido, setServicioElegido] = useState(
    declarado.por_servicio?.[0] ?? "",
  );
  // Al cambiar de pestaña hay que volver al primero: el componente se
  // reutiliza, y si no, se queda el servicio de la pestaña anterior —que
  // puede ni publicar esta colección— y la pantalla sale en 404.
  useEffect(() => {
    setServicioElegido(declarado.por_servicio?.[0] ?? "");
  }, [declarado]);
  const recurso = useMemo<Recurso>(() => {
    if (!declarado.por_servicio?.length || !servicioElegido) return declarado;
    const poner = (r?: string) => r?.replace(":servicio", servicioElegido);
    return {
      ...declarado,
      servicio: servicioElegido,
      listar: poner(declarado.listar) ?? declarado.listar,
      crear: poner(declarado.crear),
    };
  }, [declarado, servicioElegido]);
  const [filas, setFilas] = useState<Record<string, unknown>[] | null>(null);
  // Las OTRAS listas que trae la misma respuesta.
  //
  // Hay extremos que contestan con varias —«Vencen pronto» trae
  // `vencen_pronto` y `ya_vencidos`; «Transportes», cuatro catálogos—, y la
  // pantalla sólo sabía pintar una tabla. Lo que hacía entonces no era
  // esconderlas: era peor. Pintaba **una fila con el objeto entero**, una
  // columna por propiedad y las filas de verdad apelotonadas en una celda.
  //
  // Medido el 04-11-2026 llamando a las pestañas declaradas: diez caían ahí.
  // Ahora la principal es el listado —con sus filtros, su orden y su
  // exportación— y las demás se pintan debajo, cada una con su nombre. No se
  // pierde ninguna, que es lo que haría declarar sólo una.
  const [listasExtra, setListasExtra] = useState<
    { clave: string; filas: Record<string, unknown>[] }[]
  >([]);
  const [retenidos, setRetenidos] = useState<string[]>([]);
  const [tapados, setTapados] = useState<string[]>([]);
  const [siguiente, setSiguiente] = useState<string | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [campos, setCampos] = useState<CampoEsquema[] | null>(null);
  const navegar = useNavigate();
  const [creando, setCreando] = useState(abrirAlta);
  const [enviando, setEnviando] = useState(false);
  const [parametros, setParametros] = useSearchParams();
  const [termino, setTermino] = useState("");
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  // Los filtros viven en la URL y no en un estado interno: es lo que hace que
  // una lista filtrada se pueda guardar en marcadores, pegar en un chat y
  // recargar sin perderla.
  const filtros = useMemo(
    () => leerFiltros(parametros, recurso?.busqueda?.parametro),
    [parametros, recurso],
  );
  const fijarFiltros = useCallback(
    (nuevos: Filtro[]) => {
      const siguientes = new URLSearchParams();
      // Se conservan los parámetros que gobiernan la pantalla —la pestaña— y
      // se reemplazan los filtros enteros: quitar uno tiene que quitarlo de la
      // URL, no dejarlo con valor vacío, que el servidor interpretaría.
      const pestaña = parametros.get("r");
      if (pestaña) siguientes.set("r", pestaña);
      for (const f of nuevos) siguientes.set(parametroDe(f), f.valor);
      setParametros(siguientes, { replace: true });
    },
    [parametros, setParametros],
  );
  const [proposito, setProposito] = useState<Proposito | null>(null);
  /**
   * La ruta a la que se da de alta, y si la fila se puede abrir.
   *
   * Las dos las dice el contrato, no esta lista: `recurso.crear` solo estaba
   * escrito en 23 de 148 pestañas y `objeto` en 16, así que el resto enseñaba
   * información que no se podía ni crear ni tocar aunque el servidor lo
   * admitiera. Lo que se declara a mano sigue mandando —hay altas que van a una
   * ruta distinta de la que lista—, y lo que no se declara se descubre.
   */
  const [rutaDeAlta, setRutaDeAlta] = useState<string | null>(
    recurso.crear ?? null,
  );
  /**
   * El campo que va en la URL cuando el alta es un `PUT` por clave.
   *
   * Vacío en el caso normal —un `POST` a la colección—. Cuando lo hay, la
   * ruta es una plantilla (`…/riesgos/{codigo}`), el valor sale del
   * formulario y el método es `PUT`.
   */
  const [claveDeAlta, setClaveDeAlta] = useState("");
  /**
   * Con qué campo se abre un registro.
   *
   * Vacío cuando no hay ficha. `id` en el caso normal, pero no siempre: hay
   * recursos que se abren por su **clave** —`/forecast/periodos/{clave}`— y
   * mandarles el identificador daba un 404 al pulsar la fila. Lo dice el
   * contrato en el nombre de su parámetro, así que no hay que declararlo.
   */
  //
  // Empieza vacío y lo pone el contrato, **no** `objeto`. Con el respaldo
  // `objeto ? "id"`, toda pestaña con `objeto` enlazaba sus filas aunque el
  // servidor no publicara cómo leer una: medido el 05-11-2026, seis fichas
  // —usuarios, productos, categorías de caso, planes preventivos, niveles de
  // partner y aprobaciones de activos— abrían en «No existe» o «Method Not
  // Allowed». `objeto` sigue sirviendo para lo suyo: que las referencias a
  // esos registros se resuelvan a nombres.
  const [campoFicha, setCampoFicha] = useState("");
  // La acción o la edición de una fila sin ficha que está abierta. La última
  // elegida se queda para que el «Hecho» con lo que contestó el servidor siga
  // a la vista cuando el formulario se cierra.
  const [accionDeFila, setAccionDeFila] = useState<Accion | null>(null);
  const [ultimaDeFila, setUltimaDeFila] = useState<Accion | null>(null);
  const [filaElegida, setFilaElegida] = useState("");
  const [edicionDeFila, setEdicionDeFila] = useState<{
    ruta: string;
    plantilla: string;
    metodo: "PATCH" | "PUT";
    valores: Record<string, unknown>;
  } | null>(null);
  const panelDeFila = useRef<HTMLDivElement>(null);
  // El formulario sale encima de la tabla y la fila puede estar cuarenta más
  // abajo: sin acercarlo, pulsar «Editar» no parecería hacer nada.
  useEffect(() => {
    if (accionDeFila || edicionDeFila) {
      panelDeFila.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
    }
  }, [accionDeFila, edicionDeFila]);
  /**
   * La ruta de un registro y qué deja cambiar, para mover en el tablero.
   *
   * Se descubren del contrato y no se declaran: una lista a mano de «recursos
   * que se pueden arrastrar» se queda corta al primer recurso nuevo, y
   * entonces el tablero de ése es el único que no deja mover nada sin que haya
   * un motivo.
   */
  const [plantillaFicha, setPlantillaFicha] = useState<string | null>(null);
  const [camposEditables, setCamposEditables] = useState<Set<string>>(
    () => new Set(),
  );
  // El esquema de los campos que el PATCH admite, por nombre. Hace falta para
  // editar en línea: el control de una celda depende del tipo —una lista
  // cerrada es un desplegable y una fecha un calendario—, y eso sólo lo dice
  // el contrato.
  const [esquemaEditable, setEsquemaEditable] = useState<
    Map<string, CampoEsquema>
  >(() => new Map());
  // La clave con la que se recuerdan columnas y orden. La trae la pantalla
  // porque incluye la VISTA de lista, que es suya.
  const recuerdaComo = recuerdaColumnasComo;
  const [vista, setVista] = useState<Vista>(
    () => vistaRecordada(recuerdaComo) ?? "tarjetas",
  );
  /**
   * El valor por defecto se decide cuando llegan los datos, no antes.
   *
   * Tarjetas en todas partes, salvo donde el registro no tiene titular que
   * poner delante —y eso solo se sabe mirando una fila—. Solo se aplica si
   * este usuario **no ha elegido** vista para este recurso: pisarle la
   * elección con un valor calculado es la forma de que su preferencia no sirva
   * para nada. Y no se guarda nada en el almacenamiento del navegador: lo que
   * calcula la pantalla no es una decisión del usuario, y escribirlo haría que
   * el día que cambie el criterio ya nadie lo viera.
   */
  useEffect(() => {
    if (!filas?.length || vistaRecordada(recuerdaComo)) return;
    setVista(vistaPorDefecto());
    // `recuerdaComo` entra en las dependencias porque al cambiar de recurso
    // hay que volver a decidir: el componente se reutiliza entre pantallas.
  }, [filas, recuerdaComo]);

  // Por qué campo agrupar sale de los datos que hay: con un solo valor no hay
  // nada que separar, y con uno distinto por fila serían columnas de una.
  const campoAgrupacion = useMemo(
    () => campoDeAgrupacion(filas ?? []),
    [filas],
  );
  const vocabulario = useMemo(() => esVocabulario(filas ?? []), [filas]);

  /**
   * Mover un registro de columna, que en el tablero es la acción.
   *
   * Sólo existe si el contrato admite cambiar ESE campo de ESE registro: se
   * descubre, no se declara. Cuando no, `Agrupado` no marca nada como
   * arrastrable — un tablero que deja coger una tarjeta y la devuelve a su
   * sitio sin decir por qué se lee como que la aplicación falla.
   *
   * Se pinta antes de que conteste el servidor y **se deshace si falla**. Sin
   * lo primero, la tarjeta se queda donde estaba medio segundo y parece que no
   * ha funcionado; sin lo segundo, la pantalla enseña un estado que la base no
   * tiene, que es peor que el parpadeo.
   */
  /**
   * Cambiar UN campo de UNA fila, sin abrir la ficha.
   *
   * Era `mover`, que sólo sabía cambiar el campo por el que agrupa el tablero.
   * Es exactamente la misma operación —un PATCH de un campo con el cambio
   * pintado antes de que conteste el servidor y deshecho si falla—, así que
   * ahora recibe el campo y sirve para las dos cosas: arrastrar una tarjeta
   * entre columnas y editar una celda en la lista.
   *
   * **El cambio se pinta antes de que conteste el servidor** y se deshace si
   * falla. Lo contrario es que la tarjeta se quede en su sitio medio segundo
   * después de soltarla, y eso se lee como que no ha cogido el gesto.
   */
  const editarCampo = useMemo(() => {
    if (!plantillaFicha) return undefined;
    const parametro = plantillaFicha.match(/\{([a-z_]+)\}$/)?.[1] ?? "";
    const campoClave = !parametro
      ? "id"
      : /(^|_)id$/.test(parametro)
        ? "id"
        : parametro;
    return async (
      fila: Record<string, unknown>,
      campo: string,
      valor: unknown,
    ) => {
      if (!camposEditables.has(campo)) return;
      const clave = fila[campoClave] ?? fila.id;
      if (typeof clave !== "string") return;
      const antes = fila[campo];
      const mismo = (f: Record<string, unknown>) =>
        (f[campoClave] ?? f.id) === clave;
      setFilas((actuales) =>
        (actuales ?? []).map((f) => (mismo(f) ? { ...f, [campo]: valor } : f)),
      );
      try {
        await llamar(
          plantillaFicha.replace(/\{[a-z_]+\}$/, encodeURIComponent(clave)),
          {
            metodo: "PATCH",
            cuerpo: { [campo]: valor },
          },
        );
      } catch (error) {
        setFilas((actuales) =>
          (actuales ?? []).map((f) =>
            mismo(f) ? { ...f, [campo]: antes } : f,
          ),
        );
        throw error;
      }
    };
  }, [plantillaFicha, camposEditables]);

  // El tablero sigue pidiendo lo suyo: mover por el campo de agrupación.
  const mover = useMemo(() => {
    if (
      !editarCampo ||
      !campoAgrupacion ||
      !camposEditables.has(campoAgrupacion)
    ) {
      return undefined;
    }
    return (fila: Record<string, unknown>, valor: string) =>
      editarCampo(fila, campoAgrupacion, valor);
  }, [editarCampo, campoAgrupacion, camposEditables]);
  /**
   * Número de la última petición lanzada.
   *
   * Escribir en el buscador lanza una por pulsación, y llegan desordenadas.
   * Sin esto, la respuesta de «T» pisaba a la de «Tr»: lo visible era el
   * resultado de lo que ya no estaba escrito, y si la vieja fallaba se quedaba
   * un «Algo ha ido mal» al lado del «Cargando…» de la nueva, que es lo que
   * se veía en pantalla.
   */
  const peticion = useRef(0);

  // Se decide ANTES de pedir nada. Estaba después de los efectos, así que la
  // pantalla pedía igualmente la lista, recibía un 403 y lo pintaba como un
  // error del sistema: el usuario veía algo roto donde lo que pasa es que no le
  // toca. Y `solo_plataforma` no es un permiso —el administrador de una empresa
  // tiene `tenant:read` y aun así recibe 403—, por eso va aparte.
  const puedeVer =
    puede(sesion, recurso.permiso) &&
    (!recurso.solo_plataforma || Boolean(sesion?.es_admin_plataforma));

  // Las acciones sobre la colección entera: las que deduce el contrato más las
  // declaradas a mano —que son las excepciones, no la norma—. Si una sale por
  // las dos vías manda la escrita, que lleva su frase de ayuda.
  const { superficie } = useSuperficie();
  const accionesDeLaColeccion = useMemo(() => {
    const aMano = recurso.acciones ?? [];
    const escritas = new Set(aMano.map((a) => a.ruta));
    const descubiertas = accionesDeColeccion(
      superficie,
      recurso.listar,
      (permiso) => puede(sesion, permiso),
    )
      .filter((a) => !escritas.has(a.ruta))
      // Y las que la pestaña calla porque hay una pantalla que las hace bien.
      .filter((a) => !(recurso.acciones_ocultas ?? []).includes(a.ruta));
    // Las escritas a mano se llevan a la misma forma que las deducidas, para
    // que las pinte un solo componente. Antes eran dos mecanismos: el de la
    // ficha, que sabe abrir el formulario de una acción, y uno propio de esta
    // pantalla que sólo sabía pulsar. Por eso aquí no había formularios.
    const aManoComoAccion: Accion[] = aMano.map((a) => ({
      ruta: a.ruta,
      plantilla: a.ruta,
      metodo: "POST",
      nombre: a.nombre,
      permiso: a.permiso ?? null,
      clave: a.ruta.split("/").pop() ?? "",
      detalle: a.detalle,
    }));
    return [...aManoComoAccion, ...descubiertas];
  }, [superficie, recurso.acciones, recurso.acciones_ocultas, recurso.listar, sesion]);

  // Solo se enlaza lo que TIENE ficha: un enlace que lleva a una pantalla
  // vacía es peor que no tener enlace, porque parece que algo se ha roto.
  // Un listado derivado puede hablar de un registro que vive en otro módulo:
  // «documentos que vencen» son documentos de un proveedor, y lo que hay que
  // hacer con ellos se hace en la ficha del proveedor. Sin esto la fila no
  // llevaba a ninguna parte — se veía el problema y no había por dónde ir.
  const aOtroModulo = recurso.abre;
  const aLaFicha = aOtroModulo
    ? (fila: Record<string, unknown>) => {
        const destino = fila[aOtroModulo.campo];
        return typeof destino === "string"
          ? `/m/${aOtroModulo.modulo}/${aOtroModulo.objeto}/${destino}`
          : null;
      }
    : campoFicha
      ? (fila: Record<string, unknown>) => {
          // Un parámetro con nombre propio que la fila no trae es su clave:
          // `/almacen/tablas/{tabla}` se lee por la clave de la tabla, y caer al
          // `id` —como hacía— daba un 404 al pulsar cualquier fila.
          const clave = fila[campoFicha] ?? fila.clave ?? fila.id;
          return typeof clave === "string"
            ? `/m/${ruta}/${objetoDe(recurso)}/${encodeURIComponent(clave)}`
            : null;
        }
      : undefined;

  // Lo que se hace con una fila **sin ficha**: sus acciones, editarla y
  // quitarla, desde su propio menú. Ver `operacionesDeRegistro`.
  const sinFicha = !aLaFicha;
  const deLaFila = useMemo(
    () =>
      sinFicha
        ? operacionesDeRegistro(superficie, recurso.listar, (p) => puede(sesion, p))
        : null,
    [sinFicha, superficie, recurso.listar, sesion],
  );
  function opcionesDeLaFila(fila: Record<string, unknown>): OpcionDeMenu[] {
    if (!deLaFila) return [];
    const valor = fila[deLaFila.campo];
    if (typeof valor !== "string" && typeof valor !== "number") return [];
    const clave = String(valor);
    // Sin campo de nombre —una sesión no se llama de ninguna manera—, sus dos
    // primeros textos que no sean identificadores: «127.0.0.1 · Firefox» dice
    // cuál es; un UUID no.
    const nombre =
      nombreDelRegistro(fila) ||
      Object.entries(fila)
        .filter(([c, v]) => typeof v === "string" && v && !esIdentificadorTecnico(c))
        .slice(0, 2)
        .map(([, v]) => String(v))
        .join(" · ") ||
      clave;
    const elegir = (accion: Accion) => () => {
      setFilaElegida(nombre);
      setEdicionDeFila(null);
      setUltimaDeFila(accion);
      setAccionDeFila(accion);
    };
    const opciones: OpcionDeMenu[] = deLaFila.acciones.map((op) => {
      const accion = comoAccionDeFila(op, clave);
      return { clave: accion.plantilla, nombre: accion.nombre, alElegir: elegir(accion) };
    });
    const editar = deLaFila.editar;
    if (editar) {
      opciones.unshift({
        clave: "__editar",
        nombre: t("modulo.editar"),
        alElegir: () => {
          setFilaElegida(nombre);
          setAccionDeFila(null);
          setEdicionDeFila({
            ruta: comoAccionDeFila(editar, clave).ruta,
            plantilla: editar.ruta,
            metodo: editar.metodo.toUpperCase() === "PUT" ? "PUT" : "PATCH",
            valores: fila,
          });
        },
      });
    }
    if (deLaFila.quitar) {
      // Con el nombre que le da el contrato, como en la ficha: «Revocar una
      // clave», «Cerrar una sesión», «Levantar una supresión».
      const accion = comoAccionDeFila(deLaFila.quitar, clave);
      opciones.push({
        clave: "__quitar",
        nombre: accion.nombre,
        destructiva: true,
        alElegir: elegir(accion),
      });
    }
    return opciones;
  }

  const busqueda = recurso.busqueda;
  const terminoValido =
    !busqueda || termino.trim().length >= (busqueda.minimo ?? 1);
  // Un informe de periodo exige las dos fechas. No se inventa un rango por
  // defecto: el número que alguien copia a un correo tiene que ser de un
  // periodo que eligió alguien.
  const periodo = recurso.periodo === true;
  const rangoValido =
    !periodo || (desde !== "" && hasta !== "" && desde <= hasta);

  const cargar = useCallback(
    async (cursor?: string) => {
      if (!puedeVer) return;
      // Un recurso de búsqueda no se pide sin término: la API contesta 422 y la
      // pantalla enseñaría un error donde lo que falta es que alguien escriba.
      if (busqueda && !terminoValido) {
        setFilas(null);
        return;
      }
      if (periodo && !rangoValido) {
        setFilas(null);
        return;
      }
      const mia = (peticion.current += 1);
      setFallo(null);
      try {
        const partes: string[] = [];
        if (busqueda)
          partes.push(
            `${busqueda.parametro}=${encodeURIComponent(termino.trim())}`,
          );
        if (periodo) partes.push(`desde=${desde}`, `hasta=${hasta}`);
        // Los filtros van en la petición, no se aplican sobre lo recibido.
        // Filtrar en el navegador obliga a traerse todas las filas para
        // enseñar diez —y con paginación por cursor, además, miente: filtra
        // sólo la página que ya se había traído.
        const consulta = comoQuery(filtros);
        if (consulta) partes.push(consulta);
        if (cursor) partes.push(`cursor=${encodeURIComponent(cursor)}`);
        const separador = recurso.listar.includes("?") ? "&" : "?";
        const ruta = partes.length
          ? `${recurso.listar}${separador}${partes.join("&")}`
          : recurso.listar;
        const respuesta = await llamar<unknown>(ruta);
        if (mia !== peticion.current) return;
        const nuevas = comoFilas(respuesta.datos, recurso.clave_lista);
        setListasExtra(otrasListas(respuesta.datos, recurso.clave_lista));
        // Se ACUMULA al paginar: sustituir haría que «cargar más» pareciera
        // saltar de página, y la lista perdería lo que el usuario ya miraba.
        setFilas((previas) =>
          cursor && previas ? [...previas, ...nuevas] : nuevas,
        );
        setRetenidos(respuesta.retenidos);
        setTapados(respuesta.enmascarados);
        const cuerpo = respuesta.datos as { siguiente?: string | null } | null;
        setSiguiente(
          cuerpo && typeof cuerpo === "object"
            ? (cuerpo.siguiente ?? null)
            : null,
        );
      } catch (error) {
        // El fallo de una petición ya superada no se enseña: sería un error
        // sobre algo que el usuario ya no está pidiendo.
        if (mia === peticion.current) setFallo(error);
      }
    },
    [
      recurso.listar,
      // Una cadena, así que no cambia de identidad en cada pintado: entra sin
      // el riesgo de la función nueva que dispara una petición por tecla.
      recurso.clave_lista,
      puedeVer,
      busqueda,
      termino,
      terminoValido,
      periodo,
      rangoValido,
      desde,
      hasta,
      filtros,
    ],
  );

  useEffect(() => {
    setFilas(null);
    setSiguiente(null);
    void cargar();
  }, [cargar]);

  // Para qué sirve esta pestaña, dicho por el servicio dueño. Una que se llama
  // «Duplicados» y enseña una caja de búsqueda no dice qué hace, y probarla
  // para averiguarlo da miedo cuando la pestaña de al lado es «Papelera».
  useEffect(() => {
    let vivo = true;
    setProposito(null);
    void contratoDe(recurso.servicio).then((documento) => {
      if (!vivo) return;
      // Con el nombre de la pestaña: el propósito sólo se pinta si dice
      // algo que ese rótulo no diga ya. 62 de los 214 resúmenes de esta
      // instalación eran «Listar <el nombre de la pestaña>».
      setProposito(
        propositoDe(documento, recurso.listar, "get", recurso.nombre),
      );
      // El alta: la declarada si la hay, y si no la de la propia ruta que
      // lista, que es donde la pone el servidor salvo excepción.
      // El alta: la declarada si la hay, y si no la de la propia ruta que
      // lista, que es donde la pone el servidor salvo excepción.
      //
      // **Y si no hay `POST`, el `PUT` por clave.** Hay colecciones que se
      // escriben con `PUT /coleccion/{codigo}` —riesgos, controles, reglas de
      // segregación—: sin esto salían sin botón de alta aunque el servidor
      // las admitiera, y la que lo declaraba a mano salía con botón y un
      // formulario VACÍO, porque no hay `POST` del que sacar los campos.
      const declarada = recurso.crear ?? null;
      const porPost = admite(documento, recurso.listar, "post") ? recurso.listar : null;
      const porClave =
        declarada?.includes("{") || (!declarada && !porPost)
          ? altaPorClave(documento, recurso.listar)
          : null;
      const alta = porClave?.plantilla ?? declarada ?? porPost;
      setRutaDeAlta(alta);
      setClaveDeAlta(porClave?.clave ?? "");
      setCampos(
        alta
          ? porClave
            ? camposConLaClave(camposDe(documento, alta, "put"), porClave.clave)
            : camposDe(documento, alta, "post")
          : null,
      );
      // La ficha: basta con que el contrato tenga la operación de un registro.
      // Se enlaza aunque solo se pueda leer, porque casi todo lo que se hace
      // con un registro —acciones, líneas, adjuntos, la conversación— cuelga de
      // la ficha y sin abrirla no se alcanza nada de eso.
      const plantillaFicha = fichaDe(documento, recurso.listar);
      setPlantillaFicha(plantillaFicha);
      // Lo que el PATCH del registro admite. Si el campo por el que se agrupa
      // no está, el tablero no deja arrastrar: ofrecer un gesto que el
      // servidor va a rechazar es peor que no ofrecerlo.
      const editables = plantillaFicha
        ? camposDe(documento, plantillaFicha, "patch")
        : [];
      setCamposEditables(new Set(editables.map((c) => c.nombre)));
      setEsquemaEditable(new Map(editables.map((c) => [c.nombre, c])));
      const parametro = plantillaFicha?.match(/\{([a-z_]+)\}$/)?.[1] ?? "";
      // `{cuenta_id}` es el identificador de siempre; `{clave}` es otro campo
      // de la fila, y hay que mandar ese.
      const campo = !parametro
        ? ""
        : /(^|_)id$/.test(parametro)
          ? "id"
          : parametro;
      setCampoFicha(campo);
    });
    return () => {
      vivo = false;
    };
  }, [
    recurso.servicio,
    recurso.listar,
    recurso.crear,
    recurso.objeto,
    recurso.nombre,
  ]);

  if (!puedeVer) {
    // Con el mismo lenguaje que el resto de estados. Una línea de texto suelta
    // en medio de la pantalla se lee como un fallo a medias; un recuadro con su
    // icono se lee como lo que es: aquí no te toca entrar.
    return (
      <Vacio
        icono="lock"
        titulo={
          recurso.solo_plataforma
            ? t("errores.soloPlataforma")
            : t("errores.sinPermiso")
        }
        detalle={
          recurso.solo_plataforma
            ? t("errores.soloPlataformaDetalle")
            : t("errores.sinPermisoDetalle")
        }
      />
    );
  }

  async function crear(valores: Record<string, unknown>) {
    setEnviando(true);
    try {
      // Con clave, el alta es un `PUT` a la ruta con el código puesto, y el
      // código **no viaja en el cuerpo**: el servidor lo lee de la URL y
      // mandarlo dos veces es pedirle que decida cuál vale.
      const { ruta, cuerpo, metodo } = claveDeAlta
        ? {
            ruta: rutaDeAlta!.replace(
              `{${claveDeAlta}}`,
              encodeURIComponent(String(valores[claveDeAlta] ?? "")),
            ),
            // La clave se quita del cuerpo **sólo si el cuerpo no la pide**.
            // Quitarla siempre dejaba un 422 en las rutas que la declaran en
            // los dos sitios, como `politicas-acceso/{nombre}`.
            cuerpo: (campos ?? []).some((c) => c.nombre === claveDeAlta)
              ? valores
              : Object.fromEntries(
                  Object.entries(valores).filter(([k]) => k !== claveDeAlta),
                ),
            metodo: "PUT",
          }
        : { ruta: rutaDeAlta!, cuerpo: valores, metodo: "POST" };
      await llamar(ruta, { metodo, cuerpo });
      setCreando(false);
      await cargar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  // El botón de alta y su formulario, definidos una vez y colocados por las
  // dos barras de herramientas —la que pinta la tabla y la de las demás
  // vistas—, porque son el mismo control y tienen que estar en el mismo sitio.
  //
  // Antes el botón tenía una fila para él solo encima de todo: 52 px en las 53
  // pantallas que pintan listas, medidos a 1440×900, para un control que cabe
  // de sobra en la barra que ya existe.
  //
  // Cuando la lista está vacía el botón NO sale: lo ofrece el propio estado
  // vacío, y dos botones iguales a diez centímetros uno de otro hacen dudar de
  // si son lo mismo.
  const botonDeAlta =
    rutaDeAlta && (creando || (filas !== null && filas.length > 0)) ? (
      <button
        type="button"
        onClick={() => setCreando((v) => !v)}
        className={creando ? "btn-secondary" : "btn-primary"}
      >
        {creando ? t("modulo.cancelar") : t("modulo.nuevo")}
      </button>
    ) : null;

  const formularioDeAlta =
    creando && campos ? (
      <div className="mb-4 rounded-xl border border-ink-dim/60 bg-paper p-4">
        <Formulario
          fallo={fallo}
          recurso={recurso}
          campos={campos}
          enviando={enviando}
          textoEnviar={t("modulo.guardar")}
          alEnviar={(v) => void crear(v)}
        />
      </div>
    ) : null;

  // La cabecera de la lista va pegada a lo de abajo, así que lo de abajo
  // tiene que CERRAR la tarjeta. Con la tabla lo hace ella; en las demás
  // vistas —tarjetas, columnas, un vocabulario, el estado vacío o un error—
  // hace falta este recuadro, o la cabecera se queda abierta por abajo y
  // parece recortada.
  const enTabla = vista === "tabla" && !vocabulario && (filas?.length ?? 0) > 0;

  return (
    <div
      className={
        enTabla
          ? ""
          : "rounded-b border-x border-b border-ink-dim/50 bg-paper p-3 shadow-elevation-1"
      }
    >
      {proposito?.resumen ? (
        <div className="mb-4 max-w-3xl">
          <p className="text-titulin text-ink">{proposito.resumen}</p>
          {proposito.detalle ? (
            <p className="mt-0.5 text-dato text-ink-faint">
              {proposito.detalle}
            </p>
          ) : null}
        </div>
      ) : null}

      {busqueda ? (
        <div className="mb-4 max-w-md">
          <label htmlFor="modulo-busqueda" className="label-base">
            {busqueda.etiqueta}
          </label>
          <input
            id="modulo-busqueda"
            value={termino}
            onChange={(e) => setTermino(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void cargar();
              }
            }}
            onBlur={() => void cargar()}
            className="input-base"
          />
        </div>
      ) : null}

      {periodo ? (
        <div className="mb-4 flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1">
            <span className="label-base">{t("modulo.desde")}</span>
            <input
              type="date"
              value={desde}
              onChange={(e) => setDesde(e.target.value)}
              className="input-base"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="label-base">{t("modulo.hasta")}</span>
            <input
              type="date"
              value={hasta}
              onChange={(e) => setHasta(e.target.value)}
              className="input-base"
            />
          </label>
        </div>
      ) : null}

      {/* El selector de servicio, arriba y antes de los datos: lo que se ve
          debajo es de UNO, y enseñarlo sin decir de cuál es lo que hacía creer
          que era de todos. Mismo sitio y misma forma que en «Plataforma», que
          tiene el mismo problema y lo resuelve igual. */}
      {declarado.por_servicio?.length ? (
        <label className="mb-3 flex items-center gap-2 text-dato text-ink-muted">
          {t("modulo.servicio")}
          <select
            className="input-base"
            value={servicioElegido}
            onChange={(e) => setServicioElegido(e.target.value)}
          >
            {declarado.por_servicio.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {/* Las medidas que acompañan al listado, arriba: el gasto del mes encima
          del consumo, la calidad de los borradores encima de los borradores.
          Es donde se preguntan. */}
      {recurso.resumen?.length ? <Medidas rutas={recurso.resumen} /> : null}

      {accionesDeLaColeccion.length ? (
        <Acciones
          acciones={accionesDeLaColeccion}
          servicio={recurso.servicio}
          alTerminar={() => void cargar()}
        />
      ) : null}

      {fallo ? <Fallo error={fallo} reintentar={() => void cargar()} /> : null}

      {busqueda && !terminoValido ? (
        <p className="text-dato text-ink-faint" role="status">
          {t("modulo.escribeParaBuscar", { minimo: busqueda.minimo ?? 1 })}
        </p>
      ) : periodo && !rangoValido ? (
        <p className="text-dato text-ink-faint" role="status">
          {t(desde && hasta ? "modulo.rangoAlReves" : "modulo.eligePeriodo")}
        </p>
      ) : filas === null ? (
        <Cargando />
      ) : filas.length === 0 ? (
        // El vacío ofrece lo único que se puede hacer aquí: dar de alta el
        // primero. Un recuadro que solo dice «no hay nada» deja a quien mira en
        // el mismo sitio en el que estaba.
        // Con la lista vacía no hay barra de herramientas donde poner el
        // botón, así que el formulario se pinta aquí y con su «Cancelar»
        // delante: sin él, abrir el alta desde el estado vacío dejaba sin
        // salida — el único botón que lo cerraba vivía en la barra que esta
        // rama no pinta.
        <>
          {creando ? <div className="mb-3">{botonDeAlta}</div> : null}
          {formularioDeAlta}
          {creando ? null : (
            <Vacio
              icono="inbox"
              titulo={t("modulo.sinRegistros")}
              detalle={
                rutaDeAlta
                  ? t("modulo.sinRegistrosDetalle")
                  : t("vacio.detalle")
              }
              accion={
                rutaDeAlta && campos
                  ? {
                      texto: t("modulo.nuevo"),
                      alPulsar: () => setCreando(true),
                    }
                  : undefined
              }
            />
          )}
        </>
      ) : (
        <>
          {/* Los controles van a la derecha, que es donde los pone todo el
              mercado y por tanto donde se buscan, y en **una sola fila**: el de
              columnas primero y el de vista a su derecha, siempre en ese orden.
              En la vista de tabla los pinta la propia tabla, porque el botón de
              columnas es suyo; aquí solo cuando no hay tabla. */}
          {/* Los filtros, encima de todo y siempre visibles. Un panel lateral
              tapa justo lo que se está filtrando, y uno escondido tras un botón
              hace que nadie sepa que hay un recorte puesto — que es cómo se
              acaba discutiendo un número calculado sobre media lista.

              No se enseñan en un vocabulario: son nueve palabras, y filtrar
              nueve palabras es más trabajo que leerlas. */}
          {/* En la vista de tabla los filtros van en SU barra de herramientas
              (ver abajo). Aquí sólo para las demás vistas, que no la tienen. */}
          {vocabulario || vista === "tabla" ? null : (
            <Filtros
              campos={ordenar(filas, recurso.columnas)}
              filas={filas}
              puestos={filtros}
              alCambiar={fijarFiltros}
            />
          )}
          {vista === "tabla" && !vocabulario ? null : (
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-3">
                {botonDeAlta}
                <p className="text-rotulo text-ink-faint" role="status">
                  {t("modulo.filasCargadas", { cuantas: filas.length })}
                </p>
              </div>
              {/* Sin selector para un vocabulario: no hay tres formas de mirar
                  nueve palabras. */}
              {vocabulario ? null : (
                <span className="flex items-center gap-2">
                  {/* Con los filtros puestos: exportar «todo» cuando en
                      pantalla hay un recorte es la forma de que alguien mande
                      un fichero con mucho más de lo que creía. */}
                  <Exportar
                    listar={recurso.listar}
                    nombre={recurso.nombre}
                    consulta={comoQuery(filtros)}
                  />
                  <SelectorVista
                    vista={vista}
                    alCambiar={setVista}
                    recuerdaComo={recuerdaComo}
                    puedeAgrupar={Boolean(campoAgrupacion)}
                  />
                </span>
              )}
            </div>
          )}
          {/* En la vista de tabla lo coloca la propia tabla, por su ranura
              `antes`: su barra de herramientas la pinta ella. */}
          {vista === "tabla" && !vocabulario ? null : formularioDeAlta}
          {vocabulario ? (
            <Etiquetas filas={filas} />
          ) : vista === "agrupado" && campoAgrupacion ? (
            <Agrupado
              filas={filas}
              campo={campoAgrupacion}
              columnas={recurso.columnas}
              enlace={aLaFicha}
              mover={mover}
            />
          ) : vista === "tarjetas" ? (
            <Tarjetas
              filas={filas}
              columnas={recurso.columnas}
              enlace={aLaFicha}
            />
          ) : (
            <Tabla
              filas={filas}
              columnas={ordenar(filas, recurso.columnas)}
              titulo={recurso.nombre}
              // Las preferidas del recurso mandan de entrada; si no declara
              // ninguna, las seis primeras. Y la elección se recuerda por
              // recurso: las columnas útiles de cuentas no son las de casos.
              porDefecto={recurso.columnas?.length || 6}
              recuerdaComo={recuerdaComo}
              // Solo se enlaza lo que TIENE ficha: un enlace que lleva a una
              // pantalla vacía es peor que no tener enlace, porque el usuario
              // cree que se ha roto algo.
              enlace={aLaFicha}
              encabezado={
                <div className="flex min-w-0 flex-wrap items-center gap-3">
                  {botonDeAlta}
                  {/* El recuento ya no se pone aquí: lo pinta la tabla, junto
                      al orden, porque el orden sólo lo sabe ella y los dos
                      datos contestan la misma pregunta —qué estoy viendo y en
                      qué orden—. Repetirlo aquí era decirlo dos veces. */}
                  {/* Los filtros, en la MISMA fila que el resto de controles.
                      Tenían una banda propia encima, así que entre la cabecera
                      y la primera fila había tres bandas para tres controles.
                      Siguen siempre visibles, que era su razón de ser: uno
                      escondido tras un botón hace que nadie sepa que hay un
                      recorte puesto. */}
                  {vocabulario ? null : (
                    <Filtros
                      campos={ordenar(filas, recurso.columnas)}
                      filas={filas}
                      puestos={filtros}
                      alCambiar={fijarFiltros}
                    />
                  )}
                </div>
              }
              antes={
                <>
                  {formularioDeAlta}
                  {/* Lo que se ha elegido en el menú de una fila sin ficha. */}
                  <div ref={panelDeFila}>
                    {(edicionDeFila || accionDeFila) && filaElegida ? (
                      <p className="mb-1.5 text-rotulo text-ink-faint">
                        {t("modulo.sobreLaFila", { nombre: filaElegida })}
                      </p>
                    ) : null}
                    {edicionDeFila ? (
                      <FormularioDeEdicion
                        recurso={recurso}
                        ruta={edicionDeFila.ruta}
                        plantilla={edicionDeFila.plantilla}
                        metodo={edicionDeFila.metodo}
                        valores={edicionDeFila.valores}
                        alGuardar={() => {
                          setEdicionDeFila(null);
                          void cargar();
                        }}
                        alCancelar={() => setEdicionDeFila(null)}
                      />
                    ) : null}
                    {ultimaDeFila ? (
                      <Acciones
                        acciones={[ultimaDeFila]}
                        servicio={recurso.servicio}
                        abierta={accionDeFila}
                        alCambiarAbierta={setAccionDeFila}
                        alTerminar={() => void cargar()}
                      />
                    ) : null}
                  </div>
                </>
              }
              // El listado ES la pantalla: se recorre con la página.
              ocupaLaPantalla
              pegada
              columnasIniciales={columnasDeLaVista}
              ordenInicial={ordenDeLaVista ?? null}
              // Lo que se puede hacer con una fila sin abrirla. Sólo cuando el
              // registro TIENE ficha: un menú sobre una fila a la que no se
              // llega no puede ofrecer ni abrir ni editar, y un menú con una
              // sola opción gris es peor que no tener menú.
              //
              // Editar en línea: qué campos y con qué control lo dice el
              // contrato; guardar es el mismo PATCH que usa el tablero.
              esquemaDeCampo={(c) => esquemaEditable.get(c)}
              alEditarCelda={editarCampo}
              accionesDeFila={
                aLaFicha
                  ? (f) => {
                      const destino = aLaFicha(f);
                      if (!destino) return [];
                      return [
                        {
                          clave: "abrir",
                          nombre: t("modulo.abrir"),
                          alElegir: () => navegar(destino),
                        },
                        {
                          clave: "editar",
                          nombre: t("modulo.editar"),
                          // Llega YA en edición: «Editar» que sólo abre la
                          // ficha deja a quien lo pulsó a un clic más de lo
                          // que pidió.
                          alElegir: () => navegar(`${destino}?editar=1`),
                        },
                      ];
                    }
                  : deLaFila
                    ? opcionesDeLaFila
                    : undefined
              }
              acciones={
                <span className="flex items-center gap-2">
                  <Exportar
                    listar={recurso.listar}
                    nombre={recurso.nombre}
                    consulta={comoQuery(filtros)}
                  />
                  <SelectorVista
                    vista={vista}
                    alCambiar={setVista}
                    recuerdaComo={recuerdaComo}
                    puedeAgrupar={Boolean(campoAgrupacion)}
                  />
                </span>
              }
            />
          )}
          {listasExtra.map((lista) => (
            <div key={lista.clave} className="mt-4">
              <Tabla filas={lista.filas} titulo={humanizar(lista.clave)} />
            </div>
          ))}
          <Retenidos campos={retenidos} enmascarados={tapados} />
          {siguiente ? (
            <button
              type="button"
              onClick={() => void cargar(siguiente)}
              className="mt-3 rounded-lg border border-ink-dim/60 px-3 py-1.5 text-dato text-ink-muted hover:bg-paper-light"
            >
              {t("modulo.cargarMas")}
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}

/**
 * Las columnas preferidas primero y el resto detrás, sin perder ninguna.
 *
 * Quedarse solo con las preferidas escondería los campos que el servicio añada
 * después, y el usuario no sabría que existen.
 */
export function ordenar(
  filas: Record<string, unknown>[],
  preferidas: string[] | undefined,
): string[] {
  const todas = new Set<string>();
  for (const fila of filas)
    for (const clave of Object.keys(fila)) todas.add(clave);
  if (!preferidas) return [...todas];
  const delante = preferidas.filter((c) => todas.has(c));
  return [...delante, ...[...todas].filter((c) => !delante.includes(c))];
}

/**
 * Una medida: un objeto con cifras y una frase que dice qué significan.
 *
 * Lo que se enseña sale del propio objeto. Las cifras delante —que es lo que
 * se viene a mirar— y la explicación debajo, con las palabras del servidor:
 * un número sin su frase se interpreta mal, y la frase la escribe quien sabe
 * cómo se calculó.
 *
 * **Lo que no es concluyente se dice.** Estas respuestas traen `medible`,
 * `concluyente` o `aviso` justo para eso, y pintar sus ceros como si fueran
 * una medida es la forma de que alguien decida sobre un dato que nadie ha
 * medido.
 */
export function Medidas({ rutas }: { rutas: string[] }) {
  const [datos, setDatos] = useState<Record<string, Record<string, unknown>>>(
    {},
  );

  useEffect(() => {
    const control = new AbortController();
    setDatos({});
    for (const ruta of rutas) {
      // Cada una con su fallo: que no se pueda leer una medida no puede dejar
      // sin ver el listado, que es a lo que se venía.
      void llamar<Record<string, unknown>>(ruta, { signal: control.signal })
        .then((r) => setDatos((previos) => ({ ...previos, [ruta]: r.datos })))
        .catch(() => undefined);
    }
    return () => control.abort();
  }, [rutas]);

  const pintadas = rutas.filter((r) => datos[r]);
  if (pintadas.length === 0) return null;

  return (
    <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {pintadas.map((ruta) => (
        <Medida key={ruta} datos={datos[ruta] ?? {}} />
      ))}
    </div>
  );
}

/** Los campos que explican, por orden de cuál manda si hay varios. */
const EXPLICAN = ["que_significa", "porque", "aviso", "detalle"];
/** Los que dicen que el número NO es una medida. */
const NO_CONCLUYE = ["medible", "concluyente", "tier_confirmado"];

function Medida({ datos }: { datos: Record<string, unknown> }) {
  const explicacion = EXPLICAN.map((c) => datos[c]).find(
    (v) => typeof v === "string" && v.trim(),
  ) as string | undefined;
  const sinMedir = NO_CONCLUYE.some((c) => datos[c] === false);
  const util = Object.entries(datos).filter(
    ([clave]) =>
      !EXPLICAN.includes(clave) &&
      !NO_CONCLUYE.includes(clave) &&
      !esIdentificadorTecnico(clave),
  );
  const cifras = util.filter(
    ([, valor]) =>
      typeof valor === "number" ||
      (typeof valor === "string" && /^-?\d+([.,]\d+)?$/.test(valor)),
  );
  // Hay medidas que no son cifras: un catálogo de opciones con su
  // descripción —las estrategias de reparto: «por turnos», «al que menos carga
  // tenga»—. Se enseñan igual, porque es justo lo que hace falta tener delante
  // al escribir la regla que las usa. Antes salían como un recuadro vacío: lo
  // vio quien lo usa, y tenía razón en preguntar para qué servía esa caja.
  const textos = util.filter(
    ([, valor]) =>
      typeof valor === "string" &&
      valor.trim().length > 2 &&
      !/^-?\d/.test(valor),
  );

  // **Sin nada que enseñar, no se enseña.** Un recuadro con marco y vacío se
  // lee como un dato que falta; y aquí es peor, porque no es un dato que
  // falte: es que esa respuesta no tenía nada que contar.
  if (cifras.length === 0 && textos.length === 0 && !explicacion) return null;

  return (
    <section className="card p-3">
      {cifras.length > 0 ? (
        <dl className="flex flex-wrap gap-x-4 gap-y-1">
          {cifras.slice(0, 6).map(([clave, valor]) => (
            <div key={clave}>
              <dt className="text-rotulo text-ink-faint">{humanizar(clave)}</dt>
              <dd
                className={`text-titulo font-medium ${sinMedir ? "text-ink-muted" : "text-ink"}`}
              >
                {escalar(valor, clave)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {cifras.length === 0 && textos.length > 0 ? (
        <dl className="space-y-0.5">
          {textos.slice(0, 8).map(([clave, valor]) => (
            <div key={clave} className="flex flex-wrap items-baseline gap-x-2">
              <dt className="text-dato text-ink">{humanizar(clave)}</dt>
              <dd className="text-rotulo text-ink-faint">{String(valor)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {explicacion ? (
        <p
          className={`mt-1 text-rotulo ${sinMedir ? "text-warning" : "text-ink-faint"}`}
        >
          {explicacion}
        </p>
      ) : null}
    </section>
  );
}
