/**
 * Lo que se puede hacer con este registro, y hacerlo.
 *
 * Los botones y sus formularios salen del contrato, no de una lista escrita a
 * mano: la superficie dice qué acciones admite el servidor sobre esta ruta y
 * qué permiso exige cada una, y el OpenAPI dice qué campos pide. Una acción
 * nueva en el servidor aparece aquí sola.
 *
 * **Se pide confirmación de lo que no se deshace.** Descartar un lead, cerrar
 * un caso o fusionar dos cuentas no son pulsaciones que se puedan retirar, y un
 * botón que actúa al primer clic es un botón que alguien pulsa sin querer.
 *
 * **Y se dice qué contestó el servidor.** Una acción que no dice nada deja a
 * quien la ejecuta sin saber si pasó algo: la mitad de estas devuelven un
 * resultado —qué se creó, qué quedó pendiente— y esconderlo sería tirar la
 * respuesta a la basura.
 */

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { Formulario } from "@/componentes/Formulario";
import { Icono } from "@/componentes/Icono";
import { Celda } from "@/componentes/Tabla";
import { Link } from "react-router-dom";

import { llamar } from "@/lib/api";
import { escalar, humanizar } from "@/lib/formato";
import { MODULOS, type Recurso } from "@/lib/modulos";
import { recursosDe } from "@/lib/recursos";
import { objetoDe, recursoDeReferencia } from "@/lib/referencias";
import {
  camposDe,
  contratoDe,
  cuerpoDeLosValores,
  type CampoEsquema,
} from "@/lib/contrato";
import { type Accion } from "@/lib/acciones";
import { useSuperficie } from "@/lib/permisos";
import { useFocoDeConfirmacion } from "@/lib/foco";
import { operacionDe } from "@/lib/superficie";

/**
 * Acciones que no se pueden deshacer y se preguntan antes.
 *
 * Por el verbo de la ruta y no por una lista de rutas concretas: `descartar`,
 * `cerrar` o `anular` significan lo mismo los ejecute quien los ejecute, y una
 * lista por ruta se queda corta con el primer recurso nuevo.
 */
const IRREVERSIBLES =
  /^(descartar|cerrar|anular|cancelar|fusionar|purgar|revocar|baja|destruir)/;

/**
 * Lo que devolvió la acción, escrito para una persona.
 *
 * Los identificadores que salen —«se ha creado la oportunidad
 * 01a0ce88-…»— se convierten en un enlace a esa ficha cuando se sabe de qué
 * objeto son. Un UUID suelto obliga a copiarlo y buscarlo a mano, que es
 * exactamente lo que el sistema tenía que ahorrar.
 */
function Resultado({ datos }: { datos: unknown }) {
  const { t } = useTranslation();
  const { superficie } = useSuperficie();
  if (!datos || typeof datos !== "object") return null;
  const pares = Object.entries(datos as Record<string, unknown>).filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );
  if (pares.length === 0) return null;

  return (
    <dl className="mt-2 space-y-1">
      {pares.map(([clave, valor]) => {
        const recurso = recursoDeReferencia(clave);
        const objeto = objetoDe(clave);
        const modulo = recurso ? moduloDelRecurso(recurso) : null;
        const enlazable =
          recurso &&
          modulo &&
          objeto &&
          typeof valor === "string" &&
          UUID_SUELTO.test(valor) &&
          // Y sólo si ese registro se puede LEER: un `producto_id` enlazaba a
          // una ficha que contestaba 404 porque no hay `GET /productos/{id}`.
          Boolean(
            operacionDe(
              superficie,
              "GET",
              `${recurso.listar.split("?")[0]}/${valor}`,
            ),
          );
        return (
          <div
            key={clave}
            className="flex items-baseline justify-between gap-3"
          >
            <dt className="shrink-0 text-rotulo text-ink-faint">
              {humanizar(clave)}
            </dt>
            <dd className="truncate text-dato text-ink">
              {enlazable ? (
                <Link
                  to={`/m/${modulo}/${objeto}/${valor}`}
                  className="text-accent hover:underline"
                >
                  {t("acciones.abrir")}
                </Link>
              ) : typeof valor === "object" ? (
                // Con el mismo renderizador que la tabla y que la ficha: la
                // misma información no puede salir de tres formas distintas
                // según qué panel la enseñe.
                <Celda valor={valor} campo={clave} />
              ) : (
                escalar(valor, clave)
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

const UUID_SUELTO =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** En qué módulo vive un recurso, para poder componer la ruta de su ficha. */
function moduloDelRecurso(recurso: Recurso): string | null {
  for (const modulo of MODULOS) {
    if (recursosDe(modulo.ruta).includes(recurso)) return modulo.ruta;
  }
  return null;
}

/**
 * Lo que ya marcan las casillas del registro, para que la acción lo enseñe.
 * Ver la propiedad `registro` de `Acciones`.
 */
export function casillasDelRegistro(
  campos: CampoEsquema[],
  registro: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  const salida: Record<string, unknown> = {};
  if (!registro) return salida;
  for (const campo of campos) {
    const valor = registro[campo.nombre];
    if (campo.tipo === "booleano" && typeof valor === "boolean") {
      salida[campo.nombre] = valor;
    }
  }
  return salida;
}

/**
 * Cuáles de estas acciones no se deshacen. Lo usa quien pinta la barra para
 * mandarlas al fondo del menú, separadas.
 */
/**
 * «Esto no se deshace», antes de ejecutar de un clic lo que no tiene vuelta.
 * El foco entra en «Cancelar» y, si se cancela, vuelve al botón de la acción
 * (auditoría 13-11-2026, UX-7).
 */
function PreguntaIrreversible({
  nombre,
  alEntender,
  alCancelar,
}: {
  nombre: string;
  alEntender: () => void;
  alCancelar: () => void;
}) {
  const { t } = useTranslation();
  const cancelar = useRef<HTMLButtonElement>(null);
  useFocoDeConfirmacion(cancelar);
  return (
    <div className="mt-3" role="alertdialog" aria-label={nombre}>
      <p className="text-dato text-ink-muted">{t("acciones.noSeDeshace")}</p>
      <div className="mt-3 flex gap-2">
        <button type="button" onClick={alEntender} className="btn-danger">
          {t("acciones.entendido")}
        </button>
        <button
          ref={cancelar}
          type="button"
          onClick={alCancelar}
          className="btn-secondary"
        >
          {t("modulo.cancelar")}
        </button>
      </div>
    </div>
  );
}

export function esIrreversible(accion: Accion): boolean {
  return IRREVERSIBLES.test(accion.clave);
}

export function Acciones({
  acciones,
  servicio,
  alTerminar,
  abierta: abiertaFuera,
  alCambiarAbierta,
  registro,
  recurso: recursoPropio,
}: {
  acciones: Accion[];
  /** Servicio dueño, para leer su contrato. */
  servicio: string;
  /** Se llama tras ejecutar, para que la ficha recargue. */
  alTerminar: () => void;
  /**
   * Qué acción está desplegada, cuando la elige **otro** —el menú de la barra
   * de registro—. Sin esto, esta sección pintaba sus propios botones: siete en
   * la ficha de una cuenta, del mismo peso que «Editar» y «Eliminar», en dos
   * filas que envolvían. Pasándole quién está abierta se queda sólo con el
   * formulario y el resultado, y los botones los ofrece un único menú.
   */
  abierta?: Accion | null;
  alCambiarAbierta?: (accion: Accion | null) => void;
  /**
   * El registro sobre el que se actúa, si se tiene delante.
   *
   * Sirve para que una casilla enseñe **el valor que tiene ahora**: «Activar
   * o desactivar» salía siempre sin marcar, también con la regla encendida,
   * y quien la abría no sabía en qué estado estaba ni qué iba a pasar al
   * pulsar. Sólo las casillas: un texto o una lista vacíos dicen «no lo
   * cambies», y precargarlos con lo de ahora haría que una acción pensada
   * para cambiar algo saliera rellena con lo que se quiere cambiar.
   */
  registro?: Record<string, unknown> | null;
  /**
   * El recurso del registro, para que los campos que apuntan a otro del
   * MISMO tipo —`original_id`, `maestro_id`, `padre_id`— salgan como buscador
   * y no como una caja que pide un identificador.
   */
  recurso?: Recurso | null;
}) {
  const { t } = useTranslation();
  const controlada = alCambiarAbierta !== undefined;
  const [abiertaDentro, setAbiertaDentro] = useState<Accion | null>(null);
  const abierta = controlada ? (abiertaFuera ?? null) : abiertaDentro;
  const setAbierta = controlada
    ? (a: Accion | null) => alCambiarAbierta(a)
    : setAbiertaDentro;
  const [campos, setCampos] = useState<CampoEsquema[] | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [resultado, setResultado] = useState<unknown>(null);
  const [confirmada, setConfirmada] = useState(false);
  // Tras «Lo entiendo», el foco pasa al botón que ejecuta: quien acaba de
  // decir que sí sigue con Intro, sin volver a buscarlo con el tabulador
  // (auditoría 13-11-2026, UX-7).
  const ejecutarSinCampos = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (confirmada) ejecutarSinCampos.current?.focus();
  }, [confirmada]);

  useEffect(() => {
    if (!abierta) return;
    let vivo = true;
    setCampos(null);
    void contratoDe(servicio).then((documento) => {
      if (vivo)
        setCampos(
          // Lo que pone la pantalla no se pregunta.
          camposDe(documento, abierta.plantilla, abierta.metodo).filter(
            (c) => !(c.nombre in (abierta.fijos ?? {})),
          ),
        );
    });
    return () => {
      vivo = false;
    };
  }, [abierta, servicio]);

  // Y los campos de TODAS, por adelantado, para saber cuáles no piden nada.
  //
  // Sin esto, una acción que no necesita ningún dato costaba dos clics: abrir y
  // confirmar en un panel con un solo botón que repite el rótulo del que acabas
  // de pulsar. En la ficha se tolera porque quien abre es el menú de la barra;
  // en un listado, donde el botón está a la vista, es un paso de más en todas.
  // El contrato ya está en caché —lo pide la ficha al entrar—, así que esto no
  // añade una llamada.
  const [camposPorRuta, setCamposPorRuta] = useState<Record<string, number>>(
    {},
  );
  useEffect(() => {
    if (controlada || !servicio || acciones.length === 0) return;
    let vivo = true;
    void contratoDe(servicio).then((documento) => {
      if (!vivo) return;
      const cuenta: Record<string, number> = {};
      for (const a of acciones) {
        cuenta[a.ruta] = camposDe(documento, a.plantilla, a.metodo).filter(
          (c) => !(c.nombre in (a.fijos ?? {})),
        ).length;
      }
      setCamposPorRuta(cuenta);
    });
    return () => {
      vivo = false;
    };
    // `acciones` se recalcula en cada render de quien llama; lo que importa es
    // qué rutas hay, y eso se resume en la lista de rutas.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controlada, servicio, acciones.map((a) => a.ruta).join("|")]);

  if (acciones.length === 0) return null;

  async function ejecutar(
    valores: Record<string, unknown>,
    accion: Accion | null = abierta,
  ) {
    if (!accion) return;
    setEnviando(true);
    setFallo(null);
    try {
      // Con el método de la operación: la mayoría son `POST`, pero las de una
      // fila sin ficha también son quitar (`DELETE`) y editar por clave
      // (`PUT`), y mandarlas todas como `POST` contestaría 405.
      const metodo = accion.metodo.toUpperCase();
      const r = await llamar<unknown>(accion.ruta, {
        metodo,
        // El cuerpo lo arma el contrato: hay operaciones cuyo único campo ES
        // el cuerpo, y meterlo dentro de una llave las rompería.
        // Un `DELETE` sin campos va sin cuerpo; con campos, con ellos. Se
        // tiraba siempre, y «Levantar una supresión», que exige el motivo
        // escrito, contestaba 422 con el motivo rellenado (10-11-2026).
        cuerpo:
          metodo === "DELETE" && (accion !== abierta || !(campos ?? []).length)
            ? undefined
            : accion.fijos
              ? {
                  ...(cuerpoDeLosValores(campos ?? [], valores) as Record<
                    string,
                    unknown
                  >),
                  ...accion.fijos,
                }
              : cuerpoDeLosValores(campos ?? [], valores),
      });
      setResultado(r.datos ?? { hecho: true });
      setAbierta(null);
      setConfirmada(false);
      alTerminar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  const irreversible = abierta ? IRREVERSIBLES.test(abierta.clave) : false;

  return (
    <section className="mb-3" aria-label={t("acciones.titulo")}>
      {/* Sólo cuando nadie los ofrece desde fuera: si la barra de registro ya
          los lleva en su menú, pintarlos aquí otra vez sería la pared de
          botones que esto viene a quitar. */}
      <div className={controlada ? "hidden" : "flex flex-wrap gap-2"}>
        {acciones.map((a) => (
          <button
            key={a.ruta}
            type="button"
            disabled={enviando}
            onClick={() => {
              setConfirmada(false);
              setResultado(null);
              setFallo(null);
              if (camposPorRuta[a.ruta] === 0 && !IRREVERSIBLES.test(a.clave)) {
                void ejecutar({}, a);
                return;
              }
              setAbierta(a);
            }}
            className={
              abierta?.ruta === a.ruta ? "btn-primary" : "btn-secondary"
            }
          >
            {a.nombre}
          </button>
        ))}
      </div>

      {/* La frase de ayuda de las que la llevan. Es para lo que no se adivina
          por el rótulo: «Cargar ahora» no dice de dónde trae las filas. */}
      {!controlada && acciones.some((a) => a.detalle) ? (
        <div className="mt-1.5 flex flex-col gap-1">
          {acciones
            .filter((a) => a.detalle)
            .map((a) => (
              <p key={a.ruta} className="text-rotulo text-ink-faint">
                {a.detalle}
              </p>
            ))}
        </div>
      ) : null}

      {resultado ? (
        <div className="card mt-3 border-success/40 p-3" role="status">
          <p className="inline-flex items-center gap-1.5 text-titulin text-success">
            <Icono nombre="check_circle" tamano="sm" />
            {t("acciones.hecho")}
          </p>
          {/* Lo que contestó el servidor, en legible. La mitad de estas acciones
              devuelven algo que importa —qué se creó, qué quedó pendiente— y
              esconderlo sería tirar la respuesta; pero enseñarla en JSON con
              UUID dentro es lo mismo que esconderla. */}
          <Resultado datos={resultado} />
        </div>
      ) : null}

      {abierta ? (
        <div className="card mt-3 p-4">
          <h3 className="text-titulin font-medium text-ink">
            {abierta.nombre}
          </h3>

          {/* **Confirmar sólo lo que se ejecuta de un clic.** Si la acción
              tiene formulario —cerrar un caso pide el motivo—, rellenarlo y
              pulsar ya es decidir, y el aviso va encima de él. Antes salía
              además «Lo entiendo, sigue» y después el formulario: dos pasos
              para una sola decisión (tarea T10, 10-11-2026). */}
          {campos === null ? (
            <Cargando />
          ) : irreversible && !confirmada && campos.length === 0 ? (
            <PreguntaIrreversible
              nombre={abierta.nombre}
              alEntender={() => setConfirmada(true)}
              alCancelar={() => setAbierta(null)}
            />
          ) : (
            <div className="mt-3">
              {irreversible && campos.length > 0 ? (
                <p className="mb-2 text-dato text-ink-muted" role="note">
                  {t("acciones.noSeDeshace")}
                </p>
              ) : null}
              {campos.length === 0 ? (
                // Sin campos no se enseña un formulario vacío: se ejecuta y ya.
                <button
                  ref={ejecutarSinCampos}
                  type="button"
                  disabled={enviando}
                  onClick={() => void ejecutar({})}
                  className="btn-primary"
                >
                  {enviando ? t("app.cargando") : abierta.nombre}
                </button>
              ) : (
                <Formulario
                  fallo={fallo}
                  propio={recursoPropio}
                  campos={campos}
                  valores={casillasDelRegistro(campos, registro)}
                  enviando={enviando}
                  textoEnviar={abierta.nombre}
                  alEnviar={(v) => void ejecutar(v)}
                />
              )}
              <button
                type="button"
                onClick={() => setAbierta(null)}
                className="btn-link mt-3"
              >
                {t("modulo.cancelar")}
              </button>
            </div>
          )}

          {fallo ? (
            <div className="mt-3">
              <Fallo error={fallo} />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
