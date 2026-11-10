/**
 * Un componente cuyo código se baja la primera vez que se pinta.
 *
 * Para los bloques de la ficha que sólo salen en un tipo de registro —la
 * transcripción en una reunión, el marcador en un contacto, la renovación en
 * un contrato—. Importados de forma estática, viajaban en la ficha de TODOS
 * los registros: medido el 10-11-2026, la ficha pesaba 14 kB comprimidos con
 * diecisiete bloques así, por encima del tope por pantalla.
 *
 * No necesita `Suspense`: mientras llega no pinta nada, y el sitio lo ocupa
 * el bloque cuando está. Lo que se pinta después es el mismo componente con
 * las mismas propiedades, así que quien lo usa no cambia nada.
 */

import { useEffect, useState, type ComponentType, type JSX } from "react";

export function diferido<P extends object>(
  cargar: () => Promise<ComponentType<P>>,
): (props: P) => JSX.Element | null {
  let cargado: ComponentType<P> | null = null;
  let pendiente: Promise<ComponentType<P>> | null = null;
  return function Diferido(props: P) {
    const [Componente, setComponente] = useState<ComponentType<P> | null>(
      () => cargado,
    );
    useEffect(() => {
      if (Componente) return;
      let vivo = true;
      pendiente ??= cargar().then((c) => (cargado = c));
      void pendiente.then((c) => {
        if (vivo) setComponente(() => c);
      });
      return () => {
        vivo = false;
      };
    }, [Componente]);
    return Componente ? <Componente {...props} /> : null;
  };
}
