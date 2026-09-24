/**
 * Rendimiento a la vista: volumetría, límites y por qué algo tarda
 * (CRM-07.04.03.29).
 *
 * La pregunta que llega a soporte no es «¿cuál es vuestro p95?»: es **«¿por qué
 * mi lista tarda?»**. Esta pantalla contesta esa, y por eso enseña tres cosas
 * juntas que normalmente están en tres sitios:
 *
 * **Cuánto hay** —volumen por objeto—, porque una lista de dos millones de filas
 * tarda por motivos distintos que una de dos mil.
 *
 * **Cuánto cabe** —los límites del plan—, con aviso antes y no cuando ya no cabe
 * nada.
 *
 * **Y qué se está aplazando ahora mismo.** Si el sistema está bajo presión, los
 * recálculos y los informes pesados esperan: saberlo evita la mitad de los avisos
 * de «no me sale el informe».
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";
import { cargarSesion } from "@/lib/sesion";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";

interface Presion {
  peor?: { servicio?: string; presion?: number; que_significa?: string };
  sin_respuesta: string[];
  que_significa: string;
  aviso: string;
}

interface Uso {
  metrica: string;
  consumido: number;
  limite: number;
  pct: number;
  en_aviso: boolean;
}

export function Rendimiento() {
  const { t } = useTranslation();
  const [presion, setPresion] = useState<Presion | null>(null);
  const [cuotas, setCuotas] = useState<Uso[] | null>(null);
  const [tenant, setTenant] = useState<string>("");
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Presion>("/api/v1/estado/presion", { signal: control.signal })
      .then((r) => setPresion(r.datos))
      .catch(salvoCancelacion(setFallo));
    // Las cuotas se piden aparte y su fallo no tumba la página: saber qué se
    // está aplazando es lo urgente cuando algo va lento.
    cargarSesion(control.signal)
      .then((s) => {
        if (!s?.tenant_id) return null;
        setTenant(s.tenant_id);
        return llamar<Uso[]>(`/api/v1/tenants/${s.tenant_id}/consumo`, {
          signal: control.signal,
        });
      })
      .then((r) => (r ? setCuotas(r.datos) : undefined))
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  if (fallo) return <Fallo error={fallo} />;
  if (!presion) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("rendimiento.titulo")}
        entradilla={t("rendimiento.intro")}
        icono="speed"
      />

      <section className="mt-4 rounded-xl border border-ink-dim/60 bg-paper p-4">
        <h2 className="text-xs font-medium text-ink">
          {t("rendimiento.queSeAplaza")}
        </h2>
        <p className="mt-2 text-2xs text-ink-muted" role="status">
          {presion.que_significa}
        </p>
        {/* Un servicio que no contesta no cuenta como tranquilo: suele ser el
            que está peor. */}
        {presion.aviso ? (
          <p className="mt-2 text-2xs text-warning">{presion.aviso}</p>
        ) : null}
      </section>

      {cuotas ? (
        <section className="mt-4">
          <h2 className="text-xs font-medium text-ink">
            {t("rendimiento.limites")}
            {tenant ? (
              <span className="ml-2 text-3xs text-ink-faint">{tenant}</span>
            ) : null}
          </h2>
          <Rejilla
            compacta
            className="mt-2"
            cabeceras={[
              t("rendimiento.recurso"),
              t("rendimiento.usado"),
              t("rendimiento.limite"),
            ]}
          >
            {cuotas.map((u) => (
              <tr
                key={u.metrica}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla className="text-ink">{u.metrica}</Casilla>
                <Casilla
                  className={`${u.en_aviso ? "text-warning" : "text-ink-muted"}`}
                >
                  {u.consumido} ({u.pct} %)
                </Casilla>
                {/* Sin límite no se pinta «ilimitado»: se pinta que no
                        consta, que es lo que es. */}
                <Casilla className="text-ink-faint">
                  {u.limite > 0 ? u.limite : t("rendimiento.noConsta")}
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        </section>
      ) : null}
    </>
  );
}
