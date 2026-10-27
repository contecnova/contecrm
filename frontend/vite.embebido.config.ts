/**
 * La construcción del componente embebible, aparte (CRM-00.02.03.05).
 *
 * **Un fichero y nada más.** Se carga desde la web de un cliente, así que no
 * puede arrastrar React, ni el cliente HTTP, ni los estilos de la aplicación:
 * son cientos de kilobytes viajando a una página ajena para pintar cuatro
 * líneas. Por eso tiene su propia configuración en vez de ser otra entrada de
 * la principal — con una entrada compartida, Vite reparte trozos comunes y el
 * componente acabaría pidiendo ficheros del CRM.
 *
 * Y su propia carpeta de salida, por lo mismo que las pruebas de pantalla: dos
 * construcciones escribiendo la misma dejan una a medias.
 */

import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "dist-embebido",
    emptyOutDir: true,
    lib: {
      entry: "src/embebido/index.ts",
      name: "contecrm",
      // Un solo formato: un módulo ES, que es lo que entiende cualquier
      // navegador desde hace años con `<script type="module">`. Publicar
      // también UMD sería mantener dos cosas para el navegador que ya no hay.
      formats: ["es"],
      fileName: () => "embebido.js",
    },
    // Sin trocear: un `<script>` que pide otros ficheros obliga a quien lo
    // incrusta a servirlos todos, y el primero que falta deja el componente
    // sin pintar en una web que no es nuestra.
    // Sin trocear, con la opción vigente de Vite 8: `inlineDynamicImports`
    // está deprecada y avisa en cada construcción.
    rollupOptions: { output: { codeSplitting: false } },
    target: "es2020",
    // Con el minificador que trae Vite 8. `esbuild` ya no viene incluido y
    // pedirlo aquí obligaría a instalar un paquete más sólo para esto.
    minify: true,
  },
});
