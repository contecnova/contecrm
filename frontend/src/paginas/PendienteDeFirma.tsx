/**
 * Lo que está esperando una firma (CRM-06.01.02.10, CRM-06.01.02.03,
 * CRM-06.01.02.04).
 *
 * Es la pregunta del comercial que cierra un trimestre: **qué contratos están
 * parados y por quién**. El servidor la contesta desde el primer día en
 * `/api/v1/firma/panel` y no había forma de pedirla desde ninguna pantalla:
 * sólo se podía listar los sobres uno a uno, que es el inventario, no la
 * pregunta.
 *
 * Tres cosas que decide esta pantalla y que no son de estilo:
 *
 *   · **ordenado por lo que lleva más tiempo parado**, que es lo que hay que
 *     perseguir. Un listado por fecha de creación pone arriba lo recién
 *     mandado, que es lo único que no hay que tocar;
 *   · **«nadie lo ha abierto» se distingue de «abierto y sin firmar»**. El
 *     primero es un correo que no llegó —se reenvía—; el segundo es una
 *     decisión que no se toma —se llama por teléfono—. Mezclarlos hace perder
 *     el tiempo en la mitad de los casos;
 *   · y **a quién le toca, por su nombre**. «2 de 3 firmado» no dice a quién
 *     hay que llamar, que es lo único que se va a hacer con este dato.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";

interface Sobre {
  sobre_id: string;
  referencia: string;
  asunto: string;
  estado: string;
  nivel: string;
  proveedor: string;
  objeto_origen: string | null;
  objeto_origen_id: string | null;
  dias_esperando: number;
  firmados: number;
  total: number;
  esperando_a: string[];
  caduca_en_dias: number | null;
  nadie_lo_ha_abierto: boolean;
}

interface Llamadas {
  llamadas: {
    id: string;
    proveedor: string;
    operacion: string;
    codigo: number | null;
    ok: boolean;
    coste: string | null;
    error: string | null;
    cuando: string;
  }[];
  cuantas: number;
  gasto: string;
  fallidas: number;
  gasto_de_las_fallidas: string;
  /** Por qué no hay filas. Vacío cuando sí las hay. */
  aviso: string;
}

interface Panel {
  sobres: Sobre[];
  cuantos: number;
  medible: boolean;
}

export function PendienteDeFirma() {
  const { t } = useTranslation();
  const [panel, setPanel] = useState<Panel | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Panel>("/api/v1/firma/panel?limite=100", { signal: control.signal })
      .then((r) => setPanel(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!panel) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("firma.titulo")}
        icono="draw"
        entradilla={t("firma.entradilla")}
      />

      {/* Sin sobres abiertos NO se dice «todo firmado»: es que no hay nada
          esperando, y un verde vacío se lee igual que uno ganado. */}
      {!panel.medible ? (
        <Vacio
          titulo={t("firma.nadaEsperando")}
          detalle={t("firma.nadaEsperandoDetalle")}
        />
      ) : (
        <>
          <p className="mb-3 text-2xs text-ink-muted" role="status">
            {t("firma.cuantos", { cuantos: panel.cuantos })}
          </p>
          <ul className="space-y-2">
            {panel.sobres.map((sobre) => (
              <li key={sobre.sobre_id} className="card p-3">
                <div className="flex flex-wrap items-baseline gap-x-3">
                  {/* Los días parados, delante y grandes: es el número por el
                      que se entra aquí. */}
                  <span
                    className={
                      sobre.dias_esperando >= 7
                        ? "text-lg font-semibold leading-none text-danger"
                        : "text-lg font-semibold leading-none text-ink"
                    }
                  >
                    {t("firma.diasParado", { dias: sobre.dias_esperando })}
                  </span>
                  <span className="text-sm font-medium text-ink">
                    {sobre.asunto}
                  </span>
                  <span className="text-3xs text-ink-faint">
                    {sobre.referencia}
                  </span>
                  <span className="chip-dato">{sobre.nivel}</span>
                  <span className="chip-dato">{sobre.proveedor}</span>
                </div>

                <div className="mt-1 flex flex-wrap items-baseline gap-x-3">
                  <span className="text-2xs text-ink-muted">
                    {t("firma.firmados", {
                      firmados: sobre.firmados,
                      total: sobre.total,
                    })}
                  </span>
                  {/* Un correo que no llegó y una decisión que no se toma se
                      persiguen de forma distinta. */}
                  {sobre.nadie_lo_ha_abierto ? (
                    <span className="chip-dato chip-dato--no">
                      {t("firma.nadieLoHaAbierto")}
                    </span>
                  ) : null}
                  {sobre.caduca_en_dias !== null ? (
                    <span
                      className={
                        sobre.caduca_en_dias <= 3
                          ? "text-3xs text-danger"
                          : "text-3xs text-ink-muted"
                      }
                    >
                      {t("firma.caducaEn", { dias: sobre.caduca_en_dias })}
                    </span>
                  ) : null}
                  <Link
                    to={`/m/operacion/sobre_firma/${sobre.sobre_id}`}
                    className="btn-link text-3xs"
                  >
                    {t("firma.abrirSobre")}
                  </Link>
                </div>

                {/* A quién le toca, por su nombre: «2 de 3» no dice a quién
                    hay que llamar, que es lo único que se va a hacer. */}
                {sobre.esperando_a.length > 0 ? (
                  <p className="mt-1 flex flex-wrap items-center gap-1 text-3xs text-ink-muted">
                    <Icono nombre="hourglass_empty" /> {t("firma.esperandoA")}
                    {sobre.esperando_a.map((quien) => (
                      <span key={quien} className="chip-dato">
                        {quien}
                      </span>
                    ))}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      )}

      {/* Lo que el proveedor cobró, al lado de lo que hizo. */}
      <LoQueCobraElProveedor />
    </>
  );
}

/**
 * Qué se le pidió al proveedor de firma, qué contestó y cuánto costó
 * (`CRM-06.01.02.15`).
 *
 * El registro se escribía desde el primer día y **no lo leía nadie**: no había
 * ninguna ruta que lo devolviera. La capacidad dice «para conciliar la
 * factura», y un registro que no se puede leer no concilia nada — ni sirve
 * para desatascar un sobre a las dos de la mañana, que es la otra vez que se
 * mira.
 *
 * Dos cosas que se enseñan a propósito:
 *
 * - **el gasto sumado**, porque conciliar una factura con doscientos importes
 *   en pantalla es volver a sumarlos a mano;
 * - **las fallidas aparte, con su gasto**. Un proveedor que cobra por intento
 *   hace que el importe y el número de sobres no cuadren, y esa diferencia es
 *   lo primero que se busca en una factura que no sale.
 *
 * Y sin filas no se dice «cero gasto»: se dice que no consta ninguna llamada.
 * Un cero ahí se leería como «el proveedor no ha cobrado nada».
 */
function LoQueCobraElProveedor() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Llamadas | null>(null);
  const [soloFallidas, setSoloFallidas] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Llamadas>(
      `/api/v1/firma/llamadas?solo_fallidas=${soloFallidas}&limite=200`,
      {
        signal: control.signal,
      },
    )
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [soloFallidas]);

  return (
    <section className="card mt-6 p-4">
      <h2 className="section-label mb-1">{t("firma.llamadas.titulo")}</h2>
      <p className="mb-3 max-w-prose text-2xs text-ink-muted">
        {t("firma.llamadas.porQue")}
      </p>

      <label className="flex items-center gap-2 text-2xs text-ink-muted">
        <input
          type="checkbox"
          checked={soloFallidas}
          onChange={(e) => setSoloFallidas(e.target.checked)}
        />
        {t("firma.llamadas.soloFallidas")}
      </label>

      {fallo ? <Fallo error={fallo} /> : null}
      <div role="status" aria-live="polite" className="mt-3">
        {datos ? (
          datos.aviso ? (
            <p className="text-2xs text-ink-muted">{datos.aviso}</p>
          ) : (
            <p className="text-2xs text-ink">
              {t("firma.llamadas.resumen", {
                cuantas: datos.cuantas,
                gasto: datos.gasto,
              })}
              {datos.fallidas > 0 ? (
                <span className="ml-2 text-warning">
                  {t("firma.llamadas.deEllasFallidas", {
                    fallidas: datos.fallidas,
                    gasto: datos.gasto_de_las_fallidas,
                  })}
                </span>
              ) : null}
            </p>
          )
        ) : null}
      </div>

      {datos && datos.llamadas.length > 0 ? (
        <ul className="lista-acotada mt-2 divide-y divide-ink-dim/30 pr-1">
          {datos.llamadas.map((l) => (
            <li key={l.id} className="py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="text-2xs text-ink">{l.operacion}</span>
                <span className="text-3xs text-ink-muted">{l.proveedor}</span>
                <span
                  className={`badge ${l.ok ? "badge-muted" : "badge-danger"}`}
                >
                  {l.codigo ?? "—"}
                </span>
                <span className="font-mono text-3xs text-ink-faint">
                  {l.coste ?? t("firma.llamadas.sinCoste")}
                </span>
              </div>
              {/* El error entero: es lo que se lee para desatascar, y
                  recortarlo obliga a ir al registro del servidor — justo lo
                  que esta tabla existe para evitar. */}
              {l.error ? (
                <p className="mt-0.5 text-3xs text-danger">{l.error}</p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
