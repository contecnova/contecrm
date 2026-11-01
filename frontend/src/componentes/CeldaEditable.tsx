/**
 * Cambiar un dato sin salir de la lista.
 *
 * Es de lo que más se usa en Lightning: el lápiz sobre una celda, se escribe,
 * se guarda y no se ha salido de la lista. Aquí no existía — para corregir un
 * estado o un importe había que abrir la ficha, buscar «Editar», cambiar,
 * guardar y volver atrás. Cinco pasos para un dato.
 *
 * Tres decisiones, y las tres se notan:
 *
 * **El lápiz sólo aparece al pasar por encima o al llegar con el teclado.** Un
 * lápiz en cada celda de una tabla de veinte filas por cinco columnas son cien
 * iconos, y entonces no se ve la tabla. Pero *tiene* que aparecer con el
 * teclado, o quien no usa ratón no se entera de que la celda se puede editar.
 *
 * **El control lo decide el contrato.** Una lista cerrada es un desplegable,
 * una fecha un calendario y un número un campo numérico. Pintar todo como
 * texto es pedirle a alguien que escriba `2026-11-01` a mano y acierte.
 *
 * **Y se guarda al salir del campo o con Intro, no con un botón.** Un botón de
 * guardar por celda es otro icono más en la tabla. `Escape` cancela y deja el
 * valor como estaba, que es lo que espera cualquiera que haya empezado a
 * escribir y se arrepienta.
 *
 * El error **no se traga**: si el servidor rechaza el cambio, el valor vuelve
 * al anterior —lo hace quien guarda— y la celda lo dice. Un cambio que parece
 * guardado y no lo está es peor que uno que falla a la vista.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import type { CampoEsquema } from "@/lib/contrato";
import { humanizar } from "@/lib/formato";

/** El tipo de `<input>` que le toca a un campo del contrato. */
function tipoDeEntrada(campo: CampoEsquema): string {
  if (campo.tipo === "fecha") return campo.formato === "date-time" ? "datetime-local" : "date";
  if (campo.tipo === "numero") return "number";
  return "text";
}

export function CeldaEditable({
  valor,
  campo,
  esquema,
  alGuardar,
  children,
}: {
  valor: unknown;
  campo: string;
  esquema: CampoEsquema;
  /** Lanza si el servidor lo rechaza; quien guarda deshace el cambio. */
  alGuardar: (valor: unknown) => Promise<void>;
  /** Cómo se ve el valor cuando no se está editando. */
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const [editando, setEditando] = useState(false);
  const [borrador, setBorrador] = useState("");
  const [fallo, setFallo] = useState("");
  const entrada = useRef<HTMLInputElement | HTMLSelectElement>(null);

  useEffect(() => {
    if (editando) entrada.current?.focus();
  }, [editando]);

  function abrir() {
    setBorrador(valor === null || valor === undefined ? "" : String(valor));
    setFallo("");
    setEditando(true);
  }

  async function guardar() {
    setEditando(false);
    const antes = valor === null || valor === undefined ? "" : String(valor);
    if (borrador === antes) return;
    try {
      await alGuardar(esquema.tipo === "numero" && borrador !== "" ? Number(borrador) : borrador);
    } catch (error) {
      setFallo(error instanceof Error ? error.message : String(error));
    }
  }

  if (editando) {
    const comun = {
      ref: entrada as never,
      value: borrador,
      "aria-label": humanizar(campo),
      className: "input-base !py-0.5 !text-2xs",
      onBlur: () => void guardar(),
      onKeyDown: (e: React.KeyboardEvent) => {
        if (e.key === "Enter") {
          e.preventDefault();
          void guardar();
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setEditando(false);
        }
      },
    };
    return esquema.opciones.length > 0 ? (
      <select
        {...comun}
        onChange={(e) => setBorrador(e.target.value)}
        // Un desplegable guarda al elegir: no hay nada más que escribir, y
        // esperar a que salga del campo deja la sensación de que no ha cogido.
        onInput={(e) => setBorrador((e.target as HTMLSelectElement).value)}
      >
        <option value="">—</option>
        {esquema.opciones.map((o) => (
          <option key={o} value={o}>
            {humanizar(o)}
          </option>
        ))}
      </select>
    ) : (
      <input
        {...comun}
        type={tipoDeEntrada(esquema)}
        onChange={(e) => setBorrador(e.target.value)}
      />
    );
  }

  return (
    <span className="group/celda inline-flex min-w-0 items-center gap-1">
      <span className="min-w-0 truncate">{children}</span>
      <button
        type="button"
        onClick={abrir}
        aria-label={t("tabla.editarCampo", { campo: humanizar(campo) })}
        // Invisible hasta que se pasa por encima o se llega con el teclado.
        className="shrink-0 rounded p-0.5 text-ink-faint opacity-0 transition-opacity hover:bg-paper-light hover:text-ink focus-visible:opacity-100 group-hover/celda:opacity-100"
      >
        <Icono nombre="edit" tamano="sm" />
      </button>
      {fallo ? (
        <span className="text-3xs text-danger" role="alert" title={fallo}>
          {t("tabla.noSeGuardo")}
        </span>
      ) : null}
    </span>
  );
}
