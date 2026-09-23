import { useCallback, useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";

import { Cargando } from "@/componentes/Estados";
import { Marco } from "@/componentes/Marco";
import { Cobertura } from "@/paginas/Cobertura";
import { Cuenta } from "@/paginas/Cuenta";
import { Consola } from "@/paginas/Consola";
import { Entrar } from "@/paginas/Entrar";
import { Estado } from "@/paginas/Estado";
import { Casos } from "@/paginas/Casos";
import { Conocimiento } from "@/paginas/Conocimiento";
import { ConsolaAgente } from "@/paginas/Consola.agente";
import { Cuadros } from "@/paginas/Cuadros";
import { Explotacion } from "@/paginas/Explotacion";
import { Marketing } from "@/paginas/Marketing";
import { Ficha } from "@/paginas/Ficha";
import { Inicio } from "@/paginas/Inicio";
import { Pipeline } from "@/paginas/Pipeline";
import { Modulo } from "@/paginas/Modulo";
import { Procesos } from "@/paginas/Procesos";
import { Recorrido } from "@/paginas/Recorrido";
import { Alm } from "@/paginas/Alm";
import { Ayuda } from "@/paginas/Ayuda";
import { Coste } from "@/paginas/Coste";
import { Inteligencia } from "@/paginas/Inteligencia";
import { Proveedores } from "@/paginas/Proveedores";
import { Puesto } from "@/paginas/Puesto";
import { Rendimiento } from "@/paginas/Rendimiento";
import { SuiteGobierno } from "@/paginas/Suite";
import { llamar } from "@/lib/api";
import { cargarSesion, type Sesion } from "@/lib/sesion";

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
    const reloj = window.setInterval(
      () => {
        void llamar("/api/v1/sesion/renovar", { metodo: "POST" }).catch(() => undefined);
      },
      MINUTOS_ENTRE_RENOVACIONES * 60_000,
    );
    return () => window.clearInterval(reloj);
  }, [sesion]);

  // Mientras no se sabe si hay sesión no se pinta ninguna de las dos cosas: ni
  // la pantalla de entrada —que haría parpadear un formulario a quien ya estaba
  // dentro— ni la aplicación, que pediría datos sin credencial.
  if (!resuelta) return <Cargando />;
  if (!sesion) return <Entrar alEntrar={refrescar} />;

  return (
    <Marco sesion={sesion}>
      <Routes>
        <Route path="/" element={<Inicio sesion={sesion} />} />
        <Route path="/administracion" element={<Consola sesion={sesion} />} />
        <Route path="/m/:ruta" element={<Modulo sesion={sesion} />} />
        {/* La cuenta tiene ficha propia: la genérica es un inspector de
            registros y con ella delante no se puede contestar «¿cómo vamos
            con este cliente?», que es para lo que se abre un CRM. */}
        <Route path="/m/cuentas/cuenta/:id" element={<Cuenta />} />
        <Route path="/m/:ruta/:tipo/:id" element={<Ficha />} />
        <Route path="/estado" element={<Estado />} />
        <Route path="/cobertura" element={<Cobertura />} />
        <Route path="/recorrido" element={<Recorrido />} />
        <Route path="/procesos" element={<Procesos />} />
        <Route path="/explotacion" element={<Explotacion />} />
        <Route path="/cuadros" element={<Cuadros />} />
        <Route path="/embudo" element={<Pipeline sesion={sesion} />} />
        <Route path="/casos" element={<Casos />} />
        <Route path="/consola-agente" element={<ConsolaAgente />} />
        <Route path="/conocimiento" element={<Conocimiento />} />
        <Route path="/marketing" element={<Marketing />} />
        <Route path="/proveedores" element={<Proveedores />} />
        <Route path="/coste" element={<Coste />} />
        <Route path="/inteligencia" element={<Inteligencia />} />
        <Route path="/puesto" element={<Puesto />} />
        <Route path="/alm" element={<Alm />} />
        <Route path="/rendimiento" element={<Rendimiento />} />
        <Route path="/suite" element={<SuiteGobierno />} />
        <Route path="/ayuda" element={<Ayuda />} />
      </Routes>
    </Marco>
  );
}
