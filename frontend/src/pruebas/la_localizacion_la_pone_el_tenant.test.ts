/**
 * Los formatos los pone el tenant, no el código (CRM-07.04.01.05).
 *
 * El CRM es headless, así que la jerarquía de localización la resuelve **el
 * servidor**: si cada frontend la resolviera por su cuenta, la web y el móvil
 * acabarían escribiendo la misma fecha de dos maneras.
 * `GET /api/v1/localizacion` devuelve lo ya resuelto —global → tier → tenant →
 * unidad → usuario— con ejemplos que son el contrato.
 *
 * Esa ruta existía desde hacía tiempo y **el front no la leía**. Tenía
 * `"es-ES"` escrito a mano en **dieciséis sitios de cinco ficheros**, y los
 * formateadores construidos como constantes de módulo: se crean al importar,
 * así que no podían cambiar ni aunque alguien quisiera. Un tenant en Portugal
 * o en México veía sus números escritos como en España. Medido el 26-10-2026
 * auditando la base del front.
 */

import { afterEach, describe, expect, it } from "vitest";

import { escalar, fijarLocalizacion, importe, localizacion } from "@/lib/formato";

afterEach(() => {
  // Se deja como estaba: el estado del módulo es compartido entre pruebas.
  fijarLocalizacion("es-ES");
});

describe("la localización", () => {
  it("arranca en castellano y cambia cuando el servidor dice otra cosa", () => {
    expect(localizacion()).toBe("es-ES");
    fijarLocalizacion("en-US");
    expect(localizacion()).toBe("en-US");
  });

  it("cambia de verdad cómo se escribe un número", () => {
    // Es lo que se vería en pantalla, no una variable: en castellano el punto
    // separa los miles y en inglés es al revés, y leer «1.234,5» donde se
    // espera «1,234.5» es leer otro número.
    // La coma decimal en castellano y el punto en inglés. Se mira el
    // separador y no la cadena entera, porque los separadores de millar los
    // decide `Intl` y no son lo que se está midiendo.
    expect(escalar(1234.5)).toContain(",5");
    fijarLocalizacion("en-US");
    expect(escalar(1234.5)).toContain(".5");
  });

  it("y cómo se escribe un importe, con su moneda", () => {
    // Las monedas se guardaban ya construidas, así que llevaban la
    // localización vieja dentro: sin vaciar ese cajón, cambiar de tenant no
    // cambiaba los importes aunque sí los números.
    const antes = importe(1234, "EUR");
    fijarLocalizacion("en-US");
    const despues = importe(1234, "EUR");
    expect(despues).not.toBe(antes);
  });

  it("una localización que no existe no deja los números sin pintar", () => {
    // Un formateador que revienta vacía la pantalla entera, y el precio de
    // equivocarse en un código de idioma no puede ser ese: se queda la que
    // había.
    fijarLocalizacion("en-US");
    fijarLocalizacion("no-es-un-idioma-$$");
    expect(localizacion()).toBe("en-US");
    expect(escalar(1234.5)).toContain(".5");
  });

  it("vacío no cambia nada", () => {
    // El servidor puede no haber resuelto idioma todavía; eso no es motivo
    // para romper el formateo.
    fijarLocalizacion("en-US");
    fijarLocalizacion("");
    expect(localizacion()).toBe("en-US");
  });
});

describe("nadie escribe la localización a mano", () => {
  it("no queda ningún «es-ES» suelto en el producto", async () => {
    // Es el guardián de que esto no vuelva: dieciséis apariciones en cinco
    // ficheros, y cada una es un tenant al que se le escriben los números como
    // si estuviera en España.
    const { readFileSync, readdirSync, statSync } = await import("node:fs");
    const { join, resolve } = await import("node:path");

    const raiz = resolve(process.cwd(), "src");
    const malos: string[] = [];
    const recorridos: string[] = [];

    function recorrer(dir: string) {
      for (const entrada of readdirSync(dir)) {
        const ruta = join(dir, entrada);
        if (statSync(ruta).isDirectory()) {
          // Las pruebas sí pueden nombrarla: es lo que están midiendo.
          if (entrada !== "pruebas") recorrer(ruta);
          continue;
        }
        if (!/\.(ts|tsx)$/.test(entrada)) continue;
        recorridos.push(ruta);
        const texto = readFileSync(ruta, "utf-8");
        // La declaración del respaldo en `formato.ts` es la única legítima.
        const lineas = texto.split("\n").filter((l) => l.includes('"es-ES"'));
        for (const linea of lineas) {
          if (linea.includes("let LOCALE")) continue;
          // Los comentarios pueden nombrarla: cuentan la historia del
          // arreglo, que es lo que impide que vuelva por descuido.
          const limpia = linea.trimStart();
          if (limpia.startsWith("*") || limpia.startsWith("//")) continue;
          malos.push(`${ruta}: ${linea.trim()}`);
        }
      }
    }
    recorrer(raiz);

    // Que el recorrido mire de verdad: sin esto, un fallo al leer el árbol
    // daría cero apariciones, que es el mismo verde que no tener el problema.
    expect(recorridos.length).toBeGreaterThan(40);
    expect(malos).toEqual([]);
  });
});
