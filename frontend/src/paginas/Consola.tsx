/**
 * La consola de administración, construida desde el contrato
 * (CRM-07.01.01.01, CRM-07.04.03.26).
 *
 * Y por eso **enseña todo lo que el servidor marca como administración**, sin
 * que nadie escriba una pantalla por área. Estas son las capacidades de
 * producto que se ven aquí y en ningún otro sitio, cada una con el área que la
 * pinta: `claves-cifrado` (CRM-00.01.04.09, la clave del cliente con su
 * rotación y su revocación), `flags` (CRM-00.01.04.04), `plantillas`
 * (CRM-07.01.01.04), `calendarios` (CRM-07.01.01.05), `monedas`
 * (CRM-07.01.01.06), `sharing-rules` (CRM-00.05.02.04) y `buzones`
 * (CRM-06.01.01.01, la sincronización de correo y calendario del puesto).
 *
 * La lista no se mantiene a mano en ninguna otra parte: el área aparece porque
 * el servidor etiqueta sus operaciones como de administración, así que si una
 * de estas desapareciera del servidor, dejaría de pintarse — y el gate de
 * cobertura por capacidad lo diría.
 *
 * El menú, las tablas y las acciones salen de `GET /api/v1/superficie`. Eso es
 * lo que hace **comprobable** —y no solo declarado— que la consola está
 * replicada al 100 % por API: aquí no hay forma de pintar una acción que no sea
 * una operación publicada, porque no hay ninguna lista de acciones escrita a
 * mano de donde sacarla.
 *
 * Y lo que la consola no hace: **no decide permisos**. Pregunta a la sesión si
 * el permiso que la propia operación declara está concedido, y con eso decide
 * si ofrecerla. Quien decide de verdad sigue siendo el servidor.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Retenidos, Vacio } from "@/componentes/Estados";
import { Tabla, normalizar } from "@/componentes/Tabla";
import { llamar, salvoCancelacion } from "@/lib/api";
import { puede, type Sesion } from "@/lib/sesion";
import { CabeceraPagina } from "@/componentes/Pagina";
import {
  acciones,
  areasDeAdministracion,
  cargarSuperficie,
  operacionDeListado,
  type Area,
  type Superficie,
} from "@/lib/superficie";

export function Consola({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  const [superficie, setSuperficie] = useState<Superficie | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [area, setArea] = useState<Area | null>(null);

  useEffect(() => {
    const control = new AbortController();
    cargarSuperficie(control.signal).then(setSuperficie).catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  if (fallo) return <Fallo error={fallo} />;
  if (!superficie) return <Cargando />;

  const areas = areasDeAdministracion(superficie);

  return (
    <div className="grid gap-6 md:grid-cols-[16rem_1fr]">
      <aside>
        <CabeceraPagina
          titulo={t("consola.titulo")}
          entradilla={t("consola.intro")}
          icono="settings"
        />
        <p className="mt-2 text-3xs text-ink-faint">
          {t("consola.total", { total: superficie.total, administracion: superficie.administracion })}
        </p>
        {/* Un servicio que no contesta se dice y se nombra. Callarlo haría que
            la consola escondiera media administración como si no existiera. */}
        {superficie.servicios_sin_contestar.length > 0 ? (
          <p className="mt-2 rounded-lg bg-warning/10 p-2 text-3xs text-warning" role="alert">
            {t("consola.incompleta", {
              count: superficie.servicios_sin_contestar.length,
              servicios: superficie.servicios_sin_contestar.join(", "),
            })}
          </p>
        ) : null}

        <nav aria-label={t("consola.areas")} className="mt-4 flex flex-col gap-0.5">
          {areas.map((a) => (
            <button
              key={a.recurso}
              type="button"
              onClick={() => setArea(a)}
              className={`rounded-lg px-3 py-1.5 text-left text-xs ${
                area?.recurso === a.recurso
                  ? "bg-paper-light text-ink"
                  : "text-ink-muted hover:bg-paper-light"
              }`}
            >
              {a.nombre}
              <span className="ml-2 text-3xs text-ink-faint">{a.operaciones.length}</span>
            </button>
          ))}
        </nav>
      </aside>

      {/* Cambiar de área cambia la pantalla entera: sin anunciarlo, quien
          navega con lector pulsa y no sabe si ha pasado algo. */}
      <p className="sr-only" role="status">
        {area ? area.nombre : ""}
      </p>
      <section>
        {area ? (
          <AreaVista area={area} sesion={sesion} />
        ) : (
          // Sin área elegida no se enseña «no hay nada» —que suena a que la
          // consola está vacía cuando tiene mil operaciones— sino qué hacer.
          <Vacio
            icono="left_click"
            titulo={t("consola.eligeArea")}
            detalle={t("consola.eligeAreaDetalle")}
          />
        )}
      </section>
    </div>
  );
}

function AreaVista({ area, sesion }: { area: Area; sesion: Sesion | null }) {
  const { t } = useTranslation();
  const listado = operacionDeListado(area);
  const [filas, setFilas] = useState<Record<string, unknown>[] | null>(null);
  const [retenidos, setRetenidos] = useState<string[]>([]);
  const [tapados, setTapados] = useState<string[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    setFilas(null);
    setFallo(null);
    if (!listado) return;
    const control = new AbortController();
    llamar<unknown>(listado.ruta, { signal: control.signal })
      .then((r) => {
        setFilas(comoFilas(r.datos));
        setRetenidos(r.retenidos);
        setTapados(r.enmascarados);
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [listado]);

  return (
    <>
      <h2 className="text-sm font-medium text-ink">{area.nombre}</h2>

      {listado ? (
        fallo ? (
          <Fallo error={fallo} />
        ) : filas === null ? (
          <Cargando />
        ) : filas.length === 0 ? (
          <Vacio />
        ) : (
          <div className="mt-3">
            <Tabla filas={filas} titulo={area.nombre} />
            <Retenidos campos={retenidos} enmascarados={tapados} />
          </div>
        )
      ) : (
        <p className="mt-3 text-2xs text-ink-faint">{t("consola.sinListado")}</p>
      )}

      <h3 className="mt-6 text-2xs font-medium uppercase tracking-wide text-ink-faint">
        {t("consola.operaciones")}
      </h3>
      <ul className="mt-2 flex flex-col gap-1">
        {acciones(area).map((o) => {
          const permitida = puede(sesion, o.permiso);
          return (
            <li
              key={`${o.metodo} ${o.ruta}`}
              className={`rounded-lg border border-ink-dim/30 px-3 py-2 ${
                permitida ? "bg-paper" : "bg-paper-light opacity-60"
              }`}
            >
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-3xs text-accent">{o.metodo}</span>
                <span className="font-mono text-2xs text-ink-muted">{o.ruta}</span>
              </div>
              <p className="text-2xs text-ink">{o.resumen}</p>
              <p className="text-3xs text-ink-faint">
                {o.permiso ? `${t("consola.permiso")}: ${o.permiso}` : null}
                {!permitida ? ` · ${t("consola.sinPermiso")}` : null}
              </p>
            </li>
          );
        })}
      </ul>
    </>
  );
}

/**
 * Convierte lo que devuelve un listado en filas.
 *
 * La API pagina por cursor y devuelve `{items, siguiente}` en unos sitios y una
 * lista a secas en otros. Se admiten las dos formas en vez de exigir una: la
 * alternativa era que media consola no enseñara nada y pareciera que esos
 * recursos están vacíos.
 */
export function comoFilas(datos: unknown): Record<string, unknown>[] {
  if (Array.isArray(datos)) return normalizar(datos);
  if (datos && typeof datos === "object") {
    const objeto = datos as Record<string, unknown>;
    for (const clave of ["items", "resultados", "datos"]) {
      if (Array.isArray(objeto[clave])) return normalizar(objeto[clave]);
    }
    // Y la tercera forma: la lista bajo su propio nombre —`{partners: […]}`,
    // `{ordenes: […]}`—. Se coge cuando hay una sola propiedad que sea un
    // array; con dos no se adivina cuál es la lista.
    const arrays = Object.values(objeto).filter(Array.isArray) as unknown[][];
    if (arrays.length === 1 && arrays[0]) return normalizar(arrays[0]);
    return [objeto];
  }
  return [];
}
