/**
 * Las vistas de lista guardadas de un listado.
 *
 * Es el recorte con nombre que alguien crea una vez y abre cada día: «Mis
 * oportunidades abiertas», «Casos que vencen hoy». El producto tenía filtros,
 * orden y elección de columnas y ninguna forma de guardarlos.
 *
 * **Las guarda el servidor y no el navegador**, y eso es la mitad de lo que
 * aporta: una vista guardada en `localStorage` se pierde al cambiar de
 * ordenador, no se puede compartir con el equipo y no existe para el móvil.
 * Lo que sí sigue en el navegador es la preferencia suelta —qué columnas miro
 * yo hoy en esta pestaña—, que es otra cosa.
 */

import { llamar } from "@/lib/api";

export interface VistaDeLista {
  id: string;
  recurso: string;
  nombre: string;
  /** El mismo objeto de filtros que ya viaja en la URL del listado. */
  filtros: Record<string, unknown>;
  columnas: string[];
  orden: { columna: string; sentido: "asc" | "desc" } | null;
  /** La ve todo el tenant. Sin esto, sólo quien la guardó. */
  compartida: boolean;
  es_defecto: boolean;
}

// La ruta va ESCRITA en cada llamada y no en una constante compartida. Es más
// repetitivo y es a propósito: el gate que comprueba que una pantalla manda lo
// que el servidor exige lee las rutas del código, y una constante le esconde
// qué parámetros lleva cada llamada. Aquí importa —el `GET` exige `recurso` y
// el `POST` no, porque al crear viaja en el cuerpo— y esconderlo deja la
// lectura sin vigilar.

export async function vistasDe(recurso: string): Promise<VistaDeLista[]> {
  // Un fallo aquí **no puede tumbar el listado**: las vistas son una ayuda y
  // la lista funciona sin ellas. Sin este `catch`, un tenant cuyo servicio de
  // metadatos esté caído no podría abrir ninguna pantalla.
  try {
    const r = await llamar<VistaDeLista[]>(
      `/api/v1/metadata/vistas-de-lista?recurso=${encodeURIComponent(recurso)}`,
    );
    return Array.isArray(r.datos) ? r.datos : [];
  } catch {
    return [];
  }
}

export async function guardarVista(
  datos: Omit<VistaDeLista, "id" | "es_defecto"> & { es_defecto?: boolean },
): Promise<VistaDeLista> {
  const r = await llamar<VistaDeLista>("/api/v1/metadata/vistas-de-lista", {
    metodo: "POST",
    cuerpo: datos,
  });
  return r.datos;
}

export async function cambiarVista(
  id: string,
  cambios: Partial<Pick<VistaDeLista, "nombre" | "filtros" | "columnas" | "orden" | "es_defecto">>,
): Promise<VistaDeLista> {
  const r = await llamar<VistaDeLista>(`/api/v1/metadata/vistas-de-lista/${id}`, {
    metodo: "PATCH",
    cuerpo: cambios,
  });
  return r.datos;
}

export async function borrarVista(id: string): Promise<void> {
  await llamar(`/api/v1/metadata/vistas-de-lista/${id}`, { metodo: "DELETE" });
}

/**
 * Cuál se abre: la marcada por defecto, y si no, ninguna.
 *
 * «Ninguna» es un estado legítimo y se enseña como **«Todo»**: es lo que había
 * antes de que existieran las vistas, y quien no ha guardado ninguna tiene que
 * seguir viendo su listado completo sin tener que elegir nada.
 */
export function vistaDeEntrada(vistas: VistaDeLista[]): VistaDeLista | null {
  return vistas.find((v) => v.es_defecto) ?? null;
}
