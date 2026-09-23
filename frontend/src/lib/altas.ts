/**
 * Lo que se da de alta todos los días, en un sitio y siempre a mano.
 *
 * Esto faltaba, y era lo primero que falta al abrir el producto: el menú decía
 * «Cuentas y contactos», «Pipeline», «Prospección» —nombres de pantalla— y
 * quien entra no busca una pantalla, busca **dar de alta un cliente**. Sin un
 * punto de creación visible, la única forma de encontrarlo es entrar en la
 * pantalla correcta y localizar un botón dentro. Eso no lo adivina nadie.
 *
 * Todas las herramientas del mercado resuelven esto igual y por el mismo
 * motivo: Salesforce con «+ New», HubSpot con «Create», Dynamics con «+ New».
 * Un botón fijo en la barra, con las altas frecuentes dentro.
 *
 * Cada alta lleva a la pantalla de su recurso con el formulario **ya abierto**
 * (`?nuevo=1`), así que de la intención al formulario hay un clic.
 */

export interface Alta {
  /** Clave de traducción del rótulo, en forma de acción: «Cliente», «Lead». */
  clave: string;
  icono: string;
  /** Módulo y recurso donde vive el alta. */
  a: string;
  /** Permiso que exige el servidor para crearlo. */
  permiso: string;
}

export const ALTAS: Alta[] = [
  {
    clave: "altas.cuenta",
    icono: "domain_add",
    a: "/m/cuentas?r=Cuentas&nuevo=1",
    permiso: "account:write",
  },
  {
    clave: "altas.contacto",
    icono: "person_add",
    a: "/m/cuentas?r=Contactos&nuevo=1",
    permiso: "contact:write",
  },
  {
    clave: "altas.oportunidad",
    icono: "trending_up",
    a: "/m/oportunidades?r=Oportunidades&nuevo=1",
    permiso: "opportunity:write",
  },
  {
    clave: "altas.lead",
    icono: "person_search",
    a: "/m/leads?r=Leads&nuevo=1",
    permiso: "lead:write",
  },
  {
    clave: "altas.actividad",
    icono: "event",
    a: "/m/actividades?r=Actividades&nuevo=1",
    permiso: "activity:write",
  },
  {
    clave: "altas.caso",
    icono: "confirmation_number",
    a: "/m/casos?r=Casos&nuevo=1",
    permiso: "case:write",
  },
];
