/**
 * ALM: entornos, paquetes, promoción, desvío y vuelta atrás
 * (CRM-07.04.03.27).
 *
 * La pantalla que hace visible lo que de otro modo solo sabe quien lo hizo: qué
 * hay configurado en cada entorno, qué se ha promocionado y **qué tocó alguien a
 * mano un viernes**.
 *
 * Dos decisiones:
 *
 * **El desvío se enseña contra el paquete desplegado**, no contra otro entorno.
 * Comparar dos entornos dice en qué se diferencian —que puede ser legítimo—;
 * comparar contra lo desplegado dice qué se tocó fuera del camino, que es la
 * pregunta.
 *
 * **Y lo que desapareció también es desvío.** Un panel que solo enseña lo que se
 * añadió deja fuera el caso más incómodo: alguien borró algo en producción y
 * nadie lo sabe.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo, Vacio } from "@/componentes/Estados";
import { llamar } from "@/lib/api";

interface Diferencia {
  tipo: string;
  clave: string;
  que_paso: string;
}

interface Drift {
  hay_desvio: boolean;
  diferencias: Diferencia[];
  medible: boolean;
  que_significa: string;
}

export function Alm() {
  const { t } = useTranslation();
  const [entorno, setEntorno] = useState("produccion");
  const [datos, setDatos] = useState<Drift | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const mirar = async () => {
    setFallo(null);
    try {
      const r = await llamar<Drift>(`/api/v1/entornos/${entorno}/drift`);
      setDatos(r.datos);
    } catch (e) {
      setFallo(e);
    }
  };

  return (
    <>
      <h1 className="text-sm font-medium text-ink">{t("alm.titulo")}</h1>
      <p className="mt-1 text-2xs text-ink-faint">{t("alm.intro")}</p>

      <div className="mt-4 flex flex-wrap items-end gap-2">
        <div>
          <label className="block text-2xs text-ink-muted" htmlFor="alm-entorno">
            {t("alm.entorno")}
          </label>
          <select
            id="alm-entorno"
            className="mt-1 rounded-lg border border-ink-dim/60 bg-paper px-3 py-2 text-xs text-ink"
            value={entorno}
            onChange={(e) => setEntorno(e.target.value)}
          >
            <option value="desarrollo">desarrollo</option>
            <option value="pruebas">pruebas</option>
            <option value="preproduccion">preproducción</option>
            <option value="produccion">producción</option>
          </select>
        </div>
        <button
          type="button"
          onClick={mirar}
          className="rounded-lg bg-accent px-3 py-1.5 text-2xs text-paper"
        >
          {t("alm.verDesvio")}
        </button>
      </div>

      {fallo ? <Fallo error={fallo} /> : null}

      {datos && !datos.medible ? (
        <Vacio titulo={t("alm.sinPaquete")} detalle={datos.que_significa} />
      ) : null}

      {datos && datos.medible ? (
        <>
          <p
            className={`mt-4 text-xs ${datos.hay_desvio ? "text-warning" : "text-success"}`}
            role="status"
          >
            {datos.que_significa}
          </p>
          {datos.diferencias.length > 0 ? (
            <div className="mt-3 overflow-x-auto rounded-xl border border-ink-dim/60 bg-paper">
              <table className="w-full text-left text-2xs">
                <thead className="border-b border-ink-dim/30 bg-paper-light">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-medium text-ink-muted">
                      {t("alm.tipo")}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium text-ink-muted">
                      {t("alm.clave")}
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium text-ink-muted">
                      {t("alm.quePaso")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {datos.diferencias.map((d) => (
                    <tr
                      key={`${d.tipo}:${d.clave}`}
                      className="border-b border-ink-dim/30 last:border-0"
                    >
                      <td className="px-3 py-2 text-ink-muted">{d.tipo}</td>
                      <td className="px-3 py-2 text-ink">{d.clave}</td>
                      {/* Lo que desapareció se pinta igual que lo que se añadió:
                          es el caso que más se esconde. */}
                      <td className="px-3 py-2 text-ink-muted">{d.que_paso}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : null}
    </>
  );
}
