/**
 * El editor de procesos: el lienzo ES la definición
 * (CRM-00.03.05.01, CRM-00.03.05.02, CRM-00.03.02.02, CRM-00.03.05.03,
 * CRM-00.03.05.04, CRM-00.03.02.14).
 *
 * No hay dos documentos. El JSON es la definición y el diagrama es una lectura
 * de ese mismo JSON: se puede escribir el proceso a mano y abrirlo como
 * diagrama, o moverlo en el lienzo y leerlo como código. Lo único que el lienzo
 * añade son las posiciones de las cajas, y van dentro de la propia definición
 * porque mantenerlas aparte obligaría a sincronizar dos documentos — y el día
 * que se desincronizaran, el diagrama enseñaría un proceso que no es el que se
 * ejecuta.
 *
 * **Validar y simular no publican nada.** Es el punto entero de esta pantalla:
 * un error descubierto aquí es un mensaje, y descubierto en ejecución es un
 * proceso a medias en producción con su compensación pendiente.
 *
 * Validar busca lo que no se ve leyendo el diagrama: pasos a los que no se
 * llega desde el inicio, pasos desde los que no se llega a ningún final —un
 * bucle sin salida, una rama que se quedó sin enlazar—, ramas que apuntan a
 * un paso que no existe, condiciones sin atributo (que se toman SIEMPRE, con
 * el «si no» de al lado sin usarse nunca) y tareas humanas sin dueño, que
 * nadie ve y dejan el proceso parado para siempre.
 *
 * **Y simular contesta con datos de ejemplo**: qué ruta seguiría este caso,
 * **quién aprobaría** y **cuánto tardaría**. Las tres, porque las dos últimas
 * son lo que decide alguien y antes no las decía nadie: el recorrido enseñaba
 * por qué pasos iría y ni por cuántas manos ni en cuánto tiempo. El plazo es
 * el DECLARADO, no una predicción, y los pasos humanos que no declaran plazo
 * salen dichos: un proceso que espera a una persona sin fecha no tarda cero.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { llamar } from "@/lib/api";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Diagrama } from "@/componentes/Diagrama";
import {
  colocar,
  conPosiciones,
  type Definicion,
  type Nodo,
} from "@/lib/grafo";

const EJEMPLO: Definicion = {
  inicio: "recibir",
  pasos: {
    recibir: {
      tipo: "servicio",
      operacion: "sales.crear_oportunidad",
      siguiente: "aprobar",
    },
    aprobar: { tipo: "humano", rutas: { si: "terminar", no: "terminar" } },
    terminar: { tipo: "fin" },
  },
};

/** Quién aprobaría y cuánto tardaría el camino simulado (CRM-00.03.05.04). */
interface Resumen {
  quien_aprobaria: { paso: string; quien: string; horas: number | null }[];
  horas_declaradas: number;
  pasos_sin_plazo: string[];
  que_significa: string;
}

export function Procesos() {
  const { t } = useTranslation();
  const [texto, setTexto] = useState(() => JSON.stringify(EJEMPLO, null, 2));
  const [clave, setClave] = useState("mi_proceso");
  const [nombre, setNombre] = useState("Mi proceso");
  const [problemas, setProblemas] = useState<string[] | null>(null);
  const [recorrido, setRecorrido] = useState<Record<string, unknown>[] | null>(
    null,
  );
  const [resumen, setResumen] = useState<Resumen | null>(null);
  // Los datos de ejemplo con los que se simula. Simular con el caso vacío
  // recorre la rama por defecto y deja sin probar justo la que preocupa.
  const [variables, setVariables] = useState("{}");
  const [respuestas, setRespuestas] = useState("{}");
  const [fallo, setFallo] = useState<unknown>(null);

  // El JSON puede estar a medias mientras se teclea; eso no es un error que
  // haya que gritar, es el estado normal de un editor de texto.
  const definicion = useMemo<Definicion | null>(() => {
    try {
      return JSON.parse(texto) as Definicion;
    } catch {
      return null;
    }
  }, [texto]);

  const [nodos, setNodos] = useState<Nodo[]>([]);
  useEffect(() => {
    if (definicion) setNodos(colocar(definicion));
  }, [definicion]);

  const guardarPosiciones = useCallback(
    (nuevos: Nodo[]) => {
      setNodos(nuevos);
      if (definicion)
        setTexto(JSON.stringify(conPosiciones(definicion, nuevos), null, 2));
    },
    [definicion],
  );

  async function accion(ruta: string, extra: Record<string, unknown> = {}) {
    if (!definicion) return;
    setFallo(null);
    setRecorrido(null);
    try {
      const { datos } = await llamar<
        {
          problemas?: string[];
          recorrido?: Record<string, unknown>[];
        } & Partial<Resumen>
      >(ruta, {
        metodo: "POST",
        cuerpo: { clave, nombre, definicion, ...extra },
      });
      setProblemas(datos.problemas ?? []);
      if (datos.recorrido) setRecorrido(datos.recorrido);
      setResumen(
        datos.quien_aprobaria
          ? {
              quien_aprobaria: datos.quien_aprobaria,
              horas_declaradas: datos.horas_declaradas ?? 0,
              pasos_sin_plazo: datos.pasos_sin_plazo ?? [],
              que_significa: datos.que_significa ?? "",
            }
          : null,
      );
    } catch (error) {
      setFallo(error);
    }
  }

  return (
    <>
      <CabeceraPagina
        titulo={t("procesos.titulo")}
        entradilla={t("procesos.intro")}
        icono="account_tree"
      />

      <div className="mt-4 flex flex-wrap gap-2">
        <Campo
          etiqueta={t("procesos.clave")}
          valor={clave}
          alCambiar={setClave}
        />
        <Campo
          etiqueta={t("procesos.nombre")}
          valor={nombre}
          alCambiar={setNombre}
        />
      </div>

      {/* Los datos de ejemplo con los que se simula. Sin ellos se recorre
          siempre la rama por defecto, que es justo la que no preocupa. */}
      <div className="mt-2 flex flex-wrap gap-2">
        <Campo
          etiqueta={t("procesos.variablesEjemplo")}
          valor={variables}
          alCambiar={setVariables}
        />
        <Campo
          etiqueta={t("procesos.respuestasEjemplo")}
          valor={respuestas}
          alCambiar={setRespuestas}
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Boton
          texto={t("procesos.validar")}
          onClick={() => void accion("/api/v1/procesos/definiciones/validar")}
        />
        <Boton
          texto={t("procesos.simular")}
          onClick={() => {
            // Lo que esté a medias se manda como vacío en vez de reventar: el
            // JSON de un campo que se está tecleando es el estado normal.
            const leer = (texto: string) => {
              try {
                return JSON.parse(texto) as Record<string, unknown>;
              } catch {
                return {};
              }
            };
            void accion("/api/v1/procesos/definiciones/simular", {
              variables: leer(variables),
              respuestas_humanas: leer(respuestas),
            });
          }}
        />
        <Boton
          texto={t("procesos.guardarBorrador")}
          onClick={() =>
            void accion("/api/v1/procesos/definiciones", { estado: "borrador" })
          }
        />
        <Boton
          texto={t("procesos.publicar")}
          destacado
          onClick={() =>
            void accion("/api/v1/procesos/definiciones", {
              estado: "publicada",
            })
          }
        />
      </div>

      {fallo ? (
        <div className="mt-3">
          <Fallo error={fallo} />
        </div>
      ) : null}

      {problemas !== null ? (
        <div
          className={`mt-3 rounded-xl border p-3 text-2xs ${
            problemas.length === 0
              ? "border-success/40 bg-success/5 text-success"
              : "border-danger/40 bg-danger/5 text-danger"
          }`}
          role="status"
        >
          {problemas.length === 0 ? (
            t("procesos.valida")
          ) : (
            <ul className="lista-acotada flex flex-col gap-0.5 pr-1">
              {problemas.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <section>
          <h2 className="text-2xs font-medium uppercase tracking-wide text-ink-faint">
            {t("procesos.lienzo")}
          </h2>
          {definicion ? (
            <Lienzo
              definicion={definicion}
              nodos={nodos}
              alMover={guardarPosiciones}
            />
          ) : (
            <p className="mt-2 text-2xs text-warning">
              {t("procesos.jsonAMedias")}
            </p>
          )}
        </section>

        <section>
          <h2 className="text-2xs font-medium uppercase tracking-wide text-ink-faint">
            {t("procesos.codigo")}
          </h2>
          <label className="sr-only" htmlFor="definicion">
            {t("procesos.codigo")}
          </label>
          <textarea
            id="definicion"
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            spellCheck={false}
            rows={22}
            className="mt-2 w-full rounded-xl border border-ink-dim/60 bg-paper p-3 font-mono text-2xs text-ink"
          />
        </section>
      </div>

      {resumen ? (
        <section className="card mt-6 p-4">
          <h2 className="section-label mb-1">{t("procesos.quienYCuanto")}</h2>
          <p className="mb-2 text-3xs text-ink-faint">
            {t("procesos.quienYCuantoAyuda")}
          </p>
          {resumen.quien_aprobaria.length === 0 ? (
            <p className="text-2xs text-ink-muted">
              {t("procesos.sinManos")}
            </p>
          ) : (
            <ul className="divide-y divide-ink-dim/30">
              {resumen.quien_aprobaria.map((m) => (
                <li
                  key={m.paso}
                  className="flex flex-wrap items-baseline gap-x-3 py-1.5"
                >
                  <span className="text-2xs font-medium text-ink">{m.paso}</span>
                  <span className="chip-dato">
                    {m.quien || t("procesos.sinDueno")}
                  </span>
                  <span className="text-3xs text-ink-muted">
                    {m.horas
                      ? t("procesos.enHoras", { horas: m.horas })
                      : t("procesos.sinPlazo")}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-2xs text-ink">
            {t("procesos.totalHoras", { horas: resumen.horas_declaradas })}
          </p>
          {/* Un total que no avisa de lo que no sabe es un total que engaña. */}
          <p
            className={
              resumen.pasos_sin_plazo.length
                ? "mt-1 text-3xs text-warning"
                : "mt-1 text-3xs text-ink-faint"
            }
          >
            {resumen.que_significa}
          </p>
        </section>
      ) : null}

      {recorrido ? (
        <section className="mt-6">
          <h2 className="text-2xs font-medium uppercase tracking-wide text-ink-faint">
            {t("procesos.recorrido")}
          </h2>
          {/* El recorrido de un proceso largo son cientos de pasos, y debajo
              no quedaba nada visible. */}
          <ol className="lista-acotada mt-2 flex flex-col gap-1 pr-1">
            {recorrido.map((paso, i) => (
              <li
                key={`${String(paso.paso)}-${i}`}
                className="rounded-lg border border-ink-dim/30 bg-paper px-3 py-1.5 font-mono text-2xs text-ink"
              >
                {JSON.stringify(paso)}
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </>
  );
}

function Lienzo({
  definicion,
  nodos,
  alMover,
}: {
  definicion: Definicion;
  nodos: Nodo[];
  alMover: (nodos: Nodo[]) => void;
}) {
  const { t } = useTranslation();
  function mover(nombre: string, dx: number, dy: number) {
    alMover(
      nodos.map((n) =>
        n.nombre === nombre
          ? { ...n, x: Math.max(0, n.x + dx), y: Math.max(0, n.y + dy) }
          : n,
      ),
    );
  }

  return (
    <div className="mt-2 overflow-auto rounded-xl border border-ink-dim/60 bg-paper">
      {/* El MISMO dibujo que la pantalla de una instancia, con otra forma de
          pintar las cajas: aquí se marca el inicio, allí por dónde va. Dos
          diagramas del mismo objeto divergen en cuanto uno aprende una forma
          de enlace que el otro no. */}
      <Diagrama
        definicion={definicion}
        nodos={nodos}
        rotulo={t("procesos.lienzo")}
        conEtiquetas
        pinta={(n) => ({
          trazo: n.esInicio ? "rgb(var(--accent))" : "rgb(var(--ink-dim))",
          grosor: n.esInicio ? 2 : 1,
          lineas: [n.nombre, n.tipo],
        })}
      />

      {/* Mover con el teclado y no solo arrastrando: un lienzo que solo
          responde al ratón deja fuera a quien navega con teclado, y es
          exactamente el tipo de pantalla donde más se nota. */}
      <div className="flex flex-wrap gap-1 border-t border-ink-dim/30 p-2">
        {nodos.map((n) => (
          <div
            key={n.nombre}
            className="flex items-center gap-1 text-3xs text-ink-faint"
          >
            <span className="font-mono">{n.nombre}</span>
            {(
              [
                ["←", -40, 0],
                ["→", 40, 0],
                ["↑", 0, -30],
                ["↓", 0, 30],
              ] as const
            ).map(([signo, dx, dy]) => (
              <button
                key={signo}
                type="button"
                aria-label={`${t("procesos.mover")} ${n.nombre} ${signo}`}
                onClick={() => mover(n.nombre, dx, dy)}
                className="rounded border border-ink-dim/40 px-1 hover:bg-paper-light"
              >
                {signo}
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function Campo({
  etiqueta,
  valor,
  alCambiar,
}: {
  etiqueta: string;
  valor: string;
  alCambiar: (v: string) => void;
}) {
  const id = `campo-${etiqueta}`;
  return (
    <label htmlFor={id} className="text-2xs text-ink-muted">
      {etiqueta}
      <input
        id={id}
        value={valor}
        onChange={(e) => alCambiar(e.target.value)}
        className="input-sm ml-2 inline-block w-auto"
      />
    </label>
  );
}

function Boton({
  texto,
  onClick,
  destacado,
}: {
  texto: string;
  onClick: () => void;
  destacado?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg px-3 py-1.5 text-2xs ${
        destacado
          ? "bg-accent text-paper hover:bg-accent-soft"
          : "border border-ink-dim/60 text-ink-muted hover:bg-paper-light"
      }`}
    >
      {texto}
    </button>
  );
}
