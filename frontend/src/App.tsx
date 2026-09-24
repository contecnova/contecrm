import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";

import { Cargando } from "@/componentes/Estados";
import { Marco } from "@/componentes/Marco";
import { Cuenta } from "@/paginas/Cuenta";
import { Consola } from "@/paginas/Consola";
import { Entrar } from "@/paginas/Entrar";
import { Casos } from "@/paginas/Casos";
import { ConsolaAgente } from "@/paginas/Consola.agente";
import { Marketing } from "@/paginas/Marketing";
import { Ficha } from "@/paginas/Ficha";
import { Inicio } from "@/paginas/Inicio";
import { Pipeline } from "@/paginas/Pipeline";
import { Modulo } from "@/paginas/Modulo";
import { Procesos } from "@/paginas/Procesos";
import { Puesto } from "@/paginas/Puesto";
import { llamar } from "@/lib/api";
import { cargarSesion, type Sesion } from "@/lib/sesion";

/**
 * Las pantallas que no son de uso diario, cargadas cuando se abren.
 *
 * Con las veintiséis en el paquete inicial, quien entra a mirar sus casos se
 * descarga también el recorrido guiado, el informe de cobertura y la consola
 * de despliegue. El tope de tamaño del front existe justamente para que eso no
 * crezca sin que nadie lo decida, y la respuesta correcta a rozarlo es partir
 * el paquete, no subir el tope.
 *
 * Las de uso diario —inicio, módulos, fichas, puesto, casos— siguen yendo de
 * una pieza: diferirlas cambiaría una espera de nada por un parpadeo en lo
 * que se abre veinte veces al día.
 */
const Cobertura = lazy(() =>
  import("@/paginas/Cobertura").then((m) => ({ default: m.Cobertura })),
);
const Estado = lazy(() =>
  import("@/paginas/Estado").then((m) => ({ default: m.Estado })),
);
const Recorrido = lazy(() =>
  import("@/paginas/Recorrido").then((m) => ({ default: m.Recorrido })),
);
const Alm = lazy(() =>
  import("@/paginas/Alm").then((m) => ({ default: m.Alm })),
);
const Ayuda = lazy(() =>
  import("@/paginas/Ayuda").then((m) => ({ default: m.Ayuda })),
);
const Inteligencia = lazy(() =>
  import("@/paginas/Inteligencia").then((m) => ({ default: m.Inteligencia })),
);
const Rendimiento = lazy(() =>
  import("@/paginas/Rendimiento").then((m) => ({ default: m.Rendimiento })),
);
const SuiteGobierno = lazy(() =>
  import("@/paginas/Suite").then((m) => ({ default: m.SuiteGobierno })),
);
const Explotacion = lazy(() =>
  import("@/paginas/Explotacion").then((m) => ({ default: m.Explotacion })),
);
const Cuadros = lazy(() =>
  import("@/paginas/Cuadros").then((m) => ({ default: m.Cuadros })),
);
const Coste = lazy(() =>
  import("@/paginas/Coste").then((m) => ({ default: m.Coste })),
);
const Conocimiento = lazy(() =>
  import("@/paginas/Conocimiento").then((m) => ({ default: m.Conocimiento })),
);
const Chat = lazy(() =>
  import("@/paginas/Chat").then((m) => ({ default: m.Chat })),
);

/**
 * Cada cuánto se renueva la sesión.
 *
 * Por debajo de la vida del token de acceso —quince minutos por defecto— y con
 * margen: renovar justo al filo deja la sesión colgando de que la red vaya bien
 * en ese instante.
 */
const MINUTOS_ENTRE_RENOVACIONES = 10;

export function App() {
  const [sesion, setSesion] = useState<Sesion | null>(null);
  const [resuelta, setResuelta] = useState(false);

  const refrescar = useCallback(() => {
    const control = new AbortController();
    cargarSesion(control.signal).then((s) => {
      setSesion(s);
      setResuelta(true);
    });
    return () => control.abort();
  }, []);

  useEffect(refrescar, [refrescar]);

  // Renovación silenciosa (CRM-07.04.02.02). Se pide ANTES de que caduque, no
  // después: descubrirlo con un 401 en mitad de un formulario pierde lo que se
  // estaba escribiendo. Si la renovación falla, la sesión se cae sola en la
  // siguiente llamada y la aplicación vuelve a la pantalla de entrada — que es
  // lo correcto, porque el token ya no vale.
  useEffect(() => {
    if (!sesion) return;
    const reloj = window.setInterval(() => {
      void llamar("/api/v1/sesion/renovar", { metodo: "POST" }).catch(
        () => undefined,
      );
    }, MINUTOS_ENTRE_RENOVACIONES * 60_000);
    return () => window.clearInterval(reloj);
  }, [sesion]);

  // Mientras no se sabe si hay sesión no se pinta ninguna de las dos cosas: ni
  // la pantalla de entrada —que haría parpadear un formulario a quien ya estaba
  // dentro— ni la aplicación, que pediría datos sin credencial.
  if (!resuelta) return <Cargando />;
  if (!sesion) return <Entrar alEntrar={refrescar} />;

  return (
    <Marco sesion={sesion}>
      <Suspense fallback={<Cargando />}>
        <Routes>
          <Route path="/" element={<Inicio sesion={sesion} />} />
          <Route path="/administracion" element={<Consola sesion={sesion} />} />
          <Route path="/m/:ruta" element={<Modulo sesion={sesion} />} />
          {/* La cuenta tiene ficha propia: la genérica es un inspector de
              registros y con ella delante no se puede contestar «¿cómo vamos
              con este cliente?», que es para lo que se abre un CRM. */}
          <Route path="/m/cuentas/cuenta/:id" element={<Cuenta />} />
          {/* Y la del proveedor es **la misma pantalla**, porque un proveedor
              es una cuenta con ese rol. Una ficha propia y parecida sería un
              segundo sitio donde mirar lo mismo, con el «lo que ha pasado» en
              otro lugar y las mismas cosas contadas de otra forma. */}
          <Route path="/m/proveedores/proveedor/:id" element={<Cuenta />} />
          <Route path="/m/:ruta/:tipo/:id" element={<Ficha />} />
          <Route path="/estado" element={<Estado />} />
          <Route path="/cobertura" element={<Cobertura />} />
          <Route path="/chat" element={<Chat sesion={sesion} />} />
          <Route path="/recorrido" element={<Recorrido />} />
          <Route path="/procesos" element={<Procesos />} />
          <Route path="/explotacion" element={<Explotacion />} />
          <Route path="/cuadros" element={<Cuadros />} />
          <Route path="/embudo" element={<Pipeline sesion={sesion} />} />
          <Route path="/casos" element={<Casos />} />
          <Route path="/consola-agente" element={<ConsolaAgente />} />
          <Route path="/conocimiento" element={<Conocimiento />} />
          <Route path="/marketing" element={<Marketing />} />
          <Route path="/coste" element={<Coste />} />
          <Route path="/inteligencia" element={<Inteligencia />} />
          <Route path="/puesto" element={<Puesto />} />
          <Route path="/alm" element={<Alm />} />
          <Route path="/rendimiento" element={<Rendimiento />} />
          <Route path="/suite" element={<SuiteGobierno />} />
          <Route path="/ayuda" element={<Ayuda />} />
        </Routes>
      </Suspense>
    </Marco>
  );
}
