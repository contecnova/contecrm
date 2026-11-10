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
const COMPONENTES: Record<
  string,
  { ruta: string; titulo: string; metodo?: string }
> = {
  "ficha-cuenta": { ruta: "/embebido/ficha-cuenta", titulo: "Cliente" },
  "lista-casos": { ruta: "/embebido/lista-casos", titulo: "Incidencias" },
  "estado-pedido": {
    ruta: "/embebido/estado-pedido",
    titulo: "Estado del pedido",
  },
  "formulario-alta": {
    ruta: "/embebido/formulario-alta",
    titulo: "Contacto",
    metodo: "POST",
  },
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
  label { display: block; font-size: .8rem; margin: 0 0 .5rem; }
  input, textarea { display: block; width: 100%; box-sizing: border-box; font: inherit; margin-top: .15rem; }
  textarea { min-height: 4rem; }
  .trampa { position: absolute; left: -10000px; width: 1px; height: 1px; overflow: hidden; }
  .aviso { font-size: .8rem; margin: .5rem 0 0; }
`;

/**
 * Lo que viene del CRM, escapado. Se pinta con `innerHTML` en la web de otro,
 * y el asunto de un caso lo puede haber escrito un cliente desde un correo:
 * sin escapar, un `<img onerror>` en un asunto se ejecutaba en la página del
 * anfitrión. El Shadow DOM aísla estilos, no scripts.
 */
function escapar(valor: string): string {
  return valor
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function texto(valor: unknown): string {
  if (valor === null || valor === undefined || valor === "") return "—";
  return escapar(String(valor));
}

/**
 * Los campos del formulario de alta: los que declara el extremo
 * (`AltaEmbebida` en `services/sales/api_embebido.py`). `trampa` no se ve: lo
 * rellena un robot y no una persona, y el canal lo descarta.
 */
const CAMPOS_ALTA: {
  nombre: string;
  etiqueta: string;
  tipo: string;
  area?: boolean;
}[] = [
  { nombre: "nombre", etiqueta: "Nombre", tipo: "text" },
  { nombre: "apellidos", etiqueta: "Apellidos", tipo: "text" },
  { nombre: "empresa", etiqueta: "Empresa", tipo: "text" },
  { nombre: "email", etiqueta: "Correo", tipo: "email" },
  { nombre: "telefono", etiqueta: "Teléfono", tipo: "tel" },
  { nombre: "mensaje", etiqueta: "Mensaje", tipo: "text", area: true },
];

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
      this.error(
        `Componente desconocido: «${nombre}». Los que hay: ${Object.keys(COMPONENTES).join(", ")}.`,
      );
      return;
    }
    if (!api || !token) {
      // Se dice qué falta y no se intenta igual: una llamada sin token
      // devuelve 401 y el mensaje que vería quien integra esto sería «no
      // autenticado», que manda a mirar al sitio equivocado.
      this.error("Faltan los atributos «api» y «token».");
      return;
    }
    if (decl.metodo === "POST") {
      // El que escribe no llama al cargar: pinta el formulario y manda lo que
      // rellena la persona. Mandaba un `{}` en cuanto se pintaba, así que cada
      // visita a la web dejaba una recepción «descartada, sin correo ni
      // teléfono» y nadie podía darse de alta.
      this.formulario(decl.titulo, `${api}${decl.ruta}`, token);
      return;
    }

    try {
      const respuesta = await fetch(`${api}${decl.ruta}`, {
        method: "GET",
        headers: { Authorization: `Bearer ${token}` },
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
    this.raiz.innerHTML = `<style>${ESTILO}</style><div class="caja"><p class="error">${escapar(mensaje)}</p></div>`;
  }

  private formulario(titulo: string, url: string, token: string): void {
    const campos = CAMPOS_ALTA.map((c) =>
      c.area
        ? `<label>${c.etiqueta}<textarea name="${c.nombre}" maxlength="2000"></textarea></label>`
        : `<label>${c.etiqueta}<input name="${c.nombre}" type="${c.tipo}" maxlength="200"></label>`,
    ).join("");
    this.raiz.innerHTML =
      `<style>${ESTILO}</style><form class="caja" novalidate><p class="titulo">${titulo}</p>${campos}` +
      // Fuera de la vista y del tabulador: una persona no lo ve ni llega a él.
      `<label class="trampa" aria-hidden="true">Web<input name="trampa" tabindex="-1" autocomplete="off"></label>` +
      `<button type="submit">Enviar</button><p class="aviso" role="status"></p></form>`;
    const form = this.raiz.querySelector("form") as HTMLFormElement;
    const aviso = this.raiz.querySelector(".aviso") as HTMLElement;
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const datos: Record<string, string> = {};
      new FormData(form).forEach((valor, clave) => {
        const v = String(valor).trim();
        if (v) datos[clave] = v;
      });
      if (!datos.email && !datos.telefono) {
        // Sin forma de contactar, el canal lo descarta: mejor decirlo aquí
        // que dar las gracias por algo que no va a llegar a nadie.
        aviso.textContent =
          "Déjanos un correo o un teléfono para poder contestarte.";
        return;
      }
      const boton = form.querySelector("button") as HTMLButtonElement;
      boton.disabled = true;
      fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(datos),
        credentials: "omit",
      })
        .then((r) => {
          if (!r.ok) throw new Error(String(r.status));
          form.innerHTML = `<p class="titulo">${titulo}</p><p>Recibido. Gracias, te contestaremos pronto.</p>`;
        })
        .catch(() => {
          boton.disabled = false;
          aviso.textContent =
            "No se ha podido enviar. Inténtalo de nuevo en un momento.";
        });
    });
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
