/**
 * Consola única de gobierno de la suite (CRM-00.01.07.06).
 *
 * Enseña CRM-00.01.07.03 (el alta y la baja de usuario en cascada, y sobre
 * todo las bajas sin aplicar), CRM-00.01.07.07 (la divergencia entre lo que
 * dice cada herramienta y lo que decimos nosotros), CRM-00.01.07.10 (la cola de
 * aprovisionamiento con su cuarentena y su reintento) y CRM-00.01.07.12 (la
 * auditoría transversal).
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

      <p className="mt-6 text-3xs text-ink-faint">
        {t("suite.noEsControlRemoto")}
      </p>
    </>
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
  const [credenciales, setCredenciales] = useState<SaludCredenciales | null>(null);
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
      <p className="mb-3 text-3xs text-ink-faint">{t("suite.saludSuitesAyuda")}</p>

      {/* **Sin conexiones no se dice «todo bien».** Un panel que sólo cuenta lo
          sincronizado enseña un número que sube mientras tres buzones llevan
          una semana parados: el número es verdad y la impresión es falsa. */}
      {salud.total === 0 ? (
        <Vacio titulo={t("suite.sinConexiones")} detalle={t("suite.sinConexionesPorque")} compacto />
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
              ? t("suite.paradas", { cuantas: salud.paradas.length, total: salud.total })
              : t("suite.todasAlDia", { total: salud.total })}
          </p>

          {salud.paradas.length > 0 ? (
            <ul className="mt-2 divide-y divide-ink-dim/30">
              {salud.paradas.map((parada) => (
                <li key={parada.conexion} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
                  {/* Las horas paradas, delante: es el número que decide a cuál
                      se va primero. */}
                  <span className="text-sm font-semibold leading-none text-danger">
                    {t("suite.horasParada", { horas: parada.horas_sin_sincronizar })}
                  </span>
                  <span className="text-2xs text-ink">{parada.conexion}</span>
                  {parada.estado ? <span className="chip-dato">{parada.estado}</span> : null}
                  {/* Por qué, dicho por el servidor: «no sincroniza» sin motivo
                      obliga a abrir el registro del servidor, que es justo lo
                      que esta pantalla existe para evitar. */}
                  {parada.porque ? (
                    <span className="text-3xs text-ink-muted">{parada.porque}</span>
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
          <p className="text-2xs font-medium text-ink">{t("suite.credenciales")}</p>
          {/* Sin credenciales revisadas no se dice «al día»: no se ha mirado
              nada. Es la misma distinción que arriba con las conexiones. */}
          {credenciales !== null && credenciales.revisados === 0 ? (
            <p className="text-3xs text-ink-faint">{t("suite.credencialesSinRevisar")}</p>
          ) : piden.length === 0 ? (
            <p className="text-3xs text-ink-muted">
              {t("suite.credencialesAlDia", { revisados: credenciales?.revisados ?? 0 })}
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
                <li key={c.consentimiento_id} className="text-3xs text-ink-muted">
                  {c.perfil} · {c.recurso} — {c.porque}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <p className="text-2xs font-medium text-ink">{t("suite.suscripciones")}</p>
          {porRenovar.length === 0 && sinDeclarar.length === 0 ? (
            <p className="text-3xs text-ink-muted">{t("suite.suscripcionesAlDia")}</p>
          ) : (
            <ul className="mt-1 space-y-0.5">
              {porRenovar.map((s) => (
                <li key={s.id} className="text-3xs text-ink-muted">
                  {s.recurso}
                  {s.caduca_at ? ` — ${escalar(s.caduca_at, "caduca_at")}` : null}
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
            <p className="mt-1 text-3xs text-ink-faint">{suscripciones.aviso}</p>
          ) : null}
        </div>
      </div>
    </section>
  );
}

interface SaludSuites {
  total: number;
  paradas: { conexion: string; horas_sin_sincronizar: number; estado: string | null; porque: string }[];
  sin_medir: string[];
  en_sondeo: string[];
  todo_bien: boolean;
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
  por_renovar: { id: string; recurso: string; usuario_id: string; caduca_at: string | null }[];
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
          <Casilla className="text-3xs text-ink-faint">{f.error ?? "—"}</Casilla>
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
