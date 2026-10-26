/**
 * El armazón de una tabla: el recuadro, la cabecera y el cuerpo.
 *
 * Existe porque el mismo marcado estaba copiado **cinco veces** —la tabla
 * genérica y cuatro pantallas con tabla propia— carácter por carácter. Hoy
 * coinciden; el día que alguien mejore una —filas alternas, cabecera fija, otro
 * comportamiento en móvil— dejarán de coincidir, y nadie se dará cuenta hasta
 * que un cliente pregunte por qué la pantalla de estado se ve distinta.
 *
 * No sustituye a `Tabla`: `Tabla` sirve para lo que llega de la API sin
 * estructura conocida —elige columnas, las esconde, las recuerda—, y esto es
 * para las tablas de forma fija, donde esas capacidades no aportan nada y lo
 * único que se quiere compartir es el aspecto.
 */

import type { ReactNode } from "react";

export function Rejilla({
  cabeceras,
  titulo,
  children,
  className = "",
  compacta = false,
}: {
  /** Rótulos de las columnas, en orden. */
  cabeceras: ReactNode[];
  /** Título para quien no ve la tabla. No se pinta. */
  titulo?: string;
  /** Las filas, ya montadas: `<tr>` con `<Casilla>` dentro. */
  children: ReactNode;
  className?: string;
  /**
   * Letra un punto más pequeña, para tablas de apoyo dentro de otra pantalla.
   *
   * Está aquí y no suelto porque **ya divergía**: dos de las cuatro copias
   * usaban `text-2xs` y las otras dos `text-xs`, sin que nadie lo decidiera.
   *
   * Es una distinción RELATIVA a la densidad de quien mira, no un tamaño: se
   * calcula desde el token en `.celda-rejilla--apoyo`.
   */
  compacta?: boolean;
}) {
  return (
    <div
      className={`overflow-x-auto rounded-xl border border-ink-dim/60 bg-paper ${className}`}
    >
      {/* El tamaño de letra sale del token de densidad, en `.celda-rejilla`, y
          no de una clase fija: con la densidad por persona, una tabla con
          `text-xs` clavado se queda igual de apretada cuando alguien pide el
          modo cómodo — y entonces el interruptor parece que no hace nada. */}
      <table className={`w-full text-left ${compacta ? "es-apoyo" : ""}`}>
        {titulo ? <caption className="sr-only">{titulo}</caption> : null}
        <thead className="border-b border-ink-dim/30 bg-paper-light">
          <tr>
            {cabeceras.map((c, i) => (
              <th
                key={i}
                scope="col"
                className="celda-rejilla whitespace-nowrap font-medium text-ink-muted"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/**
 * Una celda, con el mismo espaciado y alineado que el resto del producto.
 *
 * El tono lo pone quien la usa —hay columnas que van apagadas a propósito, como
 * el nombre del servicio al lado del componente— pero el espaciado no: era
 * justo donde las cinco copias ya habían empezado a separarse.
 */
export function Casilla({
  children,
  className = "",
  enUnaLinea = false,
}: {
  children?: ReactNode;
  className?: string;
  /** Impide que el texto parta en dos líneas. Para datos cortos: fechas, cifras. */
  enUnaLinea?: boolean;
}) {
  return (
    <td
      className={`celda-rejilla align-top ${enUnaLinea ? "whitespace-nowrap" : ""} ${
        className || "text-ink"
      }`}
    >
      {children}
    </td>
  );
}
