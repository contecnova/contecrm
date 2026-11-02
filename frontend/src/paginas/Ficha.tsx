/**
 * La ficha de un registro: sus datos y lo que cuelga de él (CRM-07.04.03.25,
 * CRM-00.05.04.02, CRM-00.05.04.06).
 *
 * Adjuntos, comentarios y documentos del corpus son **transversales**: los
 * mismos para una cuenta, un contacto o una oportunidad. Por eso están aquí, en
 * una ficha que sirve para cualquier objeto, y no repetidos en cada módulo —que
 * es como se acaba con tres implementaciones del mismo panel de adjuntos, dos
 * de ellas sin el aviso de fichero infectado.
 *
 * El tipo de objeto va en la ruta de la API (`/adjuntos/{tipo}/...`) porque es
 * el servicio dueño del registro quien guarda lo que cuelga de él: `party` los
 * adjuntos de una cuenta y `sales` los de una oportunidad. Aquí solo se pasa.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  Cargando,
  Error as Fallo,
  Retenidos,
  Vacio,
} from "@/componentes/Estados";
import { Celda, Tabla } from "@/componentes/Tabla";
import {
  BotonesDeRegistro,
  ConfirmarBorrado,
  FormularioDeEdicion,
  useEdicion,
} from "@/componentes/Edicion";
import {
  escalar,
  esIdentificadorTecnico,
  humanizar,
  nombreDelRegistro,
} from "@/lib/formato";
import { Acciones, esIrreversible } from "@/componentes/Acciones";
import { RegistrarActividad } from "@/componentes/RegistrarActividad";
import { PanelRelacionado } from "@/componentes/PanelRelacionado";
import { SubColecciones } from "@/componentes/SubColecciones";
import { accionesDe, subColeccionesDe, type Accion } from "@/lib/acciones";
import { useSuperficie } from "@/lib/permisos";
import { ErrorApi, llamar, salvoCancelacion, subir } from "@/lib/api";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";
import { DatosClave } from "@/componentes/DatosClave";
import { AprobacionDeDocumento } from "@/paginas/Aprobaciones";

/**
 * Las pestañas de una ficha, con los nombres y el reparto de Lightning.
 *
 * Allí son **Relacionado** y **Detalles**, y «Relacionado» va primero: al
 * abrir un registro lo que se busca casi siempre es lo que cuelga de él —sus
 * contactos, sus oportunidades, sus adjuntos—, no releer sus campos.
 *
 * Aquí estaba al revés y en otro orden: «Datos» primero con TODO dentro
 * —campos, historial y las colecciones relacionadas, una debajo de otra— y
 * después tres pestañas sueltas para adjuntos, comentarios y documentos. Esas
 * tres son cosas que cuelgan del registro, así que su sitio es «Relacionado».
 *
 * «Actividad» es la de Lightning: lo que se habla CON el registro —una
 * llamada, una reunión, una nota, un correo— y lo que se le pregunta a la IA
 * sobre él. Estaba suelto encima de las pestañas, y ocupaba media pantalla
 * antes de llegar a nada.
 *
 * «Comentarios» se queda aparte porque es conversación y no un dato adjunto;
 * es el sitio que en Salesforce ocupa Chatter.
 */
type Pestana = "relacionado" | "detalles" | "actividad" | "comentarios";

export function Ficha() {
  const { t } = useTranslation();
  const navegar = useNavigate();
  const { ruta: rutaDelModulo = "", tipo = "", id = "" } = useParams();
  const modulo = moduloDe(rutaDelModulo);
  // Por el objeto de la dirección y no `recursos[0]`: un módulo tiene varias
  // pestañas y con la primera se pedía el registro contra la ruta equivocada,
  // así que solo se podía abrir una fila de todo el módulo.
  const recurso = modulo ? recursoDe(modulo, tipo) : undefined;
  const { superficie, tiene } = useSuperficie();

  const [pestana, setPestana] = useState<Pestana | null>(null);
  /**
   * El registro lo carga ESTA pantalla, no la pestaña.
   *
   * Lo pedía la pestaña de datos y lo subía a la ficha para el panel de
   * cabecera. Con las pestañas de Lightning eso ya no vale: los botones del
   * registro —«Editar», «Eliminar», lo que el contrato permita— viven en el
   * panel de cabecera y están en todas las pestañas, así que quien manda
   * sobre el registro es la página. Además, pedirlo en la pestaña hacía que
   * cambiar de pestaña volviera a pedirlo entero.
   */
  const [fila, setFila] = useState<Record<string, unknown> | null>(null);
  const [retenidos, setRetenidos] = useState<string[]>([]);
  const [tapados, setTapados] = useState<string[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);
  // Se puede llegar YA en edición, con `?editar=1`. Lo usa el menú de la fila
  // en el listado: en Lightning cada fila lleva un `⌄` con «Editar», y sin
  // esto ese «Editar» sólo podía abrir la ficha y dejar a quien lo pulsó a un
  // clic más de lo que pidió.
  const [parametrosDeFicha] = useSearchParams();
  const [editando, setEditando] = useState(
    parametrosDeFicha.get("editar") === "1",
  );
  // Qué acción del contrato está desplegada. Vive aquí y no dentro de
  // `<Acciones>` porque quien las ofrece es el menú de la barra: con el estado
  // dentro habría dos sitios desde los que abrir la misma cosa.
  const [accionAbierta, setAccionAbierta] = useState<Accion | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);

  // Al cambiar de registro se sale de edición y se cancela la confirmación
  // pendiente. Esta pantalla atiende a `/m/:ruta/:tipo/:id`: ir de una ficha a
  // otra **no la desmonta**, así que sin esto se abría la siguiente ya en modo
  // edición —con los datos de la anterior todavía en el formulario— y un
  // «¿seguro que quieres borrar?» a medias se quedaba apuntando al registro
  // nuevo. Borrar el que no era está a un clic de ahí.
  //
  // **Salvo si la dirección pide lo contrario**: se puede llegar con
  // `?editar=1` desde el menú de una fila del listado, y este efecto corre
  // también en el primer montaje — así que sin mirar el parámetro deshacía lo
  // que acababa de pedirse. Medido: el «Editar» de la fila abría la ficha en
  // modo lectura.
  useEffect(() => {
    setEditando(parametrosDeFicha.get("editar") === "1");
    setConfirmando(false);
  }, [rutaDelModulo, tipo, id, parametrosDeFicha]);

  const { ruta, puedeEditar, puedeBorrar } = useEdicion(recurso, id);

  const cargar = useCallback(
    (signal?: AbortSignal) => {
      if (!ruta) return;
      llamar<Record<string, unknown>>(ruta, { signal })
        .then((r) => {
          setFila(r.datos);
          setRetenidos(r.retenidos);
          setTapados(r.enmascarados);
        })
        .catch(salvoCancelacion(setFallo));
    },
    [ruta],
  );

  useEffect(() => {
    const control = new AbortController();
    cargar(control.signal);
    return () => control.abort();
  }, [cargar]);

  // Todo lo que el servidor admite hacer con este registro, leído del contrato.
  // Son 144 en el sistema y ninguna se escribe a mano aquí.
  const acciones = useMemo(
    () => (recurso ? accionesDe(superficie, recurso.listar, id, tiene) : []),
    [superficie, recurso, id, tiene],
  );
  // Y lo que cuelga de él: líneas, equipo, direcciones, identificadores. Son
  // 196 en el sistema y ninguna se alcanzaba. Se calcula aquí porque de ello
  // depende en qué pestaña se aterriza.
  const paneles = useMemo(
    () =>
      recurso ? subColeccionesDe(superficie, recurso.listar, id, tiene) : [],
    [superficie, recurso, id, tiene],
  );

  /**
   * Si de este registro se habla con alguien.
   *
   * Es lo que decide si tiene sentido apuntarle una llamada, una reunión, una
   * nota o un correo, y si tiene sentido preguntarle a la IA sobre él. Lo
   * contesta el servidor —`objetos.actividades` de la superficie— y no una
   * lista escrita aquí: dos listas acaban diciendo cosas distintas.
   *
   * **Medido el 29-10-2026**: se ofrecían sobre los 52 tipos de registro que
   * declara el front, porque el campo `objeto` de una actividad es polimórfico
   * y el servidor no rechaza nada. «Llamada» sobre un calendario laboral,
   * «Correo» sobre una entrada de papelera. Ofrecer lo que no tiene sentido
   * hace dudar de lo que sí.
   *
   * Y mientras la superficie no ha llegado **no se ofrecen**, al revés que las
   * pestañas. Es la regla de la casa para las acciones: un botón que aparece
   * por defecto y luego resulta que no tocaba es un botón que alguien ya ha
   * pulsado.
   */
  const seHablaConAlguien = Boolean(
    tipo && superficie?.objetos?.actividades?.includes(tipo),
  );

  // Solo las pestañas que este objeto puede tener. Pedir adjuntos de algo que
  // no los admite no sale como «aquí no hay»: sale como un 404 en la consola y
  // una pestaña que nunca carga, y pasaba en 81 de 85 fichas.
  const puedeTener = useCallback(
    (cual: "adjuntos" | "comentarios" | "documentos") =>
      // Mientras la superficie no ha llegado se da por bueno: esconder algo y
      // hacerlo aparecer un segundo después mueve los botones bajo el cursor.
      !superficie?.objetos || superficie.objetos[cual].includes(tipo),
    [superficie, tipo],
  );

  // El orden es el de Lightning: Relacionado, Detalles, Actividad y al final
  // la conversación.
  const pestanas = useMemo<Pestana[]>(
    () => [
      "relacionado",
      "detalles",
      ...(seHablaConAlguien ? ["actividad" as const] : []),
      ...(puedeTener("comentarios") ? ["comentarios" as const] : []),
    ],
    [puedeTener, seHablaConAlguien],
  );

  /**
   * Cuál se abre.
   *
   * **«Relacionado» cuando hay algo que enseñar, y si no «Detalles».** En
   * Lightning la de entrada es siempre «Relacionado» porque al abrir un
   * registro lo que se busca es lo que cuelga de él. Aquí se mira además si
   * hay algo: aterrizar en una pestaña vacía es peor que empezar por los
   * campos, y en este producto hay objetos que no tienen nada colgando.
   *
   * Se calcula sólo mientras nadie ha elegido: en cuanto alguien pulsa una
   * pestaña, manda lo que pulsó — que la pantalla se la cambie al llegar un
   * dato es de las cosas que más desconciertan.
   *
   * Y aquí la regla es la CONTRARIA a la de `puedeTener`, a propósito. Para
   * **enseñar** una pestaña, mientras no se sabe se da por bueno. Para
   * **aterrizar** en ella hace falta saberlo de verdad: con la regla optimista,
   * abrir el enlace directo a un registro cuya superficie todavía no ha
   * llegado aterrizaba siempre en «Relacionado», y en los objetos que no
   * tienen nada colgando eso es una pestaña vacía como primera impresión.
   */
  const hayRelacionado =
    paneles.length > 0 ||
    Boolean(
      superficie?.objetos &&
      (superficie.objetos.adjuntos.includes(tipo) ||
        superficie.objetos.documentos.includes(tipo)),
    );
  const activa: Pestana =
    pestana && pestanas.includes(pestana)
      ? pestana
      : hayRelacionado
        ? "relacionado"
        : "detalles";

  async function borrar() {
    setEnviando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      // Se vuelve al listado: quedarse en la ficha de algo que ya no existe
      // enseñaría un registro fantasma hasta que alguien recargara.
      navegar(`/m/${rutaDelModulo}`);
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setEnviando(false);
    }
  }

  if (!modulo) return <Vacio />;

  const nombre = fila ? nombreDelRegistro(fila) : "";

  return (
    <>
      {/* El panel de datos clave, como el de Salesforce: qué es, cómo se
          llama, por dónde va, los cinco campos que importan y **qué se puede
          hacer con él**, todo arriba y sin entrar en ninguna pestaña.

          Los botones estaban debajo de las pestañas, dentro de la pestaña de
          datos: para editar desde «Relacionado» había que volver. Visto en la
          pantalla el 02-11-2026.

          Si el registro no tiene con qué llamarse el título sigue siendo **el
          nombre de lo que es** y no su UUID: treinta y seis caracteres de
          encabezado no dicen qué se está mirando. */}
      <DatosClave
        recurso={recurso}
        tipo={tipo}
        nombre={nombre || recurso?.nombre || modulo.titulo}
        fila={fila}
        volverA={{ a: `/m/${rutaDelModulo}`, titulo: modulo.titulo, id }}
        acciones={
          fila && !editando ? (
            <BotonesDeRegistro
              puedeEditar={puedeEditar}
              puedeBorrar={puedeBorrar}
              alEditar={() => setEditando(true)}
              alBorrar={() => setConfirmando(true)}
              extra={acciones.map((a) => ({
                clave: a.ruta,
                nombre: a.nombre,
                alElegir: () => setAccionAbierta(a),
                destructiva: esIrreversible(a),
              }))}
            />
          ) : null
        }
      />

      {/* El formulario de la acción elegida en «Más». Va aquí, pegado al panel
          que la ofrece, y no dentro de una pestaña: la acción es sobre el
          registro, no sobre lo que se esté mirando de él. */}
      {!editando ? (
        <Acciones
          acciones={acciones}
          servicio={recurso?.servicio ?? ""}
          abierta={accionAbierta}
          alCambiarAbierta={setAccionAbierta}
          alTerminar={cargar}
        />
      ) : null}

      {confirmando ? (
        <ConfirmarBorrado
          enviando={enviando}
          alBorrar={() => void borrar()}
          alCancelar={() => setConfirmando(false)}
        />
      ) : null}

      {fallo && fila ? (
        <div className="mb-3">
          <Fallo error={fallo} />
        </div>
      ) : null}

      {/* Las pestañas con la forma de Lightning: subrayado azul en la activa
          sobre una línea que recorre el ancho. Eran píldoras con el fondo
          claro del tema, y sobre una tarjeta blanca la activa quedaba del
          mismo color que las otras: se marcaba con `aria-current` y no se
          veía. Visto en la pantalla: tres pestañas idénticas. */}
      <nav
        aria-label={t("ficha.secciones")}
        className="mt-3 flex flex-wrap border-b border-ink-dim"
      >
        {pestanas.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setPestana(p)}
            aria-current={p === activa ? "page" : undefined}
            className={`-mb-px border-b-[3px] px-4 py-2 text-xs ${
              p === activa
                ? "border-accent font-semibold text-accent"
                : "border-transparent text-ink-muted hover:border-ink-dim hover:text-ink"
            }`}
          >
            {t(`ficha.${p}`)}
          </button>
        ))}
      </nav>

      <div className="mt-4">
        {fallo && !fila ? (
          <Fallo error={fallo} reintentar={() => cargar()} />
        ) : !fila ? (
          <Cargando />
        ) : editando && recurso ? (
          // El formulario sale mirando cualquier pestaña: «Editar» se pulsa
          // desde arriba, y abrirlo sólo en «Detalles» dejaba el botón sin
          // efecto visible.
          <FormularioDeEdicion
            recurso={recurso}
            ruta={ruta}
            valores={fila}
            alGuardar={() => {
              setEditando(false);
              cargar();
              setFallo(null);
            }}
            alCancelar={() => setEditando(false)}
          />
        ) : (
          <>
            {activa === "detalles" ? (
              <Detalles
                fila={fila}
                retenidos={retenidos}
                enmascarados={tapados}
                objeto={tipo}
                servicio={recurso?.servicio ?? ""}
                id={id}
              />
            ) : null}

            {activa === "relacionado" ? (
              <div className="space-y-3">
                <SubColecciones
                  paneles={paneles}
                  servicio={recurso?.servicio ?? ""}
                  id={id}
                />
                {puedeTener("adjuntos") ? (
                  <Adjuntos tipo={tipo} id={id} />
                ) : null}
                {puedeTener("documentos") ? (
                  <Documentos tipo={tipo} id={id} nombre={nombre} />
                ) : null}
              </div>
            ) : null}

            {/* Apuntar una llamada o un correo sobre este registro sin salir
                de aquí: antes obligaba a irse a Actividades y teclear a mano
                el identificador para que quedara colgado, y eso no lo hace
                nadie dos veces. Y preguntar sobre ESTE registro
                (CRM-05.01.04.09), delante del dato, que es donde se le ocurre
                a alguien. */}
            {activa === "actividad" ? (
              <>
                <RegistrarActividad
                  objeto={tipo}
                  objetoId={id}
                  alRegistrar={cargar}
                />
                <PreguntarSobreEsto objeto={tipo} objetoId={id} />
              </>
            ) : null}

            {activa === "comentarios" ? (
              <Comentarios tipo={tipo} id={id} />
            ) : null}
          </>
        )}
      </div>
    </>
  );
}

/**
 * La pestaña «Detalles»: los campos del registro y su trazabilidad.
 *
 * Sólo pinta; el registro lo carga la ficha. Antes esto era la pestaña
 * «Datos» y llevaba dentro TODO —campos, historial, los botones del registro
 * y las colecciones relacionadas, una debajo de otra—, que es justo el reparto
 * que Lightning separa en dos pestañas.
 */
function Detalles({
  fila,
  retenidos,
  enmascarados,
  objeto,
  servicio,
  id,
}: {
  fila: Record<string, unknown>;
  retenidos: string[];
  enmascarados: string[];
  /** Tipo del registro (`cuenta`, `oportunidad`…), para su trazabilidad. */
  objeto: string;
  servicio: string;
  id: string;
}) {
  const { t } = useTranslation();
  return (
    <>
      {/* Los datos como ficha, no como una tabla de una sola fila: una tabla
          horizontal de veinte columnas para UN registro obliga a desplazarse
          para leer sus propios campos. */}
      <dl className="card grid gap-x-8 gap-y-3 p-4 sm:grid-cols-2">
        {Object.entries(fila)
          .filter(
            ([clave]) => clave !== "campos" && !esIdentificadorTecnico(clave),
          )
          .map(([clave, valor]) => (
            <Campo key={clave} clave={clave} valor={valor} />
          ))}
      </dl>

      {/* Los identificadores, detrás de un desplegable. Ocupaban la mitad de
          la ficha y no dicen nada a quien la mira, pero quien abre una
          incidencia de soporte los necesita enteros. */}
      <details className="mt-2">
        <summary className="cursor-pointer text-3xs text-ink-faint">
          {t("ficha.identificadores")}
        </summary>
        <dl className="card mt-2 grid gap-x-8 gap-y-2 p-4 sm:grid-cols-2">
          {Object.entries(fila)
            .filter(([clave]) => esIdentificadorTecnico(clave))
            .map(([clave, valor]) => (
              <Campo key={clave} clave={clave} valor={valor} monoespaciado />
            ))}
        </dl>
      </details>

      <Retenidos campos={retenidos} enmascarados={enmascarados} />

      {/* Qué ha cambiado en ESTE registro, campo a campo. Plegado y cargado
          sólo al abrirlo: es trazabilidad, no contenido, y pedirlo en cada
          ficha abierta sería una llamada más por registro que casi nadie mira.
          Pero cuando hace falta es lo primero que se pregunta —«esto antes no
          decía esto»—, y hasta el 29-10-2026 se escribía y no lo devolvía
          ninguna ruta. */}
      {objeto && servicio ? (
        <HistorialDeCampos servicio={servicio} objeto={objeto} objetoId={id} />
      ) : null}

      {/* Y cómo estaba el registro ENTERO en un momento dado, para los objetos
          que tienen el rastro completo encendido. El historial de campos dice
          qué cambió; no dice cómo era el conjunto, y reconstruirlo a mano
          encadenando cambios sale mal en cuanto hay una fusión por medio. */}
      {objeto && servicio ? (
        <ComoEstabaEsto servicio={servicio} objeto={objeto} objetoId={id} />
      ) : null}
    </>
  );
}

function Campo({
  clave,
  valor,
  monoespaciado = false,
}: {
  clave: string;
  valor: unknown;
  monoespaciado?: boolean;
}) {
  // El rótulo encima y el valor debajo, como el panel de datos clave de
  // arriba y como la pestaña «Detalles» de Lightning. Estaban enfrentados a
  // los dos extremos de la fila: en una pantalla ancha quedaban 900 px entre
  // «Nombre» y «Ana», y emparejar rótulo y valor a esa distancia no se hace
  // de un vistazo. Dos sitios del producto que enseñan lo mismo —aquí y
  // arriba— ahora lo colocan igual.
  return (
    <div className="min-w-0">
      <dt className="truncate text-3xs text-ink-faint" title={humanizar(clave)}>
        {humanizar(clave)}
      </dt>
      <dd
        className={`truncate text-2xs text-ink ${monoespaciado ? "font-mono text-3xs text-ink-muted" : ""}`}
        title={String(valor ?? "")}
      >
        {/* Un valor compuesto se pinta con el MISMO renderizador que la tabla.
            Aquí iba `JSON.stringify(valor)`, así que la ficha de un registro
            enseñaba `{"esquema":"CNAE","codigo":"2932"}` donde la tabla del
            listado enseña dos etiquetas legibles. La misma información, en dos
            pantallas del mismo producto, con dos formatos — y el de la ficha
            nadie lo lee de un vistazo. */}
        {valor === null || valor === undefined || valor === "" ? (
          <span className="text-ink-faint">—</span>
        ) : typeof valor === "object" ? (
          <Celda valor={valor} campo={clave} />
        ) : (
          escalar(valor, clave)
        )}
      </dd>
    </div>
  );
}

function Adjuntos({ tipo, id }: { tipo: string; id: string }) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Record<string, unknown>[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [subiendo, setSubiendo] = useState(false);
  // Abierto de entrada, al revés que los paneles del contrato: aquí sólo hay
  // dos tarjetas y son el motivo de la pestaña. Los otros son hasta ocho y se
  // piden al abrirse.
  const [abierto, setAbierto] = useState(true);

  const cargar = useCallback(async () => {
    try {
      const r = await llamar<Record<string, unknown>[]>(
        `/api/v1/adjuntos/${tipo}?objeto_id=${encodeURIComponent(id)}`,
      );
      setFilas(r.datos);
    } catch (error) {
      setFallo(error);
    }
  }, [tipo, id]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function elegir(fichero: File | undefined) {
    if (!fichero) return;
    setSubiendo(true);
    setFallo(null);
    try {
      await subir(`/api/v1/adjuntos/${tipo}`, fichero, { objeto_id: id });
      await cargar();
    } catch (error) {
      setFallo(error);
    } finally {
      setSubiendo(false);
    }
  }

  return (
    <PanelRelacionado
      nombre={t("ficha.adjuntos")}
      cuantos={filas?.length}
      abierto={abierto}
      alAlternar={() => setAbierto((v) => !v)}
      acciones={
        <label className="btn-secondary cursor-pointer">
          {subiendo ? t("ficha.subiendo") : t("ficha.subir")}
          <input
            type="file"
            className="sr-only"
            disabled={subiendo}
            onChange={(e) => void elegir(e.target.files?.[0])}
          />
        </label>
      }
    >
      <>
        {/* Subir un adjunto cambia la lista sin decir nada: quien no ve la
            pantalla no se entera de que ha terminado (CRM-06.02.01.05). */}
        <p className="sr-only" role="status">
          {subiendo ? t("ficha.subiendo") : t("ficha.subido")}
        </p>
        {fallo ? (
          <div className="mb-3">
            <Fallo error={fallo} />
          </div>
        ) : null}
        {filas === null ? (
          <Cargando />
        ) : filas.length === 0 ? (
          <Vacio compacto />
        ) : (
          <Tabla
            filas={filas}
            columnas={["nombre", "tipo_mime", "tamano", "version", "analisis"]}
            titulo={t("ficha.adjuntos")}
          />
        )}
      </>
    </PanelRelacionado>
  );
}

function Comentarios({ tipo, id }: { tipo: string; id: string }) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Record<string, unknown>[] | null>(null);
  const [texto, setTexto] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(async () => {
    try {
      const r = await llamar<Record<string, unknown>[]>(
        `/api/v1/comentarios/${tipo}/${id}`,
      );
      setFilas(r.datos);
    } catch (error) {
      setFallo(error);
    }
  }, [tipo, id]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function enviar() {
    if (!texto.trim()) return;
    try {
      await llamar(`/api/v1/comentarios/${tipo}/${id}`, {
        metodo: "POST",
        cuerpo: { texto },
      });
      setTexto("");
      await cargar();
    } catch (error) {
      setFallo(error);
    }
  }

  return (
    <>
      <div className="flex gap-2">
        <label className="sr-only" htmlFor="comentario">
          {t("ficha.escribir")}
        </label>
        <input
          id="comentario"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder={t("ficha.escribir")}
          className="flex-1 rounded-lg border border-ink-dim/60 bg-paper px-3 py-2 text-xs text-ink"
        />
        <button
          type="button"
          onClick={() => void enviar()}
          className="rounded-lg bg-accent px-3 py-1.5 text-2xs text-paper hover:bg-accent-soft"
        >
          {t("ficha.enviar")}
        </button>
      </div>
      {fallo ? (
        <div className="mt-3">
          <Fallo error={fallo} />
        </div>
      ) : null}
      <div className="mt-3">
        {filas === null ? (
          <Cargando />
        ) : filas.length === 0 ? (
          <Vacio compacto />
        ) : (
          <Tabla filas={filas} titulo={t("ficha.comentarios")} />
        )}
      </div>
    </>
  );
}

function Documentos({
  tipo,
  id,
  nombre,
}: {
  tipo: string;
  id: string;
  nombre: string;
}) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Record<string, unknown>[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [recargar, setRecargar] = useState(0);
  const [abierto, setAbierto] = useState(true);

  useEffect(() => {
    const control = new AbortController();
    llamar<Record<string, unknown>[]>(`/api/v1/documentos/${tipo}/${id}`, {
      signal: control.signal,
    })
      .then((r) => setFilas(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [tipo, id, recargar]);

  return (
    <PanelRelacionado
      nombre={t("ficha.documentos")}
      cuantos={filas?.length}
      abierto={abierto}
      alAlternar={() => setAbierto((v) => !v)}
    >
      <>
        {/* Se dice de dónde sale el estado real: sin esta línea, alguien
            construiría un informe sobre el título creyendo que está al día. El
            documento vive en el gestor, aquí está el enlace y el contexto. */}
        <p className="mb-2 text-2xs text-ink-faint">
          {t("ficha.documentosIntro")}
        </p>
        {fallo ? (
          <Fallo error={fallo} />
        ) : filas === null ? (
          <Cargando />
        ) : (
          <>
            {filas.length === 0 ? (
              <Vacio compacto />
            ) : (
              <Tabla filas={filas} titulo={t("ficha.documentos")} />
            )}
            {filas.length > 0 ? <Aprobacion filas={filas} /> : null}
            <BuscarEnElCorpus
              tipo={tipo}
              id={id}
              nombre={nombre}
              alEnlazar={() => setRecargar((n) => n + 1)}
            />
          </>
        )}
      </>
    </PanelRelacionado>
  );
}

/**
 * La aprobación de los documentos enlazados a este registro.
 *
 * Va debajo de la tabla y no como una columna suya porque esa tabla es
 * genérica: se pinta de lo que devuelve la API, sin celdas a medida. Meter aquí
 * una excepción obligaría a que la tabla supiera de aprobaciones, y entonces
 * las otras treinta pantallas que la usan también.
 *
 * Cerrado de entrada: cada documento abierto es una llamada al gestor, y una
 * ficha con doce contratos enlazados haría doce al abrir la pestaña.
 */
function Aprobacion({ filas }: { filas: Record<string, unknown>[] }) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState<string | null>(null);

  return (
    <section className="mt-6 border-t border-ink-dim/30 pt-4">
      <h3 className="mb-2 text-xs font-medium text-ink">
        {t("ficha.aprobacion")}
      </h3>
      <ul className="lista-acotada space-y-1 pr-1">
        {filas.map((fila, i) => {
          const id = String(fila.documento_id ?? fila.document_id ?? "");
          const titulo = String(fila.titulo ?? fila.title ?? id);
          if (!id) return null;
          const esta = abierto === id;
          return (
            <li
              key={id || i}
              className="rounded border border-ink-dim/30 px-2 py-1"
            >
              <button
                type="button"
                onClick={() => setAbierto(esta ? null : id)}
                aria-expanded={esta}
                className="flex w-full items-center justify-between gap-2 text-left text-xs text-ink"
              >
                <span className="truncate">{titulo}</span>
                <span className="shrink-0 text-2xs text-ink-muted">
                  {esta ? t("ficha.cerrar") : t("ficha.verAprobacion")}
                </span>
              </button>
              {esta ? (
                <div className="mt-2 border-t border-ink-dim/30 pt-2">
                  <AprobacionDeDocumento documentoId={id} />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * Buscar en el corpus y traerse un documento a este registro.
 *
 * La búsqueda va **con la identidad de quien la hace**, así que enseña lo que
 * esa persona vería entrando al gestor: ni más ni menos. Un resultado que no
 * aparece no es un fallo de la búsqueda.
 *
 * Al enlazar se manda el NOMBRE del registro, y con él el servidor coloca el
 * documento en la carpeta de este registro y guarda cuál. Se hace allí y no
 * aquí porque son dos llamadas al gestor —resolver la carpeta y mover el
 * documento— y partirlas entre navegador y servidor dejaría el enlace creado y
 * el documento sin colocar en cuanto una fallara a medias.
 */
function BuscarEnElCorpus({
  tipo,
  id,
  nombre,
  alEnlazar,
}: {
  tipo: string;
  id: string;
  nombre: string;
  alEnlazar: () => void;
}) {
  const { t } = useTranslation();
  const [texto, setTexto] = useState("");
  const [resultados, setResultados] = useState<
    Record<string, unknown>[] | null
  >(null);
  const [buscando, setBuscando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  const buscar = useCallback(async () => {
    if (texto.trim().length < 2) return;
    setBuscando(true);
    setFallo(null);
    try {
      const r = await llamar<{ resultados: Record<string, unknown>[] }>(
        `/api/v1/documentos/buscar?q=${encodeURIComponent(texto.trim())}`,
      );
      setResultados(r.datos.resultados ?? []);
    } catch (e) {
      setFallo(e);
    } finally {
      setBuscando(false);
    }
  }, [texto]);

  const enlazar = useCallback(
    async (doc: Record<string, unknown>) => {
      try {
        await llamar(`/api/v1/documentos/${tipo}/${id}`, {
          metodo: "POST",
          cuerpo: {
            documento_id: String(doc.id ?? doc.document_id ?? ""),
            titulo: String(doc.title ?? doc.titulo ?? ""),
            // El nombre del registro es lo que da nombre a su carpeta. Si el
            // registro aún no tiene nombre cargado se manda vacío y el
            // documento se enlaza sin colocar, que es mejor que colocarlo en
            // una carpeta llamada como un identificador.
            etiqueta: nombre,
          },
        });
        alEnlazar();
        setResultados(null);
        setTexto("");
      } catch (e) {
        setFallo(e);
      }
    },
    [tipo, id, nombre, alEnlazar],
  );

  return (
    <section className="mt-6 border-t border-ink-dim/30 pt-4">
      <h3 className="mb-2 text-xs font-medium text-ink">
        {t("ficha.buscarCorpus")}
      </h3>
      <div className="flex gap-2">
        <input
          type="search"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void buscar();
          }}
          placeholder={t("ficha.buscarCorpusPista")}
          aria-label={t("ficha.buscarCorpus")}
          className="flex-1 rounded border border-ink-dim/60 bg-paper px-2 py-1 text-xs text-ink"
        />
        <button
          type="button"
          onClick={() => void buscar()}
          disabled={buscando || texto.trim().length < 2}
          className="rounded border border-ink-dim/60 px-3 py-1 text-xs text-ink disabled:opacity-50"
        >
          {buscando ? t("ficha.buscando") : t("ficha.buscar")}
        </button>
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      {resultados !== null && resultados.length === 0 ? (
        <p className="mt-2 text-2xs text-ink-faint">
          {t("ficha.corpusSinResultados")}
        </p>
      ) : null}
      {resultados !== null && resultados.length > 0 ? (
        <ul className="lista-acotada mt-2 space-y-1 pr-1">
          {resultados.map((doc, i) => (
            <li
              key={String(doc.id ?? doc.document_id ?? i)}
              className="flex items-center justify-between gap-2 rounded border border-ink-dim/30 px-2 py-1"
            >
              <span className="truncate text-xs text-ink">
                {String(doc.title ?? doc.titulo ?? doc.id ?? "")}
              </span>
              <button
                type="button"
                onClick={() => void enlazar(doc)}
                className="shrink-0 rounded border border-ink-dim/60 px-2 py-0.5 text-2xs text-ink"
              >
                {t("ficha.enlazar")}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/**
 * Preguntar sobre el registro que se está mirando (CRM-05.01.04.09).
 *
 * La pregunta se hace **delante del dato**, que es donde se le ocurre a
 * alguien. Obligar a irse a la pantalla de explotación y volver a escribir de
 * qué cuenta se habla es como se deja de preguntar.
 *
 * Lo que no se negocia: **el filtro se enseña**. El servidor lo añade —no lo
 * sugiere— y devuelve la pregunta tal como quedó, porque un número que parece
 * de toda la empresa y es de una cuenta no cuadra con nada en la reunión
 * siguiente, y para cuando se descubre ya se ha dicho en voz alta.
 */
export function PreguntarSobreEsto({
  objeto,
  objetoId,
}: {
  objeto: string;
  objetoId: string;
}) {
  const { t } = useTranslation();
  const [pregunta, setPregunta] = useState("");
  const [salida, setSalida] = useState<{
    pregunta?: string;
    filtro?: string;
  } | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);
  const [pidiendo, setPidiendo] = useState(false);

  async function preguntar() {
    setPidiendo(true);
    setFallo(null);
    try {
      const r = await llamar<{ pregunta?: string; filtro?: string }>(
        "/api/v1/analisis/contexto",
        {
          metodo: "POST",
          cuerpo: { pregunta, objeto, registro_id: objetoId },
        },
      );
      setSalida(r.datos);
    } catch (e: unknown) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      setPidiendo(false);
    }
  }

  return (
    <section className="card p-3">
      <h2 className="section-label mb-1">{t("ficha.preguntarSobreEsto")}</h2>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex-1">
          <span className="sr-only">{t("ficha.tuPregunta")}</span>
          <input
            className="input-base w-full"
            value={pregunta}
            placeholder={t("ficha.ejemploPregunta")}
            onChange={(e) => setPregunta(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="btn-primary"
          disabled={pidiendo || pregunta.trim() === ""}
          onClick={() => void preguntar()}
        >
          {t("ficha.preguntar")}
        </button>
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      <div role="status" aria-live="polite">
        {salida ? (
          <p
            className="mt-2 text-3xs text-ink-muted"
            data-testid="pregunta-en-contexto"
          >
            {salida.pregunta}
            {salida.filtro ? (
              <span className="ml-1 text-ink">
                {t("ficha.conFiltro", { filtro: salida.filtro })}
              </span>
            ) : null}
          </p>
        ) : null}
      </div>
    </section>
  );
}

interface CambioDeCampo {
  campo: string;
  valor_anterior: string | null;
  valor_nuevo: string | null;
  actor?: string | null;
  origen?: string | null;
  cuando?: string | null;
}

interface HistorialCampos {
  cambios: CambioDeCampo[];
  cuantos: number;
  que_significa: string;
}

/**
 * Qué ha cambiado en este registro, campo a campo.
 *
 * **Se escribía y no lo leía nadie.** Cada edición anota el campo, el valor
 * anterior, el nuevo, quién lo hizo y **desde dónde** —la pantalla, la API o
 * una automatización—, y ninguna ruta lo devolvía. Es la primera pregunta de
 * cualquier discusión sobre un registro: «esto antes no decía esto».
 *
 * El **origen** es la mitad que casi nunca se guarda y la que la zanja: no es
 * lo mismo que lo cambiara una persona a que lo pisara una sincronización
 * todas las noches, y sin saberlo se culpa a quien pasaba por ahí.
 *
 * Plegado y cargado **sólo al abrirlo**: es trazabilidad, no contenido, y
 * pedirlo en cada ficha abierta sería una llamada por registro que casi nadie
 * mira. Y cuando está vacío, el servidor dice cuál de las dos cosas es —este
 * registro no se ha tocado, o este servicio no lleva ese histórico—, que con
 * la lista vacía se ven igual.
 */
export function HistorialDeCampos({
  servicio,
  objeto,
  objetoId,
}: {
  servicio: string;
  objeto: string;
  objetoId: string;
}) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const [datos, setDatos] = useState<HistorialCampos | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<HistorialCampos>(
      `/api/v1/${servicio}/rastro/campos/${objeto}/${objetoId}`,
      { signal: control.signal },
    )
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [servicio, objeto, objetoId]);

  useEffect(() => {
    if (!abierto || datos) return undefined;
    return cargar();
  }, [abierto, datos, cargar]);

  return (
    <details
      className="mt-3"
      onToggle={(e) => setAbierto(e.currentTarget.open)}
    >
      <summary className="cursor-pointer text-3xs text-ink-faint">
        {t("ficha.queHaCambiado")}
      </summary>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {abierto && !datos && !fallo ? <Cargando /> : null}
      {datos ? (
        datos.cambios.length === 0 ? (
          <Vacio
            titulo={t("ficha.sinCambios")}
            detalle={datos.que_significa}
            compacto
          />
        ) : (
          <ul className="card mt-2 flex flex-col gap-2 p-4">
            {datos.cambios.map((c, i) => (
              <li key={`${c.campo}-${i}`} className="text-2xs">
                <span className="text-ink">{c.campo}</span>:{" "}
                <span className="text-ink-faint line-through">
                  {c.valor_anterior ?? "—"}
                </span>{" "}
                → <span className="text-ink">{c.valor_nuevo ?? "—"}</span>
                {/* El origen al lado del cambio, no en otra columna: es lo que
                    distingue «lo cambió alguien» de «lo pisó una
                    sincronización», y es la diferencia que zanja la
                    discusión. */}
                {c.origen ? (
                  <span className="ml-2 chip-dato">{c.origen}</span>
                ) : null}
              </li>
            ))}
          </ul>
        )
      ) : null}
    </details>
  );
}

interface Reconstruido {
  objeto: string;
  hasta: string | null;
  hechos: number;
  estado: Record<string, unknown>;
  hechos_compensados: number;
  porque: string;
}

interface Cuadra {
  cuadra: boolean;
  diferencias: { campo: string; reconstruido: unknown; vivo: unknown }[];
  que_significa: string;
}

/**
 * Cómo estaba este registro en un momento dado (CRM-00.05.04.06).
 *
 * La pregunta que resuelve llega siempre tarde: **«¿cómo estaba esto el 3 de
 * marzo?»**. El historial de campos dice qué cambió; no dice cómo era el
 * conjunto, y reconstruirlo a mano encadenando cambios sale mal en cuanto hay
 * una fusión o un borrado por medio.
 *
 * **Y lo que de verdad importa es la comprobación de que cuadra.** Una
 * reconstrucción que no coincide con la tabla viva significa que alguien
 * escribió en la tabla sin pasar por el rastro —un script de corrección, una
 * migración, un arreglo a mano un viernes— y a partir de ahí el rastro deja de
 * ser una prueba sin que nadie se entere, porque sigue contestando con la
 * misma seguridad.
 *
 * Plegado y cargado sólo al abrirlo: el rastro completo está encendido en muy
 * pocos objetos a propósito —guardar todos los hechos de todo multiplica la
 * escritura por algo que casi nadie consulta— y pedirlo en cada ficha sería
 * una llamada por registro abierto que casi siempre contestaría «aquí no hay».
 */
export function ComoEstabaEsto({
  servicio,
  objeto,
  objetoId,
}: {
  servicio: string;
  objeto: string;
  objetoId: string;
}) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const [estado, setEstado] = useState<Reconstruido | null>(null);
  const [cuadra, setCuadra] = useState<Cuadra | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    if (!abierto) return;
    const control = new AbortController();
    setFallo(null);
    llamar<Reconstruido>(`/api/v1/${servicio}/rastro/${objeto}/${objetoId}`, {
      signal: control.signal,
    })
      .then((r) => setEstado(r.datos))
      // Un objeto sin rastro completo contesta 404 a propósito, y eso no es un
      // error: es que nadie lo encendió para este objeto.
      .catch(salvoCancelacion(setFallo));
    void llamar<Cuadra>(
      `/api/v1/${servicio}/rastro/${objeto}/${objetoId}/cuadra`,
      { signal: control.signal },
    )
      .then((r) => setCuadra(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, [abierto, servicio, objeto, objetoId]);

  return (
    <details
      className="card mt-4 p-4"
      onToggle={(e) => setAbierto((e.target as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer text-2xs font-medium text-ink">
        {t("ficha.comoEstaba")}
      </summary>
      {fallo ? (
        <p className="mt-2 text-2xs text-ink-muted">
          {t("ficha.sinRastroCompleto")}
        </p>
      ) : null}
      {estado ? (
        <>
          <p className="mt-2 text-2xs text-ink-muted">
            {t("ficha.hechos", {
              cuantos: estado.hechos,
              compensados: estado.hechos_compensados,
            })}
          </p>
          {/* Los compensados se aplican y se anulan, no se saltan: saltarlos
              daría el estado que habría habido si nadie se hubiera equivocado,
              que no es lo que pasó. */}
          <p className="mt-1 text-3xs text-ink-faint">{estado.porque}</p>
        </>
      ) : null}
      {cuadra ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-2">
          <p
            className={
              cuadra.cuadra ? "text-2xs text-success" : "text-2xs text-danger"
            }
          >
            {cuadra.cuadra ? t("ficha.cuadra") : t("ficha.noCuadra")}
          </p>
          <p className="mt-1 text-3xs text-ink-muted">{cuadra.que_significa}</p>
          {(cuadra.diferencias ?? []).length > 0 ? (
            <ul className="mt-1 divide-y divide-ink-dim/30">
              {(cuadra.diferencias ?? []).map((d) => (
                <li
                  key={d.campo}
                  className="flex flex-wrap items-baseline gap-x-2 py-1 text-3xs"
                >
                  <span className="font-medium text-ink">{d.campo}</span>
                  <span className="text-ink-faint">
                    {String(d.reconstruido ?? "—")}
                  </span>
                  <span className="text-ink-muted">
                    ≠ {String(d.vivo ?? "—")}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}
