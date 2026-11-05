/**
 * Lo que la IA puede hacer con este registro, a la vista.
 *
 * Estaba en el menú «Más» de cada ficha, mezclado con «Archivar» y «Colgar el
 * caso de una incidencia masiva», y quien abría la herramienta no lo veía: el
 * 05-11-2026 el usuario miraba la ficha y decía que no había cambiado nada. Lo
 * que la IA ofrece se reconoce por el permiso que exige —`ia:usar`, el mismo en
 * todas— y no por una lista de rutas: una acción nueva de IA sale aquí sola.
 *
 * Abre el mismo formulario que abría el menú: aquí sólo cambia DÓNDE se ofrece.
 */
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import type { Accion } from "@/lib/acciones";

export function esDeIA(accion: Accion): boolean {
  return accion.permiso === "ia:usar";
}

/** «Resumir esta cuenta con IA: puntos clave…» → «Resumir esta cuenta con IA». */
function rotuloCorto(nombre: string): string {
  return nombre.split(":")[0]?.trim() || nombre;
}

export function AsistenteIA({
  acciones,
  abierta,
  alElegir,
}: {
  acciones: Accion[];
  abierta: Accion | null;
  alElegir: (accion: Accion) => void;
}) {
  const { t } = useTranslation();
  const deIA = acciones.filter(esDeIA);
  if (deIA.length === 0) return null;
  return (
    <section
      aria-label={t("asistenteIA.titulo")}
      className="mt-3 rounded-lg border border-accent/30 bg-accent/5 p-3"
    >
      <div className="flex flex-wrap items-baseline gap-x-2 text-rotulo">
        <Icono
          nombre="auto_awesome"
          tamano="sm"
          className="self-center text-accent"
        />
        <span className="font-medium text-ink">{t("asistenteIA.titulo")}</span>
        <span className="text-ink-muted">{t("asistenteIA.detalle")}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {deIA.map((accion) => (
          <button
            key={accion.ruta}
            type="button"
            className="btn-secondary"
            title={accion.nombre}
            aria-pressed={abierta?.ruta === accion.ruta}
            onClick={() => alElegir(accion)}
          >
            {rotuloCorto(accion.nombre)}
          </button>
        ))}
      </div>
    </section>
  );
}
