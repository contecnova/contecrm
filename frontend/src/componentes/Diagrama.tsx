/**
 * El diagrama de un proceso, en un sitio.
 *
 * Lo pintaban dos pantallas con código distinto: el editor —donde se escribe
 * el proceso— y la instancia —donde se sigue—. Dos dibujos del mismo objeto
 * tienen dos problemas: pesan dos veces, y **divergen**. El día que al editor
 * se le añada una forma de enlace y a la instancia no, el mismo proceso se
 * verá de dos maneras y habrá que entenderlo otra vez al cambiar de pantalla.
 *
 * Lo que cambia entre las dos es **cómo se pinta cada caja**, no cómo se
 * colocan ni cómo se unen: el editor marca el inicio, la instancia marca por
 * dónde va. Eso entra por `pinta`, que recibe el nodo y devuelve su trazo y
 * las líneas de texto que lleva dentro.
 *
 * **El color nunca va solo.** Las líneas de texto son parte del contrato de
 * este componente a propósito: un diagrama que sólo se entiende viendo los
 * colores no lo lee quien no los distingue.
 */

import { ALTO, ANCHO, aristas, type Arista, type Definicion, type Nodo } from "@/lib/grafo";

/** Cómo se pinta una caja: su trazo y lo que lleva escrito dentro. */
export interface Pintura {
  trazo: string;
  grosor: number;
  /** Las líneas de texto de la caja, de arriba abajo. */
  lineas: string[];
}

export function Diagrama({
  definicion,
  nodos,
  rotulo,
  pinta,
  conEtiquetas = false,
}: {
  definicion: Definicion;
  nodos: Nodo[];
  /** Etiqueta accesible del dibujo. */
  rotulo: string;
  pinta: (nodo: Nodo) => Pintura;
  /** Si las flechas llevan escrito por qué se toman. Sólo el editor. */
  conEtiquetas?: boolean;
}) {
  const enlaces: Arista[] = aristas(definicion);
  const porNombre = new Map(nodos.map((n) => [n.nombre, n]));
  const ancho = Math.max(400, ...nodos.map((n) => n.x + ANCHO));
  const alto = Math.max(280, ...nodos.map((n) => n.y + ALTO));

  return (
    <svg width={ancho} height={alto} role="img" aria-label={rotulo}>
      {enlaces.map((a, i) => {
        const desde = porNombre.get(a.desde);
        const hasta = porNombre.get(a.hasta);
        if (!desde || !hasta) return null;
        return (
          <g key={`${a.desde}-${a.hasta}-${a.etiqueta}-${i}`}>
            <line
              x1={desde.x + 140}
              y1={desde.y + 18}
              x2={hasta.x}
              y2={hasta.y + 18}
              stroke="rgb(var(--ink-dim))"
              strokeWidth={1.5}
            />
            {conEtiquetas ? (
              <text
                x={(desde.x + 140 + hasta.x) / 2}
                y={(desde.y + hasta.y) / 2 + 12}
                fill="rgb(var(--ink-faint))"
                fontSize={9}
              >
                {a.etiqueta}
              </text>
            ) : null}
          </g>
        );
      })}
      {nodos.map((n) => {
        const { trazo, grosor, lineas } = pinta(n);
        return (
          <g key={n.nombre}>
            <rect
              x={n.x}
              y={n.y}
              width={140}
              height={12 + lineas.length * 13}
              rx={8}
              fill="rgb(var(--paper-light))"
              stroke={trazo}
              strokeWidth={grosor}
            />
            {lineas.map((linea, i) => (
              <text
                key={linea + i}
                x={n.x + 10}
                y={n.y + 15 + i * 13}
                fill={i === 0 ? "rgb(var(--ink))" : "rgb(var(--ink-faint))"}
                fontSize={i === 0 ? 11 : 9}
              >
                {linea}
              </text>
            ))}
          </g>
        );
      })}
    </svg>
  );
}
