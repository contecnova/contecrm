/**
 * Estado compartido del panel lateral.
 *
 * Vive en un contexto y no en cada pantalla porque el botón que lo abre está en
 * la barra superior y el panel está fuera de ella: con estado por pantalla, las
 * que no lo gestionan se quedan sin navegación y sin forma de recuperarla.
 *
 * Se guarda en `localStorage` para que no se reabra en cada recarga a quien lo
 * cerró a propósito. Si el navegador no deja guardar —ventana privada, permisos
 * bloqueados— se sigue funcionando con el valor por defecto: abierto en
 * escritorio, cerrado en móvil, que es donde estorba.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

interface Contexto {
  abierto: boolean;
  fijar: (v: boolean) => void;
  alternar: () => void;
}

const Ctx = createContext<Contexto | null>(null);
const CLAVE = "contecrm.panel_abierto";

export function ProveedorPanel({ children }: { children: ReactNode }) {
  const [abierto, setAbierto] = useState<boolean>(() => {
    try {
      const guardado = localStorage.getItem(CLAVE);
      if (guardado !== null) return guardado === "1";
    } catch {
      /* sin almacenamiento: se usa el valor por defecto */
    }
    return typeof window !== "undefined"
      ? (window.matchMedia?.("(min-width: 768px)").matches ?? true)
      : true;
  });

  useEffect(() => {
    try {
      localStorage.setItem(CLAVE, abierto ? "1" : "0");
    } catch {
      /* sin almacenamiento: no se recuerda, pero se sigue pudiendo usar */
    }
  }, [abierto]);

  const fijar = useCallback((v: boolean) => setAbierto(v), []);
  const alternar = useCallback(() => setAbierto((v) => !v), []);

  return <Ctx.Provider value={{ abierto, fijar, alternar }}>{children}</Ctx.Provider>;
}

/**
 * El estado del panel. Sin proveedor devuelve «abierto» e inerte: ante la duda
 * se enseña la navegación, porque una pantalla sin menú no tiene salida.
 *
 * Se llama `usePanel` y no `usarPanel` —el único anglicismo del front— porque
 * la regla `react-hooks/rules-of-hooks` reconoce los hooks por el prefijo
 * `use`. Con el nombre en castellano, React deja de comprobar el orden de las
 * llamadas, que es lo único que evita la clase de fallo más difícil de
 * diagnosticar que tiene esta librería.
 */
export function usePanel(): Contexto {
  return useContext(Ctx) ?? { abierto: true, fijar: () => {}, alternar: () => {} };
}
