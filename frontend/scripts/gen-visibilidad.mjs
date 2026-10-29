/**
 * Genera el resumen de visibilidad de los módulos, derivado de `recursos.ts`.
 *
 *     node scripts/gen-visibilidad.mjs            # escribe
 *     node scripts/gen-visibilidad.mjs --comprobar # falla si está desfasado
 *
 * **Por qué existe.** La barra lateral no enseña un módulo del que no se pueda
 * ver ninguna pestaña: ofrecer lo que no se puede hacer obliga a probarlo para
 * descubrirlo, y lo que se descubre es un error. Para decidirlo necesita, de
 * cada pestaña, su ruta, el permiso que exige y si es sólo de plataforma.
 *
 * Y la barra se pinta en cuanto entra alguien, así que esos tres datos tienen
 * que estar en el módulo de entrada. La tabla entera NO: son 42 kB comprimidos
 * del paquete de apertura para algo que sólo necesitan cinco pantallas, y
 * ninguna se abre al entrar.
 *
 * Se genera en vez de escribirse a mano porque dos listas a mano acaban
 * diciendo cosas distintas, y entonces no se sabe cuál manda: un permiso que
 * se añade a una pestaña y no al resumen deja el módulo visible para quien no
 * puede abrirlo, y al revés lo esconde para quien sí.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const LIB = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "lib");
const ORIGEN = join(LIB, "recursos.ts");
const DESTINO = join(LIB, "visibilidad.ts");

/** Lee los tres datos de cada pestaña sin ejecutar TypeScript. */
function visibilidadDe(fuente) {
  const salida = {};
  // Cada módulo: `"ruta": [ … ],` en el primer nivel del objeto.
  const re = /^ {2}"([a-z-]+)": \[/gm;
  let m;
  const marcas = [];
  while ((m = re.exec(fuente)) !== null) marcas.push({ ruta: m[1], desde: m.index });
  marcas.forEach(({ ruta, desde }, i) => {
    const hasta = i + 1 < marcas.length ? marcas[i + 1].desde : fuente.length;
    const trozo = fuente.slice(desde, hasta);
    const pestañas = [];
    // Un recurso empieza siempre por su `nombre`.
    for (const bloque of trozo.split(/\n\s+\{\n/).slice(1)) {
      const listar = /listar:\s*"([^"]+)"/.exec(bloque)?.[1];
      if (!listar) continue;
      const permiso = /permiso:\s*"([^"]+)"/.exec(bloque)?.[1];
      const plataforma = /solo_plataforma:\s*true/.test(bloque);
      // `:servicio` se sustituye por el PRIMER servicio declarado. Este
      // resumen sólo decide si el módulo se enseña en el menú, y para eso
      // basta con una ruta de verdad: con la plantilla sin sustituir no casaba
      // con ninguna de las que publica el servidor, así que la pestaña quedaba
      // escondida para todo el mundo.
      const primero = /por_servicio:\s*\[\s*"([^"]+)"/.exec(bloque)?.[1];
      const fila = { r: primero ? listar.replace(":servicio", primero) : listar };
      if (permiso) fila.p = permiso;
      // El tipo de registro, cuando la pestaña lo declara. Lo necesita la
      // paleta para llevar un resultado de búsqueda a SU ficha: sin él, lo
      // único que podría hacer con «Acme» es abrir la lista de cuentas y
      // dejar que el usuario lo busque otra vez dentro.
      const objeto = /objeto:\s*"([^"]+)"/.exec(bloque)?.[1];
      if (objeto) fila.o = objeto;
      if (plataforma) fila.sp = true;
      // De qué servicio sale. Hace falta para NO esconder una pestaña cuyo
      // servicio no ha contestado: la superficie se agrega de diez servicios y
      // el que no contesta aporta cero operaciones, así que sin esto sus
      // pestañas desaparecen del menú exactamente igual que las prohibidas.
      const servicio = /servicio:\s*"([^"]+)"/.exec(bloque)?.[1];
      if (servicio) fila.s = servicio;
      pestañas.push(fila);
    }
    salida[ruta] = pestañas;
  });
  return salida;
}

const datos = visibilidadDe(readFileSync(ORIGEN, "utf8"));
const total = Object.values(datos).reduce((n, v) => n + v.length, 0);
if (total < 100) {
  console.error(`Sólo se han leído ${total} pestañas: el generador no está viendo el fichero.`);
  process.exit(2);
}

const contenido = `/**
 * Lo mínimo para decidir qué módulos enseña el menú. **Generado.**
 *
 *     node scripts/gen-visibilidad.mjs
 *
 * De cada pestaña, lo justo: de dónde lista (\`r\`), qué permiso exige (\`p\`),
 * de qué servicio sale (\`s\`) y si es sólo de quien opera la plataforma
 * (\`sp\`). Nada más — el resto de la tabla son 42 kB comprimidos que no hacen
 * falta para pintar un menú.
 *
 * NO se edita a mano: sale de \`recursos.ts\`, que es la fuente. Dos listas a
 * mano acaban diciendo cosas distintas y entonces no se sabe cuál manda.
 */

export interface PestanaVisible {
  /** De dónde lista. Se compara con lo que el servidor dice que permite. */
  r: string;
  /** El tipo de registro de la pestaña, si lo declara. */
  o?: string;
  /** El permiso que declara el recurso, si declara alguno. */
  p?: string;
  /**
   * De qué servicio sale.
   *
   * Decide si esta pestaña se puede esconder: la superficie se agrega de diez
   * servicios y el que no contesta aporta cero operaciones. Sin saber de quién
   * es cada pestaña, un servicio lento al arrancar borra del menú todo lo suyo
   * y no hay forma de distinguirlo de «no te toca».
   */
  s?: string;
  /** Sólo para quien opera la plataforma. */
  sp?: boolean;
}

export const VISIBILIDAD: Record<string, PestanaVisible[]> = ${JSON.stringify(datos, null, 2)};
`;

if (process.argv.includes("--comprobar")) {
  const actual = readFileSync(DESTINO, "utf8");
  if (actual !== contenido) {
    console.error(
      "«src/lib/visibilidad.ts» está desfasado respecto de «recursos.ts».\n" +
        "Regenéralo:  node scripts/gen-visibilidad.mjs",
    );
    process.exit(1);
  }
  console.log(`visibilidad al día (${total} pestañas)`);
} else {
  writeFileSync(DESTINO, contenido);
  console.log(`escrito src/lib/visibilidad.ts (${total} pestañas)`);
}
