/**
 * Ninguna lista empuja a las demás fuera de la vista.
 *
 * La regla, y es de producto, no de maqueta: **si una pantalla enseña más de
 * una lista que crece con los datos, ninguna puede quedarse con la pantalla
 * entera.** Con doscientos segmentos, la sección de campañas quedaba a tres
 * pantallas de distancia; con un informe de quinientas filas, los otros cinco
 * componentes del cuadro de mando quedaban igual de lejos; con cien trabajos
 * en cola, los paneles de debajo no los veía nadie.
 *
 * No es una cuestión de gusto: lo que no se ve no se usa, y el que lo abre no
 * sabe que está ahí. Se arregla con `.lista-acotada` —definida una sola vez en
 * `index.css`, para que todas se corten igual— o con el reparto de alto de la
 * ficha de cliente y del tablero, que es lo mismo llevado a columnas.
 *
 * **Lo que esto NO pide:** acotar la lista de una pantalla que ES la lista —un
 * listado de módulo, la cola de duplicados, la búsqueda en conocimiento—. Ahí
 * no hay nada a lo que dejar sitio y una barra dentro de la página es peor que
 * el problema. Por eso la regla sólo mira las pantallas con DOS o más.
 *
 * Y está escrita como excepciones con su motivo, no como lista de las que sí:
 * una lista de las que cumplen se queda corta en cuanto alguien añade una
 * pantalla, y se queda corta en silencio.
 */

import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const PANTALLAS = path.join(process.cwd(), "src/paginas");

/**
 * Lo que se pinta recorriendo datos y **no es una lista**, con su motivo.
 *
 * Por `pantalla:variable` y no por pantalla entera: eximir la pantalla dejaría
 * sin vigilar sus listas de verdad, que es como un guardián acaba sin mirar
 * nada. Y con el motivo escrito, porque una excepción sin motivo se copia.
 */
const NO_ES_UNA_LISTA: Record<string, string> = {
  "Procesos.tsx:nodos":
    "Es el diagrama del proceso: los nodos se dibujan como cajas y flechas " +
    "sobre un lienzo, con una capa de `div` encima para poder arrastrarlos. " +
    "El tamaño lo decide el lienzo, no cuántos haya, y acotarlo cortaría el " +
    "dibujo por la mitad.",
};

/**
 * Los tramos de `<svg>…</svg>` de la fuente.
 *
 * Lo que se dibuja dentro de un lienzo NO es una lista: el diagrama de un
 * proceso recorre sus nodos con `.map(` y los pinta como cajas y flechas, con
 * el tamaño que decide el lienzo. Contarlo como lista hacía que esta prueba
 * pidiera acotar un dibujo, que es pedir una tontería — y un guardián que
 * pide tonterías se acaba desactivando entero.
 */
function tramosDeLienzo(fuente: string): Array<[number, number]> {
  const tramos: Array<[number, number]> = [];
  let desde = fuente.indexOf("<svg");
  while (desde !== -1) {
    const hasta = fuente.indexOf("</svg>", desde);
    tramos.push([desde, hasta === -1 ? fuente.length : hasta]);
    desde = fuente.indexOf("<svg", hasta === -1 ? fuente.length : hasta);
  }
  return tramos;
}

/** Variables de estado que se pintan como LISTA en esta pantalla. */
function listasDelServidor(fuente: string): string[] {
  const estados = new Set<string>();
  for (const m of fuente.matchAll(
    /const \[(\w+), set\w+\] = useState<[^;]*?\[\]/g,
  )) {
    estados.add(m[1]!);
  }
  const lienzos = tramosDeLienzo(fuente);
  const dentroDeUnLienzo = (i: number) =>
    lienzos.some(([a, b]) => i > a && i < b);

  const pintadas: string[] = [];
  for (const v of estados) {
    // `.slice(0, N).map(` cuenta como pintada: recortar en el cliente es otra
    // forma de acotar, y la prueba la da por buena más abajo.
    const re = new RegExp(`\\b${v}(\\.slice\\([^)]*\\))?\\.map\\(`, "g");
    for (const m of fuente.matchAll(re)) {
      const i = m.index ?? 0;
      if (dentroDeUnLienzo(i)) continue;
      // Y que PINTE, no que calcule. `nodos.map((n) => [n.nombre, n])` arma un
      // índice y `nodos.map((n) => n.x + ANCHO)` mide un lienzo: ninguno de los
      // dos es una lista en pantalla, y contarlos hacía que esta prueba pidiera
      // acotar un cálculo. Lo que distingue a una lista es que el cuerpo de la
      // flecha abre JSX: `=> (` o `=> <`.
      const cuerpo = fuente.slice(i, i + 400);
      if (!/^=>\s*[(<]/.test(cuerpo.replace(/^[^=]*/, ""))) continue;
      pintadas.push(v);
      break;
    }
  }
  return pintadas;
}

/** Cuántas formas de acotar aparecen en la fuente. */
function cuantasAcotadas(fuente: string): number {
  return (
    (fuente.match(/lista-acotada/g) ?? []).length +
    (fuente.match(/overflow-y-auto/g) ?? []).length +
    (fuente.match(/\.slice\(0,/g) ?? []).length
  );
}

function pantallas(): string[] {
  return fs
    .readdirSync(PANTALLAS)
    .filter((f) => f.endsWith(".tsx") && !f.includes(".test."));
}

describe("ninguna lista echa a las demás de la pantalla", () => {
  it("el recorrido mira de verdad", () => {
    // Sin esto, un detector que no encontrara ninguna lista diría que está
    // todo bien y no avisaría de nada nunca.
    const todas = pantallas();
    expect(todas.length).toBeGreaterThan(20);
    const conVarias = todas.filter(
      (f) =>
        listasDelServidor(fs.readFileSync(path.join(PANTALLAS, f), "utf8"))
          .length >= 2,
    );
    expect(
      conVarias.length,
      "el detector no ve ninguna pantalla con varias listas",
    ).toBeGreaterThan(3);
    // Y que sabe distinguir: la ficha de cliente acota, y lo tiene que ver.
    const cuenta = fs.readFileSync(path.join(PANTALLAS, "Cuenta.tsx"), "utf8");
    expect(cuantasAcotadas(cuenta)).toBeGreaterThan(0);
  });

  it("toda pantalla con varias listas acota las suyas", () => {
    const fallos: string[] = [];
    let revisadas = 0;
    for (const f of pantallas()) {
      const fuente = fs.readFileSync(path.join(PANTALLAS, f), "utf8");
      const listas = listasDelServidor(fuente);
      if (listas.length < 2) continue;
      revisadas += 1;
      const deVerdad = listas.filter((v) => !(`${f}:${v}` in NO_ES_UNA_LISTA));
      if (deVerdad.length < 2) continue;
      const acotadas = cuantasAcotadas(fuente);
      if (acotadas < deVerdad.length) {
        fallos.push(
          `${f}: ${deVerdad.length} listas (${deVerdad.join(", ")}) y ${acotadas} acotadas`,
        );
      }
    }
    expect(revisadas, "no se ha revisado ninguna pantalla").toBeGreaterThan(3);
    expect(
      fallos,
      "Pantallas donde una lista puede empujar a las demás fuera de la vista. " +
        "Acótalas con `.lista-acotada`, o apúntalas en `SIN_ACOTAR_A_PROPOSITO` " +
        "con el motivo escrito:\n  " +
        fallos.join("\n  "),
    ).toEqual([]);
  });

  it("una excepción sin motivo, o que ya no aplica, no vale", () => {
    for (const [clave, porque] of Object.entries(NO_ES_UNA_LISTA)) {
      const [pantalla, variable] = clave.split(":");
      expect(
        porque.length,
        `«${clave}» está exenta sin decir por qué`,
      ).toBeGreaterThan(40);
      const ruta = path.join(PANTALLAS, pantalla!);
      expect(
        fs.existsSync(ruta),
        `«${pantalla}» ya no existe: quita la excepción`,
      ).toBe(true);
      // Y que la variable siga ahí: una excepción que sobrevive a lo que
      // eximía se queda tapando lo que venga después con ese nombre.
      expect(
        fs.readFileSync(ruta, "utf8").includes(`${variable},`),
        `«${variable}» ya no está en ${pantalla}: quita la excepción`,
      ).toBe(true);
    }
  });
});
