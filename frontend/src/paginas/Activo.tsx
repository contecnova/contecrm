/**
 * Un activo instalado: de qué cuelga, qué le ha pasado y si está en garantía
 * (CRM-04.04.02.02, CRM-04.04.02.04).
 *
 * Un activo no es una ficha de inventario: es la máquina que hay en casa del
 * cliente, y lo que se pregunta delante de ella son tres cosas.
 *
 * **«¿De qué forma parte?»** El árbol de componentes. Una avería en una bomba
 * no se entiende sin saber de qué equipo es, y un componente que se mira solo
 * lleva a cambiar la pieza y no la causa. El servidor corta el árbol a seis
 * niveles y **dice que lo ha cortado**: un árbol truncado sin avisar se lee
 * como un árbol completo.
 *
 * **«¿Qué le ha pasado?»** Y aquí está lo que hace útil al historial: sigue la
 * **cadena de sustituciones**. Si la máquina se cambió hace dos años, su
 * historial empieza en la que estaba antes — porque la avería de hoy puede
 * venir de aquello, y un historial que arranca en la sustitución oculta justo
 * el patrón que había que ver. El número de equipos de la cadena va delante.
 *
 * **«¿Lo paga la garantía?»** Y la respuesta importante no es sí o no: es
 * **si es concluyente**. Una cobertura que no se puede determinar y una que
 * dice que no se leen igual en una pantalla, y la diferencia es quién paga
 * una reparación de cuatro mil euros.
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
import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { DatosClave } from "@/componentes/DatosClave";
import { DetallesDelRegistro } from "@/componentes/DetallesDelRegistro";
import { PestanasDeFicha } from "@/componentes/PestanasDeFicha";
import { llamar, salvoCancelacion } from "@/lib/api";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";
import { fecha } from "@/lib/formato";

interface Nodo {
  id: string;
  codigo: string;
  nombre: string;
  numero_serie: string | null;
  estado: string;
  componentes: Nodo[];
  /** El árbol se corta a seis niveles, y se dice. */
  truncado?: boolean;
}

interface Evento {
  tipo?: string;
  cuando?: string;
  detalle?: Record<string, unknown>;
  activo_id?: string;
}

interface Historial {
  activo_id: string;
  /** Los identificadores de la cadena de sustituciones, no su número. */
  equipos_en_la_cadena: string[];
  eventos: Evento[];
}

interface Cobertura {
  cubierto: boolean;
  /** Lo que de verdad decide: «no se sabe» y «no» se leen igual y no lo son. */
  concluyente: boolean;
  garantia_id?: string | null;
  tipo?: string | null;
  hasta?: string | null;
  proveedor?: string | null;
  exclusiones?: string[];
  motivo: string;
  garantias: unknown[];
}

/**
 * El contador sale de la ficha del activo, no de una ruta propia.
 *
 * `leer_contador` **anota** una lectura —escribe— pese al nombre, así que no
 * hay forma de consultarlo sin registrar una. La ficha ya trae la columna con
 * la fecha de la última lectura, que es lo que hace falta aquí: un contador
 * sin fecha al lado no dice si es de hoy o del año pasado.
 */
interface FichaDelActivo {
  contador: number | null;
  unidad_contador: string | null;
  contador_at: string | null;
}

function Rama({ nodo, nivel = 0 }: { nodo: Nodo; nivel?: number }) {
  const { t } = useTranslation();
  return (
    <li style={{ marginLeft: nivel * 12 }}>
      <span className="text-dato text-ink">{nodo.nombre}</span>{" "}
      <span className="chip-dato font-mono">{nodo.codigo}</span>{" "}
      <span className="text-rotulo text-ink-muted">{nodo.estado}</span>
      {/* Un árbol cortado sin avisar se lee como un árbol completo. */}
      {nodo.truncado ? (
        <span className="ml-1 text-rotulo text-warning">
          {t("activo.truncado")}
        </span>
      ) : null}
      {(nodo.componentes ?? []).length > 0 ? (
        <ul className="mt-1 flex flex-col gap-1">
          {nodo.componentes.map((hijo) => (
            <Rama key={hijo.id} nodo={hijo} nivel={nivel + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function Activo() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [arbol, setArbol] = useState<Nodo | null>(null);
  const [historial, setHistorial] = useState<Historial | null>(null);
  const [cobertura, setCobertura] = useState<Cobertura | null>(null);
  const [ficha, setFicha] = useState<FichaDelActivo | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const navegar = useNavigate();
  const modulo = moduloDe("campo");
  const recurso = modulo ? recursoDe(modulo, "activo") : undefined;
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
    llamar<Nodo>(`/api/v1/activos/${id}/arbol`, { signal })
      .then((r) => setArbol(r.datos))
      .catch(salvoCancelacion(setFallo));
    llamar<Historial>(`/api/v1/activos/${id}/historial`, { signal })
      .then((r) => setHistorial(r.datos))
      .catch(salvoCancelacion(() => setHistorial(null)));
    llamar<Cobertura>(`/api/v1/activos/${id}/cobertura`, { signal })
      .then((r) => setCobertura(r.datos))
      .catch(salvoCancelacion(() => setCobertura(null)));
    llamar<FichaDelActivo>(`/api/v1/activos/${id}`, { signal })
      .then((r) => setFicha(r.datos))
      .catch(salvoCancelacion(() => setFicha(null)));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/m/campo");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !arbol) return <Fallo error={fallo} reintentar={cargar} />;
  if (!arbol) return <Cargando />;

  const eventos = historial?.eventos ?? [];

  return (
    <>
      <DatosClave
        recurso={recurso}
        tipo="activo"
        // Las insignias llevan sólo lo que NO es columna preferida del
        // recurso: ésas salen como dato clave aquí mismo, y escribirlas
        // además como insignia las pone dos veces en el mismo panel.
        nombre={arbol.nombre}
        fila={arbol as unknown as Record<string, unknown>}
        volverA={{ a: "/m/campo", titulo: modulo?.titulo ?? "", id }}
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
          valores={arbol as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      {!editando ? (
        <PestanasDeFicha
          tipo="activo"
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
            <div className="grid gap-4 lg:grid-cols-2">
              <section className="card p-4">
                <h2 className="text-titulo font-medium text-ink">
                  {t("activo.cobertura")}
                </h2>
                {!cobertura ? (
                  <Vacio
                    compacto
                    titulo={t("activo.sinCobertura")}
                    detalle=""
                  />
                ) : !cobertura.concluyente ? (
                  /* Lo que de verdad decide: «no se sabe» no es «no». */
                  <>
                    <p className="mt-2 text-dato text-warning">
                      {t("activo.noConcluyente")}
                    </p>
                    <p className="mt-1 text-dato text-ink">
                      {cobertura.motivo}
                    </p>
                  </>
                ) : (
                  <>
                    <p
                      className={
                        cobertura.cubierto
                          ? "mt-2 text-dato text-success"
                          : "mt-2 text-dato text-ink"
                      }
                    >
                      {t(
                        cobertura.cubierto
                          ? "activo.cubierto"
                          : "activo.noCubierto",
                      )}
                    </p>
                    <p className="mt-1 text-dato text-ink-muted">
                      {cobertura.motivo}
                    </p>
                    {cobertura.hasta ? (
                      <p className="mt-1 font-mono text-rotulo text-ink-faint">
                        {t("activo.hasta", { fecha: cobertura.hasta })}
                      </p>
                    ) : null}
                    {(cobertura.exclusiones ?? []).length > 0 ? (
                      <p className="mt-1 text-dato text-warning">
                        {t("activo.exclusiones", {
                          cuantas: (cobertura.exclusiones ?? []).length,
                        })}
                      </p>
                    ) : null}
                  </>
                )}
              </section>

              <section className="card p-4">
                <h2 className="text-titulo font-medium text-ink">
                  {t("activo.contador")}
                </h2>
                {!ficha || ficha.contador === null ? (
                  <Vacio compacto titulo={t("activo.sinContador")} detalle="" />
                ) : (
                  <>
                    <p className="mt-2 font-mono text-grande text-ink">
                      {t("activo.lectura", {
                        contador: ficha.contador,
                        unidad: ficha.unidad_contador ?? "",
                      })}
                    </p>
                    {/* Con su fecha SIEMPRE: una lectura sin fecha al lado se lee
                    como la de hoy, y sobre eso se decide un mantenimiento. */}
                    <p className="mt-1 text-dato text-ink-muted">
                      {ficha.contador_at
                        ? t("activo.leidoEl", {
                            fecha: fecha(ficha.contador_at),
                          })
                        : t("activo.sinFechaDeLectura")}
                    </p>
                  </>
                )}
              </section>

              <section className="card p-4">
                <h2 className="text-titulo font-medium text-ink">
                  {t("activo.arbol")}
                </h2>
                <p className="mt-1 text-rotulo text-ink-faint">
                  {t("activo.porqueArbol")}
                </p>
                <ul className="lista-acotada mt-2 flex flex-col gap-1 pr-1">
                  <Rama nodo={arbol} />
                </ul>
              </section>

              <section className="card p-4">
                <h2 className="text-titulo font-medium text-ink">
                  {t("activo.historial")}
                </h2>
                {/* La cadena delante: un historial que arranca en la sustitución
                esconde justo el patrón que había que ver. */}
                {(historial?.equipos_en_la_cadena ?? []).length > 1 ? (
                  <p className="mt-1 text-dato text-ink">
                    {t("activo.cadena", {
                      equipos: (historial?.equipos_en_la_cadena ?? []).length,
                    })}
                  </p>
                ) : null}
                {eventos.length === 0 ? (
                  <Vacio compacto titulo={t("activo.sinEventos")} detalle="" />
                ) : (
                  <ul className="lista-acotada mt-2 flex flex-col gap-1 pr-1">
                    {eventos.map((e, i) => (
                      <li key={i} className="flex items-baseline gap-2">
                        <span className="chip-dato">{e.tipo}</span>
                        <span className="flex-1 font-mono text-rotulo text-ink-muted">
                          {fecha(e.cuando)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </>
        ) : (
          <DetallesDelRegistro
            ruta={ruta}
            objeto="activo"
            servicio={recurso?.servicio ?? ""}
            id={id}
          />
        )}
      </div>
    </>
  );
}
