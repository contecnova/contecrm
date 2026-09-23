/**
 * Cómo se escribe un valor para que lo lea una persona.
 *
 * Esto existe porque la tabla genérica volcaba los valores compuestos en JSON:
 * una celda con `{"procesos":true,"webhooks":true,"ia_gen…` recortada a la
 * mitad. Es información verdadera y es **inutilizable**: nadie lee un objeto
 * JSON de un vistazo, y recortado ni siquiera se puede leer entero.
 *
 * Lo mismo con los números —`19440000.00` no se lee, `19.440.000 €` sí— y con
 * las fechas en ISO, que son para máquinas.
 */

/** Separadores de miles y coma decimal, en español. */
const NUMERO = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2 });
const DINERO = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 });
const FECHA = new Intl.DateTimeFormat("es-ES", { dateStyle: "short" });
const FECHA_HORA = new Intl.DateTimeFormat("es-ES", { dateStyle: "short", timeStyle: "short" });

const ISO_FECHA = /^\d{4}-\d{2}-\d{2}$/;
const ISO_MOMENTO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Nombres de campo que se leen como importes: se escriben sin decimales. */
const PARECE_IMPORTE = /(importe|facturacion|precio|coste|margen|total|saldo|cuota)/i;

/**
 * Prefijos técnicos que no aportan nada al leerlo.
 *
 * `quota_registros` se lee «Registros»: la columna ya se llama «Cuotas», y
 * repetir «quota» en cada etiqueta gasta espacio y no dice nada. Es una regla,
 * no una tabla de traducciones, para que no se quede corta al primer campo
 * nuevo.
 */
const PREFIJOS_TECNICOS = /^(quota|cuota|flag|attr|meta|config|param)_/;

/** El nombre del campo, escrito como se lee: `sector_codigo` → «Sector codigo». */
export function humanizar(campo: string): string {
  const limpio = campo.replace(PREFIJOS_TECNICOS, "").replace(/_/g, " ").trim();
  return limpio.charAt(0).toUpperCase() + limpio.slice(1);
}

/** ¿Hay algo que enseñar? Una lista vacía y un objeto vacío no lo son. */
export function tieneDato(valor: unknown): boolean {
  if (valor === null || valor === undefined || valor === "") return false;
  if (Array.isArray(valor)) return valor.length > 0;
  if (typeof valor === "object") return Object.keys(valor as object).length > 0;
  return true;
}

/** Un número, una fecha o un texto, escritos en castellano. */
export function escalar(valor: unknown, campo = ""): string {
  if (typeof valor === "boolean") return valor ? "sí" : "no";
  if (typeof valor === "number") {
    return (PARECE_IMPORTE.test(campo) ? DINERO : NUMERO).format(valor);
  }
  const texto = String(valor);
  // Los decimales llegan como cadena desde la API (`Numeric` en JSON es texto
  // para no perder precisión), así que hay que reconocerlos aquí.
  if (/^-?\d+(\.\d+)?$/.test(texto) && texto.length < 18) {
    return (PARECE_IMPORTE.test(campo) ? DINERO : NUMERO).format(Number(texto));
  }
  if (ISO_MOMENTO.test(texto)) {
    const d = new Date(texto);
    if (!Number.isNaN(d.getTime())) return FECHA_HORA.format(d);
  }
  if (ISO_FECHA.test(texto)) {
    const d = new Date(`${texto}T00:00:00`);
    if (!Number.isNaN(d.getTime())) return FECHA.format(d);
  }
  return texto;
}

export interface Trozo {
  texto: string;
  /** Un interruptor apagado se pinta distinto de uno encendido. */
  apagado?: boolean;
}

/**
 * Un valor compuesto, convertido en trozos legibles.
 *
 * Un objeto de interruptores —`{"procesos":true,"ia_generativa":false}`— se lee
 * como lo que es: qué está encendido y qué no. Un objeto de cifras —las
 * cuotas— como pares «nombre: cifra». Y una lista, como sus elementos.
 */
export function trozos(valor: unknown, campo = ""): Trozo[] {
  if (Array.isArray(valor)) {
    return valor.map((v) => ({
      texto:
        v !== null && typeof v === "object"
          ? trozos(v)
              .map((t) => t.texto)
              .join(" · ")
          : escalar(v, campo),
    }));
  }
  if (valor !== null && typeof valor === "object") {
    return Object.entries(valor as Record<string, unknown>).map(([k, v]) => {
      if (typeof v === "boolean") return { texto: humanizar(k), apagado: !v };
      if (v !== null && typeof v === "object") {
        return { texto: `${humanizar(k)}: ${trozos(v).length}` };
      }
      return { texto: `${humanizar(k)}: ${escalar(v, k)}` };
    });
  }
  return [{ texto: escalar(valor, campo) }];
}
