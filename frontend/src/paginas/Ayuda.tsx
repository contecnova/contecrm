/**
 * Ayuda en producto: el manual donde estás (CRM-07.04.03.33).
 *
 * Un manual excelente que vive en otro sitio no lo lee nadie en el momento en que
 * hace falta, que es justo cuando alguien está mirando una pantalla y no entiende
 * por qué el sistema le dice que no.
 *
 * Dos decisiones:
 *
 * **Se abre por la sección de la pantalla en la que estás**, no por el índice.
 * Mandar al índice es mandar a buscar, y quien está atascado no busca: se rinde y
 * escribe a soporte.
 *
 * **Y los mensajes de «no se puede» llevan su enlace.** El sistema explica por
 * qué dice que no; esta pantalla conecta esa explicación con el capítulo que la
 * desarrolla.
 */

import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { CabeceraPagina } from "@/componentes/Pagina";

/**
 * Qué capítulo del manual corresponde a cada pantalla.
 *
 * Es un mapa explícito y no una convención sobre la ruta: una convención se
 * rompe en silencio el día que alguien renombra una ruta, y entonces la ayuda
 * lleva al sitio equivocado — que es peor que no llevar a ninguno.
 */
const CAPITULOS: Record<string, { ancla: string; titulo: string }> = {
  "/": { ancla: "como-se-entra-y-como-se-busca-seccion-05", titulo: "Empezar" },
  "/casos": { ancla: "casos-y-atencion-al-cliente-seccion-41", titulo: "Casos" },
  "/consola-agente": { ancla: "por-donde-entran-los-clientes-seccion-42", titulo: "Atención" },
  "/conocimiento": { ancla: "conocimiento-y-autoservicio-seccion-43", titulo: "Conocimiento" },
  "/marketing": { ancla: "campanas-y-recorridos-seccion-22", titulo: "Campañas" },
  "/cuadros": { ancla: "informes-y-cuadros-de-mando-seccion-51", titulo: "Informes" },
  "/procesos": { ancla: "lo-que-el-crm-puede-hacer-sin-ti-seccion-03", titulo: "Procesos" },
  "/administracion": { ancla: "administrar-el-crm-seccion-71", titulo: "Administración" },
  "/estado": { ancla: "saber-si-el-sistema-va-bien-seccion-06", titulo: "Estado" },
  "/proveedores": { ancla: "tus-proveedores-seccion-91", titulo: "Proveedores" },
  "/coste": { ancla: "lo-que-cuesta-y-lo-que-se-puede-comprometer-seccion-92", titulo: "Coste" },
  "/puesto": { ancla: "correo-calendario-y-el-resto-de-tus-herramientas-seccion-61", titulo: "Puesto" },
  "/inteligencia": { ancla: "lo-que-hace-la-inteligencia-artificial-seccion-52", titulo: "IA" },
  "/alm": { ancla: "cambios-entornos-y-vuelta-atras-seccion-72", titulo: "ALM" },
  "/rendimiento": { ancla: "cuando-hay-mucho-volumen-seccion-81", titulo: "Rendimiento" },
};

const BASE = "/docs/manual-usuario";

export function Ayuda() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const capitulo = CAPITULOS[pathname];

  return (
    <>
      <CabeceraPagina
        titulo={t("ayuda.titulo")}
        entradilla={t("ayuda.intro")}
        icono="help"
      />

      {capitulo ? (
        <a
          className="mt-4 inline-block rounded-lg bg-accent px-3 py-1.5 text-2xs text-paper"
          href={`${BASE}/#${capitulo.ancla}`}
        >
          {t("ayuda.abrirCapitulo", { capitulo: capitulo.titulo })}
        </a>
      ) : (
        /* Sin capítulo asociado se dice, en vez de mandar al índice: mandar a
           buscar a quien está atascado es como se pierde al usuario. */
        <p className="mt-4 text-2xs text-ink-muted">{t("ayuda.sinCapitulo")}</p>
      )}

      <nav aria-label={t("ayuda.otros")} className="mt-6">
        <h2 className="text-xs font-medium text-ink">{t("ayuda.otros")}</h2>
        <ul className="mt-2 space-y-1">
          <li>
            <a className="text-2xs text-accent underline" href={`${BASE}/`}>
              {t("ayuda.manualUsuario")}
            </a>
          </li>
          <li>
            <a className="text-2xs text-accent underline" href="/docs/manual-tecnico/">
              {t("ayuda.manualTecnico")}
            </a>
          </li>
        </ul>
      </nav>
    </>
  );
}
