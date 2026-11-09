/**
 * Lo que enseñan las pantallas de marketing que salen de verdad
 * (CRM-02.02.02.05, CRM-02.03.01.07, CRM-02.03.01.06, CRM-02.02.02.04,
 * CRM-02.01.01.09).
 *
 * Lo que cambia el resultado: que el envío diga por qué va a esa hora y por qué
 * dominio salió, que el spam enseñe cada regla, que la prueba A/B diga a dónde
 * va el tráfico y que la audiencia enseñe sus bajas.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { EnviosProgramados } from "@/componentes/EnviosDeMarketing";
import { VistaPreviaCorreo } from "@/componentes/VistaPreviaCorreo";
import { AudienciaPublicitaria } from "@/paginas/AudienciaPublicitaria";
import { RecorridoDeMarketing } from "@/paginas/RecorridoDeMarketing";

const RESPUESTAS: [string, unknown][] = [
  [
    "/envios-programados?",
    {
      programados: 1,
      omitidos: 0,
      a_la_hora_general: 0,
      personalizados: 1,
      que_significa: "0 de 1 van a la hora general.",
      por_estado: { enviado: 1 },
      envios: [
        {
          id: "e1",
          objeto_id: "0123456789",
          nodo: null,
          canal: "email",
          clase: "transaccional",
          plantilla: "factura",
          programado_at: "2026-11-10T17:00:00Z",
          hora_local: 17,
          zona: "Europe/Madrid",
          como_hora: "historial",
          como_canal: "historial",
          porque: "De 9 respuestas, 7 llegaron alrededor de las 17:00.",
          estado: "enviado",
          motivo: null,
          dominio: "marca.com",
          remitente: "avisos@marca.com",
          flujo: "propio:smtp-tx",
        },
      ],
    },
  ],
  [
    "/vista-previa",
    {
      clase: "promocional",
      asunto: "Hola Ana",
      sin_dato: [],
      bloques_que_faltan: [],
      aviso_datos: "",
      datos: {},
      recomendaciones: {
        productos: [
          { nombre: "Freno B", porque: "Es de la familia «frenos»." },
        ],
        contenidos: [],
        porque: "Sale de 1 producto.",
      },
      clientes: [
        { clave: "movil", nombre: "Móvil", ancho: 375, html: "<p>x</p>" },
      ],
      spam: {
        puntos: 6,
        umbral: 5,
        veredicto: "basura",
        reglas: [
          {
            regla: "acortador",
            grupo: "enlaces",
            puntos: 1.2,
            porque: "Un enlace usa el acortador bit.ly: esconde el destino.",
          },
        ],
      },
      salida: {
        dominio: "info.marca.com",
        remitente: "n@info.marca.com",
        problemas: [],
      },
    },
  ],
  ["/contacts?", { items: [] }],
  [
    "/prueba/",
    {
      variantes: [
        { clave: "a", personas: 120, conversiones: 5, tasa: 4.2 },
        { clave: "b", personas: 120, conversiones: 30, tasa: 25 },
      ],
      ganadora: "b",
      concluyente: true,
      significativa: true,
      p_valor: 0.0001,
      alfa: 0.05,
      minimo: 100,
      ganadora_aplicada: "b",
      aviso: "«b» gana con p = 0.0001.",
    },
  ],
  ["/inscritos", []],
  [
    "/lienzo",
    {
      id: "r1",
      clave: "r",
      nombre: "Bienvenida",
      nodos: {
        ab: {
          tipo: "prueba",
          ganadora: "b",
          variantes: [
            { clave: "a", peso: 50, siguiente: "fin" },
            { clave: "b", peso: 50, siguiente: "fin" },
          ],
        },
        fin: { tipo: "fin" },
      },
      inicio: "ab",
      por_cuenta: true,
      estado: "publicado",
      version: 2,
      inscritos: {},
      tipos: [],
      comportamientos: [],
    },
  ],
  [
    "/audiencias-publicitarias/a1",
    {
      id: "a1",
      nombre: "Clientes",
      segmento_id: "s",
      conexion_id: "c",
      finalidad: "",
      id_externo: "AUD-1",
      estado: "sincronizada",
      miembros: 4,
      ultima_sync_at: null,
      ultimo_error: null,
      minimo: 100,
      finalidad_exigida: "perfilado",
      historial: [
        {
          id: "h1",
          at: "2026-11-09T10:00:00Z",
          ok: true,
          altas: 0,
          bajas: 1,
          en_el_segmento: 6,
          sin_consentimiento: 1,
          suprimidos: 1,
          error: null,
          porque: "",
        },
      ],
    },
  ],
  ["/correo/plantillas", []],
];

vi.mock("@/lib/api", () => ({
  llamar: vi.fn(async (ruta: string) => {
    for (const [trozo, datos] of RESPUESTAS) {
      if (ruta.includes(trozo)) return { datos };
    }
    return { datos: {} };
  }),
  salvoCancelacion: (f: (e: unknown) => void) => f,
  ErrorApi: class extends Error {},
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (clave: string, o?: Record<string, unknown>) =>
      o ? `${clave} ${JSON.stringify(o)}` : clave,
  }),
}));

describe("marketing que sale de verdad", () => {
  it("el envío dice por qué a esa hora y por qué dominio salió", async () => {
    render(<EnviosProgramados origen="campana" origenId="c1" />);
    expect(
      await screen.findByText(/7 llegaron alrededor de las 17:00/),
    ).toBeTruthy();
    expect(screen.getByText("avisos@marca.com")).toBeTruthy();
    expect(screen.getByText(/propio:smtp-tx/)).toBeTruthy();
  });

  it("el spam enseña cada regla con su porqué y las recomendaciones salen", async () => {
    render(<VistaPreviaCorreo clave="promo" idioma="es" />);
    expect(await screen.findByText(/acortador bit.ly/)).toBeTruthy();
    expect(screen.getByText("Freno B")).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Móvil/ })).toBeTruthy();
  });

  it("la prueba A/B dice a dónde va el tráfico nuevo", async () => {
    render(
      <MemoryRouter initialEntries={["/m/campanas/recorrido/r1"]}>
        <Routes>
          <Route
            path="/m/campanas/recorrido/:id"
            element={<RecorridoDeMarketing />}
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/mk.recorrido.yendoA/)).toBeTruthy();
    expect(
      screen.getByRole("img", { name: "mk.recorrido.lienzo" }),
    ).toBeTruthy();
  });

  it("la audiencia enseña sus bajas en el historial", async () => {
    render(
      <MemoryRouter initialEntries={["/m/segmentos/audiencia_publicitaria/a1"]}>
        <Routes>
          <Route
            path="/m/segmentos/audiencia_publicitaria/:id"
            element={<AudienciaPublicitaria />}
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/AUD-1/)).toBeTruthy();
    expect(screen.getAllByRole("row").length).toBeGreaterThan(1);
  });
});
