/**
 * La barra de filtros de un listado.
 *
 * Va **encima** de la tabla y en una sola fila: un panel lateral de filtros
 * tapa justo lo que se está filtrando, y uno escondido detrás de un botón hace
 * que nadie sepa que hay filtros puestos — que es cómo se acaba discutiendo un
 * número calculado sobre media lista.
 *
 * Lo puesto se enseña como pastillas, cada una con su aspa. Es lo que permite
 * ver de un vistazo **qué recorte estás mirando**, que importa más que poder
 * añadir el filtro siguiente.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import { humanizar } from "@/lib/formato";
import {
  operadoresDe,
  parametroDe,
  tipoDe,
  type Filtro,
  type TipoCampo,
} from "@/lib/filtros";

export function Filtros({
  campos,
  filas,
  puestos,
  alCambiar,
}: {
  /** Columnas por las que se puede filtrar, en el orden en que se enseñan. */
  campos: string[];
  /** Las filas que han llegado, para deducir el tipo de cada columna. */
  filas: Array<Record<string, unknown>>;
  puestos: Filtro[];
  alCambiar: (filtros: Filtro[]) => void;
}) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const [campo, setCampo] = useState("");
  const [sufijo, setSufijo] = useState("");
  const [valor, setValor] = useState("");

  const tipo: TipoCampo = campo ? tipoDe(filas, campo) : "texto";
  const operadores = operadoresDe(tipo);
  const elegido = operadores.find((o) => o.sufijo === sufijo) ?? operadores[0];
  const necesitaValor = elegido?.conValor ?? true;
  const listo = campo !== "" && (!necesitaValor || valor.trim() !== "");

  function anadir() {
    if (!listo || !elegido) return;
    // `1` y no vacío para los que no llevan valor: el servidor ignora el
    // contenido, pero un parámetro sin `=` se pierde por el camino en algunos
    // proxies y entonces el filtro desaparece sin decirlo.
    alCambiar([
      ...puestos,
      { campo, sufijo: elegido.sufijo, valor: necesitaValor ? valor.trim() : "1" },
    ]);
    setCampo("");
    setSufijo("");
    setValor("");
    setAbierto(false);
  }

  return (
    <div className="mb-2 flex flex-wrap items-center gap-1.5">
      {puestos.map((f) => (
        <span key={parametroDe(f)} className="pill inline-flex items-center gap-1">
          <span className="text-3xs">
            {humanizar(f.campo)}{" "}
            <span className="text-ink-muted">{rotuloDe(t, f, tipoDe(filas, f.campo))}</span>
          </span>
          <button
            type="button"
            onClick={() => alCambiar(puestos.filter((x) => parametroDe(x) !== parametroDe(f)))}
            className="btn-icon h-4 w-4 text-ink-muted hover:text-ink"
            aria-label={t("filtros.quitar", { campo: humanizar(f.campo) })}
          >
            <Icono nombre="close" tamano="xs" />
          </button>
        </span>
      ))}

      {puestos.length > 1 ? (
        <button type="button" onClick={() => alCambiar([])} className="btn-link">
          {t("filtros.quitarTodos")}
        </button>
      ) : null}

      {abierto ? (
        <span className="inline-flex flex-wrap items-center gap-1">
          <select
            value={campo}
            onChange={(e) => {
              setCampo(e.target.value);
              setSufijo("");
              setValor("");
            }}
            className="input-sm"
            aria-label={t("filtros.campo")}
          >
            <option value="">{t("filtros.elegirCampo")}</option>
            {campos.map((c) => (
              <option key={c} value={c}>
                {humanizar(c)}
              </option>
            ))}
          </select>

          {campo ? (
            <select
              value={elegido?.sufijo ?? ""}
              onChange={(e) => setSufijo(e.target.value)}
              className="input-sm"
              aria-label={t("filtros.operador")}
            >
              {operadores.map((o) => (
                <option key={o.sufijo || "igual"} value={o.sufijo}>
                  {t(o.clave)}
                </option>
              ))}
            </select>
          ) : null}

          {campo && necesitaValor ? (
            <input
              // El tipo del campo decide el teclado y el selector: pedir una
              // fecha en una caja de texto libre produce formatos que el
              // servidor rechaza, y el error llega donde no se entiende.
              type={tipo === "fecha" ? "date" : tipo === "numero" ? "number" : "text"}
              value={valor}
              onChange={(e) => setValor(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") anadir();
              }}
              className="input-sm"
              placeholder={t("filtros.valor")}
              aria-label={t("filtros.valor")}
            />
          ) : null}

          <button type="button" onClick={anadir} disabled={!listo} className="btn-secondary">
            {t("filtros.aplicar")}
          </button>
          <button type="button" onClick={() => setAbierto(false)} className="btn-link">
            {t("filtros.cancelar")}
          </button>
        </span>
      ) : (
        <button
          type="button"
          onClick={() => setAbierto(true)}
          className="btn-link inline-flex items-center gap-1"
        >
          <Icono nombre="filter_alt" tamano="sm" />
          {t("filtros.anadir")}
        </button>
      )}
    </div>
  );
}

/** El texto de una pastilla: «desde 2026-10-01», «sin valor». */
function rotuloDe(
  t: (clave: string) => string,
  filtro: Filtro,
  tipo: TipoCampo,
): string {
  const op = operadoresDe(tipo).find((o) => o.sufijo === filtro.sufijo);
  const rotulo = op ? t(op.clave) : filtro.sufijo;
  return op && !op.conValor ? rotulo : `${rotulo} ${filtro.valor}`;
}
