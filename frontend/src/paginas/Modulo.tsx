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
import { useParams, useSearchParams } from "react-router-dom";

import { Cargando, Error as Fallo, Retenidos, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import {
  Agrupado,
  Etiquetas,
  SelectorVista,
  Tarjetas,
  campoDeAgrupacion,
  esVocabulario,
  leerVista,
  type Vista,
} from "@/componentes/Vistas";
import { cn } from "@/lib/utiles";
import { Formulario } from "@/componentes/Formulario";
import { Tabla } from "@/componentes/Tabla";
import { llamar } from "@/lib/api";
import {
  admite,
  camposDe,
  contratoDe,
  fichaDe,
  propositoDe,
  type CampoEsquema,
  type Proposito,
} from "@/lib/contrato";
import { moduloDe, objetoDe, recursoVisible, type Recurso } from "@/lib/modulos";
import { puede, type Sesion } from "@/lib/sesion";
import { comoFilas } from "@/paginas/Consola";
import { usePermitidas } from "@/lib/permisos";
import { CabeceraPagina } from "@/componentes/Pagina";
import { iconoDeGrupo } from "@/lib/navegacion";

export function Modulo({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  const { ruta = "" } = useParams();
  const [parametros] = useSearchParams();
  const modulo = moduloDe(ruta);
  // `?r=Cuentas` elige la pestaña. Lo usa el botón «Crear» de la barra para
  // llevar directamente al alta que se ha pedido: sin esto caería en la primera
  // pestaña del módulo, que puede no ser la del recurso que se quiere crear.
  const pedido = parametros.get("r");
  const inicial = Math.max(
    0,
    modulo?.recursos.findIndex((r) => r.nombre === pedido) ?? 0,
  );
  const [activo, setActivo] = useState(inicial);
  const permitidas = usePermitidas();
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
      (modulo?.recursos ?? [])
        .map((r, i) => ({ r, i }))
        .filter(({ r }) => recursoVisible(sesion, r, permitidas))
        .sort((a, b) => Number(Boolean(a.r.icono)) - Number(Boolean(b.r.icono))),
    [modulo?.recursos, sesion, permitidas],
  );

  useEffect(() => setActivo(inicial), [ruta, inicial]);

  // Si la activa no es visible —porque se llegó con `?r=` a una que no toca, o
  // porque la superficie llegó después—, se cae a la primera que sí lo es.
  useEffect(() => {
    if (pestañas.length > 0 && !pestañas.some(({ i }) => i === activo)) {
      setActivo(pestañas[0]!.i);
    }
  }, [pestañas, activo]);

  if (!modulo) return <Vacio />;
  const recurso = modulo.recursos[activo] ?? modulo.recursos[0];

  return (
    <>
      {/* Cada pantalla dice qué capacidad del catálogo implementa
          (CRM-07.04.05.05). Desde aquí se llega al enunciado, al código y a la
          prueba: es la trazabilidad puesta delante de quien la mira, en vez de
          enterrada en un fichero que solo abre quien ya sabe que existe. */}
      <CabeceraPagina
        titulo={modulo.titulo}
        icono={iconoDeGrupo(modulo.grupo)}
        entradilla={
          <span className="font-mono text-3xs">
            {modulo.capacidad} · {t("modulo.seccion")} {modulo.seccion}
          </span>
        }
      />
      {modulo.recursos.length > 1 ? (
        <nav aria-label={modulo.titulo} className="mt-3 flex flex-wrap items-center gap-1">
          {/* Las pestañas rotuladas con icono —hoy, la papelera— van siempre al
              final y separadas del resto: no son un sitio donde se trabaja, son
              el sitio donde se mira cuando algo falta. Mezcladas entre las demás
              obligan a leerlas todas para encontrar la que se usa. */}
          {pestañas.map(({ r, i }, posicion) => (
            <button
              key={r.nombre}
              type="button"
              onClick={() => setActivo(i)}
              aria-current={i === activo ? "page" : undefined}
              title={r.icono ? r.nombre : undefined}
              aria-label={r.icono ? r.nombre : undefined}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs",
                i === activo ? "bg-paper-light text-ink" : "text-ink-muted hover:bg-paper-light",
                r.icono && !pestañas[posicion - 1]?.r.icono ? "ml-auto" : "",
              )}
            >
              {r.icono ? <Icono nombre={r.icono} /> : r.nombre}
            </button>
          ))}
        </nav>
      ) : null}
      {recurso ? (
        <RecursoVista
          recurso={recurso}
          sesion={sesion}
          ruta={ruta}
          abrirAlta={parametros.get("nuevo") === "1"}
        />
      ) : (
        <Vacio />
      )}
    </>
  );
}

function RecursoVista({
  recurso,
  sesion,
  ruta,
  abrirAlta = false,
}: {
  recurso: Recurso;
  sesion: Sesion | null;
  ruta: string;
  /** Se llega con el formulario ya abierto desde el botón «Crear». */
  abrirAlta?: boolean;
}) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Record<string, unknown>[] | null>(null);
  const [retenidos, setRetenidos] = useState<string[]>([]);
  const [siguiente, setSiguiente] = useState<string | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [campos, setCampos] = useState<CampoEsquema[] | null>(null);
  const [creando, setCreando] = useState(abrirAlta);
  const [enviando, setEnviando] = useState(false);
  const [termino, setTermino] = useState("");
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
  const [rutaDeAlta, setRutaDeAlta] = useState<string | null>(recurso.crear ?? null);
  /**
   * Con qué campo se abre un registro.
   *
   * Vacío cuando no hay ficha. `id` en el caso normal, pero no siempre: hay
   * recursos que se abren por su **clave** —`/forecast/periodos/{clave}`— y
   * mandarles el identificador daba un 404 al pulsar la fila. Lo dice el
   * contrato en el nombre de su parámetro, así que no hay que declararlo.
   */
  const [campoFicha, setCampoFicha] = useState(recurso.objeto ? "id" : "");
  const recuerdaComo = `${ruta}.${recurso.nombre}`;
  const [vista, setVista] = useState<Vista>(() => leerVista(recuerdaComo));
  // Por qué campo agrupar sale de los datos que hay: con un solo valor no hay
  // nada que separar, y con uno distinto por fila serían columnas de una.
  const campoAgrupacion = useMemo(() => campoDeAgrupacion(filas ?? []), [filas]);
  const vocabulario = useMemo(() => esVocabulario(filas ?? []), [filas]);
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
          const clave = fila[campoFicha] ?? fila.id;
          return typeof clave === "string"
            ? `/m/${ruta}/${objetoDe(recurso)}/${encodeURIComponent(clave)}`
            : null;
        }
      : undefined;

  const busqueda = recurso.busqueda;
  const terminoValido = !busqueda || termino.trim().length >= (busqueda.minimo ?? 1);

  const cargar = useCallback(
    async (cursor?: string) => {
      if (!puedeVer) return;
      // Un recurso de búsqueda no se pide sin término: la API contesta 422 y la
      // pantalla enseñaría un error donde lo que falta es que alguien escriba.
      if (busqueda && !terminoValido) {
        setFilas(null);
        return;
      }
      const mia = (peticion.current += 1);
      setFallo(null);
      try {
        const partes: string[] = [];
        if (busqueda) partes.push(`${busqueda.parametro}=${encodeURIComponent(termino.trim())}`);
        if (cursor) partes.push(`cursor=${encodeURIComponent(cursor)}`);
        const separador = recurso.listar.includes("?") ? "&" : "?";
        const ruta = partes.length ? `${recurso.listar}${separador}${partes.join("&")}` : recurso.listar;
        const respuesta = await llamar<unknown>(ruta);
        if (mia !== peticion.current) return;
        const nuevas = comoFilas(respuesta.datos);
        // Se ACUMULA al paginar: sustituir haría que «cargar más» pareciera
        // saltar de página, y la lista perdería lo que el usuario ya miraba.
        setFilas((previas) => (cursor && previas ? [...previas, ...nuevas] : nuevas));
        setRetenidos(respuesta.retenidos);
        const cuerpo = respuesta.datos as { siguiente?: string | null } | null;
        setSiguiente(cuerpo && typeof cuerpo === "object" ? (cuerpo.siguiente ?? null) : null);
      } catch (error) {
        // El fallo de una petición ya superada no se enseña: sería un error
        // sobre algo que el usuario ya no está pidiendo.
        if (mia === peticion.current) setFallo(error);
      }
    },
    [recurso.listar, puedeVer, busqueda, termino, terminoValido],
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
      setProposito(propositoDe(documento, recurso.listar, "get"));
      // El alta: la declarada si la hay, y si no la de la propia ruta que
      // lista, que es donde la pone el servidor salvo excepción.
      const alta = recurso.crear ?? (admite(documento, recurso.listar, "post") ? recurso.listar : null);
      setRutaDeAlta(alta);
      setCampos(alta ? camposDe(documento, alta, "post") : null);
      // La ficha: basta con que el contrato tenga la operación de un registro.
      // Se enlaza aunque solo se pueda leer, porque casi todo lo que se hace
      // con un registro —acciones, líneas, adjuntos, la conversación— cuelga de
      // la ficha y sin abrirla no se alcanza nada de eso.
      const plantillaFicha = fichaDe(documento, recurso.listar);
      const parametro = plantillaFicha?.match(/\{([a-z_]+)\}$/)?.[1] ?? "";
      // `{cuenta_id}` es el identificador de siempre; `{clave}` es otro campo
      // de la fila, y hay que mandar ese.
      const campo = !parametro ? "" : /(^|_)id$/.test(parametro) ? "id" : parametro;
      setCampoFicha(campo || (recurso.objeto ? "id" : ""));
    });
    return () => {
      vivo = false;
    };
  }, [recurso.servicio, recurso.listar, recurso.crear, recurso.objeto]);

  if (!puedeVer) {
    // Con el mismo lenguaje que el resto de estados. Una línea de texto suelta
    // en medio de la pantalla se lee como un fallo a medias; un recuadro con su
    // icono se lee como lo que es: aquí no te toca entrar.
    return (
      <Vacio
        icono="lock"
        titulo={recurso.solo_plataforma ? t("errores.soloPlataforma") : t("errores.sinPermiso")}
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
      await llamar(rutaDeAlta!, { metodo: "POST", cuerpo: valores });
      setCreando(false);
      await cargar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="mt-4">
      {/* Cuando la lista está vacía el botón no va aquí: lo ofrece el propio
          estado vacío, y dos botones iguales a diez centímetros uno de otro
          hacen dudar de si son lo mismo. */}
      {rutaDeAlta && (creando || (filas !== null && filas.length > 0)) ? (
        <button
          type="button"
          onClick={() => setCreando((v) => !v)}
          className={creando ? "btn-secondary mb-3" : "btn-primary mb-3"}
        >
          {creando ? t("modulo.cancelar") : t("modulo.nuevo")}
        </button>
      ) : null}

      {creando && campos ? (
        <div className="mb-4 rounded-xl border border-ink-dim/60 bg-paper p-4">
          <Formulario
            campos={campos}
            enviando={enviando}
            textoEnviar={t("modulo.guardar")}
            alEnviar={(v) => void crear(v)}
          />
        </div>
      ) : null}

      {proposito?.resumen ? (
        <div className="mb-4 max-w-3xl">
          <p className="text-xs text-ink">{proposito.resumen}</p>
          {proposito.detalle ? (
            <p className="mt-0.5 text-2xs text-ink-faint">{proposito.detalle}</p>
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

      {fallo ? <Fallo error={fallo} reintentar={() => void cargar()} /> : null}

      {busqueda && !terminoValido ? (
        <p className="text-2xs text-ink-faint" role="status">
          {t("modulo.escribeParaBuscar", { minimo: busqueda.minimo ?? 1 })}
        </p>
      ) : filas === null ? (
        <Cargando />
      ) : filas.length === 0 ? (
        // El vacío ofrece lo único que se puede hacer aquí: dar de alta el
        // primero. Un recuadro que solo dice «no hay nada» deja a quien mira en
        // el mismo sitio en el que estaba.
        <Vacio
          icono="inbox"
          titulo={t("modulo.sinRegistros")}
          detalle={rutaDeAlta ? t("modulo.sinRegistrosDetalle") : t("vacio.detalle")}
          accion={
            rutaDeAlta && campos
              ? { texto: t("modulo.nuevo"), alPulsar: () => setCreando(true) }
              : undefined
          }
        />
      ) : (
        <>
          {/* Los controles van a la derecha, que es donde los pone todo el
              mercado y por tanto donde se buscan, y en **una sola fila**: el de
              columnas primero y el de vista a su derecha, siempre en ese orden.
              En la vista de tabla los pinta la propia tabla, porque el botón de
              columnas es suyo; aquí solo cuando no hay tabla. */}
          {vista === "tabla" && !vocabulario ? null : (
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-3xs text-ink-faint" role="status">
                {t("modulo.filasCargadas", { cuantas: filas.length })}
              </p>
              {/* Sin selector para un vocabulario: no hay tres formas de mirar
                  nueve palabras. */}
              {vocabulario ? null : (
                <SelectorVista
                  vista={vista}
                  alCambiar={setVista}
                  recuerdaComo={recuerdaComo}
                  puedeAgrupar={Boolean(campoAgrupacion)}
                />
              )}
            </div>
          )}
          {vocabulario ? (
            <Etiquetas filas={filas} />
          ) : vista === "agrupado" && campoAgrupacion ? (
            <Agrupado
              filas={filas}
              campo={campoAgrupacion}
              columnas={recurso.columnas}
              enlace={aLaFicha}
            />
          ) : vista === "tarjetas" ? (
            <Tarjetas filas={filas} columnas={recurso.columnas} enlace={aLaFicha} />
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
                <p className="text-3xs text-ink-faint" role="status">
                  {t("modulo.filasCargadas", { cuantas: filas.length })}
                </p>
              }
              acciones={
                <SelectorVista
                  vista={vista}
                  alCambiar={setVista}
                  recuerdaComo={recuerdaComo}
                  puedeAgrupar={Boolean(campoAgrupacion)}
                />
              }
            />
          )}
          <Retenidos campos={retenidos} />
          {siguiente ? (
            <button
              type="button"
              onClick={() => void cargar(siguiente)}
              className="mt-3 rounded-lg border border-ink-dim/60 px-3 py-1.5 text-2xs text-ink-muted hover:bg-paper-light"
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
  for (const fila of filas) for (const clave of Object.keys(fila)) todas.add(clave);
  if (!preferidas) return [...todas];
  const delante = preferidas.filter((c) => todas.has(c));
  return [...delante, ...[...todas].filter((c) => !delante.includes(c))];
}
