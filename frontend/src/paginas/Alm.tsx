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
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";

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
      <CabeceraPagina
        titulo={t("alm.titulo")}
        entradilla={t("alm.intro")}
        icono="layers"
      />

      <div className="mt-4 flex flex-wrap items-end gap-2">
        <div>
          <label
            className="block text-2xs text-ink-muted"
            htmlFor="alm-entorno"
          >
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
            <Rejilla
              compacta
              className="mt-3"
              cabeceras={[t("alm.tipo"), t("alm.clave"), t("alm.quePaso")]}
            >
              {datos.diferencias.map((d) => (
                <tr
                  key={`${d.tipo}:${d.clave}`}
                  className="border-b border-ink-dim/30 last:border-0"
                >
                  <Casilla className="text-ink-muted">{d.tipo}</Casilla>
                  <Casilla className="text-ink">{d.clave}</Casilla>
                  {/* Lo que desapareció se pinta igual que lo que se añadió:
                          es el caso que más se esconde. */}
                  <Casilla className="text-ink-muted">{d.que_paso}</Casilla>
                </tr>
              ))}
            </Rejilla>
          ) : null}
        </>
      ) : null}
    </>
  );
}
