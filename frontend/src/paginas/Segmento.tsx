/**
 * Un segmento: a cuánta gente le va a llegar, y a cuánta le va a llegar dos veces
 * (CRM-02.01.01.03, CRM-02.01.01.04, CRM-02.01.01.07).
 *
 * El módulo listaba segmentos con su nombre y su tamaño. Delante de un
 * segmento la pregunta no es cuántos son: es **si ese número sigue siendo
 * verdad y a quién de ellos le va a llegar también lo otro**.
 *
 * Tres cosas que esta pantalla pone delante y la lista no podía:
 *
 * **Dinámico o foto congelada.** Un segmento dinámico se recalcula al
 * preguntarlo; uno estático devuelve lo que se congeló. Los dos enseñan un
 * número con la misma cara, y sobre el segundo se manda un correo creyendo que
 * es la gente de hoy. Congelar es lo que permite contestar en junio «¿a quién
 * se le mandó?» con la lista de marzo — y es irreversible: deja de recalcularse.
 *
 * **El bruto y los alcanzables no son el mismo número.** Entre uno y otro están
 * las supresiones: bajas, rebotes duros y listas negras. Planificar un envío a
 * diez mil y que salga a siete mil sin saber por qué faltan tres mil es el caso
 * que esto evita, y por eso el hueco se nombra en vez de enseñar sólo el total.
 *
 * **El solapamiento se mide contra OTRO segmento, no en abstracto.** «Si lanzo
 * las dos campañas esta semana, ¿a cuánta gente le llegan las dos?» es la
 * pregunta real, y el número solo no la contesta: mil personas comunes es mucho
 * si el segmento tiene mil doscientas y poco si tiene cien mil. Por eso va con
 * el porcentaje **sobre cada uno de los dos**.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import {
  BotonesDeRegistro,
  ConfirmarBorrado,
  FormularioDeEdicion,
  useEdicion,
} from "@/componentes/Edicion";
import {
  NOMBRE_DE_OPERADOR,
  PerfilesDeMarketing,
} from "@/componentes/ConstructorDeSegmento";
import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { DatosClave } from "@/componentes/DatosClave";
import { DetallesDelRegistro } from "@/componentes/DetallesDelRegistro";
import { PestanasDeFicha } from "@/componentes/PestanasDeFicha";
import { llamar, salvoCancelacion } from "@/lib/api";
import { listar } from "@/lib/listados";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";
import { cifra, fechaHora } from "@/lib/formato";

interface Segmento {
  id: string;
  clave: string;
  nombre: string;
  descripcion: string;
  objeto: string;
  /** Dinámico se recalcula al preguntarlo; estático es lo que se congeló. */
  dinamico: boolean;
  definicion: Record<string, unknown>;
  excluye: string[];
  tamano: number | null;
  tamano_at: string | null;
}

interface Tamano {
  segmento: string;
  bruto: number;
  alcanzables: number;
  /** Lo que se cae entre el bruto y los alcanzables: bajas, rebotes, negras. */
  suprimidos: number;
  calculado_at: string;
  dinamico: boolean;
  es_foto_congelada: boolean;
}

interface Solapamiento {
  a: string;
  b: string;
  tamano_a: number;
  tamano_b: number;
  comunes: number;
  pct_de_a: number | null;
  pct_de_b: number | null;
  solo_a: number;
  solo_b: number;
}

interface Otro {
  id: string;
  nombre: string;
}

/** Las condiciones anidadas, tal cual se guardaron (CRM-02.01.01.02). */
function Condicion({ nodo, nivel = 0 }: { nodo: unknown; nivel?: number }) {
  const { t } = useTranslation();
  if (!nodo || typeof nodo !== "object") return null;
  const n = nodo as Record<string, unknown>;
  const hijos = Array.isArray(n.hijos) ? n.hijos : null;

  if (hijos) {
    return (
      <div style={{ marginLeft: nivel * 12 }}>
        <span className="badge badge-muted">
          {t(
            n.op === "o"
              ? "segmento.o"
              : n.op === "no"
                ? "segmento.no"
                : "segmento.y",
          )}
        </span>
        {hijos.map((hijo, i) => (
          <Condicion key={i} nodo={hijo} nivel={nivel + 1} />
        ))}
      </div>
    );
  }
  // `atributo` y no `campo`: es la gramática del motor. Leía `campo`, que no
  // existe, y cada condición salía como «— = "cliente"» (medido el 10-11-2026).
  const atributo = String(n.atributo ?? "");
  const propio = atributo.split(".").slice(1).join(".");
  const operador = String(n.operador ?? "=");
  return (
    <p className="text-dato text-ink" style={{ marginLeft: nivel * 12 }}>
      <span>
        {propio.startsWith("campos.")
          ? propio.slice("campos.".length)
          : t(`constructorSegmento.atributo.${propio}`, {
              defaultValue: atributo || "—",
            })}
      </span>{" "}
      <span className="text-ink-muted">
        {t(
          `constructorSegmento.op.${NOMBRE_DE_OPERADOR[operador] ?? operador}`,
          {
            defaultValue: operador,
          },
        )}
      </span>{" "}
      {"valor" in n ? (
        <span className="font-mono">
          {Array.isArray(n.valor) ? n.valor.join(", ") : String(n.valor ?? "")}
        </span>
      ) : null}
    </p>
  );
}

export function Segmento() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [segmento, setSegmento] = useState<Segmento | null>(null);
  const [tamano, setTamano] = useState<Tamano | null>(null);
  const [otros, setOtros] = useState<Otro[]>([]);
  const [contra, setContra] = useState("");
  const [solape, setSolape] = useState<Solapamiento | null>(null);
  const [midiendo, setMidiendo] = useState(false);
  const [congelando, setCongelando] = useState(false);
  const [aviso, setAviso] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const navegar = useNavigate();
  // La edición existía en la ficha genérica y no se pierde al traerse el
  // segmento a su propia pantalla: el contrato publica `PATCH`, y quitarla
  // aquí sería retirar algo que funcionaba sin que nadie lo decidiera.
  const modulo = moduloDe("segmentos");
  const recurso = modulo ? recursoDe(modulo, "segmento") : undefined;
  const { ruta, puedeEditar, puedeBorrar, borrado } = useEdicion(recurso, id);
  // Las mismas dos pestañas que las demás fichas: «Relacionado» es lo que
  // esta pantalla ya enseñaba y «Detalles» son los campos del registro, que
  // hasta hoy sólo se leían entrando a editar.
  const [pestana, setPestana] = useState<"relacionado" | "detalles">(
    "relacionado",
  );

  const cargar = useCallback(() => {
    const control = new AbortController();
    const { signal } = control;
    setFallo(null);
    llamar<Segmento>(`/api/v1/segmentos/${id}`, { signal })
      .then((r) => setSegmento(r.datos))
      .catch(salvoCancelacion(setFallo));
    // El recuento se pide aparte: es el que se calcula ahora, y el de la ficha
    // es el último guardado. Enseñar sólo uno de los dos sería mentir en uno
    // de los dos sentidos.
    llamar<Tamano>(`/api/v1/segmentos/${id}/tamano`, { signal })
      .then((r) => setTamano(r.datos))
      .catch(salvoCancelacion(() => setTamano(null)));
    listar<Otro>("/api/v1/segmentos", { signal })
      .then((lista) => setOtros(lista.filter((s) => s.id !== id)))
      .catch(salvoCancelacion(() => setOtros([])));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  async function medirSolape() {
    if (!contra) return;
    setMidiendo(true);
    setFallo(null);
    try {
      const r = await llamar<Solapamiento>(
        `/api/v1/segmentos/solapamiento?a=${id}&b=${contra}`,
      );
      setSolape(r.datos);
    } catch (error) {
      setFallo(error);
    } finally {
      setMidiendo(false);
    }
  }

  async function congelar() {
    setCongelando(true);
    setFallo(null);
    try {
      const r = await llamar<{ miembros: number }>(
        `/api/v1/segmentos/${id}/congelar`,
        { metodo: "POST" },
      );
      setAviso(t("segmento.congelado", { cuantos: r.datos.miembros }));
      cargar();
    } catch (error) {
      setFallo(error);
    } finally {
      setCongelando(false);
    }
  }

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/m/segmentos");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !segmento) return <Fallo error={fallo} reintentar={cargar} />;
  if (!segmento) return <Cargando />;

  const excluye = segmento.excluye ?? [];

  return (
    <>
      <DatosClave
        recurso={recurso}
        tipo="segmento"
        // Las insignias llevan sólo lo que NO es columna preferida del
        // recurso: ésas salen como dato clave aquí mismo, y escribirlas
        // además como insignia las pone dos veces en el mismo panel.
        nombre={segmento.nombre}
        fila={segmento as unknown as Record<string, unknown>}
        // El `tamano` guardado NO: esta pantalla enseña los alcanzables,
        // medidos ahora y con su desglose, y el del listado sale a su lado
        // con la misma cara y otro significado.
        camposClave={["clave", "tamano_at"]}
        volverA={{ a: "/m/segmentos", titulo: modulo?.titulo ?? "", id }}
        distintivos={
          <>
            {/* Dinámico o foto: los dos enseñan un número con la misma cara, y
                sobre el segundo se manda un correo creyendo que es de hoy. */}
            <span
              className={
                segmento.dinamico ? "badge badge-muted" : "badge badge-aviso"
              }
            >
              {t(
                segmento.dinamico
                  ? "segmento.dinamico"
                  : "segmento.congeladoEtiqueta",
              )}
            </span>
            {segmento.descripcion ? (
              <span className="text-dato text-ink-muted">
                {segmento.descripcion}
              </span>
            ) : null}
          </>
        }
        acciones={
          !editando ? (
            <BotonesDeRegistro
              puedeEditar={puedeEditar}
              puedeBorrar={puedeBorrar}
              borrado={borrado}
              alEditar={() => setEditando(true)}
              alBorrar={() => setConfirmando(true)}
            />
          ) : null
        }
      />

      {confirmando ? (
        <ConfirmarBorrado
          borrado={borrado}
          enviando={borrando}
          alBorrar={() => void borrar()}
          alCancelar={() => setConfirmando(false)}
        />
      ) : null}

      {editando && recurso ? (
        <FormularioDeEdicion
          recurso={recurso}
          ruta={ruta}
          valores={segmento as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      {!editando ? (
        <PestanasDeFicha
          tipo="segmento"
          id={id ?? ""}

          etiqueta={t("ficha.secciones")}
          pestanas={[
            { clave: "relacionado", nombre: t("ficha.relacionado") },
            { clave: "detalles", nombre: t("ficha.detalles") },
          ]}
          activa={pestana}
          alElegir={(clave) => setPestana(clave as "relacionado" | "detalles")}
        />
      ) : null}

      <div className="mt-4">
        {editando || pestana === "relacionado" ? (
          <>
            {/* `role="status"`: congelar y medir hacen aparecer un resultado, y quien
            no ve la pantalla no se entera de que ha pasado algo. */}
            <div role="status" aria-live="polite">
              {aviso ? (
                <p className="card mb-3 p-3 text-dato text-ink">{aviso}</p>
              ) : null}
            </div>
            {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}

            <div className="grid gap-4 lg:grid-cols-2">
              <section className="card p-4">
                <h2 className="text-titulo font-medium text-ink">
                  {t("segmento.cuantos")}
                </h2>
                {!tamano ? (
                  <Vacio titulo={t("segmento.sinRecuento")} detalle="" />
                ) : (
                  <>
                    <p className="mt-2 font-mono text-grande text-ink">
                      {tamano.alcanzables}
                    </p>
                    {/* El hueco se NOMBRA. Enseñar sólo el total hace que alguien
                    planifique un envío a diez mil y salga a siete mil sin saber
                    por qué faltan tres mil. */}
                    <p className="mt-1 text-dato text-ink-muted">
                      {t("segmento.deLosCuales", {
                        bruto: tamano.bruto,
                        suprimidos: tamano.suprimidos,
                      })}
                    </p>
                    <p className="mt-1 text-rotulo text-ink-faint">
                      {t("segmento.calculado", {
                        fecha: fechaHora(tamano.calculado_at),
                      })}
                    </p>
                    {tamano.es_foto_congelada ? (
                      <p className="mt-2 text-dato text-warning">
                        {t("segmento.esFoto")}
                      </p>
                    ) : null}
                  </>
                )}
                {segmento.dinamico ? (
                  <button
                    type="button"
                    className="btn-secondary mt-3"
                    disabled={congelando}
                    onClick={() => void congelar()}
                  >
                    {congelando
                      ? t("segmento.congelando")
                      : t("segmento.congelar")}
                  </button>
                ) : null}
                {segmento.dinamico ? (
                  <p className="mt-1 text-rotulo text-ink-faint">
                    {t("segmento.porqueCongelar")}
                  </p>
                ) : null}
                {/* De cuándo son los datos sobre los que se cuenta, y cómo
                    ponerlos al día: un cero sobre una copia vieja no es un
                    cero. */}
                <div className="mt-3 border-t border-ink-dim/30 pt-2">
                  <PerfilesDeMarketing objeto={segmento.objeto} />
                </div>
              </section>

              <section className="card p-4">
                <h2 className="text-titulo font-medium text-ink">
                  {t("segmento.solapamiento")}
                </h2>
                <p className="mt-1 text-rotulo text-ink-faint">
                  {t("segmento.porqueSolape")}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <select
                    className="input-base"
                    value={contra}
                    aria-label={t("segmento.contra")}
                    onChange={(e) => setContra(e.target.value)}
                  >
                    <option value="">{t("segmento.elegirOtro")}</option>
                    {otros.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.nombre}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn-secondary"
                    disabled={!contra || midiendo}
                    onClick={() => void medirSolape()}
                  >
                    {midiendo ? t("segmento.midiendo") : t("segmento.medir")}
                  </button>
                </div>
                {solape ? (
                  <div className="mt-3" role="status" aria-live="polite">
                    <p className="font-mono text-grande text-ink">
                      {solape.comunes}
                    </p>
                    {/* El porcentaje sobre CADA uno: mil comunes es mucho si uno
                    tiene mil doscientos y poco si tiene cien mil. */}
                    <p className="mt-1 text-dato text-ink">
                      {t("segmento.pctDeCada", {
                        // Con la coma de aquí: «66.7 %» salía con punto.
                        a:
                          solape.pct_de_a === null
                            ? "—"
                            : cifra(solape.pct_de_a),
                        b:
                          solape.pct_de_b === null
                            ? "—"
                            : cifra(solape.pct_de_b),
                      })}
                    </p>
                    <p className="mt-1 text-dato text-ink-muted">
                      {t("segmento.solos", {
                        a: solape.solo_a,
                        b: solape.solo_b,
                      })}
                    </p>
                  </div>
                ) : null}
              </section>

              <section className="card p-4 lg:col-span-2">
                <h2 className="text-titulo font-medium text-ink">
                  {t("segmento.definicion")}
                </h2>
                <p className="mt-1 text-rotulo text-ink-faint">
                  {t("segmento.porqueDefinicion")}
                </p>
                <div className="mt-2">
                  <Condicion nodo={segmento.definicion} />
                </div>
                {excluye.length > 0 ? (
                  <p className="mt-3 text-dato text-ink">
                    {t("segmento.excluye", { cuantos: excluye.length })}
                  </p>
                ) : null}
              </section>
            </div>
          </>
        ) : (
          <DetallesDelRegistro
            ruta={ruta}
            objeto="segmento"
            servicio={recurso?.servicio ?? ""}
            id={id}
          />
        )}
      </div>
    </>
  );
}
