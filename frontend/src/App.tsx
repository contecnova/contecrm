import { useCallback, useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";

import { Cargando } from "@/componentes/Estados";
import { Marco } from "@/componentes/Marco";
import { Cobertura } from "@/paginas/Cobertura";
import { Consola } from "@/paginas/Consola";
import { Entrar } from "@/paginas/Entrar";
import { Estado } from "@/paginas/Estado";
import { Explotacion } from "@/paginas/Explotacion";
import { Ficha } from "@/paginas/Ficha";
import { Inicio } from "@/paginas/Inicio";
import { Modulo } from "@/paginas/Modulo";
import { Procesos } from "@/paginas/Procesos";
import { Recorrido } from "@/paginas/Recorrido";
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
        <Route path="/m/:ruta/:tipo/:id" element={<Ficha />} />
        <Route path="/estado" element={<Estado />} />
        <Route path="/cobertura" element={<Cobertura />} />
        <Route path="/recorrido" element={<Recorrido />} />
        <Route path="/procesos" element={<Procesos />} />
        <Route path="/explotacion" element={<Explotacion />} />
      </Routes>
    </Marco>
  );
}
