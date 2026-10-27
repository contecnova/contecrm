/**
 * Abrir el alta en una pantalla no deja en modo alta a las demás.
 *
 * Lo contó quien lo usaba: pulsar «crear» en un módulo, irse a otro sin
 * cerrar, y seguir en modo alta ahí y en todos los siguientes hasta darle a
 * cancelar en alguno. Un formulario que aparece solo encima de otra pantalla
 * no se lee como un estado heredado: se lee como un error.
 *
 * La causa es de React y no del producto: la pantalla de módulo atiende a
 * `/m/:ruta`, así que cambiar de módulo **no desmonta el componente** y su
 * estado sobrevive. Con él sobrevivían también el término de búsqueda y el
 * rango de fechas de la pantalla anterior.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
const MODULO = readFileSync(join(SRC, "paginas", "Modulo.tsx"), "utf8");
const FICHA = readFileSync(join(SRC, "paginas", "Ficha.tsx"), "utf8");
const ARRANQUE = readFileSync(join(SRC, "main.tsx"), "utf8");
const APP = readFileSync(join(SRC, "App.tsx"), "utf8");

describe("el modo alta y el modo edición no viajan entre pantallas", () => {
  it("la vista del recurso se remonta al cambiar de módulo o de pestaña", () => {
    // Se comprueba sobre el código y no montando dos rutas: lo que falla es
    // la ausencia de `key`, y una prueba de render que no reprodujera
    // exactamente la reutilización de instancia de React pasaría en verde con
    // el defecto puesto.
    const uso = /<RecursoVista\b[\s\S]{0,400}?\/>/.exec(MODULO)?.[0] ?? "";
    expect(uso, "no se ha encontrado el uso de RecursoVista").not.toBe("");
    expect(uso).toMatch(/key=\{/);
    // Y la clave tiene que depender del módulo Y de la pestaña: sólo con el
    // módulo, cambiar de pestaña seguiría arrastrando el formulario abierto.
    expect(uso).toMatch(/key=\{`\$\{ruta\}:\$\{recurso\.nombre\}`\}/);
  });

  it("la ficha sale de edición al cambiar de registro", () => {
    // Ir de una ficha a otra tampoco desmonta: sin esto, la siguiente se abre
    // ya en modo edición con los datos de la anterior en el formulario, y un
    // «¿seguro que quieres borrar?» a medias apunta al registro nuevo.
    expect(FICHA).toMatch(/setEditando\(false\);\s*\n\s*setConfirmando\(false\);/);
    expect(FICHA).toMatch(/\}, \[modulo, objeto, id\]\);/);
  });
});

describe("no se piden al servidor cosas que todavía no se pueden pedir", () => {
  it("la localización NO se pide en el arranque, sino al haber sesión", () => {
    /**
     * Se pedía en los dos sitios. En el arranque no puede funcionar —todavía
     * no hay sesión—, así que el servidor responde 401 y el navegador lo
     * escribe en rojo en la consola CADA VEZ que alguien abre la pantalla de
     * entrada. El valor no se usaba, porque `App` lo vuelve a pedir y ese sí
     * llega: lo único que aportaba era el error.
     *
     * Un error que sale siempre y no significa nada es donde se esconde el
     * que sí importa.
     */
    expect(ARRANQUE).not.toMatch(/aplicarLocalizacion\(\)/);
    expect(APP).toMatch(/aplicarLocalizacion\(\)/);
    // Y la marca, por lo mismo y en el mismo sitio.
    expect(APP).toMatch(/aplicarMarcaDelTenant\(\)/);
  });
});
