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
 * **Son tres estados, no dos.** Durante mucho tiempo esto se resolvía con un
 * solo conjunto de rutas y la regla «si está vacío, no se esconde nada», que
 * mezclaba dos situaciones muy distintas —todavía no se sabe, y se sabe que no
 * puede nada— y además dejaba una tercera sin representar:
 *
 * 1. **Todavía no ha llegado.** No se esconde nada. Es deliberado: esconder por
 *    defecto haría que el menú apareciera a trozos al cargar, y un menú que se
 *    mueve mientras lo miras es peor que uno con una entrada de más durante
 *    medio segundo.
 * 2. **Ha llegado entera.** Manda ella: lo que no está, no se enseña.
 * 3. **Ha llegado incompleta.** El gateway la agrega preguntando a los diez
 *    servicios y **dice cuáles no le han contestado**. Un servicio que no
 *    contesta aporta cero operaciones, así que sus pestañas se escondían con el
 *    mismo gesto con el que se esconde lo prohibido. Para quien mira el menú
 *    eso no es un servicio caído: son opciones que aparecen y desaparecen sin
 *    motivo entre una pantalla y la siguiente.
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

/** Lo que hace falta para decidir si una pestaña se enseña. */
export interface Visibilidad {
  /** Rutas de lectura que esta sesión puede llamar, según el servidor. */
  rutas: Set<string>;
  /**
   * Si la superficie ya ha llegado.
   *
   * Mientras es `false` **no se esconde nada**, y eso no se puede deducir de
   * que `rutas` esté vacío: una sesión sin permisos tiene el conjunto vacío y
   * ahí sí hay que esconder.
   */
  cargada: boolean;
  /**
   * Servicios que no contestaron al agregarse la superficie.
   *
   * De lo suyo no se sabe nada —no es que esté prohibido, es que no se ha
   * podido preguntar—, así que sus pestañas **no se esconden**.
   */
  sinContestar: Set<string>;
}

interface Permisos {
  visibilidad: Visibilidad;
  /** ¿Admite el servidor esta operación, y se la admite a esta sesión? */
  puedeOperar: (metodo: string, ruta: string) => boolean;
  /** Lo que publica el servidor, para calcular las acciones de un registro. */
  superficie: Superficie | null;
  /** Si esta sesión tiene un permiso concreto. */
  tiene: (permiso: string | null) => boolean;
}

/** Lo que se sabe antes de preguntar: nada, y por eso no se esconde nada. */
const NADA_SABIDO: Visibilidad = {
  rutas: new Set(),
  cargada: false,
  sinContestar: new Set(),
};

const Ctx = createContext<Permisos>({
  visibilidad: NADA_SABIDO,
  puedeOperar: () => false,
  superficie: null,
  tiene: () => false,
});

export function ProveedorPermisos({
  sesion,
  children,
}: {
  sesion: Sesion | null;
  children: ReactNode;
}) {
  const [visibilidad, setVisibilidad] = useState<Visibilidad>(NADA_SABIDO);
  const [superficie, setSuperficie] = useState<Superficie | null>(null);

  useEffect(() => {
    if (!sesion) {
      setVisibilidad(NADA_SABIDO);
      setSuperficie(null);
      return;
    }
    const control = new AbortController();
    cargarSuperficie(control.signal)
      .then((s: Superficie) => {
        setSuperficie(s);
        setVisibilidad({
          rutas: rutasPermitidas(s, (p) => puede(sesion, p), Boolean(sesion?.es_admin_plataforma)),
          cargada: true,
          // Lo que el gateway ya decía y aquí no leía nadie. Sin esto, un
          // servicio que tarda en arrancar deja su parte del menú fuera
          // durante toda la sesión y no hay forma de saber por qué.
          sinContestar: new Set(s.servicios_sin_contestar ?? []),
        });
      })
      .catch(() => {
        // **Un aborto no es un fallo.** Lo dispara la limpieza de este mismo
        // efecto, y entrar aquí por eso hace que se apunte «no se ha podido
        // preguntar» cuando lo que ha pasado es que ya no interesa la
        // respuesta. No es lo que causaba el menú cambiante —eso era la
        // superficie incompleta, arriba—; se distingue igual porque un estado
        // que miente sobre su causa es el siguiente rato perdido.
        if (control.signal.aborted) return;
        // Si de verdad no llega, no se esconde nada del menú: dejar a alguien
        // sin navegación porque una llamada auxiliar ha fallado es peor que
        // enseñarle una entrada que luego le dirá que no le toca.
        setVisibilidad(NADA_SABIDO);
        setSuperficie(null);
      });
    return () => control.abort();
  }, [sesion]);

  const valor = useMemo<Permisos>(
    () => ({
      visibilidad,
      // Al revés que el menú: aquí, mientras no se sabe, **no se ofrece**. Un
      // botón de eliminar que aparece por defecto y luego resulta que no te
      // tocaba es un botón que alguien ya ha pulsado.
      puedeOperar: (metodo, ruta) =>
        operacionPermitida(superficie, metodo, ruta, (p) => puede(sesion, p)),
      superficie,
      tiene: (permiso) => puede(sesion, permiso),
    }),
    [visibilidad, superficie, sesion],
  );

  return <Ctx.Provider value={valor}>{children}</Ctx.Provider>;
}

/**
 * Lo que hace falta para decidir qué enseña el menú.
 *
 * Devuelve los tres datos juntos —rutas, si ya se sabe y de qué servicios no—
 * porque los tres hacen falta a la vez y entregar sólo el conjunto obligaba a
 * adivinar los otros dos a partir de su tamaño.
 */
export function useVisibilidad(): Visibilidad {
  return useContext(Ctx).visibilidad;
}

/** Si el servidor admite esa operación y se la admite a esta sesión. */
export function usePuedeOperar(): (metodo: string, ruta: string) => boolean {
  return useContext(Ctx).puedeOperar;
}

/** Lo que publica el servidor y qué permisos tiene esta sesión. */
export function useSuperficie(): { superficie: Superficie | null; tiene: (p: string | null) => boolean } {
  const { superficie, tiene } = useContext(Ctx);
  return { superficie, tiene };
}
