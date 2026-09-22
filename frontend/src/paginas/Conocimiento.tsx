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
import { ErrorApi, llamar } from "@/lib/api";

interface Articulo {
  id: string;
  titulo: string;
  estado: string;
  publico: boolean;
  categoria: string | null;
  vistas: number;
  util: number | null;
}

export function Conocimiento() {
  const { t } = useTranslation();
  const [articulos, setArticulos] = useState<Articulo[] | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);
  const [busqueda, setBusqueda] = useState("");

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<Articulo[]>("/api/v1/conocimiento/articulos", { signal: control.signal })
      .then((r) => setArticulos(r.datos))
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!articulos) return <Cargando />;

  const filtrados = busqueda
    ? articulos.filter((a) => a.titulo.toLowerCase().includes(busqueda.toLowerCase()))
    : articulos;

  return (
    <div className="flex flex-col gap-4 p-4">
      <header>
        <h1 className="text-lg font-medium text-ink">{t("conocimiento.titulo")}</h1>
        <p className="mt-1 max-w-prose text-2xs text-ink-muted">
          {t("conocimiento.entradilla")}
        </p>
      </header>

      <input
        type="search"
        value={busqueda}
        onChange={(e) => setBusqueda(e.target.value)}
        placeholder={t("conocimiento.buscar")}
        aria-label={t("conocimiento.buscar")}
        className="rounded-lg border border-ink-dim/60 bg-paper px-3 py-2 text-sm text-ink"
      />

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
