/**
 * Conocimiento y autoservicio (CRM-07.04.03.19).
 *
 * **Lo publicado se distingue de lo que está en revisión, siempre.** Un artículo
 * a medias que se lee como bueno se copia y se pega en una respuesta a un
 * cliente, y ahí ya no hay quien lo recoja. Por eso el estado va al lado del
 * título y no en una pestaña aparte.
 *
 * Y se dice qué artículos ve el cliente en el portal: escribir para dentro y
 * escribir para fuera no es lo mismo, y confundirlo es cómo se publica el
 * procedimiento interno de descuentos.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { ErrorApi } from "@/lib/api";
import { listar } from "@/lib/listados";
import { CabeceraPagina } from "@/componentes/Pagina";

interface Articulo {
  id: string;
  clave: string;
  /**
   * El título NO es una columna del artículo: vive en la versión, y el listado
   * lo resuelve para la página entera. Antes no lo mandaba nadie, así que la
   * lista salía sin nombres y el buscador tumbaba la pantalla.
   */
  titulo: string;
  /** Si lo que se enseña es el borrador y no lo publicado. */
  es_borrador: boolean;
  version_mostrada: number | null;
  estado: string;
  publico: boolean;
  vistas: number;
}

export function Conocimiento() {
  const { t } = useTranslation();
  const [articulos, setArticulos] = useState<Articulo[] | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);
  const [busqueda, setBusqueda] = useState("");

  const cargar = useCallback(() => {
    const control = new AbortController();
    listar<Articulo>("/api/v1/conocimiento/articulos", { signal: control.signal })
      .then(setArticulos)
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!articulos) return <Cargando />;

  const filtrados = busqueda
    ? articulos.filter((a) =>
        (a.titulo ?? a.clave ?? "").toLowerCase().includes(busqueda.toLowerCase()),
      )
    : articulos;

  return (
    <div className="flex flex-col gap-4">
      <CabeceraPagina
        titulo={t("conocimiento.titulo")}
        entradilla={t("conocimiento.entradilla")}
        icono="menu_book"
      />

      {/* `input-base` y no un estilo propio: este buscador tenía otro borde,
          otro espaciado y **ningún foco**, así que quien navega con el teclado
          no veía dónde estaba. */}
      <div className="max-w-md">
        <input
          type="search"
          value={busqueda}
          onChange={(e) => setBusqueda(e.target.value)}
          placeholder={t("conocimiento.buscar")}
          aria-label={t("conocimiento.buscar")}
          className="input-base"
        />
      </div>

      {filtrados.length === 0 ? (
        <Vacio titulo={t("conocimiento.sinResultados")} detalle="" />
      ) : (
        <ul className="flex flex-col gap-2">
          {filtrados.map((a) => (
            <li
              key={a.id}
              className="flex flex-wrap items-baseline gap-2 rounded-lg border border-ink-dim/40 bg-paper-light p-3"
            >
              <span className="flex-1 text-sm text-ink">{a.titulo}</span>
              {/* Lo publicado y el borrador NO se enseñan igual: citarle a un
                  cliente un texto que nadie ha aprobado es el caso que esto
                  existe para evitar. */}
              {a.es_borrador ? (
                <span className="rounded bg-warning/10 px-1.5 py-0.5 text-3xs uppercase text-warning">
                  {t("conocimiento.borrador", { version: a.version_mostrada ?? "—" })}
                </span>
              ) : null}
              {/* El estado va AL LADO del título: un artículo a medias que se lee
                  como bueno se copia en una respuesta a un cliente, y ahí ya no
                  hay quien lo recoja. */}
              <span
                className={`rounded px-1.5 py-0.5 text-3xs uppercase ${
                  a.estado === "publicado"
                    ? "bg-success/10 text-success"
                    : "bg-warning/10 text-warning"
                }`}
              >
                {a.estado}
              </span>
              {a.publico ? (
                <span className="rounded bg-accent/10 px-1.5 py-0.5 text-3xs uppercase text-accent">
                  {t("conocimiento.enPortal")}
                </span>
              ) : null}
              <span className="font-mono text-2xs text-ink-faint">
                {t("conocimiento.vistas", { vistas: a.vistas })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
