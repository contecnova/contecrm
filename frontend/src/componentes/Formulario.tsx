/**
 * Un formulario generado del contrato, no escrito a mano.
 *
 * Escribirlo a mano produce dos definiciones del mismo objeto que se separan en
 * cuanto alguien añade un campo al servicio: el formulario deja de ofrecerlo y
 * nadie se entera hasta que falta el dato.
 *
 * **No valida reglas de negocio.** Marca lo obligatorio y respeta el tipo y la
 * longitud que declara el esquema, porque eso es contrato; cualquier otra regla
 * —«el descuento no puede pasar del 30 %»— la comprueba el servicio, y
 * duplicarla aquí sería tener dos versiones de la misma regla.
 */

import { useState, type FormEvent } from "react";

import type { CampoEsquema } from "@/lib/contrato";

export interface Props {
  campos: CampoEsquema[];
  valores?: Record<string, unknown>;
  enviando?: boolean;
  textoEnviar: string;
  alEnviar: (valores: Record<string, unknown>) => void;
}

export function Formulario({ campos, valores = {}, enviando, textoEnviar, alEnviar }: Props) {
  const [estado, setEstado] = useState<Record<string, unknown>>(valores);

  function enviar(evento: FormEvent) {
    evento.preventDefault();
    // Se quitan los vacíos que no son obligatorios: mandar cadenas vacías
    // sobrescribiría con "" campos que el servidor tenía a nulo, y eso borra
    // datos sin que nadie lo haya pedido.
    const limpio: Record<string, unknown> = {};
    for (const campo of campos) {
      const valor = estado[campo.nombre];
      if (valor === undefined || valor === "") {
        if (campo.obligatorio) limpio[campo.nombre] = valor;
        continue;
      }
      limpio[campo.nombre] = valor;
    }
    alEnviar(limpio);
  }

  if (campos.length === 0) {
    // Se dice, no se enseña un formulario vacío: uno vacío presentado como
    // «este recurso no pide nada» haría crear registros incompletos.
    return (
      <p className="text-2xs text-ink-faint">
        El contrato de esta operación no declara cuerpo, o no se ha podido leer.
      </p>
    );
  }

  return (
    <form onSubmit={enviar} className="flex flex-col gap-3">
      {campos.map((campo) => (
        <Campo
          key={campo.nombre}
          campo={campo}
          valor={estado[campo.nombre]}
          alCambiar={(v) => setEstado((previo) => ({ ...previo, [campo.nombre]: v }))}
        />
      ))}
      <button
        type="submit"
        disabled={enviando}
        className="mt-1 self-start rounded-lg bg-accent px-4 py-2 text-xs text-paper hover:bg-accent-soft disabled:opacity-50"
      >
        {textoEnviar}
      </button>
    </form>
  );
}

function Campo({
  campo,
  valor,
  alCambiar,
}: {
  campo: CampoEsquema;
  valor: unknown;
  alCambiar: (valor: unknown) => void;
}) {
  const id = `campo-${campo.nombre}`;
  const ayuda = campo.descripcion ? `${id}-ayuda` : undefined;
  const comun = {
    id,
    "aria-describedby": ayuda,
    required: campo.obligatorio,
    className:
      "mt-1 w-full rounded-lg border border-ink-dim/60 bg-paper px-3 py-2 text-xs text-ink",
  };

  return (
    <div>
      <label htmlFor={id} className="text-2xs text-ink-muted">
        {campo.titulo}
        {campo.obligatorio ? <span className="text-danger"> *</span> : null}
      </label>

      {campo.tipo === "booleano" ? (
        <input
          type="checkbox"
          id={id}
          aria-describedby={ayuda}
          checked={Boolean(valor)}
          onChange={(e) => alCambiar(e.target.checked)}
          className="mt-1 block"
        />
      ) : campo.tipo === "lista" ? (
        <select {...comun} value={String(valor ?? "")} onChange={(e) => alCambiar(e.target.value)}>
          <option value="">—</option>
          {campo.opciones.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : campo.tipo === "objeto" ? (
        // Un valor compuesto se edita como JSON y se dice. Inventar aquí un
        // editor por forma de objeto sería adivinar, y adivinar mal en un
        // formulario es perder lo que el usuario escribió.
        <textarea
          {...comun}
          rows={3}
          value={typeof valor === "string" ? valor : JSON.stringify(valor ?? "")}
          onChange={(e) => alCambiar(intentarJson(e.target.value))}
        />
      ) : (
        <input
          {...comun}
          type={campo.tipo === "numero" ? "number" : campo.tipo === "fecha" ? "date" : "text"}
          maxLength={campo.maximo ?? undefined}
          value={String(valor ?? "")}
          onChange={(e) =>
            alCambiar(campo.tipo === "numero" ? Number(e.target.value) : e.target.value)
          }
        />
      )}

      {campo.descripcion ? (
        <p id={ayuda} className="mt-1 text-3xs text-ink-faint">
          {campo.descripcion}
        </p>
      ) : null}
    </div>
  );
}

export function intentarJson(texto: string): unknown {
  try {
    return JSON.parse(texto);
  } catch {
    // Mientras se escribe, el JSON está a medias casi siempre. Se guarda el
    // texto tal cual y el servidor dirá si vale: rechazarlo aquí a cada tecla
    // haría imposible teclear nada.
    return texto;
  }
}
