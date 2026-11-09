/**
 * Leer un CSV en el navegador, para importar (CRM-07.01.01.08).
 *
 * Se lee aquí y no en el servidor porque lo que viene después —elegir a qué
 * campo va cada columna— necesita ver las cabeceras y una fila de ejemplo antes
 * de mandar nada. Al servidor llegan ya las filas como objetos, con los campos
 * de destino puestos.
 *
 * Lo que tiene que aguantar, porque es lo que sale de una hoja de cálculo real:
 *
 * - **El separador lo decide el fichero.** Excel en español guarda con `;`, el
 *   resto del mundo con `,`, y hay quien exporta con tabuladores. Se mira la
 *   primera línea y gana el que más aparece.
 * - **Comillas**: un campo entre comillas puede llevar el separador, saltos de
 *   línea y comillas dobladas (`""`) dentro.
 * - **La marca BOM** que pone Excel al principio, que sin quitarla convierte la
 *   primera cabecera en «\uFEFFnombre» y no casa con nada.
 * - **Líneas vacías** al final, que no son filas.
 */

export interface Csv {
  separador: string;
  cabeceras: string[];
  filas: string[][];
}

const CANDIDATOS = [";", ",", "\t"];

export function separadorDe(primeraLinea: string): string {
  let mejor = ",";
  let veces = 0;
  for (const s of CANDIDATOS) {
    const n = primeraLinea.split(s).length - 1;
    if (n > veces) {
      mejor = s;
      veces = n;
    }
  }
  return mejor;
}

export function leerCsv(texto: string): Csv {
  const limpio = texto.replace(/^\uFEFF/, "");
  const primera = limpio.split(/\r?\n/, 1)[0] ?? "";
  const separador = separadorDe(primera);

  const registros: string[][] = [];
  let actual: string[] = [];
  let campo = "";
  let entreComillas = false;
  for (let i = 0; i < limpio.length; i += 1) {
    const c = limpio[i]!;
    if (entreComillas) {
      if (c === '"') {
        if (limpio[i + 1] === '"') {
          campo += '"';
          i += 1;
        } else {
          entreComillas = false;
        }
      } else {
        campo += c;
      }
      continue;
    }
    if (c === '"') {
      entreComillas = true;
    } else if (c === separador) {
      actual.push(campo);
      campo = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && limpio[i + 1] === "\n") i += 1;
      actual.push(campo);
      registros.push(actual);
      actual = [];
      campo = "";
    } else {
      campo += c;
    }
  }
  if (campo !== "" || actual.length > 0) {
    actual.push(campo);
    registros.push(actual);
  }
  const utiles = registros.filter((r) => r.some((v) => v.trim() !== ""));
  const [cabeceras = [], ...filas] = utiles;
  return { separador, cabeceras: cabeceras.map((c) => c.trim()), filas };
}

/** Para comparar una cabecera con un nombre de campo: sin acentos, ni mayúsculas, ni separadores. */
export function claveDeCabecera(texto: string): string {
  return texto
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}
