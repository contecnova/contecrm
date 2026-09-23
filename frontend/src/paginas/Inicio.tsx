/**
 * La portada: a dónde ir, con lo que hay de verdad.
 *
 * Antes eran dos tarjetas —administración y estado— en una aplicación con
 * veinticinco módulos: una portada que no lleva a casi nada obliga a buscar por
 * el menú desde el primer día. Ahora enseña los módulos del catálogo agrupados
 * como en el menú, y las herramientas transversales debajo.
 *
 * Lo que se pinta sale de la declaración de módulos y del árbol de navegación,
 * no de una lista escrita aquí: una portada con su propia lista se queda
 * desfasada a la primera pantalla nueva, y nadie lo nota porque sigue pintando.
 */

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { CabeceraPagina } from "@/componentes/Pagina";
import { Icono } from "@/componentes/Icono";
import { ALTAS } from "@/lib/altas";
import { porGrupoVisible } from "@/lib/modulos";
import { usePermitidas } from "@/lib/permisos";
import { TRANSVERSALES, entradaVisible, iconoDeGrupo } from "@/lib/navegacion";
import { puede, type Sesion } from "@/lib/sesion";
import { teclaAtajo } from "@/lib/utiles";

export function Inicio({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  // Lo mismo que el menú: solo lo que esta persona puede abrir. Enseñar en la
  // portada veintitrés módulos a quien puede entrar en cuatro es prometer un
  // producto que no va a poder usar.
  const permitidas = usePermitidas();
  const grupos = [...porGrupoVisible(sesion, permitidas)];
  const herramientas = TRANSVERSALES.filter((e) => entradaVisible(sesion, e));
  const cuantosModulos = grupos.reduce((total, [, m]) => total + m.length, 0);
  const altas = ALTAS.filter((a) => puede(sesion, a.permiso));

  return (
    <>
      <CabeceraPagina
        titulo={t("inicio.saludo", { nombre: sesion?.nombre || sesion?.email || "" })}
        entradilla={t("inicio.entradilla", {
          modulos: cuantosModulos,
          pantallas: herramientas.length,
          atajo: teclaAtajo(),
        })}
        icono="home"
        acciones={
          sesion && sesion.roles.length > 0 ? (
            <span className="badge badge-muted">{sesion.roles.join(", ")}</span>
          ) : (
            <span className="badge badge-warning">{t("inicio.sinRoles")}</span>
          )
        }
      />

      {/* Lo primero, empezar a trabajar. La portada enseñaba una rejilla de
          veintitrés módulos y ninguna forma evidente de dar de alta un cliente:
          quien entra no busca una pantalla, busca hacer algo. */}
      {altas.length > 0 ? (
        <section aria-labelledby="inicio-altas" className="mb-8">
          <h2 id="inicio-altas" className="text-sm font-semibold text-ink">
            {t("inicio.empezar")}
          </h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {altas.map((alta) => (
              <Link
                key={alta.a}
                to={alta.a}
                className="card card-hover inline-flex items-center gap-2 px-3 py-2"
              >
                <Icono nombre={alta.icono} tamano="sm" className="text-accent" />
                <span className="text-xs text-ink">{t(alta.clave)}</span>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      <section aria-labelledby="inicio-modulos">
        <h2 id="inicio-modulos" className="text-sm font-semibold text-ink">
          {t("inicio.modulos")}
        </h2>
        <p className="mt-1 text-2xs text-ink-faint">{t("inicio.modulosDetalle")}</p>

        <div className="mt-4 space-y-5">
          {grupos.map(([grupo, modulos]) => (
            <div key={grupo}>
              <p className="section-label mb-2 flex items-center gap-1.5">
                <Icono nombre={iconoDeGrupo(grupo)} tamano="sm" />
                {grupo}
              </p>
              <div className="grid auto-rows-fr gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {modulos.map((modulo) => (
                  <Link
                    key={modulo.ruta}
                    to={`/m/${modulo.ruta}`}
                    className="card card-hover flex h-full flex-col p-3"
                  >
                    <p className="truncate text-xs font-medium text-ink">{modulo.titulo}</p>
                    {/* Dos líneas y corta. Un módulo con quince recursos
                        desbordaba la tarjeta a seis líneas y estiraba toda la
                        fila de la rejilla: la lista completa está dentro, aquí
                        solo hace falta reconocerlo. */}
                    <p className="mt-1 line-clamp-2 text-3xs text-ink-faint">
                      {modulo.recursos.map((r) => r.nombre).join(" · ")}
                    </p>
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="inicio-herramientas" className="mt-8">
        <h2 id="inicio-herramientas" className="text-sm font-semibold text-ink">
          {t("inicio.herramientas")}
        </h2>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {herramientas.map((entrada) => (
            <Link
              key={entrada.a}
              to={entrada.a}
              className="card card-hover flex items-center gap-2.5 p-3"
            >
              <Icono nombre={entrada.icono} className="text-ink-muted" />
              <span className="truncate text-xs text-ink">{t(entrada.clave)}</span>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
