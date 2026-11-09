/**
 * Las condiciones de una automatización, con los campos propios del objeto a
 * mano (CRM-00.04.03.05).
 *
 * **Medido el 09-11-2026 en Procesos y orquestación › Automatizaciones ›
 * Nuevo:** «Condiciones» salía como un editor de clave y valor —ni siquiera una
 * lista— y un campo personalizado sólo se podía usar sabiendo que se escribe
 * `campos.<nombre>` y sabiéndose el nombre de memoria. El motor ya los
 * evaluaba; lo que faltaba era poder elegirlos.
 *
 * Cada fila es la gramática del motor tal cual —`{atributo, op, valor}`—, y
 * el atributo se puede **elegir** entre los campos propios que declara el
 * objeto (`GET /metadata/objetos/{objeto}/describe`) o escribir: los campos
 * de serie del objeto (`importe`, `estado`) no salen en el describe y siguen
 * haciendo falta.
 *
 * El objeto es el que se esté escribiendo en «Objetivo». Si no tiene campos
 * propios declarados se dice, en vez de enseñar un desplegable vacío.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ErrorApi, llamar } from "@/lib/api";

interface Condicion {
  atributo?: string;
  op?: string;
  valor?: unknown;
}

interface CampoPropio {
  nombre: string;
  etiqueta: string;
  deprecado?: boolean;
  activo?: boolean;
}

/** Las que entiende el motor, como sugerencia: el que manda es el servidor. */
const OPERADORES_SUGERIDOS = [
  "=",
  "!=",
  ">",
  ">=",
  "<",
  "<=",
  "en",
  "contiene",
  "vacio",
  "no_vacio",
  "hace_mas_de_horas",
  "hace_menos_de_horas",
];

const NOMBRE_DE_OBJETO = /^[a-z][a-z0-9_]{1,59}$/;

function filasDe(valor: unknown): Condicion[] {
  return Array.isArray(valor)
    ? valor.filter((c): c is Condicion => Boolean(c) && typeof c === "object")
    : [];
}

/** El valor tecleado: un número o un sí/no se mandan como tales. */
function leerValor(texto: string): unknown {
  const limpio = texto.trim();
  if (limpio === "") return "";
  if (/^-?\d+(\.\d+)?$/.test(limpio)) return Number(limpio);
  if (limpio === "true") return true;
  if (limpio === "false") return false;
  return texto;
}

function escribirValor(valor: unknown): string {
  if (valor === undefined || valor === null) return "";
  return typeof valor === "string" ? valor : JSON.stringify(valor);
}

export function EditorDeCondiciones({
  id,
  valor,
  alCambiar,
  objeto,
  ayuda,
}: {
  id: string;
  valor: unknown;
  alCambiar: (v: unknown) => void;
  /** El objeto sobre el que actúa la regla, tal como esté escrito. */
  objeto: string;
  ayuda?: string;
}) {
  const { t } = useTranslation();
  const filas = filasDe(valor);
  /** `null` mientras no hay objeto que mirar; `[]` si no declara ninguno. */
  const [propios, setPropios] = useState<CampoPropio[] | null>(null);

  const nombre = objeto.trim();
  useEffect(() => {
    if (!NOMBRE_DE_OBJETO.test(nombre)) {
      setPropios(null);
      return;
    }
    const control = new AbortController();
    // Se espera a que se deje de teclear: «oportunidad» son once peticiones
    // si se pide una por letra.
    const espera = window.setTimeout(() => {
      llamar<{ campos?: CampoPropio[] }>(
        `/api/v1/metadata/objetos/${encodeURIComponent(nombre)}/describe`,
        { signal: control.signal },
      )
        .then((r) =>
          setPropios(
            (r.datos.campos ?? []).filter(
              (c) => c.activo !== false && !c.deprecado,
            ),
          ),
        )
        .catch((e: unknown) => {
          if (control.signal.aborted) return;
          // Un 404 es la respuesta —el objeto no tiene nada declarado—, no un
          // error de la pantalla.
          setPropios(e instanceof ErrorApi && e.estado === 404 ? [] : null);
        });
    }, 300);
    return () => {
      window.clearTimeout(espera);
      control.abort();
    };
  }, [nombre]);

  function cambiarFila(indice: number, cambio: Condicion) {
    alCambiar(filas.map((f, i) => (i === indice ? { ...f, ...cambio } : f)));
  }

  const idSugerencias = `${id}-operadores`;

  return (
    <div
      id={id}
      aria-describedby={ayuda}
      className="flex flex-col gap-2"
      data-testid="editor-condiciones"
    >
      <datalist id={idSugerencias}>
        {OPERADORES_SUGERIDOS.map((op) => (
          <option key={op} value={op} />
        ))}
      </datalist>

      {nombre === "" ? (
        <p className="text-rotulo text-ink-faint">
          {t("condiciones.escribeElObjetivo")}
        </p>
      ) : propios !== null && propios.length === 0 ? (
        <p className="text-rotulo text-ink-faint">
          {t("condiciones.sinCamposPropios", { objeto: nombre })}
        </p>
      ) : null}

      {filas.length === 0 ? (
        <p className="text-rotulo text-ink-faint">{t("condiciones.ninguna")}</p>
      ) : null}

      {filas.map((fila, indice) => {
        const atributo = String(fila.atributo ?? "");
        return (
          <div
            key={indice}
            className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,0.6fr)_minmax(0,1fr)_auto]"
          >
            {propios && propios.length > 0 ? (
              <select
                aria-label={t("condiciones.campoPropio", {
                  numero: indice + 1,
                })}
                className="input-base"
                value={
                  propios.some((c) => `campos.${c.nombre}` === atributo)
                    ? atributo
                    : ""
                }
                onChange={(e) =>
                  e.target.value &&
                  cambiarFila(indice, { atributo: e.target.value })
                }
              >
                <option value="">{t("condiciones.elegirCampoPropio")}</option>
                {propios.map((c) => (
                  <option key={c.nombre} value={`campos.${c.nombre}`}>
                    {c.etiqueta || c.nombre}
                  </option>
                ))}
              </select>
            ) : (
              <span className="hidden md:block" />
            )}
            <input
              aria-label={t("condiciones.atributo", { numero: indice + 1 })}
              className="input-base"
              placeholder={t("condiciones.atributoEjemplo")}
              value={atributo}
              onChange={(e) =>
                cambiarFila(indice, { atributo: e.target.value })
              }
            />
            <input
              aria-label={t("condiciones.operador", { numero: indice + 1 })}
              className="input-base"
              list={idSugerencias}
              value={String(fila.op ?? "=")}
              onChange={(e) => cambiarFila(indice, { op: e.target.value })}
            />
            <input
              aria-label={t("condiciones.valor", { numero: indice + 1 })}
              className="input-base"
              value={escribirValor(fila.valor)}
              onChange={(e) =>
                cambiarFila(indice, { valor: leerValor(e.target.value) })
              }
            />
            <button
              type="button"
              className="btn-ghost"
              aria-label={t("condiciones.quitar", { numero: indice + 1 })}
              onClick={() => alCambiar(filas.filter((_, i) => i !== indice))}
            >
              {t("condiciones.quitarCorto")}
            </button>
          </div>
        );
      })}

      <button
        type="button"
        className="btn-secondary self-start"
        onClick={() =>
          alCambiar([...filas, { atributo: "", op: "=", valor: "" }])
        }
      >
        {t("condiciones.anadir")}
      </button>
    </div>
  );
}
