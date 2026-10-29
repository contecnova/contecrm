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
import { Link, useNavigate, useParams } from "react-router-dom";

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
import { Acciones } from "@/componentes/Acciones";
import { RegistrarActividad } from "@/componentes/RegistrarActividad";
import { SubColecciones } from "@/componentes/SubColecciones";
import { accionesDe, subColeccionesDe } from "@/lib/acciones";
import { useSuperficie } from "@/lib/permisos";
import { ErrorApi, llamar, salvoCancelacion, subir } from "@/lib/api";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";
import { CabeceraPagina } from "@/componentes/Pagina";
import { AprobacionDeDocumento } from "@/paginas/Aprobaciones";

type Pestana = "datos" | "adjuntos" | "comentarios" | "documentos";

export function Ficha() {
  const { t } = useTranslation();
  const { ruta = "", tipo = "", id = "" } = useParams();
  const modulo = moduloDe(ruta);
  const [pestana, setPestana] = useState<Pestana>("datos");
  // El nombre lo pone la pestaña de datos en cuanto carga el registro: el
  // título era el UUID, así que la ficha de una oportunidad no decía cuál era.
  const [nombre, setNombre] = useState("");
  const { superficie } = useSuperficie();

  // Solo las pestañas que este objeto puede tener. Pedir adjuntos de algo que
  // no los admite no sale como «aquí no hay»: sale como un 404 en la consola y
  // una pestaña que nunca carga, y pasaba en 81 de 85 fichas.
  const pestanas = useMemo<Pestana[]>(() => {
    const puede = (cual: "adjuntos" | "comentarios" | "documentos") =>
      // Mientras la superficie no ha llegado se ofrecen todas: esconderlas y
      // hacerlas aparecer un segundo después mueve los botones bajo el cursor.
      !superficie?.objetos || superficie.objetos[cual].includes(tipo);
    return [
      "datos",
      ...(["adjuntos", "comentarios", "documentos"] as const).filter(puede),
    ];
  }, [superficie, tipo]);

  // Si la pestaña abierta deja de estar —la superficie llega y dice que este
  // objeto no admite adjuntos— se vuelve a datos, en vez de dejar el contenido
  // en blanco debajo de una barra donde ese botón ya no aparece.
  const activa: Pestana = pestanas.includes(pestana) ? pestana : "datos";
  const recursoAbierto = modulo ? recursoDe(modulo, tipo) : undefined;

  if (!modulo) return <Vacio />;

  return (
    <>
      {/* Si el registro no tiene con qué llamarse, el título es **el nombre de
          lo que es**, no su identificador: un UUID de treinta y seis caracteres
          como encabezado no dice qué se está mirando y no hay forma de leerlo.
          El identificador se queda debajo, corto, para poder citarlo. */}
      <CabeceraPagina
        titulo={nombre || recursoAbierto?.nombre || modulo.titulo}
        icono="description"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <Link to={`/m/${ruta}`} className="text-accent hover:underline">
              {modulo.titulo}
            </Link>
            <span className="font-mono text-3xs text-ink-faint" title={id}>
              {id.slice(0, 8)}…
            </span>
          </span>
        }
      />

      <nav
        aria-label={t("ficha.secciones")}
        className="mt-3 flex flex-wrap gap-1"
      >
        {pestanas.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setPestana(p)}
            aria-current={p === activa ? "page" : undefined}
            className={`rounded-lg px-3 py-1.5 text-xs ${
              p === activa
                ? "bg-paper-light text-ink"
                : "text-ink-muted hover:bg-paper-light"
            }`}
          >
            {t(`ficha.${p}`)}
          </button>
        ))}
      </nav>

      <div className="mt-4">
        {activa === "datos" ? (
          <Datos
            modulo={ruta}
            id={id}
            objeto={tipo}
            alSaberNombre={setNombre}
          />
        ) : null}
        {activa === "adjuntos" ? <Adjuntos tipo={tipo} id={id} /> : null}
        {activa === "comentarios" ? <Comentarios tipo={tipo} id={id} /> : null}
        {activa === "documentos" ? (
          <Documentos tipo={tipo} id={id} nombre={nombre} />
        ) : null}
      </div>
    </>
  );
}

function Datos({
  modulo,
  id,
  objeto,
  alSaberNombre,
}: {
  modulo: string;
  id: string;
  /** Tipo del registro (`cuenta`, `oportunidad`…), para colgarle la actividad. */
  objeto: string;
  /** Sube el nombre del registro para que lo use el título de la ficha. */
  alSaberNombre: (nombre: string) => void;
}) {
  const { t } = useTranslation();
  const navegar = useNavigate();
  const { superficie, tiene } = useSuperficie();
  const m = moduloDe(modulo);
  // Por el objeto de la dirección y no `recursos[0]`: un módulo tiene varias
  // pestañas y con la primera se pedía el registro contra la ruta equivocada,
  // así que solo se podía abrir una fila de todo el módulo.
  const recurso = m ? recursoDe(m, objeto) : undefined;
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
   * pestañas de arriba. Es la regla de la casa para las acciones: un botón que
   * aparece por defecto y luego resulta que no tocaba es un botón que alguien
   * ya ha pulsado.
   */
  const seHablaConAlguien = Boolean(
    objeto && superficie?.objetos?.actividades?.includes(objeto),
  );
  const [fila, setFila] = useState<Record<string, unknown> | null>(null);
  const [retenidos, setRetenidos] = useState<string[]>([]);
  const [tapados, setTapados] = useState<string[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);

  // Al cambiar de registro se sale de edición y se cancela la confirmación
  // pendiente. Esta pantalla atiende a `/m/:ruta/:tipo/:id`: ir de una ficha a
  // otra **no la desmonta**, así que sin esto se abría la siguiente ya en modo
  // edición —con los datos de la anterior todavía en el formulario— y un
  // «¿seguro que quieres borrar?» a medias se quedaba apuntando al registro
  // nuevo. Borrar el que no era está a un clic de ahí.
  useEffect(() => {
    setEditando(false);
    setConfirmando(false);
  }, [modulo, objeto, id]);

  const { ruta, puedeEditar, puedeBorrar } = useEdicion(recurso, id);
  // Todo lo que el servidor admite hacer con este registro, leído del contrato.
  // Son 144 en el sistema y ninguna se escribe a mano aquí.
  const acciones = useMemo(
    () => (recurso ? accionesDe(superficie, recurso.listar, id, tiene) : []),
    [superficie, recurso, id, tiene],
  );
  // Y lo que cuelga de él: líneas, equipo, direcciones, identificadores. Son
  // 196 en el sistema y ninguna se alcanzaba.
  const paneles = useMemo(
    () =>
      recurso ? subColeccionesDe(superficie, recurso.listar, id, tiene) : [],
    [superficie, recurso, id, tiene],
  );
  const cargar = useCallback(
    (signal?: AbortSignal) => {
      if (!ruta) return;
      llamar<Record<string, unknown>>(ruta, { signal })
        .then((r) => {
          setFila(r.datos);
          setRetenidos(r.retenidos);
          setTapados(r.enmascarados);
          alSaberNombre(nombreDelRegistro(r.datos));
        })
        .catch(salvoCancelacion(setFallo));
    },
    [ruta, alSaberNombre],
  );

  useEffect(() => {
    const control = new AbortController();
    cargar(control.signal);
    return () => control.abort();
  }, [cargar]);

  async function borrar() {
    setEnviando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      // Se vuelve al listado: quedarse en la ficha de algo que ya no existe
      // enseñaría un registro fantasma hasta que alguien recargara.
      navegar(`/m/${modulo}`);
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setEnviando(false);
    }
  }

  if (fallo && !fila)
    return <Fallo error={fallo} reintentar={() => cargar()} />;
  if (!fila) return <Cargando />;

  return (
    <>
      {!editando ? (
        <>
          <Acciones
            acciones={acciones}
            servicio={recurso?.servicio ?? ""}
            alTerminar={cargar}
          />
          {/* Apuntar una llamada o un correo sobre este registro sin salir de
              aquí: antes obligaba a irse a Actividades y teclear a mano el
              identificador para que quedara colgado, y eso no lo hace nadie dos
              veces. */}
          {seHablaConAlguien ? (
            <RegistrarActividad
              objeto={objeto}
              objetoId={id}
              alRegistrar={cargar}
            />
          ) : null}
          {/* Y preguntar sobre ESTE registro (CRM-05.01.04.09). La pregunta se
              hace aquí, delante del dato, que es donde se le ocurre a alguien;
              obligar a irse a la pantalla de explotación y volver a escribir de
              qué cuenta se habla es como se deja de preguntar. */}
          {seHablaConAlguien ? (
            <PreguntarSobreEsto objeto={objeto} objetoId={id} />
          ) : null}
        </>
      ) : null}

      {!editando ? (
        <div className="mb-3">
          <BotonesDeRegistro
            puedeEditar={puedeEditar}
            puedeBorrar={puedeBorrar}
            alEditar={() => setEditando(true)}
            alBorrar={() => setConfirmando(true)}
          />
        </div>
      ) : null}

      {confirmando ? (
        <ConfirmarBorrado
          enviando={enviando}
          alBorrar={() => void borrar()}
          alCancelar={() => setConfirmando(false)}
        />
      ) : null}

      {fallo ? (
        <div className="mb-3">
          <Fallo error={fallo} />
        </div>
      ) : null}

      {editando && recurso ? (
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
        // Los datos como ficha, no como una tabla de una sola fila: una tabla
        // horizontal de veinte columnas para UN registro obliga a desplazarse
        // para leer sus propios campos.
        <>
          <dl className="card grid gap-x-8 gap-y-3 p-4 sm:grid-cols-2">
            {Object.entries(fila)
              .filter(
                ([clave]) =>
                  clave !== "campos" && !esIdentificadorTecnico(clave),
              )
              .map(([clave, valor]) => (
                <Campo key={clave} clave={clave} valor={valor} />
              ))}
          </dl>

          {/* Los identificadores, detrás de un desplegable. Ocupaban la mitad
              de la ficha y no dicen nada a quien la mira, pero quien abre una
              incidencia de soporte los necesita enteros. */}
          <details className="mt-2">
            <summary className="cursor-pointer text-3xs text-ink-faint">
              {t("ficha.identificadores")}
            </summary>
            <dl className="card mt-2 grid gap-x-8 gap-y-2 p-4 sm:grid-cols-2">
              {Object.entries(fila)
                .filter(([clave]) => esIdentificadorTecnico(clave))
                .map(([clave, valor]) => (
                  <Campo
                    key={clave}
                    clave={clave}
                    valor={valor}
                    monoespaciado
                  />
                ))}
            </dl>
          </details>
        </>
      )}
      <Retenidos campos={retenidos} enmascarados={tapados} />

      {/* Qué ha cambiado en ESTE registro, campo a campo. Plegado y cargado
          sólo al abrirlo: es trazabilidad, no contenido, y pedirlo en cada
          ficha abierta sería una llamada más por registro que casi nadie mira.
          Pero cuando hace falta es lo primero que se pregunta —«esto antes no
          decía esto»—, y hasta el 29-10-2026 se escribía y no lo devolvía
          ninguna ruta. */}
      {objeto && recurso?.servicio ? (
        <HistorialDeCampos
          servicio={recurso.servicio}
          objeto={objeto}
          objetoId={id}
        />
      ) : null}

      {/* Y cómo estaba el registro ENTERO en un momento dado, para los objetos
          que tienen el rastro completo encendido. El historial de campos dice
          qué cambió; no dice cómo era el conjunto, y reconstruirlo a mano
          encadenando cambios sale mal en cuanto hay una fusión por medio. */}
      {objeto && recurso?.servicio ? (
        <ComoEstabaEsto
          servicio={recurso.servicio}
          objeto={objeto}
          objetoId={id}
        />
      ) : null}

      {!editando ? (
        <SubColecciones
          paneles={paneles}
          servicio={recurso?.servicio ?? ""}
          id={id}
        />
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
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-3xs text-ink-faint">{humanizar(clave)}</dt>
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
    <>
      <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-ink-dim/60 px-3 py-1.5 text-2xs text-ink-muted hover:bg-paper-light">
        {subiendo ? t("ficha.subiendo") : t("ficha.subir")}
        <input
          type="file"
          className="sr-only"
          disabled={subiendo}
          onChange={(e) => void elegir(e.target.files?.[0])}
        />
      </label>
      {/* Subir un adjunto cambia la lista sin decir nada: quien no ve la
          pantalla no se entera de que ha terminado (CRM-06.02.01.05). */}
      <p className="sr-only" role="status">
        {subiendo ? t("ficha.subiendo") : t("ficha.subido")}
      </p>
      {fallo ? (
        <div className="mt-3">
          <Fallo error={fallo} />
        </div>
      ) : null}
      <div className="mt-3">
        {filas === null ? (
          <Cargando />
        ) : filas.length === 0 ? (
          <Vacio />
        ) : (
          <Tabla
            filas={filas}
            columnas={["nombre", "tipo_mime", "tamano", "version", "analisis"]}
            titulo={t("ficha.adjuntos")}
          />
        )}
      </div>
    </>
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
          <Vacio />
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

  useEffect(() => {
    const control = new AbortController();
    llamar<Record<string, unknown>[]>(`/api/v1/documentos/${tipo}/${id}`, {
      signal: control.signal,
    })
      .then((r) => setFilas(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [tipo, id, recargar]);

  if (fallo) return <Fallo error={fallo} />;
  if (filas === null) return <Cargando />;
  return (
    <>
      {/* Se dice de dónde sale el estado real: sin esta línea, alguien
          construiría un informe sobre el título creyendo que está al día. El
          documento vive en el gestor, aquí está el enlace y el contexto. */}
      <p className="mb-2 text-2xs text-ink-faint">
        {t("ficha.documentosIntro")}
      </p>
      {filas.length === 0 ? (
        <Vacio />
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
export function PreguntarSobreEsto({ objeto, objetoId }: { objeto: string; objetoId: string }) {
  const { t } = useTranslation();
  const [pregunta, setPregunta] = useState("");
  const [salida, setSalida] = useState<{ pregunta?: string; filtro?: string } | null>(null);
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
          <p className="mt-2 text-3xs text-ink-muted" data-testid="pregunta-en-contexto">
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
    <details className="mt-3" onToggle={(e) => setAbierto(e.currentTarget.open)}>
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
    llamar<Reconstruido>(
      `/api/v1/${servicio}/rastro/${objeto}/${objetoId}`,
      { signal: control.signal },
    )
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
        <p className="mt-2 text-2xs text-ink-muted">{t("ficha.sinRastroCompleto")}</p>
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
          <p className={cuadra.cuadra ? "text-2xs text-success" : "text-2xs text-danger"}>
            {cuadra.cuadra ? t("ficha.cuadra") : t("ficha.noCuadra")}
          </p>
          <p className="mt-1 text-3xs text-ink-muted">{cuadra.que_significa}</p>
          {(cuadra.diferencias ?? []).length > 0 ? (
            <ul className="mt-1 divide-y divide-ink-dim/30">
              {(cuadra.diferencias ?? []).map((d) => (
                <li key={d.campo} className="flex flex-wrap items-baseline gap-x-2 py-1 text-3xs">
                  <span className="font-medium text-ink">{d.campo}</span>
                  <span className="text-ink-faint">{String(d.reconstruido ?? "—")}</span>
                  <span className="text-ink-muted">≠ {String(d.vivo ?? "—")}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}
