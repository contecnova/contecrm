import { Suspense, lazy, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { Frontera } from "@/componentes/Frontera";
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
import { Aprobaciones } from "@/paginas/Aprobaciones";
import { Puesto } from "@/paginas/Puesto";
import { llamar } from "@/lib/api";
import { aplicarDensidad, densidadDelPerfil } from "@/lib/densidad";
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
const Portal = lazy(() => import("@/paginas/Portal").then((m) => ({ default: m.Portal })));
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

  // La densidad de quien ha entrado, **en cuanto se sabe quién es**.
  //
  // Después de la sesión y no en el arranque: antes de saber quién entra no hay
  // a quién preguntarle, y pedirla sin credencial devuelve un 401 que deja la
  // interfaz en el defecto para toda la visita.
  //
  // No se guarda nada aquí. Escribir el defecto «para tenerlo ya» le daría a
  // cada persona un valor propio idéntico al defecto, y el día que la empresa
  // cambiara el suyo no le cambiaría a nadie.
  useEffect(() => {
    if (!sesion) return;
    let vivo = true;
    void densidadDelPerfil().then((d) => {
      if (vivo) aplicarDensidad(d);
    });
    return () => {
      vivo = false;
    };
  }, [sesion]);

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
  // El portal va **antes** de todo, incluida la comprobación de sesión: quien
  // entra ahí es un cliente, no un empleado sin sesión, y mandarle a la
  // pantalla de entrada del CRM sería pedirle una credencial que no tiene ni
  // debe tener. Tampoco pasa por el marco: sin menú lateral ni paleta, porque
  // una interfaz que parece el CRM recortado invita a buscar lo que no está.
  if (window.location.pathname.startsWith("/portal")) {
    // Con su propio `Suspense`: el de las rutas vive dentro del marco, y aquí
    // no hay marco. Sin esto, React revienta al cargar la pantalla diferida.
    return (
      <Suspense fallback={<Cargando />}>
        <Portal />
      </Suspense>
    );
  }

  if (!resuelta) return <Cargando />;
  if (!sesion) return <Entrar alEntrar={refrescar} />;

  return (
    <Marco sesion={sesion}>
      {/* La frontera va DENTRO del marco: lo que se cae es el contenido de la
          pantalla, así que el menú y la barra siguen ahí y el usuario puede
          irse a otro sitio. Sin ella, un error al pintar cualquier pantalla
          dejaba el `<body>` vacío — ni mensaje, ni menú, ni forma de volver.
          Se midió el 04-10-2026 al montar las pruebas de pantalla. */}
      <Frontera clave={window.location.pathname}>
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
          <Route path="/aprobaciones" element={<Aprobaciones />} />
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
          {/* Atajos que la gente escribe. `/admin` es el que más: se teclea sin
              pensar y aquí la pantalla se llama `/administracion`. */}
          <Route path="/admin" element={<Navigate to="/administracion" replace />} />
          <Route path="/dashboard" element={<Navigate to="/cuadros" replace />} />
          <Route path="/informes" element={<Navigate to="/cuadros" replace />} />
          {/* Y CUALQUIER otra dirección dice que no existe.
              Sin esto, una dirección desconocida no daba error: dejaba la
              pantalla EN BLANCO, con un aviso en la consola del navegador que
              nadie mira. Es la peor forma de fallar — parece que la aplicación
              se ha roto, y no hay nada que leer ni a dónde ir. */}
          <Route path="*" element={<NoExiste />} />
          </Routes>
        </Suspense>
      </Frontera>
    </Marco>
  );
}


/**
 * Una dirección que no existe, dicha con todas las letras.
 *
 * Con el camino que se pidió delante: casi siempre es una errata o un enlace
 * viejo, y verlo escrito es lo que permite darse cuenta. Y con la salida a mano,
 * que es lo que evita que alguien cierre la pestaña.
 */
function NoExiste() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  return (
    <div className="p-4" role="alert">
      <h1 className="text-lg text-ink">{t("noExiste.titulo")}</h1>
      <p className="mt-2 max-w-prose text-2xs text-ink-muted">
        {t("noExiste.detalle")} <code className="font-mono text-ink">{pathname}</code>
      </p>
      <Link to="/" className="mt-4 inline-block text-2xs text-accent underline">
        {t("noExiste.volver")}
      </Link>
    </div>
  );
}
