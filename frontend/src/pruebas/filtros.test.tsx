/**
 * Los filtros del listado.
 *
 * Lo que se vigila es lo que haría que un filtro mintiera sin que se note:
 *
 *   · que filtre **en el servidor** y no sobre lo ya recibido. Con paginación
 *     por cursor, filtrar en el navegador recorta sólo la página que ya se
 *     había traído y enseña «3 resultados» cuando hay cuarenta;
 *   · que el tipo de la columna salga de la primera fila **con valor**, y no
 *     de la primera fila: en una columna casi vacía todo parecería texto y se
 *     ofrecerían los operadores equivocados;
 *   · y que quitar un filtro lo quite de la URL en vez de dejarlo vacío, que
 *     el servidor interpretaría como «igual a nada».
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Filtros } from "@/componentes/Filtros";
import {
  comoQuery,
  leerFiltros,
  operadoresDe,
  parametroDe,
  tipoDe,
  type Filtro,
} from "@/lib/filtros";

describe("de qué tipo es cada columna", () => {
  it("se mira la primera fila CON VALOR, no la primera", () => {
    // En una columna mayoritariamente vacía la primera suele estar vacía, y
    // entonces todo saldría como texto: a una fecha se le ofrecerían «es» y
    // «no es» en vez de «desde» y «hasta».
    const filas = [
      { cierre: null, importe: null },
      { cierre: "", importe: "" },
      { cierre: "2026-10-26T09:00:00Z", importe: 1200 },
    ];
    expect(tipoDe(filas, "cierre")).toBe("fecha");
    expect(tipoDe(filas, "importe")).toBe("numero");
  });

  it("un importe que viaja como texto sigue siendo un número", () => {
    // La API los manda así a propósito, para no perder precisión en coma
    // flotante. Tratarlos como texto quitaría «más de», que es justo lo que se
    // pregunta de un importe.
    expect(tipoDe([{ importe: "1200.50" }], "importe")).toBe("numero");
  });

  it("no se confunde un número con una fecha", () => {
    // `Date.parse("5")` devuelve una fecha válida. Por eso se reconocen por la
    // forma ISO y no intentando convertir.
    expect(tipoDe([{ x: "5" }], "x")).toBe("numero");
    expect(tipoDe([{ x: "Acme" }], "x")).toBe("texto");
    expect(tipoDe([{ x: true }], "x")).toBe("booleano");
  });

  it("una columna vacía del todo cae a texto y no revienta", () => {
    expect(tipoDe([{ x: null }, { x: undefined }], "x")).toBe("texto");
    expect(tipoDe([], "x")).toBe("texto");
  });
});

describe("qué operadores se ofrecen", () => {
  it("una fecha ofrece rangos y un booleano no", () => {
    const fecha = operadoresDe("fecha").map((o) => o.sufijo);
    expect(fecha).toContain("desde");
    expect(fecha).toContain("hasta");
    // «más de» sobre un booleano no significa nada, y un desplegable con
    // opciones que no aplican se lee entero cada vez.
    expect(operadoresDe("booleano").map((o) => o.sufijo)).not.toContain("mayor");
  });

  it("los que no llevan valor están marcados", () => {
    const vacio = operadoresDe("texto").find((o) => o.sufijo === "vacio");
    expect(vacio?.conValor).toBe(false);
    expect(operadoresDe("texto").find((o) => o.sufijo === "")?.conValor).toBe(true);
  });

  it("todos los sufijos son de la gramática del servidor", () => {
    // Si alguien añade aquí uno inventado, el servidor contesta 422 y el
    // usuario ve un error sobre un filtro que la propia pantalla le ofreció.
    const DEL_SERVIDOR = new Set([
      "",
      "desde",
      "hasta",
      "mayor",
      "menor",
      "distinto",
      "en",
      "no_en",
      "vacio",
      "no_vacio",
    ]);
    for (const tipo of ["fecha", "numero", "booleano", "texto"] as const) {
      for (const op of operadoresDe(tipo)) {
        expect(DEL_SERVIDOR, `«${op.sufijo}» no existe en el servidor`).toContain(op.sufijo);
      }
    }
  });
});

describe("cómo viajan en la URL", () => {
  it("la igualdad no lleva sufijo y el resto sí", () => {
    expect(parametroDe({ campo: "estado", sufijo: "", valor: "abierta" })).toBe("estado");
    expect(parametroDe({ campo: "importe", sufijo: "mayor", valor: "50000" })).toBe(
      "importe__mayor",
    );
  });

  it("se leen de vuelta tal como se escribieron", () => {
    const params = new URLSearchParams("estado=abierta&importe__mayor=50000&cursor=XYZ&r=Cuentas");
    const leidos = leerFiltros(params);
    // `cursor` gobierna la paginación, no qué filas salen: no es un filtro.
    //
    // Y `r` tampoco, aunque esta prueba dijera lo contrario hasta el
    // 27-10-2026: es la pestaña abierta, la escribe la propia pantalla de
    // módulo, y al mandarla al servidor como si fuera un campo la respuesta
    // era un 422 «No se puede filtrar por «r»». La prueba no cazó el fallo
    // porque LO DABA POR BUENO — es el caso que convierte una prueba en un
    // candado sobre el defecto.
    expect(leidos.map(parametroDe).sort()).toEqual(["estado", "importe__mayor"]);
  });

  it("el término de búsqueda no se confunde con un filtro", () => {
    // Si se colara, la pastilla enseñaría «q: acme» y quitarla no quitaría la
    // búsqueda, que vive en su propia caja.
    const params = new URLSearchParams("q=acme&estado=abierta");
    expect(leerFiltros(params, "q").map(parametroDe)).toEqual(["estado"]);
  });

  it("los valores se codifican", () => {
    const q = comoQuery([{ campo: "vence_at", sufijo: "hasta", valor: "2026-10-26T23:59:59+02:00" }]);
    // El `+` de un desfase horario viaja como espacio si no se codifica, y el
    // servidor devolvería un error de formato que no entiende nadie.
    expect(q).toContain("%2B");
    expect(q).toContain("vence_at__hasta");
  });
});

describe("la barra", () => {
  const FILAS = [{ estado: "abierta", importe: 1200, cierre: "2026-10-26" }];

  it("añade un filtro con el operador elegido", async () => {
    const alCambiar = vi.fn();
    render(
      <Filtros
        campos={["estado", "importe", "cierre"]}
        filas={FILAS}
        puestos={[]}
        alCambiar={alCambiar}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /filtros\.anadir/i }));
    await userEvent.selectOptions(screen.getByLabelText("filtros.campo"), "importe");
    await userEvent.selectOptions(screen.getByLabelText("filtros.operador"), "mayor");
    await userEvent.type(screen.getByLabelText("filtros.valor"), "50000");
    await userEvent.click(screen.getByRole("button", { name: "filtros.aplicar" }));

    expect(alCambiar).toHaveBeenCalledWith([
      { campo: "importe", sufijo: "mayor", valor: "50000" },
    ]);
  });

  it("un operador sin valor se aplica sin escribir nada", async () => {
    const alCambiar = vi.fn();
    render(<Filtros campos={["estado"]} filas={FILAS} puestos={[]} alCambiar={alCambiar} />);

    await userEvent.click(screen.getByRole("button", { name: /filtros\.anadir/i }));
    await userEvent.selectOptions(screen.getByLabelText("filtros.campo"), "estado");
    await userEvent.selectOptions(screen.getByLabelText("filtros.operador"), "vacio");
    // No hay caja de valor: pedirla sería pedir algo que no se va a usar.
    expect(screen.queryByLabelText("filtros.valor")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "filtros.aplicar" }));

    expect(alCambiar).toHaveBeenCalledWith([{ campo: "estado", sufijo: "vacio", valor: "1" }]);
  });

  it("lo puesto se ve, y se puede quitar de uno en uno", async () => {
    const puestos: Filtro[] = [
      { campo: "estado", sufijo: "", valor: "abierta" },
      { campo: "importe", sufijo: "mayor", valor: "50000" },
    ];
    const alCambiar = vi.fn();
    render(<Filtros campos={["estado", "importe"]} filas={FILAS} puestos={puestos} alCambiar={alCambiar} />);

    // Ver qué recorte estás mirando importa más que poder añadir el siguiente.
    expect(screen.getByText(/50000/)).toBeInTheDocument();
    // Por posición y no por nombre: el rótulo accesible lleva el campo
    // interpolado, y aquí `t()` devuelve la clave, así que los dos aspas se
    // llamarían igual. En la aplicación sí se distinguen.
    const aspas = screen.getAllByRole("button", { name: "filtros.quitar" });
    expect(aspas).toHaveLength(2);
    await userEvent.click(aspas[1]!);
    expect(alCambiar).toHaveBeenCalledWith([{ campo: "estado", sufijo: "", valor: "abierta" }]);
  });

  it("no se puede aplicar un filtro a medias", async () => {
    render(<Filtros campos={["estado"]} filas={FILAS} puestos={[]} alCambiar={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /filtros\.anadir/i }));
    // Sin campo elegido, aplicar no hace nada: mandarlo produciría un 422 y el
    // usuario vería un error del servidor por no haber rellenado un hueco.
    expect(screen.getByRole("button", { name: "filtros.aplicar" })).toBeDisabled();
  });
});

describe("los parámetros que gobiernan la pantalla no son filtros", () => {
  it("«r» y «nuevo» no viajan al servidor", () => {
    /**
     * Los escribe la propia pantalla de módulo —`r` es la pestaña abierta y
     * `nuevo=1` abre el alta— y al leerlos de vuelta se mandaban como si
     * fueran campos del objeto. La respuesta era un 422 «No se puede filtrar
     * por «r»» con la lista de columnas debajo, y lo veía cualquiera que
     * pulsara «crear» desde una pestaña: la pantalla entera en rojo en vez
     * del formulario.
     */
    const params = new URLSearchParams("r=Pipelines&nuevo=1&estado=abierta");
    const filtros = leerFiltros(params);
    expect(filtros.map((f) => f.campo)).toEqual(["estado"]);
    expect(comoQuery(filtros)).toBe("estado=abierta");
  });

  it("y los de paginación y formato tampoco", () => {
    const params = new URLSearchParams("cursor=abc&limite=50&formato=csv&tier=oro");
    expect(leerFiltros(params).map((f) => f.campo)).toEqual(["tier"]);
  });
});
