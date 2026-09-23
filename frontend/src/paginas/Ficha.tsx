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

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Cargando, Error as Fallo, Retenidos, Vacio } from "@/componentes/Estados";
import { Tabla } from "@/componentes/Tabla";
import { llamar, subir } from "@/lib/api";
import { moduloDe } from "@/lib/modulos";
import { CabeceraPagina } from "@/componentes/Pagina";

type Pestana = "datos" | "adjuntos" | "comentarios" | "documentos";

export function Ficha() {
  const { t } = useTranslation();
  const { ruta = "", tipo = "", id = "" } = useParams();
  const modulo = moduloDe(ruta);
  const [pestana, setPestana] = useState<Pestana>("datos");

  if (!modulo) return <Vacio />;

  return (
    <>
      <CabeceraPagina
        titulo={<span className="font-mono">{id}</span>}
        icono="description"
        entradilla={
          <Link to={`/m/${ruta}`} className="text-accent-text hover:underline">
            {modulo.titulo}
          </Link>
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
        {pestana === "datos" ? <Datos modulo={ruta} id={id} /> : null}
        {pestana === "adjuntos" ? <Adjuntos tipo={tipo} id={id} /> : null}
        {pestana === "comentarios" ? <Comentarios tipo={tipo} id={id} /> : null}
        {pestana === "documentos" ? <Documentos tipo={tipo} id={id} /> : null}
      </div>
    </>
  );
}

function Datos({ modulo, id }: { modulo: string; id: string }) {
  const m = moduloDe(modulo);
  const recurso = m?.recursos[0];
  const [fila, setFila] = useState<Record<string, unknown> | null>(null);
  const [retenidos, setRetenidos] = useState<string[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    if (!recurso) return;
    const control = new AbortController();
    llamar<Record<string, unknown>>(`${recurso.listar}/${id}`, { signal: control.signal })
      .then((r) => {
        setFila(r.datos);
        setRetenidos(r.retenidos);
      })
      .catch(setFallo);
    return () => control.abort();
  }, [recurso, id]);

  if (fallo) return <Fallo error={fallo} />;
  if (!fila) return <Cargando />;
  return (
    <>
      <Tabla filas={[fila]} titulo="datos" />
      <Retenidos campos={retenidos} />
    </>
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
      .catch(setFallo);
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
