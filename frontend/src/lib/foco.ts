/**
 * El foco de una pregunta en línea (`role="alertdialog"`): entra al abrirla y
 * vuelve al cerrarla (auditoría 13-11-2026, UX-7).
 *
 * Un `alertdialog` que no recibe el foco no lo anuncia nadie: quien usa
 * teclado o lector pulsa «Fusionar» y no se entera de que se le está
 * preguntando algo. El foco va al botón SEGURO —cancelar, «mejor no»— para
 * que un Intro de más no haga lo que no se puede deshacer.
 *
 * Al cerrarla, el foco vuelve a `devolverA` si se da (el botón que abrió la
 * pregunta puede haberse vuelto a pintar y ser otro nodo) o a donde estaba.
 * Si lo que sale después ya ha cogido el foco —el botón de ejecutar tras
 * «Lo entiendo»—, se respeta: devolverlo atrás haría retroceder a quien
 * acaba de decir que sí.
 */

import { useEffect, type RefObject } from "react";

export function useFocoDeConfirmacion(
  seguro: RefObject<HTMLElement | null>,
  devolverA?: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    const previo = document.activeElement;
    seguro.current?.focus();
    return () => {
      // Al desmontarse, el botón que tenía el foco ya no está y el foco cae
      // en `body`. Sólo entonces se devuelve: si está en otro sitio, alguien
      // lo ha puesto ahí a propósito.
      const ahora = document.activeElement;
      if (ahora && ahora !== document.body && ahora.isConnected) return;
      const destino =
        // Se lee al CERRAR y no al abrir, a propósito: lo que se busca es el
        // botón que hay ahora, que puede ser otro nodo que el de al abrir.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        devolverA?.current ?? (previo instanceof HTMLElement ? previo : null);
      if (destino?.isConnected) destino.focus();
    };
  }, [seguro, devolverA]);
}
