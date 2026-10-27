/**
 * Identidad y seguridad: las cuatro preguntas que nadie podía contestar
 * (CRM-00.05.01.15, CRM-00.05.01.17, CRM-00.05.01.25, CRM-00.05.02.11,
 * CRM-07.03.02.06).
 *
 * Lo que esta pantalla **no** declara, aunque lo roce: `CRM-00.05.01.06` —MFA
 * obligatoria configurable por rol— porque aquí se ve si está puesta y no se
 * configura, y declarar lo que no se hace es justo lo que esta traza existe
 * para impedir.
 *
 * El módulo genérico «Identidad y acceso» ya lista lo que es una colección:
 * usuarios, roles, políticas, claves de API, sesiones, dispositivos y
 * proveedores. Lo que no puede listar es lo que **no es una tabla**, y resulta
 * que es justo lo que un administrador necesita saber:
 *
 *   · **quién no tiene segundo factor.** Un panel que diga «78 %» no sirve: el
 *     trabajo es hablar con los que faltan, así que lo que hace falta es la
 *     lista. Y separada por fuerza del factor, porque «tiene MFA» mete en el
 *     mismo saco una passkey y un SMS;
 *   · **qué certificado del proveedor de identidad caduca.** Un certificado de
 *     IdP que caduca no avisa: un sábado por la noche deja de validar toda
 *     aserción y el lunes no entra nadie de la empresa;
 *   · **quién tiene hoy permisos incompatibles.** Se calcula en vivo y no se
 *     guarda, porque una lista de conflictos vieja es peor que ninguna: se
 *     actúa sobre ella. Los que tienen excepción vigente salen igual, marcados;
 *   · **por qué esta persona puede (o no) hacer esto.** Sin el explicador, la
 *     respuesta se busca leyendo roles, políticas y reglas de compartición a la
 *     vez, y se contesta mal.
 *
 * Las cuatro son preguntas, no tablas, y por eso cada una se abre con su
 * respuesta —el número que importa— y debajo el detalle. Un listado de todo lo
 * que hay obliga a buscar el problema; esto lo pone delante.
 *
 * Nada de esto decide permisos: los pide, y el servidor contesta 403 a quien no
 * deba verlos. Lo que sí hace es no ofrecer lo que ya se sabe que va a dar 403.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { ErrorApi, llamar, salvoCancelacion } from "@/lib/api";
import { puede, type Sesion } from "@/lib/sesion";

interface UsuarioMfa {
  usuario_id: string;
  email: string;
  nombre: string;
  roles: string[];
  ultimo_acceso_at: string | null;
  factor?: string;
  fuerza?: number;
}

interface Adopcion {
  total_usuarios: number;
  con_factor: number;
  sin_factor: number;
  adopcion_pct: number | null;
  medible: boolean;
  mfa_obligatoria: boolean;
  usuarios_sin_factor: UsuarioMfa[];
  canales_debiles_activos: string[];
  aviso: string;
}

interface Certificado {
  proveedor_id: string;
  proveedor: string;
  huella: string;
  caduca_at: string | null;
  dias_restantes: number | null;
  estado: "vigente" | "por_caducar" | "caducado" | "sin_fecha";
}

interface Violacion {
  usuario_id: string;
  regla: string;
  nombre: string;
  nivel: string;
  por_el_lado_a: string[];
  por_el_lado_b: string[];
  exento?: boolean;
}

/** `GET /factores/nivel`: con qué ha entrado esta sesión. */
interface Nivel {
  nivel: number;
  factores: { factor: string; at: string }[];
  factor_fuerte_at: string | null;
}

/** `GET /factores/plan-de-inscripcion`: qué falta para tenerlo en condiciones. */
interface Plan {
  activos: string[];
  pasos: { paso: string; porque: string }[];
  completo: boolean;
  porque: string;
}

interface Operacion {
  clave: string;
  descripcion: string;
}

/** `GET /factores/cambio-de-dispositivo`: qué camino hay al cambiar de móvil. */
interface Cambio {
  puede_solo: boolean;
  camino: string;
  aprobadores_necesarios: number;
  porque: string;
}

interface Passkey {
  id: string;
  nombre?: string;
}

export function Seguridad({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  const [adopcion, setAdopcion] = useState<Adopcion | null>(null);
  const [certificados, setCertificados] = useState<Certificado[] | null>(null);
  const [sod, setSod] = useState<{ violaciones: Violacion[]; reglas: number } | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    // Las tres a la vez: en serie, la pantalla tarda la suma y se lee como
    // lenta aunque cada una vaya rápida.
    Promise.all([
      llamar<Adopcion>("/api/v1/factores/adopcion", { signal: control.signal }),
      llamar<{ certificados: Certificado[] }>("/api/v1/sso-gobierno/certificados", {
        signal: control.signal,
      }),
      llamar<{ violaciones: Violacion[]; reglas: number }>("/api/v1/segregacion/violaciones", {
        signal: control.signal,
      }),
    ])
      .then(([a, c, s]) => {
        setAdopcion(a.datos);
        setCertificados(c.datos.certificados ?? []);
        setSod(s.datos);
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!adopcion || !certificados || !sod) return <Cargando />;

  return (
    <div className="flex flex-col gap-6">
      <CabeceraPagina
        titulo={t("seguridad.titulo")}
        entradilla={t("seguridad.entradilla")}
        icono="shield_person"
      />

      <SegundoFactor datos={adopcion} />
      {/* Y lo de UNA persona, que es lo que no contesta el porcentaje: el
          administrador ve quién no tiene factor; quien entra necesita saber
          qué le falta a él, qué operaciones le van a pedir verificarse otra
          vez, y qué pasa el día que cambie de móvil — que es la llamada que
          más veces acaba en un desbloqueo manual, la puerta de atrás de toda
          la MFA. Las cuatro rutas estaban servidas y sin pantalla. */}
      <MiSegundoFactor />
      <Certificados filas={certificados} />
      <Segregacion datos={sod} />
      {puede(sesion, "user:read") ? <Explicador /> : null}
    </div>
  );
}

/**
 * Lo que le falta a QUIEN mira, no al conjunto.
 *
 * Un panel de adopción dice «78 %» y el trabajo que genera es hablar con los
 * que faltan. Esto contesta lo otro: con qué he entrado hoy, qué me falta para
 * tener el segundo factor en condiciones, qué operaciones me van a pedir
 * verificarme otra vez y qué camino hay si cambio de móvil.
 *
 * Lo último importa más de lo que parece: sin factor viejo ni respaldo, lo
 * único que demuestra quién es alguien es que otras personas respondan por
 * ella, y el desbloqueo manual es la puerta de atrás de toda la MFA. Decirlo
 * ANTES, en frío, es lo que evita descubrirlo en caliente.
 */
function MiSegundoFactor() {
  const { t } = useTranslation();
  const [nivel, setNivel] = useState<Nivel | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [sensibles, setSensibles] = useState<Operacion[] | null>(null);
  const [cambio, setCambio] = useState<Cambio | null>(null);
  const [passkeys, setPasskeys] = useState<Passkey[] | null>(null);

  useEffect(() => {
    const control = new AbortController();
    const opciones = { signal: control.signal };
    // Cada una con su fallo: que no se pueda leer el plan no puede dejar sin
    // ver con qué se ha entrado.
    void llamar<Nivel>("/api/v1/factores/nivel", opciones)
      .then((r) => setNivel(r.datos))
      .catch(() => undefined);
    void llamar<Plan>("/api/v1/factores/plan-de-inscripcion", opciones)
      .then((r) => setPlan(r.datos))
      .catch(() => undefined);
    void llamar<{ operaciones: Operacion[] }>("/api/v1/factores/operaciones-sensibles", opciones)
      .then((r) => setSensibles(r.datos.operaciones ?? []))
      .catch(() => undefined);
    void llamar<Cambio>("/api/v1/factores/cambio-de-dispositivo", opciones)
      .then((r) => setCambio(r.datos))
      .catch(() => undefined);
    void llamar<Passkey[]>("/api/v1/auth/passkeys", opciones)
      .then((r) => setPasskeys(Array.isArray(r.datos) ? r.datos : []))
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  if (!nivel && !plan && !cambio) return null;

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">{t("seguridad.mio.titulo")}</h2>

      {plan ? (
        <p className={`text-2xs ${plan.completo ? "text-ink-muted" : "text-warning"}`}>
          {plan.porque}
        </p>
      ) : null}

      {/* Los pasos que faltan, con el porqué de cada uno: «inscribe un
          respaldo» sin decir que perder el móvil obliga a un desbloqueo
          manual se lee como una recomendación opcional. */}
      {plan?.pasos?.length ? (
        <ul className="space-y-1">
          {plan.pasos.map((paso) => (
            <li key={paso.paso} className="rounded-lg bg-paper-sunk px-3 py-2">
              <p className="text-2xs text-ink">{t(`seguridad.mio.${paso.paso}`, paso.paso)}</p>
              <p className="text-3xs text-ink-faint">{paso.porque}</p>
            </li>
          ))}
        </ul>
      ) : null}

      <p className="text-3xs text-ink-faint">
        {t("seguridad.mio.entradaDeHoy", {
          factores: (nivel?.factores ?? []).map((f) => f.factor).join(", ") || "—",
        })}
        {passkeys ? ` · ${t("seguridad.mio.passkeys", { cuantas: passkeys.length })}` : ""}
      </p>

      {/* Qué va a pedir verificarse otra vez. Saberlo antes evita la sorpresa
          en mitad de una operación que no se puede dejar a medias. */}
      {sensibles?.length ? (
        <p className="text-3xs text-ink-faint">
          {t("seguridad.mio.sensibles")}:{" "}
          {sensibles.map((o) => o.descripcion).join(" · ")}
        </p>
      ) : null}

      {cambio ? (
        <p className="text-3xs text-ink-faint">{cambio.porque}</p>
      ) : null}
    </section>
  );
}

/** Quién no tiene segundo factor. El trabajo es hablar con ellos. */
function SegundoFactor({ datos }: { datos: Adopcion }) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">{t("seguridad.mfa.titulo")}</h2>
      {/* El porcentaje va con el N al lado: un 78 % sobre nueve personas no es
          lo mismo que sobre novecientas, y sin el N se lee igual. */}
      <p className="text-2xs text-ink-muted">
        {datos.medible
          ? t("seguridad.mfa.resumen", {
              pct: datos.adopcion_pct,
              con: datos.con_factor,
              total: datos.total_usuarios,
            })
          : t("seguridad.mfa.sinUsuarios")}
      </p>
      {!datos.mfa_obligatoria ? (
        <p className="text-3xs text-warning">{t("seguridad.mfa.noObligatoria")}</p>
      ) : null}
      {datos.canales_debiles_activos.length > 0 ? (
        <p className="text-3xs text-warning">
          {t("seguridad.mfa.canalesDebiles", {
            canales: datos.canales_debiles_activos.join(", "),
          })}
        </p>
      ) : null}
      {datos.usuarios_sin_factor.length === 0 ? (
        <Vacio titulo={t("seguridad.mfa.todos")} detalle={t("seguridad.mfa.todosDetalle")} />
      ) : (
        <ul className="divide-y divide-ink-dim/30 overflow-hidden rounded-lg border border-ink-dim/40">
          {datos.usuarios_sin_factor.map((u) => (
            <li key={u.usuario_id} className="flex flex-wrap items-baseline gap-x-3 px-3 py-1.5">
              <span className="min-w-0 flex-1 truncate text-2xs text-ink">{u.nombre}</span>
              <span className="truncate font-mono text-3xs text-ink-muted">{u.email}</span>
              <span className="text-3xs text-ink-faint">{u.roles.join(", ")}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Qué certificado del IdP caduca, y cuándo. */
function Certificados({ filas }: { filas: Certificado[] }) {
  const { t } = useTranslation();
  // Primero los que ya caducaron, luego los que van a caducar: el orden es el
  // de la urgencia, no el del nombre del proveedor.
  const orden = { caducado: 0, por_caducar: 1, sin_fecha: 2, vigente: 3 } as const;
  const ordenadas = [...filas].sort((a, b) => orden[a.estado] - orden[b.estado]);
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">{t("seguridad.certificados.titulo")}</h2>
      <p className="text-3xs text-ink-faint">{t("seguridad.certificados.porQue")}</p>
      {ordenadas.length === 0 ? (
        <Vacio
          titulo={t("seguridad.certificados.ninguno")}
          detalle={t("seguridad.certificados.ningunoDetalle")}
        />
      ) : (
        <ul className="divide-y divide-ink-dim/30 overflow-hidden rounded-lg border border-ink-dim/40">
          {ordenadas.map((c) => (
            <li
              key={`${c.proveedor_id}:${c.huella}`}
              className="flex flex-wrap items-baseline gap-x-3 px-3 py-1.5"
            >
              <span
                className={`badge ${
                  c.estado === "caducado"
                    ? "badge-danger"
                    : c.estado === "por_caducar"
                      ? "badge-warning"
                      : ""
                }`}
              >
                {t(`seguridad.certificados.estado.${c.estado}`)}
              </span>
              <span className="min-w-0 flex-1 truncate text-2xs text-ink">{c.proveedor}</span>
              <span className="truncate font-mono text-3xs text-ink-faint">
                {c.huella.slice(0, 16)}
              </span>
              <span className="font-mono text-3xs text-ink-muted">
                {c.dias_restantes === null
                  ? t("seguridad.certificados.sinFecha")
                  : t("seguridad.certificados.dias", { dias: c.dias_restantes })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Quién tiene hoy permisos incompatibles. */
function Segregacion({ datos }: { datos: { violaciones: Violacion[]; reglas: number } }) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">{t("seguridad.sod.titulo")}</h2>
      <p className="text-3xs text-ink-faint">
        {t("seguridad.sod.porQue", { reglas: datos.reglas })}
      </p>
      {datos.violaciones.length === 0 ? (
        <Vacio
          titulo={t(datos.reglas === 0 ? "seguridad.sod.sinReglas" : "seguridad.sod.ninguna")}
          detalle={t(
            datos.reglas === 0 ? "seguridad.sod.sinReglasDetalle" : "seguridad.sod.ningunaDetalle",
          )}
        />
      ) : (
        <ul className="divide-y divide-ink-dim/30 overflow-hidden rounded-lg border border-ink-dim/40">
          {datos.violaciones.map((v, i) => (
            <li key={`${v.usuario_id}:${v.regla}:${i}`} className="px-3 py-2">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="badge">{v.nivel}</span>
                <span className="min-w-0 flex-1 truncate text-2xs text-ink">{v.nombre}</span>
                {/* La excepción no esconde el conflicto: lo marca. Esconderlo
                    haría que una excepción caducada pasara de «aprobado» a «no
                    existe» sin que nadie lo viera. */}
                {v.exento ? (
                  <span className="badge badge-warning">{t("seguridad.sod.conExcepcion")}</span>
                ) : null}
                <span className="font-mono text-3xs text-ink-faint">{v.usuario_id.slice(0, 8)}</span>
              </div>
              <p className="mt-0.5 font-mono text-3xs text-ink-muted">
                {v.por_el_lado_a.join(", ")} ↔ {v.por_el_lado_b.join(", ")}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Por qué esta persona puede (o no) hacer esto. */
function Explicador() {
  const { t } = useTranslation();
  const [usuario, setUsuario] = useState("");
  const [objeto, setObjeto] = useState("");
  const [accion, setAccion] = useState("read");
  const [salida, setSalida] = useState<unknown>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);
  const [pidiendo, setPidiendo] = useState(false);

  async function preguntar() {
    setPidiendo(true);
    setFallo(null);
    try {
      const r = await llamar<unknown>("/api/v1/roles/explicar", {
        metodo: "POST",
        cuerpo: { usuario_id: usuario, objeto, accion, registro: {} },
      });
      setSalida(r.datos);
    } catch (e: unknown) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      setPidiendo(false);
    }
  }

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">{t("seguridad.explicador.titulo")}</h2>
      <p className="text-3xs text-ink-faint">{t("seguridad.explicador.porQue")}</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-3xs text-ink-muted">{t("seguridad.explicador.usuario")}</span>
          <input
            value={usuario}
            onChange={(e) => setUsuario(e.target.value)}
            className="input-base font-mono"
            placeholder="uuid"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-3xs text-ink-muted">{t("seguridad.explicador.objeto")}</span>
          <input
            value={objeto}
            onChange={(e) => setObjeto(e.target.value)}
            className="input-base"
            placeholder="opportunity"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-3xs text-ink-muted">{t("seguridad.explicador.accion")}</span>
          <input
            value={accion}
            onChange={(e) => setAccion(e.target.value)}
            className="input-base"
          />
        </label>
        <button
          type="button"
          className="btn-primary"
          disabled={pidiendo || usuario.trim() === "" || objeto.trim() === ""}
          onClick={() => void preguntar()}
        >
          {t("seguridad.explicador.preguntar")}
        </button>
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      {/* La respuesta se anuncia: quien no ve la pantalla pulsa y no se entera
          de que ya está contestado. */}
      <div role="status" aria-live="polite">
        {salida ? (
          <pre className="overflow-x-auto rounded-lg border border-ink-dim/40 p-3 text-3xs text-ink">
            {JSON.stringify(salida, null, 2)}
          </pre>
        ) : null}
      </div>
    </section>
  );
}
