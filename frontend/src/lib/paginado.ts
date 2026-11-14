/**
 * Una lista que se pide por páginas y se puede seguir con «cargar más».
 *
 * Las pantallas pedían `?limite=200` y pintaban lo que llegara como si fuera
 * todo: el tablero de oportunidades con la doscientas una fuera y sin decirlo.
 * El servidor ya contesta con el cursor de la página siguiente
 * (`PaginaDeListado.siguiente`), así que esto lo guarda y ofrece seguir.
 *
 * Las páginas se ACUMULAN: sustituir haría que «cargar más» pareciera saltar
 * de página y quien miraba perdería lo que ya tenía delante (la misma razón
 * que en el listado genérico de `Modulo`).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { salvoCancelacion } from "@/lib/api";
import { conCursor, listarPagina } from "@/lib/listados";

export interface ListaPaginada<T> {
  /** `null` mientras llega la primera página. */
  filas: T[] | null;
  /** El servidor ha dicho que hay más (hay cursor). */
  hayMas: boolean;
  cargarMas: () => void;
  cargandoMas: boolean;
  /** El fallo de la primera página: sin ella no hay lista que enseñar. */
  fallo: unknown;
  /**
   * El fallo al pedir la siguiente. Aparte a propósito: que no llegue la
   * segunda página no puede borrar la primera, que sí está.
   */
  falloAlCargarMas: unknown;
  recargar: () => void;
  /** Para reflejar un cambio local (mover una tarjeta) sin volver a pedir. */
  setFilas: (cambiar: (filas: T[] | null) => T[] | null) => void;
}

/** `ruta` con su `limite=`; `null` mientras no se sepa qué pedir. */
export function useListaPaginada<T>(ruta: string | null): ListaPaginada<T> {
  const [filas, setFilas] = useState<T[] | null>(null);
  const [siguiente, setSiguiente] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const [falloAlCargarMas, setFalloAlCargarMas] = useState<unknown>(null);
  const [cargandoMas, setCargandoMas] = useState(false);
  const [vuelta, setVuelta] = useState(0);
  // La lista vigente. Una página que llega de una ruta anterior (otro filtro)
  // o de antes de recargar no se mezcla con la de ahora.
  const turno = useRef(0);
  const control = useRef<AbortController | null>(null);

  useEffect(() => {
    if (ruta === null) return;
    const mio = (turno.current += 1);
    const actual = new AbortController();
    control.current = actual;
    setFallo(null);
    setFalloAlCargarMas(null);
    setCargandoMas(false);
    listarPagina<T>(ruta, { signal: actual.signal })
      .then((pagina) => {
        if (mio !== turno.current) return;
        setFilas(pagina.filas);
        setSiguiente(pagina.siguiente);
      })
      .catch(
        salvoCancelacion((error) => {
          if (mio === turno.current) setFallo(error);
        }),
      );
    return () => actual.abort();
  }, [ruta, vuelta]);

  const cargarMas = useCallback(() => {
    if (!siguiente || ruta === null || cargandoMas) return;
    const mio = turno.current;
    setCargandoMas(true);
    setFalloAlCargarMas(null);
    listarPagina<T>(conCursor(ruta, siguiente), {
      signal: control.current?.signal,
    })
      .then((pagina) => {
        if (mio !== turno.current) return;
        setFilas((previas) => [...(previas ?? []), ...pagina.filas]);
        setSiguiente(pagina.siguiente);
      })
      .catch(
        salvoCancelacion((error) => {
          if (mio === turno.current) setFalloAlCargarMas(error);
        }),
      )
      .finally(() => {
        if (mio === turno.current) setCargandoMas(false);
      });
  }, [ruta, siguiente, cargandoMas]);

  const recargar = useCallback(() => setVuelta((v) => v + 1), []);

  return {
    filas,
    hayMas: siguiente !== "",
    cargarMas,
    cargandoMas,
    fallo,
    falloAlCargarMas,
    recargar,
    setFilas,
  };
}
