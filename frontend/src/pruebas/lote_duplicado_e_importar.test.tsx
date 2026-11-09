/**
 * Lo que se hace con varios registros, con uno repetido y con un fichero
 * (CRM-00.02.01.11, CRM-01.01.03.03, CRM-07.01.01.07, CRM-07.01.01.08,
 * CRM-03.02.01.02).
 *
 * Se afirma lo que decide:
 *
 * - un 409 por duplicado enseña los candidatos y **sólo** ofrece «Es otro,
 *   crearlo igual» cuando el alta admite `forzar`, y al pulsarlo lo manda;
 * - la tabla elige filas y el lote manda lo elegido con la operación y enseña
 *   el informe con el NOMBRE de lo que falló, no su posición;
 * - duplicar copia lo que el alta admite, sin `forzar` ni líneas;
 * - el CSV se lee con el `;` de Excel, comillas y BOM, y el mapeo propone solo
 *   lo que casa por nombre;
 * - el traspaso simula en los dos servicios antes de dejar confirmar;
 * - la previsión pinta el árbol que resuelve el servidor y el agujero.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const llamadas: {
  ruta: string;
  opciones?: { metodo?: string; cuerpo?: unknown };
}[] = [];
let respuesta: (ruta: string, cuerpo: unknown) => unknown = () => ({});

vi.mock("@/lib/api", async () => {
  const real = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...real,
    llamar: vi.fn(
      async (
        ruta: string,
        opciones?: { metodo?: string; cuerpo?: unknown },
      ) => {
        llamadas.push({ ruta, opciones });
        return {
          datos: respuesta(ruta, opciones?.cuerpo),
          version: null,
          retenidos: [],
          enmascarados: [],
        };
      },
    ),
  };
});

import { AccionesMasivas } from "@/componentes/AccionesMasivas";
import { Formulario, candidatosDe } from "@/componentes/Formulario";
import { Tabla } from "@/componentes/Tabla";
import { ErrorApi } from "@/lib/api";
import type { CampoEsquema } from "@/lib/contrato";
import { leerCsv } from "@/lib/csv";
import { valoresParaDuplicar } from "@/paginas/Modulo";
import { filasMapeadas, mapeoInicial } from "@/paginas/ImportarDatos";
import { TransferirPropiedad } from "@/paginas/TransferirPropiedad";

function campo(
  nombre: string,
  extra: Partial<CampoEsquema> = {},
): CampoEsquema {
  return {
    nombre,
    tipo: "texto",
    obligatorio: false,
    titulo: nombre,
    descripcion: "",
    opciones: [],
    maximo: null,
    formato: "",
    subcampos: [],
    referencia: "",
    ...extra,
  };
}

const conflicto = new ErrorApi(
  409,
  "sales.lead_duplicado",
  "Conflicto",
  {
    candidatos: [
      {
        objeto: "lead",
        id: "l-1",
        nombre: "Ana · ACME",
        similitud: 1,
        senales: ["email"],
        concluyente: true,
      },
    ],
    contactos_consultados: false,
  },
  "Ya existe un lead o un contacto que parece el mismo",
);

// Con los textos de verdad y no con las claves: así la prueba también caza un
// texto que falte en `es.ts` o en `es.pantallas.ts`.
beforeAll(async () => {
  const { cargarTextosDePantallas, iniciarI18n } = await import("@/i18n");
  await iniciarI18n("es");
  await cargarTextosDePantallas();
});

beforeEach(() => {
  llamadas.length = 0;
  respuesta = () => ({});
});

describe("el 409 por duplicado tiene salida", () => {
  it("enseña los candidatos y manda forzar al pulsar «Es otro»", async () => {
    const alEnviar = vi.fn();
    render(
      <MemoryRouter>
        <Formulario
          campos={[
            campo("email", { obligatorio: true }),
            campo("forzar", { tipo: "booleano" }),
          ]}
          valores={{ email: "ana@acme.es" }}
          fallo={conflicto}
          textoEnviar="Crear"
          alEnviar={alEnviar}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("Ana · ACME")).toBeInTheDocument();
    expect(
      screen.getByText(/maestro de clientes no ha contestado/),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Es otro, crearlo igual" }),
    );
    expect(alEnviar).toHaveBeenCalledWith({
      email: "ana@acme.es",
      forzar: true,
    });
  });

  it("sin `forzar` en el alta no ofrece el botón", () => {
    render(
      <MemoryRouter>
        <Formulario
          campos={[campo("email")]}
          fallo={conflicto}
          textoEnviar="Crear"
          alEnviar={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(
      screen.queryByRole("button", { name: "Es otro, crearlo igual" }),
    ).toBeNull();
  });

  it("otro 409 no es un duplicado", () => {
    expect(
      candidatosDe(new ErrorApi(409, "conflicto_de_version", "", {})),
    ).toBeNull();
  });
});

describe("el lote desde la tabla", () => {
  it("la tabla elige filas y todas las que se ven", () => {
    const alCambiar = vi.fn();
    render(
      <MemoryRouter>
        <Tabla
          filas={[
            { id: "a", nombre: "Alfa" },
            { id: "b", nombre: "Beta" },
          ]}
          seleccion={{ elegidos: new Set(), alCambiar }}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByLabelText("Elegir «Beta»"));
    expect([...alCambiar.mock.calls[0]![0]]).toEqual(["b"]);
    fireEvent.click(screen.getByLabelText("Elegir todas las que se ven"));
    expect([...alCambiar.mock.calls[1]![0]]).toEqual(["a", "b"]);
  });

  it("actualiza un campo y el informe dice CUÁL falló", async () => {
    respuesta = () => ({
      total: 2,
      creados: 0,
      actualizados: 1,
      borrados: 0,
      fallidos: 1,
      errores: [{ fila: 2, motivo: "El lead no existe" }],
    });
    const alTerminar = vi.fn();
    render(
      <AccionesMasivas
        ruta="/api/v1/leads/masivo"
        operaciones={["crear", "actualizar", "borrar"]}
        ids={["a", "b"]}
        nombres={{ a: "Alfa", b: "Beta" }}
        campos={[campo("empresa", { titulo: "Empresa" })]}
        alTerminar={alTerminar}
        alQuitar={vi.fn()}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Actualizar un campo" }),
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Qué campo"),
      "empresa",
    );
    await userEvent.type(screen.getByLabelText("Empresa"), "ACME");
    await userEvent.click(screen.getByRole("button", { name: "Aplicar a 2" }));

    await waitFor(() => expect(alTerminar).toHaveBeenCalled());
    expect(llamadas[0]).toEqual({
      ruta: "/api/v1/leads/masivo",
      opciones: {
        metodo: "POST",
        cuerpo: {
          operacion: "actualizar",
          elementos: [
            { id: "a", empresa: "ACME" },
            { id: "b", empresa: "ACME" },
          ],
        },
      },
    });
    expect(screen.getByText("Actualizados 1 de 2.")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("El lead no existe")).toBeInTheDocument();
  });

  it("sin «borrar» en el contrato no ofrece borrar", () => {
    render(
      <AccionesMasivas
        ruta="/api/v1/x/masivo"
        operaciones={["crear", "actualizar"]}
        ids={["a"]}
        nombres={{}}
        campos={[campo("empresa")]}
        alTerminar={vi.fn()}
        alQuitar={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Borrar" })).toBeNull();
  });
});

describe("duplicar e importar", () => {
  it("duplicar copia lo que el alta admite, sin forzar ni líneas", () => {
    const valores = valoresParaDuplicar(
      {
        id: "x",
        nombre: "Op",
        importe: "1200.50",
        forzar: true,
        lineas: [{ a: 1 }],
        etapa_id: "e",
      },
      [
        campo("nombre"),
        campo("importe", { tipo: "numero" }),
        campo("forzar", { tipo: "booleano" }),
        campo("lineas", { tipo: "lineas" }),
      ],
      "(copia)",
    );
    expect(valores).toEqual({ nombre: "Op (copia)", importe: 1200.5 });
  });

  it("el CSV de Excel en español se lee con su separador, comillas y BOM", () => {
    const csv = leerCsv(
      '﻿Nombre;Correo;Nota\r\n"García; S.L.";a@b.es;"dice ""hola"""\r\n\r\n',
    );
    expect(csv.separador).toBe(";");
    expect(csv.cabeceras).toEqual(["Nombre", "Correo", "Nota"]);
    expect(csv.filas).toEqual([["García; S.L.", "a@b.es", 'dice "hola"']]);
  });

  it("el mapeo propone lo que casa por nombre y los propios por su título", () => {
    const csv = leerCsv("Nombre,E-mail,Zona comercial,Otra\nAlfa,,Norte,x\n");
    const mapeo = mapeoInicial(csv.cabeceras, [
      {
        nombre: "nombre",
        titulo: "nombre",
        tipo: "texto",
        obligatorio: true,
        propio: false,
      },
      {
        nombre: "email",
        titulo: "email",
        tipo: "texto",
        obligatorio: false,
        propio: false,
      },
      {
        nombre: "zona",
        titulo: "Zona comercial",
        tipo: "texto",
        obligatorio: false,
        propio: true,
      },
    ]);
    expect(mapeo).toEqual({ 0: "nombre", 2: "zona" });
    // Los vacíos no se mandan: un "" pisaría un dato con nada.
    expect(filasMapeadas(csv, mapeo)).toEqual([
      { nombre: "Alfa", zona: "Norte" },
    ]);
  });
});

describe("el traspaso de cartera", () => {
  it("simula en los dos servicios y sólo entonces deja confirmar", async () => {
    respuesta = (ruta) => {
      if (ruta.startsWith("/api/v1/usuarios"))
        return {
          items: [
            { id: "u-1", nombre: "Marta", email: "marta@x.es" },
            { id: "u-2", nombre: "Pablo", email: "pablo@x.es" },
          ],
        };
      if (ruta.startsWith("/api/v1/party-admin"))
        return { simulado: true, movidos: { cuentas: 3 }, total: 3 };
      return { simulado: true, movidos: { oportunidades: 2 }, total: 2 };
    };
    render(
      <MemoryRouter>
        <TransferirPropiedad />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(
        screen.getAllByRole("option", { name: /Marta/ }).length,
      ).toBeGreaterThan(0),
    );
    await userEvent.selectOptions(screen.getByLabelText("De"), "u-1");
    await userEvent.selectOptions(screen.getByLabelText("A"), "u-2");
    await userEvent.click(
      screen.getByRole("button", { name: "Simular el traspaso" }),
    );

    expect(
      await screen.findByText("En total, 5 registros."),
    ).toBeInTheDocument();
    const traspasos = llamadas.filter((l) =>
      l.ruta.endsWith("/transferir-propiedad"),
    );
    expect(traspasos.map((l) => l.ruta).sort()).toEqual([
      "/api/v1/party-admin/transferir-propiedad",
      "/api/v1/sales-admin/transferir-propiedad",
    ]);
    expect(traspasos[0]!.opciones?.cuerpo).toMatchObject({
      de_usuario: "u-1",
      a_usuario: "u-2",
      simular: true,
    });

    const confirmar = screen.getByRole("button", {
      name: "Traspasar 5 registros",
    });
    expect(confirmar).toBeDisabled();
    await userEvent.type(
      screen.getByLabelText("Motivo del traspaso"),
      "Baja de Marta",
    );
    expect(confirmar).toBeEnabled();
  });
});
