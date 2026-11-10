/**
 * Qué herramientas ve un agente de fuera en esta exposición.
 *
 * El catálogo que recibe el agente por MCP, **filtrado por los permisos de
 * quien mira**: es justo lo que hay que comprobar antes de darle la exposición
 * a alguien. Se dice cuántas se ocultan por permisos, porque eso es lo que
 * explica que dos personas vean catálogos distintos de la misma exposición; y
 * si la exposición está detenida se dice por qué, en vez de una lista vacía.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";

interface Herramienta {
  nombre: string;
  descripcion?: string | null;
  tipo: string;
  exige_confirmacion?: boolean;
}

interface Catalogo {
  herramientas: Herramienta[];
  ocultas_por_permisos?: number;
  detenida: boolean;
  porque?: string;
}

export function HerramientasDeExposicion({ clave }: { clave: string }) {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Catalogo | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Catalogo>(
      `/api/v1/agentes-ia/${encodeURIComponent(clave)}/herramientas`,
      { signal: control.signal },
    )
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [clave]);

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("herramientasMcp.titulo")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("herramientasMcp.ayuda")}
      </p>
      {fallo ? <Fallo error={fallo} /> : null}
      {datos?.detenida ? (
        <p className="text-dato text-warning">
          {t("herramientasMcp.detenida")} {datos.porque ?? ""}
        </p>
      ) : null}
      {datos && !datos.detenida && datos.herramientas.length === 0 ? (
        <p className="text-dato text-ink-faint">
          {datos.porque || t("herramientasMcp.ninguna")}
        </p>
      ) : null}
      {datos && datos.herramientas.length > 0 ? (
        <ul className="lista-acotada flex flex-col gap-1 pr-1">
          {datos.herramientas.map((h) => (
            <li key={h.nombre} className="text-dato">
              <span className="font-mono text-ink">{h.nombre}</span>{" "}
              <span className="chip-dato">{h.tipo}</span>
              {h.exige_confirmacion ? (
                <span className="chip-dato chip-dato--aviso ml-1">
                  {t("herramientasMcp.confirmacion")}
                </span>
              ) : null}
              {h.descripcion ? (
                <span className="block text-rotulo text-ink-muted">
                  {h.descripcion}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {datos?.ocultas_por_permisos ? (
        <p className="mt-2 text-rotulo text-ink-muted">
          {t("herramientasMcp.ocultas", { n: datos.ocultas_por_permisos })}
        </p>
      ) : null}
    </section>
  );
}
