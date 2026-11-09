/**
 * Los embudos de venta y sus etapas, configurados por la empresa.
 *
 * Pedido el 09-11-2026: «no veo dónde definir cuántos estados hay en el
 * embudo; todo configurable por administradores». La API dejaba crear etapas
 * y nada más; aquí se crean embudos, y de cada etapa se cambia el nombre, la
 * probabilidad, el color, los días a partir de los que está estancada, si es
 * final —ganada o perdida— y los criterios de salida: los campos sin los que
 * una oportunidad no avanza. Se ordenan y se quitan; si una etapa tiene
 * oportunidades, se dice a cuál pasan.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { Opciones } from "@/componentes/Formulario";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { ErrorApi, llamar } from "@/lib/api";
import { contratoDe, type CampoEsquema } from "@/lib/contrato";
import { listar } from "@/lib/listados";
import { cn } from "@/lib/utiles";

interface Etapa {
  id: string;
  clave: string;
  nombre: string;
  orden: number;
  probabilidad: number;
  color: string;
  terminal: boolean;
  ganada: boolean;
  criterios_salida: string[];
  dias_estancamiento: number | null;
}

interface Embudo {
  id: string;
  clave: string;
  nombre: string;
  activo: boolean;
  por_defecto: boolean;
  etapas: Etapa[];
}

function clave(nombre: string): string {
  return (
    nombre
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 50) || "etapa"
  );
}

export function Embudos() {
  const { t } = useTranslation();
  const [embudos, setEmbudos] = useState<Embudo[] | null>(null);
  const [elegido, setElegido] = useState<string>("");
  const [campos, setCampos] = useState<string[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);
  const [nuevo, setNuevo] = useState("");

  const cargar = useCallback(() => {
    listar<Embudo>("/api/v1/pipelines?limite=50")
      .then((filas) => {
        setEmbudos(filas);
        setElegido(
          (e) =>
            e || filas.find((f) => f.por_defecto)?.id || filas[0]?.id || "",
        );
      })
      .catch((e) => setFallo(e));
  }, []);
  useEffect(cargar, [cargar]);

  useEffect(() => {
    // Los criterios de salida son campos de la oportunidad: los que su alta
    // declara en el contrato, que es la lista que el servidor sabe comprobar.
    void contratoDe("sales").then((doc) => {
      const props = doc.components?.schemas?.CrearOportunidad?.properties ?? {};
      setCampos(Object.keys(props));
    });
  }, []);

  async function crearEmbudo() {
    try {
      const r = await llamar<Embudo>("/api/v1/pipelines", {
        metodo: "POST",
        cuerpo: { clave: clave(nuevo), nombre: nuevo },
      });
      setNuevo("");
      setElegido(r.datos.id);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !embudos) return <Fallo error={fallo} />;
  if (!embudos) return <Cargando />;
  const embudo = embudos.find((e) => e.id === elegido);

  return (
    <>
      <CabeceraPagina
        icono="view_kanban"
        titulo={t("embudos.titulo")}
        entradilla={t("embudos.entradilla")}
      />
      <div className="grid gap-4 lg:grid-cols-[13rem_minmax(0,1fr)]">
        <div className="card p-2">
          <ul className="lista-acotada" aria-label={t("embudos.lista")}>
            {embudos.map((e) => (
              <li key={e.id}>
                <button
                  type="button"
                  onClick={() => setElegido(e.id)}
                  aria-current={e.id === elegido}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded px-3 py-1.5 text-left text-titulin",
                    e.id === elegido
                      ? "bg-accent/10 font-semibold text-accent"
                      : "text-ink hover:bg-paper-light",
                  )}
                >
                  <span className="truncate">{e.nombre}</span>
                  {e.por_defecto ? (
                    <span className="chip-dato">{t("embudos.porDefecto")}</span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-2 border-t border-ink-dim/30 p-2">
            <input
              className="input-base"
              value={nuevo}
              placeholder={t("embudos.nuevoNombre")}
              aria-label={t("embudos.nuevoNombre")}
              onChange={(e) => setNuevo(e.target.value)}
            />
            <button
              type="button"
              className="btn-secondary mt-2 w-full"
              disabled={!nuevo.trim()}
              onClick={() => void crearEmbudo()}
            >
              <Icono nombre="add" tamano="sm" />
              {t("embudos.crear")}
            </button>
          </div>
        </div>
        {embudo ? (
          <EditorDeEmbudo
            key={embudo.id}
            embudo={embudo}
            campos={campos}
            alCambiar={cargar}
          />
        ) : null}
      </div>
    </>
  );
}

function EditorDeEmbudo({
  embudo,
  campos,
  alCambiar,
}: {
  embudo: Embudo;
  campos: string[];
  alCambiar: () => void;
}) {
  const { t } = useTranslation();
  const [etapas, setEtapas] = useState<Etapa[]>(
    [...embudo.etapas].sort((a, b) => a.orden - b.orden),
  );
  const [cambiadas, setCambiadas] = useState<Set<string>>(new Set());
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const [quitando, setQuitando] = useState<{
    etapa: Etapa;
    cuantas: number;
  } | null>(null);
  const [destino, setDestino] = useState("");
  const [nueva, setNueva] = useState("");
  const base = `/api/v1/pipelines/${embudo.id}/etapas`;

  const campoCriterios: CampoEsquema = {
    nombre: "criterios_salida",
    tipo: "lista_multiple",
    obligatorio: false,
    titulo: t("embudos.criterios"),
    descripcion: "",
    opciones: campos,
    maximo: null,
    formato: "",
    subcampos: [],
    referencia: "",
  } as CampoEsquema;

  function cambia(id: string, cambio: Partial<Etapa>) {
    setEtapas((es) => es.map((e) => (e.id === id ? { ...e, ...cambio } : e)));
    setCambiadas((c) => new Set(c).add(id));
  }

  async function intenta(accion: () => Promise<unknown>, ok: string) {
    setAviso("");
    try {
      await accion();
      setFallo(null);
      setAviso(ok);
      alCambiar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function guardar() {
    await intenta(async () => {
      for (const e of etapas.filter((x) => cambiadas.has(x.id))) {
        await llamar(`${base}/${e.id}`, {
          metodo: "PATCH",
          cuerpo: {
            nombre: e.nombre,
            probabilidad: e.probabilidad,
            color: e.color,
            terminal: e.terminal,
            ganada: e.ganada,
            criterios_salida: e.criterios_salida,
            dias_estancamiento: e.dias_estancamiento || null,
          },
        });
      }
      await llamar(`${base}/orden`, {
        metodo: "PUT",
        cuerpo: { etapas: etapas.map((e) => e.id) },
      });
      setCambiadas(new Set());
    }, t("embudos.guardado"));
  }

  function mueve(i: number, paso: -1 | 1) {
    const j = i + paso;
    if (j < 0 || j >= etapas.length) return;
    const copia = [...etapas];
    [copia[i], copia[j]] = [copia[j]!, copia[i]!];
    setEtapas(copia);
  }

  async function quitar(etapa: Etapa, moverA?: string) {
    setAviso("");
    try {
      await llamar(`${base}/${etapa.id}${moverA ? `?mover_a=${moverA}` : ""}`, {
        metodo: "DELETE",
      });
      setQuitando(null);
      setFallo(null);
      setAviso(t("embudos.quitada", { etapa: etapa.nombre }));
      alCambiar();
    } catch (e) {
      // Con oportunidades dentro, el servidor pide a dónde van: se pregunta.
      if (
        e instanceof ErrorApi &&
        e.codigo === "sales.etapa_con_oportunidades"
      ) {
        const detalle = (e.detalle ?? {}) as { oportunidades?: number };
        setQuitando({ etapa, cuantas: Number(detalle.oportunidades ?? 0) });
      } else setFallo(e);
    }
  }

  async function anadir() {
    await intenta(
      () =>
        llamar(base, {
          metodo: "POST",
          cuerpo: { clave: clave(nueva), nombre: nueva, orden: etapas.length },
        }).then(() => setNueva("")),
      t("embudos.anadida"),
    );
  }

  return (
    <div className="space-y-4">
      <section className="card p-4">
        <h2 className="section-label mb-1">
          {t("embudos.etapasDe", { embudo: embudo.nombre })}
        </h2>
        <p className="mb-2 text-rotulo text-ink-faint">{t("embudos.ayuda")}</p>
        <Rejilla
          titulo={t("embudos.etapasDe", { embudo: embudo.nombre })}
          acotada={false}
          cabeceras={[
            t("embudos.orden"),
            t("embudos.nombre"),
            t("embudos.probabilidad"),
            t("embudos.color"),
            t("embudos.estancada"),
            t("embudos.final"),
            t("embudos.ganada"),
            t("embudos.criterios"),
            "",
          ]}
        >
          {etapas.map((e, i) => (
            <tr key={e.id} className="border-b border-ink-dim/30 last:border-0">
              <Casilla enUnaLinea>
                <button
                  type="button"
                  className="btn-link"
                  disabled={i === 0}
                  onClick={() => mueve(i, -1)}
                  aria-label={t("embudos.subir", { etapa: e.nombre })}
                >
                  <Icono nombre="arrow_upward" tamano="sm" />
                </button>
                <button
                  type="button"
                  className="btn-link"
                  disabled={i === etapas.length - 1}
                  onClick={() => mueve(i, 1)}
                  aria-label={t("embudos.bajar", { etapa: e.nombre })}
                >
                  <Icono nombre="arrow_downward" tamano="sm" />
                </button>
              </Casilla>
              <Casilla className="min-w-[13rem]">
                <input
                  className="input-base"
                  value={e.nombre}
                  aria-label={t("embudos.nombreDe", { etapa: e.clave })}
                  onChange={(ev) => cambia(e.id, { nombre: ev.target.value })}
                />
              </Casilla>
              <Casilla>
                <input
                  type="number"
                  min={0}
                  max={100}
                  className="input-base !w-20"
                  value={e.probabilidad}
                  aria-label={t("embudos.probabilidadDe", { etapa: e.nombre })}
                  onChange={(ev) =>
                    cambia(e.id, { probabilidad: Number(ev.target.value) })
                  }
                />
              </Casilla>
              <Casilla>
                <input
                  type="color"
                  className="h-8 w-10 rounded border border-ink-dim/60 bg-paper"
                  value={e.color}
                  aria-label={t("embudos.colorDe", { etapa: e.nombre })}
                  onChange={(ev) => cambia(e.id, { color: ev.target.value })}
                />
              </Casilla>
              <Casilla>
                <input
                  type="number"
                  min={1}
                  className="input-base !w-20"
                  value={e.dias_estancamiento ?? ""}
                  aria-label={t("embudos.estancadaDe", { etapa: e.nombre })}
                  onChange={(ev) =>
                    cambia(e.id, {
                      dias_estancamiento: ev.target.value
                        ? Number(ev.target.value)
                        : null,
                    })
                  }
                />
              </Casilla>
              <Casilla className="text-center">
                <input
                  type="checkbox"
                  checked={e.terminal}
                  aria-label={t("embudos.finalDe", { etapa: e.nombre })}
                  onChange={(ev) =>
                    cambia(e.id, {
                      terminal: ev.target.checked,
                      ganada: ev.target.checked ? e.ganada : false,
                    })
                  }
                  className="h-4 w-4 accent-accent"
                />
              </Casilla>
              <Casilla className="text-center">
                <input
                  type="checkbox"
                  checked={e.ganada}
                  disabled={!e.terminal}
                  aria-label={t("embudos.ganadaDe", { etapa: e.nombre })}
                  onChange={(ev) => cambia(e.id, { ganada: ev.target.checked })}
                  className="h-4 w-4 accent-accent"
                />
              </Casilla>
              <Casilla className="min-w-[12rem]">
                {e.terminal ? (
                  <span className="text-rotulo text-ink-faint">—</span>
                ) : (
                  <Opciones
                    campo={campoCriterios}
                    valor={e.criterios_salida}
                    alCambiar={(v) =>
                      cambia(e.id, { criterios_salida: v as string[] })
                    }
                  />
                )}
              </Casilla>
              <Casilla>
                <button
                  type="button"
                  className="btn-link text-danger"
                  onClick={() => void quitar(e)}
                  aria-label={t("embudos.quitar", { etapa: e.nombre })}
                >
                  <Icono nombre="delete" tamano="sm" />
                </button>
              </Casilla>
            </tr>
          ))}
        </Rejilla>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            className="input-base w-64"
            value={nueva}
            placeholder={t("embudos.nuevaEtapa")}
            aria-label={t("embudos.nuevaEtapa")}
            onChange={(e) => setNueva(e.target.value)}
          />
          <button
            type="button"
            className="btn-secondary"
            disabled={!nueva.trim()}
            onClick={() => void anadir()}
          >
            <Icono nombre="add" tamano="sm" />
            {t("embudos.anadir")}
          </button>
        </div>
      </section>

      {quitando ? (
        <section className="card border-warning/50 p-4">
          <p className="text-dato text-ink">
            {t("embudos.conOportunidades", {
              etapa: quitando.etapa.nombre,
              n: quitando.cuantas,
            })}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select
              className="input-base w-auto"
              value={destino}
              aria-label={t("embudos.moverA")}
              onChange={(e) => setDestino(e.target.value)}
            >
              <option value="">{t("embudos.moverA")}</option>
              {etapas
                .filter((x) => x.id !== quitando.etapa.id)
                .map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.nombre}
                  </option>
                ))}
            </select>
            <button
              type="button"
              className="btn-primary"
              disabled={!destino}
              onClick={() => void quitar(quitando.etapa, destino)}
            >
              {t("embudos.moverYQuitar")}
            </button>
            <button
              type="button"
              className="btn-link"
              onClick={() => setQuitando(null)}
            >
              {t("embudos.cancelar")}
            </button>
          </div>
        </section>
      ) : null}

      <div role="status" className="space-y-2">
        {fallo ? <Fallo error={fallo} /> : null}
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
      <button
        type="button"
        className="btn-primary"
        onClick={() => void guardar()}
      >
        {t("embudos.guardar")}
      </button>
    </div>
  );
}
