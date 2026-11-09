/**
 * La ficha de una oportunidad, con lo que hace falta para cerrarla
 * (CRM-03.01.01.05, CRM-03.01.01.06, CRM-03.01.01.08, CRM-03.01.01.10,
 * CRM-03.01.01.11, CRM-03.01.01.13, CRM-03.01.02.02, CRM-03.01.02.03,
 * CRM-03.01.02.05).
 *
 * Lo que había era la ficha genérica: un volcado de campos. Con eso delante no
 * se contesta «¿cómo vamos con esta venta?», que es para lo que se abre.
 *
 * Mismo reparto que la ficha de cliente, a propósito: arriba lo que identifica
 * y el estado, a la izquierda el dinero, a la derecha quién decide y de dónde
 * viene. Dos pantallas que enseñan el mismo tipo de cosa lo colocan igual, o
 * hay que volver a aprenderlas al cambiar de una a otra.
 *
 * **Tres de estos paneles enseñan cosas que se guardaban y no leía nadie.** El
 * reparto entre comerciales y las oportunidades relacionadas vivían en su
 * tabla, consultadas sólo por su propio escritor para reemplazar filas: se
 * podía declarar quién se lleva qué parte de una comisión y no había forma de
 * comprobarlo hasta que llegaba la liquidación.
 *
 * **Tres paneles más, del mismo registro y por eso aquí.** La metodología dice
 * qué falta para poder cerrar y cuál es el siguiente paso —una puntuación sin
 * el «lo que falta» al lado es una nota, no una guía—; el playbook dice qué
 * hacer en ESTA etapa, que es lo que convierte la metodología en trabajo; y el
 * plan conjunto con el cliente separa **lo retrasado nuestro de lo retrasado
 * suyo**, que es la única distinción que cambia a quién se llama.
 *
 * **Y el ARR no se calcula aquí.** Las líneas se mandan al servicio que sabe
 * qué cuenta como recurrente y qué no, y lo que vuelve se pinta. Calcularlo en
 * la pantalla dividiendo el total entre los años mete la implantación dentro y
 * la métrica con la que se valora la empresa sale inflada — y entonces hay dos
 * sitios donde se calcula, que acaban diciendo cosas distintas.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import {
  BotonesDeRegistro,
  ConfirmarBorrado,
  FormularioDeEdicion,
  useEdicion,
} from "@/componentes/Edicion";
import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { DatosClave } from "@/componentes/DatosClave";
import { DetallesDelRegistro } from "@/componentes/DetallesDelRegistro";
import { PestanasDeFicha } from "@/componentes/PestanasDeFicha";
import { filas, llamar, salvoCancelacion } from "@/lib/api";
import { Acciones, esIrreversible } from "@/componentes/Acciones";
import { AsistenteIA, esDeIA } from "@/componentes/AsistenteIA";
import { ConsejosDeLecciones } from "@/componentes/ConsejosDeLecciones";
import { PrediccionDelRegistro } from "@/componentes/PrediccionDelRegistro";
import { accionesDe, type Accion } from "@/lib/acciones";
import { useSuperficie } from "@/lib/permisos";
import { listar } from "@/lib/listados";
import {
  escalar,
  fecha,
  humanizar,
  importe as comoImporte,
} from "@/lib/formato";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";
import { cn } from "@/lib/utiles";

interface Oportunidad {
  id: string;
  codigo: string | null;
  nombre: string;
  cuenta_id: string | null;
  pipeline: string | null;
  pipeline_id: string | null;
  etapa: string | null;
  importe: string;
  moneda: string;
  probabilidad: number;
  importe_ponderado: string;
  fecha_cierre: string | null;
  estado: string;
  /** Qué significa el estado —abierto, ganado, perdido…—, lo dice el servidor. */
  estado_significa?: string | null;
  categoria_forecast: string | null;
  etapa_desde: string | null;
  bloqueada: boolean;
}

/** Un pipeline con sus etapas en orden, tal y como lo publica `sales`. */
interface Pipeline {
  id: string;
  // Con el identificador: mover la oportunidad se hace con el id de la etapa,
  // no con su nombre. Declarar sólo el nombre dejaba la ruta inútil.
  etapas: { id: string; nombre: string }[];
}

interface Linea {
  id: string;
  descripcion: string;
  cantidad: string;
  precio_unitario: string;
  descuento_pct: string;
  total: string;
  /** `tipo_ingreso` en el servidor. Se llamaba `tipo` aquí y nadie lo mandaba. */
  tipo_ingreso?: string;
}

/** A qué margen sale, calculado por el servidor con las líneas guardadas. */
interface MargenDeLineas {
  completo: boolean;
  lineas_sin_coste: string[];
  lineas_en_perdidas: { referencia: string }[];
  margen_pct: string;
  necesita_aprobacion: boolean;
  porque: string;
  aviso_lineas_en_perdidas: string;
}

interface Metricas {
  arr: string;
  mrr: string;
  tcv: string;
  acv: string;
  puntual: string;
  hay_recurrente: boolean;
  porque: string;
  lo_que_no_cuenta_como_arr: string[];
}

interface Reparto {
  reparto: {
    usuario_id: string;
    papel: string;
    porcentaje: string;
    motivo: string;
  }[];
  credito_total: string;
  credito_cuadra: boolean;
  porque_el_overlay_no_suma: string;
  relacionadas: { tipo: string; sentido: string; otra_id: string }[];
}

interface GrupoDeCompra {
  roles: Record<
    string,
    { contacto_id: string; postura: number; motivo: string; hablado: boolean }[]
  >;
  faltan_por_identificar: string[];
  clave_sin_hablar: string[];
  en_contra: number;
  completo: boolean;
  que_mirar: string;
}

/** Un criterio de la metodología que todavía no está cubierto. */
interface CriterioQueFalta {
  clave: string;
  etiqueta: string;
  peso: number;
}

interface Evaluacion {
  /** Todos los criterios, cubiertos y no: se marcan desde la ficha. */
  detalle?: {
    clave: string;
    etiqueta: string;
    peso: number;
    cubierto: boolean;
    nota: string;
  }[];
  metodologia?: { id: string; nombre: string } | null;
  puntuacion: number;
  criterios: number;
  cubiertos: number;
  /**
   * Una puntuación sin esto al lado es una nota, no una guía.
   *
   * **Estaba declarado `string[]` y el servidor manda objetos.** Pintarlos
   * reventaba la ficha entera —«Objects are not valid as a React child»— y,
   * como el error de pantalla decía «No se ha podido contactar con el
   * servidor», la ficha de cualquier oportunidad con metodología activa era
   * una caja roja que mandaba a mirar la red. El servidor contestaba 200.
   *
   * No lo cazó ningún gate porque esta operación **no declara esquema de
   * respuesta** en el contrato: devuelve un diccionario suelto, así que el
   * front se inventó el tipo y TypeScript lo creyó.
   */
  lo_que_falta: CriterioQueFalta[];
  siguiente_paso: string;
  cualificada: boolean;
}

interface Playbook {
  clave: string;
  titulo: string;
  pasos: string[];
  por_que: string;
}

interface Plan {
  id: string;
  oportunidad_id: string;
  fecha_objetivo: string | null;
}

interface EstadoDelPlan {
  pasos: number;
  hechos: number;
  /** Las tres por separado: es lo único que cambia a quién se llama. */
  retrasados_nuestros: unknown[];
  retrasados_del_cliente: unknown[];
  retrasados_conjuntos: unknown[];
  compartido: boolean;
  visto_por_el_cliente: string | null;
  la_fecha_es_creible: boolean;
  que_significa: string;
  aviso: string;
}

interface CambioDePrevision {
  campo: string;
  anterior: string | null;
  nuevo: string | null;
  dias_deslizados: number | null;
  delta_importe: string | null;
  motivo: string | null;
  at: string;
}

export function Oportunidad() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [op, setOp] = useState<Oportunidad | null>(null);
  const [lineas, setLineas] = useState<Linea[]>([]);
  const [metricas, setMetricas] = useState<Metricas | null>(null);
  const [margen, setMargen] = useState<MargenDeLineas | null>(null);
  const [reparto, setReparto] = useState<Reparto | null>(null);
  const [grupo, setGrupo] = useState<GrupoDeCompra | null>(null);
  const [deslizamientos, setDeslizamientos] = useState<CambioDePrevision[]>([]);
  const [evaluacion, setEvaluacion] = useState<Evaluacion | null>(null);
  const [playbook, setPlaybook] = useState<Playbook | null>(null);
  const [plan, setPlan] = useState<EstadoDelPlan | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  // Se puede llegar YA en edición, con `?editar=1`. Lo usa el menú de la fila
  // en el listado: en Lightning cada fila lleva un `⌄` con «Editar», y sin
  // esto ese «Editar» sólo podía abrir la ficha y dejar a quien lo pulsó a un
  // clic más de lo que pidió.
  const [parametrosDeFicha] = useSearchParams();
  const [editando, setEditando] = useState(
    parametrosDeFicha.get("editar") === "1",
  );
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const navegar = useNavigate();
  /**
   * El mismo recurso que el listado, y no una ruta escrita a mano.
   *
   * Dos pantallas que enseñan el mismo registro tienen que escribirlo igual,
   * o una de las dos se queda atrás el día que cambie el contrato.
   */
  const modulo = moduloDe("oportunidades");
  const recurso = modulo ? recursoDe(modulo, "oportunidad") : undefined;
  const { ruta, puedeEditar, puedeBorrar, borrado } = useEdicion(recurso, id);
  // Las acciones del contrato sobre la oportunidad —entre ellas «Qué hacer ahora», con IA— en el menú, igual que en la ficha del cliente. Mover de etapa no: tiene su control arriba.
  const { superficie, tiene } = useSuperficie();
  const [accionAbierta, setAccionAbierta] = useState<Accion | null>(null);
  const acciones = accionesDe(
    superficie,
    "/api/v1/opportunities",
    id ?? "",
    tiene,
  ).filter(
    (a) =>
      !["/api/v1/opportunities/{oportunidad_id}/etapa"].includes(a.plantilla),
  );
  // Las mismas dos pestañas que las demás fichas. «Relacionado» es lo que
  // esta pantalla ya enseñaba —las líneas, quién decide, el plan— y
  // «Detalles» son sus campos, que hasta hoy sólo se leían entrando a editar.
  const [pestana, setPestana] = useState<"relacionado" | "detalles">(
    "relacionado",
  );

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Oportunidad>(`/api/v1/opportunities/${id}`, {
      signal: control.signal,
    })
      .then((r) => setOp(r.datos))
      .catch(salvoCancelacion(setFallo));

    // Cada panel con su propio fallo: que no responda el histórico de
    // previsión no puede dejar sin ver las líneas, que es a lo que se entra.
    listar<Linea>(`/api/v1/opportunities/${id}/lineas`, {
      signal: control.signal,
    })
      .then((suyas) => {
        setLineas(suyas);
        // Las métricas las calcula el servicio que sabe qué es recurrente, con
        // las líneas de verdad. Sin líneas no se pregunta: contestaría ceros y
        // un ARR de cero se lee como «no factura», no como «no hay líneas».
        if (suyas.length > 0) {
          // El margen, del servidor y con el mínimo del tenant: calcularlo aquí
          // sería lógica de negocio en el front (CRM-09.02.01.02).
          void llamar<MargenDeLineas>(`/api/v1/opportunities/${id}/margen`, {
            signal: control.signal,
          })
            .then((m) => setMargen(m.datos))
            .catch(() => undefined);
          void llamar<Metricas>("/api/v1/ingresos/metricas", {
            metodo: "POST",
            cuerpo: { lineas: suyas },
            signal: control.signal,
          })
            .then((m) => setMetricas(m.datos))
            .catch(() => undefined);
        }
      })
      .catch(() => undefined);

    void llamar<Reparto>(`/api/v1/ingresos/de/${id}`, {
      signal: control.signal,
    })
      .then((r) => setReparto(r.datos))
      .catch(() => undefined);
    void llamar<GrupoDeCompra>(`/api/v1/ingresos/grupo-compra/${id}`, {
      signal: control.signal,
    })
      .then((r) => setGrupo(r.datos))
      .catch(() => undefined);
    void llamar<CambioDePrevision[]>(
      `/api/v1/forecast/oportunidades/${id}/historial-prevision`,
      { signal: control.signal },
    )
      .then((r) => setDeslizamientos(r.datos))
      .catch(() => undefined);

    // La metodología de SU embudo —o la general—, con todos sus criterios.
    // Antes se cogía la primera activa, fuera del embudo que fuera.
    void llamar<
      Evaluacion & { metodologia: { id: string; nombre: string } | null }
    >(`/api/v1/opportunities/${id}/metodologia`, { signal: control.signal })
      .then((r) => setEvaluacion(r.datos?.metodologia ? r.datos : null))
      .catch(() => undefined);

    // El plan conjunto se busca por su oportunidad: puede no haberlo, y no
    // tenerlo es una respuesta —no se ha acordado nada con el cliente—.
    void listar<Plan>(`/api/v1/planes-conjuntos?oportunidad_id=${id}`, {
      signal: control.signal,
    })
      .then((planes) => {
        const suyo = planes[0];
        if (!suyo) return;
        void llamar<EstadoDelPlan>(
          `/api/v1/planes-conjuntos/${suyo.id}/estado`,
          {
            signal: control.signal,
          },
        )
          .then((r) => setPlan(r.datos))
          .catch(() => undefined);
      })
      .catch(() => undefined);

    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  /**
   * Las etapas de SU pipeline, para pintar la ruta del panel de cabecera.
   *
   * No salen del contrato: la oportunidad no declara `etapa` en su esquema
   * —se cambia por un extremo aparte con el identificador de una etapa— y los
   * pipelines son configuración de cada tenant. Así que se leen de donde de
   * verdad están. **Medido el 02-11-2026**: hasta hoy la ficha de una
   * oportunidad salía sin ruta, con la etapa como un campo suelto, aunque el
   * comentario de aquí al lado decía que la pintaba el panel.
   *
   * Si falla no pasa nada: la ficha se queda como estaba y la etapa sale como
   * un dato clave más. Es un adorno útil, no el contenido.
   */
  const pipelineId = op?.pipeline_id ?? "";
  // Las etapas CON SU IDENTIFICADOR, no sólo el nombre: mover la oportunidad
  // se hace con el id de la etapa del pipeline, que es configuración del
  // tenant. Guardando sólo los nombres, la ruta podía pintarse y no se podía
  // usar para nada.
  const [etapasDelPipeline, setEtapasDelPipeline] = useState<
    { id: string; nombre: string }[]
  >([]);
  useEffect(() => {
    if (!pipelineId) return undefined;
    const control = new AbortController();
    void llamar<Pipeline[]>("/api/v1/pipelines?limite=50", {
      signal: control.signal,
    })
      .then((r) => {
        const suyo = filas<Pipeline>(r.datos).find((x) => x.id === pipelineId);
        setEtapasDelPipeline(
          (suyo?.etapas ?? []).map((e) => ({
            id: String(e.id ?? ""),
            nombre: e.nombre,
          })),
        );
      })
      .catch(() => undefined);
    return () => control.abort();
  }, [pipelineId]);

  // El playbook de SU etapa, y en su propio efecto: uno genérico no es un
  // playbook, es una lista. Va aparte porque depende de la etapa, que llega
  // con la oportunidad — pedirlo dentro de `cargar` obligaría a pedir la
  // oportunidad dos veces.
  const etapa = op?.etapa ?? "";
  useEffect(() => {
    if (!etapa) return undefined;
    const control = new AbortController();
    void llamar<Playbook>(
      `/api/v1/metodologias/playbook?etapa=${encodeURIComponent(etapa)}`,
      { signal: control.signal },
    )
      .then((r) => setPlaybook(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, [etapa]);

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/m/oportunidades");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !op) return <Fallo error={fallo} reintentar={cargar} />;
  if (!op) return <Cargando />;

  return (
    <>
      {/* El mismo panel que las demás fichas, y aquí con **la ruta de
          etapas**, que es lo que de verdad se mira en una oportunidad: una
          etapa suelta dice dónde estás; la ruta dice además cuánto queda y qué
          viene después. Los pasos se los da esta pantalla porque los suyos no
          están en el contrato sino en el pipeline del tenant. */}
      <DatosClave
        recurso={recurso}
        tipo="oportunidad"
        nombre={op.nombre}
        fila={op as unknown as Record<string, unknown>}
        volverA={{ a: "/m/oportunidades", titulo: modulo?.titulo ?? "", id }}
        cambioDeEstado={{ servicio: "sales", ruta, alCambiar: () => cargar() }}
        recorrido={{
          campo: "etapa",
          pasos: etapasDelPipeline.map((e) => e.nombre),
          // Y SE PUEDE MOVER DESDE AHÍ.
          //
          // Lo pidió quien lo usa: «clicando en alguno de estos deberíamos
          // poder movernos». Mover de etapa es el gesto más repetido del día
          // en una oportunidad, y tenerlo sólo dentro del formulario de
          // edición lo convierte en cuatro clics.
          //
          // Si el producto lo rechaza —criterios de salida sin cumplir, una
          // etapa cerrada— el mensaje sale donde salen los demás de esta
          // ficha, no se traga.
          alElegir: async (paso: string) => {
            const destino = etapasDelPipeline.find((e) => e.nombre === paso);
            if (!destino?.id || !id) return;
            try {
              await llamar(`/api/v1/opportunities/${id}/etapa`, {
                metodo: "POST",
                cuerpo: { etapa_id: destino.id },
              });
              setFallo(null);
              await cargar();
            } catch (error) {
              setFallo(error);
            }
          },
        }}
        distintivos={
          <>
            {/* El estado no: es una de las columnas preferidas del recurso y
                sale como dato clave ahí debajo. Estaba en los dos sitios. */}
            {/* El código lleva `font-mono` explícito: SÍ es un identificador
                —«OPP-2026-00314»— y se lee carácter a carácter. La clase
                `.badge` dejó de forzarla el 03-11-2026 porque la llevaba
                también sobre palabras corrientes. */}
            {op.codigo ? (
              <span className="badge badge-muted font-mono">{op.codigo}</span>
            ) : null}
            {op.categoria_forecast ? (
              <span className="chip-dato">{op.categoria_forecast}</span>
            ) : null}
            {op.bloqueada ? (
              <span className="chip-dato chip-dato--no">
                {t("oportunidad.bloqueada")}
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
              extra={acciones
                .filter((a) => !esDeIA(a))
                .map((a) => ({
                  clave: a.ruta,
                  nombre: a.nombre,
                  alElegir: () => setAccionAbierta(a),
                  destructiva: esIrreversible(a),
                }))}
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

      {/* Por lo que SIGNIFICA el estado, no por cómo se llama: la empresa
          puede llamar «Adjudicada» a la ganada o tener sus propios estados. */}
      {op &&
      (op.estado_significa === "perdido" ||
        op.estado_significa === "ganado") ? (
        <PorQueSeCerro id={op.id} estado={op.estado_significa} />
      ) : (
        // Abierta: lo que las lecciones de otras ventas tienen que decirle.
        <ConsejosDeLecciones id={op.id} />
      )}

      {/* Lo que dice el modelo entrenado con el histórico: probabilidad,
          importe y fecha real, con sus porqués (CRM-05.02.01.02). */}
      {op &&
      op.estado_significa !== "perdido" &&
      op.estado_significa !== "ganado" ? (
        <PrediccionDelRegistro objeto="oportunidad" id={op.id} />
      ) : null}

      <AsistenteIA
        acciones={acciones}

        abierta={accionAbierta}

        alElegir={setAccionAbierta}
      />

      <Acciones
        acciones={acciones}

        servicio="sales"

        abierta={accionAbierta}

        alCambiarAbierta={setAccionAbierta}

        alTerminar={() => cargar()}
      />

      {editando && recurso ? (
        <FormularioDeEdicion
          recurso={recurso}
          ruta={ruta}
          valores={op as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      {/* Sólo el ponderado: el importe a secas ya está arriba, como dato
          clave y con su moneda. Esta tarjeta lo repetía al lado. */}
      <section className="card mb-4 p-4">
        <p className="text-titulo font-medium text-ink">
          {t("oportunidad.ponderado", {
            valor: comoImporte(op.importe_ponderado, op.moneda),
            pct: op.probabilidad,
          })}
        </p>
        {/* La fecha de cierre estaba aquí también, y en crudo: el panel de
            arriba decía «21/04/2027» y esta línea «2027-04-21», el mismo dato
            dos veces y con dos formatos en la misma pantalla. La pregunta la
            contesta el panel; aquí sobraba. */}
      </section>

      {!editando ? (
        <PestanasDeFicha
          tipo="oportunidad"
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
          <div className="grid gap-4 lg:grid-cols-2">
            <LasLineas
              lineas={lineas}
              metricas={metricas}
              margen={margen}
              moneda={op.moneda}
            />
            <QuienDecide grupo={grupo} />
            <QuienSeLoLleva reparto={reparto} />
            <LoQueSeHaMovido cambios={deslizamientos} />
            <QueFaltaParaCerrar
              evaluacion={evaluacion}
              playbook={playbook}
              alMarcar={async (clave, cubierto) => {
                if (!evaluacion?.metodologia) return;
                const r = await llamar<Evaluacion>(
                  `/api/v1/metodologias/${evaluacion.metodologia.id}/oportunidad/${id}`,
                  {
                    metodo: "PUT",
                    cuerpo: { respuestas: { [clave]: { cubierto } } },
                  },
                );
                setEvaluacion({
                  ...r.datos,
                  metodologia: evaluacion.metodologia,
                });
              }}
            />
            <ElPlanConElCliente plan={plan} />
          </div>
        ) : (
          <DetallesDelRegistro
            ruta={ruta}
            objeto="oportunidad"
            servicio={recurso?.servicio ?? ""}
            id={id}
          />
        )}
      </div>
    </>
  );
}

/**
 * Las líneas y lo que se puede decir de ellas (CRM-03.01.01.05, .01.06).
 *
 * El ARR va **con su porqué y con lo que ha dejado fuera**: «ARR 120.000» sin
 * decir que la implantación no cuenta es el número que acaba en una valoración
 * y nadie vuelve a mirar cómo se calculó.
 */
function LasLineas({
  lineas,
  metricas,
  margen,
  moneda,
}: {
  lineas: Linea[];
  metricas: Metricas | null;
  margen: MargenDeLineas | null;
  moneda: string;
}) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.lineas")}</h2>
      {lineas.length === 0 ? (
        <Vacio titulo={t("oportunidad.sinLineas")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {lineas.map((l) => (
            <li
              key={l.id}
              className="flex flex-wrap items-baseline gap-x-3 py-1.5"
            >
              <span className="text-dato font-medium text-ink">
                {l.descripcion}
              </span>
              <span className="text-rotulo text-ink-faint">
                {t("oportunidad.porUnidad", {
                  cantidad: l.cantidad,
                  precio: comoImporte(l.precio_unitario, moneda),
                })}
              </span>
              {Number(l.descuento_pct) > 0 ? (
                <span className="chip-dato">-{l.descuento_pct} %</span>
              ) : null}
              <span className="text-dato text-ink-muted">
                {comoImporte(l.total, moneda)}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* El margen, con lo que no se sabe dicho: las líneas sin coste no
          cuentan como cero, y una línea que pierde dinero se nombra aunque el
          total salga sano. */}
      {margen ? (
        <div
          className="mt-3 border-t border-ink-dim/30 pt-2"
          data-testid="margen-oportunidad"
        >
          <p className="text-dato text-ink">
            {margen.lineas_sin_coste.length === lineas.length
              ? t("oportunidad.margenSinCoste")
              : t("oportunidad.margen", { pct: escalar(margen.margen_pct) })}
          </p>
          {margen.lineas_sin_coste.length &&
          margen.lineas_sin_coste.length < lineas.length ? (
            <p className="text-rotulo text-ink-faint">
              {t("oportunidad.margenIncompleto", {
                cuales: margen.lineas_sin_coste.join(", "),
              })}
            </p>
          ) : null}
          {margen.aviso_lineas_en_perdidas ? (
            <p className="text-rotulo text-danger">
              {margen.aviso_lineas_en_perdidas}
            </p>
          ) : null}
          {margen.necesita_aprobacion ? (
            <p className="text-rotulo text-warning">{margen.porque}</p>
          ) : null}
        </div>
      ) : null}

      {metricas ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-2">
          <h3 className="text-dato font-medium text-ink">
            {t("oportunidad.metricas")}
          </h3>
          <ul className="mt-1 flex flex-wrap gap-2 text-rotulo">
            <li className="chip-dato">
              ARR {comoImporte(metricas.arr, moneda)}
            </li>
            <li className="chip-dato">
              MRR {comoImporte(metricas.mrr, moneda)}
            </li>
            <li className="chip-dato">
              TCV {comoImporte(metricas.tcv, moneda)}
            </li>
            <li className="chip-dato">
              ACV {comoImporte(metricas.acv, moneda)}
            </li>
          </ul>
          {/* Lo que NO cuenta como ARR, dicho. Sin esto, el número se cita en
              un comité como si fuera todo lo que entra. */}
          {metricas.lo_que_no_cuenta_como_arr.length > 0 ? (
            <p className="mt-1 text-rotulo text-ink-muted">
              {t("oportunidad.noCuentaComoArr", {
                tipos: metricas.lo_que_no_cuenta_como_arr.join(", "),
                puntual: comoImporte(metricas.puntual, moneda),
              })}
            </p>
          ) : null}
          <p className="mt-1 text-rotulo text-ink-faint">{metricas.porque}</p>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Quién decide, y a quién no se ha visto (CRM-03.01.01.10).
 *
 * Lo útil no es la lista: es **lo que falta**. Una oportunidad sin decisor
 * identificado no está avanzada por mucho que el presupuesto esté mandado, y
 * un económico con el que nadie ha hablado es la razón más habitual de que un
 * cierre «seguro» se caiga la última semana.
 */
function QuienDecide({ grupo }: { grupo: GrupoDeCompra | null }) {
  const { t } = useTranslation();
  if (!grupo) return null;
  const roles = Object.entries(grupo.roles);

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.quienDecide")}</h2>
      {roles.length === 0 ? (
        <Vacio titulo={t("oportunidad.sinRoles")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {roles.map(([rol, gente]) => (
            <li
              key={rol}
              className="flex flex-wrap items-baseline gap-x-3 py-1.5"
            >
              <span className="text-dato font-medium text-ink">{rol}</span>
              {gente.map((p) => (
                <span
                  key={p.contacto_id}
                  className={
                    p.hablado
                      ? "chip-dato chip-dato--si"
                      : "chip-dato chip-dato--no"
                  }
                >
                  {p.hablado
                    ? t("oportunidad.hablado")
                    : t("oportunidad.sinHablar")}
                  {p.postura < 0 ? ` · ${t("oportunidad.enContra")}` : ""}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
      {/* Lo que falta, en ámbar: es la mitad que hace útil este panel. */}
      <p
        className={
          grupo.completo
            ? "mt-2 text-dato text-success"
            : "mt-2 text-dato text-warning"
        }
      >
        {grupo.que_mirar}
      </p>
    </section>
  );
}

/**
 * Quién se lleva esto, y de dónde viene (CRM-03.01.01.08, CRM-03.01.01.11).
 *
 * Las dos cosas que se guardaban y no leía nadie. El crédito sale **con su
 * total y con si cuadra**: un reparto al 60/60 cuadra hacia arriba y el
 * descuadre lo encuentra finanzas tres meses después.
 */
function QuienSeLoLleva({ reparto }: { reparto: Reparto | null }) {
  const { t } = useTranslation();
  if (!reparto) return null;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.reparto")}</h2>
      {reparto.reparto.length === 0 ? (
        <Vacio titulo={t("oportunidad.sinReparto")} compacto />
      ) : (
        <>
          <ul className="divide-y divide-ink-dim/30">
            {reparto.reparto.map((p) => (
              <li
                key={`${p.usuario_id}-${p.papel}`}
                className="flex flex-wrap items-baseline gap-x-3 py-1.5"
              >
                <span className="text-dato font-medium text-ink">
                  {p.porcentaje} %
                </span>
                <span className="chip-dato">{p.papel}</span>
                {p.motivo ? (
                  <span className="text-rotulo text-ink-faint">{p.motivo}</span>
                ) : null}
              </li>
            ))}
          </ul>
          <p
            className={
              reparto.credito_cuadra
                ? "mt-2 text-dato text-ink-muted"
                : "mt-2 text-dato text-danger"
            }
          >
            {t("oportunidad.creditoTotal", { total: reparto.credito_total })}
            {reparto.credito_cuadra ? "" : ` · ${t("oportunidad.noCuadra")}`}
          </p>
          <p className="mt-1 text-rotulo text-ink-faint">
            {reparto.porque_el_overlay_no_suma}
          </p>
        </>
      )}

      {reparto.relacionadas.length > 0 ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-2">
          <h3 className="text-dato font-medium text-ink">
            {t("oportunidad.relacionadas")}
          </h3>
          <ul className="mt-1 space-y-1">
            {reparto.relacionadas.map((r) => (
              <li
                key={`${r.tipo}-${r.otra_id}`}
                className="text-rotulo text-ink-muted"
              >
                <span className="chip-dato">{r.tipo}</span>{" "}
                {/* El sentido: sin él, «renovación» no dice si ésta es la que
                    se renueva o la que renueva a otra, que en el informe de
                    crecimiento son cosas opuestas. */}
                {t(`oportunidad.sentido.${r.sentido}`)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Lo que se ha movido: importe y fecha (CRM-03.01.01.13).
 *
 * Una oportunidad que ha cambiado tres veces de fecha no es la misma que una
 * que nunca se movió, aunque hoy tengan el mismo importe y la misma etapa. El
 * deslizamiento se anota **con su motivo**, que es lo que convierte un
 * histórico en algo que se puede discutir en un comité.
 */
function LoQueSeHaMovido({ cambios }: { cambios: CambioDePrevision[] }) {
  const { t } = useTranslation();
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.movimientos")}</h2>
      {cambios.length === 0 ? (
        <Vacio titulo={t("oportunidad.sinMovimientos")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {cambios.map((c, i) => (
            <li key={`${c.campo}-${c.at}-${i}`} className="py-1.5">
              <div className="flex flex-wrap items-baseline gap-x-2 text-dato">
                <span className="font-medium text-ink">{c.campo}</span>
                <span className="text-ink-faint">{c.anterior ?? "—"}</span>
                <Icono nombre="arrow_forward" tamano="sm" />
                <span className="text-ink-muted">{c.nuevo ?? "—"}</span>
                {c.dias_deslizados ? (
                  <span className="chip-dato chip-dato--no">
                    {t("oportunidad.deslizada", { dias: c.dias_deslizados })}
                  </span>
                ) : null}
                {c.delta_importe ? (
                  <span className="chip-dato">{c.delta_importe}</span>
                ) : null}
              </div>
              {c.motivo ? (
                <p className="text-rotulo text-ink-faint">{c.motivo}</p>
              ) : (
                /* Un movimiento sin motivo es el que no se puede discutir.
                   Decirlo es lo que hace que la próxima vez se escriba. */
                <p className="text-rotulo text-warning">
                  {t("oportunidad.sinMotivo")}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Qué falta para poder cerrar, y qué hacer ahora
 * (CRM-03.01.02.02, CRM-03.01.02.03).
 *
 * **La puntuación va con «lo que falta» al lado, nunca sola.** Un «62 sobre
 * 100» es una nota: no dice qué hacer, así que no cambia nada. La lista de
 * criterios sin cubrir sí, y es lo que convierte la metodología en trabajo.
 *
 * Y el playbook es el de ESTA etapa. Uno genérico no es un playbook, es una
 * lista de buenas intenciones; por eso el servidor devuelve también **por qué**
 * eligió ése, que es lo único que hace que alguien se fíe del siguiente.
 */
function QueFaltaParaCerrar({
  evaluacion,
  playbook,
  alMarcar,
}: {
  evaluacion: Evaluacion | null;
  playbook: Playbook | null;
  alMarcar: (clave: string, cubierto: boolean) => Promise<void>;
}) {
  const { t } = useTranslation();
  if (!evaluacion && !playbook) {
    return (
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("oportunidad.queFalta")}</h2>
        <Vacio titulo={t("oportunidad.sinMetodologia")} compacto />
      </section>
    );
  }

  const faltan = evaluacion?.lo_que_falta ?? [];

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.queFalta")}</h2>
      {evaluacion ? (
        <>
          <p className="font-mono text-dato text-ink">
            {t("oportunidad.cubiertos", {
              cubiertos: evaluacion.cubiertos,
              criterios: evaluacion.criterios,
              puntuacion: evaluacion.puntuacion,
            })}
          </p>
          <p
            className={
              evaluacion.cualificada
                ? "mt-1 text-dato text-success"
                : "mt-1 text-dato text-warning"
            }
          >
            {t(
              evaluacion.cualificada
                ? "oportunidad.cualificada"
                : "oportunidad.noCualificada",
            )}
          </p>
          {/* Todos los criterios de su metodología, para marcarlos: lo que se
              sabe de esta venta se apunta aquí mismo. */}
          {evaluacion.detalle?.length ? (
            <ul className="mt-2 divide-y divide-ink-dim/30" role="status">
              {evaluacion.detalle.map((c) => (
                <li
                  key={c.clave}
                  className="flex items-center gap-2 py-1.5 text-dato"
                >
                  <input
                    type="checkbox"
                    checked={c.cubierto}
                    aria-label={c.etiqueta}
                    onChange={(e) => void alMarcar(c.clave, e.target.checked)}
                    className="h-4 w-4 accent-accent"
                  />
                  <span className={c.cubierto ? "text-ink" : "text-ink-muted"}>
                    {c.etiqueta}
                  </span>
                  <span className="ml-auto text-rotulo text-ink-faint">
                    {c.peso}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {/* Lo que falta, enumerado. La nota sola no cambia nada. */}
          {!evaluacion.detalle?.length && faltan.length > 0 ? (
            <ul className="mt-2 flex flex-col gap-1">
              {faltan.map((x) => (
                <li key={x.clave} className="text-dato text-ink">
                  {/* La `etiqueta` que manda el servidor es la clave cruda
                      —«comprador_economico»—, así que se escribe como se lee.
                      Y se prefiere a la clave por si algún día trae el nombre
                      de verdad. */}
                  {humanizar(x.etiqueta || x.clave)}
                </li>
              ))}
            </ul>
          ) : null}
          {evaluacion.siguiente_paso ? (
            <p className="mt-2 text-dato text-ink">
              {t("oportunidad.siguientePaso", {
                paso: humanizar(evaluacion.siguiente_paso),
              })}
            </p>
          ) : null}
        </>
      ) : null}

      {playbook ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-2">
          <p className="text-dato font-medium text-ink">{playbook.titulo}</p>
          {/* El porqué del playbook: uno que aparece sin explicación se
              ignora, y entonces da igual que esté. */}
          <p className="mt-1 text-rotulo text-ink-faint">{playbook.por_que}</p>
          <ul className="mt-1 flex flex-col gap-1">
            {(playbook.pasos ?? []).map((paso, i) => (
              <li key={i} className="text-dato text-ink-muted">
                {paso}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/**
 * El plan conjunto con el cliente (CRM-03.01.02.05).
 *
 * **Lo retrasado nuestro y lo retrasado suyo van por separado**, y es la única
 * distinción de este panel que cambia algo: si vamos tarde nosotros se empuja
 * dentro de casa, y si va tarde el cliente la conversación es con él. Juntos
 * son «el plan va mal», que no se acciona.
 *
 * **Y un plan que el cliente no ha visto no es un plan conjunto**: es una
 * lista nuestra con su nombre encima. Por eso `compartido` y
 * `visto_por_el_cliente` salen delante de los pasos.
 */
function ElPlanConElCliente({ plan }: { plan: EstadoDelPlan | null }) {
  const { t } = useTranslation();
  if (!plan) {
    return (
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("oportunidad.planConjunto")}</h2>
        {/* No tenerlo es una respuesta: no se ha acordado nada con el cliente. */}
        <Vacio titulo={t("oportunidad.sinPlan")} compacto />
      </section>
    );
  }

  const nuestros = plan.retrasados_nuestros ?? [];
  const suyos = plan.retrasados_del_cliente ?? [];
  const conjuntos = plan.retrasados_conjuntos ?? [];

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("oportunidad.planConjunto")}</h2>
      {/* Si el cliente no lo ha visto, lo demás importa menos. */}
      <p
        className={
          plan.compartido
            ? "text-dato text-ink-muted"
            : "text-dato text-warning"
        }
      >
        {plan.compartido
          ? plan.visto_por_el_cliente
            ? t("oportunidad.planVisto", {
                fecha: fecha(plan.visto_por_el_cliente),
              })
            : t("oportunidad.planCompartidoSinVer")
          : t("oportunidad.planSinCompartir")}
      </p>
      <p className="mt-2 font-mono text-dato text-ink">
        {t("oportunidad.pasosDelPlan", {
          hechos: plan.hechos,
          pasos: plan.pasos,
        })}
      </p>
      {/* Los tres retrasos por separado. */}
      {nuestros.length > 0 ? (
        <p className="mt-1 text-dato text-danger">
          {t("oportunidad.retrasoNuestro", { cuantos: nuestros.length })}
        </p>
      ) : null}
      {suyos.length > 0 ? (
        <p className="mt-1 text-dato text-warning">
          {t("oportunidad.retrasoDelCliente", { cuantos: suyos.length })}
        </p>
      ) : null}
      {conjuntos.length > 0 ? (
        <p className="mt-1 text-dato text-warning">
          {t("oportunidad.retrasoConjunto", { cuantos: conjuntos.length })}
        </p>
      ) : null}
      {/* Y si la fecha de cierre ya no se la cree ni el plan, se dice. */}
      {!plan.la_fecha_es_creible ? (
        <p className="mt-2 text-dato text-danger">
          {t("oportunidad.fechaNoCreible")}
        </p>
      ) : null}
      {plan.aviso ? (
        <p className="mt-1 text-rotulo text-ink-faint">{plan.aviso}</p>
      ) : null}
    </section>
  );
}

/**
 * Por qué se cerró así, en la propia oportunidad: las señales del expediente y
 * su lección. Si el post-mortem obligatorio está sin firmar, se dice aquí, que
 * es donde lo ve quien la llevaba.
 */
function PorQueSeCerro({ id, estado }: { id: string; estado: string }) {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<{
    senales: { factor: string; texto: string }[];
    leccion: { id: string; estado: string; obligatoria: boolean } | null;
  } | null>(null);
  useEffect(() => {
    const control = new AbortController();
    llamar<NonNullable<typeof datos>>(
      `/api/v1/opportunities/${id}/expediente`,
      {
        signal: control.signal,
      },
    )
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(() => setDatos(null)));
    return () => control.abort();
  }, [id]);
  if (!datos) return null;
  const pendiente =
    datos.leccion?.estado === "pendiente" && datos.leccion.obligatoria;
  // Con la forma de los demás paneles de la ficha —rótulo de sección, filas
  // separadas, el factor como etiqueta—, no con un encabezado propio.
  return (
    <section
      className={cn("card mb-4 p-4", pendiente && "border-warning/50")}
      aria-label={t("oportunidad.porQue.titulo")}
    >
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="section-label">
          {t(
            estado === "perdido"
              ? "oportunidad.porQue.perdida"
              : "oportunidad.porQue.ganada",
          )}
        </h2>
        {datos.leccion ? (
          <Link
            to={`/m/lecciones/leccion/${datos.leccion.id}`}
            className={pendiente ? "btn-primary" : "btn-secondary"}
          >
            {t(
              pendiente
                ? "oportunidad.porQue.firmar"
                : "oportunidad.porQue.verLeccion",
            )}
          </Link>
        ) : null}
      </div>
      {pendiente ? (
        <p className="text-rotulo text-warning">
          {t("oportunidad.porQue.pendiente")}
        </p>
      ) : null}
      {datos.senales.length ? (
        <ul className="divide-y divide-ink-dim/30">
          {datos.senales.map((s, i) => (
            <li
              key={i}
              className="flex flex-wrap items-baseline gap-x-3 py-1.5"
            >
              <span className="chip-dato">{humanizar(s.factor)}</span>
              <span className="text-dato text-ink">{s.texto}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-dato text-ink-muted">
          {t("oportunidad.porQue.sinSenales")}
        </p>
      )}
    </section>
  );
}
