/**
 * El marco de la aplicación (CRM-07.04.01.03).
 *
 * **Son dos marcos, no uno**, y es lo que cambió el 01-11-2026:
 *
 * - **Trabajando** no hay barra lateral. Arriba va la barra de la aplicación
 *   en la que estás —Ventas, Servicio, Marketing, Analítica— con sus
 *   pestañas, y a las demás se va por el lanzador. Es la forma de Salesforce
 *   y se copia a propósito: es la que ya conoce quien usa un CRM.
 * - **Configurando** sí hay árbol a la izquierda, porque ahí lo que se hace
 *   es recorrer una lista larga buscando un ajuste, que es justo para lo que
 *   sirve un árbol — y es también lo que hace Salesforce en su Setup.
 *
 * Lo de antes era un panel lateral con 29 entradas en el que «Cuentas y
 * contactos» y «Contrato de la API» estaban a la misma altura, y detrás 211
 * pestañas repartidas en 25 módulos. El panel no estaba mal construido: estaba
 * resolviendo el problema equivocado, que era enseñar cincuenta y nueve
 * destinos a la vez en lugar de poner delante los ocho de ahora mismo.
 *
 * El ámbito sale del CAMINO y no de un estado, igual que antes: un enlace
 * directo a una pantalla de configuración tiene que abrir el marco de
 * configuración, no el de trabajo con el menú equivocado marcado.
 */

import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import { useLocation, useNavigate } from "react-router-dom";

import { BarraDeAplicacion } from "@/componentes/BarraDeAplicacion";
import { BarraLateral } from "@/componentes/BarraLateral";
import { BarraSuperior } from "@/componentes/BarraSuperior";
import { llamar } from "@/lib/api";
import {
  aplicacionDelCamino,
  aplicacionRecordada,
  pestanasDe,
  pestanasDeTodas,
  recordarAplicacion,
  type Aplicacion,
} from "@/lib/aplicaciones";
import { grupoDelModulo, porGrupoVisible } from "@/lib/modulos";
import {
  ACCESOS,
  ambitoDelCamino,
  entradaVisible,
  menuDe,
  type Entrada,
} from "@/lib/navegacion";
import { ProveedorPanel } from "@/lib/panel";
import { ProveedorPermisos, useVisibilidad } from "@/lib/permisos";
import { volverASesionPropia, type Sesion } from "@/lib/sesion";

/**
 * La paleta se carga cuando se abre, no al arrancar.
 *
 * Es la única pieza del marco que NO se ve nunca hasta que alguien la pide —con
 * Ctrl+K o pulsando el buscador—, y arrastra el índice de pantallas entero. En
 * el paquete de apertura son 8 kB que nadie usa para mirar sus casos, y el tope
 * de apertura está para que ese tipo de peso se note. Al abrirla se descarga en
 * una petición que ya va en paralelo con lo que se está escribiendo.
 */
const Paleta = lazy(() =>
  import("@/componentes/Paleta").then((m) => ({ default: m.Paleta })),
);

/** Lo mismo que la paleta: no se ve hasta que alguien lo pide. */
const Lanzador = lazy(() =>
  import("@/componentes/LanzadorDeAplicaciones").then((m) => ({
    default: m.LanzadorDeAplicaciones,
  })),
);

export interface Props {
  sesion: Sesion | null;
  children: ReactNode;
}

export function Marco({ sesion, children }: Props) {
  const [paleta, setPaleta] = useState(false);

  const salir = useCallback(async () => {
    // Se recarga en vez de vaciar el estado: es la única forma de estar seguro
    // de que no queda nada del usuario anterior en memoria.
    await llamar("/api/v1/sesion/salir", { metodo: "POST" }).catch(
      () => undefined,
    );
    window.location.assign("/");
  }, []);

  // El atajo se escucha en la ventana y no en un campo: tiene que funcionar
  // esté donde esté el foco, que es justo lo que lo hace útil.
  useEffect(() => {
    function alTeclear(evento: KeyboardEvent) {
      if (
        (evento.metaKey || evento.ctrlKey) &&
        evento.key.toLowerCase() === "k"
      ) {
        evento.preventDefault();
        setPaleta((v) => !v);
      }
    }
    window.addEventListener("keydown", alTeclear);
    return () => window.removeEventListener("keydown", alTeclear);
  }, []);

  return (
    <ProveedorPanel>
      <ProveedorPermisos sesion={sesion}>
        <Armazon
          sesion={sesion}
          alSalir={() => void salir()}
          alAbrirPaleta={() => setPaleta(true)}
        >
          {children}
        </Armazon>

        {/* Sin `fallback` visible: mientras llega no hay nada que enseñar, y un
            esqueleto parpadeando encima de la pantalla es peor que esperar los
            milisegundos que tarda. */}
        {paleta ? (
          <Suspense fallback={null}>
            <Paleta abierta alCerrar={() => setPaleta(false)} sesion={sesion} />
          </Suspense>
        ) : null}
      </ProveedorPermisos>
    </ProveedorPanel>
  );
}

/**
 * El reparto de la pantalla, que depende de en qué ámbito estás.
 *
 * Va aparte de `Marco` porque necesita `useVisibilidad()`, y ese hook sólo
 * existe dentro del proveedor que monta `Marco`.
 */
function Armazon({
  sesion,
  alSalir,
  alAbrirPaleta,
  children,
}: {
  sesion: Sesion | null;
  alSalir: () => void;
  alAbrirPaleta: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const visibilidad = useVisibilidad();
  const [lanzador, setLanzador] = useState(false);

  const ambito = ambitoDelCamino(pathname, grupoDelModulo);
  const menu = useMemo(
    () =>
      menuDe(
        porGrupoVisible(sesion, visibilidad),
        (e) => entradaVisible(sesion, e),
        "trabajar",
      ),
    [sesion, visibilidad],
  );

  // La aplicación la manda el CAMINO cuando el camino pertenece a una. Sólo
  // cuando no —la portada, el chat, las menciones— manda la recordada: una
  // portada que cambia de aplicación según desde dónde llegues no deja saber
  // nunca en cuál estás.
  const navegar = useNavigate();
  const [elegida, setElegida] = useState<Aplicacion>(aplicacionRecordada);
  const delCamino = aplicacionDelCamino(pathname, menu);
  const aplicacion = delCamino ?? elegida;
  useEffect(() => {
    if (delCamino && delCamino.id !== elegida.id) {
      setElegida(delCamino);
      recordarAplicacion(delCamino);
    }
  }, [delCamino, elegida.id]);

  // «Inicio» y «Puesto» son pestaña de TODAS las aplicaciones: no son de un
  // dominio, son de donde se empieza el día. El chat y las menciones no, que
  // ya tienen su icono en la barra de arriba — ponerlos otra vez aquí sería lo
  // mismo en dos sitios.
  const cabecera = ACCESOS.filter(
    (e) => (e.a === "/" || e.a === "/puesto") && entradaVisible(sesion, e),
  );
  const pestanas: Entrada[] = [
    ...cabecera,
    ...pestanasDe(aplicacion, menu),
    // Y lo que es trabajo de todos: hoy las aprobaciones. Al final porque no
    // son el dominio de esta aplicación, pero presentes, porque se aprueba un
    // descuento, un contrato y un gasto desde el mismo sitio.
    ...pestanasDeTodas(menu),
  ];

  const configurando = ambito === "administrar";

  return (
    <div className="flex h-screen overflow-hidden bg-paper-dark">
      {/* Un salto al contenido es lo primero que necesita quien navega con
          teclado: sin él, cada página empieza por recorrer el menú entero. */}
      <a
        href="#contenido"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-focus-ring focus:rounded-lg focus:bg-accent focus:px-3 focus:py-2 focus:text-titulo focus:font-medium focus:text-paper focus:shadow-elevation-3"
      >
        {t("app.saltarAlContenido")}
      </a>

      {/* El árbol sólo en configuración. Es donde se recorre una lista larga
          buscando un ajuste, que es para lo que sirve un árbol; trabajando
          estorba, porque lo que se necesita son las ocho pantallas de ahora
          mismo y ésas caben arriba. */}
      {configurando ? <BarraLateral sesion={sesion} alSalir={alSalir} /> : null}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* La suplantación se dice SIEMPRE y en todas las pantallas. Un
            administrador que olvida que está viendo el CRM en nombre de otra
            persona toma decisiones sobre datos que no son los que cree. */}
        {sesion?.suplantado_por ? <FranjaDeSoporte sesion={sesion} /> : null}

        <BarraSuperior
          sesion={sesion}
          alSalir={alSalir}
          alAbrirPaleta={alAbrirPaleta}
          // Hay panel que plegar sólo donde se pinta el árbol, que es la misma
          // condición de tres líneas más abajo. Lo dice el marco porque es
          // quien decide si lo monta.
          conPanel={configurando}
        />

        {configurando ? null : (
          <BarraDeAplicacion
            aplicacion={aplicacion}
            pestanas={pestanas}
            alAbrirLanzador={() => setLanzador(true)}
          />
        )}

        <main id="contenido" className="min-h-0 flex-1 overflow-y-auto">
          <div className="contenido-pagina">{children}</div>
        </main>
      </div>

      {lanzador ? (
        <Suspense fallback={null}>
          <Lanzador
            menu={menu}
            actual={aplicacion}
            alElegirAplicacion={(app) => {
              setElegida(app);
              recordarAplicacion(app);
              setLanzador(false);
              // Y SE VA A ELLA. Elegir una aplicación y quedarse donde estabas
              // no se parece a nada: si la pantalla en la que estás pertenece a
              // otra, `aplicacion` la saca del camino —`delCamino ?? elegida`—
              // y tu elección **se ignora entera**; el efecto llegaba a verse
              // sólo desde la portada, el chat o las menciones, que no son de
              // ninguna. De ahí el «a veces funciona y a veces no», con una
              // regla que nadie puede adivinar mirando la pantalla.
              //
              // Lo dijo quien lo usa el 04-11-2026, y es lo que hace un
              // iniciador de aplicaciones: te lleva a la aplicación. Se entra
              // por su primera pestaña, salvo que ya estuvieras dentro.
              if (aplicacionDelCamino(pathname, menu)?.id === app.id) return;
              const primera = pestanasDe(app, menu)[0];
              if (primera) navegar(primera.a);
            }}
            alCerrar={() => setLanzador(false)}
          />
        </Suspense>
      ) : null}
    </div>
  );
}

/**
 * «Estás dentro como X por soporte: motivo», y el botón para salir
 * (CRM-00.01.02.06).
 *
 * Con nombre y motivo, no un aviso genérico: quien entra en la cuenta de otra
 * persona para un ticket tiene que ver EN CADA PANTALLA de quién es y para
 * qué, porque lo que se olvida a mitad de trabajo es exactamente eso.
 */
function FranjaDeSoporte({ sesion }: { sesion: Sesion }) {
  const { t } = useTranslation();
  const [saliendo, setSaliendo] = useState(false);
  const [fallo, setFallo] = useState(false);
  const datos = sesion.suplantacion;
  return (
    <div
      className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-warning px-4 py-1 text-center text-dato text-ink"
      role="status"
    >
      <span>
        {datos?.motivo
          ? t("app.suplantadoComo", {
              quien: sesion.nombre || sesion.email,
              motivo: datos.motivo,
            })
          : t("app.suplantado")}
      </span>
      {datos?.por_email ? (
        <span className="text-rotulo">
          {t("app.suplantadoPor", { soporte: datos.por_email })}
        </span>
      ) : null}
      <button
        type="button"
        className="rounded border border-ink/40 px-2 py-0.5 text-rotulo font-medium hover:bg-ink/10"
        disabled={saliendo}
        onClick={() => {
          setSaliendo(true);
          setFallo(false);
          volverASesionPropia().catch(() => {
            setSaliendo(false);
            setFallo(true);
          });
        }}
      >
        {t("app.salirDeSuplantacion")}
      </button>
      {fallo ? (
        <span className="text-rotulo">{t("app.salirDeSuplantacionFallo")}</span>
      ) : null}
    </div>
  );
}
