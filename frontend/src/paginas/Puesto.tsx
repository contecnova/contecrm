/**
 * El puesto de trabajo: correo y calendario conectados (CRM-07.04.03.24).
 *
 * Lo que enseña esta pantalla no es «está conectado»: es **si está entrando algo
 * y desde cuándo no**. Es la diferencia entre un panel que tranquiliza y uno que
 * sirve.
 *
 * Tres decisiones:
 *
 * **Lo que no se ha medido no cuenta como verde.** Una conexión sin última
 * sincronización no es una conexión sana, es una de la que no se sabe nada.
 *
 * **Lo que va por sondeo se dice.** Sus cambios entran con retraso en vez de al
 * instante, y el usuario tiene derecho a saber por qué su cita tarda diez
 * minutos en aparecer.
 *
 * **Y el consentimiento es suyo.** Desde aquí se ve qué autorizó cada persona,
 * recurso a recurso, y se puede revocar — pero nadie puede autorizar por otro.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";
import { CabeceraPagina } from "@/componentes/Pagina";

interface Parada {
  conexion: string;
  horas_sin_sincronizar: number;
  estado: string;
  porque: string;
}

interface Salud {
  total: number;
  paradas: Parada[];
  sin_medir: string[];
  en_sondeo: string[];
  todo_bien: boolean;
  medible: boolean;
  que_significa: string;
  los_en_sondeo: string;
}

export function Puesto() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Salud | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Salud>("/api/v1/suites/salud", { signal: control.signal })
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  if (fallo) return <Fallo error={fallo} />;
  if (!datos) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("puesto.titulo")}
        entradilla={t("puesto.intro")}
        icono="desk"
      />

      {!datos.medible ? (
        <Vacio titulo={t("puesto.sinConexiones")} detalle={datos.que_significa} />
      ) : (
        <>
          <p
            className={`mt-4 text-xs ${datos.todo_bien ? "text-success" : "text-warning"}`}
            role="status"
          >
            {datos.que_significa}
          </p>

          {datos.paradas.length > 0 ? (
            <section className="mt-4">
              <h2 className="text-xs font-medium text-danger">{t("puesto.paradas")}</h2>
              <ul className="mt-2 space-y-1">
                {datos.paradas.map((p) => (
                  <li key={p.conexion} className="text-2xs text-ink">
                    {p.conexion} · {t("puesto.horas", { horas: p.horas_sin_sincronizar })} ·{" "}
                    <span className="text-ink-muted">{p.porque}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {/* Lo que no se ha medido no se pinta en verde: es una conexión de la
              que no se sabe nada. */}
          {datos.sin_medir.length > 0 ? (
            <p className="mt-4 text-2xs text-warning">
              {t("puesto.sinMedir", { cuantas: datos.sin_medir.length })}
            </p>
          ) : null}

          {datos.los_en_sondeo ? (
            <p className="mt-2 text-2xs text-ink-muted">{datos.los_en_sondeo}</p>
          ) : null}
        </>
      )}
    </>
  );
}
