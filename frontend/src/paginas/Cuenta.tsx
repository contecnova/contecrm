/**
 * La ficha de un cliente, con la forma que tiene en el mercado.
 *
 * Es donde se ven CRM-01.01.05.01 (la línea de tiempo unificada de todas las
 * interacciones), CRM-01.01.01.10 (el equipo de cuenta con sus roles),
 * CRM-01.01.02.02 (la relación contacto–cuenta con su rol y su vigencia) y
 * CRM-01.01.05.06 (las métricas embebidas del cliente).
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

          Lo que cuadra es esto: la rejilla se queda en una pantalla, cada
          columna reparte su alto entre sus cajas y cada caja recorre su lista.
          Cuántas filas se ven no lo decide una constante: lo decide el alto que
          hay, que es lo que hace que cuadre en cualquier pantalla.

          **Sólo de `lg` para arriba.** En un móvil hay una sola columna y una
          barra dentro de otra es peor que el problema: el dedo no sabe cuál de
          las dos está moviendo. Ahí se desplaza la página. */}
      <div className="grid gap-4 lg:h-[calc(100vh-15rem)] lg:min-h-[32rem] lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)_minmax(0,19rem)]">
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
    <section className="card flex flex-col overflow-hidden p-4 lg:min-h-0">
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
