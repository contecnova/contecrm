/**
 * La cola de lo hecho sin conexión (CRM-06.02.01.04).
 *
 * Se prueba con la cola en memoria: jsdom no trae IndexedDB, y lo que importa
 * aquí es qué se encola, qué se envía y qué se hace con cada respuesta.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorApi, llamar } from "@/lib/api";
import {
  cola,
  encolar,
  fijarUsuario,
  resolver,
  sincronizar,
  usarAlmacen,
  type OperacionEncolada,
} from "@/lib/sinConexion";

const ID = "0b9f1c62-6a43-4f7e-9d7a-1c1d2e3f4a5b";

let filas = new Map<string, OperacionEncolada>();

function enMemoria() {
  filas = new Map<string, OperacionEncolada>();
  usarAlmacen({
    todas: async () => [...filas.values()],
    poner: async (op) => void filas.set(op.id_cliente, op),
    quitar: async (id) => void filas.delete(id),
  });
}

describe("sin conexión", () => {
  beforeEach(() => {
    enMemoria();
    fijarUsuario("");
    vi.stubGlobal("navigator", { ...navigator, onLine: false });
    fijarUsuario("u1");
  });

  it("encola la edición de un registro con la versión sobre la que se hizo", async () => {
    const ok = await encolar({
      metodo: "PATCH",
      ruta: `/api/v1/contacts/${ID}`,
      cuerpo: { nombre: "Ana María" },
      version: 'W/"3"',
      idempotencia: "c1",
      mirado: "",
    });
    expect(ok).toBe(true);
    const [op] = await cola();
    expect(op).toMatchObject({
      tipo: "actualizar",
      recurso: "contacts",
      registro_id: ID,
      version_base: 3,
      campos: { nombre: "Ana María" },
    });
  });

  it("sin versión no se encola: no se podría detectar el conflicto", async () => {
    const ok = await encolar({
      metodo: "PATCH",
      ruta: `/api/v1/contacts/${ID}`,
      cuerpo: { nombre: "x" },
      idempotencia: "c2",
      mirado: "",
    });
    expect(ok).toBe(false);
    expect(await cola()).toHaveLength(0);
  });

  it("una acción que no es crear ni editar no se encola", async () => {
    const ok = await encolar({
      metodo: "POST",
      ruta: `/api/v1/contacts/${ID}/archivar`,
      cuerpo: {},
      idempotencia: "c3",
      mirado: "",
    });
    expect(ok).toBe(false);
  });

  it("la cola es de quien la hizo", async () => {
    await encolar({
      metodo: "POST",
      ruta: "/api/v1/contacts",
      cuerpo: { nombre: "Nueva" },
      idempotencia: "c4",
      mirado: "",
    });
    fijarUsuario("otra");
    expect(await cola()).toHaveLength(0);
  });

  it("llamar sin red encola y lo dice con su propio código", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    const error = await llamar(`/api/v1/contacts/${ID}`, {
      metodo: "PATCH",
      cuerpo: { cargo: "Gerente" },
      version: 'W/"2"',
    }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ErrorApi);
    expect((error as ErrorApi).codigo).toBe("encolada_sin_conexion");
    expect(await cola()).toHaveLength(1);
    vi.unstubAllGlobals();
  });

  it("al volver: lo aplicado sale, el conflicto se queda con los dos valores y se resuelve", async () => {
    await encolar({
      metodo: "PATCH",
      ruta: `/api/v1/contacts/${ID}`,
      cuerpo: { cargo: "Gerente", nombre: "Ana" },
      version: 'W/"1"',
      idempotencia: "c5",
      mirado: "",
    });
    const [op] = await cola();
    // Sin la tabla de recursos cargada, se fija el servicio a mano.
    await usarYPoner({ ...op!, servicio: "party" });

    const enviar = vi.fn(async () => ({
      ok: true,
      estado: 200,
      datos: {
        plan: [
          {
            id_cliente: "c5",
            accion: "conflicto",
            campos: ["cargo"],
            valores_servidor: { cargo: "Consejera" },
            version_servidor: 4,
          },
        ],
      },
    }));
    const res = await sincronizar(enviar);
    expect(res.conflictos).toBe(1);
    const cuerpo = (enviar.mock.calls[0] as unknown[])[1] as {
      cuerpo: { aplicar: boolean };
    };
    expect(cuerpo.cuerpo.aplicar).toBe(true);
    const [enConflicto] = await cola();
    expect(enConflicto!.estado).toBe("conflicto");
    expect(enConflicto!.conflicto!.valores_servidor).toEqual({
      cargo: "Consejera",
    });

    // Me quedo con lo mío: se reenvía sobre la versión de ahora.
    await resolver(enConflicto!, { cargo: true });
    const [resuelta] = await cola();
    expect(resuelta).toMatchObject({
      estado: "pendiente",
      version_base: 4,
      campos: { cargo: "Gerente", nombre: "Ana" },
      campos_base: { cargo: "Consejera" },
    });

    const aplicada = vi.fn(async () => ({
      ok: true,
      estado: 200,
      datos: { plan: [{ id_cliente: "c5", accion: "aplicada", version: 5 }] },
    }));
    await sincronizar(aplicada);
    expect(await cola()).toHaveLength(0);
  });

  it("quedarse con lo del servidor en todo no envía nada", async () => {
    const op: OperacionEncolada = {
      id_cliente: "c6",
      usuario: "u1",
      tipo: "actualizar",
      metodo: "PATCH",
      ruta: `/api/v1/contacts/${ID}`,
      recurso: "contacts",
      registro_id: ID,
      servicio: "party",
      version_base: 1,
      campos_base: {},
      campos: { cargo: "Gerente" },
      encolada_at: new Date().toISOString(),
      estado: "conflicto",
      conflicto: {
        campos: ["cargo"],
        valores_servidor: { cargo: "X" },
        version_servidor: 2,
      },
    };
    await usarYPoner(op);
    await resolver(op, { cargo: false });
    expect(await cola()).toHaveLength(0);
  });
});

async function usarYPoner(op: OperacionEncolada) {
  filas.set(op.id_cliente, op);
}
