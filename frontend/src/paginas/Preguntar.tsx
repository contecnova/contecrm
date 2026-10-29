/**
 * Nexus: pregúntale al sistema (CRM-05.02.03.01, CRM-05.02.03.05).
 *
 * **El agente autónomo no tenía dónde usarse.** Estaba entero por debajo —plan,
 * aprobación por riesgo, tope de acciones, presupuesto, reversión paso a paso—
 * y lo único que se veía de él era una fila en un listado de administración,
 * con un botón para apagarlo. `Chat.tsx` es chat entre personas,
 * `Consola.agente.tsx` es la cola de soporte y `/ia/asistencia` sugiere dentro
 * de una ficha: no había ningún sitio donde escribir «¿qué cuentas están en
 * riesgo y por qué?» y que el CRM lo hiciera.
 *
 * Las decisiones de esta pantalla, que son todas la misma: **lo que importa no
 * es la respuesta, es poder no fiarse de ella.**
 *
 * - **El plan se ve antes de que pase nada.** Es lo que distingue esto de una
 *   caja de texto mágica: se lee qué va a hacer, con qué herramienta y por qué,
 *   y se puede no dejarle.
 * - **Un paso cada vez, y el botón es del usuario.** El servidor ejecuta uno
 *   por llamada a propósito; una pantalla que los disparara todos de golpe
 *   convertiría el tope, el apagado y la aprobación en decoración. Aquí la
 *   pantalla va pidiendo el siguiente y **se detiene sola** en cuanto hace
 *   falta una persona.
 * - **El riesgo va al lado de cada paso, no en la letra pequeña.** Quien
 *   aprueba tiene que ver «escritura» antes de pulsar, no después.
 * - **Pensar también se cuenta.** Un agente iterativo alterna vueltas que
 *   ejecutan con vueltas que deciden el siguiente paso con el resultado
 *   delante. La pantalla lo dice en vez de parecer que no ha hecho nada.
 * - **Lo que no se puede deshacer se dice antes de ofrecer deshacer.** Un
 *   correo enviado no se «des-envía»; un botón de deshacer que no lo advierta
 *   es la peor promesa de todo el módulo.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { ErrorApi, filas, llamar } from "@/lib/api";

interface Agente {
  id: string;
  clave: string;
  tipo: string;
  descripcion?: string;
  modo?: string;
  activo?: boolean;
}

interface Paso {
  orden: number;
  herramienta: string;
  riesgo: string;
  porque: string;
  argumentos?: Record<string, unknown>;
  estado: string;
  error?: string;
  reversible: boolean;
}

interface Actuacion {
  ejecucion_id: string;
  objetivo: string;
  estado: string;
  modo?: string;
  motivo_fin?: string;
  tokens: number;
  pasos: Paso[];
  reversible_del_todo: boolean;
  no_reversibles: { orden: number; herramienta: string }[];
}

interface Vuelta {
  avanzado?: boolean;
  porque?: string;
  terminada?: boolean;
  detenida?: boolean;
  conclusion?: string;
  estado?: string;
  error?: string;
  paso_decidido?: {
    orden: number;
    herramienta: string;
    riesgo: string;
    porque: string;
  };
  herramientas_descartadas?: string[];
  esperando?: number[];
}

/** Si esta vuelta deja algo por hacer o si la ejecución ya no va a moverse sola. */
function seAcabo(v: Vuelta): boolean {
  if (v.terminada || v.detenida) return true;
  // Un paso fallido para la ejecución entera en el servidor; seguir pidiendo
  // vueltas sería pedirle que siga un plan que ya no tiene sentido.
  if (v.estado === "fallido") return true;
  // `avanzado: false` SIN paso decidido es «aquí hace falta una persona»: o
  // espera aprobación, o se ha descartado una herramienta. Con paso decidido
  // es una vuelta de pensar, y la siguiente lo ejecuta.
  return v.avanzado === false && !v.paso_decidido;
}

const COLOR_RIESGO: Record<string, string> = {
  lectura: "bg-ink-dim/15 text-ink-muted",
  escritura: "bg-warning/10 text-warning",
  destructivo: "bg-danger/10 text-danger",
};

/**
 * Los agentes que contestan en Nexus: los de consulta, y activos.
 *
 * Se ordena por clave para que, habiendo varios, conteste **siempre el mismo**:
 * el orden en que los devuelva el servidor no es una decisión de producto, y
 * que la respuesta dependa de él sería imposible de explicar.
 */
function asistentes(lista: Agente[]): Agente[] {
  return lista
    .filter((a) => a.activo !== false && a.tipo === "asistente_conversacional")
    .sort((a, b) => a.clave.localeCompare(b.clave));
}

export function Preguntar() {
  const { t } = useTranslation();
  const [agentes, setAgentes] = useState<Agente[] | null>(null);
  const [elegido, setElegido] = useState("");
  const [objetivo, setObjetivo] = useState("");
  const [actuacion, setActuacion] = useState<Actuacion | null>(null);
  const [ultima, setUltima] = useState<Vuelta | null>(null);
  const [trabajando, setTrabajando] = useState(false);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);
  // El bucle de vueltas se para si el usuario se va de la pantalla: dejarlo
  // corriendo contra un componente desmontado pinta sobre nada y sigue
  // gastando presupuesto del agente.
  const vivo = useRef(true);
  useEffect(() => () => void (vivo.current = false), []);

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<unknown>("/api/v1/ia/agentes-autonomos", { signal: control.signal })
      .then((r) => {
        const lista = filas<Agente>(r.datos);
        setAgentes(lista);
        // **Aquí no se elige nunca.** Nexus es la caja de «pregúntale al
        // sistema», y elegir agente es en realidad elegir con qué permisos y
        // con qué herramientas se contesta — que no es una pregunta para quien
        // escribe «qué cuentas están en riesgo».
        //
        // Contesta siempre un ASISTENTE. Los demás agentes hacen un trabajo
        // con un registro delante —proponer la respuesta de un caso, calificar
        // un lead— y su sitio es la pantalla de ese trabajo: ofrecerlos aquí
        // era dar a elegir entre cosas que no contestan la misma pregunta.
        const usables = asistentes(lista);
        if (usables[0]) setElegido(usables[0].clave);
      })
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  const leerActuacion = useCallback(async (id: string) => {
    const r = await llamar<Actuacion>(
      `/api/v1/ia/agentes-autonomos/ejecuciones/${id}`,
    );
    if (vivo.current) setActuacion(r.datos);
  }, []);

  async function preguntar() {
    if (!elegido || objetivo.trim().length < 3) return;
    setTrabajando(true);
    setFallo(null);
    setUltima(null);
    setActuacion(null);
    try {
      const r = await llamar<{ ejecucion_id: string }>(
        `/api/v1/ia/agentes-autonomos/${encodeURIComponent(elegido)}/lanzar`,
        { metodo: "POST", cuerpo: { objetivo: objetivo.trim(), contexto: {} } },
      );
      await leerActuacion(r.datos.ejecucion_id);
    } catch (e: unknown) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      if (vivo.current) setTrabajando(false);
    }
  }

  /**
   * Va pidiendo vueltas hasta que haga falta una persona o se acabe.
   *
   * Una llamada por vuelta, que es como está hecho el servidor: el tope de
   * acciones, el presupuesto y el apagado se comprueban entre una y otra. Esto
   * **no** es un atajo para ejecutarlo todo de golpe — es el mismo paso a paso,
   * sin obligar a pulsar un botón por cada uno.
   */
  async function seguir() {
    if (!actuacion) return;
    setTrabajando(true);
    setFallo(null);
    try {
      for (;;) {
        const r = await llamar<Vuelta>(
          `/api/v1/ia/agentes-autonomos/ejecuciones/${actuacion.ejecucion_id}/avanzar`,
          { metodo: "POST", cuerpo: {} },
        );
        if (!vivo.current) return;
        setUltima(r.datos);
        await leerActuacion(actuacion.ejecucion_id);
        if (!vivo.current || seAcabo(r.datos)) return;
      }
    } catch (e: unknown) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      if (vivo.current) setTrabajando(false);
    }
  }

  async function decidir(orden: number, aprobado: boolean) {
    if (!actuacion) return;
    // Se aprueba por identificador de paso, no por su orden: el orden es lo
    // que se lee en pantalla, y dos ejecuciones tienen un paso 1 cada una.
    const id = pasoId(actuacion, orden);
    if (!id) return;
    setTrabajando(true);
    try {
      await llamar(`/api/v1/ia/agentes-autonomos/pasos/${id}/aprobar`, {
        metodo: "POST",
        cuerpo: { aprobado, motivo: "" },
      });
      await leerActuacion(actuacion.ejecucion_id);
    } catch (e: unknown) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      if (vivo.current) setTrabajando(false);
    }
  }

  async function deshacer() {
    if (!actuacion) return;
    setTrabajando(true);
    try {
      await llamar(
        `/api/v1/ia/agentes-autonomos/ejecuciones/${actuacion.ejecucion_id}/revertir`,
        {
          metodo: "POST",
          cuerpo: {},
        },
      );
      await leerActuacion(actuacion.ejecucion_id);
    } catch (e: unknown) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      if (vivo.current) setTrabajando(false);
    }
  }

  if (fallo && !actuacion) return <Fallo error={fallo} reintentar={cargar} />;
  if (!agentes) return <Cargando />;

  const usables = asistentes(agentes);
  const esperando = (actuacion?.pasos ?? []).filter(
    (p) => p.estado === "esperando_aprobacion",
  );
  const hechos = (actuacion?.pasos ?? []).filter((p) => p.estado === "hecho");
  const terminada = ["terminada", "fallida", "detenida", "revertida"].includes(
    actuacion?.estado ?? "",
  );

  return (
    <div className="flex flex-col gap-4">
      <CabeceraPagina
        titulo={t("preguntar.titulo")}
        entradilla={t("preguntar.entradilla")}
        icono="smart_toy"
      />

      {usables.length === 0 ? (
        // Y se dice QUÉ falta, no sólo que no hay: un agente es configuración,
        // y quien abre esto no tiene por qué saber que se declara en otra
        // pantalla.
        <Vacio
          titulo={t("preguntar.sinAgentes")}
          detalle={t("preguntar.sinAgentesDetalle")}
        />
      ) : (
        <form
          className="flex flex-col gap-3 rounded-lg border border-ink-dim/40 bg-paper-light p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void preguntar();
          }}
        >
          {/* Se DICE quién responde en vez de callarlo: el asistente decide
              qué herramientas usa y hasta dónde llega, así que saber cuál es
              forma parte de poder no fiarse de la respuesta. Lo que sobra es
              el desplegable, no el dato. */}
          <p className="text-sm text-ink-muted">
            {t("preguntar.quienResponde")}:{" "}
            <span className="text-ink">{usables[0]?.clave}</span>
            {usables[0]?.modo === "iterativo"
              ? ` · ${t("preguntar.modoIterativo")}`
              : ""}
          </p>
          <label className="flex flex-col gap-1 text-sm text-ink-muted">
            {t("preguntar.quePides")}
            <textarea
              className="input-base min-h-20"
              value={objetivo}
              onChange={(e) => setObjetivo(e.target.value)}
              placeholder={t("preguntar.ejemplo")}
            />
          </label>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              className="btn-primary"
              disabled={trabajando || !elegido || objetivo.trim().length < 3}
            >
              {t("preguntar.planificar")}
            </button>
            {/* Dicho antes de pulsar y no después: lo que devuelve este botón
                es un plan, no un resultado. */}
            <span className="text-2xs text-ink-faint">
              {t("preguntar.noEjecutaNada")}
            </span>
          </div>
        </form>
      )}

      {fallo && actuacion ? <Fallo error={fallo} /> : null}

      {actuacion ? (
        <section className="flex flex-col gap-3 rounded-lg border border-ink-dim/40 bg-paper-light p-4">
          <header className="flex flex-wrap items-baseline gap-2">
            <h2 className="flex-1 text-sm font-medium text-ink">
              {actuacion.objetivo}
            </h2>
            <span className="rounded bg-ink-dim/15 px-1.5 py-0.5 text-3xs uppercase text-ink-muted">
              {actuacion.estado}
            </span>
            <span className="font-mono text-2xs text-ink-faint">
              {t("preguntar.tokens", { tokens: actuacion.tokens })}
            </span>
          </header>

          {actuacion.pasos.length === 0 ? (
            <p className="text-sm text-ink-muted">{t("preguntar.sinPasos")}</p>
          ) : (
            <ol className="flex flex-col gap-2">
              {actuacion.pasos.map((p) => (
                <li
                  key={p.orden}
                  className="flex flex-wrap items-baseline gap-2 rounded border border-ink-dim/30 p-2"
                >
                  <span className="font-mono text-2xs text-ink-faint">
                    {p.orden}
                  </span>
                  <span className="flex-1 text-sm text-ink">
                    {p.porque || p.herramienta}
                    <span className="ml-2 font-mono text-2xs text-ink-faint">
                      {p.herramienta}
                    </span>
                  </span>
                  {/* El riesgo, antes de aprobar y no en la letra pequeña. */}
                  <span
                    className={`rounded px-1.5 py-0.5 text-3xs uppercase ${
                      COLOR_RIESGO[p.riesgo] ?? COLOR_RIESGO.lectura
                    }`}
                  >
                    {p.riesgo}
                  </span>
                  <span className="rounded bg-ink-dim/15 px-1.5 py-0.5 text-3xs uppercase text-ink-muted">
                    {p.estado}
                  </span>
                  {p.error ? (
                    <span className="w-full text-2xs text-danger">
                      {p.error}
                    </span>
                  ) : null}
                  {p.estado === "esperando_aprobacion" ? (
                    <span className="flex gap-2">
                      <button
                        type="button"
                        className="btn-primary"
                        disabled={trabajando}
                        onClick={() => void decidir(p.orden, true)}
                      >
                        {t("preguntar.autorizar")}
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={trabajando}
                        onClick={() => void decidir(p.orden, false)}
                      >
                        {t("preguntar.rechazar")}
                      </button>
                    </span>
                  ) : null}
                </li>
              ))}
            </ol>
          )}

          {/* Lo que ha pasado al pulsar, en una región que se anuncia. Sin
            esto, quien no ve la pantalla pulsa «seguir» y no se entera de
            nada: ni de que el agente ha pensado, ni de que ha terminado, ni
            de que está esperando a una persona. */}
          <div role="status" aria-live="polite" className="flex flex-col gap-2">
            {/* La vuelta que piensa se cuenta: si no, parece que el botón no ha
              hecho nada cuando lo que ha hecho es decidir el paso siguiente. */}
            {ultima?.paso_decidido ? (
              <p className="flex items-start gap-2 text-sm text-ink-muted">
                <Icono nombre="psychology" tamano="sm" />
                <span>
                  {t("preguntar.haPensado")}{" "}
                  <span className="text-ink">
                    {ultima.paso_decidido.porque}
                  </span>
                </span>
              </p>
            ) : null}
            {ultima?.conclusion ? (
              <p className="rounded bg-accent/5 p-3 text-sm text-ink">
                {ultima.conclusion}
              </p>
            ) : null}
            {terminada && actuacion.motivo_fin ? (
              <p className="text-2xs text-ink-faint">
                {t("preguntar.paroPorque")} {actuacion.motivo_fin}
              </p>
            ) : null}
            {ultima?.herramientas_descartadas?.length ? (
              <p className="text-2xs text-warning">
                {t("preguntar.pidioLoQueNoTiene")}{" "}
                {ultima.herramientas_descartadas.join(", ")}
              </p>
            ) : null}
            {esperando.length > 0 ? (
              <p className="text-2xs text-warning">
                {t("preguntar.esperaAPersona", { count: esperando.length })}
              </p>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {!terminada ? (
              <button
                type="button"
                className="btn-primary"
                disabled={trabajando || esperando.length > 0}
                onClick={() => void seguir()}
              >
                {trabajando ? t("preguntar.trabajando") : t("preguntar.seguir")}
              </button>
            ) : null}
            {hechos.length > 0 && actuacion.estado !== "revertida" ? (
              <button
                type="button"
                className="btn-secondary"
                disabled={trabajando}
                onClick={() => void deshacer()}
              >
                {t("preguntar.deshacer")}
              </button>
            ) : null}
          </div>

          {/* Antes de ofrecer deshacer, lo que no va a deshacerse. Un botón de
              deshacer que no lo advierta hace confiar en una reversión que no
              es total. */}
          {hechos.length > 0 && !actuacion.reversible_del_todo ? (
            <p className="text-2xs text-danger">
              {t("preguntar.noTodoSeDeshace")}{" "}
              {actuacion.no_reversibles.map((n) => n.herramienta).join(", ")}
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

/** El identificador del paso, que la actuación trae junto al orden. */
function pasoId(actuacion: Actuacion, orden: number): string | null {
  const p = actuacion.pasos.find((x) => x.orden === orden) as
    (Paso & { id?: string }) | undefined;
  return p?.id ?? null;
}
