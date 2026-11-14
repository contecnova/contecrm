/**
 * Cargas secundarias: los paneles de una pantalla que se piden aparte de lo
 * principal y cuyo fallo **no tumba la pantalla, pero se dice**.
 *
 * Antes cada una acababa en `.catch(() => undefined)`: el panel no salía, y
 * «no se ha podido consultar» se veía exactamente igual que «no hay nada que
 * enseñar». Medido el 13-11-2026: 95 `catch` mudos en 24 pantallas, quince
 * de ellos en la ficha de una oportunidad. Quien
 * mira no sabe si fiarse de lo que NO ve, que es justo lo que la pantalla de
 * menciones ya prohibía.
 *
 * Aquí se resuelve una vez: cada carga se sigue por su clave, su fallo se
 * guarda (salvo la cancelación, que no es un fallo) y se puede reintentar sin
 * recargar la pantalla. Lo que se pinta con eso es `<FalloCompacto>`.
 *
 *     const secundarias = useCargasSecundarias();
 *     secundarias.seguir("slo", () =>
 *       llamar<Slo>(ruta, { signal }).then((r) => setSlo(r.datos)),
 *     );
 *     …
 *     <FalloCompacto {...secundarias.estado("slo")} que={t("estado.slo")} />
 */

import { useCallback, useRef, useState } from "react";

import { ErrorApi } from "@/lib/api";
import { esCancelacion } from "@/lib/cancelacion";

/** Lo que una pantalla necesita saber de una carga secundaria. */
export interface EstadoDeCarga {
  /** Pedida y sin contestar todavía. */
  cargando: boolean;
  /** El fallo, o `null`. Una cancelación nunca llega aquí. */
  error: unknown;
  /**
   * El servidor ha dicho que no te toca (403). No se pinta como fallo: un
   * panel que tu rol no puede ver no se anuncia en cada pantalla, igual que el
   * menú no enseña lo que no puedes abrir. Se expone por si una pantalla
   * necesita distinguirlo.
   */
  sinPermiso: boolean;
  /** Vuelve a pedir ESA carga, sin tocar las demás ni la principal. */
  reintentar: () => void;
}

interface Seguimiento {
  cargando: boolean;
  error: unknown;
  sinPermiso: boolean;
}

const EN_REPOSO: Seguimiento = { cargando: false, error: null, sinPermiso: false };

export interface CargasSecundarias {
  /**
   * Sigue una carga por su clave. `pedir` debe devolver la promesa YA con su
   * `.then` que guarda el dato: se vuelve a llamar tal cual al reintentar.
   */
  seguir: (clave: string, pedir: () => Promise<unknown>) => void;
  estado: (clave: string) => EstadoDeCarga;
}

export function useCargasSecundarias(): CargasSecundarias {
  const [seguimientos, setSeguimientos] = useState<Record<string, Seguimiento>>({});
  // Lo último que se pidió con cada clave, para reintentarlo igual.
  const pedidos = useRef<Record<string, () => Promise<unknown>>>({});
  // Qué vuelta de cada clave es la vigente. Sin esto, la respuesta tardía de
  // una vuelta anterior —la que cancela el doble efecto del modo estricto, o
  // la de antes de un reintento— pisaría el estado de la buena.
  const turnos = useRef<Record<string, number>>({});

  const seguir = useCallback((clave: string, pedir: () => Promise<unknown>) => {
    pedidos.current[clave] = pedir;
    const mio = (turnos.current[clave] ?? 0) + 1;
    turnos.current[clave] = mio;
    const poner = (s: Seguimiento) =>
      setSeguimientos((previos) => ({ ...previos, [clave]: s }));
    poner({ cargando: true, error: null, sinPermiso: false });
    let promesa: Promise<unknown>;
    try {
      promesa = pedir();
    } catch (error) {
      promesa = Promise.reject(error);
    }
    promesa.then(
      () => {
        if (turnos.current[clave] === mio) poner(EN_REPOSO);
      },
      (error: unknown) => {
        if (turnos.current[clave] !== mio) return;
        if (esCancelacion(error)) poner(EN_REPOSO);
        else if (error instanceof ErrorApi && error.estado === 403)
          poner({ cargando: false, error: null, sinPermiso: true });
        else poner({ cargando: false, error, sinPermiso: false });
      },
    );
  }, []);

  const estado = useCallback(
    (clave: string): EstadoDeCarga => ({
      ...(seguimientos[clave] ?? EN_REPOSO),
      reintentar: () => {
        const pedir = pedidos.current[clave];
        if (pedir) seguir(clave, pedir);
      },
    }),
    [seguimientos, seguir],
  );

  return { seguir, estado };
}
