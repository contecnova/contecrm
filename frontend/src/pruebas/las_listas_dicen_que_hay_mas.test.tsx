/**
 * Las listas que el servidor recorta dicen que hay más (auditoría 13-11-2026,
 * COB-16).
 *
 * El panel de firma, el registro de llamadas al proveedor de firma, las
 * llamadas de telefonía y las propuestas de identidad enseñaban las primeras
 * filas como si fueran todas. Ahora el servidor da el total y la pantalla pone
 * el aviso de recorte; y la telefonía, que se tragaba el error y enseñaba «no
 * hay llamadas», lo dice como fallo.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CalidadDelDato } from "@/paginas/CalidadDelDato";
import { PendienteDeFirma } from "@/paginas/PendienteDeFirma";
import { Telefonia } from "@/paginas/Telefonia";

let respuestas: Record<string, unknown> = {};
let fallaTelefonia = false;

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    if (fallaTelefonia && ruta.includes("/telefonia/llamadas"))
      throw new Error("la centralita no contesta");
    const clave = Object.keys(respuestas).find((r) => ruta.includes(r));
    return { datos: clave ? respuestas[clave] : { items: [] } };
  }),
  salvoCancelacion: (f: (e: unknown) => void) => f,
  ErrorApi: class extends Error {},
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, datos?: Record<string, unknown>) =>
      datos ? `${clave}:${JSON.stringify(datos)}` : clave,
  }),
}));

const sobre = (n: number) => ({
  sobre_id: `s${n}`,
  referencia: `SOB-${n}`,
  asunto: `Sobre ${n}`,
  estado: "enviado",
  nivel: "simple",
  proveedor: "p",
  objeto_origen: "",
  objeto_origen_id: null,
  dias_esperando: 3,
  firmados: 0,
  total: 1,
  esperando_a: [],
  caduca_en_dias: null,
  nadie_lo_ha_abierto: true,
});

describe("las listas recortadas dicen que hay más", () => {
  beforeEach(() => {
    fallaTelefonia = false;
    respuestas = {
      "/firma/proveedores": [],
      "/firma/reglas": { reglas: [], que_significa: "" },
      "/firma/plantillas": { plantillas: [] },
      "/firma/llamadas": {
        llamadas: [],
        cuantas: 0,
        total: 0,
        hay_mas: false,
        gasto: "0",
        fallidas: 0,
        gasto_de_las_fallidas: "0",
        aviso: "",
      },
    };
  });

  it("el panel de firma cuenta el total y avisa del recorte", async () => {
    respuestas["/firma/panel"] = {
      sobres: [sobre(1)],
      cuantos: 1,
      total: 7,
      hay_mas: true,
      medible: true,
    };
    render(
      <MemoryRouter>
        <PendienteDeFirma />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText('firma.cuantos:{"cuantos":7}'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('listas.recortada:{"count":1}'),
    ).toBeInTheDocument();
  });

  it("las llamadas de telefonía avisan del recorte", async () => {
    respuestas["/telefonia/perfil"] = { conexion_id: "", webhook: {} };
    respuestas["/telefonia/llamadas"] = {
      llamadas: [
        { id: "l1", sentido: "entrante", numero: "600", estado: "colgada" },
      ],
      total: 40,
      hay_mas: true,
    };
    render(
      <MemoryRouter>
        <Telefonia />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText('listas.recortada:{"count":1}'),
    ).toBeInTheDocument();
  });

  it("si las llamadas no llegan se dice, no se enseña la lista vacía", async () => {
    fallaTelefonia = true;
    respuestas["/telefonia/perfil"] = { conexion_id: "", webhook: {} };
    render(
      <MemoryRouter>
        <Telefonia />
      </MemoryRouter>,
    );
    // El fallo se dice con el panel que falta, y no como «no hay llamadas».
    expect(
      await screen.findByText(/cargaSecundaria\.falloDe/),
    ).toBeInTheDocument();
    expect(screen.queryByText("telefonia.sinLlamadas")).not.toBeInTheDocument();
  });

  it("las propuestas de identidad avisan cuando hay más de las que se ven", async () => {
    // Las otras secciones de la página, con su forma real y vacías.
    respuestas["/golden/reglas"] = { reglas: [], campos: [], estrategias: [] };
    respuestas["/identidades/propuestas"] = {
      umbral: 60,
      cuantas: 120,
      propuestas: [
        { a: "c1", b: "c2", a_nombre: "Ana", b_nombre: "Ana P.", puntuacion: 90, senales: [] },
      ],
    };
    render(
      <MemoryRouter>
        <CalidadDelDato />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText("calidadDelDato.propuestasPorPuntuacion"),
    ).toBeInTheDocument();
  });
});
