import { Suspense, lazy, useCallback, useEffect, useState, type ComponentType } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { FronteraDeRuta } from "@/componentes/Frontera";
import { cargarTextosDePantallas } from "@/i18n";
import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { Marco } from "@/componentes/Marco";
import { Consola } from "@/paginas/Consola";
import { Entrar } from "@/paginas/Entrar";
import { Casos } from "@/paginas/Casos";
import { ConsolaAgente } from "@/paginas/Consola.agente";
import { Marketing } from "@/paginas/Marketing";
import { Inicio } from "@/paginas/Inicio";
import { Pipeline } from "@/paginas/Pipeline";
import { Procesos } from "@/paginas/Procesos";
import { Aprobaciones } from "@/paginas/Aprobaciones";
import { Puesto } from "@/paginas/Puesto";
import { llamar } from "@/lib/api";
import { aplicarDensidad, densidadDelPerfil } from "@/lib/densidad";
import { aplicarLocalizacion, aplicarMarcaDelTenant } from "@/lib/localizacion";
import { cargarEntrada, type Sesion } from "@/lib/sesion";

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
/**
 * Una pantalla diferida, con sus textos delante.
 *
 * El diccionario de las pantallas viaja en su propio trozo para no cargarlo al
 * abrir la aplicación, y se espera **antes** de resolver el componente: en
 * paralelo quedaría una ventana de milisegundos con la clave de traducción
 * escrita en la cabecera, que es el aspecto que tiene una interfaz rota.
 */
function pantalla<M, P>(cargar: () => Promise<M>, elegir: (modulo: M) => ComponentType<P>) {
  return lazy(async () => {
    const [modulo] = await Promise.all([cargar(), cargarTextosDePantallas()]);
    return { default: elegir(modulo) };
  });
}

const Portal = pantalla(
  () => import("@/paginas/Portal"),
  (m) => m.Portal,
);
const Cobertura = pantalla(
  () => import("@/paginas/Cobertura"),
  (m) => m.Cobertura,
);
const Estado = pantalla(
  () => import("@/paginas/Estado"),
  (m) => m.Estado,
);
const Recorrido = pantalla(
  () => import("@/paginas/Recorrido"),
  (m) => m.Recorrido,
);
const Alm = pantalla(
  () => import("@/paginas/Alm"),
  (m) => m.Alm,
);
const Ayuda = pantalla(
  () => import("@/paginas/Ayuda"),
  (m) => m.Ayuda,
);
const Inteligencia = pantalla(
  () => import("@/paginas/Inteligencia"),
  (m) => m.Inteligencia,
);
// Diferida: se entra a propósito, no al abrir la aplicación, y trae su propio
// bucle de vueltas. Cargarla con el marco engordaría lo que el navegador baja
// antes de pintar nada.
// Diferida: se entra desde calidad del dato, no al abrir la aplicación.
const Duplicados = pantalla(
  () => import("@/paginas/Duplicados"),
  (m) => m.Duplicados,
);
const Preguntar = pantalla(
  () => import("@/paginas/Preguntar"),
  (m) => m.Preguntar,
);
const Rendimiento = pantalla(
  () => import("@/paginas/Rendimiento"),
  (m) => m.Rendimiento,
);
const SuiteGobierno = pantalla(
  () => import("@/paginas/Suite"),
  (m) => m.SuiteGobierno,
);
const Explotacion = pantalla(
  () => import("@/paginas/Explotacion"),
  (m) => m.Explotacion,
);
const Cuadros = pantalla(
  () => import("@/paginas/Cuadros"),
  (m) => m.Cuadros,
);
const Coste = pantalla(
  () => import("@/paginas/Coste"),
  (m) => m.Coste,
);
const Conocimiento = pantalla(
  () => import("@/paginas/Conocimiento"),
  (m) => m.Conocimiento,
);
// Diferida como las demás pantallas de ruta: estática, entraba en el módulo
// de entrada y subía a 131 kB lo que se descarga antes de pintar nada, con un
// tope de 130. A una conversación se entra desde la cola, no al abrir.
const Conversacion = pantalla(
  () => import("@/paginas/Conversacion"),
  (m) => m.Conversacion,
);
const Seguridad = pantalla(
  () => import("@/paginas/Seguridad"),
  (m) => m.Seguridad,
);
// Diferida como el resto de las de administración: no la abre nadie al entrar,
// y cargarla con el marco engorda lo que el navegador descarga antes de pintar.
const Plataforma = pantalla(
  () => import("@/paginas/Plataforma"),
  (m) => m.Plataforma,
);
const ModuloInstalado = pantalla(
  () => import("@/paginas/ModuloInstalado"),
  (m) => m.ModuloInstalado,
);
const InstanciaDeProceso = pantalla(
  () => import("@/paginas/InstanciaDeProceso"),
  (m) => m.InstanciaDeProceso,
);
const SobreDeFirma = pantalla(
  () => import("@/paginas/SobreDeFirma"),
  (m) => m.SobreDeFirma,
);
const Caso = pantalla(() => import("@/paginas/Caso"), (m) => m.Caso);
const Liquidacion = pantalla(
  () => import("@/paginas/Liquidacion"),
  (m) => m.Liquidacion,
);
const Territorios = pantalla(
  () => import("@/paginas/Territorios"),
  (m) => m.Territorios,
);
const Segmento = pantalla(() => import("@/paginas/Segmento"), (m) => m.Segmento);
const PuntuacionDeLead = pantalla(
  () => import("@/paginas/PuntuacionDeLead"),
  (m) => m.PuntuacionDeLead,
);
const PeriodoDePrevision = pantalla(
  () => import("@/paginas/PeriodoDePrevision"),
  (m) => m.PeriodoDePrevision,
);
const Oportunidad = pantalla(
  () => import("@/paginas/Oportunidad"),
  (m) => m.Oportunidad,
);
const ObjetoDelModelo = pantalla(
  () => import("@/paginas/ObjetoDelModelo"),
  (m) => m.ObjetoDelModelo,
);
const PendienteDeFirma = pantalla(
  () => import("@/paginas/PendienteDeFirma"),
  (m) => m.PendienteDeFirma,
);
// La ficha de cliente trae las acciones y el formulario, y con ellos la tabla
// de pestañas. Diferida por lo mismo que las otras dos.
const Cuenta = pantalla(
  () => import("@/paginas/Cuenta"),
  (m) => m.Cuenta,
);
// Las dos que traen la tabla de pestañas (`recursos.ts`, 42 kB comprimidos).
// Diferidas, esa tabla deja de viajar en el paquete de apertura y llega cuando
// alguien abre un módulo — que es justo cuando hace falta.
const Modulo = pantalla(
  () => import("@/paginas/Modulo"),
  (m) => m.Modulo,
);
const Ficha = pantalla(
  () => import("@/paginas/Ficha"),
  (m) => m.Ficha,
);
const Chat = pantalla(
  () => import("@/paginas/Chat"),
  (m) => m.Chat,
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
  /**
   * Que no se ha podido ni preguntar quién entra.
   *
   * Es distinto de no haber entrado: antes se trataban igual y un 502 —el
   * gateway caído, el contenedor reiniciándose— salía como la pantalla de
   * entrada, invitando a teclear la contraseña en un sistema que no puede
   * contestar. Y al enviarla, otro error opaco.
   */
  const [caido, setCaido] = useState<unknown>(null);

  const refrescar = useCallback(() => {
    const control = new AbortController();
    cargarEntrada(control.signal).then((entrada) => {
      setSesion(entrada.estado === "dentro" ? entrada.sesion : null);
      setCaido(entrada.estado === "caido" ? entrada.error : null);
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
    // Y la marca y los formatos del TENANT, por lo mismo y en el mismo sitio:
    // hasta que no se sabe quién entra no hay a quién preguntárselos, y
    // pedirlos sin credencial devuelve un 401 que deja la interfaz con los del
    // despliegue para toda la visita.
    //
    // `config.json` sigue sirviendo para la pantalla de entrada, donde todavía
    // no se sabe de qué tenant es quien mira; esto se aplica encima.
    void aplicarMarcaDelTenant();
    void aplicarLocalizacion();
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
  // Primero lo caído: con el sistema sin responder, la pantalla de entrada
  // promete algo que no se puede hacer.
  if (caido) return <Fallo error={caido} reintentar={refrescar} />;
  if (!sesion) return <Entrar alEntrar={refrescar} />;

  return (
    <Marco sesion={sesion}>
      {/* La frontera va DENTRO del marco: lo que se cae es el contenido de la
          pantalla, así que el menú y la barra siguen ahí y el usuario puede
          irse a otro sitio. Sin ella, un error al pintar cualquier pantalla
          dejaba el `<body>` vacío — ni mensaje, ni menú, ni forma de volver.
          Se midió el 04-10-2026 al montar las pruebas de pantalla.

          La clave sale de `useLocation` y no de `window.location`: esto es la
          raíz y no se vuelve a pintar al navegar, así que con la ruta leída a
          mano la frontera se quedaba abierta y el error de una pantalla se
          veía en todas las demás. Medido el 29-10-2026. */}
      <FronteraDeRuta>
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
          {/* El objeto del modelo tiene pantalla propia, y no por capricho:
              sus rutas hijas se dirigen por NOMBRE —`/objetos/{nombre}/campos`—
              y la ficha genérica pasa el identificador, así que cada panel
              habría salido en 404. Ésta abre por identificador, lee el nombre
              y con él pide lo demás. */}
          {/* La oportunidad tiene ficha propia por lo mismo que el cliente:
              con un volcado de campos delante no se contesta «¿cómo vamos con
              esta venta?». Y tres de sus paneles leen rutas de OTRO prefijo
              —`/ingresos/…`, `/forecast/…`—, que la ficha genérica no
              descubre porque busca por prefijo común. */}
          <Route path="/m/oportunidades/oportunidad/:id" element={<Oportunidad />} />
          {/* Por CLAVE y no por identificador: las rutas hijas de un periodo
              —ajustes, fotos, desglose, deslizamiento— se dirigen por su
              clave, y pasarles el identificador las deja en 404. */}
          <Route
            path="/m/prevision/periodo/:clave"
            element={<PeriodoDePrevision />}
          />
          <Route path="/m/modelo/objeto/:id" element={<ObjetoDelModelo />} />
          {/* Una instancia de proceso tiene pantalla propia por lo mismo que
              el objeto del modelo: la ficha genérica enseña columnas —estado,
              paso actual— y la pregunta delante de un proceso parado es «¿por
              dónde va, qué pasó y cómo lo desatasco?». Además el gráfico
              necesita la definición de SU versión, que la ficha no pide. */}
          <Route
            path="/m/procesos/instancia/:id"
            element={<InstanciaDeProceso />}
          />
          {/* Por CLAVE y no por identificador: las rutas hijas de un módulo
              —integridad, telemetría— se dirigen por su clave, y pasarles el
              identificador las dejaría en 404, que es peor que no tenerlas. */}
          <Route path="/m/modelo/modulo/:clave" element={<ModuloInstalado />} />
          <Route path="/m/:ruta/:tipo/:id" element={<Ficha />} />
          <Route path="/estado" element={<Estado />} />
          <Route path="/seguridad" element={<Seguridad sesion={sesion} />} />
          <Route path="/plataforma" element={<Plataforma sesion={sesion} />} />
          <Route path="/cobertura" element={<Cobertura />} />
          <Route path="/chat" element={<Chat sesion={sesion} />} />
          <Route path="/recorrido" element={<Recorrido />} />
          <Route path="/territorios" element={<Territorios />} />
          {/* La liquidación tiene ficha propia: su detalle devuelve las
              líneas y las reclamaciones dentro del mismo objeto, y la ficha
              genérica descubre paneles por rutas hijas que aquí no existen. */}
          <Route path="/m/canal/liquidacion/:id" element={<Liquidacion />} />
          {/* El caso tiene ficha propia: su detalle trae en UNA llamada las
              relaciones, el árbol, el reloj y el historial, y la ficha
              genérica los pintaba como campos sueltos —seis UUID y un array—. */}
          <Route path="/m/casos/caso/:id" element={<Caso />} />
          {/* El sobre tiene ficha propia porque su EVIDENCIA devuelve un
              objeto, y la ficha genérica sólo descubre paneles que devuelven
              listas: pintarla como panel daría siempre «nada todavía». Y la
              evidencia es justo lo que hace defendible una firma. */}
          <Route path="/m/operacion/sobre_firma/:id" element={<SobreDeFirma />} />
          {/* El segmento tiene ficha propia porque sus tres preguntas no son
              paneles: el recuento devuelve un OBJETO —y la ficha genérica sólo
              descubre lo que devuelve listas—, el solapamiento cuelga del
              prefijo de la colección y se pide contra otro segmento, y
              congelar cambia la naturaleza del segmento. */}
          <Route path="/m/segmentos/segmento/:id" element={<Segmento />} />
          {/* La puntuación de un lead devuelve un objeto con sus dos ejes por
              separado: pintarla como campos sueltos los sumaría visualmente,
              que es justo lo que el modelo evita. */}
          <Route path="/m/segmentos/lead/:id/puntuacion" element={<PuntuacionDeLead />} />
          <Route path="/procesos" element={<Procesos />} />
          <Route path="/aprobaciones" element={<Aprobaciones />} />
          <Route path="/pendiente-de-firma" element={<PendienteDeFirma />} />
          <Route path="/explotacion" element={<Explotacion />} />
          <Route path="/cuadros" element={<Cuadros />} />
          <Route path="/embudo" element={<Pipeline sesion={sesion} />} />
          <Route path="/casos" element={<Casos />} />
          <Route path="/consola-agente" element={<ConsolaAgente />} />
          {/* La cola de la consola de agente enlazaba aquí desde el primer
              día y este módulo no existe: se llegaba a «no existe». */}
          <Route
            path="/m/conversaciones/conversacion/:id"
            element={<Conversacion sesion={sesion} />}
          />
          <Route path="/conocimiento" element={<Conocimiento />} />
          <Route path="/marketing" element={<Marketing />} />
          <Route path="/coste" element={<Coste />} />
          <Route path="/inteligencia" element={<Inteligencia />} />
          <Route path="/preguntar" element={<Preguntar />} />
          <Route path="/duplicados" element={<Duplicados />} />
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
      </FronteraDeRuta>
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
