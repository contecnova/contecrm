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

import { ArchivadoDelRegistro } from "@/componentes/Archivo";
import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Tabla } from "@/componentes/Tabla";
import {
  BotonesDeRegistro,
  ConfirmarBorrado,
  FormularioDeEdicion,
  useEdicion,
} from "@/componentes/Edicion";
import { nombreDelRegistro } from "@/lib/formato";
import { Acciones, esIrreversible } from "@/componentes/Acciones";
import { AsistenteIA, esDeIA } from "@/componentes/AsistenteIA";
import { RegistrarActividad } from "@/componentes/RegistrarActividad";
import { ConvertirLead } from "@/componentes/ConvertirLead";
import { PanelRelacionado } from "@/componentes/PanelRelacionado";
import { PestanasDeFicha } from "@/componentes/PestanasDeFicha";
import { GenerarDocumento } from "@/componentes/GenerarDocumento";
import { SubColecciones } from "@/componentes/SubColecciones";
import { DetallesDelRegistro } from "@/componentes/DetallesDelRegistro";
import { accionesDe, subColeccionesDe, type Accion } from "@/lib/acciones";
import { useSuperficie } from "@/lib/permisos";
import { ErrorApi, llamar, salvoCancelacion, subir } from "@/lib/api";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";
import { DatosClave } from "@/componentes/DatosClave";
import { AprobacionDeDocumento } from "@/paginas/Aprobaciones";
import { diferido } from "@/lib/diferido";

// Los bloques que sólo salen en un tipo de registro, diferidos: importados de
// forma estática viajaban en la ficha de todos (10-11-2026).
const TranscripcionDeReunion = diferido(() =>
  import("@/componentes/TranscripcionDeReunion").then(
    (m) => m.TranscripcionDeReunion,
  ),
);
const VistaPreviaCorreo = diferido(() =>
  import("@/componentes/VistaPreviaCorreo").then((m) => m.VistaPreviaCorreo),
);
const CredencialesDeConexion = diferido(() =>
  import("@/componentes/CredencialesDeConexion").then(
    (m) => m.CredencialesDeConexion,
  ),
);
const CarpetaDelRegistro = diferido(() =>
  import("@/componentes/CarpetaDelRegistro").then((m) => m.CarpetaDelRegistro),
);
const ReunionEnLinea = diferido(() =>
  import("@/componentes/ReunionEnLinea").then((m) => m.ReunionEnLinea),
);
const VariantesDeCopy = diferido(() =>
  import("@/componentes/VariantesDeCopy").then((m) => m.VariantesDeCopy),
);
const ReferenciasDeSuite = diferido(() =>
  import("@/componentes/ReferenciasDeSuite").then((m) => m.ReferenciasDeSuite),
);
const PrediccionDelRegistro = diferido(() =>
  import("@/componentes/PrediccionDelRegistro").then(
    (m) => m.PrediccionDelRegistro,
  ),
);
const Marcador = diferido(() =>
  import("@/componentes/Marcador").then((m) => m.Marcador),
);
const RepartoYOrigenDelLead = diferido(() =>
  import("@/componentes/RepartoYOrigenDelLead").then(
    (m) => m.RepartoYOrigenDelLead,
  ),
);
const CorreoDelContacto = diferido(() =>
  import("@/componentes/CorreoDelContacto").then((m) => m.CorreoDelContacto),
);
const PuntuacionDelLead = diferido(() =>
  import("@/componentes/PuntuacionDelLead").then((m) => m.PuntuacionDelLead),
);
const AtribucionDeLead = diferido(() =>
  import("@/componentes/AtribucionDeLead").then((m) => m.AtribucionDeLead),
);
const ResolucionesDeDevolucion = diferido(() =>
  import("@/componentes/ResolucionesDeDevolucion").then(
    (m) => m.ResolucionesDeDevolucion,
  ),
);
const RenovacionDeContrato = diferido(() =>
  import("@/componentes/RenovacionDeContrato").then(
    (m) => m.RenovacionDeContrato,
  ),
);
const HerramientasDeExposicion = diferido(() =>
  import("@/componentes/HerramientasDeExposicion").then(
    (m) => m.HerramientasDeExposicion,
  ),
);
const SePuedePublicar = diferido(() =>
  import("@/componentes/SePuedePublicar").then((m) => m.SePuedePublicar),
);
const QuienMandaSobre = diferido(() =>
  import("@/componentes/QuienMandaSobre").then((m) => m.QuienMandaSobre),
);

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
  // Sube al generar un documento: el PDF se guarda como adjunto y el panel
  // de adjuntos tiene que volver a pedirse para enseñarlo.
  const [adjuntosVersion, setAdjuntosVersion] = useState(0);
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

  const { ruta, puedeEditar, puedeBorrar, borrado } = useEdicion(recurso, id);

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
    () =>
      recurso
        ? accionesDe(superficie, recurso.listar.split("?")[0] ?? "", id, tiene)
        : [],
    [superficie, recurso, id, tiene],
  );
  // Y lo que cuelga de él: líneas, equipo, direcciones, identificadores. Son
  // 196 en el sistema y ninguna se alcanzaba. Se calcula aquí porque de ello
  // depende en qué pestaña se aterriza.
  const paneles = useMemo(
    () =>
      recurso
        ? subColeccionesDe(
            superficie,
            recurso.listar.split("?")[0] ?? "",
            id,
            tiene,
          )
        : [],
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

  if (!modulo) return <Vacio compacto />;

  // **Hay lecturas que devuelven lo que el registro CONTIENE, no el registro.**
  // `GET /colas/{clave}` es lo que espera en esa cola —una lista de casos—, y
  // la ficha la pintaba como «0 · Caso ID: … +4», un campo por posición. Una
  // lista se enseña como tabla; y sin el registro delante no hay con qué
  // rellenar «Editar», así que no se ofrece: esos campos se editan en línea
  // desde el listado, que sí los tiene.
  const contenido = Array.isArray(fila)
    ? (fila as Record<string, unknown>[])
    : null;
  const registro = contenido ? null : fila;
  const nombre = registro
    ? nombreDelRegistro(registro)
    : contenido
      ? (id ?? "")
      : "";

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
        // Con la lista delante no hay registro que resumir, pero tampoco se está
        // cargando: `null` aquí pinta «Cargando…» para siempre.
        fila={registro ?? (contenido ? {} : null)}
        volverA={{ a: `/m/${rutaDelModulo}`, titulo: modulo.titulo, id }}
        cambioDeEstado={
          recurso?.servicio && ruta
            ? { servicio: recurso.servicio, ruta, alCambiar: () => cargar() }
            : undefined
        }
        acciones={
          fila && !editando ? (
            <BotonesDeRegistro
              puedeEditar={puedeEditar && !contenido}
              puedeBorrar={puedeBorrar}
              borrado={borrado}
              alEditar={() => setEditando(true)}
              alBorrar={() => setConfirmando(true)}
              destacadas={recurso?.destacadas}
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

      {/* El formulario de la acción elegida en «Más». Va aquí, pegado al panel
          que la ofrece, y no dentro de una pestaña: la acción es sobre el
          registro, no sobre lo que se esté mirando de él. */}
      {!editando ? (
        <>
          <AsistenteIA
            acciones={acciones}
            abierta={accionAbierta}
            alElegir={setAccionAbierta}
          />
          {/* Convertir un lead no es el formulario del contrato —que pide un
              cliente que ya exista—: es el paso entero, con el cliente y el
              contacto propuestos. Ver `ConvertirLead`. */}
          {tipo === "lead" && id && accionAbierta?.clave === "convertir" ? (
            <ConvertirLead
              leadId={id}
              lead={(registro ?? {}) as Record<string, string | null>}
              alCancelar={() => setAccionAbierta(null)}
            />
          ) : null}
          <Acciones
            acciones={acciones}
            recurso={recurso}
            servicio={recurso?.servicio ?? ""}
            abierta={
              tipo === "lead" && accionAbierta?.clave === "convertir"
                ? null
                : accionAbierta
            }
            alCambiarAbierta={setAccionAbierta}
            alTerminar={cargar}
            registro={registro}
          />
        </>
      ) : null}

      {/* Lo que un objeto concreto necesita y la ficha genérica no puede
          deducir del contrato: el PUT de las credenciales de una conexión
          (CRM-00.01.04.08) y la sala de una reunión (CRM-06.01.03.10). Va
          encima de las pestañas para que se vea en cualquiera: escondido en
          una que no es la de entrada, cuenta como no hecho. */}
      {/* La probabilidad de convertir, del modelo entrenado con los leads
          convertidos y descartados (CRM-02.01.02.02). */}
      {!editando && tipo === "lead" && id ? (
        <PrediccionDelRegistro objeto="lead" id={id} />
      ) : null}
      {/* Las resoluciones de la devolución y anotar el abono, que cuelga de
          la resolución y no de la devolución (CRM-04.05.01.02). */}
      {!editando && tipo === "devolucion" && id ? (
        <ResolucionesDeDevolucion devolucionId={id} />
      ) : null}
      {!editando && tipo === "conexion" && id ? (
        <CredencialesDeConexion conexionId={id} />
      ) : null}
      {!editando && tipo === "actividad" && id && fila?.tipo === "reunion" ? (
        <ReunionEnLinea actividadId={id} actividad={fila} alCrear={cargar} />
      ) : null}
      {/* Transcribir y resumir la llamada o la reunión, con sus compromisos
          convertidos en tareas al confirmarlos (CRM-01.02.01.05, .06). */}
      {!editando &&
      tipo === "actividad" &&
      id &&
      ["llamada", "reunion", "visita"].includes(String(fila?.tipo ?? "")) ? (
        <TranscripcionDeReunion actividadId={id} />
      ) : null}
      {/* La atribución de la venta del lead, con el importe de su oportunidad
          (CRM-02.02.01.06), y la plantilla montada con los datos de un contacto
          real en varios clientes de correo (CRM-02.03.01.06). */}
      {/* La puntuación de marketing: calificación, ejes y el porqué
          (CRM-02.01.02.01 a .05). */}
      {!editando && tipo === "lead" && id ? (
        <PuntuacionDelLead leadId={id} alCambiar={cargar} />
      ) : null}
      {!editando && tipo === "lead" && id ? (
        <AtribucionDeLead leadId={id} lead={fila} />
      ) : null}
      {/* Por qué cayó donde cayó y por dónde llegó: las reglas de reparto
          evaluadas y sus toques en orden. */}
      {!editando && tipo === "lead" && id ? (
        <RepartoYOrigenDelLead leadId={id} />
      ) : null}
      {/* Lo que quiere recibir y a qué hora abre: se pregunta delante del
          contacto, antes de escribirle o de meterlo en una campaña. */}
      {!editando && tipo === "contacto" && id && fila ? (
        <CorreoDelContacto
          contactoId={id}
          email={typeof fila.email === "string" ? fila.email : ""}
        />
      ) : null}
      {/* Con todas las reglas del objeto juntas, quién gana hoy. */}
      {!editando &&
      tipo === "regla_convivencia" &&
      typeof fila?.objeto === "string" ? (
        <QuienMandaSobre objeto={fila.objeto} />
      ) : null}
      {/* Un activo de marketing: si su versión se puede publicar ya, y qué
          paso de aprobación falta. */}
      {!editando && tipo === "activo_marketing" && id && fila ? (
        <SePuedePublicar
          objeto={tipo}
          objetoId={id}
          version={typeof fila.version === "number" ? fila.version : 1}
        />
      ) : null}
      {/* Lo que ve un agente de fuera en esta exposición. */}
      {!editando &&
      tipo === "exposicion_mcp" &&
      typeof fila?.clave === "string" ? (
        <HerramientasDeExposicion clave={fila.clave} />
      ) : null}
      {/* La renovación del contrato, revisada sólo para él (CRM-03.03.02.10). */}
      {!editando && tipo === "contrato" && id ? (
        <RenovacionDeContrato
          contratoId={id}
          contrato={fila}
          alRevisar={() => cargar()}
        />
      ) : null}
      {/* Notas, ficheros y conversaciones de la suite vinculados por
          referencia (CRM-06.01.03.08, .09, .12). En cualquier registro: el
          vínculo es al registro, no a un tipo concreto. */}
      {/* Llamar al contacto con la telefonía conectada (CRM-03.03.01.05). */}
      {!editando && tipo === "contacto" && id && fila ? (
        <Marcador
          contactoId={id}
          telefonos={[String(fila.telefono ?? ""), String(fila.movil ?? "")]}
        />
      ) : null}
      {!editando && tipo && id && fila ? (
        <ReferenciasDeSuite objeto={tipo} objetoId={id} />
      ) : null}
      {!editando &&
      recurso?.listar === "/api/v1/correo/plantillas" &&
      typeof fila?.clave === "string" ? (
        <VistaPreviaCorreo
          clave={fila.clave}
          idioma={typeof fila.idioma === "string" ? fila.idioma : "es"}
        />
      ) : null}
      {/* Variantes del asunto generadas con el modelo y revisadas por una
          persona (CRM-02.04.01.04). */}
      {!editando &&
      recurso?.listar === "/api/v1/correo/plantillas" &&
      typeof fila?.clave === "string" ? (
        <VariantesDeCopy
          objeto="plantilla_correo"
          objetoRef={fila.clave}
          textoBase={typeof fila.asunto === "string" ? fila.asunto : ""}
        />
      ) : null}

      {confirmando ? (
        <ConfirmarBorrado
          borrado={borrado}
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

      <PestanasDeFicha
        tipo={tipo}
        id={id ?? ""}
        etiqueta={t("ficha.secciones")}
        pestanas={pestanas.map((p) => ({ clave: p, nombre: t(`ficha.${p}`) }))}
        activa={activa}
        alElegir={(clave) => setPestana(clave as Pestana)}
      />

      <div className="mt-4">
        {fallo && !fila ? (
          <>
            <Fallo error={fallo} reintentar={() => cargar()} />
            {/* Un registro que ya no está en la tabla viva puede estar
                archivado: aquí se dice dónde está y se puede devolver. */}
            {recurso?.servicio && id ? (
              <div className="mt-3">
                <ArchivadoDelRegistro servicio={recurso.servicio} id={id} />
              </div>
            ) : null}
          </>
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
            {activa === "detalles" && contenido ? (
              <Tabla filas={contenido} titulo={nombre} />
            ) : activa === "detalles" ? (
              <DetallesDelRegistro
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
                  <Adjuntos key={adjuntosVersion} tipo={tipo} id={id} />
                ) : null}
                {/* Generar un documento desde este registro: sólo sale en los
                    tipos que la configuración del servidor admite. El PDF
                    llega a «Adjuntos», que se recarga al terminar. */}
                {puedeTener("adjuntos") && id ? (
                  <GenerarDocumento
                    objeto={tipo}
                    id={id}
                    alGenerar={() => setAdjuntosVersion((v) => v + 1)}
                  />
                ) : null}
                {puedeTener("documentos") ? (
                  <Documentos tipo={tipo} id={id} nombre={nombre} />
                ) : null}
                {/* Lo archivado que cuelga de este registro (CRM-07.03.01.02). */}
                {recurso?.servicio ? (
                  <ArchivadoDelRegistro servicio={recurso.servicio} id={id} />
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
                <ReunionEnLinea objeto={tipo} objetoId={id} alCrear={cargar} />
                <PreguntarSobreEsto objeto={tipo} objetoId={id} />
              </>
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
        <p className="mb-2 text-dato text-ink-faint">
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
            <CarpetaDelRegistro
              tipo={tipo}
              id={id}
              nombreDelRegistro={nombre}
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
      <h3 className="mb-2 text-titulin font-medium text-ink">
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
                className="flex w-full items-center justify-between gap-2 text-left text-titulin text-ink"
              >
                <span className="truncate">{titulo}</span>
                <span className="shrink-0 text-dato text-ink-muted">
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
      <h3 className="mb-2 text-titulin font-medium text-ink">
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
          className="flex-1 rounded border border-ink-dim/60 bg-paper px-2 py-1 text-titulin text-ink"
        />
        <button
          type="button"
          onClick={() => void buscar()}
          disabled={buscando || texto.trim().length < 2}
          className="rounded border border-ink-dim/60 px-3 py-1 text-titulin text-ink disabled:opacity-50"
        >
          {buscando ? t("ficha.buscando") : t("ficha.buscar")}
        </button>
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      {resultados !== null && resultados.length === 0 ? (
        <p className="mt-2 text-dato text-ink-faint">
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
              <span className="truncate text-titulin text-ink">
                {String(doc.title ?? doc.titulo ?? doc.id ?? "")}
              </span>
              <button
                type="button"
                onClick={() => void enlazar(doc)}
                className="shrink-0 rounded border border-ink-dim/60 px-2 py-0.5 text-dato text-ink"
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
            className="mt-2 text-rotulo text-ink-muted"
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
