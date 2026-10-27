/**
 * El componente que se incrusta en una web ajena (CRM-00.02.03.05).
 *
 *     <script type="module" src="https://…/embebido.js"></script>
 *     <contecrm-componente
 *       componente="ficha-cuenta"
 *       api="https://…/api/v1"
 *       token="…"></contecrm-componente>
 *
 * **Lo que decide si esto sirve no es cómo pinta: es con qué identidad habla.**
 * El token va acotado al registro —el identificador viaja DENTRO— así que el
 * elemento no recibe ningún identificador y no hay nada que cambiar desde las
 * herramientas del navegador. Un token de la cuenta A no puede pedir la cuenta
 * B porque no existe forma de pedirla.
 *
 * Cuatro decisiones más, todas de incrustar en casa ajena:
 *
 * **Shadow DOM.** Los estilos del anfitrión no entran y los nuestros no salen.
 * Sin él, una hoja de estilos cualquiera de la página puede dejar el
 * componente ilegible —o al revés, nosotros romperle su maquetación—, y lo
 * descubre el cliente en su web, no nosotros.
 *
 * **Hereda del anfitrión por variables CSS**, sin imponer tipografía ni
 * colores: un recuadro con nuestra tipografía dentro de la web de otro se ve
 * como lo que es, un trozo pegado.
 *
 * **No usa nada de la aplicación.** Ni React, ni el cliente HTTP, ni los
 * estilos: todo eso pesa cientos de kilobytes y viajaría a la web del cliente
 * para pintar cuatro líneas. Es DOM a mano a propósito.
 *
 * **No escribe en `window` ni en `localStorage`.** Está en una página que no es
 * nuestra: lo que toque fuera de su propio árbol es una colisión esperando.
 */

type Datos = Record<string, unknown>;

/** Qué pide cada componente y cómo se rotula. Lista cerrada, como el contrato. */
const COMPONENTES: Record<string, { ruta: string; titulo: string; metodo?: string }> = {
  "ficha-cuenta": { ruta: "/embebido/ficha-cuenta", titulo: "Cliente" },
  "lista-casos": { ruta: "/embebido/lista-casos", titulo: "Incidencias" },
  "estado-pedido": { ruta: "/embebido/estado-pedido", titulo: "Estado del pedido" },
  "formulario-alta": { ruta: "/embebido/formulario-alta", titulo: "Contacto", metodo: "POST" },
};

const ESTILO = `
  :host { display: block; font-family: inherit; color: inherit; }
  .caja {
    border: 1px solid var(--contecrm-borde, rgba(127,127,127,.35));
    border-radius: var(--contecrm-radio, 12px);
    padding: var(--contecrm-espacio, 12px);
    background: var(--contecrm-fondo, transparent);
  }
  .titulo { font-size: .8rem; font-weight: 600; margin: 0 0 .5rem; }
  .fila { display: flex; gap: .5rem; justify-content: space-between; padding: .15rem 0; }
  .etiqueta { opacity: .7; }
  .error { color: var(--contecrm-error, #b00020); font-size: .8rem; }
  ul { list-style: none; margin: 0; padding: 0; }
  li { padding: .25rem 0; border-top: 1px solid var(--contecrm-borde, rgba(127,127,127,.2)); }
`;

function texto(valor: unknown): string {
  if (valor === null || valor === undefined || valor === "") return "—";
  return String(valor);
}

class ComponenteContecrm extends HTMLElement {
  static get observedAttributes(): string[] {
    return ["componente", "api", "token"];
  }

  private raiz: ShadowRoot;

  constructor() {
    super();
    this.raiz = this.attachShadow({ mode: "open" });
  }

  connectedCallback(): void {
    void this.pintar();
  }

  attributeChangedCallback(): void {
    if (this.isConnected) void this.pintar();
  }

  private async pintar(): Promise<void> {
    const nombre = this.getAttribute("componente") ?? "";
    const api = (this.getAttribute("api") ?? "").replace(/\/$/, "");
    const token = this.getAttribute("token") ?? "";
    const decl = COMPONENTES[nombre];

    if (!decl) {
      this.error(`Componente desconocido: «${nombre}». Los que hay: ${Object.keys(COMPONENTES).join(", ")}.`);
      return;
    }
    if (!api || !token) {
      // Se dice qué falta y no se intenta igual: una llamada sin token
      // devuelve 401 y el mensaje que vería quien integra esto sería «no
      // autenticado», que manda a mirar al sitio equivocado.
      this.error("Faltan los atributos «api» y «token».");
      return;
    }

    try {
      const respuesta = await fetch(`${api}${decl.ruta}`, {
        method: decl.metodo ?? "GET",
        headers: {
          Authorization: `Bearer ${token}`,
          ...(decl.metodo === "POST" ? { "Content-Type": "application/json" } : {}),
        },
        ...(decl.metodo === "POST" ? { body: "{}" } : {}),
        // Sin cookies a propósito: este componente vive en otra web y la
        // sesión del CRM no tiene nada que hacer aquí. Es la misma decisión
        // que el token acotado, por el otro lado.
        credentials: "omit",
      });
      if (!respuesta.ok) {
        this.error(
          respuesta.status === 401
            ? "El token ha caducado o no vale."
            : `No se ha podido cargar (${respuesta.status}).`,
        );
        return;
      }
      this.dibujar(decl.titulo, (await respuesta.json()) as Datos);
    } catch {
      // El motivo exacto de un fallo de red no se enseña en la web de un
      // cliente: no le dice nada a quien la mira y puede filtrar el destino.
      this.error("No se ha podido contactar con el servicio.");
    }
  }

  private error(mensaje: string): void {
    this.raiz.innerHTML = `<style>${ESTILO}</style><div class="caja"><p class="error">${mensaje}</p></div>`;
  }

  private dibujar(titulo: string, datos: Datos): void {
    const casos = Array.isArray(datos.casos) ? (datos.casos as Datos[]) : null;
    const cuerpo = casos
      ? `<ul>${casos
          .map(
            (c) =>
              `<li><div class="fila"><span>${texto(c.asunto)}</span><span class="etiqueta">${texto(c.estado)}</span></div></li>`,
          )
          .join("")}</ul>`
      : Object.entries(datos)
          .filter(([clave]) => clave !== "porque" && clave !== "campos")
          .map(
            ([clave, valor]) =>
              `<div class="fila"><span class="etiqueta">${clave.replace(/_/g, " ")}</span><span>${texto(valor)}</span></div>`,
          )
          .join("");
    this.raiz.innerHTML = `<style>${ESTILO}</style><div class="caja"><p class="titulo">${titulo}</p>${cuerpo || '<p class="error">Sin datos.</p>'}</div>`;
  }
}

// Registrar dos veces lanza, y esto puede cargarse dos veces en una página que
// incrusta dos componentes: se comprueba antes.
if (!customElements.get("contecrm-componente")) {
  customElements.define("contecrm-componente", ComponenteContecrm);
}

export { ComponenteContecrm, COMPONENTES };
