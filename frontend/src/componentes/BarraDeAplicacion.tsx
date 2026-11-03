/**
 * La barra de aplicación: el nombre de dónde estás y sus pestañas.
 *
 * Sustituye a la barra lateral de 29 entradas. La idea es la de Salesforce y
 * se copia a propósito: **se trabaja dentro de una aplicación cada vez**, y
 * arriba sólo están sus pestañas. A las demás se va por el lanzador, y la
 * configuración vive detrás de su propia puerta.
 *
 * Medido el 01-11-2026, antes: 24 módulos del catálogo, ~35 pantallas a mano y
 * 211 pestañas dentro de ellas, todo colgando del mismo menú lateral, con
 * «Cuentas y contactos» y «Contrato de la API» a la misma altura.
 *
 * **Las pestañas que no caben se van a «Más», medido y no adivinado.** Un
 * número fijo —«las ocho primeras»— se queda corto en una pantalla ancha y se
 * desborda en una estrecha; aquí se miden los anchos de verdad y se corta
 * donde deja de caber, y se vuelve a calcular cuando cambia el tamaño de la
 * ventana. La pestaña ACTIVA nunca se va a «Más»: la que dice dónde estás no
 * puede estar escondida.
 */

import { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import {
  MenuDeAcciones,
  type OpcionDeMenu,
} from "@/componentes/MenuDeAcciones";
import type { Aplicacion } from "@/lib/aplicaciones";
import type { Entrada } from "@/lib/navegacion";
import { cn } from "@/lib/utiles";

/** Lo que hay que dejar libre para el botón «Más». Medido: 86 px a 13 px de letra. */
const RESERVA_MAS = 92;

/** ¿Este camino está dentro de esta entrada? */
function activa(camino: string, entrada: Entrada): boolean {
  return camino === entrada.a || camino.startsWith(entrada.a + "/");
}

export function BarraDeAplicacion({
  aplicacion,
  pestanas,
  alAbrirLanzador,
}: {
  aplicacion: Aplicacion;
  pestanas: Entrada[];
  alAbrirLanzador: () => void;
}) {
  const { t } = useTranslation();
  const navegar = useNavigate();
  const { pathname } = useLocation();

  const caja = useRef<HTMLDivElement>(null);
  const anchos = useRef<number[]>([]);
  const [cuantas, setCuantas] = useState(pestanas.length);

  // Se mide en `useLayoutEffect` y no en `useEffect`: entre pintar todas las
  // pestañas y cortarlas hay un fotograma, y en `useEffect` ese fotograma se
  // ve — la barra parpadea al entrar en cada pantalla.
  useLayoutEffect(() => {
    const el = caja.current;
    if (!el) return;
    const hijos = [...el.querySelectorAll<HTMLElement>("[data-pestana]")];
    // Los anchos sólo se pueden leer con TODAS pintadas. Se guardan en la
    // primera pasada y se reutilizan: después ya no están todas en el DOM, así
    // que volver a medir daría un ancho cada vez más pequeño y la barra se
    // comería sus propias pestañas.
    if (hijos.length === pestanas.length) {
      anchos.current = hijos.map((h) => h.offsetWidth);
    } else if (anchos.current.length !== pestanas.length) {
      setCuantas(pestanas.length);
      return;
    }

    function recalcular() {
      const ancho = el!.clientWidth;
      if (ancho === 0) return;
      const total = anchos.current.reduce((s, w) => s + w, 0);
      // Sin «Más» no hay que reservarle sitio: si caben todas, caben todas.
      const disponible = total <= ancho ? ancho : ancho - RESERVA_MAS;
      let suma = 0;
      let n = 0;
      for (const w of anchos.current) {
        if (suma + w > disponible) break;
        suma += w;
        n++;
      }
      // Al menos una: una barra de aplicación sin ninguna pestaña no dice nada
      // y deja «Más» como único camino.
      setCuantas(Math.max(1, n));
    }

    recalcular();
    const observador = new ResizeObserver(recalcular);
    observador.observe(el);
    return () => observador.disconnect();
  }, [pestanas]);

  // La activa se queda siempre a la vista. Si cayera dentro de «Más», la barra
  // no diría dónde estás, que es su primer trabajo.
  const iActiva = pestanas.findIndex((e) => activa(pathname, e));
  const visibles =
    iActiva >= cuantas
      ? [...pestanas.slice(0, Math.max(0, cuantas - 1)), pestanas[iActiva]!]
      : pestanas.slice(0, cuantas);
  const escondidas = pestanas.filter((e) => !visibles.includes(e));

  const enMas: OpcionDeMenu[] = escondidas.map((e) => ({
    clave: e.a,
    nombre: t(e.clave),
    alElegir: () => navegar(e.a),
  }));

  return (
    <div className="flex h-11 shrink-0 items-stretch gap-1 border-b border-ink-dim/60 bg-paper pl-2 pr-4">
      {/* El nombre de la aplicación abre el lanzador. Es lo que hace
          Salesforce y resuelve una pregunta real: quien quiere cambiar de
          aplicación pulsa donde pone el nombre de la que tiene. */}
      <button
        type="button"
        onClick={alAbrirLanzador}
        className="my-1.5 flex shrink-0 items-center gap-2 rounded-md px-2.5 text-titulo font-bold text-ink hover:bg-paper-light"
        aria-haspopup="dialog"
      >
        <Icono nombre="apps" tamano="sm" className="text-ink-muted" />
        {t(aplicacion.clave)}
        <Icono nombre="expand_more" tamano="sm" className="text-ink-muted" />
      </button>

      <div
        ref={caja}
        className="flex min-w-0 flex-1 items-stretch overflow-hidden"
      >
        {(anchos.current.length === pestanas.length ? visibles : pestanas).map(
          (e) => {
            const aqui = activa(pathname, e);
            return (
              <Link
                key={e.a}
                data-pestana
                to={e.a}
                aria-current={aqui ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center whitespace-nowrap border-b-[3px] px-3.5 text-titulo transition-colors",
                  aqui
                    ? "border-accent font-semibold text-accent"
                    : "border-transparent text-ink-muted hover:border-ink-dim hover:text-ink",
                )}
              >
                {t(e.clave)}
              </Link>
            );
          },
        )}
      </div>

      {enMas.length > 0 ? (
        <div className="flex shrink-0 items-center">
          <MenuDeAcciones
            opciones={enMas}
            etiqueta={t("app.masPestanas")}
            clase="flex h-full items-center gap-1 whitespace-nowrap px-3 text-titulo text-ink-muted hover:text-ink"
          />
        </div>
      ) : null}
    </div>
  );
}
