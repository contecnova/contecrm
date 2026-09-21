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

import { useEffect, useState } from "react";

import { filas, llamar } from "@/lib/api";

export interface Persona {
  id: string;
  nombre: string;
  email: string;
}

let promesa: Promise<Record<string, Persona>> | null = null;

function cargar(): Promise<Record<string, Persona>> {
  if (promesa) return promesa;
  promesa = llamar<unknown>("/api/v1/usuarios?limite=500")
    .then((r) =>
      Object.fromEntries(filas<Persona>(r.datos).map((p) => [p.id, p])),
    )
    .catch(() => ({}) as Record<string, Persona>);
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
    void cargar().then((p) => {
      if (vivo) setPersonas(p);
    });
    return () => {
      vivo = false;
    };
  }, []);
  return personas;
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
