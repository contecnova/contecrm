/**
 * Qué del sistema enseña la interfaz, y qué no
 * (CRM-07.04.05.01, CRM-07.04.05.02).
 *
 * El informe normal es el de cobertura: cuántas operaciones publicadas tienen
 * pantalla. El que **nadie hace** es el de vuelta, y es el que importa aquí:
 * **qué sabe hacer el CRM que ninguna pantalla enseña**. Esa es la lista de
 * potencia escondida en la API — capacidades construidas, probadas y
 * documentadas que quien mira el producto concluye que no están.
 *
 * Se calcula en vivo cruzando la superficie con los módulos declarados. Un
 * informe guardado se queda viejo en cuanto alguien añade una ruta, y un
 * informe de cobertura viejo es peor que ninguno porque se decide sobre él.
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { MODULOS } from "@/lib/modulos";
import { cargarSuperficie, recursoDe, type Superficie } from "@/lib/superficie";
import { CabeceraPagina } from "@/componentes/Pagina";

export function Cobertura() {
  const { t } = useTranslation();
  const [superficie, setSuperficie] = useState<Superficie | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    cargarSuperficie(control.signal).then(setSuperficie).catch(setFallo);
    return () => control.abort();
  }, []);

  const informe = useMemo(() => (superficie ? calcular(superficie) : null), [superficie]);

  if (fallo) return <Fallo error={fallo} />;
  if (!informe) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("cobertura.titulo")}
        entradilla={t("cobertura.intro")}
        icono="fact_check"
      />

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Dato titulo={t("cobertura.publicadas")} valor={informe.publicadas} />
        <Dato titulo={t("cobertura.conPantalla")} valor={informe.conPantalla} />
        <Dato
          titulo={t("cobertura.sinPantalla")}
          valor={informe.sinPantalla.length}
          alerta={informe.sinPantalla.length > 0}
        />
      </div>

      <h2 className="mt-8 text-2xs font-medium uppercase tracking-wide text-ink-faint">
        {t("cobertura.escondido")}
      </h2>
      <p className="mt-1 text-2xs text-ink-faint">{t("cobertura.escondidoIntro")}</p>
      {informe.sinPantalla.length === 0 ? (
        <p className="mt-3 text-2xs text-success">{t("cobertura.todoEnsenado")}</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-1">
          {informe.sinPantalla.map((r) => (
            <li
              key={r.recurso}
              className="rounded-lg border border-ink-dim/30 bg-paper px-3 py-2 text-2xs"
            >
              <span className="font-mono text-ink">{r.recurso}</span>
              <span className="ml-2 text-ink-faint">
                {r.servicios.join(", ")} · {r.operaciones} {t("cobertura.operaciones")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function Dato({ titulo, valor, alerta }: { titulo: string; valor: number; alerta?: boolean }) {
  return (
    <div className="rounded-xl border border-ink-dim/60 bg-paper p-4">
      <p className="text-2xs text-ink-faint">{titulo}</p>
      <p className={`mt-1 text-lg ${alerta ? "text-warning" : "text-ink"}`}>{valor}</p>
    </div>
  );
}

export interface Informe {
  publicadas: number;
  conPantalla: number;
  sinPantalla: { recurso: string; servicios: string[]; operaciones: number }[];
}

export function calcular(superficie: Superficie): Informe {
  // Los recursos que alguna pantalla enseña salen de las rutas declaradas en
  // los módulos, no de una lista aparte: una lista aparte se queda vieja en
  // cuanto alguien añade una pestaña.
  const enseñados = new Set<string>();
  for (const modulo of MODULOS) {
    for (const recurso of modulo.recursos) enseñados.add(recursoDe(recurso.listar));
  }
  // La consola de administración enseña TODO lo marcado como administración,
  // porque se construye de la propia superficie.
  for (const operacion of superficie.operaciones) {
    if (operacion.administracion) enseñados.add(recursoDe(operacion.ruta));
  }

  const porRecurso = new Map<string, { servicios: Set<string>; operaciones: number }>();
  for (const operacion of superficie.operaciones) {
    const recurso = recursoDe(operacion.ruta);
    if (!recurso) continue;
    const dato = porRecurso.get(recurso) ?? { servicios: new Set<string>(), operaciones: 0 };
    dato.servicios.add(operacion.servicio);
    dato.operaciones += 1;
    porRecurso.set(recurso, dato);
  }

  const sinPantalla = [...porRecurso.entries()]
    .filter(([recurso]) => !enseñados.has(recurso))
    .map(([recurso, dato]) => ({
      recurso,
      servicios: [...dato.servicios].sort(),
      operaciones: dato.operaciones,
    }))
    .sort((a, b) => b.operaciones - a.operaciones);

  return {
    publicadas: superficie.total,
    conPantalla: superficie.total - sinPantalla.reduce((n, r) => n + r.operaciones, 0),
    sinPantalla,
  };
}
