/**
 * La ficha de un cliente, con la forma que tiene en el mercado.
 *
 * Es donde se ven CRM-01.01.05.01 (la línea de tiempo unificada de todas las
 * interacciones), CRM-01.01.01.10 (el equipo de cuenta con sus roles),
 * CRM-01.01.02.02 (la relación contacto–cuenta con su rol y su vigencia),
 * CRM-01.01.05.06 (las métricas embebidas del cliente), CRM-01.01.01.02 y
 * CRM-01.01.01.03 (las jerarquías, y varias a la vez), CRM-01.01.04.07 (de
 * dónde sale cada valor), CRM-01.01.04.09 (qué lleva demasiado sin que nadie
 * lo confirme) y CRM-01.01.05.07 (la salud del cliente).
 *
 * **Las cuatro últimas son preguntas POR REGISTRO que la API contestaba y no
 * alcanzaba nadie.** El módulo de calidad del dato enseña la cola y los
 * agregados —qué hay que tocar hoy, si la cola crece—, que es otra pregunta:
 * delante de un cliente concreto lo que se quiere saber es por qué su
 * teléfono dice eso y no lo que dice el ERP.
 *
 * Salesforce y HubSpot llevan años convergiendo en el mismo reparto, y no por
 * copiarse: es lo que hace falta para trabajar con un cliente delante.
 *
 *   · Arriba, lo que identifica al cliente y **las acciones** que se hacen con
 *     él. Salesforce lo llama «highlights panel» y lo deja fijo al desplazar.
 *   · A la izquierda, los datos.
 *   · En el centro, **la línea de tiempo**: lo que ha pasado, en orden. Es la
 *     columna ancha porque es lo que se mira: quién llamó, qué se acordó, qué
 *     queda pendiente.
 *   · A la derecha, **lo relacionado**: contactos, oportunidades, casos.
 *
 * Lo que había antes era una ficha genérica que servía para cualquier objeto:
 * un volcado de campos y cuatro pestañas de adjuntos. Eso es un inspector de
 * registros, no la ficha de un cliente — con ella delante, un comercial no
 * puede contestar «¿cómo vamos con este cliente?», que es para lo que abre el
 * CRM.
 *
 * **Lo que no se sabe se dice.** Si la proyección de métricas no tiene el dato
 * de facturación, se escribe que no lo tiene: «cero incidencias» y «no tenemos
 * el dato de incidencias» se pintan igual y significan lo contrario.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  BotonesDeRegistro,
  ConfirmarBorrado,
  FormularioDeEdicion,
  useEdicion,
} from "@/componentes/Edicion";
import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { filas, llamar, salvoCancelacion, siguientePagina } from "@/lib/api";
import { Acciones } from "@/componentes/Acciones";
import { RegistrarActividad } from "@/componentes/RegistrarActividad";
import { SubColecciones } from "@/componentes/SubColecciones";
import { accionesDe, subColeccionesDe } from "@/lib/acciones";
import { escalar, humanizar, importe } from "@/lib/formato";
import { moduloDe, moduloDeObjeto } from "@/lib/modulos";
import { useSuperficie } from "@/lib/permisos";
import { recursoDe } from "@/lib/recursos";
import { cn } from "@/lib/utiles";

interface FuenteDeUnValor {
  fuente: string;
  valor: unknown;
  /** Cuál de las fuentes manda. Sin esto, una lista de valores no dice nada. */
  gana: boolean;
  cambio_el_valor: string | null;
  ultimo_mensaje: string;
  confianza: number;
}

interface Linaje {
  campos: Record<string, FuenteDeUnValor[]>;
  medible: boolean;
  que_significa: string;
}

interface Obsoletos {
  obsoletos: { campo: string; fuente: string; dias_sin_confirmar: number; tope: number }[];
  campos_con_linaje: string[];
  aviso: string;
}

interface RamaDeJerarquia {
  id: string;
  nombre: string;
  rol: string;
  hijos: RamaDeJerarquia[];
}

interface Arbol {
  id: string;
  nombre: string;
  jerarquia: string;
  hijos: RamaDeJerarquia[];
}

interface Salud {
  hay: boolean;
  porque?: string;
  que_hacer?: string;
  puntuacion?: number;
  nivel?: string;
  fiable?: boolean;
  vigente?: boolean;
  medida_hace_dias?: number;
  motivo?: string;
  /** Lo único que decide si este número se puede usar para algo. */
  sirve_para_actuar?: boolean;
  aviso?: string;
  de_donde_sale?: string;
}

interface Contacto360 {
  id: string;
  nombre: string;
  cargo: string | null;
  email: string | null;
  rol: string | null;
  principal: boolean;
  no_contactar: boolean;
}

interface Hito {
  tipo: string;
  asunto?: string;
  titulo?: string;
  momento?: string;
  fecha?: string;
  created_at?: string;
  [k: string]: unknown;
}

interface Metrica {
  clave: string;
  valor: string;
  unidad: string;
  moneda?: string | null;
  de_hace_dias: number;
  fresca: boolean;
  origen: string;
}

interface Vista360 {
  cuenta: {
    id: string;
    nombre: string;
    estado: string;
    roles: string[];
    sector: { esquema: string | null; codigo: string | null };
    calidad: { puntuacion: number; faltan: string[] };
    owner_id: string | null;
  };
  identificadores: { tipo: string; valor: string; verificado?: boolean }[];
  direcciones: Record<string, unknown>[];
  contactos: Contacto360[];
  timeline: Hito[];
  metricas: {
    metricas?: Metrica[];
    sin_dato?: string[];
    caducadas?: string[];
    completo?: boolean;
    que_significa?: string;
  };
}

/**
 * Lo que la vista 360 devuelve de línea de tiempo.
 *
 * No es un gusto de esta pantalla: lo decide el servidor
 * (`servicio.vista_360`, `limite=20`). Está aquí para poder DECIR que la lista
 * viene cortada; si el servidor cambiara el suyo, lo que pasaría es que el
 * aviso saldría antes de tiempo, no que se escondiera nada.
 */
const TOPE_DEL_360 = 20;

/**
 * A partir de cuántas filas —entre la línea de tiempo y los tres paneles— se
 * acota la ficha a una pantalla.
 *
 * Hace falta el umbral porque las dos formas de acotar fallan en el caso
 * contrario, y las dos se probaron:
 *
 *   · con un alto DEFINIDO siempre, un cliente recién creado enseñaba un
 *     recuadro vacío de pantalla entera;
 *   · con un MÁXIMO siempre, la rejilla no comprime sus filas —`max-height`
 *     acota el contenedor, no la fila— así que con mucha cola el contenido se
 *     salía por abajo y se pintaba encima de lo que hubiera debajo. Es lo que
 *     se vio en la ficha de un proveedor con veinte reuniones.
 *
 * Así que el alto se fija sólo cuando hay de qué: por debajo, la ficha mide lo
 * que mide su contenido y no hay nada que acotar.
 */
const FILAS_PARA_ACOTAR = 12;

interface Oportunidad {
  id: string;
  nombre: string;
  importe: string | number;
  moneda: string;
  estado: string;
  fecha_cierre: string | null;
}

interface Caso {
  id: string;
  codigo: string | null;
  asunto: string;
  estado: string;
  prioridad: string;
}

export function Cuenta() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [vista, setVista] = useState<Vista360 | null>(null);
  const [oportunidades, setOportunidades] = useState<Oportunidad[]>([]);
  const [casos, setCasos] = useState<Caso[]>([]);
  /**
   * Si la lista viene recortada.
   *
   * El panel enseñaba `oportunidades.length` como si fuera el total, y se pide
   * con `limite=20`: un cliente con doscientas oportunidades ponía «20» y se
   * leía como «tiene veinte». Una lista recortada que parece completa es peor
   * que una lista larga. El servidor ya lo dice —devuelve cursor cuando hay
   * más— así que no hace falta contar nada.
   */
  const [hayMasOportunidades, setHayMasOportunidades] = useState(false);
  const [hayMasCasos, setHayMasCasos] = useState(false);
  // Lo que ha pasado se pide con tope, y se puede pedir más sin salir de aquí.
  const [masTimeline, setMasTimeline] = useState<
    Record<string, unknown>[] | null
  >(null);
  const [pidiendoMas, setPidiendoMas] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  /** De dónde sale cada valor de esta ficha, y qué lleva sin confirmarse. */
  const [linaje, setLinaje] = useState<Linaje | null>(null);
  const [obsoletos, setObsoletos] = useState<Obsoletos | null>(null);
  const [arbol, setArbol] = useState<Arbol | null>(null);
  const [salud, setSalud] = useState<Salud | null>(null);
  const { superficie, tiene } = useSuperficie();
  const navegar = useNavigate();
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  /**
   * El recurso de cuentas, el mismo que usa el listado y la ficha genérica.
   *
   * Se busca y no se escribe a mano para que la edición de un cliente pase por
   * la MISMA ruta y el mismo contrato que su listado: dos pantallas que enseñan
   * el mismo registro tienen que escribirlo igual, o una de las dos se queda
   * atrás el día que cambie el contrato.
   */
  const moduloCuentas = moduloDe("cuentas");
  const recurso = moduloCuentas
    ? recursoDe(moduloCuentas, "cuenta")
    : undefined;
  const { ruta, puedeEditar, puedeBorrar } = useEdicion(recurso, id);

  const cargar = useCallback(
    (signal?: AbortSignal) => {
      llamar<Vista360>(`/api/v1/accounts/${id}/360`, { signal })
        .then((r) => setVista(r.datos))
        .catch(salvoCancelacion(setFallo));

      // Las cuatro preguntas de calidad del dato de ESTE cliente. Cada una con
      // su propio fallo: que no haya linaje no puede dejar sin ver la ficha.
      void llamar<Linaje>(`/api/v1/calidad-dato/linaje/cuenta/${id}`, { signal })
        .then((r) => setLinaje(r.datos))
        .catch(() => undefined);
      void llamar<Obsoletos>(`/api/v1/calidad-dato/obsoletos/cuenta/${id}`, { signal })
        .then((r) => setObsoletos(r.datos))
        .catch(() => undefined);
      void llamar<Arbol>(`/api/v1/accounts/${id}/jerarquia`, { signal })
        .then((r) => setArbol(r.datos))
        .catch(() => undefined);
      void llamar<Salud>(`/api/v1/calidad-dato/salud/${id}`, { signal })
        .then((r) => setSalud(r.datos))
        .catch(() => undefined);
      // Oportunidades y casos viven en otros servicios: se piden aparte y **su
      // fallo no tumba la ficha**. Que no responda soporte no puede dejar sin
      // ver los datos del cliente.
      // `estado=` vacío a propósito: la API filtra por abiertas de serie, y en
      // la ficha de un cliente eso esconde justo lo que se ganó con él. «Cómo
      // vamos con este cliente» incluye lo cerrado.
      llamar<unknown>(
        `/api/v1/opportunities?cuenta_id=${id}&estado=&limite=20`,
        { signal },
      )
        .then((r) => {
          setOportunidades(filas<Oportunidad>(r.datos));
          setHayMasOportunidades(Boolean(siguientePagina(r.datos)));
        })
        .catch(() => undefined);
      llamar<unknown>(`/api/v1/casos?cuenta_id=${id}&limite=20`, { signal })
        .then((r) => {
          setCasos(filas<Caso>(r.datos));
          setHayMasCasos(Boolean(siguientePagina(r.datos)));
        })
        .catch(() => undefined);
    },
    [id],
  );

  useEffect(() => {
    const control = new AbortController();
    cargar(control.signal);
    return () => control.abort();
  }, [cargar]);

  // Al cambiar de cliente se sale de edición y se cancela la confirmación: esta
  // pantalla no se desmonta al ir de una ficha a otra, y sin esto el «¿seguro
  // que quieres eliminar?» a medias quedaría apuntando al cliente nuevo.
  useEffect(() => {
    setEditando(false);
    setConfirmando(false);
  }, [id]);

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      // Se vuelve al listado: quedarse en la ficha de algo que ya no existe
      // enseña un cliente fantasma hasta que alguien recargue.
      navegar("/m/cuentas");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo) return <Fallo error={fallo} reintentar={() => cargar()} />;
  if (!vista) return <Cargando />;

  // Fusionar duplicados, verificar un identificador, geocodificar, dar de alta
  // en el equipo de cuenta… todo lo que el servidor admite hacer con un
  // cliente, sin escribir un botón por acción.
  const acciones = accionesDe(superficie, "/api/v1/accounts", id, tiene);
  const paneles = subColeccionesDe(superficie, "/api/v1/accounts", id, tiene);
  // Lo que cuelga de la cuenta **por ser proveedora**: homologaciones por
  // categoría, documentos con vigencia, sus contactos. Sale de la superficie
  // igual que el resto, así que no hay que enumerarlo aquí ni mantenerlo.
  const panelesProveedor = subColeccionesDe(
    superficie,
    "/api/v1/proveedores",
    id,
    tiene,
  );

  const { cuenta, contactos, identificadores, metricas } = vista;
  /**
   * A dónde lleva «ver todas» en cada panel.
   *
   * Derivado del catálogo y no escrito a mano: si el módulo cambia de camino,
   * un enlace a mano lleva a «no existe» y nadie se entera hasta que alguien
   * lo pulsa. Vacío si el objeto no vive en ningún módulo, y entonces el panel
   * no enseña el enlace en vez de llevar a una pantalla que no hay.
   */
  const verTodasDe = (objeto: string) => {
    const ruta = moduloDeObjeto(objeto);
    if (!ruta) return undefined;
    // Y la PESTAÑA, no sólo el módulo. Los contactos viven dentro del módulo
    // de cuentas: sin `?r=`, «ver todas» de contactos abría el listado de
    // cuentas —que es el que sale primero— y parecía que el enlace estaba mal
    // puesto. El nombre sale del catálogo, que es quien lo decide.
    const modulo = moduloDe(ruta);
    const recurso = modulo ? recursoDe(modulo, objeto) : undefined;
    const pestana = recurso ? `r=${encodeURIComponent(recurso.nombre)}&` : "";
    return `/m/${ruta}?${pestana}cuenta_id=${id}`;
  };
  // La 360 trae los últimos 20 hitos. Si se han pedido más, mandan ésos.
  const timeline = (masTimeline ?? vista.timeline) as Hito[];
  // Exactamente 20 es la señal de que puede haber más: el servidor corta ahí.
  const puedeHaberMas =
    masTimeline === null && vista.timeline.length >= TOPE_DEL_360;
  // Todos los que haya: los que no caben se alcanzan con la barra de la caja.
  // Recortarlos aquí dejaría la caja medio vacía en una pantalla alta, que es
  // justo lo que se intentó antes y quedaba peor.
  const alaVista = timeline;
  // Si hay poco que enseñar no se acota nada: la ficha mide lo suyo. Ver la
  // nota de `FILAS_PARA_ACOTAR`, que explica por qué no vale ni acotar siempre
  // ni no acotar nunca.
  const hayCola =
    timeline.length + contactos.length + oportunidades.length + casos.length >=
    FILAS_PARA_ACOTAR;
  const nif = identificadores.find((i) => i.tipo === "nif")?.valor;

  return (
    <>
      <CabeceraPagina
        titulo={cuenta.nombre}
        icono="domain"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <span className="badge badge-muted">{cuenta.estado}</span>
            {cuenta.roles.map((r) => (
              <span key={r} className="chip-dato chip-dato--si">
                {r}
              </span>
            ))}
            {nif ? (
              <span className="text-2xs text-ink-faint">{nif}</span>
            ) : null}
          </span>
        }
        acciones={
          <>
            <Link
              to={`/m/oportunidades?r=Oportunidades&nuevo=1`}
              className="btn-primary"
            >
              {t("cuenta.nuevaOportunidad")}
            </Link>
          </>
        }
      />

      {/* Editar y borrar van ANTES que las acciones de negocio: lo primero
          que se busca en una ficha abierta es cambiar un dato que está mal, y
          esta pantalla no lo ofrecía en ningún punto aunque el servidor lo
          admitiera. */}
      {!editando ? (
        <div className="mb-3">
          <BotonesDeRegistro
            puedeEditar={puedeEditar}
            puedeBorrar={puedeBorrar}
            alEditar={() => setEditando(true)}
            alBorrar={() => setConfirmando(true)}
          />
        </div>
      ) : null}

      {confirmando ? (
        <ConfirmarBorrado
          enviando={borrando}
          alBorrar={() => void borrar()}
          alCancelar={() => setConfirmando(false)}
        />
      ) : null}

      {editando && recurso ? (
        <FormularioDeEdicion
          recurso={recurso}
          ruta={ruta}
          valores={cuenta as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      <Acciones
        acciones={acciones}
        servicio="party"
        alTerminar={() => cargar()}
      />

      {/* Las tres columnas acaban a la MISMA altura, y dentro de cada una las
          cajas se reparten el alto disponible. Cada caja recorre lo suyo.

          Dos intentos antes, los dos mal, y los dos están aquí para que no se
          vuelvan a probar:

            · una barra por COLUMNA: una sola barra corriendo por el lateral de
              tres tarjetas no dice a cuál pertenece, y al arrastrarla se mueve
              lo que no se está mirando;
            · un número FIJO de filas por caja y sin barras: la caja del centro
              se estiraba hasta el alto de la fila de la rejilla y quedaba
              medio vacía, con el contenido arriba y un desierto debajo.

            · un alto FIJO de una pantalla: con un cliente recién creado —sin
              actividad, sin contactos, sin oportunidades y sin casos— la caja
              del centro era un recuadro vacío de pantalla entera. El tope
              tiene que ser un MÁXIMO, no una altura: con poco que enseñar, la
              ficha mide lo que mide su contenido.

          Lo que cuadra es esto: la rejilla no pasa de una pantalla, cada
          columna reparte su alto entre sus cajas y cada caja recorre su lista.
          Cuántas filas se ven no lo decide una constante: lo decide el alto que
          hay, que es lo que hace que cuadre en cualquier pantalla.

          **Sólo de `lg` para arriba.** En un móvil hay una sola columna y una
          barra dentro de otra es peor que el problema: el dedo no sabe cuál de
          las dos está moviendo. Ahí se desplaza la página. */}
      <div
        className={cn(
          "grid gap-4 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)_minmax(0,19rem)]",
          hayCola && "lg:h-[calc(100vh-15rem)]",
        )}
      >
        {/* ── Datos ──────────────────────────────────────────────────── */}
        <aside className="space-y-4 lg:min-h-0 lg:overflow-y-auto lg:pr-1">
          <section className="card p-4">
            <h2 className="section-label mb-3">{t("cuenta.datos")}</h2>
            <dl className="space-y-2">
              <Dato clave="sector" valor={cuenta.sector.codigo} />
              <Dato clave="estado" valor={cuenta.estado} />
              {identificadores.map((i) => (
                <Dato key={i.valor} clave={i.tipo} valor={i.valor} />
              ))}
            </dl>
          </section>

          <section className="card p-4">
            <h2 className="section-label mb-2">{t("cuenta.calidad")}</h2>
            <p className="text-sm font-medium text-ink">
              {cuenta.calidad.puntuacion} / 100
            </p>
            {cuenta.calidad.faltan.length > 0 ? (
              <>
                {/* Qué falta, por su nombre. Una puntuación sin el detalle no
                    dice qué hay que hacer para subirla. */}
                <p className="mt-2 text-3xs text-ink-faint">
                  {t("cuenta.faltan")}
                </p>
                <ul className="mt-1 flex flex-wrap gap-1">
                  {cuenta.calidad.faltan.map((f) => (
                    <li key={f} className="chip-dato">
                      {humanizar(f)}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </section>

          <section className="card p-4">
            <h2 className="section-label mb-2">{t("cuenta.metricas")}</h2>
            <Metricas datos={metricas} />
          </section>
        </aside>

        {/* ── Lo que ha pasado ───────────────────────────────────────── */}
        <section
          className="card flex flex-col overflow-hidden p-4 lg:min-h-0"
          aria-labelledby="cuenta-timeline"
        >
          <h2 id="cuenta-timeline" className="section-label mb-3">
            {t("cuenta.timeline")}
          </h2>

          {/* Apuntar va ARRIBA de la línea de tiempo, no en otra pantalla: se
              apunta justo después de hablar con el cliente, mirándolo. */}
          <RegistrarActividad
            objeto="cuenta"
            objetoId={id}
            alRegistrar={() => cargar()}
          />
          {timeline.length === 0 ? (
            <Vacio compacto icono="history" titulo={t("cuenta.sinTimeline")} />
          ) : (
            <ol className="relative space-y-4 overflow-y-auto border-l border-ink-dim/60 pl-4 lg:min-h-0 lg:flex-1">
              {alaVista.map((h, i) => (
                <li key={i} className="relative">
                  <span
                    aria-hidden
                    className="absolute -left-[1.4rem] top-1.5 h-2 w-2 rounded-full bg-accent"
                  />
                  <p className="text-xs text-ink">
                    {String(h.asunto ?? h.titulo ?? h.tipo ?? "")}
                  </p>
                  <p className="mt-0.5 text-3xs text-ink-faint">
                    {humanizar(String(h.tipo ?? ""))}
                    {h.momento || h.fecha || h.created_at
                      ? ` · ${escalar(h.momento ?? h.fecha ?? h.created_at)}`
                      : ""}
                  </p>
                </li>
              ))}
            </ol>
          )}
          {/* El tope del servidor, dicho y con salida. Veinte hitos en una
              cuenta activa son los de esta semana: sin esto, la línea de
              tiempo se lee como «esto es todo lo que ha pasado». */}
          {/* Región que se anuncia: al pulsar «ver todo lo que ha pasado»
              aparecen hitos más arriba de donde está el foco, y quien no ve la
              pantalla no se enteraría de que ha pasado algo. Dice cuántos hay
              delante, que es el dato que cambia. */}
          <div role="status" aria-live="polite">
            {masTimeline ? (
              <p className="mt-3 border-t border-ink-dim/30 pt-2 text-3xs text-ink-faint">
                {t("cuenta.timelineEntera", { cuantos: timeline.length })}
              </p>
            ) : null}
            {puedeHaberMas ? (
              <p className="mt-3 border-t border-ink-dim/30 pt-2 text-3xs text-ink-faint">
                {t("cuenta.timelineRecortada", { cuantos: TOPE_DEL_360 })}{" "}
                <button
                  type="button"
                  className="btn-link"
                  disabled={pidiendoMas}
                  onClick={() => {
                    setPidiendoMas(true);
                    void llamar<unknown>(
                      `/api/v1/accounts/${id}/timeline?limite=200`,
                    )
                      .then((r) =>
                        setMasTimeline(filas<Record<string, unknown>>(r.datos)),
                      )
                      .catch(() => undefined)
                      .finally(() => setPidiendoMas(false));
                  }}
                >
                  {pidiendoMas
                    ? t("cuenta.cargandoMas")
                    : t("cuenta.verTodoLoQuePaso")}
                </button>
              </p>
            ) : null}
          </div>
        </section>

        {/* ── Lo relacionado ─────────────────────────────────────────── */}
        <aside className="flex flex-col gap-4 lg:min-h-0">
          <Relacionados
            titulo={t("cuenta.contactos")}
            icono="person"
            vacio={t("cuenta.sinContactos")}
            cuantos={contactos.length}
            verTodas={verTodasDe("contacto")}
          >
            {contactos.map((c) => (
              <li key={c.id} className="py-1.5">
                <p className="truncate text-xs text-ink">{c.nombre}</p>
                <p className="truncate text-3xs text-ink-faint">
                  {[c.cargo, c.email].filter(Boolean).join(" · ") || "—"}
                </p>
                {c.no_contactar ? (
                  <span className="badge badge-warning mt-1">
                    {t("cuenta.noContactar")}
                  </span>
                ) : null}
              </li>
            ))}
          </Relacionados>

          <Relacionados
            titulo={t("cuenta.oportunidades")}
            icono="trending_up"
            vacio={t("cuenta.sinOportunidades")}
            cuantos={oportunidades.length}
            hayMas={hayMasOportunidades}
            verTodas={verTodasDe("oportunidad")}
          >
            {oportunidades.map((o) => (
              <li key={o.id} className="py-1.5">
                <Link
                  to={`/m/oportunidades/oportunidad/${o.id}`}
                  className="block truncate text-xs text-accent hover:underline"
                >
                  {o.nombre}
                </Link>
                <p className="flex items-center gap-1.5 text-3xs text-ink-faint">
                  {importe(o.importe, o.moneda)}
                  <span
                    className={
                      o.estado === "ganada"
                        ? "badge badge-success"
                        : o.estado === "perdida"
                          ? "badge badge-danger"
                          : "badge badge-muted"
                    }
                  >
                    {o.estado}
                  </span>
                </p>
              </li>
            ))}
          </Relacionados>

          <Relacionados
            titulo={t("cuenta.casos")}
            icono="confirmation_number"
            vacio={t("cuenta.sinCasos")}
            cuantos={casos.length}
            hayMas={hayMasCasos}
            verTodas={verTodasDe("caso")}
          >
            {casos.map((c) => (
              <li key={c.id} className="py-1.5">
                <p className="truncate text-xs text-ink">{c.asunto}</p>
                <p className="text-3xs text-ink-faint">
                  {[c.codigo, c.estado, c.prioridad]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </li>
            ))}
          </Relacionados>
        </aside>
      </div>

      {/* ── De qué grupo es, de dónde salen sus datos y cómo está ──────
          Cuatro preguntas POR REGISTRO que la API contestaba y no alcanzaba
          nadie. El módulo de calidad del dato enseña la cola y los agregados
          —qué hay que tocar hoy, si la cola crece—, que es otra pregunta:
          delante de un cliente concreto lo que se quiere saber es por qué su
          teléfono dice eso y no lo que dice el ERP. */}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <LaJerarquia arbol={arbol} />
        <LaSalud salud={salud} />
        <DeDondeSaleCadaDato linaje={linaje} />
        <LoQueLlevaSinConfirmarse obsoletos={obsoletos} />
      </div>

      {/* Direcciones, identificadores fiscales, equipo de cuenta, relaciones
          entre empresas: todo lo que cuelga del cliente, con sus altas y sus
          acciones. */}
      <SubColecciones paneles={paneles} servicio="party" id={id} />

      {/* Y si además es proveedora, lo suyo — en esta misma ficha y no en otra
          parecida: es la misma empresa, y tenerla en dos sitios obliga a saber
          en cuál mirar. */}
      {cuenta.roles.includes("proveedor") ? (
        <SubColecciones paneles={panelesProveedor} servicio="party" id={id} />
      ) : null}
    </>
  );
}

function Dato({ clave, valor }: { clave: string; valor: unknown }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-3xs text-ink-faint">{humanizar(clave)}</dt>
      <dd className="truncate text-2xs text-ink">
        {valor ? (
          escalar(valor, clave)
        ) : (
          <span className="text-ink-faint">{t("cuenta.sinDato")}</span>
        )}
      </dd>
    </div>
  );
}

function Relacionados({
  titulo,
  icono,
  vacio,
  cuantos,
  hayMas = false,
  verTodas,
  children,
}: {
  titulo: string;
  icono: string;
  vacio: string;
  cuantos: number;
  /** La lista viene recortada: hay más de las que se enseñan. */
  hayMas?: boolean;
  /** A dónde ir a verlas todas. Sólo se pinta si `hayMas`. */
  verTodas?: string;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <section className="card flex flex-col overflow-hidden p-4 lg:min-h-0 lg:max-h-max lg:flex-1 lg:basis-0">
      <h2 className="section-label mb-2 flex shrink-0 items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5">
          <Icono nombre={icono} tamano="sm" />
          {titulo}
        </span>
        {/* «20+» y no «20» cuando viene recortada. Una lista recortada que
            parece completa se lee como «este cliente tiene veinte casos»
            cuando puede tener doscientos, y esa lectura cambia decisiones. El
            servidor ya lo dice —devuelve cursor cuando hay más—, así que no
            hace falta contar nada. */}
        <span className="text-ink-faint">
          {cuantos}
          {hayMas ? "+" : ""}
        </span>
      </h2>
      {/* El reparto del alto de la columna, que es lo que decide cuántas filas
          se ven en cada caja:

            · `flex-1 basis-0` → todas parten de cero y se reparten el alto a
              PARTES IGUALES. Sin esto el encogido es proporcional a lo que
              cada una mide, así que la caja de tres contactos se quedaba sin
              una sola fila mientras la de veinte casos enseñaba siete;
            · `max-h-max` → pero ninguna coge más de lo que necesita. La de
              tres contactos se queda en tres filas y el hueco que le sobra se
              reparte entre las que sí tienen cola.

          O sea: unas cuantas de cada una, y nada de espacio vacío. */}
      {cuantos === 0 ? (
        <p className="py-2 text-3xs text-ink-faint">{vacio}</p>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          {/* La barra, en la caja, y la lista es lo ÚNICO que crece y se
              recorta: el rótulo y el pie no. Cuántas filas se ven lo decide el
              alto que la columna le ha repartido, no una constante, así que
              cuadra igual en un portátil que en una pantalla de 27 pulgadas.
              Tenía aquí un `min-h` y era un error: cuando la columna encogía
              la caja por debajo de ese mínimo, la lista se salía por el borde
              y se pintaba ENCIMA de la tarjeta de abajo. Lo que acota es el
              `overflow-hidden` de la caja, no un mínimo. */}
          <ul className="min-h-0 flex-1 divide-y divide-ink-dim/30 overflow-y-auto">
            {children}
          </ul>
          {/* Siempre que haya a dónde ir, no sólo cuando la lista viene
              recortada: si un panel lo ofrece y el de al lado no, quien lo usa
              no sabe si es que no se puede o es que no hay más. Y aun con
              nueve filas se quiere ir al listado entero, a filtrar o a
              ordenar por otra cosa. */}
          {verTodas ? (
            <p className="mt-2 shrink-0 border-t border-ink-dim/30 pt-2 text-3xs">
              <Link to={verTodas} className="text-accent hover:underline">
                {t("cuenta.verTodas")}
              </Link>
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}

/**
 * Las métricas, distinguiendo el cero del «no lo sé».
 *
 * «Cero incidencias» y «no tenemos el dato de incidencias» se pintan igual en
 * un panel y significan lo contrario: uno es un cliente tranquilo y el otro una
 * integración caída. El servidor ya los separa; aquí se respeta.
 */
function Metricas({ datos }: { datos: Vista360["metricas"] }) {
  const { t } = useTranslation();
  const metricas = datos.metricas ?? [];
  const sinDato = datos.sin_dato ?? [];

  if (metricas.length === 0 && sinDato.length === 0) {
    return <p className="text-3xs text-ink-faint">{t("cuenta.sinMetricas")}</p>;
  }
  return (
    <>
      <dl className="space-y-2">
        {metricas.map((m) => (
          <div
            key={m.clave}
            className="flex items-baseline justify-between gap-3"
          >
            <dt className="shrink-0 text-3xs text-ink-faint">
              {humanizar(m.clave)}
            </dt>
            <dd className="truncate text-2xs text-ink">
              {m.unidad === "moneda"
                ? importe(m.valor, m.moneda ?? "EUR")
                : escalar(m.valor)}
              {m.fresca ? null : (
                <span
                  className="ml-1 text-3xs text-warning"
                  title={t("cuenta.caducada")}
                >
                  ({t("cuenta.deHace", { dias: m.de_hace_dias })})
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {sinDato.length > 0 ? (
        <p className="mt-3 text-3xs text-ink-faint">
          {t("cuenta.sinDatoDe", {
            metricas: sinDato.map(humanizar).join(", "),
          })}
        </p>
      ) : null}
    </>
  );
}


/**
 * De qué grupo forma parte (CRM-01.01.01.02, CRM-01.01.01.03).
 *
 * **Y en qué jerarquía**, porque son varias a la vez: la legal no es la
 * comercial ni la de facturación. Una empresa puede depender de la matriz
 * francesa para firmar y de la delegación de aquí para que la atiendan, y
 * enseñar una sola haría que la otra pareciera un error.
 */
function LaJerarquia({ arbol }: { arbol: Arbol | null }) {
  const { t } = useTranslation();
  // Sin `hijos` no se asume lista vacía por comodidad: un panel que lee
  // `.length` de algo que no llegó tumba la ficha ENTERA, y eso convierte un
  // campo que falta en una pantalla en blanco. Es el fallo más caro de los
  // que no fallan: no hay error, no hay traza, no hay nada.
  if (!arbol) return null;
  const ramas = arbol.hijos ?? [];

  function pintar(ramas: RamaDeJerarquia[], nivel: number) {
    return ramas.map((r) => (
      <li key={r.id} style={{ paddingLeft: nivel * 12 }}>
        <div className="flex flex-wrap items-baseline gap-x-2 py-1 text-2xs">
          <Link to={`/m/cuentas/cuenta/${r.id}`} className="text-ink hover:underline">
            {r.nombre}
          </Link>
          {r.rol ? <span className="chip-dato">{r.rol}</span> : null}
        </div>
        {r.hijos?.length ? (
          <ul>{pintar(r.hijos ?? [], nivel + 1)}</ul>
        ) : null}
      </li>
    ));
  }

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("cuenta.jerarquia")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">
        {t("cuenta.jerarquiaAyuda", { cual: arbol.jerarquia })}
      </p>
      {ramas.length ? (
        <ul>
          <li className="text-2xs font-medium text-ink">{arbol.nombre}</li>
          {pintar(ramas, 1)}
        </ul>
      ) : (
        <Vacio titulo={t("cuenta.sinJerarquia")} compacto />
      )}
    </section>
  );
}

/**
 * La salud del cliente (CRM-01.01.05.07).
 *
 * **Con `sirve_para_actuar` delante de la puntuación.** Un número que no es
 * fiable o que se midió hace tres meses no puede mover una decisión, y
 * pintarlo igual que uno bueno es lo que hace que nadie se crea ninguno. La
 * puntuación va DESPUÉS del veredicto a propósito.
 */
function LaSalud({ salud }: { salud: Salud | null }) {
  const { t } = useTranslation();
  if (!salud) return null;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("cuenta.salud")}</h2>
      {!salud.hay ? (
        <>
          <p className="text-2xs text-ink-muted">{salud.porque}</p>
          {salud.que_hacer ? (
            <p className="mt-1 text-3xs text-ink-faint">{salud.que_hacer}</p>
          ) : null}
        </>
      ) : (
        <>
          <p
            className={
              salud.sirve_para_actuar
                ? "text-2xs text-success"
                : "text-2xs text-warning"
            }
          >
            {salud.sirve_para_actuar
              ? t("cuenta.saludSirve")
              : t("cuenta.saludNoSirve")}
          </p>
          <p className="mt-1 text-sm font-medium text-ink">
            {t("cuenta.saludPuntuacion", {
              puntuacion: salud.puntuacion,
              nivel: salud.nivel,
            })}
          </p>
          <p className="mt-1 text-3xs text-ink-muted">
            {t("cuenta.saludMedida", { dias: salud.medida_hace_dias })}
          </p>
          {salud.motivo ? (
            <p className="mt-1 text-3xs text-ink-muted">{salud.motivo}</p>
          ) : null}
          {salud.aviso ? (
            <p className="mt-1 text-3xs text-warning">{salud.aviso}</p>
          ) : null}
        </>
      )}
    </section>
  );
}

/**
 * De dónde sale cada valor (CRM-01.01.04.07).
 *
 * Contesta «¿por qué pone esto si el ERP dice otra cosa?», que hoy se contesta
 * preguntando a quien montó la integración. Cada campo con sus fuentes, **cuál
 * gana** y con qué confianza: sin el «gana», una lista de valores distintos no
 * dice cuál se está usando.
 */
function DeDondeSaleCadaDato({ linaje }: { linaje: Linaje | null }) {
  const { t } = useTranslation();
  if (!linaje) return null;
  const campos = Object.entries(linaje.campos ?? {});

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("cuenta.linaje")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">{t("cuenta.linajeAyuda")}</p>
      {!linaje.medible || campos.length === 0 ? (
        <p className="text-2xs text-ink-muted">{linaje.que_significa}</p>
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {campos.map(([campo, fuentes]) => (
            <li key={campo} className="py-1.5">
              <span className="text-2xs font-medium text-ink">{humanizar(campo)}</span>
              <ul className="mt-0.5">
                {(fuentes ?? []).map((f, i) => (
                  <li
                    key={`${f.fuente}-${i}`}
                    className="flex flex-wrap items-baseline gap-x-2 text-3xs"
                  >
                    <span className={f.gana ? "chip-dato chip-dato--si" : "chip-dato"}>
                      {f.fuente}
                    </span>
                    <span className="text-ink-muted">{String(f.valor ?? "")}</span>
                    <span className="text-ink-faint">
                      {t("cuenta.confianza", { valor: f.confianza })}
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Qué lleva demasiado sin que nadie lo confirme (CRM-01.01.04.09).
 *
 * Un dato viejo no se distingue de uno bueno mirándolo: el teléfono de hace
 * cuatro años se ve igual que el de ayer. Por eso van los días **y el tope**,
 * que es lo que convierte «lleva 400 días» en «se ha pasado».
 */
function LoQueLlevaSinConfirmarse({ obsoletos }: { obsoletos: Obsoletos | null }) {
  const { t } = useTranslation();
  if (!obsoletos) return null;
  const viejos = obsoletos.obsoletos ?? [];

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("cuenta.obsoletos")}</h2>
      {viejos.length === 0 ? (
        <>
          <Vacio titulo={t("cuenta.sinObsoletos")} compacto />
          {/* Sin linaje no es que esté todo al día: es que no se sabe. */}
          {obsoletos.aviso ? (
            <p className="mt-1 text-3xs text-ink-faint">{obsoletos.aviso}</p>
          ) : null}
        </>
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {viejos.map((o) => (
            <li
              key={`${o.campo}-${o.fuente}`}
              className="flex flex-wrap items-baseline gap-x-3 py-1.5"
            >
              <span className="text-2xs font-medium text-ink">{humanizar(o.campo)}</span>
              <span className="chip-dato">{o.fuente}</span>
              <span className="text-3xs text-warning">
                {t("cuenta.sinConfirmar", { dias: o.dias_sin_confirmar, tope: o.tope })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
