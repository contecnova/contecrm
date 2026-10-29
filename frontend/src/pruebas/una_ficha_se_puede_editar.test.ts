/**
 * Si una pantalla enseña UN registro, tiene que poder cambiarlo.
 *
 * El fallo que se vigila ya pasó, y pasó por el sitio por el que pasan
 * siempre: la edición vivía dentro de `Ficha.tsx`, la ficha genérica, en vez
 * de en una pieza propia. Cuando se escribió la ficha de cliente a medida
 * —que es la que se usa de verdad, la que se abre desde el listado— se quedó
 * sin ella: un cliente no se podía editar desde ningún punto de su propia
 * ficha, aunque el servidor admitiera el `PATCH` y la pantalla enseñara al
 * lado que le faltaban cuatro campos por rellenar.
 *
 * Por eso esto no mira la ficha de cliente: mira **todas** las rutas que
 * abren un registro. Arreglar una y dejar las demás es cómo se vuelve a estar
 * igual dentro de dos pantallas nuevas.
 *
 * Las excepciones llevan su motivo escrito. Una lista de las que SÍ pueden
 * editarse se quedaría corta el día que se añada la siguiente; una lista de
 * las que no, con el porqué, obliga a justificarse.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const RAIZ = join(__dirname, "..", "..", "src");

/** Rutas que abren un registro y no ofrecen edición, y por qué. */
const SIN_EDICION_PORQUE: Record<string, string> = {
  Conversacion:
    "El contrato de `/conversaciones/{id}` no declara `PATCH`: una conversación " +
    "no se edita campo a campo, se responde, se transfiere o se escala a una " +
    "persona, y las tres son acciones que la pantalla ya ofrece.",
  Liquidacion:
    "El contrato de `/liquidaciones/{id}` sólo declara `GET`, y no es un " +
    "olvido: una liquidación de comisión es un número CALCULADO con cada euro " +
    "explicado, y poder cambiarlo a mano destruiría justo lo que la hace " +
    "defendible. Lo que sí se puede hacer son las cuatro acciones que el " +
    "servidor publica —enviar a aprobación, aprobar, reclamar y pagar—, y " +
    "cada una deja su rastro. Corregirla se hace revirtiéndola y volviendo a " +
    "liquidar, que es lo que deja una línea de reversión con su porqué.",
  InstanciaDeProceso:
    "Una instancia en marcha NO se edita campo a campo, y no es un olvido: " +
    "poner a mano su estado o su paso actual metería el registro en una rama " +
    "por la que no pasó, y el histórico diría que el proceso se siguió. Las " +
    "tres formas legítimas de tocarla son las que ofrece la pantalla —" +
    "reintentar, saltar el paso a un destino que la definición declara, y " +
    "corregir las variables—, y las tres exigen motivo y quedan auditadas. " +
    "El `PATCH` del contrato es exactamente el de las variables, y ése sí " +
    "está enchufado.",
};

function fuente(fichero: string): string {
  return readFileSync(join(RAIZ, fichero), "utf8");
}

/** Las rutas con `:id`, leídas de las rutas de verdad y no de una lista. */
function pantallasDeUnRegistro(): { ruta: string; componente: string }[] {
  const app = fuente("App.tsx");
  const salida: { ruta: string; componente: string }[] = [];
  const patron = /<Route\s+[^>]*path="([^"]*:id[^"]*)"[^>]*element=\{<(\w+)/gs;
  for (const [, ruta, componente] of app.matchAll(patron)) {
    if (ruta && componente) salida.push({ ruta, componente });
  }
  // Y las que llevan el `element` en otra línea, que `matchAll` de arriba no
  // coge: sin esto el recuento salía corto y la prueba pasaba por no mirar.
  const partido = /<Route\s+path="([^"]*:id[^"]*)"\s*\n\s*element=\{<(\w+)/g;
  for (const [, ruta, componente] of app.matchAll(partido)) {
    if (ruta && componente && !salida.some((x) => x.ruta === ruta)) {
      salida.push({ ruta, componente });
    }
  }
  return salida;
}

describe("toda pantalla que abre un registro deja cambiarlo", () => {
  const pantallas = pantallasDeUnRegistro();

  it("se han encontrado las rutas de ficha", () => {
    // Si el patrón deja de casar, lo de abajo no falla: no mira nada. Esto es
    // lo que convierte el recuento en parte de la comprobación.
    expect(pantallas.length).toBeGreaterThanOrEqual(4);
    expect(pantallas.map((p) => p.componente)).toContain("Cuenta");
    expect(pantallas.map((p) => p.componente)).toContain("Ficha");
  });

  it.each(pantallasDeUnRegistro())("$ruta", ({ componente }) => {
    const motivo = SIN_EDICION_PORQUE[componente];
    if (motivo) {
      // Sacar una pantalla del recuento cuesta explicarlo, y explicarlo en
      // serio: un «no aplica» de cuatro palabras no es un motivo.
      expect(motivo.length).toBeGreaterThanOrEqual(80);
      return;
    }
    const codigo = fuente(join("paginas", `${componente}.tsx`));
    expect(
      codigo.includes('from "@/componentes/Edicion"'),
      `«${componente}» abre un registro y no usa la edición compartida. O la ` +
        "enchufa, o entra en SIN_EDICION_PORQUE con el motivo escrito.",
    ).toBe(true);
    // Y que la use de verdad, no solo que la importe: un import sin usar lo
    // quita el compilador y la pantalla se queda sin botón igual.
    expect(codigo).toMatch(/<BotonesDeRegistro/);
    expect(codigo).toMatch(/<FormularioDeEdicion/);
  });
});
