/**
 * Tema claro y oscuro, con la elección recordada por navegador.
 *
 * Es lo único que este front guarda en el navegador, junto con el idioma:
 * preferencias de quien mira, nunca dato de negocio (CRM-07.04.02.09). Y
 * siempre entre `try`, porque en modo privado o con el almacenamiento
 * bloqueado leer o escribir **lanza**, y una preferencia no puede tumbar la
 * aplicación.
 */

export type Tema = "claro" | "oscuro";

const CLAVE = "contecrm.tema";

export function temaActual(): Tema {
  try {
    const guardado = localStorage.getItem(CLAVE);
    if (guardado === "claro" || guardado === "oscuro") return guardado;
  } catch {
    /* sin almacenamiento: manda el sistema */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro";
}

export function aplicarTema(tema: Tema): void {
  document.documentElement.classList.toggle("dark", tema === "oscuro");
  try {
    localStorage.setItem(CLAVE, tema);
  } catch {
    /* la elección no sobrevive a la recarga, pero la sesión funciona */
  }
}
