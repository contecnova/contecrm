/**
 * Consola única de gobierno de la suite (CRM-00.01.07.06).
 *
 * Quien administra contecrm administra también el resto de herramientas de la
 * casa, y hasta ahora eso significaba cuatro pantallas y cuatro sitios donde dar
 * de baja a alguien que se va — que es justo el momento en el que olvidarse de
 * uno tiene consecuencias.
 *
 * Por eso esta pantalla enseña primero **las bajas sin aplicar**, que es lo único
 * que hay que mirar con prisa: una baja que no llegó es un acceso que sigue
 * abierto en otra herramienta, y eso no lo ve nadie hasta una auditoría.
 *
 * Y dos cosas que se pintan a propósito:
 *
 * **Sin herramientas conectadas no se dice «todo bien».** Un verde silencioso
 * haría creer que el cliente está en la suite cuando solo está en el CRM.
 *
 * **Esto no es un panel de control remoto.** Cada herramienta sigue mandando en
 * lo suyo; aquí se ve lo que cada una publica.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { llamar } from "@/lib/api";

interface Herramienta {
  herramienta: string;
  tipo: string;
  activa: boolean;
  estado: string;
  bajas_sin_aplicar: number;
  ultimo_error: string | null;
}

interface Panel {
  herramientas: Herramienta[];
  cuarentena: number;
  bajas_sin_aplicar: number;
  en_verde: boolean;
  sin_herramientas: boolean;
}

export function SuiteGobierno() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Panel | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Panel>("/api/v1/suite/panel", { signal: control.signal })
      .then((r) => setDatos(r.datos))
      .catch(setFallo);
    return () => control.abort();
  }, []);

  if (fallo) return <Fallo error={fallo} />;
  if (!datos) return <Cargando />;

  return (
    <>
      <h1 className="text-sm font-medium text-ink">{t("suite.titulo")}</h1>
      <p className="mt-1 text-2xs text-ink-faint">{t("suite.intro")}</p>

      {datos.sin_herramientas ? (
        /* Un verde silencioso haría creer que el cliente está en la suite
           cuando solo está en el CRM. */
        <Vacio titulo={t("suite.sinHerramientas")} detalle={t("suite.sinHerramientasPorque")} />
      ) : (
        <>
          {/* Lo primero y aparte: una baja sin aplicar es un acceso abierto. */}
          <p
            className={`mt-4 text-xs ${
              datos.bajas_sin_aplicar > 0 ? "text-danger" : "text-success"
            }`}
            role="status"
          >
            {datos.bajas_sin_aplicar > 0
              ? t("suite.bajasSinAplicar", { cuantas: datos.bajas_sin_aplicar })
              : t("suite.sinBajasPendientes")}
          </p>

          <div className="mt-4 overflow-x-auto rounded-xl border border-ink-dim/60 bg-paper">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-ink-dim/30 bg-paper-light">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium text-ink-muted">
                    {t("suite.herramienta")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium text-ink-muted">
                    {t("suite.estado")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium text-ink-muted">
                    {t("suite.bajas")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium text-ink-muted">
                    {t("suite.ultimoError")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {datos.herramientas.map((h) => (
                  <tr key={h.herramienta} className="border-b border-ink-dim/30 last:border-0">
                    <td className="px-3 py-2 text-ink">{h.herramienta}</td>
                    <td
                      className={`px-3 py-2 ${h.activa ? "text-success" : "text-ink-faint"}`}
                    >
                      {h.estado}
                    </td>
                    <td
                      className={`px-3 py-2 ${
                        h.bajas_sin_aplicar > 0 ? "text-danger" : "text-ink-muted"
                      }`}
                    >
                      {h.bajas_sin_aplicar}
                    </td>
                    <td className="px-3 py-2 text-3xs text-ink-faint">
                      {h.ultimo_error ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {datos.cuarentena > 0 ? (
            <p className="mt-3 text-2xs text-warning">
              {t("suite.cuarentena", { cuantas: datos.cuarentena })}
            </p>
          ) : null}
        </>
      )}

      <p className="mt-6 text-3xs text-ink-faint">{t("suite.noEsControlRemoto")}</p>
    </>
  );
}
