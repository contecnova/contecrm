/**
 * Las opciones de un campo cuya lista decide la empresa (un vocabulario).
 *
 * El contrato no puede llevarlas como `enum`: serían las de fábrica para
 * siempre, y la empresa que añade «Urgente» a sus prioridades no la vería en
 * ningún formulario. Así que el campo dice **de qué vocabulario** sale
 * (`x-vocabulario: "service/prioridades_caso"`) y aquí se piden sus valores
 * activos, en el orden y con el rótulo que tenga la empresa.
 *
 * Una vez por vocabulario y sesión de la pantalla: un formulario con la
 * prioridad y una tabla con la columna editable no la piden dos veces.
 */
import { useEffect, useState } from "react";

import { filas, llamar } from "@/lib/api";
import type { CampoEsquema } from "@/lib/contrato";
import { rotuloDeOpcion } from "@/lib/formato";

export interface Opcion {
  valor: string;
  etiqueta: string;
}

const pedidos = new Map<string, Promise<Opcion[]>>();

function pedir(ruta: string): Promise<Opcion[]> {
  const hay = pedidos.get(ruta);
  if (hay) return hay;
  const promesa = llamar<unknown>(
    `/api/v1/${ruta.replace("/", "/vocabularios/")}`,
  )
    .then((r) =>
      filas<{
        valor: string;
        etiqueta?: string;
        activo?: boolean;
        orden?: number;
      }>(r.datos)
        .filter((f) => f.activo !== false)
        .sort((a, b) => (a.orden ?? 0) - (b.orden ?? 0))
        .map((f) => ({
          valor: f.valor,
          etiqueta: f.etiqueta || rotuloDeOpcion(f.valor),
        })),
    )
    .catch((error: unknown) => {
      // Un fallo no se recuerda: la siguiente pantalla lo vuelve a intentar.
      pedidos.delete(ruta);
      throw error;
    });
  pedidos.set(ruta, promesa);
  return promesa;
}

/**
 * Las opciones del campo: las del vocabulario si sale de uno, y si no las del
 * contrato. `null` mientras llegan.
 *
 * El valor que ya tiene el registro se añade aunque esté retirado: un caso
 * antiguo con una prioridad que la empresa ya no usa tiene que seguir
 * enseñándola, no aparecer vacío.
 */
export function useOpciones(
  campo: Pick<CampoEsquema, "opciones" | "vocabulario">,
  actual?: unknown,
): Opcion[] | null {
  const ruta = campo.vocabulario ?? "";
  const [delVocabulario, setDelVocabulario] = useState<Opcion[] | null>(null);
  useEffect(() => {
    if (!ruta) return;
    let vivo = true;
    pedir(ruta)
      .then((o) => vivo && setDelVocabulario(o))
      // Sin la lista, se escribe a mano: el servidor dirá si vale.
      .catch(() => vivo && setDelVocabulario([]));
    return () => {
      vivo = false;
    };
  }, [ruta]);

  const base = ruta
    ? delVocabulario
    : campo.opciones.map((o) => ({ valor: o, etiqueta: rotuloDeOpcion(o) }));
  if (base === null) return null;
  const valor = actual === undefined || actual === null ? "" : String(actual);
  if (valor && !base.some((o) => o.valor === valor))
    return [...base, { valor, etiqueta: rotuloDeOpcion(valor) }];
  return base;
}
