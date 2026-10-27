/**
 * Lo que la plataforma hace por debajo, con puerta (CRM-00.05.04.01,
 * CRM-00.05.04.03, CRM-00.05.04.04, CRM-00.05.04.05, CRM-00.05.03.06,
 * CRM-07.03.01.04, CRM-07.03.01.07, CRM-07.03.02.09, CRM-00.06.02.03,
 * CRM-00.06.02.02, CRM-00.05.03.04).
 *
 * Son rutas que el producto publica desde el primer día y a las que **no se
 * llegaba desde ninguna pantalla**: el audit trail, las anomalías de
 * exportación, el registro de tratamiento, la matriz de permisos, lo que se
 * puede restaurar y lo que hay en la papelera. Medido sobre el contrato
 * publicado el 27-10-2026: 477 colecciones GET sin un solo botón, y 170 de
 * ellas eran **la misma ruta repetida en los catorce servicios**.
 *
 * De ahí la forma de esta pantalla. Lo evidente —una pestaña por servicio y
 * por familia— son setenta y ocho pestañas que dicen lo mismo, y nadie
 * encuentra nada en setenta y ocho pestañas. Aquí hay **un selector de
 * servicio arriba** y debajo las preguntas, que son las mismas para todos:
 * cada servicio guarda lo suyo y la pregunta no cambia.
 *
 * Y son preguntas, no tablas. «Quién tocó esto», «qué se salió de lo normal»,
 * «qué datos personales trata esto», «qué se puede recuperar». Un volcado de
 * todo lo que hay obliga a buscar el problema; esto lo pone delante.
 *
 * Lo que esta pantalla **no** declara, aunque lo roce: `CRM-00.05.04.06`
 * —event sourcing para reconstruir un agregado—, porque reconstruir pide el
 * identificador de un registro concreto y su sitio es la ficha de ese
 * registro, no un panel de plataforma. Declararlo aquí sería declarar lo que
 * no se hace.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { escalar } from "@/lib/formato";
import { puede, type Sesion } from "@/lib/sesion";

/**
 * Los servicios que guardan datos del cliente.
 *
 * Se escriben aquí y no se descubren: el único sitio que los sabe es el
 * despliegue, y pedirle al navegador que recorra catorce rutas para ver cuál
 * contesta son catorce peticiones y un segundo de espera para pintar un
 * desplegable. Si alguno no está desplegado, su panel lo dice al pedirlo —que
 * es lo honesto— en vez de esconderlo.
 */
const SERVICIOS = [
  "party",
  "sales",
  "service",
  "marketing",
  "identity",
  "analytics",
  "automation",
  "integration",
  "intelligence",
  "metadata",
  "orchestrator",
  "tenancy",
  "eventing",
] as const;

/** `GET /{servicio}/cumplimiento/informe`: lo que el RAT no contesta. */
interface InformeCumplimiento {
  servicio: string;
  generado_at: string;
  avisos: string[];
  integridad_del_audit_trail: { verificacion: Record<string, unknown> };
  politicas_de_acceso: { activas: number; nombres: string[] };
}

/** `GET /{servicio}/rastro`: qué agregados tienen el rastro completo encendido. */
interface Rastro {
  servicio: string;
  agregados: Record<string, unknown>;
  porque: string;
}

/** `GET /{servicio}/volumen/plan-de-particion`: todas las tablas que crecen. */
interface PlanDeParticion {
  cuantas: number;
  porque_solo_estas: string;
  tablas: {
    tabla: string;
    por_que_crece: string;
    estrategia: string;
    meses_en_caliente: number;
    porque_por_tiempo: string;
    indice_por_tenant: boolean;
  }[];
}

interface Apunte {
  secuencia: number;
  cuando: string;
  accion: string;
  objeto: string;
  objeto_id: string | null;
  actor_id: string | null;
  en_nombre_de: string | null;
  origen: string | null;
  ip: string | null;
  motivo: string | null;
}

interface Anomalia {
  usuario_id: string;
  cuando: string;
  objeto: string;
  registros: number;
  bloqueada: boolean;
  motivo: string;
  ip: string | null;
}

interface Rat {
  completo: boolean;
  actividades: { objeto: string; finalidad: string; base_legal: string; plazo: string }[];
  objetos_sin_tratamiento_declarado: string[];
}

interface Matriz {
  exigidos_sin_ningun_rol: string[];
  concedidos_que_ninguna_ruta_exige: string[];
  quien_puede: Record<string, string[]>;
  alcance_de_los_roles: string;
}

interface Rpo {
  medible: boolean;
  /** Nulo cuando no hay copia de la que medir: no se sabe, que no es «dentro». */
  dentro: boolean | null;
  se_perderia_min: number | null;
  rpo_comprometido_min: number;
  porque: string;
}

interface Ventana {
  se_puede: boolean;
  retencion_dias: number;
  pedidos_dias: number;
  porque: string;
}

interface Tokenizacion {
  hay_boveda: boolean;
  tipos: string[];
  que_significa: string;
}

interface Particiones {
  urgente: boolean;
  ya_falta_la_de_este_mes: boolean;
  faltan: string[];
  porque: string;
}

interface EntradaPapelera {
  id: string;
  objeto: string;
  etiqueta: string;
  borrado_at: string;
  dias_para_purga: number;
  en_cascada: number;
}

export function Plataforma({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  const [servicio, setServicio] = useState<string>("party");

  return (
    <>
      <CabeceraPagina
        titulo={t("plataforma.titulo")}
        icono="shield_lock"
        entradilla={t("plataforma.entradilla")}
        acciones={
          <label className="flex items-center gap-2 text-2xs text-ink-muted">
            {t("plataforma.servicio")}
            <select
              className="campo"
              value={servicio}
              onChange={(e) => setServicio(e.target.value)}
              aria-label={t("plataforma.servicio")}
            >
              {SERVICIOS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        }
      />

      {/* El audit trail y las anomalías viven en `tenancy` y valen para todo el
          tenant: no se mueven con el selector, y por eso van primero y
          separados de lo que sí es de un servicio. Mezclarlos haría creer que
          cambiando de servicio cambia también lo que enseñan. */}
      <Auditoria puedeVer={puede(sesion, "tenant:read")} />
      <Anomalias puedeVer={puede(sesion, "tenant:read")} />

      <h2 className="section-label mb-2 mt-6">
        {t("plataforma.deEsteServicio", { servicio })}
      </h2>
      <Cumplimiento servicio={servicio} puedeVer={puede(sesion, "cumplimiento:leer")} />
      <Recuperable servicio={servicio} puedeVer={puede(sesion, "datos:restaurar")} />
      <HastaDondeSeVuelve servicio={servicio} puedeVer={puede(sesion, "datos:restaurar")} />
      <Aguanta servicio={servicio} puedeVer={puede(sesion, "datos:restaurar")} />
      <ComoSeCorta servicio={servicio} puedeVer={puede(sesion, "admin:read")} />
      <RastroCompleto servicio={servicio} puedeVer={puede(sesion, "admin:read")} />
      <Boveda servicio={servicio} puedeVer={puede(sesion, "tokenizacion:read")} />
    </>
  );
}

function Panel({
  titulo,
  ayuda,
  children,
  acciones,
}: {
  titulo: string;
  ayuda: string;
  children: React.ReactNode;
  acciones?: React.ReactNode;
}) {
  return (
    <section className="card mb-4 p-4">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <h3 className="section-label">{titulo}</h3>
          <p className="mt-0.5 text-3xs text-ink-faint">{ayuda}</p>
        </div>
        {acciones}
      </div>
      {children}
    </section>
  );
}

/** Quién tocó qué, y desde dónde. */
function Auditoria({ puedeVer }: { puedeVer: boolean }) {
  const { t } = useTranslation();
  const [accion, setAccion] = useState("");
  const [objeto, setObjeto] = useState("");
  const [filas, setFilas] = useState<Apunte[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    if (!puedeVer) return undefined;
    const control = new AbortController();
    const q = new URLSearchParams();
    if (accion) q.set("accion", accion);
    if (objeto) q.set("objeto", objeto);
    q.set("limite", "100");
    llamar<Apunte[]>(`/api/v1/grc/auditoria?${q}`, { signal: control.signal })
      .then((r) => setFilas(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [accion, objeto, puedeVer]);

  useEffect(cargar, [cargar]);

  if (!puedeVer) return null;
  return (
    <Panel
      titulo={t("plataforma.auditoria")}
      ayuda={t("plataforma.auditoriaAyuda")}
      acciones={
        // El volcado al SIEM es una exportación masiva y el servidor pide
        // reverificación: el enlace se ofrece igual, porque esconder lo que
        // existe no lo hace más seguro — lo hace invisible.
        <a
          className="btn-secondary"
          href={`/api/v1/grc/auditoria/volcado.jsonl?desde=${hace(30)}&hasta=${ahora()}`}
          download
        >
          <Icono nombre="download" /> {t("plataforma.volcarSiem")}
        </a>
      }
    >
      <div className="mb-3 flex flex-wrap gap-2">
        <input
          className="campo"
          placeholder={t("plataforma.filtroAccion")}
          aria-label={t("plataforma.filtroAccion")}
          value={accion}
          onChange={(e) => setAccion(e.target.value)}
        />
        <input
          className="campo"
          placeholder={t("plataforma.filtroObjeto")}
          aria-label={t("plataforma.filtroObjeto")}
          value={objeto}
          onChange={(e) => setObjeto(e.target.value)}
        />
      </div>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {!filas && !fallo ? <Cargando /> : null}
      {filas && filas.length === 0 ? <Vacio titulo={t("plataforma.sinApuntes")} compacto /> : null}
      {filas && filas.length > 0 ? (
        <ul className="divide-y divide-ink-dim/30">
          {filas.map((a) => (
            <li key={a.secuencia} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
              <span className="text-2xs font-medium text-ink">{a.accion}</span>
              <span className="text-3xs text-ink-muted">{a.objeto}</span>
              <span className="text-3xs text-ink-faint">{escalar(a.cuando, "cuando")}</span>
              {/* Quién, y en nombre de quién: una acción hecha por soporte
                  suplantando a alguien es la que más falta hace distinguir, y
                  con un solo identificador no se distingue. */}
              {a.en_nombre_de ? (
                <span className="chip-dato">{t("plataforma.enNombreDe")}</span>
              ) : null}
              {a.origen ? <span className="text-3xs text-ink-faint">{a.origen}</span> : null}
              {a.ip ? <span className="text-3xs text-ink-faint">{a.ip}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

/** Lo que se salió de lo normal: exportaciones masivas y lecturas raras. */
function Anomalias({ puedeVer }: { puedeVer: boolean }) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Anomalia[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    if (!puedeVer) return undefined;
    const control = new AbortController();
    llamar<Anomalia[]>("/api/v1/grc/anomalias?dias=30", { signal: control.signal })
      .then((r) => setFilas(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [puedeVer]);

  useEffect(cargar, [cargar]);

  if (!puedeVer) return null;
  return (
    <Panel titulo={t("plataforma.anomalias")} ayuda={t("plataforma.anomaliasAyuda")}>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {!filas && !fallo ? <Cargando /> : null}
      {filas && filas.length === 0 ? <Vacio titulo={t("plataforma.sinAnomalias")} compacto /> : null}
      {filas && filas.length > 0 ? (
        <ul className="divide-y divide-ink-dim/30">
          {filas.map((a, i) => (
            <li key={`${a.usuario_id}:${a.cuando}:${i}`} className="py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-3">
                {/* Cuántos registros salieron, primero: es el número que dice
                    si esto es una consulta grande o una fuga. */}
                <span className="text-sm font-medium text-ink">{a.registros}</span>
                <span className="text-2xs text-ink">{a.objeto}</span>
                <span className="text-3xs text-ink-faint">{escalar(a.cuando, "cuando")}</span>
                <span className={a.bloqueada ? "chip-dato chip-dato--si" : "chip-dato"}>
                  {a.bloqueada ? t("plataforma.bloqueada") : t("plataforma.permitida")}
                </span>
              </div>
              <p className="text-3xs text-ink-muted">{a.motivo}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

/** Qué datos personales trata este servicio, y quién puede hacer qué en él. */
function Cumplimiento({ servicio, puedeVer }: { servicio: string; puedeVer: boolean }) {
  const { t } = useTranslation();
  const [rat, setRat] = useState<Rat | null>(null);
  const [matriz, setMatriz] = useState<Matriz | null>(null);
  const [informe, setInforme] = useState<InformeCumplimiento | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    if (!puedeVer) return undefined;
    const control = new AbortController();
    setRat(null);
    setMatriz(null);
    setInforme(null);
    setFallo(null);
    Promise.all([
      llamar<Rat>(`/api/v1/${servicio}/cumplimiento/rat`, { signal: control.signal }),
      llamar<Matriz>(`/api/v1/${servicio}/cumplimiento/matriz-permisos`, {
        signal: control.signal,
      }),
    ])
      .then(([r, m]) => {
        setRat(r.datos);
        setMatriz(m.datos);
      })
      .catch(salvoCancelacion(setFallo));
    // El informe aparte y con su propio fallo: contesta otras dos preguntas
    // —si el rastro de auditoría cuadra y cuántas políticas de acceso hay
    // activas— y que no se pueda leer no puede dejar el RAT sin ver.
    llamar<InformeCumplimiento>(`/api/v1/${servicio}/cumplimiento/informe`, {
      signal: control.signal,
    })
      .then((r) => setInforme(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, [servicio, puedeVer]);

  useEffect(cargar, [cargar]);

  if (!puedeVer) return null;
  return (
    <Panel titulo={t("plataforma.cumplimiento")} ayuda={t("plataforma.cumplimientoAyuda")}>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {!rat && !fallo ? <Cargando /> : null}
      {rat ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-sm font-medium text-ink">
              {t("plataforma.tratamientos", { cuantos: rat.actividades.length })}
            </p>
            {/* Los huecos primero: un RAT que se presenta completo sin serlo es
                peor que no tenerlo, porque nadie vuelve a mirarlo. */}
            {rat.objetos_sin_tratamiento_declarado.length > 0 ? (
              <>
                <p className="mt-1 text-3xs text-danger">
                  {t("plataforma.sinTratamiento", {
                    cuantos: rat.objetos_sin_tratamiento_declarado.length,
                  })}
                </p>
                <ul className="mt-1 flex flex-wrap gap-1">
                  {rat.objetos_sin_tratamiento_declarado.map((o) => (
                    <li key={o} className="chip-dato">
                      {o}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="mt-1 text-3xs text-ink-faint">{t("plataforma.ratCompleto")}</p>
            )}
          </div>
          <div>
            <p className="text-sm font-medium text-ink">{t("plataforma.permisos")}</p>
            {/* Los dos huecos son opuestos y los dos importan: un permiso que
                nadie tiene es funcionalidad muerta; uno que nadie exige es un
                privilegio dado por si acaso. */}
            <p className="mt-1 text-3xs text-ink-muted">
              {t("plataforma.sinRol", {
                cuantos: matriz?.exigidos_sin_ningun_rol.length ?? 0,
              })}
            </p>
            <p className="text-3xs text-ink-muted">
              {t("plataforma.sinRuta", {
                cuantos: matriz?.concedidos_que_ninguna_ruta_exige.length ?? 0,
              })}
            </p>
            {matriz ? (
              <p className="mt-1 text-3xs text-ink-faint">{matriz.alcance_de_los_roles}</p>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* Los avisos del informe van los ÚLTIMOS y en rojo: son lo único de
          este panel que obliga a hacer algo hoy, y enterrarlos entre dos
          recuentos es cómo se aprende a no mirarlos. */}
      {informe ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-3">
          <p className="text-3xs text-ink-muted">
            {t("plataforma.politicasActivas", {
              cuantas: informe.politicas_de_acceso.activas,
            })}
          </p>
          {informe.avisos.length > 0 ? (
            <ul className="mt-1 space-y-0.5">
              {informe.avisos.map((aviso) => (
                <li key={aviso} className="text-3xs text-danger">
                  {aviso}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-3xs text-ink-faint">{t("plataforma.sinAvisos")}</p>
          )}
        </div>
      ) : null}
    </Panel>
  );
}

/** Qué se puede recuperar, y qué está a punto de no poder recuperarse. */
function Recuperable({ servicio, puedeVer }: { servicio: string; puedeVer: boolean }) {
  const { t } = useTranslation();
  const [papelera, setPapelera] = useState<EntradaPapelera[] | null>(null);
  const [objetos, setObjetos] = useState<string[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    if (!puedeVer) return undefined;
    const control = new AbortController();
    setPapelera(null);
    setFallo(null);
    Promise.all([
      llamar<EntradaPapelera[]>(`/api/v1/${servicio}/papelera`, { signal: control.signal }),
      llamar<{ objetos: string[] }>(`/api/v1/${servicio}/restauracion/objetos`, {
        signal: control.signal,
      }),
    ])
      .then(([p, o]) => {
        setPapelera(p.datos);
        setObjetos(o.datos.objetos ?? []);
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [servicio, puedeVer]);

  useEffect(cargar, [cargar]);

  // Lo que menos tiempo le queda, primero: la papelera se mira cuando alguien
  // borró algo sin querer, y lo urgente es lo que está a punto de purgarse.
  const ordenada = useMemo(
    () => [...(papelera ?? [])].sort((a, b) => a.dias_para_purga - b.dias_para_purga),
    [papelera],
  );

  if (!puedeVer) return null;
  return (
    <Panel titulo={t("plataforma.recuperable")} ayuda={t("plataforma.recuperableAyuda")}>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {!papelera && !fallo ? <Cargando /> : null}
      {papelera && papelera.length === 0 ? (
        <Vacio titulo={t("plataforma.papeleraVacia")} compacto />
      ) : null}
      {ordenada.length > 0 ? (
        <ul className="divide-y divide-ink-dim/30">
          {ordenada.map((e) => (
            <li key={e.id} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
              <span
                className={
                  e.dias_para_purga <= 7
                    ? "text-sm font-medium text-danger"
                    : "text-sm font-medium text-ink"
                }
              >
                {t("plataforma.diasParaPurga", { dias: e.dias_para_purga })}
              </span>
              <span className="text-2xs text-ink">{e.etiqueta || e.objeto}</span>
              <span className="text-3xs text-ink-faint">{e.objeto}</span>
              {/* Lo que se lleva por delante: restaurar una fila sin sus hijos
                  deja un registro a medias, y eso no se ve hasta abrirlo. */}
              {e.en_cascada > 0 ? (
                <span className="chip-dato">
                  {t("plataforma.enCascada", { cuantos: e.en_cascada })}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {objetos && objetos.length > 0 ? (
        <p className="mt-3 text-3xs text-ink-faint">
          {t("plataforma.restaurables", { objetos: objetos.join(", ") })}
        </p>
      ) : null}
    </Panel>
  );
}

/**
 * Hasta cuándo se puede volver atrás, y cuánto se perdería si fuera ahora.
 *
 * Las dos preguntas que se hacen el día del incidente, y ese día nadie se pone
 * a leer una API. El RPO que importa es el **real**, no el del contrato: la
 * diferencia entre los dos es lo único que se puede enseñar en una auditoría.
 */
function HastaDondeSeVuelve({ servicio, puedeVer }: { servicio: string; puedeVer: boolean }) {
  const { t } = useTranslation();
  const [rpo, setRpo] = useState<Rpo | null>(null);
  const [ventana, setVentana] = useState<Ventana | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    if (!puedeVer) return undefined;
    const control = new AbortController();
    setRpo(null);
    setFallo(null);
    Promise.all([
      llamar<Rpo>(`/api/v1/${servicio}/restauracion/rpo`, { signal: control.signal }),
      llamar<Ventana>(`/api/v1/${servicio}/restauracion/ventana`, { signal: control.signal }),
    ])
      .then(([r, v]) => {
        setRpo(r.datos);
        setVentana(v.datos);
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [servicio, puedeVer]);

  useEffect(cargar, [cargar]);

  if (!puedeVer) return null;
  return (
    <Panel titulo={t("plataforma.volverAtras")} ayuda={t("plataforma.volverAtrasAyuda")}>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {!rpo && !fallo ? <Cargando /> : null}
      {rpo ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            {/* «No medible» NO es «cero minutos»: sin la fecha de la última
                copia no se sabe cuánto se perdería, y enseñar un cero sería un
                verde que nadie se ha ganado. */}
            {rpo.medible ? (
              <p
                className={
                  rpo.dentro ? "text-sm font-medium text-ink" : "text-sm font-medium text-danger"
                }
              >
                {t("plataforma.sePerderia", { minutos: rpo.se_perderia_min ?? 0 })}
                <span className="text-3xs text-ink-faint">
                  {" "}
                  {t("plataforma.comprometido", { minutos: rpo.rpo_comprometido_min })}
                </span>
              </p>
            ) : (
              <p className="text-sm font-medium text-ink-muted">{t("plataforma.noMedible")}</p>
            )}
            <p className="mt-1 text-3xs text-ink-muted">{rpo.porque}</p>
          </div>
          {ventana ? (
            <div>
              <p
                className={
                  ventana.se_puede
                    ? "text-sm font-medium text-ink"
                    : "text-sm font-medium text-danger"
                }
              >
                {t("plataforma.ventana", {
                  pedidos: ventana.pedidos_dias,
                  retencion: ventana.retencion_dias,
                })}
              </p>
              <p className="mt-1 text-3xs text-ink-muted">{ventana.porque}</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}

/**
 * Qué tabla va camino de dar problemas, antes de darlos.
 *
 * Una partición que falta no se nota hasta que la escritura falla, y entonces
 * ya es un incidente. Por eso lo que se enseña es **lo que falta por crear**,
 * no el inventario de lo que hay.
 *
 * La pregunta necesita un dato que sólo sabe quien administra la base: **cuál
 * es la última partición que ya existe**. El servidor lo exige, y la primera
 * versión de este panel llamaba sin él: la respuesta era un 422 y el panel
 * salía en error siempre, para todos los servicios. Así que se pide, con el
 * primero del mes en curso de partida —el caso normal— y diciendo para qué
 * sirve, en vez de inventarse un valor y dar una respuesta que no es sobre
 * esta instalación.
 */
function Aguanta({ servicio, puedeVer }: { servicio: string; puedeVer: boolean }) {
  const { t } = useTranslation();
  const [ultima, setUltima] = useState(primeroDeEsteMes);
  const [particiones, setParticiones] = useState<Particiones | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    if (!puedeVer || !ultima) return undefined;
    const control = new AbortController();
    setParticiones(null);
    setFallo(null);
    llamar<Particiones>(
      `/api/v1/${servicio}/volumen/particiones-a-crear?ultima_existente=${ultima}`,
      { signal: control.signal },
    )
      .then((r) => setParticiones(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [servicio, puedeVer, ultima]);

  useEffect(cargar, [cargar]);

  if (!puedeVer) return null;
  return (
    <Panel titulo={t("plataforma.volumen")} ayuda={t("plataforma.volumenAyuda")}>
      <label className="mb-3 flex flex-wrap items-center gap-2 text-2xs text-ink-muted">
        {t("plataforma.ultimaParticion")}
        <input
          type="date"
          className="campo"
          value={ultima}
          onChange={(e) => setUltima(e.target.value)}
          aria-label={t("plataforma.ultimaParticion")}
        />
      </label>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {!particiones && !fallo ? <Cargando /> : null}
      {particiones ? (
        <>
          <p
            className={
              particiones.urgente ? "text-sm font-medium text-danger" : "text-sm font-medium text-ink"
            }
          >
            {particiones.ya_falta_la_de_este_mes
              ? t("plataforma.faltaLaDeEsteMes")
              : t("plataforma.particionesPorCrear", { cuantas: particiones.faltan.length })}
          </p>
          {particiones.faltan.length > 0 ? (
            <ul className="mt-1 flex flex-wrap gap-1">
              {particiones.faltan.map((f) => (
                <li key={f} className="chip-dato">
                  {f}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="mt-1 text-3xs text-ink-muted">{particiones.porque}</p>
        </>
      ) : null}
    </Panel>
  );
}

/**
 * Cómo se corta cada tabla que crece, y por qué así.
 *
 * Va pegado a «qué particiones faltan» porque son la misma conversación: una
 * dice qué hay que crear mañana y la otra por qué esa tabla se parte por mes y
 * no por cliente. La ruta existía desde el primer día y **no tenía puerta
 * posible**: exigía el nombre de la tabla, y la lista de tablas de alto volumen
 * sólo vivía dentro del núcleo.
 */
function ComoSeCorta({ servicio, puedeVer }: { servicio: string; puedeVer: boolean }) {
  const { t } = useTranslation();
  const [plan, setPlan] = useState<PlanDeParticion | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    if (!puedeVer) return undefined;
    const control = new AbortController();
    setPlan(null);
    setFallo(null);
    llamar<PlanDeParticion>(`/api/v1/${servicio}/volumen/plan-de-particion`, {
      signal: control.signal,
    })
      .then((r) => setPlan(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [servicio, puedeVer]);

  useEffect(cargar, [cargar]);

  if (!puedeVer) return null;
  return (
    <Panel titulo={t("plataforma.comoSeCorta")} ayuda={t("plataforma.comoSeCortaAyuda")}>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {!plan && !fallo ? <Cargando /> : null}
      {plan ? (
        <>
          <ul className="divide-y divide-ink-dim/30">
            {plan.tablas.map((tabla) => (
              <li key={tabla.tabla} className="py-1.5">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-sm font-medium text-ink">{tabla.tabla}</span>
                  <span className="chip-dato">{tabla.estrategia}</span>
                  <span className="text-3xs text-ink-muted">
                    {t("plataforma.mesesEnCaliente", { meses: tabla.meses_en_caliente })}
                  </span>
                </div>
                {/* Por qué crece, dicho por el servidor: sin eso la lista es un
                    inventario y no explica por qué sólo se parten éstas. */}
                <p className="text-3xs text-ink-faint">{tabla.por_que_crece}</p>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-3xs text-ink-muted">{plan.porque_solo_estas}</p>
        </>
      ) : null}
    </Panel>
  );
}

/**
 * Qué agregados guardan su historia completa, y por qué no todos.
 *
 * «Ninguno» no es un hueco: encender el rastro completo para todo multiplica
 * la escritura por algo que casi nunca se consulta. Por eso el servidor manda
 * el porqué y aquí se enseña — un panel vacío sin explicación se lee como algo
 * que falta.
 */
function RastroCompleto({ servicio, puedeVer }: { servicio: string; puedeVer: boolean }) {
  const { t } = useTranslation();
  const [rastro, setRastro] = useState<Rastro | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    if (!puedeVer) return undefined;
    const control = new AbortController();
    setRastro(null);
    setFallo(null);
    llamar<Rastro>(`/api/v1/${servicio}/rastro`, { signal: control.signal })
      .then((r) => setRastro(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [servicio, puedeVer]);

  useEffect(cargar, [cargar]);

  if (!puedeVer) return null;
  const agregados = Object.keys(rastro?.agregados ?? {});
  return (
    <Panel titulo={t("plataforma.rastro")} ayuda={t("plataforma.rastroAyuda")}>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {!rastro && !fallo ? <Cargando /> : null}
      {rastro ? (
        <>
          {agregados.length > 0 ? (
            <ul className="flex flex-wrap gap-1">
              {agregados.map((a) => (
                <li key={a} className="chip-dato">
                  {a}
                </li>
              ))}
            </ul>
          ) : (
            <Vacio
              titulo={t("plataforma.sinRastroCompleto")}
              detalle={rastro.porque}
              compacto
            />
          )}
          {agregados.length > 0 ? (
            <p className="mt-2 text-3xs text-ink-muted">{rastro.porque}</p>
          ) : null}
        </>
      ) : null}
    </Panel>
  );
}

/**
 * Si este despliegue puede sacar del CRM un número de tarjeta o un NIF.
 *
 * Se pregunta **antes** de ofrecer el campo: sin bóveda no se tokeniza en
 * falso, porque guardar el número «hasta que haya bóveda» mete el sistema en
 * el alcance de PCI sin que nadie lo haya decidido.
 */
function Boveda({ servicio, puedeVer }: { servicio: string; puedeVer: boolean }) {
  const { t } = useTranslation();
  const [estado, setEstado] = useState<Tokenizacion | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    if (!puedeVer) return undefined;
    const control = new AbortController();
    setEstado(null);
    setFallo(null);
    llamar<Tokenizacion>(`/api/v1/${servicio}/tokenizacion`, { signal: control.signal })
      .then((r) => setEstado(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [servicio, puedeVer]);

  useEffect(cargar, [cargar]);

  if (!puedeVer) return null;
  return (
    <Panel titulo={t("plataforma.boveda")} ayuda={t("plataforma.bovedaAyuda")}>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {!estado && !fallo ? <Cargando /> : null}
      {estado ? (
        <>
          <p
            className={
              estado.hay_boveda ? "text-sm font-medium text-ink" : "text-sm font-medium text-danger"
            }
          >
            {estado.hay_boveda ? t("plataforma.conBoveda") : t("plataforma.sinBoveda")}
          </p>
          <p className="mt-1 text-3xs text-ink-muted">{estado.que_significa}</p>
          {estado.tipos.length > 0 ? (
            <ul className="mt-1 flex flex-wrap gap-1">
              {estado.tipos.map((x) => (
                <li key={x} className="chip-dato">
                  {x}
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </Panel>
  );
}

function primeroDeEsteMes(): string {
  const hoy = new Date();
  return `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}-01`;
}

function ahora(): string {
  return new Date().toISOString();
}

function hace(dias: number): string {
  return new Date(Date.now() - dias * 86_400_000).toISOString();
}
