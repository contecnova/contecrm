/**
 * Un módulo vertical instalado, con todo lo suyo (CRM-00.04.04.01,
 * CRM-00.04.04.03, CRM-00.04.04.04, CRM-00.04.04.05, CRM-00.04.04.07,
 * CRM-00.04.04.08, CRM-00.04.04.10).
 *
 * **La familia entera estaba publicada y sin puerta.** El servidor contesta si
 * el módulo sigue siendo el del catálogo, qué partes usa el cliente de verdad,
 * qué ajustó a mano, qué pantallas aporta y qué pasaría con los datos al
 * desinstalarlo — y nada de eso se alcanzaba desde el producto. El módulo
 * «Modelo de datos» listaba los instalados con su versión, y ahí se acababa.
 *
 * Las tres preguntas que de verdad se hacen delante de un módulo, y en este
 * orden:
 *
 *   · **¿sigue siendo el que instalamos?** Lo contesta la integridad,
 *     comparando con el catálogo. Y cuando no se puede comparar —el módulo se
 *     instaló desde un fichero, o esa versión se retiró— lo dice en vez de
 *     dar un visto bueno: un «íntegro» calculado sobre nada es peor que un «no
 *     se sabe»;
 *   · **¿sobra?** Lo contesta la telemetría: qué elementos se usan y cuáles no
 *     se han tocado nunca. Con su aviso cuando lleva pocos días instalado,
 *     porque concluir que algo sobra a los dos días es concluir sobre nada;
 *   · **¿qué pierdo si lo quito?** Lo que se borra y lo que se queda, antes de
 *     tocar el botón y no después.
 *
 * Lo que esta pantalla **no** declara, aunque lo roce: `CRM-00.04.04.02`
 * —instalar, actualizar y desinstalar— y `CRM-00.04.04.09` —desinstalar
 * diciendo qué pasa con los datos—, porque las dos son acciones y aquí no hay
 * botón que las dispare; `CRM-00.04.04.06` —los conectores que vienen dentro
 * de un módulo—, porque aquí se ve el módulo y no sus conectores; y
 * `CRM-00.04.04.11` —el módulo de ejemplo documentado—, que es un entregable
 * del repositorio y no una pantalla.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";

interface Modulo {
  clave: string;
  nombre: string;
  version: string;
  autor: string;
  estado: string;
  instalado_at: string | null;
  objetos?: string[];
  campos?: number;
  espacio_de_nombres?: string;
  depende_de?: Record<string, string>;
  nucleo_minimo?: string;
  huella?: string;
}

interface Integridad {
  modulo: string;
  medible: boolean;
  motivo?: string;
  integro?: boolean;
  tocados_a_mano?: string[];
  desaparecidos?: string[];
}

interface Telemetria {
  modulo: string;
  version: string;
  instalado_hace_dias: number;
  elementos: number;
  usados: number;
  sin_usar: string[];
  modificados_por_el_cliente: string[];
  mas_usados: { elemento: string; veces: number }[];
  concluyente: boolean;
  aviso: string;
}

interface Superficie {
  modulos: { clave: string; nombre: string; version: string }[];
  pantallas: { modulo: string; clave: string; titulo?: string }[];
}

export function ModuloInstalado() {
  const { t } = useTranslation();
  const { clave = "" } = useParams();
  const [modulo, setModulo] = useState<Modulo | null>(null);
  const [integridad, setIntegridad] = useState<Integridad | null>(null);
  const [telemetria, setTelemetria] = useState<Telemetria | null>(null);
  const [superficie, setSuperficie] = useState<Superficie | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    const opciones = { signal: control.signal };
    // Las cuatro a la vez: en serie la pantalla tarda la suma y se lee como
    // lenta aunque cada una vaya rápida.
    llamar<Modulo>(`/api/v1/metadata/modulos/${clave}`, opciones)
      .then((r) => setModulo(r.datos))
      .catch(salvoCancelacion(setFallo));
    void llamar<Integridad>(`/api/v1/metadata/modulos/${clave}/integridad`, opciones)
      .then((r) => setIntegridad(r.datos))
      .catch(() => undefined);
    void llamar<Telemetria>(`/api/v1/metadata/modulos/${clave}/telemetria`, opciones)
      .then((r) => setTelemetria(r.datos))
      .catch(() => undefined);
    void llamar<Superficie>("/api/v1/metadata/modulos/superficie", opciones)
      .then((r) => setSuperficie(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, [clave]);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!modulo) return <Cargando />;

  const pantallas = (superficie?.pantallas ?? []).filter((p) => p.modulo === clave);

  return (
    <div className="flex flex-col gap-4">
      <CabeceraPagina
        titulo={modulo.nombre || modulo.clave}
        entradilla={t("modulo.entradilla", {
          version: modulo.version,
          autor: modulo.autor || t("modulo.sinAutor"),
          estado: modulo.estado,
        })}
        icono="extension"
      />

      {/* 0. Lo que el módulo declara. Va primero porque es la pieza de la que
             vive todo lo demás: la integridad compara contra esto y la
             telemetría cuenta sobre esto. */}
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("modulo.manifiesto")}</h2>
        <p className="text-sm text-ink" data-testid="modulo-manifiesto">
          {t("modulo.trae", {
            objetos: (modulo.objetos ?? []).length,
            campos: modulo.campos ?? 0,
          })}
          {(modulo.objetos ?? []).length
            ? `: ${(modulo.objetos ?? []).slice(0, 8).join(", ")}`
            : ""}
        </p>
        {/* El espacio de nombres, que es lo que impide que dos módulos de
            sectores distintos se pisen un objeto llamado «pedido». */}
        <p className="mt-1 text-3xs text-ink-muted">
          {t("modulo.espacioDeNombres", { prefijo: modulo.espacio_de_nombres || modulo.clave })}
        </p>
        <p className="text-3xs text-ink-muted">
          {Object.keys(modulo.depende_de ?? {}).length
            ? t("modulo.dependeDe", {
                cuales: Object.entries(modulo.depende_de ?? {})
                  .map(([m, v]) => `${m} ${v}`)
                  .join(", "),
              })
            : t("modulo.sinDependencias")}
          {modulo.nucleo_minimo ? ` · ${t("modulo.nucleo", { version: modulo.nucleo_minimo })}` : ""}
        </p>
        {/* La huella: es lo que convierte «de quién es este módulo» en algo
            comprobable y no en una línea del manifiesto que cualquiera
            escribe. Si no consta, se dice. */}
        <p className="mt-1 font-mono text-3xs text-ink-faint">
          {modulo.huella
            ? t("modulo.huella", { huella: modulo.huella.slice(0, 16) })
            : t("modulo.sinHuella")}
        </p>
      </section>

      {/* 1. ¿Sigue siendo el que instalamos? */}
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("modulo.integridad")}</h2>
        {integridad?.medible === false ? (
          /* Y cuando no se puede comparar se DICE, con su motivo. Un «íntegro»
             calculado sobre nada es peor que un «no se sabe». */
          <p className="text-sm text-ink-muted" data-testid="modulo-integridad">
            {integridad.motivo}
          </p>
        ) : integridad ? (
          <div data-testid="modulo-integridad">
            <p
              className={
                integridad.integro ? "text-sm text-success" : "text-sm text-warning"
              }
            >
              {integridad.integro ? t("modulo.integro") : t("modulo.tocado")}
            </p>
            {(integridad.tocados_a_mano ?? []).length ? (
              <p className="mt-1 text-3xs text-ink-muted">
                {t("modulo.tocadosAMano", {
                  cuales: integridad.tocados_a_mano?.slice(0, 6).join(", "),
                })}
              </p>
            ) : null}
            {/* Lo desaparecido al lado de lo tocado: un panel que sólo enseña
                lo añadido deja fuera el caso que más se esconde, que es que
                alguien borró algo. */}
            {(integridad.desaparecidos ?? []).length ? (
              <p className="text-3xs text-warning">
                {t("modulo.desaparecidos", {
                  cuales: integridad.desaparecidos?.slice(0, 6).join(", "),
                })}
              </p>
            ) : null}
          </div>
        ) : (
          <Cargando />
        )}
      </section>

      {/* 2. ¿Sobra? */}
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("modulo.uso")}</h2>
        {telemetria ? (
          <div data-testid="modulo-telemetria">
            <p className="text-sm text-ink">
              {t("modulo.usados", {
                usados: telemetria.usados,
                elementos: telemetria.elementos,
              })}
            </p>
            {/* El aviso ANTES de la lista: concluir que algo sobra a los dos
                días de instalarlo es concluir sobre nada, y la lista invita a
                hacerlo. */}
            {!telemetria.concluyente && telemetria.aviso ? (
              <p className="mt-1 text-3xs text-warning">{telemetria.aviso}</p>
            ) : null}
            {telemetria.sin_usar.length ? (
              <p className="mt-1 text-3xs text-ink-muted">
                {t("modulo.sinUsar", {
                  cuales: telemetria.sin_usar.slice(0, 8).join(", "),
                })}
              </p>
            ) : null}
            {telemetria.modificados_por_el_cliente.length ? (
              <p className="text-3xs text-ink-faint">
                {t("modulo.ajustados", {
                  cuales: telemetria.modificados_por_el_cliente.slice(0, 6).join(", "),
                })}
              </p>
            ) : null}
          </div>
        ) : (
          <Cargando />
        )}
      </section>

      {/* 3. Qué aporta a la interfaz: el front oficial no sabe de este módulo
             más que lo que el módulo declara. */}
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("modulo.pantallas")}</h2>
        {pantallas.length === 0 ? (
          <Vacio
            titulo={t("modulo.sinPantallas")}
            detalle={t("modulo.sinPantallasPorque")}
          />
        ) : (
          <ul className="divide-y divide-ink-dim/30" data-testid="modulo-pantallas">
            {pantallas.map((p) => (
              <li key={p.clave} className="py-1.5 text-sm text-ink">
                {p.titulo || p.clave}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
