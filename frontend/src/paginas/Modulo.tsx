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

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useSearchParams } from "react-router-dom";

import { Cargando, Error as Fallo, Retenidos, Vacio } from "@/componentes/Estados";
import { Formulario } from "@/componentes/Formulario";
import { Tabla } from "@/componentes/Tabla";
import { llamar } from "@/lib/api";
import { camposDe, contratoDe, type CampoEsquema } from "@/lib/contrato";
import { moduloDe, type Recurso } from "@/lib/modulos";
import { puede, type Sesion } from "@/lib/sesion";
import { comoFilas } from "@/paginas/Consola";
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

  useEffect(() => setActivo(inicial), [ruta, inicial]);

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
        <nav aria-label={modulo.titulo} className="mt-3 flex flex-wrap gap-1">
          {modulo.recursos.map((r, i) => (
            <button
              key={r.nombre}
              type="button"
              onClick={() => setActivo(i)}
              aria-current={i === activo ? "page" : undefined}
              className={`rounded-lg px-3 py-1.5 text-xs ${
                i === activo ? "bg-paper-light text-ink" : "text-ink-muted hover:bg-paper-light"
              }`}
            >
              {r.nombre}
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

  // Se decide ANTES de pedir nada. Estaba después de los efectos, así que la
  // pantalla pedía igualmente la lista, recibía un 403 y lo pintaba como un
  // error del sistema: el usuario veía algo roto donde lo que pasa es que no le
  // toca. Y `solo_plataforma` no es un permiso —el administrador de una empresa
  // tiene `tenant:read` y aun así recibe 403—, por eso va aparte.
  const puedeVer =
    puede(sesion, recurso.permiso) &&
    (!recurso.solo_plataforma || Boolean(sesion?.es_admin_plataforma));

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
      setFallo(null);
      try {
        const partes: string[] = [];
        if (busqueda) partes.push(`${busqueda.parametro}=${encodeURIComponent(termino.trim())}`);
        if (cursor) partes.push(`cursor=${encodeURIComponent(cursor)}`);
        const separador = recurso.listar.includes("?") ? "&" : "?";
        const ruta = partes.length ? `${recurso.listar}${separador}${partes.join("&")}` : recurso.listar;
        const respuesta = await llamar<unknown>(ruta);
        const nuevas = comoFilas(respuesta.datos);
        // Se ACUMULA al paginar: sustituir haría que «cargar más» pareciera
        // saltar de página, y la lista perdería lo que el usuario ya miraba.
        setFilas((previas) => (cursor && previas ? [...previas, ...nuevas] : nuevas));
        setRetenidos(respuesta.retenidos);
        const cuerpo = respuesta.datos as { siguiente?: string | null } | null;
        setSiguiente(cuerpo && typeof cuerpo === "object" ? (cuerpo.siguiente ?? null) : null);
      } catch (error) {
        setFallo(error);
      }
    },
    [recurso.listar, puedeVer, busqueda, termino, terminoValido],
  );

  useEffect(() => {
    setFilas(null);
    setSiguiente(null);
    void cargar();
  }, [cargar]);

  useEffect(() => {
    if (!recurso.crear) return;
    let vivo = true;
    void contratoDe(recurso.servicio).then((documento) => {
      if (vivo) setCampos(camposDe(documento, plantilla(recurso.crear!), "post"));
    });
    return () => {
      vivo = false;
    };
  }, [recurso.crear, recurso.servicio]);

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
      await llamar(recurso.crear!, { metodo: "POST", cuerpo: valores });
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
      {recurso.crear && (creando || (filas !== null && filas.length > 0)) ? (
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
          titulo={t("modulo.sinRegistros", { recurso: recurso.nombre.toLowerCase() })}
          detalle={recurso.crear ? t("modulo.sinRegistrosDetalle") : t("vacio.detalle")}
          accion={
            recurso.crear && campos
              ? { texto: t("modulo.nuevo"), alPulsar: () => setCreando(true) }
              : undefined
          }
        />
      ) : (
        <>
          <Tabla
            filas={filas}
            columnas={ordenar(filas, recurso.columnas)}
            titulo={recurso.nombre}
            // Solo se enlaza lo que TIENE ficha: un enlace que lleva a una
            // pantalla vacía es peor que no tener enlace, porque el usuario
            // cree que se ha roto algo.
            enlace={
              recurso.objeto
                ? (fila) =>
                    typeof fila.id === "string"
                      ? `/m/${ruta}/${recurso.objeto}/${fila.id}`
                      : null
                : undefined
            }
          />
          {/* Al crear un registro o al cargar más, la lista cambia sin que
              nada lo diga: quien no ve la pantalla no se entera de que ha
              pasado algo (CRM-06.02.01.05). */}
          <p className="sr-only" role="status">
            {t("modulo.filasCargadas", { cuantas: filas.length })}
          </p>
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

/** `/api/v1/politicas-acceso/{nombre}` es la plantilla que usa el OpenAPI. */
function plantilla(ruta: string): string {
  return ruta;
}
