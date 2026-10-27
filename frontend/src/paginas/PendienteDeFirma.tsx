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
        <Vacio titulo={t("firma.nadaEsperando")} detalle={t("firma.nadaEsperandoDetalle")} />
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
                  <span className="text-sm font-medium text-ink">{sobre.asunto}</span>
                  <span className="text-3xs text-ink-faint">{sobre.referencia}</span>
                  <span className="chip-dato">{sobre.nivel}</span>
                  <span className="chip-dato">{sobre.proveedor}</span>
                </div>

                <div className="mt-1 flex flex-wrap items-baseline gap-x-3">
                  <span className="text-2xs text-ink-muted">
                    {t("firma.firmados", { firmados: sobre.firmados, total: sobre.total })}
                  </span>
                  {/* Un correo que no llegó y una decisión que no se toma se
                      persiguen de forma distinta. */}
                  {sobre.nadie_lo_ha_abierto ? (
                    <span className="chip-dato chip-dato--no">{t("firma.nadieLoHaAbierto")}</span>
                  ) : null}
                  {sobre.caduca_en_dias !== null ? (
                    <span
                      className={
                        sobre.caduca_en_dias <= 3 ? "text-3xs text-danger" : "text-3xs text-ink-muted"
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
    </>
  );
}
