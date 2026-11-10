/**
 * Cómo se llaman estos registros.
 *
 * **El problema que resuelve.** Hay listas del producto que guardan a qué
 * registro apuntan —«Lo que sigo», la biblioteca de archivos— y no su nombre:
 * guardan `objeto_tipo` y `objeto_id`. Pintadas tal cual son una lista de
 * identificadores, que no sirve para nada: lo que convierte
 * «contrato-2026.pdf» en algo útil es «de Metalúrgica del Norte».
 *
 * **Una llamada por TIPO, no una por registro.** Los listados admiten
 * `id__en=a,b,c`, así que cinco cuentas y tres casos son dos llamadas. Una por
 * registro serían ocho, y crecerían con lo que tenga cada lista.
 *
 * **Lo que no se puede resolver no se inventa.** Un tipo sin módulo declarado,
 * un listado que falla o un registro que ya no existe se quedan sin nombre, y
 * eso lo dice cada pantalla a su manera —«ya no está», o el tipo a secas—:
 * aquí simplemente no aparecen en el mapa. Poner el identificador en su lugar
 * sería enseñar el dato en crudo con cara de nombre.
 */

import { llamar } from "@/lib/api";
import { nombreDelRegistro } from "@/lib/formato";
import { moduloDe, moduloDeObjeto } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";

interface Pagina {
  items: Record<string, unknown>[];
}

/**
 * Los nombres de unos registros del mismo tipo, de una vez.
 *
 * Devuelve también **si se ha podido preguntar**. Sin eso, un registro sin
 * nombre tiene dos causas que no se distinguen: que ya no exista, o que no se
 * haya podido mirar —el tipo no tiene pantalla, o su listado no contestó—. Y
 * son cosas distintas que una pantalla no puede contar como la misma: decir
 * «este registro ya no existe» de algo que sigue ahí es una afirmación falsa
 * sobre los datos de alguien.
 */
async function deUnTipo(
  objetoTipo: string,
  ids: string[],
  signal?: AbortSignal,
): Promise<{ nombres: Map<string, string>; preguntado: boolean }> {
  const nombres = new Map<string, string>();
  const ruta = moduloDeObjeto(objetoTipo);
  if (!ruta) return { nombres, preguntado: false };
  const modulo = moduloDe(ruta);
  const recurso = modulo ? recursoDe(modulo, objetoTipo) : undefined;
  if (!recurso) return { nombres, preguntado: false };
  try {
    const { datos } = await llamar<Pagina>(
      `${recurso.listar}?id__en=${ids.join(",")}&limite=200`,
      { signal },
    );
    for (const fila of datos.items ?? []) {
      const id = String(fila.id ?? "");
      if (id) nombres.set(id, nombreDelRegistro(fila));
    }
    return { nombres, preguntado: true };
  } catch {
    // Un tipo que no contesta no puede dejar la pantalla entera sin pintar:
    // lo suyo sale sin nombre y lo demás sigue leyéndose.
    return { nombres, preguntado: false };
  }
}

export interface NombresResueltos {
  /**
   * Cómo se llama cada registro, por su identificador.
   *
   * La clave es el identificador y no «tipo:id»: es único dentro del tenant,
   * así que componer la clave obligaría a cada pantalla a saber cómo.
   */
  nombres: Map<string, string>;
  /**
   * Los tipos que SÍ se han podido mirar.
   *
   * Un registro de un tipo preguntado que no trae nombre **ya no existe**, y
   * eso se puede decir. Uno de un tipo que no se ha podido preguntar sólo
   * permite decir que no se sabe. Sin esta lista las dos cosas se pintan
   * igual, y una de las dos sería mentira.
   */
  preguntados: Set<string>;
}

/** Los nombres de una lista de registros de varios tipos. */
export async function nombresDeRegistros(
  registros: { objeto_tipo: string; objeto_id: string }[],
  signal?: AbortSignal,
): Promise<NombresResueltos> {
  const porTipo = new Map<string, string[]>();
  for (const r of registros) {
    if (!r.objeto_tipo || !r.objeto_id) continue;
    porTipo.set(r.objeto_tipo, [
      ...(porTipo.get(r.objeto_tipo) ?? []),
      r.objeto_id,
    ]);
  }
  // Los tipos EN PARALELO: en serie, cuatro tipos con su viaje de red son
  // cuatro esperas seguidas para pintar una lista que ya se tiene entera.
  const lotes = await Promise.all(
    [...porTipo].map(async ([tipo, ids]) => ({
      tipo,
      ...(await deUnTipo(tipo, [...new Set(ids)], signal)),
    })),
  );
  const nombres = new Map<string, string>();
  const preguntados = new Set<string>();
  for (const lote of lotes) {
    if (lote.preguntado) preguntados.add(lote.tipo);
    for (const [id, nombre] of lote.nombres) nombres.set(id, nombre);
  }
  return { nombres, preguntados };
}

/**
 * El nombre de UN registro, juntando en una sola llamada por tipo todos los que
 * se piden en el mismo instante.
 *
 * Lo usa la celda de una tabla: cincuenta filas con `cuenta_id` son cincuenta
 * celdas que preguntan a la vez, y una llamada por celda serían cincuenta. Se
 * juntan en el mismo turno y se resuelven con `nombresDeRegistros`, y lo ya
 * resuelto se recuerda durante la sesión de la pantalla.
 */
const resueltos = new Map<string, Promise<string | undefined>>();
let pendientes: { tipo: string; id: string; listo: (n?: string) => void }[] =
  [];
let programado = false;

export function nombreEnLote(
  tipo: string,
  id: string,
): Promise<string | undefined> {
  const clave = `${tipo}:${id}`;
  const hay = resueltos.get(clave);
  if (hay) return hay;
  const promesa = new Promise<string | undefined>((listo) => {
    pendientes.push({ tipo, id, listo });
    if (!programado) {
      programado = true;
      setTimeout(() => {
        const lote = pendientes;
        pendientes = [];
        programado = false;
        void nombresDeRegistros(
          lote.map((p) => ({ objeto_tipo: p.tipo, objeto_id: p.id })),
        ).then(
          ({ nombres }) => lote.forEach((p) => p.listo(nombres.get(p.id))),
          () => lote.forEach((p) => p.listo(undefined)),
        );
      }, 0);
    }
  });
  resueltos.set(clave, promesa);
  return promesa;
}
