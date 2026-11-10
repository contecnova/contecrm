/**
 * Un caso: con qué tiene que ver, cómo va su reloj y cómo acabó
 * (CRM-04.01.01.03, CRM-04.01.01.04, CRM-04.01.01.06, CRM-04.01.01.09,
 * CRM-04.01.01.10, CRM-04.01.02.06, CRM-04.03.01.05).
 *
 * La bandeja dice qué atender primero; abrir un caso es otra cosa. Lo que se
 * necesita delante es **de qué cliente es, sobre qué producto o activo, de
 * quién cuelga y cuánto queda**, y la ficha genérica enseñaba una lista de
 * campos con seis UUID sueltos.
 *
 * Tres decisiones:
 *
 * **Los dos incumplimientos van separados.** Incumplir la primera respuesta y
 * incumplir la resolución son dos conversaciones distintas con el cliente, y
 * sumarlos en un «SLA incumplido» hace que la primera —que es la que todavía
 * se puede salvar— no se mire.
 *
 * **El reloj parado se dice.** Un caso que lleva seis días esperando al
 * cliente no lleva seis días sin atenderse, y en una lista se ven igual.
 *
 * **Y un caso cerrado pendiente de que el cliente lo dé por bueno NO está
 * cerrado.** Es la mitad que casi nunca se publica, y la que hace que un
 * informe de cierres diga lo que no es.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

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
import { Acciones, esIrreversible } from "@/componentes/Acciones";
import { AsistenteIA, esDeIA } from "@/componentes/AsistenteIA";
import { ActividadDelRegistro } from "@/componentes/ActividadDelRegistro";
import { ResponderCaso } from "@/componentes/ResponderCaso";
import { accionesDe, type Accion } from "@/lib/acciones";
import { useSuperficie } from "@/lib/permisos";
import { listar } from "@/lib/listados";
import { fecha, fechaHora, rotuloDeOpcion } from "@/lib/formato";
import { moduloDe, moduloDeObjeto } from "@/lib/modulos";
import { nombresDeRegistros, type NombresResueltos } from "@/lib/nombres";
import { recursoDe } from "@/lib/recursos";
import { cn } from "@/lib/utiles";

interface Asignacion {
  at: string;
  regla: string | null;
  asignado_a: string | null;
  cola: string | null;
  estrategia: string | null;
  motivo: string | null;
  /** Cuántas reglas se miraron antes de ésta. Sin eso, «ninguna coincidió» y
   *  «se cogió la primera» se cuentan igual. */
  evaluadas: number | null;
}

interface Bolsa {
  incluidas?: string | null;
  incluidos?: number | null;
  consumidas?: string;
  consumidos?: number;
  restantes?: string | number | null;
  sin_limite: boolean;
  agotado: boolean;
}

interface Saldo {
  entitlement: string;
  al_agotar: string | null;
  horas: Bolsa;
  casos: Bolsa;
  vigente_hasta: string | null;
}

interface Sla {
  clave: string | null;
  version: number | null;
  vence_primera_respuesta_at: string | null;
  vence_resolucion_at: string | null;
  primera_respuesta_at: string | null;
  pausa_acumulada_s: number;
  /** Si el reloj está parado ahora mismo (esperando al cliente), desde cuándo. */
  pausado_desde?: string | null;
  incumplio_primera_respuesta: boolean;
  incumplio_resolucion: boolean;
}

interface CasoRelacionado {
  id: string;
  asunto: string;
  estado: string;
}

interface Arbol {
  caso: string;
  padre: string | null;
  /** La incidencia masiva de la que cuelga, si cuelga de alguna. */
  maestro?: string | null;
  duplicado_de: string | null;
  /** El asunto de padre, maestro y original, por su identificador. */
  asuntos?: Record<string, string>;
  hijos: CasoRelacionado[];
  colgados_del_maestro: CasoRelacionado[];
  duplicados?: CasoRelacionado[];
}

interface Cierre {
  motivo: string | null;
  resolucion: string | null;
  validacion_cliente: string | null;
  reaperturas: number;
  cerrado_at: string | null;
  resuelto_at: string | null;
}

interface Caso {
  id: string;
  codigo: string | null;
  asunto: string;
  descripcion: string | null;
  estado: string;
  prioridad: string;
  severidad: string;
  /** La cola en la que está. */
  equipo?: string | null;
  /**
   * El camino de categorías, de la raíz a la hoja.
   *
   * Es una LISTA —`ruta_de_categoria` la devuelve así porque los informes
   * agrupan por nivel—, y aquí estaba declarada como texto. React pinta una
   * lista pegando sus elementos sin nada en medio, así que en la cabecera de
   * un caso salía «Calidad de productoAcabado y aspecto». Un tipo equivocado
   * no da error: da una palabra inventada.
   */
  clasificacion?: string[] | null;
  relacionado_con: Record<string, string | null>;
  cierre: Cierre;
  sla: Sla;
  relaciones: Arbol;
  historial: { tipo: string; detalle: Record<string, unknown>; at: string }[];
}

/**
 * De qué tipo de registro es cada relación.
 *
 * Con el tipo se resuelve su NOMBRE y la pantalla que lo enseña. Antes la
 * cuenta salía como «Cliente · Abrir» —sin decir qué cliente— y el activo,
 * el contrato, el producto y el pedido como los ocho primeros caracteres de
 * su UUID: el agente tenía que abrir otra pantalla para saber de quién era el
 * caso. Medido el 10-11-2026 recorriendo la ficha de un caso.
 */
const TIPO_DE: Record<string, string> = {
  cuenta_id: "cuenta",
  contacto_id: "contacto",
  producto_id: "producto",
  activo_id: "activo",
  contrato_id: "contrato",
  pedido_id: "pedido",
};

export function Caso() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [caso, setCaso] = useState<Caso | null>(null);
  const [porQueAqui, setPorQueAqui] = useState<Asignacion[] | null>(null);
  const [saldo, setSaldo] = useState<Saldo | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  // Derivar a otra cola o a otro nivel (CRM-04.01.01.08).
  const [derivando, setDerivando] = useState(false);
  // Contestar al cliente por correo: sale de verdad (10-11-2026).
  const [respondiendo, setRespondiendo] = useState(false);
  const navegar = useNavigate();
  // El mismo recurso que el listado: dos pantallas que enseñan el mismo
  // registro tienen que escribirlo por la misma ruta y el mismo contrato.
  const modulo = moduloDe("casos");
  const recurso = modulo ? recursoDe(modulo, "caso") : undefined;
  const { ruta, puedeEditar, puedeBorrar, borrado } = useEdicion(recurso, id);
  // Las acciones del contrato sobre el caso —resumirlo y sugerir respuesta con IA, entre otras— en el menú, igual que en la ficha del cliente.
  const { superficie, tiene } = useSuperficie();
  const [accionAbierta, setAccionAbierta] = useState<Accion | null>(null);
  const acciones = accionesDe(superficie, "/api/v1/casos", id ?? "", tiene);
  // Las mismas dos pestañas que las demás fichas. «Relacionado» es todo lo
  // que esta pantalla ya enseñaba —con qué tiene que ver, el reloj, de qué
  // cuelga, cómo acabó— y «Detalles» son sus campos, que hasta hoy sólo se
  // podían leer entrando en «Editar».
  const [pestana, setPestana] = useState<"relacionado" | "detalles">(
    "relacionado",
  );

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Caso>(`/api/v1/casos/${id}`, { signal: control.signal })
      .then(({ datos }) => {
        setCaso(datos);
        // Qué derecho cubre esto se pregunta POR EL CLIENTE del caso, no por
        // el caso: el derecho es del contrato, y hasta que no se sabe de quién
        // es el caso no hay a quién preguntárselo.
        const cuenta = datos.relacionado_con?.cuenta_id;
        if (!cuenta) return;
        // `aplicable` ya trae el saldo. Se esperaba un `entitlement_id` que
        // la ruta no devuelve, así que el panel no salía en NINGÚN caso
        // (medido el 10-11-2026 con un derecho recién imputado).
        void llamar<{ tiene_derecho?: boolean; saldo?: Saldo | null }>(
          `/api/v1/entitlements/aplicable?cuenta_id=${cuenta}`,
          { signal: control.signal },
        )
          .then((r) => {
            if (r.datos?.tiene_derecho && r.datos.saldo)
              setSaldo(r.datos.saldo);
          })
          .catch(() => undefined);
      })
      .catch(salvoCancelacion(setFallo));

    void llamar<Asignacion[]>(`/api/v1/colas/explicar/${id}`, {
      signal: control.signal,
    })
      .then((r) => setPorQueAqui(r.datos))
      .catch(() => undefined);

    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/m/casos");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !caso) return <Fallo error={fallo} reintentar={cargar} />;
  if (!caso) return <Cargando />;

  return (
    <>
      {/* El mismo panel de cabecera que la cuenta, la oportunidad y la ficha
          genérica. Aquí era un título suelto sobre el fondo de la página, con
          los botones colgando debajo: cuatro fichas del mismo producto con
          dos cabeceras distintas, y en ésta no había ni panel ni sitio para
          los botones. */}
      <DatosClave
        recurso={recurso}
        tipo="caso"
        nombre={caso.asunto}
        fila={caso as unknown as Record<string, unknown>}
        volverA={{ a: "/m/casos", titulo: modulo?.titulo ?? "", id }}
        // El estado se mueve desde aquí, con los que la empresa haya
        // configurado: el `POST …/estado` del caso para y reanuda el reloj.
        cambioDeEstado={{
          servicio: "service",
          ruta: `/api/v1/casos/${id}`,
          alCambiar: () => cargar(),
        }}
        // Sólo lo que NO está ya en los datos clave de debajo. El código, el
        // estado y la prioridad son las columnas preferidas del recurso, así
        // que salían dos veces en el mismo panel: como insignia arriba y como
        // par etiqueta/valor tres centímetros más abajo.
        distintivos={
          <>
            <span className="chip-dato">{caso.severidad}</span>
            {/* La ruta de categorías con sus escalones separados: es un
                camino, de lo general a lo concreto. */}
            {(caso.clasificacion ?? []).length > 0 ? (
              <span className="text-dato text-ink-muted">
                {(caso.clasificacion ?? []).join(" › ")}
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
              destacadas={recurso?.destacadas}
              extra={[
                // Derivar: a segundo nivel, a ingeniería o a una cola interna.
                // La ruta existía y sólo se llegaba desde «Escalado»; la
                // pregunta se hace delante del caso, no en otra pantalla.
                ...(puedeEditar
                  ? [
                      {
                        clave: "derivar",
                        nombre: t("caso.derivar.boton"),
                        alElegir: () => setDerivando(true),
                        destructiva: false,
                      },
                    ]
                  : []),
                ...acciones
                  .filter((a) => !esDeIA(a))
                  .map((a) => ({
                    clave: a.ruta,
                    nombre: a.nombre,
                    // Responder tiene su formulario: el genérico diría «Hecho»
                    // aunque el correo no hubiera salido.
                    alElegir: a.ruta.endsWith("/responder")
                      ? () => setRespondiendo(true)
                      : () => setAccionAbierta(a),
                    destructiva: esIrreversible(a),
                  })),
              ]}
            />
          ) : null
        }
      />

      {respondiendo ? (
        <ResponderCaso
          casoId={id}
          contactoId={caso.relacionado_con?.contacto_id}
          alTerminar={() => cargar()}
          alCancelar={() => setRespondiendo(false)}
        />
      ) : null}

      {derivando ? (
        <DerivarCaso
          casoId={id}
          equipo={caso.equipo ?? null}
          alTerminar={() => {
            setDerivando(false);
            cargar();
          }}
          alCancelar={() => setDerivando(false)}
        />
      ) : null}

      {confirmando ? (
        <ConfirmarBorrado
          borrado={borrado}
          enviando={borrando}
          alBorrar={() => void borrar()}
          alCancelar={() => setConfirmando(false)}
        />
      ) : null}

      <AsistenteIA
        acciones={acciones}

        abierta={accionAbierta}

        alElegir={setAccionAbierta}
      />

      <Acciones
        acciones={acciones}
        recurso={recurso}

        servicio="service"

        abierta={accionAbierta}

        alCambiarAbierta={setAccionAbierta}

        alTerminar={() => cargar()}
      />

      {editando && recurso ? (
        <FormularioDeEdicion
          recurso={recurso}
          ruta={ruta}
          valores={caso as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      {!editando ? (
        <PestanasDeFicha
          tipo="caso"
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
            {caso.descripcion ? (
              <p className="card mb-4 p-3 text-dato text-ink-muted">
                {caso.descripcion}
              </p>
            ) : null}

            {/* Apuntar la respuesta que se le dio al cliente, delante del caso
                y sin teclear su identificador en otra pantalla. */}
            {!editando ? (
              <ActividadDelRegistro objeto="caso" objetoId={id ?? ""} />
            ) : null}

            <div className="grid gap-4 lg:grid-cols-2">
              <ConQueTieneQueVer relaciones={caso.relacionado_con} />
              <ElReloj sla={caso.sla} />
              <DeQuienCuelga arbol={caso.relaciones} />
              <ComoAcabo cierre={caso.cierre} casoId={id} />
              <PorQueEstaAqui asignaciones={porQueAqui} />
              <QueDerechoLoCubre saldo={saldo} />
            </div>

            <ElHistorial eventos={caso.historial} />
          </>
        ) : (
          <DetallesDelRegistro
            ruta={ruta}
            objeto="caso"
            servicio={recurso?.servicio ?? ""}
            id={id}
          />
        )}
      </div>
    </>
  );
}

/**
 * Con qué tiene que ver (CRM-04.01.01.03).
 *
 * Los seis, no sólo el cliente: un caso sobre un activo instalado se atiende
 * distinto que uno sobre un pedido, y sin el activo hay que preguntárselo al
 * cliente, que ya lo dijo al abrirlo.
 */
function ConQueTieneQueVer({
  relaciones,
}: {
  relaciones: Record<string, string | null>;
}) {
  const { t } = useTranslation();
  const puestas = Object.entries(relaciones ?? {}).filter(([, v]) => v) as [
    string,
    string,
  ][];
  const [resueltos, setResueltos] = useState<NombresResueltos | null>(null);
  const clave = puestas.map(([c, v]) => `${c}:${v}`).join(",");

  useEffect(() => {
    if (!clave) return;
    const control = new AbortController();
    void nombresDeRegistros(
      clave.split(",").map((par) => {
        const [campo = "", id = ""] = par.split(":");
        return { objeto_tipo: TIPO_DE[campo] ?? "", objeto_id: id };
      }),
      control.signal,
    ).then((r) => {
      if (!control.signal.aborted) setResueltos(r);
    });
    return () => control.abort();
  }, [clave]);

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("caso.relacionado")}</h2>
      {puestas.length === 0 ? (
        <Vacio titulo={t("caso.sinRelaciones")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {puestas.map(([campo, valor]) => {
            const tipo = TIPO_DE[campo] ?? "";
            const nombre = resueltos?.nombres.get(valor);
            // Un tipo que se pudo preguntar y no trae el registro: ya no
            // existe. Uno que no se pudo preguntar: no se sabe, y se dice así.
            const texto =
              nombre ??
              (resueltos === null
                ? "…"
                : resueltos.preguntados.has(tipo)
                  ? t("caso.yaNoEsta")
                  : t("caso.sinNombre"));
            // Sólo se enlaza lo que TIENE ficha y sigue existiendo: un enlace
            // a una pantalla que no existe parece que algo se ha roto.
            const adonde = nombre && moduloDeObjeto(tipo);
            return (
              <li
                key={campo}
                className="flex items-baseline justify-between gap-3 py-1.5"
              >
                <span className="text-rotulo text-ink-faint">
                  {t(`caso.rel.${campo}`)}
                </span>
                {adonde ? (
                  <Link
                    to={`/m/${adonde}/${tipo}/${valor}`}
                    className="truncate text-dato text-ink hover:underline"
                  >
                    {nombre}
                  </Link>
                ) : (
                  <span className="truncate text-dato text-ink-muted">
                    {texto}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/**
 * El reloj, con los dos incumplimientos por separado (CRM-04.01.02.03).
 *
 * Y la pausa: un caso que lleva seis días esperando al cliente no lleva seis
 * días sin atenderse, y en una lista se ven igual.
 */
function ElReloj({ sla }: { sla: Sla }) {
  const { t } = useTranslation();
  if (!sla?.clave) {
    return (
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("caso.reloj")}</h2>
        <Vacio titulo={t("caso.sinSla")} compacto />
      </section>
    );
  }

  const horasEnPausa = Math.round((sla.pausa_acumulada_s ?? 0) / 360) / 10;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("caso.reloj")}</h2>
      <p className="text-rotulo text-ink-faint">
        {t("caso.sla", { clave: sla.clave, version: sla.version })}
      </p>
      <ul className="mt-2 space-y-1 text-dato">
        <li
          className={
            sla.incumplio_primera_respuesta ? "text-danger" : "text-ink-muted"
          }
        >
          {sla.incumplio_primera_respuesta
            ? t("caso.incumplioPrimera")
            : t("caso.primeraVence", {
                cuando: fechaHora(sla.vence_primera_respuesta_at),
              })}
        </li>
        <li
          className={
            sla.incumplio_resolucion ? "text-danger" : "text-ink-muted"
          }
        >
          {sla.incumplio_resolucion
            ? t("caso.incumplioResolucion")
            : t("caso.resolucionVence", {
                cuando: fechaHora(sla.vence_resolucion_at),
              })}
        </li>
      </ul>
      {sla.pausado_desde ? (
        <p className="mt-1 text-dato text-warning">
          {t("caso.relojParado", { desde: fechaHora(sla.pausado_desde) })}
        </p>
      ) : null}
      {horasEnPausa > 0 ? (
        <p className="mt-2 text-rotulo text-warning">
          {t("caso.enPausa", { horas: horasEnPausa })}
        </p>
      ) : null}
    </section>
  );
}

/**
 * De quién cuelga y qué cuelga de él (CRM-04.01.01.04).
 *
 * Un caso duplicado que no dice de cuál lo es obliga a buscarlo, y mientras
 * tanto se contesta dos veces al mismo cliente.
 */
function DeQuienCuelga({ arbol }: { arbol: Arbol }) {
  const { t } = useTranslation();
  const asuntos = arbol?.asuntos ?? {};
  // Hacia arriba: de qué cuelga. Con el asunto del otro caso: «cuelga de otro
  // caso» obligaba a pinchar para saber de cuál.
  const arriba = (
    [
      ["cuelgaDe", arbol?.padre],
      ["colgadoDe", arbol?.maestro],
      ["duplicadoDe", arbol?.duplicado_de],
    ] as const
  ).filter(([, id]) => id) as [string, string][];
  // Hacia abajo, cada relación en su grupo: un hijo, un caso colgado de una
  // incidencia masiva y un duplicado se tratan distinto, y en una sola lista
  // no se distinguían.
  const abajo = (
    [
      ["hijos", arbol?.hijos ?? []],
      ["colgados", arbol?.colgados_del_maestro ?? []],
      ["duplicados", arbol?.duplicados ?? []],
    ] as const
  ).filter(([, lista]) => lista.length > 0);

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("caso.jerarquia")}</h2>
      {arriba.length === 0 && abajo.length === 0 ? (
        <Vacio titulo={t("caso.sinJerarquia")} compacto />
      ) : (
        <div className="space-y-2 text-dato">
          {arriba.length > 0 ? (
            <ul className="space-y-1">
              {arriba.map(([clave, id]) => (
                <li
                  key={clave}
                  className={cn(
                    "flex flex-wrap items-baseline gap-x-2",
                    clave === "duplicadoDe" && "text-warning",
                  )}
                >
                  <span className="text-rotulo text-ink-faint">
                    {t(`caso.${clave}`)}
                  </span>
                  {asuntos[id] ? (
                    <Link
                      to={`/m/casos/caso/${id}`}
                      className="hover:underline"
                    >
                      {asuntos[id]}
                    </Link>
                  ) : (
                    <span className="text-ink-muted">
                      {t("caso.yaNoExiste")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
          {abajo.map(([clave, lista]) => (
            <div key={clave}>
              <p className="text-rotulo text-ink-faint">
                {t(`caso.${clave}`, { cuantos: lista.length })}
              </p>
              <ul className="space-y-1">
                {lista.map((h) => (
                  <li
                    key={h.id}
                    className="flex flex-wrap items-baseline gap-x-2"
                  >
                    <Link
                      to={`/m/casos/caso/${h.id}`}
                      className="text-ink hover:underline"
                    >
                      {h.asunto}
                    </Link>
                    <span className="chip-dato">{h.estado}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/**
 * Cómo acabó (CRM-04.01.01.09, CRM-04.01.01.10).
 *
 * **Cerrado y pendiente de que el cliente lo dé por bueno no es cerrado.** Es
 * la mitad que casi nunca se publica, y la que hace que un informe de cierres
 * diga lo que no es. Y las reaperturas van con el cierre: un caso cerrado tres
 * veces no es un caso resuelto.
 */
function ComoAcabo({ cierre, casoId }: { cierre: Cierre; casoId: string }) {
  const { t } = useTranslation();
  if (!cierre?.motivo && !cierre?.cerrado_at && !cierre?.reaperturas) {
    return (
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("caso.cierre")}</h2>
        <Vacio titulo={t("caso.sinCerrar")} compacto />
      </section>
    );
  }

  const aFaltaDeCliente =
    cierre.validacion_cliente != null &&
    cierre.validacion_cliente !== "aceptado";

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("caso.cierre")}</h2>
      {aFaltaDeCliente ? (
        <p className="mb-2 text-dato text-warning">
          {t("caso.pendienteDelCliente", { estado: cierre.validacion_cliente })}
        </p>
      ) : null}
      {cierre.validacion_cliente === "aceptado" ? (
        <p className="mb-2 text-dato text-success">
          {t("caso.aceptadoPorCliente")}
        </p>
      ) : null}
      {/* Reabierto: el motivo que queda es el del cierre ANTERIOR, y así se
          dice. Sin el rótulo, un caso en curso salía «Cómo acabó: Duplicado». */}
      {cierre.motivo && !cierre.cerrado_at ? (
        <p className="text-rotulo text-ink-faint">{t("caso.ultimoCierre")}</p>
      ) : null}
      {cierre.motivo ? (
        <span className="chip-dato">{rotuloDeOpcion(cierre.motivo)}</span>
      ) : null}
      {cierre.resolucion ? (
        <p className="mt-1 text-dato text-ink-muted">{cierre.resolucion}</p>
      ) : null}
      {cierre.reaperturas > 0 ? (
        <p className="mt-2 text-dato text-danger">
          {t("caso.reaperturas", { cuantas: cierre.reaperturas })}
        </p>
      ) : null}
      <EscribirloEnConocimiento
        casoId={casoId}
        resolucion={cierre.resolucion}
      />
    </section>
  );
}

/**
 * Escribir el artículo aquí y ahora (CRM-04.03.01.05).
 *
 * **El momento es la capacidad.** Se escribe cuando se resuelve, con el
 * problema fresco y por quien lo resolvió; pedirlo después, en una sesión
 * dedicada, es como no pedirlo — y es por lo que las bases de conocimiento se
 * quedan vacías teniendo el procedimiento escrito en el servidor.
 *
 * El cuerpo viene relleno con la resolución del caso **y se puede cambiar
 * antes de guardar**, que es justo lo que hay que hacer: la resolución lleva
 * casi siempre el nombre del cliente, su configuración y a veces sus
 * credenciales. Por eso el artículo nace en borrador e interno aunque venga
 * de un caso resuelto, y aquí se dice.
 */
function EscribirloEnConocimiento({
  casoId,
  resolucion,
}: {
  casoId: string;
  resolucion: string | null;
}) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const [titulo, setTitulo] = useState("");
  const [cuerpo, setCuerpo] = useState(resolucion ?? "");
  const [creado, setCreado] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");

  async function crear() {
    setGuardando(true);
    setError("");
    try {
      const r = await llamar<{ id: string; clave: string }>(
        `/api/v1/conocimiento/desde-caso/${casoId}`,
        {
          metodo: "POST",
          cuerpo: {
            clave: `caso-${casoId.slice(0, 8)}`,
            titulo,
            cuerpo,
          },
        },
      );
      setCreado(r.datos.clave);
      setAbierto(false);
    } catch (fallo) {
      setError(fallo instanceof Error ? fallo.message : String(fallo));
    } finally {
      setGuardando(false);
    }
  }

  if (creado) {
    return (
      <p className="mt-3 text-dato text-ink" role="status">
        {t("caso.articuloCreado", { clave: creado })}
      </p>
    );
  }

  if (!abierto) {
    return (
      <button
        type="button"
        className="btn-link mt-3"
        onClick={() => setAbierto(true)}
      >
        {t("caso.escribirArticulo")}
      </button>
    );
  }

  return (
    <div className="mt-3 flex flex-col gap-2">
      {/* El aviso ANTES del formulario, no después de guardar: lo que hay que
          quitar del texto se quita mientras se escribe. */}
      <p className="text-dato text-warning">{t("caso.avisoResolucion")}</p>
      <input
        className="input-base"
        value={titulo}
        aria-label={t("caso.tituloArticulo")}
        placeholder={t("caso.tituloArticulo")}
        onChange={(e) => setTitulo(e.target.value)}
      />
      <textarea
        className="input-base"
        rows={4}
        value={cuerpo}
        aria-label={t("caso.cuerpoArticulo")}
        onChange={(e) => setCuerpo(e.target.value)}
      />
      {error ? <p className="text-dato text-danger">{error}</p> : null}
      <div className="flex gap-2">
        <button
          type="button"
          className="btn-secondary"
          disabled={!titulo.trim() || guardando}
          onClick={() => void crear()}
        >
          {guardando ? t("caso.guardando") : t("caso.guardarArticulo")}
        </button>
        <button
          type="button"
          className="btn-link"
          onClick={() => setAbierto(false)}
        >
          {t("caso.cancelar")}
        </button>
      </div>
    </div>
  );
}

/**
 * Derivar el caso a otra cola: segundo o tercer nivel, ingeniería, o una cola
 * interna (CRM-04.01.01.08).
 *
 * El motivo es obligatorio —sin él quien lo recibe tiene que leerse el caso
 * entero para saber qué se espera— y el caso sigue siendo del cliente: no se
 * crea otro ni se reinicia el reloj. «Interno» lo marca para que no se le
 * enseñe al cliente.
 */
function DerivarCaso({
  casoId,
  equipo,
  alTerminar,
  alCancelar,
}: {
  casoId: string;
  equipo: string | null;
  alTerminar: () => void;
  alCancelar: () => void;
}) {
  const { t } = useTranslation();
  const [colas, setColas] = useState<
    { clave: string; nombre: string; nivel: number }[] | null
  >(null);
  const [cola, setCola] = useState("");
  const [motivo, setMotivo] = useState("");
  const [interno, setInterno] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    void listar<{ clave: string; nombre: string; nivel: number }>(
      "/api/v1/colas?limite=200",
    )
      .then((filas) => setColas(filas.filter((c) => c.clave !== equipo)))
      .catch((e) => {
        setColas([]);
        setFallo(e);
      });
  }, [equipo]);

  async function derivar() {
    setEnviando(true);
    setFallo(null);
    try {
      await llamar(`/api/v1/escalado/derivar/${casoId}`, {
        metodo: "POST",
        cuerpo: { cola_destino: cola, motivo: motivo.trim(), interno },
      });
      alTerminar();
    } catch (e) {
      setFallo(e);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="card mb-4 p-4" aria-label={t("caso.derivar.titulo")}>
      <h2 className="section-label mb-2">{t("caso.derivar.titulo")}</h2>
      <p className="mb-3 text-dato text-ink-muted">
        {t("caso.derivar.explicacion")}
      </p>
      {colas !== null && colas.length === 0 && !fallo ? (
        <p className="mb-3 text-dato text-warning" role="status">
          {t("caso.derivar.sinColas")}
        </p>
      ) : null}
      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("caso.derivar.cola")}
          <select
            className="input-base"
            value={cola}
            onChange={(e) => setCola(e.target.value)}
          >
            <option value="">{t("caso.derivar.elige")}</option>
            {(colas ?? []).map((c) => (
              <option key={c.clave} value={c.clave}>
                {t("caso.derivar.opcion", { nombre: c.nombre, nivel: c.nivel })}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 self-end text-dato text-ink">
          <input
            type="checkbox"
            checked={interno}
            onChange={(e) => setInterno(e.target.checked)}
          />
          {t("caso.derivar.interno")}
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
          {t("caso.derivar.motivo")}
          <textarea
            className="input-base"
            rows={3}
            value={motivo}
            placeholder={t("caso.derivar.motivoAyuda")}
            onChange={(e) => setMotivo(e.target.value)}
          />
        </label>
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={!cola || !motivo.trim() || enviando}
          onClick={() => void derivar()}
        >
          {enviando ? t("caso.derivar.enviando") : t("caso.derivar.confirmar")}
        </button>
        <button type="button" className="btn-secondary" onClick={alCancelar}>
          {t("caso.cancelar")}
        </button>
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}

/**
 * Lo que le ha pasado, en orden (CRM-04.01.01.10).
 *
 * Es la trazabilidad de la reapertura y de todo lo demás: se escribía desde el
 * primer día y la ficha genérica la pintaba como un campo más.
 */
function ElHistorial({
  eventos,
}: {
  eventos: { tipo: string; detalle: Record<string, unknown>; at: string }[];
}) {
  const { t } = useTranslation();
  const todos = eventos ?? [];

  return (
    <section className="card mt-4 p-4">
      <h2 className="section-label mb-1">{t("caso.historial")}</h2>
      {todos.length === 0 ? (
        <Vacio titulo={t("caso.sinHistorial")} compacto />
      ) : (
        <ol className="lista-acotada divide-y divide-ink-dim/30 pr-1">
          {todos.map((e, i) => (
            <li
              key={`${e.tipo}-${e.at}-${i}`}
              className="flex flex-wrap items-baseline gap-x-3 py-1.5"
            >
              <span className="text-dato font-medium text-ink">{e.tipo}</span>
              <time className="text-rotulo text-ink-faint" dateTime={e.at}>
                {e.at.slice(0, 16).replace("T", " ")}
              </time>
              {Object.entries(e.detalle ?? {}).map(([k, v]) => (
                <span key={k} className="text-rotulo text-ink-muted">
                  {k}: {String(v)}
                </span>
              ))}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/**
 * Por qué acabó en esta cola (CRM-04.01.01.06).
 *
 * «¿Por qué me ha llegado esto a mí?» es la pregunta que más se repite en un
 * reparto automático, y sin respuesta la gente deja de fiarse del reparto y
 * empieza a cogerlo todo a mano — que es exactamente lo que el reparto existe
 * para evitar.
 *
 * **Y cuántas reglas se miraron antes.** Sin ese número, «ninguna coincidió y
 * cayó a la cola por defecto» y «coincidió la primera» se cuentan igual, y son
 * cosas opuestas: una dice que el reparto funcionó y la otra que no hay reglas
 * que cubran este caso.
 */
function PorQueEstaAqui({
  asignaciones,
}: {
  asignaciones: Asignacion[] | null;
}) {
  const { t } = useTranslation();
  if (!asignaciones) return null;
  // `Array.isArray` y no `?? []`: esta ruta devuelve una LISTA, y un doble —o
  // un error devuelto como objeto— la haría `.map` de algo que no lo es y
  // tumbaría la ficha entera. Es el mismo fallo que ya costó diez pruebas
  // rojas en la ficha de cliente, cometido otra vez: asumir la forma de lo
  // que llega. Un campo con otra forma no puede ser una pantalla en blanco.
  const cuales = Array.isArray(asignaciones) ? asignaciones : [];

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("caso.porQueAqui")}</h2>
      {cuales.length === 0 ? (
        <Vacio titulo={t("caso.sinAsignacion")} compacto />
      ) : (
        <ol className="divide-y divide-ink-dim/30">
          {cuales.map((a, i) => (
            <li key={`${a.at}-${i}`} className="py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-3 text-dato">
                <span className="font-medium text-ink">{a.cola ?? "—"}</span>
                {a.regla ? <span className="chip-dato">{a.regla}</span> : null}
                {a.estrategia ? (
                  <span className="text-rotulo text-ink-faint">
                    {a.estrategia}
                  </span>
                ) : null}
                <time className="text-rotulo text-ink-faint" dateTime={a.at}>
                  {a.at.slice(0, 16).replace("T", " ")}
                </time>
              </div>
              {a.motivo ? (
                <p className="text-rotulo text-ink-muted">{a.motivo}</p>
              ) : null}
              {typeof a.evaluadas === "number" ? (
                <p className="text-rotulo text-ink-faint">
                  {t("caso.reglasMiradas", { cuantas: a.evaluadas })}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/**
 * Qué derecho cubre esto y cuánto queda (CRM-04.01.02.06).
 *
 * **Las dos bolsas, aunque sólo una esté limitada.** Enseñar sólo la limitada
 * hace que quien mira no sepa si la otra no se cuenta o es que nadie ha
 * gastado, y son cosas distintas delante de un cliente que pregunta.
 *
 * **Y la caducidad al lado del saldo**: un derecho con doscientas horas libres
 * que vence el viernes es tan inservible como uno agotado, y el saldo solo lo
 * pinta como si estuviera holgado.
 */
function QueDerechoLoCubre({ saldo }: { saldo: Saldo | null }) {
  const { t } = useTranslation();
  if (!saldo) return null;

  const agotado = saldo.horas?.agotado || saldo.casos?.agotado;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("caso.derecho")}</h2>
      <p className="text-dato font-medium text-ink">{saldo.entitlement}</p>
      <ul className="mt-2 space-y-1 text-dato">
        <li className={saldo.horas?.agotado ? "text-danger" : "text-ink-muted"}>
          {saldo.horas?.sin_limite
            ? t("caso.horasSinLimite", { consumidas: saldo.horas?.consumidas })
            : t("caso.horasRestantes", {
                restantes: saldo.horas?.restantes,
                incluidas: saldo.horas?.incluidas,
              })}
        </li>
        <li className={saldo.casos?.agotado ? "text-danger" : "text-ink-muted"}>
          {saldo.casos?.sin_limite
            ? t("caso.casosSinLimite", { consumidos: saldo.casos?.consumidos })
            : t("caso.casosRestantes", {
                restantes: saldo.casos?.restantes,
                incluidos: saldo.casos?.incluidos,
              })}
        </li>
      </ul>
      {saldo.vigente_hasta ? (
        <p className="mt-2 text-rotulo text-ink-faint">
          {/* Las tres fechas de esta pantalla salían en crudo:
              «vence 2026-10-28T14:38:22.843025+01:00». Un sello de tiempo de
              la API no es una fecha para nadie. */}
          {t("caso.vigenteHasta", { cuando: fecha(saldo.vigente_hasta) })}
        </p>
      ) : null}
      {agotado && saldo.al_agotar ? (
        <p className="mt-1 text-rotulo text-danger">
          {t("caso.alAgotar", { que: saldo.al_agotar })}
        </p>
      ) : null}
    </section>
  );
}
