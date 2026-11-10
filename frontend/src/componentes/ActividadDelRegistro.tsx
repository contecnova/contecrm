/**
 * Apuntar y ver lo que ha pasado con un registro, en su ficha.
 *
 * La ficha del cliente lo tenía —llamada, reunión, nota, correo, encima de la
 * línea de tiempo—, y **la de la oportunidad y la del caso no**, aunque el
 * servidor admite actividades sobre los dos. Medido el 10-11-2026 (tareas T07 y
 * T09): para apuntar la reunión de una oportunidad o la respuesta que se le dio
 * a un cliente en su caso había que ir al alta suelta de actividades y teclear
 * el identificador interno del registro. Eso no lo hace nadie dos veces.
 *
 * Es el mismo `RegistrarActividad` de las demás fichas, con debajo lo último
 * apuntado: lo que se apunta y no se ve, se vuelve a apuntar.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Vacio } from "@/componentes/Estados";
import { RegistrarActividad } from "@/componentes/RegistrarActividad";
import { filas, llamar, salvoCancelacion } from "@/lib/api";
import { fechaHora } from "@/lib/formato";

interface Actividad {
  id: string;
  tipo: string;
  asunto: string;
  created_at?: string;
}

export function ActividadDelRegistro({
  objeto,
  objetoId,
}: {
  objeto: string;
  objetoId: string;
}) {
  const { t } = useTranslation();
  const [actividades, setActividades] = useState<Actividad[] | null>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<unknown>(
      `/api/v1/activities?objeto=${encodeURIComponent(objeto)}&objeto_id=${encodeURIComponent(objetoId)}&limite=10`,
      { signal: control.signal },
    )
      .then((r) => setActividades(filas<Actividad>(r.datos)))
      // Sin la lista, se puede seguir apuntando: no se tapa el formulario.
      .catch(salvoCancelacion(() => setActividades([])));
    return () => control.abort();
  }, [objeto, objetoId]);

  useEffect(cargar, [cargar]);

  return (
    <section
      className="card mb-4 p-4"
      aria-labelledby={`actividad-${objetoId}`}
    >
      <h2 id={`actividad-${objetoId}`} className="section-label mb-3">
        {t("actividadDelRegistro.titulo")}
      </h2>
      <RegistrarActividad
        objeto={objeto}
        objetoId={objetoId}
        alRegistrar={cargar}
      />
      {actividades === null ? null : actividades.length === 0 ? (
        <Vacio
          compacto
          icono="history"
          titulo={t("actividadDelRegistro.vacio")}
        />
      ) : (
        <ul className="divide-y divide-ink-dim/40">
          {actividades.map((a) => (
            <li
              key={a.id}
              className="flex items-baseline justify-between gap-3 py-1.5"
            >
              <span className="min-w-0 truncate text-dato text-ink">
                <span className="mr-2 text-rotulo text-ink-faint">
                  {t(`actividad.${a.tipo}`, { defaultValue: a.tipo })}
                </span>
                {a.asunto}
              </span>
              <span className="shrink-0 text-rotulo text-ink-faint">
                {a.created_at ? fechaHora(a.created_at) : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
