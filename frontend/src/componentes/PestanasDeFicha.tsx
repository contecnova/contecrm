/**
 * Las pestañas de una ficha, con la forma de Lightning.
 *
 * Subrayado azul en la activa sobre una línea que recorre el ancho. Eran
 * píldoras con el fondo claro del tema y, sobre una tarjeta blanca, la activa
 * quedaba del mismo color que las otras: se marcaba con `aria-current` y no se
 * veía. Visto en la pantalla el 02-11-2026.
 *
 * Está aquí fuera y no dentro de la ficha genérica porque las tres fichas de a
 * medida —cuenta, oportunidad y caso— llevan las mismas: dos pantallas que
 * enseñan lo mismo lo colocan igual, o quien usa las dos cree que son dos
 * productos.
 */

import { Suspense, lazy } from "react";
import { useTranslation } from "react-i18next";

// **La conversación se carga cuando se abre, no al entrar.** Esta barra viaja
// en el paquete de apertura —la llevan las quince fichas—, así que importarla
// arriba metía la conversación y su tabla en lo primero que descarga
// cualquiera. Medido el 04-11-2026: el paquete pasó de 124 kB comprimidos, que
// es el tope. Nadie abre una ficha para leer los comentarios antes de verla.
const Comentarios = lazy(() =>
  import("@/componentes/Comentarios").then((m) => ({ default: m.Comentarios })),
);
import { useSuperficie } from "@/lib/permisos";

export interface Pestana {
  /** Lo que identifica la pestaña en el código. */
  clave: string;
  /** Lo que se lee. */
  nombre: string;
}

export const CLAVE_CONVERSACION = "comentarios";

export function PestanasDeFicha({
  pestanas,
  activa,
  alElegir,
  etiqueta,
  tipo,
  id,
}: {
  pestanas: Pestana[];
  activa: string;
  alElegir: (clave: string) => void;
  /** Para quien no ve la pantalla: de qué son estas pestañas. */
  etiqueta: string;
  /**
   * El registro, para la conversación.
   *
   * **La pestaña de conversación la pone esta barra**, no cada pantalla. Hay
   * quince fichas —una genérica y catorce propias— y la conversación vivía
   * encerrada en la genérica: en las otras catorce no había dónde escribir,
   * con la API publicada y alimentando las menciones. Medido el 03-11-2026
   * abriendo un caso: cero cajas de texto.
   *
   * Aquí la llevan todas, y la ficha que se escriba mañana también. Sin
   * `tipo` no se ofrece: hay registros que no admiten comentarios y ofrecer
   * una pestaña que contesta 404 es peor que no ofrecerla.
   */
  tipo?: string;
  id?: string;
}) {
  const { t } = useTranslation();
  const { superficie } = useSuperficie();
  // Mientras la superficie no ha llegado NO se ofrece: al revés haría
  // aparecer y desaparecer una pestaña bajo el cursor. Las demás pestañas no
  // se mueven, así que esto no deja la barra vacía mientras tanto.
  const conConversacion =
    Boolean(tipo && id) &&
    Boolean(superficie?.objetos?.comentarios?.includes(tipo ?? ""));
  // Y sólo si no la trae ya quien llama.
  //
  // Hay fichas que la declaran por su cuenta —`Ficha.tsx` la saca de lo que el
  // registro puede tener— y este componente la añadía encima: la pestaña salía
  // **dos veces, con el mismo rótulo, una al lado de la otra**. Lo vio quien lo
  // usa el 04-11-2026 en un candidato. Dos entradas iguales no se distinguen
  // más que pulsándolas, que es justo lo que un rótulo viene a evitar.
  //
  // Se compara por CLAVE y no por rótulo: el rótulo es traducible y dos claves
  // distintas pueden acabar llamándose igual en un idioma y no en otro.
  const yaEsta = pestanas.some((p) => p.clave === CLAVE_CONVERSACION);
  const todas =
    conConversacion && !yaEsta
      ? [...pestanas, { clave: CLAVE_CONVERSACION, nombre: t("ficha.comentarios") }]
      : pestanas;
  const barra = (
    <nav
      aria-label={etiqueta}
      className="mt-3 flex flex-wrap border-b border-ink-dim"
    >
      {todas.map((p) => (
        <button
          key={p.clave}
          type="button"
          onClick={() => alElegir(p.clave)}
          aria-current={p.clave === activa ? "page" : undefined}
          className={`-mb-px border-b-[3px] px-4 py-2 text-titulin ${
            p.clave === activa
              ? "border-accent font-semibold text-accent"
              : "border-transparent text-ink-muted hover:border-ink-dim hover:text-ink"
          }`}
        >
          {p.nombre}
        </button>
      ))}
    </nav>
  );

  // **La barra pinta también su panel.** Si sólo pusiera la pestaña, cada
  // pantalla tendría que acordarse de pintar la conversación al elegirla —y
  // la que se olvidara dejaría una pestaña que no enseña nada, que es peor
  // que no tenerla.
  if (!conConversacion || activa !== CLAVE_CONVERSACION) return barra;
  return (
    <>
      {barra}
      <div className="mt-4">
        {/* Sin `fallback` visible: lo que se carga es un fichero pequeño y un
            «cargando…» que parpadea molesta más de lo que informa. */}
        <Suspense fallback={null}>
          <Comentarios tipo={tipo ?? ""} id={id ?? ""} />
        </Suspense>
      </div>
    </>
  );
}
