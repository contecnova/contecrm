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

export interface Pestana {
  /** Lo que identifica la pestaña en el código. */
  clave: string;
  /** Lo que se lee. */
  nombre: string;
}

export function PestanasDeFicha({
  pestanas,
  activa,
  alElegir,
  etiqueta,
}: {
  pestanas: Pestana[];
  activa: string;
  alElegir: (clave: string) => void;
  /** Para quien no ve la pantalla: de qué son estas pestañas. */
  etiqueta: string;
}) {
  return (
    <nav
      aria-label={etiqueta}
      className="mt-3 flex flex-wrap border-b border-ink-dim"
    >
      {pestanas.map((p) => (
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
}
