/**
 * Qué significa cada estado, y de qué color se pinta.
 *
 * Una tarjeta con etiquetas de colores solo sirve si el color **significa algo
 * siempre lo mismo**. Con un color por valor sacado de un hash, «perdida» sale
 * verde en un listado y morada en otro, y entonces el color deja de leerse: se
 * lee la palabra, que es lo que había antes de poner colores.
 *
 * Así que el significado se declara, y lo que no está declarado sale neutro. Un
 * valor nuevo saliendo en gris es correcto —no dice nada porque todavía no
 * hemos decidido qué dice—; saliendo en un color al azar es peor que gris,
 * porque parece que dice algo.
 */

export type Tono = "exito" | "aviso" | "peligro" | "acento" | "neutro";

/**
 * Valores cuyo significado es el mismo en todo el sistema.
 *
 * Están en minúsculas y sin acentos porque así llegan de la API: `ganada`,
 * `en_curso`, `critica`.
 */
const SIGNIFICADO: Record<string, Tono> = {
  // Terminó bien
  ganada: "exito",
  ganado: "exito",
  aprobada: "exito",
  aprobado: "exito",
  activa: "exito",
  activo: "exito",
  publicada: "exito",
  publicado: "exito",
  resuelto: "exito",
  resuelta: "exito",
  cerrado: "exito",
  cerrada: "exito",
  homologado: "exito",
  convertido: "exito",
  firmado: "exito",
  pagada: "exito",
  cobrada: "exito",
  // Terminó mal, o está roto
  perdida: "peligro",
  perdido: "peligro",
  rechazada: "peligro",
  rechazado: "peligro",
  denegada: "peligro",
  bloqueado: "peligro",
  bloqueada: "peligro",
  critica: "peligro",
  critico: "peligro",
  vencida: "peligro",
  vencido: "peligro",
  incumplido: "peligro",
  descartado: "peligro",
  suspendido: "peligro",
  baja: "neutro",
  // Pide atención sin ser un fallo
  alta: "aviso",
  urgente: "aviso",
  pendiente: "aviso",
  esperando: "aviso",
  esperando_cliente: "aviso",
  esperando_humano: "aviso",
  borrador: "aviso",
  en_revision: "aviso",
  por_vencer: "aviso",
  // En marcha
  abierta: "acento",
  abierto: "acento",
  en_curso: "acento",
  nuevo: "acento",
  nueva: "acento",
  asignado: "acento",
  cualificado: "acento",
  normal: "neutro",
  media: "neutro",
};

/** El tono de un valor, o neutro si no se ha decidido qué significa. */
export function tonoDe(valor: unknown): Tono {
  return SIGNIFICADO[String(valor ?? "").toLowerCase()] ?? "neutro";
}

/**
 * Las clases de una etiqueta con ese tono.
 *
 * Se usan las variables de texto accesibles (`text-success` → `--success-text`,
 * 4,6:1 sobre la superficie) y no el color base: el base está pensado para
 * rellenos, y como texto no llega al contraste mínimo.
 */
export function clasesDeTono(tono: Tono): string {
  switch (tono) {
    case "exito":
      return "border-success/40 bg-success/10 text-success";
    case "aviso":
      return "border-warning/40 bg-warning/10 text-warning";
    case "peligro":
      return "border-danger/40 bg-danger/10 text-danger";
    case "acento":
      return "border-accent/40 bg-accent/10 text-accent";
    default:
      return "border-ink-dim/60 bg-paper-sunk text-ink-muted";
  }
}

/** Campos cuyo valor es un estado y merece pintarse como etiqueta. */
export const CAMPOS_DE_ESTADO = [
  "estado",
  "etapa",
  "prioridad",
  "severidad",
  "tipo",
  "nivel",
  "audiencia",
  "categoria",
  "tier",
];

/** Campos cuya suma o cuya cifra importa: se pintan grandes. */
export const CAMPOS_DE_CIFRA =
  /^(importe|total|presupuesto|asignado|objetivo|coste|precio_base|importe_estimado|importe_periodo|facturacion)/;

/**
 * Si esta fila va con retraso, y por qué.
 *
 * Es lo que más urge de una tarjeta y lo que una tabla esconde entre columnas.
 * Se mira en dos sitios: una marca explícita de incumplimiento —el servicio ya
 * la calcula, y su cuenta del plazo laborable es mejor que cualquier resta que
 * hagamos aquí— y una fecha de vencimiento ya pasada.
 */
export function retrasoDe(fila: Record<string, unknown>): string {
  for (const [campo, valor] of Object.entries(fila)) {
    if (valor === true && /incumpli|vencid/.test(campo)) return campo;
  }
  const ahora = Date.now();
  for (const [campo, valor] of Object.entries(fila)) {
    if (!/^(vence|caduca|valido_hasta|vigente_hasta|protegido_hasta)/.test(campo)) continue;
    const fecha = Date.parse(String(valor ?? ""));
    if (!Number.isNaN(fecha) && fecha < ahora) return campo;
  }
  return "";
}
