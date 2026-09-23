/**
 * La portada: por dónde se empieza.
 *
 * Empieza por **lo que se hace** —dar de alta un cliente, una oportunidad, un
 * caso— y sigue por las áreas del producto en el mismo orden que el menú.
 *
 * Antes empezaba por «Módulos del catálogo», agrupados por su grupo del
 * catálogo, así que lo primero que veía cualquiera al entrar era PLATAFORMA:
 * tenants, contrato de la API, modelo de datos. Es lo último que necesita quien
 * abre un CRM, y estaba lo primero porque ese es el orden interno del
 * catálogo funcional, no el de nadie que trabaje aquí.
 *
 * Tampoco se le habla al usuario de «módulos del catálogo» ni de «pantallas
 * transversales»: eso es de dónde sale el código y no significa nada para quien
 * usa el producto.
 */

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { ALTAS } from "@/lib/altas";
import { porGrupoVisible } from "@/lib/modulos";
import { entradaVisible, menuDe } from "@/lib/navegacion";
import { usePermitidas } from "@/lib/permisos";
import { puede, type Sesion } from "@/lib/sesion";
import { teclaAtajo } from "@/lib/utiles";

export function Inicio({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  // Lo mismo que el menú, y con la misma función: si la portada ordenara por su
  // cuenta, las dos listas se separarían a la primera pantalla nueva.
  const permitidas = usePermitidas();
  const areas = menuDe(porGrupoVisible(sesion, permitidas), (e) => entradaVisible(sesion, e));
  const altas = ALTAS.filter((a) => puede(sesion, a.permiso));
  const cuantas = areas.reduce((total, a) => total + a.entradas.length, 0);

  return (
    <>
      <CabeceraPagina
        titulo={t("inicio.saludo", { nombre: sesion?.nombre || sesion?.email || "" })}
        entradilla={t("inicio.entradilla", { pantallas: cuantas, atajo: teclaAtajo() })}
        icono="home"
        acciones={
          sesion && sesion.roles.length > 0 ? (
            <span className="badge badge-muted">{sesion.roles.join(", ")}</span>
          ) : (
            <span className="badge badge-warning">{t("inicio.sinRoles")}</span>
          )
        }
      />

      {/* Lo primero, empezar a trabajar. Quien entra no busca una pantalla:
          busca hacer algo. */}
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

      <div className="space-y-7">
        {areas.map((area) => (
          <section key={area.id} aria-labelledby={`area-${area.id}`}>
            <h2
              id={`area-${area.id}`}
              className="flex items-center gap-2 text-sm font-semibold text-ink"
            >
              <Icono nombre={area.icono} tamano="sm" className="text-ink-muted" />
              {t(area.clave)}
            </h2>
            <div className="mt-3 grid auto-rows-fr gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {area.entradas.map((entrada) => (
                // Sin icono por tarjeta: unas lo tendrían y otras no —los
                // módulos del catálogo no traen— y esa desigualdad se lee como
                // descuido. El icono va en la cabecera del área.
                <Link key={entrada.a} to={entrada.a} className="card card-hover p-3">
                  <span className="truncate text-xs text-ink">
                    {entrada.clave.includes(".") ? t(entrada.clave) : entrada.clave}
                  </span>
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
