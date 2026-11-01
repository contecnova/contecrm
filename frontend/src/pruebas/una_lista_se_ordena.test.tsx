/**
 * Una lista se puede ordenar, y ordena por lo que el dato ES.
 *
 * La bandeja de casos enseñaba 104 filas **sin una sola cabecera**: ni se podía
 * saber qué era cada columna ni ordenar por ninguna. `Tabla` —que sí elige
 * columnas, las recuerda y esconde las vacías— tampoco ordenaba, y sólo la
 * usaban 3 de las 56 pantallas.
 *
 * Lo que esta prueba protege no es que haya una flecha: es que **el orden
 * respete el tipo**. Ordenar como texto una columna de importes pone «1.000»
 * delante de «900», y una de fechas funciona de milagro mientras el formato no
 * cambie. Los dos son el mismo error.
 *
 * Validada plantando el caso malo: comparando con `String(a) < String(b)`
 * fallan la de importes, la de fechas y la de acentos.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Tabla } from "@/componentes/Tabla";

function textosDeColumna(indice: number): string[] {
  return screen
    .getAllByRole("row")
    .slice(1) // la cabecera
    .map((f) => within(f).getAllByRole("cell")[indice]?.textContent?.trim() ?? "");
}

/**
 * Pulsa la cabecera de esa columna.
 *
 * Se busca por `title`, que lleva el nombre crudo del campo, y no por el
 * nombre accesible: el doble de i18n de las pruebas devuelve la clave sin
 * interpolar, así que todas las cabeceras se llaman igual —`tabla.ordenarPor`—
 * y no habría forma de distinguirlas. En la aplicación real el rótulo sí se
 * interpola y dice de qué columna es.
 */
function ordenarPor(campo: string) {
  const boton = document.querySelector<HTMLButtonElement>(`th button[title="${campo}"]`);
  if (!boton) throw new Error(`no hay cabecera pulsable para «${campo}»`);
  fireEvent.click(boton);
}

describe("una lista se ordena", () => {
  it("los importes, por su valor y no por su texto", () => {
    // El caso que delata el orden alfabético: 900 va antes que 1000, pero
    // «1.000» va antes que «900» como texto.
    render(<Tabla filas={[{ importe: 900 }, { importe: 1000 }, { importe: 80 }]} />);
    // Cuatro cifras van SIN separador de millares en castellano: «1000», no
    // «1.000». Lo pone `Intl` con la localización del tenant y así es como se
    // escribe aquí.
    ordenarPor("importe");
    expect(textosDeColumna(0)).toEqual(["80", "900", "1000"]);
  });

  it("y los decimales que llegan como cadena, igual", () => {
    // La API manda `Numeric` como texto para no perder precisión, así que el
    // mismo campo puede venir número o cadena.
    render(<Tabla filas={[{ total: "900.00" }, { total: "1000.00" }, { total: "80.50" }]} />);
    ordenarPor("total");
    expect(textosDeColumna(0)).toEqual(["81", "900", "1000"]);
  });

  it("las fechas, por cuándo fueron", () => {
    render(
      <Tabla
        filas={[{ creado: "2026-02-01" }, { creado: "2025-12-31" }, { creado: "2026-01-15" }]}
      />,
    );
    ordenarPor("creado");
    expect(textosDeColumna(0)).toEqual(["31/12/2025", "15/01/2026", "01/02/2026"]);
  });

  it("el texto, como se ordena en castellano", () => {
    // Con `<` sobre puntos de código, «Ávila» cae detrás de «Zamora».
    render(<Tabla filas={[{ ciudad: "Zamora" }, { ciudad: "Ávila" }, { ciudad: "Bilbao" }]} />);
    ordenarPor("ciudad");
    expect(textosDeColumna(0)).toEqual(["Ávila", "Bilbao", "Zamora"]);
  });

  it("lo que falta va al final, suba o baje", () => {
    // Una columna ordenada que empieza por tres guiones no enseña nada de lo
    // que se pidió.
    render(<Tabla filas={[{ ciudad: "Vigo" }, { ciudad: null }, { ciudad: "Ávila" }]} />);
    ordenarPor("ciudad");
    expect(textosDeColumna(0).slice(0, 2)).toEqual(["Ávila", "Vigo"]);
    ordenarPor("ciudad"); // descendente
    expect(textosDeColumna(0).slice(0, 2)).toEqual(["Vigo", "Ávila"]);
  });

  it("el tercer clic devuelve el orden que traía", () => {
    // Sin esta vuelta, ordenar una vez es irreversible, y el orden del
    // servidor —lo más reciente, lo que más urge— suele ser el bueno.
    const filas = [{ ciudad: "Vigo" }, { ciudad: "Ávila" }, { ciudad: "Lugo" }];
    render(<Tabla filas={filas} />);
    const original = textosDeColumna(0);
    ordenarPor("ciudad");
    expect(textosDeColumna(0)).not.toEqual(original);
    ordenarPor("ciudad");
    ordenarPor("ciudad");
    expect(textosDeColumna(0)).toEqual(original);
  });

  it("ordenar no altera las filas de quien llama", () => {
    // Llegan de un `useState` de la pantalla de arriba: ordenarlas en el sitio
    // cambiaría su estado por detrás.
    const filas = [{ ciudad: "Vigo" }, { ciudad: "Ávila" }];
    const copia = JSON.parse(JSON.stringify(filas));
    render(<Tabla filas={filas} />);
    ordenarPor("ciudad");
    expect(filas).toEqual(copia);
  });
});
