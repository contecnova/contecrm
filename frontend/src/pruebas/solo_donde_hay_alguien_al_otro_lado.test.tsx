/**
 * Llamada, reunión, nota y correo sólo donde hay alguien al otro lado.
 *
 * La ficha los ofrecía sobre los **52** tipos de registro que declara el front,
 * porque el campo `objeto` de una actividad es polimórfico y el servidor no
 * rechaza nada. Salían botones de «Llamada» y «Correo» sobre un plan de cuenta,
 * un calendario laboral o una entrada de papelera. Ofrecer lo que no tiene
 * sentido no es un detalle estético: hace dudar de lo que sí lo tiene.
 *
 * Quién sí y quién no **lo dice el servidor**, en `objetos.actividades` de la
 * superficie, junto a las tres listas que ya contestaban la misma clase de
 * pregunta —adjuntos, comentarios, documentos—. Una lista en el front sería una
 * segunda que acabaría diciendo otra cosa.
 *
 * Y mientras la superficie no ha llegado **no se ofrecen**, al revés que las
 * pestañas: es la regla de la casa para las acciones, porque un botón que
 * aparece por defecto y luego resulta que no tocaba es un botón que alguien ya
 * ha pulsado.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

let objetosDeActividad: string[] | undefined = ["cuenta"];
let superficieLlegada = true;

vi.mock("@/lib/permisos", () => ({
  useSuperficie: () => ({
    superficie: superficieLlegada
      ? {
          // La ficha también recorre `operaciones` para saber qué acciones
          // ofrecer. Un doble sin ellas revienta donde el código sí mira, y
          // eso dice «la pantalla está rota» cuando lo que faltaba era el
          // doble.
          operaciones: [],
          objetos: {
            adjuntos: [],
            comentarios: [],
            documentos: [],
            actividades: objetosDeActividad,
          },
        }
      : null,
    tiene: () => true,
  }),
  usePuedeOperar: () => () => true,
  useVisibilidad: () => ({
    rutas: new Set<string>(),
    cargada: false,
    sinContestar: new Set<string>(),
  }),
}));

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(async () => ({
      datos: { id: "r-1", nombre: "Lo que sea" },
      version: null,
      retenidos: [],
      enmascarados: [],
    })),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (clave: string) => clave }),
}));

async function abrir(objeto: string) {
  const { Ficha } = await import("@/paginas/Ficha");
  return render(
    <MemoryRouter initialEntries={[`/m/cuentas/${objeto}/r-1`]}>
      <Routes>
        {/* Los mismos nombres de parámetro que `App.tsx`: con otros, la ficha
            no sabe ni de qué módulo es y pinta el vacío. */}
        <Route path="/m/:ruta/:tipo/:id" element={<Ficha />} />
      </Routes>
    </MemoryRouter>,
  );
}

/**
 * Desde el 02-11-2026 lo que se ofrece es **la pestaña «Actividad»**, que es
 * donde Lightning pone lo que se habla con un registro; dentro están los
 * cuatro botones de siempre. Así que la pregunta «¿se ofrece?» se contesta
 * mirando si la pestaña existe, y la pestaña se abre para ver los botones.
 */
async function pestanaDeActividad() {
  await waitFor(() =>
    expect(screen.getByText("ficha.detalles")).toBeInTheDocument(),
  );
  return screen.queryByText("ficha.actividad");
}

describe("apuntar una llamada", () => {
  beforeEach(() => {
    objetosDeActividad = ["cuenta"];
    superficieLlegada = true;
  });

  it("se ofrece sobre lo que el servidor dice", async () => {
    await abrir("cuenta");
    const pestana = await pestanaDeActividad();
    expect(pestana).not.toBeNull();
    pestana!.click();
    await waitFor(() =>
      expect(screen.getByText("actividad.llamada")).toBeInTheDocument(),
    );
  });

  it("no se ofrece sobre un registro de configuración", async () => {
    // El caso que lo destapó: un plan de cuenta con botones de «Llamada» y
    // «Correo». No hay nadie al otro lado de un plan.
    await abrir("plan_cuenta");
    expect(await pestanaDeActividad()).toBeNull();
    expect(screen.queryByText("actividad.llamada")).toBeNull();
  });

  it("mientras la superficie no ha llegado, no se ofrece", async () => {
    // Al revés que las otras pestañas: un botón que aparece por defecto y
    // luego resulta que no tocaba es un botón que alguien ya ha pulsado.
    superficieLlegada = false;
    await abrir("cuenta");
    expect(await pestanaDeActividad()).toBeNull();
    expect(screen.queryByText("actividad.llamada")).toBeNull();
  });

  it("si el servidor no publica la lista, tampoco se inventa", async () => {
    // Una versión del servidor sin `objetos.actividades` no es permiso para
    // ofrecerlo todo: es que no se sabe.
    objetosDeActividad = undefined;
    await abrir("cuenta");
    expect(await pestanaDeActividad()).toBeNull();
    expect(screen.queryByText("actividad.llamada")).toBeNull();
  });
});
