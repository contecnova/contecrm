/**
 * La barra de una ficha no puede enseñar dos pestañas iguales.
 *
 * Lo vio quien lo usa el 04-11-2026 en la ficha de un candidato: «Relacionado ·
 * Detalles · Actividad · **Comentarios · Comentarios**». Dos entradas con el
 * mismo rótulo, una al lado de la otra, que no se distinguen más que
 * pulsándolas — que es justo lo que un rótulo viene a evitar.
 *
 * Sale de juntar dos fuentes que no se miran: `Ficha.tsx` declara sus pestañas
 * a partir de lo que el registro puede tener —y la conversación es una de
 * ellas— y `PestanasDeFicha` añade la conversación por su cuenta cuando la
 * superficie dice que ese objeto admite comentarios. Las dos tenían razón; lo
 * que faltaba era que la segunda mirase si ya estaba.
 *
 * Se compara por **clave** y no por rótulo: el rótulo se traduce, y dos claves
 * distintas pueden acabar llamándose igual en un idioma y no en otro.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

// La superficie dice que «lead» admite comentarios, que es el caso del aviso.
vi.mock("@/lib/permisos", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/permisos")>();
  return {
    ...real,
    useSuperficie: () => ({
      superficie: { operaciones: [], objetos: { comentarios: ["lead"] } },
    }),
  };
});

const { PestanasDeFicha, CLAVE_CONVERSACION } = await import(
  "@/componentes/PestanasDeFicha"
);

function pintar(pestanas: { clave: string; nombre: string }[]) {
  return render(
    <PestanasDeFicha
      tipo="lead"
      id="01a17edf-0000-0000-0000-000000000000"
      etiqueta="secciones"
      pestanas={pestanas}
      activa={pestanas[0]?.clave ?? CLAVE_CONVERSACION}
      alElegir={() => {}}
    />,
  );
}

describe("las pestañas de una ficha", () => {
  it("no repiten la conversación cuando quien llama ya la trae", () => {
    pintar([
      { clave: "relacionado", nombre: "ficha.relacionado" },
      { clave: "detalles", nombre: "ficha.detalles" },
      { clave: CLAVE_CONVERSACION, nombre: "ficha.comentarios" },
    ]);
    expect(screen.getAllByRole("button", { name: "ficha.comentarios" })).toHaveLength(1);
  });

  it("y la añade cuando no la trae, que es para lo que está", () => {
    // La otra mitad: las fichas que no la declaran la siguen teniendo. Sin
    // esto, «no repetir» se podría cumplir no ofreciéndola nunca.
    pintar([
      { clave: "relacionado", nombre: "ficha.relacionado" },
      { clave: "detalles", nombre: "ficha.detalles" },
    ]);
    expect(screen.getAllByRole("button", { name: "ficha.comentarios" })).toHaveLength(1);
  });

  it("y ninguna barra tiene dos pestañas con la misma clave", () => {
    pintar([
      { clave: "relacionado", nombre: "ficha.relacionado" },
      { clave: "detalles", nombre: "ficha.detalles" },
      { clave: CLAVE_CONVERSACION, nombre: "ficha.comentarios" },
    ]);
    // Las pestañas son botones dentro del `nav` de la barra, no `role="tab"`.
    const barra = screen.getByRole("navigation", { name: "secciones" });
    const rotulos = [...barra.querySelectorAll("button")].map((t) => t.textContent);
    expect(new Set(rotulos).size).toBe(rotulos.length);
  });
});
