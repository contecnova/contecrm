/**
 * Antes de nada: ¿está el navegador?
 *
 * Sin esto, un navegador que falta sale como **23 pantallas rotas**. Pasó el
 * 27-10-2026 en el pase completo: veintitrés rojos idénticos, ninguno del
 * código, y entre ellos pantallas que nadie había tocado. Veintitrés fallos
 * que no significan nada son la forma más rápida de que alguien deje de mirar
 * este gate, y el día que una pantalla se rompa de verdad estará ahí, en la
 * lista, con las otras veintidós.
 *
 * Playwright ya lo dice —una vez por prueba—. Lo que falta es **pararlo
 * antes**, con un mensaje y nada más.
 */

import { existsSync } from "node:fs";

import { chromium } from "@playwright/test";

export default function comprobarNavegador(): void {
  const ejecutable = chromium.executablePath();
  if (existsSync(ejecutable)) return;
  throw new Error(
    "Falta el navegador con el que se miran las pantallas; no se ha comprobado " +
      "ninguna.\n\nEsto NO es una pantalla rota: es que no hay con qué abrirla.\n\n" +
      `  cd frontend && pnpm exec playwright install chromium\n\nSe esperaba en: ${ejecutable}`,
  );
}
