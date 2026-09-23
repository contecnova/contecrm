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

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { puede, type Sesion } from "@/lib/sesion";
import {
  cargarSuperficie,
  operacionPermitida,
  rutasPermitidas,
  type Superficie,
} from "@/lib/superficie";

interface Permisos {
  /** Rutas de lectura que esta sesión puede llamar. Vacío = todavía no se sabe. */
  rutas: Set<string>;
  /** ¿Admite el servidor esta operación, y se la admite a esta sesión? */
  puedeOperar: (metodo: string, ruta: string) => boolean;
}

const Ctx = createContext<Permisos>({ rutas: new Set(), puedeOperar: () => false });

export function ProveedorPermisos({
  sesion,
  children,
}: {
  sesion: Sesion | null;
  children: ReactNode;
}) {
  const [permitidas, setPermitidas] = useState<Set<string>>(new Set());
  const [superficie, setSuperficie] = useState<Superficie | null>(null);

  useEffect(() => {
    if (!sesion) {
      setPermitidas(new Set());
      return;
    }
    const control = new AbortController();
    cargarSuperficie(control.signal)
      .then((s: Superficie) => {
        setSuperficie(s);
        setPermitidas(rutasPermitidas(s, (p) => puede(sesion, p)));
      })
      .catch(() => {
        // Si la superficie no llega, no se esconde nada del menú: dejar a
        // alguien sin navegación porque una llamada auxiliar ha fallado es peor
        // que enseñarle una entrada que luego le dirá que no le toca.
        setPermitidas(new Set());
        setSuperficie(null);
      });
    return () => control.abort();
  }, [sesion]);

  const valor = useMemo<Permisos>(
    () => ({
      rutas: permitidas,
      // Al revés que el menú: aquí, mientras no se sabe, **no se ofrece**. Un
      // botón de eliminar que aparece por defecto y luego resulta que no te
      // tocaba es un botón que alguien ya ha pulsado.
      puedeOperar: (metodo, ruta) =>
        operacionPermitida(superficie, metodo, ruta, (p) => puede(sesion, p)),
    }),
    [permitidas, superficie, sesion],
  );

  return <Ctx.Provider value={valor}>{children}</Ctx.Provider>;
}

/** Las rutas de lectura que esta sesión puede llamar. Vacío = todavía no se sabe. */
export function usePermitidas(): Set<string> {
  return useContext(Ctx).rutas;
}

/** Si el servidor admite esa operación y se la admite a esta sesión. */
export function usePuedeOperar(): (metodo: string, ruta: string) => boolean {
  return useContext(Ctx).puedeOperar;
}
