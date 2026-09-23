/**
 * La ficha de un registro: sus datos y lo que cuelga de él (CRM-07.04.03.25).
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

import { Cargando, Error as Fallo, Retenidos, Vacio } from "@/componentes/Estados";
import { Tabla } from "@/componentes/Tabla";
import { Formulario } from "@/componentes/Formulario";
import { camposDe, contratoDe, type CampoEsquema } from "@/lib/contrato";
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
import { usePuedeOperar, useSuperficie } from "@/lib/permisos";
import { llamar, salvoCancelacion, subir } from "@/lib/api";
import { moduloDe } from "@/lib/modulos";
import { CabeceraPagina } from "@/componentes/Pagina";

type Pestana = "datos" | "adjuntos" | "comentarios" | "documentos";

export function Ficha() {
  const { t } = useTranslation();
  const { ruta = "", tipo = "", id = "" } = useParams();
  const modulo = moduloDe(ruta);
  const [pestana, setPestana] = useState<Pestana>("datos");
  // El nombre lo pone la pestaña de datos en cuanto carga el registro: el
  // título era el UUID, así que la ficha de una oportunidad no decía cuál era.
  const [nombre, setNombre] = useState("");

  if (!modulo) return <Vacio />;

  return (
    <>
      <CabeceraPagina
        titulo={nombre || <span className="font-mono text-base">{id}</span>}
        icono="description"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <Link to={`/m/${ruta}`} className="text-accent hover:underline">
              {modulo.titulo}
            </Link>
            {nombre ? (
              <span className="font-mono text-3xs text-ink-faint" title={id}>
                {id.slice(0, 8)}…
              </span>
            ) : null}
          </span>
        }
      />

      <nav aria-label={t("ficha.secciones")} className="mt-3 flex flex-wrap gap-1">
        {(["datos", "adjuntos", "comentarios", "documentos"] as const).map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setPestana(p)}
            aria-current={p === pestana ? "page" : undefined}
            className={`rounded-lg px-3 py-1.5 text-xs ${
              p === pestana ? "bg-paper-light text-ink" : "text-ink-muted hover:bg-paper-light"
            }`}
          >
            {t(`ficha.${p}`)}
          </button>
        ))}
      </nav>

      <div className="mt-4">
        {pestana === "datos" ? (
          <Datos modulo={ruta} id={id} objeto={tipo} alSaberNombre={setNombre} />
        ) : null}
        {pestana === "adjuntos" ? <Adjuntos tipo={tipo} id={id} /> : null}
        {pestana === "comentarios" ? <Comentarios tipo={tipo} id={id} /> : null}
        {pestana === "documentos" ? <Documentos tipo={tipo} id={id} /> : null}
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
  const puedeOperar = usePuedeOperar();
  const { superficie, tiene } = useSuperficie();
  const m = moduloDe(modulo);
  const recurso = m?.recursos[0];
  const [fila, setFila] = useState<Record<string, unknown> | null>(null);
  const [retenidos, setRetenidos] = useState<string[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);
  const [campos, setCampos] = useState<CampoEsquema[] | null>(null);
  const [editando, setEditando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);

  const ruta = recurso ? `${recurso.listar}/${id}` : "";
  // Todo lo que el servidor admite hacer con este registro, leído del contrato.
  // Son 144 en el sistema y ninguna se escribe a mano aquí.
  const acciones = useMemo(
    () => (recurso ? accionesDe(superficie, recurso.listar, id, tiene) : []),
    [superficie, recurso, id, tiene],
  );
  // Y lo que cuelga de él: líneas, equipo, direcciones, identificadores. Son
  // 196 en el sistema y ninguna se alcanzaba.
  const paneles = useMemo(
    () => (recurso ? subColeccionesDe(superficie, recurso.listar, id, tiene) : []),
    [superficie, recurso, id, tiene],
  );
  const puedeEditar = Boolean(ruta) && puedeOperar("PATCH", ruta);
  const puedeBorrar = Boolean(ruta) && puedeOperar("DELETE", ruta);

  const cargar = useCallback(
    (signal?: AbortSignal) => {
      if (!ruta) return;
      llamar<Record<string, unknown>>(ruta, { signal })
        .then((r) => {
          setFila(r.datos);
          setRetenidos(r.retenidos);
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

  // Los campos que admite la MODIFICACIÓN, que no son los del alta: hay cosas
  // que se fijan al crear y no se cambian después, y ofrecerlas aquí sería
  // prometer una edición que el servidor rechaza.
  useEffect(() => {
    if (!recurso || !editando) return;
    let vivo = true;
    void contratoDe(recurso.servicio).then((documento) => {
      if (vivo) setCampos(camposDe(documento, plantillaFicha(ruta), "patch"));
    });
    return () => {
      vivo = false;
    };
  }, [recurso, editando, ruta]);

  async function guardar(valores: Record<string, unknown>) {
    setEnviando(true);
    try {
      await llamar(ruta, { metodo: "PATCH", cuerpo: valores });
      setEditando(false);
      cargar();
      setFallo(null);
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

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

  if (fallo && !fila) return <Fallo error={fallo} reintentar={() => cargar()} />;
  if (!fila) return <Cargando />;

  return (
    <>
      {!editando ? (
        <>
          <Acciones acciones={acciones} servicio={recurso?.servicio ?? ""} alTerminar={cargar} />
          {/* Apuntar una llamada o un correo sobre este registro sin salir de
              aquí: antes obligaba a irse a Actividades y teclear a mano el
              identificador para que quedara colgado, y eso no lo hace nadie dos
              veces. */}
          {objeto ? (
            <RegistrarActividad objeto={objeto} objetoId={id} alRegistrar={cargar} />
          ) : null}
        </>
      ) : null}

      {(puedeEditar || puedeBorrar) && !editando ? (
        <div className="mb-3 flex gap-2">
          {puedeEditar ? (
            <button type="button" onClick={() => setEditando(true)} className="btn-secondary">
              {t("ficha.editar")}
            </button>
          ) : null}
          {puedeBorrar ? (
            <button type="button" onClick={() => setConfirmando(true)} className="btn-danger">
              {t("ficha.eliminar")}
            </button>
          ) : null}
        </div>
      ) : null}

      {confirmando ? (
        // Se pregunta antes de borrar, y se dice qué se borra. Un borrado sin
        // confirmación es un borrado que alguien hará sin querer.
        <div className="card mb-3 border-danger/40 p-4" role="alertdialog" aria-label={t("ficha.eliminar")}>
          <p className="text-xs text-ink">{t("ficha.confirmarBorrado")}</p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => void borrar()}
              disabled={enviando}
              className="btn-danger"
            >
              {t("ficha.eliminarDeVerdad")}
            </button>
            <button type="button" onClick={() => setConfirmando(false)} className="btn-secondary">
              {t("modulo.cancelar")}
            </button>
          </div>
        </div>
      ) : null}

      {fallo ? (
        <div className="mb-3">
          <Fallo error={fallo} />
        </div>
      ) : null}

      {editando ? (
        <div className="card mb-3 p-4">
          {campos ? (
            <Formulario
              campos={campos}
              valores={fila}
              enviando={enviando}
              textoEnviar={t("ficha.guardar")}
              alEnviar={(v) => void guardar(v)}
            />
          ) : (
            <Cargando />
          )}
          <button
            type="button"
            onClick={() => setEditando(false)}
            className="btn-link mt-3"
          >
            {t("modulo.cancelar")}
          </button>
        </div>
      ) : (
        // Los datos como ficha, no como una tabla de una sola fila: una tabla
        // horizontal de veinte columnas para UN registro obliga a desplazarse
        // para leer sus propios campos.
        <>
          <dl className="card grid gap-x-8 gap-y-3 p-4 sm:grid-cols-2">
            {Object.entries(fila)
              .filter(([clave]) => clave !== "campos" && !esIdentificadorTecnico(clave))
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
                  <Campo key={clave} clave={clave} valor={valor} monoespaciado />
                ))}
            </dl>
          </details>
        </>
      )}
      <Retenidos campos={retenidos} />

      {!editando ? (
        <SubColecciones paneles={paneles} servicio={recurso?.servicio ?? ""} id={id} />
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
        {valor === null || valor === undefined || valor === "" ? (
          <span className="text-ink-faint">—</span>
        ) : typeof valor === "object" ? (
          JSON.stringify(valor)
        ) : (
          escalar(valor, clave)
        )}
      </dd>
    </div>
  );
}

/** `/api/v1/accounts/{id}` es la plantilla con la que el OpenAPI declara la ficha. */
function plantillaFicha(ruta: string): string {
  return ruta.replace(/\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i, "/{id}");
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
      const r = await llamar<Record<string, unknown>[]>(`/api/v1/comentarios/${tipo}/${id}`);
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

function Documentos({ tipo, id }: { tipo: string; id: string }) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Record<string, unknown>[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Record<string, unknown>[]>(`/api/v1/documentos/${tipo}/${id}`, {
      signal: control.signal,
    })
      .then((r) => setFilas(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [tipo, id]);

  if (fallo) return <Fallo error={fallo} />;
  if (filas === null) return <Cargando />;
  return (
    <>
      {/* Se dice de dónde sale el estado real: sin esta línea, alguien
          construiría un informe sobre el título creyendo que está al día. El
          documento vive en el gestor, aquí está el enlace y el contexto. */}
      <p className="mb-2 text-2xs text-ink-faint">{t("ficha.documentosIntro")}</p>
      {filas.length === 0 ? <Vacio /> : <Tabla filas={filas} titulo={t("ficha.documentos")} />}
    </>
  );
}
