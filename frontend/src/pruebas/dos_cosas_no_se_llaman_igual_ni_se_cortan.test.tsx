/**
 * Dos cosas distintas no se llaman igual, y lo que se corta se puede leer.
 *
 * Las dos salieron el 05-11-2026 del barrido de pantallas, al enseñarle a
 * mirar lo que quien lo usa venía encontrando a ojo.
 *
 * **Doce entradas llamadas «papelera».** En `/administracion` las áreas se
 * agrupan por recurso —bien: son doce áreas distintas, con sus cuatro
 * operaciones cada una— pero el rótulo sale de la etiqueta del contrato, y
 * «papelera» la usan los doce servicios. En pantalla: doce filas idénticas y
 * dos «ajustes», imposibles de distinguir sin pulsarlas una a una.
 *
 * **Rótulos de gráfica cortados y sin nombre entero.** El embudo y el eje
 * recortan a mano con puntos suspensivos —un eje no da para más— y no dejaban
 * el nombre completo en ninguna parte: «Pendiente d…» no dice de qué etapa
 * habla. En SVG el sitio es un `<title>` dentro del propio elemento, que
 * además lo lee quien no ve la gráfica.
 */

import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { areasDeAdministracion } from "@/lib/superficie";
import type { Superficie } from "@/lib/superficie";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

function operacion(ruta: string, etiqueta: string) {
  return {
    metodo: "GET",
    ruta,
    resumen: "",
    etiquetas: [etiqueta],
    permiso: null,
    administracion: true,
    servicio: ruta.split("/")[3],
  };
}

describe("las áreas de administración", () => {
  it("apellidan el nombre que se repite, y sólo ése", () => {
    const superficie = {
      operaciones: [
        operacion("/api/v1/sales/papelera", "papelera"),
        operacion("/api/v1/marketing/papelera", "papelera"),
        operacion("/api/v1/service/papelera", "papelera"),
        operacion("/api/v1/tenancy/monedas", "monedas"),
      ],
    } as unknown as Superficie;

    const nombres = areasDeAdministracion(superficie).map((a) => a.nombre);
    // Ninguna repetida: es lo que hacía la lista inservible.
    expect(new Set(nombres).size).toBe(nombres.length);
    // Y el apellido dice CUÁL es cada una.
    expect(nombres).toContain("papelera · sales");
    expect(nombres).toContain("papelera · marketing");
    // El que no choca se queda como estaba: apellidar todo haría la lista más
    // larga y más ruidosa para distinguir lo que ya se distinguía solo.
    expect(nombres).toContain("monedas");
  });
});

describe("los rótulos de una gráfica", () => {
  it("cortados, pero con el nombre entero dentro", async () => {
    const { Grafica } = await import("@/componentes/graficas/Grafica");
    const { container } = render(
      <Grafica
        titulo="Embudo"
        forma="embudo"
        datos={{
          filas: [
            { etapa: "Pendiente de adjudicación muy larga", importe: 100 },
            { etapa: "Corta", importe: 40 },
          ],
          ejeX: "etapa",
          series: [{ clave: "importe", rotulo: "Importe" }],
          unidad: "€",
        }}
      />,
    );

    const textos = [...container.querySelectorAll("svg text")];
    const cortados = textos.filter((t) => (t.textContent ?? "").endsWith("…"));
    expect(cortados.length, "no se ha cortado ningún rótulo: la prueba no mira nada").toBeGreaterThan(0);
    for (const t of cortados) {
      const entero = t.querySelector("title")?.textContent ?? "";
      expect(entero, `«${t.textContent}» se corta y no deja el nombre entero`).toContain(
        "Pendiente de adjudicación",
      );
    }
    // Y lo que cabe no lleva `title`: repetir el mismo texto en un tooltip es
    // ruido para quien lee con un lector de pantalla.
    const cortos = textos.filter((t) => !(t.textContent ?? "").endsWith("…"));
    for (const t of cortos) expect(t.querySelector("title")).toBeNull();
  });
});
