/**
 * Configuración del cliente, leída en EJECUCIÓN y no compilada.
 *
 * La dirección del gateway, el nombre del producto y el color de marca cambian
 * por instalación y por tenant. Compilarlos obligaría a reconstruir la imagen
 * para cambiar una URL, que es justo lo que la regla de «toda la configuración
 * en el `.env` y en la parte de configuración de la solución» viene a evitar.
 *
 * `/config.json` lo sirve el propio contenedor y lo genera su arranque a partir
 * de variables de entorno, igual que hace el resto de la pila.
 *
 * Ese mismo contenedor pone las cabeceras de seguridad del cliente
 * (CRM-07.04.02.04): CSP sin `eval` ni estilos en línea, `nosniff`,
 * `frame-ancestors: none` y aislamiento de origen. Están en `nginx.conf` y no
 * aquí porque una cabecera que pone la aplicación puede quitarla la propia
 * aplicación; una que pone el servidor, no.
 */

export interface Config {
  /** Base de la API. Vacío = mismo origen, que es lo normal detrás de un proxy. */
  apiBase: string;
  /** Nombre visible del producto (marca blanca, CRM-00.01.04.06, CRM-07.04.01.04). */
  nombre: string;
  /** Idioma por defecto si el navegador no dice otra cosa. */
  idioma: string;
  /** Color de acento, como `R G B`. Vacío = el del sistema de diseño. */
  acento: string;
  /** URL del logotipo. Vacío = se enseña el nombre. */
  logotipo: string;
}

const POR_DEFECTO: Config = {
  apiBase: "",
  nombre: "contecrm",
  idioma: "es",
  acento: "",
  logotipo: "",
};

let actual: Config = POR_DEFECTO;

export async function cargarConfig(): Promise<Config> {
  try {
    const respuesta = await fetch("/config.json", { cache: "no-store" });
    if (respuesta.ok) actual = { ...POR_DEFECTO, ...(await respuesta.json()) };
  } catch {
    // Sin fichero se usan los valores por defecto: la aplicación tiene que
    // arrancar igual. Un front que se niega a cargar porque falta un fichero de
    // configuración opcional es un front que nadie puede depurar.
  }
  return actual;
}

export function config(): Config {
  return actual;
}

/**
 * Aplica la marca del cliente (CRM-07.04.01.04).
 *
 * El acento se escribe sobre la MISMA variable que usa el sistema de diseño, no
 * sobre una clase aparte: así el color del cliente llega a todo lo que ya usa
 * `bg-accent` o `text-accent` sin repasar la aplicación. Se valida la forma
 * antes de escribirla, porque una variable CSS con un valor inventado no falla:
 * simplemente deja de aplicarse y el acento desaparece sin decir por qué.
 */
export function aplicarMarca(c: Config = actual): void {
  if (/^\d{1,3} \d{1,3} \d{1,3}$/.test(c.acento)) {
    document.documentElement.style.setProperty("--accent", c.acento);
    document.documentElement.style.setProperty("--accent-text", c.acento);
  }
  if (c.nombre) document.title = c.nombre;
}
