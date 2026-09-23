/**
 * Qué puede abrir esta sesión, resuelto una vez para toda la aplicación.
 *
 * Lo necesitan el menú, la portada y el buscador, y los tres tienen que
 * coincidir: encontrar por búsqueda lo que el menú esconde hace que el sistema
 * parezca contradecirse.
 *
 * Sale de `/api/v1/superficie`, que es donde el servidor publica **qué permiso
 * exige cada operación**. Es una llamada al arrancar y evita la alternativa:
 * declarar el permiso de cada uno de los ciento doce recursos en el front, es
 * decir, una segunda lista que se separaría de la del servidor en cuanto
 * alguien cambiara un permiso, sin que nada lo avisara.
 *
 * Mientras no ha llegado, **no se esconde nada**. Es deliberado: esconder por
 * defecto haría que el menú apareciera a trozos al cargar, y un menú que se
 * mueve mientras lo miras es peor que uno con una entrada de más durante medio
 * segundo.
 */

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { puede, type Sesion } from "@/lib/sesion";
import { cargarSuperficie, rutasPermitidas, type Superficie } from "@/lib/superficie";

const Ctx = createContext<Set<string>>(new Set());

export function ProveedorPermisos({
  sesion,
  children,
}: {
  sesion: Sesion | null;
  children: ReactNode;
}) {
  const [permitidas, setPermitidas] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!sesion) {
      setPermitidas(new Set());
      return;
    }
    const control = new AbortController();
    cargarSuperficie(control.signal)
      .then((superficie: Superficie) =>
        setPermitidas(rutasPermitidas(superficie, (p) => puede(sesion, p))),
      )
      .catch(() => {
        // Si la superficie no llega, no se esconde nada: dejar a alguien sin
        // menú porque una llamada auxiliar ha fallado es peor que enseñarle una
        // entrada que luego le dirá que no le toca.
        setPermitidas(new Set());
      });
    return () => control.abort();
  }, [sesion]);

  return <Ctx.Provider value={permitidas}>{children}</Ctx.Provider>;
}

/** Las rutas que esta sesión puede llamar. Vacío = todavía no se sabe. */
export function usePermitidas(): Set<string> {
  return useContext(Ctx);
}
