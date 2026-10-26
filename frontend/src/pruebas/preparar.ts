import "@testing-library/jest-dom/vitest";

/**
 * `EventSource`, que jsdom no trae.
 *
 * El chat abre un flujo SSE al montar (CRM-06.02.02.07), y sin esto cada
 * render de esa pantalla lanzaba un `ReferenceError: EventSource is not
 * defined` que React recoge como error no capturado. No tumbaba las pruebas
 * —caía dentro de la frontera— pero llenaba la salida de trazas, y una salida
 * llena de trazas que se dan por normales es donde se esconde la traza que sí
 * importa. Medido el 26-10-2026: dieciséis excepciones por pasada completa.
 *
 * Es un doble mínimo a propósito: ni entrega eventos ni reconecta. Lo que se
 * prueba del flujo en vivo es el contrato del servidor —que se anuncia como
 * `text/event-stream`—, no el cliente del navegador; un doble que fingiera
 * entregar mensajes mediría esta clase y no el producto.
 */
class FlujoDeMentira {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  readonly url: string;
  readonly withCredentials = false;
  readyState = FlujoDeMentira.CONNECTING;
  onopen: ((this: EventSource, ev: Event) => unknown) | null = null;
  onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null = null;
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null;

  constructor(url: string | URL) {
    this.url = String(url);
  }

  addEventListener(): void {}
  removeEventListener(): void {}
  dispatchEvent(): boolean {
    return false;
  }
  close(): void {
    this.readyState = FlujoDeMentira.CLOSED;
  }
}

if (typeof globalThis.EventSource === "undefined") {
  globalThis.EventSource = FlujoDeMentira as unknown as typeof EventSource;
}

/**
 * `scrollIntoView`, que jsdom tampoco trae.
 *
 * Cualquier pantalla que lleve el foco a un sitio —el chat, al último mensaje—
 * revienta al montar con un `TypeError` que React trata como error no
 * capturado y que **desmonta el árbol**: la pantalla se queda en blanco y la
 * prueba no dice por qué. No es un fallo del producto: en un navegador existe.
 */
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}
