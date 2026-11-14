/**
 * Quién es cada identificador de persona.
 *
 * Las filas traen `owner_id`, `asignado_a`, `autor_id`… y un UUID no dice de
 * quién es nada. Resolverlo en cada pantalla acabaría pidiendo la lista de
 * usuarios una vez por tabla —y varias veces por pantalla, porque una ficha
 * tiene tablas dentro—, así que se pide **una vez por sesión** y se comparte.
 *
 * Si la lista no llega no se rompe nada: se enseña el identificador recortado,
 * que es lo que había antes. Una pantalla sin nombres es peor que con ellos,
 * pero mucho mejor que una pantalla que no carga.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { filas, llamar, siguientePagina } from "@/lib/api";
import { MAXIMO_POR_PAGINA } from "@/lib/listados";

export interface Persona {
  id: string;
  nombre: string;
  email: string;
}

/**
 * Lo que se ha podido traer del directorio, y cómo ha ido.
 *
 * Los nombres se resuelven con lo que haya (medio directorio es mejor que
 * ninguno), pero quien ELIGE a una persona de una lista necesita saber si la
 * lista está entera: que falte alguien porque la consulta falló, o porque se
 * llegó al tope, no puede leerse como «esa persona no existe».
 */
interface Carga {
  porId: Record<string, Persona>;
  /** El fallo que cortó el recorrido, o `null`. */
  fallo: unknown;
  /** Se paró en `TOPE` con el servidor diciendo que había más. */
  recortado: boolean;
}

let promesa: Promise<Carga> | null = null;

/**
 * Cuántas se piden por vuelta. **Doscientas, que es el tope del servidor.**
 *
 * Pedía quinientas y el servidor topa en doscientas: respondía 422, el `catch`
 * se lo tragaba y el directorio quedaba **vacío para toda la sesión**. El
 * efecto no era un error en pantalla sino peor: cada responsable salía como un
 * identificador recortado —«01a17cf1…»— en las tarjetas, en las tablas y en
 * las fichas, y eso se lee como un dato roto, no como una llamada que falló.
 *
 * Lo vio quien la usa, en la consola. No lo cazaba nada porque el `catch`
 * convierte el fallo en una respuesta legítima: «no se sabe quién es nadie».
 */
const POR_VUELTA = MAXIMO_POR_PAGINA;

/**
 * Tope de personas que se traen.
 *
 * Con el cursor se podría recorrer un tenant de diez mil, y eso son cincuenta
 * peticiones al abrir la primera pantalla. Dos mil cubre cualquier empresa real
 * y acota el coste; si alguna vez hiciera falta más, lo que hay que cambiar no
 * es este número sino resolver los nombres en el servidor.
 */
const TOPE = 2_000;

function cargar(): Promise<Carga> {
  if (promesa) return promesa;
  promesa = (async () => {
    const porId: Record<string, Persona> = {};
    let cursor = "";
    try {
      // Por páginas, siguiendo el cursor: con el tope del servidor en 200, una
      // sola vuelta deja fuera a cualquier empresa mediana y sus nombres
      // saldrían como identificadores sin que nada fallara.
      for (let vuelta = 0; vuelta < Math.ceil(TOPE / POR_VUELTA); vuelta += 1) {
        const q = new URLSearchParams({ limite: String(POR_VUELTA) });
        if (cursor) q.set("cursor", cursor);
        const r = await llamar<unknown>(`/api/v1/usuarios?${q}`);
        for (const persona of filas<Persona>(r.datos)) porId[persona.id] = persona;
        cursor = siguientePagina(r.datos);
        if (!cursor) break;
      }
    } catch (fallo) {
      // Lo que se haya podido traer vale para los nombres: lo que falte sale
      // como identificador. Pero el fallo se GUARDA, para que quien enseña
      // la lista para elegir pueda decir que no está entera (`useDirectorio`).
      return { porId, fallo, recortado: false };
    }
    return { porId, fallo: null, recortado: cursor !== "" };
  })();
  return promesa;
}

/** Vacía la caché. Solo para las pruebas y para cuando se cambia de sesión. */
export function olvidarPersonas(): void {
  promesa = null;
}

export function usePersonas(): Record<string, Persona> {
  const [personas, setPersonas] = useState<Record<string, Persona>>({});
  useEffect(() => {
    let vivo = true;
    void cargar().then((c) => {
      if (vivo) setPersonas(c.porId);
    });
    return () => {
      vivo = false;
    };
  }, []);
  return personas;
}

/** El directorio como LISTA PARA ELEGIR, con lo que hace falta para fiarse. */
export interface Directorio {
  /** Por nombre (o correo). `null` mientras llega. */
  personas: Persona[] | null;
  fallo: unknown;
  /** Hay más personas que las que se enseñan (se llegó a `TOPE`). */
  recortado: boolean;
  reintentar: () => void;
}

/**
 * La lista de personas para un desplegable de «elige a alguien».
 *
 * Seis selectores pedían `/usuarios?limite=200` por su cuenta y, en una
 * organización de más de doscientas, la doscientas una no se podía elegir sin
 * que nada lo dijera. Aquí sale del mismo directorio que los nombres —una
 * petición por sesión, siguiendo el cursor— y dice si falló o se cortó.
 */
export function useDirectorio(): Directorio {
  const [carga, setCarga] = useState<Carga | null>(null);
  const [vuelta, setVuelta] = useState(0);
  useEffect(() => {
    let vivo = true;
    void cargar().then((c) => {
      if (vivo) setCarga(c);
    });
    return () => {
      vivo = false;
    };
  }, [vuelta]);
  const personas = useMemo(
    () =>
      carga
        ? Object.values(carga.porId).sort((a, b) =>
            (a.nombre || a.email).localeCompare(b.nombre || b.email),
          )
        : null,
    [carga],
  );
  const reintentar = useCallback(() => {
    // Sólo se olvida si falló: un directorio bueno no se vuelve a pedir.
    if (carga?.fallo) olvidarPersonas();
    setCarga(null);
    setVuelta((v) => v + 1);
  }, [carga]);
  return {
    personas,
    fallo: carga?.fallo ?? null,
    recortado: carga?.recortado ?? false,
    reintentar,
  };
}

/** Cómo se llama, o el identificador recortado si no se sabe. */
export function nombreDe(personas: Record<string, Persona>, id: unknown): string {
  const clave = String(id ?? "");
  const persona = personas[clave];
  if (persona) return persona.nombre || persona.email;
  return clave.length > 12 ? `${clave.slice(0, 8)}…` : clave;
}

/**
 * Las iniciales, para el círculo del avatar.
 *
 * De dos palabras y no de una: con una sola inicial, media plantilla comparte
 * letra y el avatar deja de distinguir a nadie.
 */
export function inicialesDe(nombre: string): string {
  const trozos = nombre.trim().split(/\s+/).filter(Boolean);
  if (trozos.length === 0) return "?";
  if (trozos.length === 1) return (trozos[0] ?? "").slice(0, 2).toUpperCase();
  return `${trozos[0]?.[0] ?? ""}${trozos[1]?.[0] ?? ""}`.toUpperCase();
}
