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
 *
 * **Lo que no se ha comparado se dice.** La vista rápida solo sabe leer los
 * campos de un objeto; los otros siete tipos de contenido no se miran. Pintar
 * «limpio» tapando eso es la mentira más fácil de esta pantalla.
 *
 * Esta pantalla leía `hay_desvio` y `diferencias`, que el servidor no manda
 * nunca: manda `limpio`, `tocado_a_mano` y `desaparecido`. El primero llegaba
 * `undefined` —siempre en verde, dijera lo que dijera el texto de al lado— y el
 * segundo reventaba la pantalla entera al leerle `.length`. Medido el
 * 26-10-2026 recorriendo la ruta de verdad.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo, Vacio } from "@/componentes/Estados";
import { llamar } from "@/lib/api";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";

/** Lo que el servidor manda de cada cosa tocada a mano. */
interface Tocado {
  /** `<tipo>.<clave>`: «campos.nif». */
  elemento: string;
  que_paso: string;
  /** Qué campos concretos se cambiaron, cuando el elemento ya existía. */
  campos?: string[];
}

interface Drift {
  medible: boolean;
  /** Por qué no se puede medir. Solo viene cuando `medible` es `false`. */
  porque?: string;
  limpio?: boolean;
  tocado_a_mano?: Tocado[];
  /** Lo que el paquete traía y ya no está, como `<tipo>.<clave>`. */
  desaparecido?: string[];
  comparado?: string[];
  no_comparado?: string[];
  que_significa?: string;
}

/** Una fila de la tabla, venga de lo tocado o de lo desaparecido. */
interface Fila {
  tipo: string;
  clave: string;
  que_paso: string;
}

/** `campos.nif` → tipo «campos», clave «nif». Se parte por el PRIMER punto: la
 * clave puede llevar los suyos. */
function partir(elemento: string): [string, string] {
  const corte = elemento.indexOf(".");
  return corte < 0 ? ["", elemento] : [elemento.slice(0, corte), elemento.slice(corte + 1)];
}

function filas(datos: Drift): Fila[] {
  const tocado = (datos.tocado_a_mano ?? []).map((d) => {
    const [tipo, clave] = partir(d.elemento);
    return {
      tipo,
      clave,
      que_paso: d.campos?.length ? `${d.que_paso}: ${d.campos.join(", ")}` : d.que_paso,
    };
  });
  // Lo que desapareció se pinta igual que lo que se añadió: es el caso que más
  // se esconde.
  const ido = (datos.desaparecido ?? []).map((e) => {
    const [tipo, clave] = partir(e);
    return { tipo, clave, que_paso: "estaba en el paquete y ya no está" };
  });
  return [...tocado, ...ido];
}

/** Lo que hay puesto en el entorno: `GET /entornos/{entorno}/desplegado`. */
interface Desplegado {
  hay: boolean;
  porque?: string;
  paquete?: string;
  version?: number;
  /** De qué commit sale. Vacío es legítimo: se montó desde la consola. */
  referencia_git?: string;
  desplegado_at?: string | null;
  motivo?: string;
  que_significa?: string;
}

/** Un entorno declarado, de `GET /api/v1/entornos`. */
interface Entorno {
  nombre: string;
  orden: number;
  es_produccion: boolean;
}

export function Alm() {
  const { t } = useTranslation();
  const [entorno, setEntorno] = useState("produccion");
  // Los entornos SE PIDEN. Estaban escritos a mano en el desplegable —cuatro
  // `<option>`— mientras el servidor los publicaba: un entorno nuevo no
  // aparecía aquí hasta que alguien editara el front, y el síntoma no era un
  // error sino que ese entorno no existía para quien mira el desvío.
  const [entornos, setEntornos] = useState<Entorno[] | null>(null);
  const [datos, setDatos] = useState<Drift | null>(null);
  const [puesto, setPuesto] = useState<Desplegado | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<{ items: Entorno[] }>("/api/v1/entornos", { signal: control.signal })
      .then((r) => setEntornos(r.datos.items ?? []))
      // Si no se pueden pedir, se queda el que hay seleccionado: mejor un
      // desplegable con una opción que una pantalla que no deja mirar nada.
      .catch(() => setEntornos([]));
    return () => control.abort();
  }, []);

  const mirar = async () => {
    setFallo(null);
    try {
      // Las dos preguntas se hacen a la vez porque se piensan a la vez: «qué
      // hay puesto aquí» y «qué se ha tocado por encima». Enseñar el desvío sin
      // decir contra qué se compara deja el informe sin referencia.
      const [desvio, hay] = await Promise.all([
        llamar<Drift>(`/api/v1/entornos/${entorno}/drift`),
        llamar<Desplegado>(`/api/v1/entornos/${entorno}/desplegado`),
      ]);
      setDatos(desvio.datos);
      setPuesto(hay.datos);
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
            {(entornos ?? [{ nombre: entorno, orden: 0, es_produccion: true }])
              .slice()
              .sort((a, b) => a.orden - b.orden)
              .map((e) => (
                <option key={e.nombre} value={e.nombre}>
                  {e.nombre}
                </option>
              ))}
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

      {puesto ? (
        <p className="mt-4 text-2xs text-ink-muted" data-testid="alm-desplegado">
          {puesto.hay
            ? t("alm.puesto", {
                paquete: puesto.paquete,
                version: puesto.version,
                // Un paquete montado desde la consola no tiene commit al que
                // volver, y decirlo es la mitad de la respuesta.
                git: puesto.referencia_git || t("alm.sinGit"),
              })
            : puesto.porque}
        </p>
      ) : null}

      {datos && !datos.medible ? (
        <Vacio titulo={t("alm.sinPaquete")} detalle={datos.porque} />
      ) : null}

      {datos && datos.medible ? (
        <>
          <p
            className={`mt-4 text-xs ${datos.limpio ? "text-success" : "text-warning"}`}
            role="status"
          >
            {datos.que_significa}
          </p>
          {datos.no_comparado?.length ? (
            <p className="mt-1 text-2xs text-ink-muted">
              {t("alm.noComparado", { tipos: datos.no_comparado.join(", ") })}
            </p>
          ) : null}
          {filas(datos).length > 0 ? (
            <Rejilla
              compacta
              className="mt-3"
              cabeceras={[t("alm.tipo"), t("alm.clave"), t("alm.quePaso")]}
            >
              {filas(datos).map((d) => (
                <tr
                  key={`${d.tipo}:${d.clave}`}
                  className="border-b border-ink-dim/30 last:border-0"
                >
                  <Casilla className="text-ink-muted">{d.tipo}</Casilla>
                  <Casilla className="text-ink">{d.clave}</Casilla>
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
