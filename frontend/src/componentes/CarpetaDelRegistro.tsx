/**
 * La carpeta del corpus donde viven los documentos de este registro.
 *
 * El panel de documentos enseñaba lo ENLAZADO, y el gestor documental guarda
 * además una carpeta por registro —la plantilla `DMS_CARPETA_PLANTILLA`— donde
 * se colocan. Lo que había en esa carpeta y no estaba enlazado, quién podía
 * entrar y por qué, y buscar sólo dentro de ella eran cuatro rutas servidas sin
 * ninguna pantalla.
 *
 * Tres decisiones:
 *
 * **Se abre con un botón y sin crear nada.** Mirar la carpeta pregunta con
 * `crear=false`: abrir una ficha no puede dejar carpetas vacías en el gestor.
 * La carpeta nace al enlazar el primer documento, que ya la crea el servidor.
 *
 * **Todo va con la identidad de quien mira.** Una subcarpeta denegada no
 * aparece; no es un fallo, es el permiso. Por eso el porqué del permiso se
 * pide para la carpeta abierta, una vez, y no por fila.
 *
 * **«Buscar aquí» y «buscar en el corpus» son dos preguntas.** La de abajo del
 * panel busca en todo el corpus para enlazar; ésta, sólo en la rama abierta.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";

type Fila = Record<string, unknown>;

function nombre(f: Fila): string {
  return String(f.name ?? f.nombre ?? f.title ?? f.titulo ?? f.id ?? "—");
}

/** El porqué de un permiso, que el gestor da como código y aquí se traduce. */
function permisoLegible(
  valor: unknown,
  t: (k: string, o?: Record<string, unknown>) => string,
): string {
  if (typeof valor === "boolean")
    return valor ? t("carpetaRegistro.si") : t("carpetaRegistro.no");
  if (valor && typeof valor === "object") {
    const v = valor as { allowed?: unknown; reason?: unknown };
    const si = v.allowed === true;
    const motivo =
      typeof v.reason === "string"
        ? t(`carpetaRegistro.motivos.${v.reason}`, { defaultValue: v.reason })
        : "";
    return `${si ? t("carpetaRegistro.si") : t("carpetaRegistro.no")}${motivo ? ` — ${motivo}` : ""}`;
  }
  return String(valor ?? "—");
}

export function CarpetaDelRegistro({
  tipo,
  id,
  nombreDelRegistro,
}: {
  tipo: string;
  id: string;
  nombreDelRegistro: string;
}) {
  const { t } = useTranslation();
  const [mirar, setMirar] = useState(false);
  const [raiz, setRaiz] = useState<{
    carpeta_id: string;
    existe: boolean;
  } | null>(null);
  // El camino abierto: la raíz del registro y las subcarpetas en las que se
  // ha entrado. Volver es quitar del final.
  const [camino, setCamino] = useState<{ id: string; nombre: string }[]>([]);
  const [subcarpetas, setSubcarpetas] = useState<Fila[] | null>(null);
  const [documentos, setDocumentos] = useState<Fila[] | null>(null);
  const [permisos, setPermisos] = useState<Record<string, unknown> | null>(
    null,
  );
  const [texto, setTexto] = useState("");
  const [resultados, setResultados] = useState<Fila[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    if (!mirar) return;
    const control = new AbortController();
    setFallo(null);
    llamar<{ carpeta_id: string; existe: boolean }>(
      `/api/v1/documentos/${tipo}/${id}/carpeta?etiqueta=${encodeURIComponent(nombreDelRegistro || id)}&crear=false`,
      { signal: control.signal },
    )
      .then((r) => {
        setRaiz(r.datos);
        setCamino(
          r.datos.existe
            ? [{ id: r.datos.carpeta_id, nombre: nombreDelRegistro || id }]
            : [],
        );
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [mirar, tipo, id, nombreDelRegistro]);

  const actual = camino[camino.length - 1]?.id ?? "";

  useEffect(() => {
    if (!actual) return;
    const control = new AbortController();
    setSubcarpetas(null);
    setDocumentos(null);
    setPermisos(null);
    setResultados(null);
    const carpeta = encodeURIComponent(actual);
    llamar<{ items: Fila[] }>(`/api/v1/documentos/carpetas?padre=${carpeta}`, {
      signal: control.signal,
    })
      .then((r) => setSubcarpetas(r.datos.items ?? []))
      .catch(salvoCancelacion(setFallo));
    llamar<{ items: Fila[] }>(
      `/api/v1/documentos/carpetas/${carpeta}/documentos`,
      { signal: control.signal },
    )
      .then((r) => setDocumentos(r.datos.items ?? []))
      .catch(salvoCancelacion(setFallo));
    llamar<{ permisos: Record<string, unknown> }>(
      `/api/v1/documentos/carpetas/${carpeta}/permisos`,
      { signal: control.signal },
    )
      .then((r) => setPermisos(r.datos.permisos ?? {}))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [actual]);

  const buscar = useCallback(async () => {
    if (!texto.trim() || !actual) return;
    setFallo(null);
    try {
      const r = await llamar<{ resultados: Fila[] }>(
        `/api/v1/documentos/buscar-en-rama?q=${encodeURIComponent(texto.trim())}&carpeta=${encodeURIComponent(actual)}`,
      );
      setResultados(r.datos.resultados ?? []);
    } catch (e) {
      setFallo(e);
    }
  }, [texto, actual]);

  if (!mirar)
    return (
      <section className="mt-6 border-t border-ink-dim/30 pt-4">
        <button
          type="button"
          className="btn-secondary"
          onClick={() => setMirar(true)}
        >
          {t("carpetaRegistro.ver")}
        </button>
      </section>
    );

  return (
    <section className="mt-6 border-t border-ink-dim/30 pt-4">
      <h3 className="mb-2 text-titulin font-medium text-ink">
        {t("carpetaRegistro.titulo")}
      </h3>
      {fallo ? <Fallo error={fallo} /> : null}
      {raiz === null && !fallo ? <Cargando /> : null}
      {raiz && !raiz.existe ? (
        <p className="text-dato text-ink-faint">
          {t("carpetaRegistro.sinCarpeta")}
        </p>
      ) : null}
      {actual ? (
        <>
          <nav
            aria-label={t("carpetaRegistro.camino")}
            className="mb-2 flex flex-wrap gap-1 text-dato"
          >
            {camino.map((c, i) => (
              <button
                key={c.id}
                type="button"
                className={i === camino.length - 1 ? "text-ink" : "text-accent"}
                onClick={() => setCamino(camino.slice(0, i + 1))}
              >
                {i > 0 ? "/ " : ""}
                {c.nombre}
              </button>
            ))}
          </nav>
          {subcarpetas && subcarpetas.length > 0 ? (
            <ul className="mb-2 flex flex-wrap gap-1">
              {subcarpetas.map((s) => (
                <li key={String(s.id)}>
                  <button
                    type="button"
                    className="chip-dato"
                    onClick={() =>
                      setCamino([
                        ...camino,
                        { id: String(s.id), nombre: nombre(s) },
                      ])
                    }
                  >
                    {nombre(s)}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {documentos === null ? (
            <Cargando />
          ) : documentos.length === 0 ? (
            <Vacio compacto />
          ) : (
            <ul className="lista-acotada flex flex-col gap-0.5 pr-1">
              {documentos.map((d, i) => (
                <li key={String(d.id ?? i)} className="text-dato text-ink">
                  {nombre(d)}
                </li>
              ))}
            </ul>
          )}
          {permisos && Object.keys(permisos).length > 0 ? (
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-rotulo">
              {Object.entries(permisos).map(([accion, valor]) => (
                <div key={accion} className="contents">
                  <dt className="text-ink-muted">
                    {t(`carpetaRegistro.acciones.${accion}`, {
                      defaultValue: accion,
                    })}
                  </dt>
                  <dd className="text-ink">{permisoLegible(valor, t)}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          <div className="mt-3 flex gap-2">
            <input
              type="search"
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void buscar();
              }}
              placeholder={t("carpetaRegistro.buscarAqui")}
              aria-label={t("carpetaRegistro.buscarAqui")}
              className="input-base flex-1"
            />
            <button
              type="button"
              className="btn-secondary"
              disabled={!texto.trim()}
              onClick={() => void buscar()}
            >
              {t("carpetaRegistro.buscar")}
            </button>
          </div>
          {resultados !== null ? (
            resultados.length === 0 ? (
              <p className="mt-2 text-dato text-ink-faint">
                {t("carpetaRegistro.sinResultados")}
              </p>
            ) : (
              <ul className="lista-acotada mt-2 flex flex-col gap-0.5 pr-1">
                {resultados.map((d, i) => (
                  <li key={String(d.id ?? i)} className="text-dato text-ink">
                    {nombre(d)}
                  </li>
                ))}
              </ul>
            )
          ) : null}
        </>
      ) : null}
    </section>
  );
}
