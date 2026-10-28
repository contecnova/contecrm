/**
 * Consola única de gobierno de la suite (CRM-00.01.07.06).
 *
 * Enseña CRM-00.01.07.03 (el alta y la baja de usuario en cascada, y sobre
 * todo las bajas sin aplicar), CRM-00.01.07.07 (la divergencia entre lo que
 * dice cada herramienta y lo que decimos nosotros), CRM-00.01.07.10 (la cola de
 * aprovisionamiento con su cuarentena y su reintento) y CRM-00.01.07.12 (la
 * auditoría transversal).
 *
 * Y desde el 28-10-2026, las dos preguntas del momento malo
 * (CRM-06.01.03.20, CRM-06.01.03.17): «esto no conecta, ¿qué falta
 * exactamente?» —que es lo que evita que una implantación se atasque una
 * semana probándolo todo y acabe pidiendo permisos de administrador global
 * «para descartar»— y «si lo desconecto, ¿qué me llevo y qué se queda?», que
 * es lo que nadie se atreve a hacer sin saberlo.
 *
 * Y desde el 27-10-2026, la **salud de las suites de productividad**
 * (CRM-06.01.03.16, CRM-06.01.03.03, CRM-06.01.03.05): qué buzón lleva sin
 * sincronizar y por qué, qué credenciales van a dejar de funcionar y qué
 * suscripciones hay que renovar antes de que caduquen. Las tres rutas las
 * publicaba el servidor desde el principio y no se alcanzaban desde ninguna
 * pantalla: una conexión parada no avisa sola, y quien la descubre es el
 * comercial al que le falta el correo de la semana pasada.
 *
 * Quien administra contecrm administra también el resto de herramientas de la
 * casa, y hasta ahora eso significaba cuatro pantallas y cuatro sitios donde dar
 * de baja a alguien que se va — que es justo el momento en el que olvidarse de
 * uno tiene consecuencias.
 *
 * Por eso esta pantalla enseña primero **las bajas sin aplicar**, que es lo único
 * que hay que mirar con prisa: una baja que no llegó es un acceso que sigue
 * abierto en otra herramienta, y eso no lo ve nadie hasta una auditoría.
 *
 * Y dos cosas que se pintan a propósito:
 *
 * **Sin herramientas conectadas no se dice «todo bien».** Un verde silencioso
 * haría creer que el cliente está en la suite cuando solo está en el CRM.
 *
 * **Esto no es un panel de control remoto.** Cada herramienta sigue mandando en
 * lo suyo; aquí se ve lo que cada una publica.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";
import { escalar } from "@/lib/formato";
import { usePuedeOperar } from "@/lib/permisos";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";

interface Herramienta {
  herramienta: string;
  tipo: string;
  activa: boolean;
  estado: string;
  bajas_sin_aplicar: number;
  ultimo_error: string | null;
}

interface Veredicto {
  ok: boolean;
  que_pasa: string;
  que_hacer?: string;
  faltan_alcances?: string[];
}

interface PlanDeBaja {
  motivo: string;
  se_queda: { que: string; porque: string }[];
  se_borra: { que: string; porque: string }[];
}

interface Panel {
  herramientas: Herramienta[];
  cuarentena: number;
  bajas_sin_aplicar: number;
  en_verde: boolean;
  sin_herramientas: boolean;
}

export function SuiteGobierno() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Panel | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [recargar, setRecargar] = useState(0);

  useEffect(() => {
    const control = new AbortController();
    llamar<Panel>("/api/v1/suite/panel", { signal: control.signal })
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [recargar]);

  if (fallo) return <Fallo error={fallo} />;
  if (!datos) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("suite.titulo")}
        entradilla={t("suite.intro")}
        icono="sync_alt"
      />

      {datos.sin_herramientas ? (
        /* Un verde silencioso haría creer que el cliente está en la suite
           cuando solo está en el CRM. */
        <Vacio
          titulo={t("suite.sinHerramientas")}
          detalle={t("suite.sinHerramientasPorque")}
        />
      ) : (
        <>
          {/* Lo primero y aparte: una baja sin aplicar es un acceso abierto. */}
          <p
            className={`mt-4 text-xs ${
              datos.bajas_sin_aplicar > 0 ? "text-danger" : "text-success"
            }`}
            role="status"
          >
            {datos.bajas_sin_aplicar > 0
              ? t("suite.bajasSinAplicar", { cuantas: datos.bajas_sin_aplicar })
              : t("suite.sinBajasPendientes")}
          </p>

          <Rejilla
            className="mt-4"
            cabeceras={[
              t("suite.herramienta"),
              t("suite.estado"),
              t("suite.bajas"),
              t("suite.ultimoError"),
            ]}
          >
            {datos.herramientas.map((h) => (
              <tr
                key={h.herramienta}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla className="text-ink">{h.herramienta}</Casilla>
                <Casilla
                  className={`${h.activa ? "text-success" : "text-ink-faint"}`}
                >
                  {h.estado}
                </Casilla>
                <Casilla
                  className={`${
                    h.bajas_sin_aplicar > 0 ? "text-danger" : "text-ink-muted"
                  }`}
                >
                  {h.bajas_sin_aplicar}
                </Casilla>
                <Casilla className="text-3xs text-ink-faint">
                  {h.ultimo_error ?? "—"}
                </Casilla>
              </tr>
            ))}
          </Rejilla>

          {datos.cuarentena > 0 ? (
            <>
              <p className="mt-3 text-2xs text-warning" role="status">
                {t("suite.cuarentena", { cuantas: datos.cuarentena })}
              </p>
              <Cuarentena alReintentar={() => setRecargar((n) => n + 1)} />
            </>
          ) : null}
        </>
      )}

      {/* La salud de las suites va DESPUÉS del gobierno de la suite de la casa
          y antes del aviso: son dos cosas distintas —una es quién tiene acceso
          a qué herramienta, otra es si el correo y el calendario de cada uno
          están entrando— y juntarlas en el mismo bloque haría creer que una
          baja sin aplicar y un buzón parado se arreglan en el mismo sitio. */}
      <SaludDeLasSuites />
      {/* Y lo que la suite sabe del cliente como un todo: su identidad tal
          como la ven todas las herramientas, qué cambiaría una aplicación
          antes de aplicarla, quién cambió qué y dónde acabó, y el certificado
          de cierre. Las cuatro estaban servidas y sin pantalla. */}
      <LaSuiteComoUnTodo />
      {/* Y las dos preguntas que se hacen EN EL MOMENTO MALO: «esto no
          conecta, ¿qué falta exactamente?» y «si lo desconecto, ¿qué pierdo?».
          Las dos las contestaba el servidor desde el principio y no había
          dónde preguntarlas. */}
      <CuandoNoConecta />
      <AntesDeDesconectar />

      <p className="mt-6 text-3xs text-ink-faint">
        {t("suite.noEsControlRemoto")}
      </p>
    </>
  );
}

/**
 * Lo que la suite sabe del cliente, visto de una vez.
 *
 * Un gobierno de suite que sólo enseña herramienta a herramienta obliga a
 * sumar de cabeza: en qué quedó aquel cambio, si lo que vamos a aplicar va a
 * tocar algo que no esperamos, y si al dar de baja a alguien se cerró en todas
 * partes o en casi todas.
 *
 * **Lo que se simula va antes de lo que se aplica**, y por eso está aquí: un
 * cambio de identidad que se propaga a cinco herramientas no se deshace
 * llamando a cinco soportes.
 */
function LaSuiteComoUnTodo() {
  const { t } = useTranslation();
  const [identidad, setIdentidad] = useState<Record<string, unknown> | null>(
    null,
  );
  const [simulacion, setSimulacion] = useState<Simulacion | null>(null);
  const [historial, setHistorial] = useState<Cambio[] | null>(null);
  const [cierre, setCierre] = useState<Cierre | null>(null);

  useEffect(() => {
    const control = new AbortController();
    const opciones = { signal: control.signal };
    // Cada una con su fallo: no poder leer el historial no puede dejar sin ver
    // lo que está a punto de aplicarse, que es lo que tiene consecuencias.
    void llamar<{ tenant: Record<string, unknown> }>(
      "/api/v1/suite/identidad",
      opciones,
    )
      .then((r) => setIdentidad(r.datos.tenant ?? null))
      .catch(() => undefined);
    void llamar<Simulacion>("/api/v1/suite/simular", opciones)
      .then((r) => setSimulacion(r.datos))
      .catch(() => undefined);
    void llamar<Cambio[]>("/api/v1/suite/historial", opciones)
      .then((r) => setHistorial(Array.isArray(r.datos) ? r.datos : []))
      .catch(() => undefined);
    void llamar<Cierre>("/api/v1/suite/certificado-de-cierre", opciones)
      .then((r) => setCierre(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  if (!identidad && !simulacion && !cierre) return null;

  return (
    <section className="card mt-4 p-4">
      <h2 className="section-label mb-1">{t("suite.comoUnTodo")}</h2>
      <p className="mb-3 text-3xs text-ink-faint">
        {t("suite.comoUnTodoAyuda")}
      </p>

      {/* Lo que se aplicaría, primero: es lo único de aquí que cambia algo. */}
      {simulacion ? (
        <p
          className={
            simulacion.total_a_aplicar > 0
              ? "text-sm font-medium text-ink"
              : "text-sm text-ink-muted"
          }
        >
          {t("suite.aAplicar", {
            cuantos: simulacion.total_a_aplicar,
            ya: simulacion.ya_aplicadas,
          })}
        </p>
      ) : null}

      {identidad ? (
        <p className="mt-1 text-3xs text-ink-muted">
          {t("suite.identidad", {
            nombre: String(identidad.nombre ?? "—"),
            estado: String(identidad.estado ?? "—"),
          })}
        </p>
      ) : null}

      {/* El cierre: lo abierto delante de lo cerrado. Una baja que se cerró en
          cuatro herramientas de cinco es un acceso que sigue abierto. */}
      {cierre ? (
        <p
          className={`mt-1 text-3xs ${
            (cierre.abiertas ?? []).length > 0
              ? "text-danger"
              : "text-ink-faint"
          }`}
        >
          {(cierre.abiertas ?? []).length > 0
            ? t("suite.quedanAbiertas", { cuantas: cierre.abiertas.length })
            : t("suite.todoCerrado", {
                cuantas: (cierre.cerradas ?? []).length,
              })}
        </p>
      ) : null}

      {historial?.length ? (
        <ul className="mt-2 space-y-0.5">
          {historial.slice(0, 5).map((cambio, i) => (
            <li
              key={String(cambio.id ?? i)}
              className="text-3xs text-ink-muted"
            >
              {cambio.que ?? cambio.accion ?? "—"}
              {cambio.herramienta ? ` · ${cambio.herramienta}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/**
 * La salud de las suites de productividad: tres preguntas que nadie podía hacer.
 *
 * Las tres rutas existían y no las pedía ninguna pantalla. Y las tres se
 * preguntan **antes** de que pase algo, que es cuando sirven: una conexión
 * parada no avisa sola —quien la descubre es el comercial al que le falta el
 * correo de la semana pasada—, una credencial que va a caducar no se renueva
 * el día que caduca, y una suscripción vencida deja los cambios entrando por
 * sondeo, con retraso y sin que se note.
 */
function SaludDeLasSuites() {
  const { t } = useTranslation();
  const [salud, setSalud] = useState<SaludSuites | null>(null);
  const [credenciales, setCredenciales] = useState<SaludCredenciales | null>(
    null,
  );
  const [suscripciones, setSuscripciones] = useState<Renovaciones | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    // Cada una con su propio fallo: que no se pueda leer el estado de las
    // credenciales no puede dejar sin ver los buzones parados.
    void llamar<SaludSuites>("/api/v1/suites/salud", { signal: control.signal })
      .then((r) => setSalud(r.datos))
      .catch(salvoCancelacion(setFallo));
    void llamar<SaludCredenciales>("/api/v1/suites/credenciales/salud", {
      signal: control.signal,
    })
      .then((r) => setCredenciales(r.datos))
      .catch(() => undefined);
    void llamar<Renovaciones>("/api/v1/suites/suscripciones/por-renovar", {
      signal: control.signal,
    })
      .then((r) => setSuscripciones(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  if (fallo) return <Fallo error={fallo} />;
  if (!salud) return <Cargando />;

  // Las tres listas salen del sobre que manda el servidor, no de un array que
  // esta pantalla se inventó: `/credenciales/salud` devuelve
  // `{revisados, que_piden_algo}` y `/suscripciones/por-renovar` devuelve
  // `{por_renovar, sin_caducidad_declarada, aviso}`. Leerlas como listas dejaba
  // el panel en blanco sin un solo error: el `.filter` sobre un objeto reventaba
  // dentro del `then` y el `catch` se lo tragaba.
  const porRenovar = suscripciones?.por_renovar ?? [];
  const sinDeclarar = suscripciones?.sin_caducidad_declarada ?? [];
  const piden = credenciales?.que_piden_algo ?? [];
  const rompibles = piden.filter((c) => c.se_rompera_sola);
  const otrasQuePiden = piden.filter((c) => !c.se_rompera_sola);

  return (
    <section className="card mt-4 p-4">
      <h2 className="section-label mb-1">{t("suite.saludSuites")}</h2>
      <p className="mb-3 text-3xs text-ink-faint">
        {t("suite.saludSuitesAyuda")}
      </p>

      {/* **Sin conexiones no se dice «todo bien».** Un panel que sólo cuenta lo
          sincronizado enseña un número que sube mientras tres buzones llevan
          una semana parados: el número es verdad y la impresión es falsa. */}
      {salud.total === 0 ? (
        <Vacio
          titulo={t("suite.sinConexiones")}
          detalle={t("suite.sinConexionesPorque")}
          compacto
        />
      ) : (
        <>
          <p
            className={
              salud.paradas.length > 0
                ? "text-sm font-medium text-danger"
                : "text-sm font-medium text-ink"
            }
          >
            {salud.paradas.length > 0
              ? t("suite.paradas", {
                  cuantas: salud.paradas.length,
                  total: salud.total,
                })
              : t("suite.todasAlDia", { total: salud.total })}
          </p>

          {salud.paradas.length > 0 ? (
            <ul className="mt-2 divide-y divide-ink-dim/30">
              {salud.paradas.map((parada) => (
                <li
                  key={parada.conexion}
                  className="flex flex-wrap items-baseline gap-x-3 py-1.5"
                >
                  {/* Las horas paradas, delante: es el número que decide a cuál
                      se va primero. */}
                  <span className="text-sm font-semibold leading-none text-danger">
                    {t("suite.horasParada", {
                      horas: parada.horas_sin_sincronizar,
                    })}
                  </span>
                  <span className="text-2xs text-ink">{parada.conexion}</span>
                  {parada.estado ? (
                    <span className="chip-dato">{parada.estado}</span>
                  ) : null}
                  {/* Por qué, dicho por el servidor: «no sincroniza» sin motivo
                      obliga a abrir el registro del servidor, que es justo lo
                      que esta pantalla existe para evitar. */}
                  {parada.porque ? (
                    <span className="text-3xs text-ink-muted">
                      {parada.porque}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}

          {/* Lo que va por sondeo entra con RETRASO, no al instante: se dice
              aparte porque no está parado y tampoco está al día. */}
          {salud.en_sondeo.length > 0 ? (
            <p className="mt-2 text-3xs text-ink-muted">
              {t("suite.enSondeo", { cuantas: salud.en_sondeo.length })}
            </p>
          ) : null}
          {salud.sin_medir.length > 0 ? (
            <p className="mt-1 text-3xs text-ink-muted">
              {t("suite.sinMedir", { cuantas: salud.sin_medir.length })}
            </p>
          ) : null}
        </>
      )}

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <p className="text-2xs font-medium text-ink">
            {t("suite.credenciales")}
          </p>
          {/* Sin credenciales revisadas no se dice «al día»: no se ha mirado
              nada. Es la misma distinción que arriba con las conexiones. */}
          {credenciales !== null && credenciales.revisados === 0 ? (
            <p className="text-3xs text-ink-faint">
              {t("suite.credencialesSinRevisar")}
            </p>
          ) : piden.length === 0 ? (
            <p className="text-3xs text-ink-muted">
              {t("suite.credencialesAlDia", {
                revisados: credenciales?.revisados ?? 0,
              })}
            </p>
          ) : (
            <ul className="mt-1 space-y-0.5">
              {/* Las bombas de relojería primero: caducan con refresco ausente,
                  así que el día que lleguen dejan de entrar veinte buzones a la
                  vez y hay que volver a pedir autorización una por una. */}
              {rompibles.map((c) => (
                <li key={c.consentimiento_id} className="text-3xs text-danger">
                  {c.perfil} · {c.recurso}
                  {/* El porqué que manda el servidor, no «error de
                      autenticación»: ése es el mensaje que atasca una
                      implantación una semana. */}
                  <span className="text-ink-muted"> — {c.porque}</span>
                </li>
              ))}
              {otrasQuePiden.map((c) => (
                <li
                  key={c.consentimiento_id}
                  className="text-3xs text-ink-muted"
                >
                  {c.perfil} · {c.recurso} — {c.porque}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <p className="text-2xs font-medium text-ink">
            {t("suite.suscripciones")}
          </p>
          {porRenovar.length === 0 && sinDeclarar.length === 0 ? (
            <p className="text-3xs text-ink-muted">
              {t("suite.suscripcionesAlDia")}
            </p>
          ) : (
            <ul className="mt-1 space-y-0.5">
              {porRenovar.map((s) => (
                <li key={s.id} className="text-3xs text-ink-muted">
                  {s.recurso}
                  {s.caduca_at
                    ? ` — ${escalar(s.caduca_at, "caduca_at")}`
                    : null}
                </li>
              ))}
              {/* «Sin caducidad declarada» no es «no caduca»: es que no se
                  sabe, y se renueva igual por si acaso. El servidor sólo manda
                  sus identificadores, así que es lo que se enseña. */}
              {sinDeclarar.map((id) => (
                <li key={id} className="text-3xs text-ink-faint">
                  {t("suite.sinCaducidadDeclarada")} · {id.slice(0, 8)}
                </li>
              ))}
            </ul>
          )}
          {suscripciones?.aviso ? (
            <p className="mt-1 text-3xs text-ink-faint">
              {suscripciones.aviso}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}

interface SaludSuites {
  total: number;
  paradas: {
    conexion: string;
    horas_sin_sincronizar: number;
    estado: string | null;
    porque: string;
  }[];
  sin_medir: string[];
  en_sondeo: string[];
  todo_bien: boolean;
}

/** `GET /suite/simular`: qué se crearía, cambiaría o desactivaría. */
interface Simulacion {
  total_a_aplicar: number;
  ya_aplicadas: number;
}

/** `GET /suite/certificado-de-cierre`: una baja, en todas las herramientas. */
interface Cierre {
  abiertas: string[];
  cerradas: string[];
}

interface Cambio {
  id?: string;
  que?: string;
  accion?: string;
  herramienta?: string;
}

/** `GET /suites/credenciales/salud`: cuántas se miraron y cuáles piden algo. */
interface SaludCredenciales {
  revisados: number;
  que_piden_algo: {
    consentimiento_id: string;
    perfil: string;
    usuario_id: string;
    recurso: string;
    se_rompera_sola: boolean;
    renovar: boolean;
    avisar: boolean;
    fiable: boolean;
    caducada?: boolean;
    dias_que_quedan?: number;
    porque: string;
  }[];
}

/** `GET /suites/suscripciones/por-renovar`. `sin_caducidad_declarada` son
 *  identificadores sueltos, no registros: el servidor no manda más de ellas. */
interface Renovaciones {
  por_renovar: {
    id: string;
    recurso: string;
    usuario_id: string;
    caduca_at: string | null;
  }[];
  sin_caducidad_declarada: string[];
  aviso: string;
}

interface Apartado {
  id: string;
  herramienta: string;
  objeto: string;
  objeto_id: string;
  operacion: string;
  intentos: number;
  error: string | null;
  carga: Record<string, unknown>;
  gravedad: string;
}

/**
 * Lo apartado, con qué se mandó y con el botón de volver a intentarlo.
 *
 * Antes esta pantalla decía «hay 3 en cuarentena» y ahí se acababa: no había
 * forma de ver cuáles ni de reintentarlas, aunque las dos rutas existían en el
 * servidor desde el primer día. Un aviso sin salida enseña a quien lo lee a no
 * mirarlo, que es justo lo contrario de para lo que se apartó.
 *
 * Y se enseña **lo que se mandó**: sin eso, quien lo mira tiene que adivinar si
 * el problema es el dato o la herramienta.
 */
function Cuarentena({ alReintentar }: { alReintentar: () => void }) {
  const { t } = useTranslation();
  const puedeOperar = usePuedeOperar();
  const [filas, setFilas] = useState<Apartado[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [enviando, setEnviando] = useState("");

  useEffect(() => {
    const control = new AbortController();
    llamar<Apartado[]>("/api/v1/suite/cuarentena", { signal: control.signal })
      .then((r) => setFilas(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  async function reintentar(id: string) {
    setEnviando(id);
    try {
      await llamar(`/api/v1/suite/cuarentena/${id}/reintentar`, {
        metodo: "POST",
      });
      setFilas((previas) => (previas ?? []).filter((f) => f.id !== id));
      alReintentar();
    } catch (e) {
      setFallo(e);
    } finally {
      setEnviando("");
    }
  }

  if (fallo) return <Fallo error={fallo} />;
  if (!filas) return <Cargando />;

  const puede = puedeOperar("POST", "/api/v1/suite/cuarentena/{id}/reintentar");

  return (
    <Rejilla
      className="mt-2"
      cabeceras={[
        t("suite.herramienta"),
        t("suite.queSeMando"),
        t("suite.intentos"),
        t("suite.ultimoError"),
        "",
      ]}
    >
      {filas.map((f) => (
        <tr key={f.id} className="border-b border-ink-dim/30 last:border-0">
          <Casilla className="text-ink">{f.herramienta}</Casilla>
          <Casilla className="text-3xs text-ink-muted">
            {/* La baja se marca: es la única cuyo retraso deja un acceso
                abierto, y en una lista larga se pierde entre las demás. */}
            {f.gravedad === "alta" ? (
              <span className="text-danger">{t("suite.esUnaBaja")} </span>
            ) : null}
            {f.objeto}: {JSON.stringify(f.carga)}
          </Casilla>
          <Casilla className="text-ink-muted">{f.intentos}</Casilla>
          <Casilla className="text-3xs text-ink-faint">
            {f.error ?? "—"}
          </Casilla>
          <Casilla>
            {puede ? (
              <button
                type="button"
                onClick={() => void reintentar(f.id)}
                disabled={enviando === f.id}
                className="rounded border border-ink-dim/60 px-2 py-1 text-3xs text-ink disabled:opacity-50"
              >
                {enviando === f.id
                  ? t("suite.reintentando")
                  : t("suite.reintentar")}
              </button>
            ) : null}
          </Casilla>
        </tr>
      ))}
    </Rejilla>
  );
}

/**
 * «Esto no conecta. ¿Qué falta exactamente?» (CRM-06.01.03.20).
 *
 * «Error de autenticación» es el mensaje que atasca una implantación una
 * semana: el consultor no sabe si es la contraseña, el permiso, el inquilino o
 * el reloj, así que lo prueba todo y acaba pidiendo permisos de administrador
 * global «para descartar» — que es como una integración termina con más
 * permisos de los que nadie puede justificar.
 *
 * El servidor sabía contestarlo desde el principio y no había dónde
 * preguntarlo. Aquí se pega lo que diga el proveedor, se dicen los alcances que
 * tiene y los que hacen falta, y contesta qué pasa y qué hacer.
 *
 * **Los alcances se escriben separados por comas y no se piden en JSON**: lo
 * que el consultor tiene delante es la pantalla de consentimiento del
 * proveedor, que los lista así. Pedirle que los convierta a otra forma es
 * pedirle que haga de traductor para poder usar la herramienta.
 */
export function CuandoNoConecta() {
  const { t } = useTranslation();
  const [codigo, setCodigo] = useState("");
  const [concedidos, setConcedidos] = useState("");
  const [necesarios, setNecesarios] = useState("");
  const [mensaje, setMensaje] = useState("");
  const [veredicto, setVeredicto] = useState<Veredicto | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [mirando, setMirando] = useState(false);

  async function preguntar() {
    setMirando(true);
    setFallo(null);
    try {
      const r = await llamar<Veredicto>("/api/v1/suites/diagnostico", {
        metodo: "POST",
        cuerpo: {
          codigo: codigo.trim() === "" ? null : Number(codigo),
          alcances_concedidos: enLista(concedidos),
          alcances_necesarios: enLista(necesarios),
          mensaje_del_proveedor: mensaje,
        },
      });
      setVeredicto(r.datos);
    } catch (e: unknown) {
      setFallo(e);
    } finally {
      setMirando(false);
    }
  }

  return (
    <section className="card mt-6 p-4">
      <h2 className="section-label mb-1">{t("suite.noConecta")}</h2>
      <p className="mb-3 max-w-prose text-2xs text-ink-muted">
        {t("suite.noConectaPorque")}
      </p>

      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void preguntar();
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-2xs text-ink-muted">
            {t("suite.codigoHttp")}
            <input
              className="input-base"
              inputMode="numeric"
              value={codigo}
              onChange={(e) => setCodigo(e.target.value)}
              placeholder="401"
            />
          </label>
          <label className="flex flex-col gap-1 text-2xs text-ink-muted">
            {t("suite.mensajeDelProveedor")}
            <input
              className="input-base"
              value={mensaje}
              onChange={(e) => setMensaje(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-2xs text-ink-muted">
            {t("suite.alcancesConcedidos")}
            <input
              className="input-base"
              value={concedidos}
              onChange={(e) => setConcedidos(e.target.value)}
              placeholder="Mail.Read, Calendars.Read"
            />
          </label>
          <label className="flex flex-col gap-1 text-2xs text-ink-muted">
            {t("suite.alcancesNecesarios")}
            <input
              className="input-base"
              value={necesarios}
              onChange={(e) => setNecesarios(e.target.value)}
              placeholder="Mail.Read, Calendars.ReadWrite"
            />
          </label>
        </div>
        <div>
          <button type="submit" className="btn-primary" disabled={mirando}>
            {mirando ? t("suite.mirando") : t("suite.queFalla")}
          </button>
        </div>
      </form>

      {fallo ? <Fallo error={fallo} /> : null}
      {/* Se anuncia: el veredicto aparece debajo del botón y quien no ve la
          pantalla no se enteraría de que ya hay respuesta. */}
      <div role="status" aria-live="polite">
        {veredicto ? (
          <div
            className={`mt-3 rounded-lg border p-3 ${
              veredicto.ok
                ? "border-success/40 bg-success/5"
                : "border-warning/40 bg-warning/5"
            }`}
          >
            <p className="text-sm text-ink">{veredicto.que_pasa}</p>
            {veredicto.faltan_alcances?.length ? (
              <p className="mt-1 flex flex-wrap items-center gap-1 text-3xs">
                <span className="text-ink-faint">{t("suite.faltanEstos")}</span>
                {veredicto.faltan_alcances.map((a) => (
                  <span key={a} className="chip-dato">
                    {a}
                  </span>
                ))}
              </p>
            ) : null}
            {veredicto.que_hacer ? (
              <p className="mt-2 max-w-prose text-2xs text-ink-muted">
                {veredicto.que_hacer}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

/**
 * «Si lo desconecto, ¿qué me llevo y qué se queda?» (CRM-06.01.03.17).
 *
 * Nadie desconecta una integración sin saberlo, así que no se desconecta — y
 * queda un acceso vivo de alguien que ya no está, que es lo contrario de lo que
 * se quería.
 *
 * La respuesta no es simétrica y por eso hay que enseñarla entera: **las
 * actividades se quedan y la copia de su agenda se va**. Las primeras son el
 * registro de la empresa —quién habló con qué cliente y cuándo—; la segunda era
 * suya.
 */
export function AntesDeDesconectar() {
  const { t } = useTranslation();
  const [motivo, setMotivo] = useState("revocacion");
  const [plan, setPlan] = useState<PlanDeBaja | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<PlanDeBaja>(`/api/v1/suites/baja/${motivo}`, {
      signal: control.signal,
    })
      .then((r) => setPlan(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [motivo]);

  return (
    <section className="card mt-6 p-4">
      <h2 className="section-label mb-1">{t("suite.antesDeDesconectar")}</h2>
      <p className="mb-3 max-w-prose text-2xs text-ink-muted">
        {t("suite.antesDeDesconectarPorque")}
      </p>

      <label className="flex max-w-xs flex-col gap-1 text-2xs text-ink-muted">
        {t("suite.porQueSeDesconecta")}
        <select
          className="input-base"
          value={motivo}
          onChange={(e) => setMotivo(e.target.value)}
        >
          <option value="revocacion">{t("suite.motivoRevocacion")}</option>
          <option value="baja_del_usuario">{t("suite.motivoBaja")}</option>
          <option value="fin_del_contrato">
            {t("suite.motivoFinContrato")}
          </option>
        </select>
      </label>

      {fallo ? <Fallo error={fallo} /> : null}
      <div
        role="status"
        aria-live="polite"
        className="mt-3 grid gap-3 sm:grid-cols-2"
      >
        {plan ? (
          <>
            <Mitad
              titulo={t("suite.seQueda")}
              filas={plan.se_queda ?? []}
              tono="success"
            />
            <Mitad
              titulo={t("suite.seBorra")}
              filas={plan.se_borra ?? []}
              tono="danger"
            />
          </>
        ) : null}
      </div>
    </section>
  );
}

function Mitad({
  titulo,
  filas,
  tono,
}: {
  titulo: string;
  filas: { que: string; porque: string }[];
  tono: "success" | "danger";
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        tono === "success" ? "border-success/40" : "border-danger/40"
      }`}
    >
      <h3 className="section-label mb-2">{titulo}</h3>
      <ul className="lista-acotada space-y-2 pr-1">
        {filas.map((f, i) => (
          <li key={i}>
            <p className="text-2xs text-ink">{f.que}</p>
            {/* El porqué, siempre: sin él la lista es una norma que alguien
                discutirá, y con él es una decisión que se entiende. */}
            <p className="text-3xs text-ink-faint">{f.porque}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Los alcances se escriben separados por comas; aquí se parten y se limpian. */
function enLista(texto: string): string[] {
  return texto
    .split(/[,\s]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}
