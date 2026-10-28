/**
 * El editor de procesos: el lienzo ES la definición
 * (CRM-00.03.05.01, CRM-00.03.05.02, CRM-00.03.02.02).
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
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { llamar } from "@/lib/api";
import { CabeceraPagina } from "@/componentes/Pagina";
import {
  ALTO,
  ANCHO,
  aristas,
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

export function Procesos() {
  const { t } = useTranslation();
  const [texto, setTexto] = useState(() => JSON.stringify(EJEMPLO, null, 2));
  const [clave, setClave] = useState("mi_proceso");
  const [nombre, setNombre] = useState("Mi proceso");
  const [problemas, setProblemas] = useState<string[] | null>(null);
  const [recorrido, setRecorrido] = useState<Record<string, unknown>[] | null>(
    null,
  );
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
      const { datos } = await llamar<{
        problemas?: string[];
        recorrido?: Record<string, unknown>[];
      }>(ruta, {
        metodo: "POST",
        cuerpo: { clave, nombre, definicion, ...extra },
      });
      setProblemas(datos.problemas ?? []);
      if (datos.recorrido) setRecorrido(datos.recorrido);
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

      <div className="mt-3 flex flex-wrap gap-2">
        <Boton
          texto={t("procesos.validar")}
          onClick={() => void accion("/api/v1/procesos/definiciones/validar")}
        />
        <Boton
          texto={t("procesos.simular")}
          onClick={() =>
            void accion("/api/v1/procesos/definiciones/simular", {
              variables: {},
            })
          }
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
  const enlaces = aristas(definicion);
  const porNombre = new Map(nodos.map((n) => [n.nombre, n]));
  const ancho = Math.max(400, ...nodos.map((n) => n.x + ANCHO));
  const alto = Math.max(280, ...nodos.map((n) => n.y + ALTO));

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
      <svg
        width={ancho}
        height={alto}
        role="img"
        aria-label={t("procesos.lienzo")}
      >
        {enlaces.map((a, i) => {
          const desde = porNombre.get(a.desde);
          const hasta = porNombre.get(a.hasta);
          if (!desde || !hasta) return null;
          return (
            <g key={`${a.desde}-${a.hasta}-${a.etiqueta}-${i}`}>
              <line
                x1={desde.x + 140}
                y1={desde.y + 18}
                x2={hasta.x}
                y2={hasta.y + 18}
                stroke="rgb(var(--ink-dim))"
                strokeWidth={1.5}
              />
              <text
                x={(desde.x + 140 + hasta.x) / 2}
                y={(desde.y + hasta.y) / 2 + 12}
                fill="rgb(var(--ink-faint))"
                fontSize={9}
              >
                {a.etiqueta}
              </text>
            </g>
          );
        })}
        {nodos.map((n) => (
          <g key={n.nombre}>
            <rect
              x={n.x}
              y={n.y}
              width={140}
              height={36}
              rx={8}
              fill="rgb(var(--paper-light))"
              stroke={n.esInicio ? "rgb(var(--accent))" : "rgb(var(--ink-dim))"}
              strokeWidth={n.esInicio ? 2 : 1}
            />
            <text
              x={n.x + 10}
              y={n.y + 15}
              fill="rgb(var(--ink))"
              fontSize={11}
            >
              {n.nombre}
            </text>
            <text
              x={n.x + 10}
              y={n.y + 28}
              fill="rgb(var(--ink-faint))"
              fontSize={9}
            >
              {n.tipo}
            </text>
          </g>
        ))}
      </svg>

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
