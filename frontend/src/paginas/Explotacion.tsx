/**
 * La pantalla de explotación (CRM-05.01.04.01, CRM-05.01.04.03,
 * CRM-05.01.04.04, CRM-05.01.04.06, CRM-05.01.04.08).
 *
 * Cuatro de esas cinco las hacía ya y no las declaraba: **canjea la credencial
 * de aplicación por un token del usuario** en el servidor —que es lo que hace
 * que la consulta analítica no devuelva lo que esa persona no podría ver—,
 * **registra el CRM como fuente consultable**, **guarda y publica preguntas**
 * y **explica la degradación** diciendo qué sigue funcionando cuando la
 * explotación no responde.
 *
 * Lo que esta pantalla **no** declara, aunque lo roce: `CRM-05.01.04.05`, la
 * propagación de permisos. La hace —por eso se canjea el token aquí— pero no
 * la enseña, y declarar lo que no se ve es justo lo que la traza impide.
 *
 * Aquí se pregunta y se ven las respuestas **sin salir del CRM**. La consulta la
 * resuelve contecintelligence (RT-4): esta pantalla no calcula nada, no agrega
 * nada y no interpreta los datos. Pide, enseña y guarda la pregunta.
 *
 * Dos decisiones que se ven al usarla:
 *
 * **Cuando la explotación no está disponible, se dice qué SÍ funciona.** Un
 * «servicio no disponible» a secas deja a quien lo lee creyendo que su CRM se ha
 * caído. No se ha caído: lo que no funciona es preguntar. El diagnóstico llega
 * del servidor —no se deduce aquí— porque la lista de motivos depende de
 * configuración que el navegador no ve.
 *
 * **Las preguntas guardadas se separan en «mías» y «publicadas».** Sin esa
 * distinción, una pregunta a medio afinar aparece en la lista de todos y se usa
 * como si estuviera bien.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { RespuestaAnalitica, type Payload } from "@/componentes/RespuestaAnalitica";
import { ErrorApi, llamar } from "@/lib/api";

interface Diagnostico {
  puede_preguntar: boolean;
  problemas: string[];
  sigue_funcionando: string[];
  no_funciona: string[];
  /** Dirección de contecintelligence **para el navegador**, no la interna. */
  url_publica: string;
  /** Identificador de la fuente allí: `/api/ask` exige decir sobre qué se pregunta. */
  fuente_id: string;
}

/** Ejemplos que se ponen delante de la caja vacía.
 *
 * Una caja de texto sin nada alrededor tiene una barrera que no se ve: «¿y qué
 * le pregunto?». Con seis ejemplos delante, la primera pregunta es un clic, y a
 * la segunda ya se escribe solo. */
const EJEMPLOS = [
  "¿Cuántas oportunidades hay abiertas por etapa?",
  "Importe total de los presupuestos",
  "Ingreso previsto para el próximo trimestre por comercial",
  "Casos abiertos por cliente y prioridad",
  "Cuentas sin actividad en los últimos 90 días",
  "Descuento medio concedido por familia de producto",
];

interface Pregunta {
  id: string;
  clave: string;
  titulo: string;
  pregunta: string;
  publicada: boolean;
  propia: boolean;
  informe_id: string | null;
  veces_usada: number;
}

export function Explotacion() {
  const { t } = useTranslation();
  const [diagnostico, setDiagnostico] = useState<Diagnostico | null>(null);
  const [preguntas, setPreguntas] = useState<Pregunta[] | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    Promise.all([
      llamar<Diagnostico>("/api/v1/explotacion/diagnostico", { signal: control.signal }),
      llamar<Pregunta[]>("/api/v1/explotacion/preguntas", { signal: control.signal }),
    ])
      .then(([d, p]) => {
        setDiagnostico(d.datos);
        setPreguntas(p.datos);
      })
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!diagnostico || !preguntas) return <Cargando />;

  const mias = preguntas.filter((p) => p.propia && !p.publicada);
  const publicadas = preguntas.filter((p) => p.publicada);

  return (
    <div className="flex flex-col gap-6">
      <CabeceraPagina
        titulo={t("explotacion.titulo")}
        entradilla={t("explotacion.entradilla")}
        icono="query_stats"
      />

      {!diagnostico.puede_preguntar ? (
        <section
          className="rounded-lg border border-warning/40 bg-warning/5 p-4"
          role="status"
          aria-live="polite"
        >
          <h2 className="text-sm font-medium text-warning">
            {t("explotacion.noDisponible")}
          </h2>
          <ul className="mt-2 list-disc pl-5 text-2xs text-ink-muted">
            {diagnostico.problemas.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
          {/* Lo que sigue funcionando va en la MISMA tarjeta y no en otra: quien
              lee un aviso en rojo cierra la pantalla, y si la tranquilidad está
              más abajo no la lee nadie. */}
          <h3 className="mt-3 text-2xs font-medium text-ink">
            {t("explotacion.sigueFuncionando")}
          </h3>
          <ul className="mt-1 list-disc pl-5 text-2xs text-ink-muted">
            {diagnostico.sigue_funcionando.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <BotonRegistrar alTerminar={cargar} />
        </section>
      ) : (
        <Preguntar diagnostico={diagnostico} />
      )}

      <section>
        <h2 className="text-sm font-medium text-ink">{t("explotacion.publicadas")}</h2>
        {publicadas.length === 0 ? (
          <Vacio titulo={t("explotacion.sinPublicadas")} detalle={t("explotacion.sinPublicadasDetalle")} />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {publicadas.map((p) => (
              <Tarjeta key={p.id} pregunta={p} />
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="text-sm font-medium text-ink">{t("explotacion.mias")}</h2>
        {mias.length === 0 ? (
          <Vacio titulo={t("explotacion.sinMias")} detalle={t("explotacion.sinMiasDetalle")} />
        ) : (
          <ul className="mt-2 flex flex-col gap-2">
            {mias.map((p) => (
              <Tarjeta key={p.id} pregunta={p} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/**
 * Dar de alta el CRM como fuente consultable. Un botón, no un formulario.
 *
 * Todo lo que hace falta —una credencial de solo lectura, la lista de objetos
 * consultables y su forma de paginar— lo averigua el servidor. Pedirle a una
 * persona que pegue eso en un formulario es pedirle que escriba JSON, y eso no
 * es una pantalla: es un fichero de configuración con bordes redondeados.
 */
function BotonRegistrar({ alTerminar }: { alTerminar: () => void }) {
  const { t } = useTranslation();
  const [enCurso, setEnCurso] = useState(false);
  const [fallo, setFallo] = useState<string | null>(null);

  /**
   * Lo pide y **espera a que termine**, preguntando por el trabajo.
   *
   * El alta no es una petición: recorre la superficie del CRM y prueba los
   * cuarenta y siete listados para medir la forma de cada uno. Doce segundos, y
   * el gateway corta a diez. El servidor contesta 202 con un identificador y
   * esto pregunta por él hasta que acaba.
   *
   * Se sondea desde aquí y no se deja al usuario refrescando: pulsar un botón y
   * que no pase nada visible es indistinguible de que no funcione.
   */
  async function registrar() {
    setEnCurso(true);
    setFallo(null);
    try {
      const alta = await llamar<{ consultar_en: string }>(
        "/api/v1/explotacion/registrar-fuente",
        { metodo: "POST" },
      );
      const donde = alta.datos.consultar_en;
      // Tope de espera: unos dos minutos. Sin tope, un worker caído deja el
      // botón girando para siempre y nadie sabe si sigue vivo.
      for (let intento = 0; intento < 60; intento += 1) {
        await new Promise((r) => setTimeout(r, 2000));
        const ficha = await llamar<{ estado: string; error?: string | null }>(donde);
        if (ficha.datos.estado === "completado") {
          alTerminar();
          return;
        }
        if (ficha.datos.estado === "fallido" || ficha.datos.estado === "cancelado") {
          setFallo(ficha.datos.error || t("explotacion.registroFallido"));
          return;
        }
      }
      setFallo(t("explotacion.registroTarda"));
    } catch (e: unknown) {
      setFallo(e instanceof ErrorApi ? e.titulo : t("explotacion.registroFallido"));
    } finally {
      setEnCurso(false);
    }
  }

  return (
    <div className="mt-4">
      <button type="button" className="btn-primary" onClick={() => void registrar()} disabled={enCurso}>
        {enCurso ? t("explotacion.registrando") : t("explotacion.registrar")}
      </button>
      <p className="mt-1.5 text-3xs text-ink-faint">{t("explotacion.registrarDetalle")}</p>
      {fallo ? (
        <p role="alert" className="mt-2 text-2xs text-danger">
          {fallo}
        </p>
      ) : null}
    </div>
  );
}

/**
 * La caja de preguntar.
 *
 * El token se pide **por pregunta** y va al navegador; la credencial de
 * aplicación no baja nunca. Dura minutos y nombra a esta persona y a esta
 * organización, así que la respuesta llega con SUS permisos: quien no ve una
 * cuenta en su ficha tampoco la ve aquí.
 */
function Preguntar({ diagnostico }: { diagnostico: Diagnostico }) {
  const { t } = useTranslation();
  const [texto, setTexto] = useState("");
  // Las últimas preguntas de ESTE tenant, no solo los ejemplos de fábrica. Es
  // lo que convierte el diario de consultas en algo que sirve: la pestaña de al
  // lado lo enseña y no se puede hacer nada con él, y repetir una pregunta es
  // justo lo que uno quiere hacer con un historial.
  const [recientes, setRecientes] = useState<string[]>([]);
  useEffect(() => {
    llamar<Array<{ pregunta: string }>>("/api/v1/analitica/consultas")
      .then((r) => {
        const vistas: string[] = [];
        for (const c of r.datos) {
          if (c.pregunta && !vistas.includes(c.pregunta)) vistas.push(c.pregunta);
          if (vistas.length === 8) break;
        }
        setRecientes(vistas);
      })
      .catch(() => undefined);
  }, []);
  const [pensando, setPensando] = useState(false);
  const [respuesta, setRespuesta] = useState<{ payload: Payload; texto: string } | null>(null);
  const [fallo, setFallo] = useState<string | null>(null);

  async function preguntar(pregunta: string) {
    if (!pregunta.trim() || pensando) return;
    setPensando(true);
    setFallo(null);
    setRespuesta(null);
    try {
      const token = await llamar<{ token: string }>("/api/v1/analitica/token", { metodo: "POST" });
      const r = await fetch(`${diagnostico.url_publica.replace(/\/$/, "")}/api/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token.datos.token}`,
        },
        body: JSON.stringify({ source_id: diagnostico.fuente_id, question: pregunta }),
      });
      const cuerpo = (await r.json()) as { payload?: Payload; text?: string; detail?: string };
      if (!r.ok || !cuerpo.payload) {
        // El motivo de contecintelligence tal cual: dice cosas útiles como «los
        // datos no contienen información de cuentas, solo nombres», y traducirlo
        // a «no se pudo responder» quitaría justo lo que ayuda.
        setFallo(cuerpo.detail || t("explotacion.sinRespuesta"));
        return;
      }
      setRespuesta({ payload: cuerpo.payload, texto: cuerpo.text || pregunta });
      // Queda anotado en el historial de consultas, que es lo que hace que la
      // pestaña de al lado tenga sentido.
      void llamar("/api/v1/analitica/consultas", {
        metodo: "POST",
        cuerpo: { pregunta, fuente: "contecintelligence", filas_devueltas: (cuerpo.payload.data || []).length },
      }).catch(() => undefined);
    } catch (e: unknown) {
      setFallo(e instanceof ErrorApi ? e.titulo : t("explotacion.sinRespuesta"));
    } finally {
      setPensando(false);
    }
  }

  return (
    <section className="flex flex-col gap-3">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void preguntar(texto);
        }}
      >
        <input
          className="input-base flex-1"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder={t("explotacion.placeholder")}
          aria-label={t("explotacion.placeholder")}
        />
        <button type="submit" className="btn-primary" disabled={pensando || !texto.trim()}>
          {pensando ? t("explotacion.pensando") : t("explotacion.preguntar")}
        </button>
      </form>

      <p className="text-3xs text-ink-faint">
        {recientes.length ? t("explotacion.recientes") : t("explotacion.ejemplos")}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {(recientes.length ? recientes : EJEMPLOS).map((e) => (
          <button
            key={e}
            type="button"
            className="pill"
            onClick={() => {
              setTexto(e);
              void preguntar(e);
            }}
          >
            {e}
          </button>
        ))}
      </div>

      {fallo ? (
        <p role="alert" className="flex items-start gap-1.5 text-2xs text-danger">
          <Icono nombre="error" tamano="sm" />
          <span>{fallo}</span>
        </p>
      ) : null}
      {respuesta ? <RespuestaAnalitica payload={respuesta.payload} texto={respuesta.texto} /> : null}
    </section>
  );
}

function Tarjeta({ pregunta }: { pregunta: Pregunta }) {
  const { t } = useTranslation();
  return (
    <li className="rounded-lg border border-ink-dim/40 bg-paper-light p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm text-ink">{pregunta.titulo}</span>
        {pregunta.informe_id ? (
          <span className="rounded bg-success/10 px-1.5 py-0.5 text-3xs uppercase text-success">
            {t("explotacion.esInforme")}
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-2xs text-ink-muted">{pregunta.pregunta}</p>
      <p className="mt-1 text-3xs text-ink-faint">
        {t("explotacion.vecesUsada", { veces: pregunta.veces_usada })}
      </p>
    </li>
  );
}
