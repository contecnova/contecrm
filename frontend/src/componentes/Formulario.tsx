/**
 * Un formulario generado del contrato, no escrito a mano.
 *
 * Escribirlo a mano produce dos definiciones del mismo objeto que se separan en
 * cuanto alguien añade un campo al servicio: el formulario deja de ofrecerlo y
 * nadie se entera hasta que falta el dato.
 *
 * **Lo edita una persona, no un programa.** Esto antes pintaba cualquier lista
 * y cualquier objeto como un `textarea` de JSON, así que para meter dos
 * etiquetas había que escribir `["a","b"]` a mano —o separarlas por comas y
 * esperar acertar—. Eso no es un formulario, es una consola con otro nombre.
 * Ahora:
 *
 *   * una lista de textos se escribe **uno a uno**, y cada valor queda como una
 *     etiqueta que se puede quitar;
 *   * una lista de opciones cerradas se **elige**, con casillas;
 *   * un objeto se edita **por pares clave/valor**, con el JSON detrás de un
 *     interruptor para el caso raro en que haga falta;
 *   * lo obligatorio va delante y lo opcional se despliega: un alta generada de
 *     un contrato con cuarenta campos, toda a la vista, no la rellena nadie.
 *
 * **No valida reglas de negocio.** Marca lo obligatorio y respeta el tipo y la
 * longitud que declara el esquema, porque eso es contrato; cualquier otra regla
 * —«el descuento no puede pasar del 30 %»— la comprueba el servicio, y
 * duplicarla aquí sería tener dos versiones de la misma regla.
 */

import { useMemo, useState, type FormEvent, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import type { CampoEsquema } from "@/lib/contrato";
import { cn } from "@/lib/utiles";

export interface Props {
  campos: CampoEsquema[];
  valores?: Record<string, unknown>;
  enviando?: boolean;
  textoEnviar: string;
  alEnviar: (valores: Record<string, unknown>) => void;
}

export function Formulario({ campos, valores = {}, enviando, textoEnviar, alEnviar }: Props) {
  const { t } = useTranslation();
  const [estado, setEstado] = useState<Record<string, unknown>>(valores);
  const [verOpcionales, setVerOpcionales] = useState(false);

  const { obligatorios, opcionales } = useMemo(
    () => ({
      obligatorios: campos.filter((c) => c.obligatorio),
      opcionales: campos.filter((c) => !c.obligatorio),
    }),
    [campos],
  );

  function enviar(evento: FormEvent) {
    evento.preventDefault();
    // Se quitan los vacíos que no son obligatorios: mandar cadenas vacías
    // sobrescribiría con "" campos que el servidor tenía a nulo, y eso borra
    // datos sin que nadie lo haya pedido.
    const limpio: Record<string, unknown> = {};
    for (const campo of campos) {
      const valor = estado[campo.nombre];
      const vacio =
        valor === undefined ||
        valor === "" ||
        (Array.isArray(valor) && valor.length === 0) ||
        (valor !== null && typeof valor === "object" && Object.keys(valor).length === 0);
      if (vacio) {
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
    return <p className="text-2xs text-ink-faint">{t("formulario.sinContrato")}</p>;
  }

  const cambiar = (nombre: string) => (v: unknown) =>
    setEstado((previo) => ({ ...previo, [nombre]: v }));

  return (
    <form onSubmit={enviar} className="flex flex-col gap-4">
      {obligatorios.map((campo) => (
        <Campo
          key={campo.nombre}
          campo={campo}
          valor={estado[campo.nombre]}
          alCambiar={cambiar(campo.nombre)}
        />
      ))}

      {opcionales.length > 0 ? (
        <div className="border-t border-ink-dim/30 pt-3">
          <button
            type="button"
            onClick={() => setVerOpcionales((v) => !v)}
            aria-expanded={verOpcionales}
            className="inline-flex items-center gap-1.5 text-2xs text-ink-muted hover:text-ink"
          >
            <Icono
              nombre="keyboard_arrow_down"
              tamano="sm"
              className={cn("transition-transform", !verOpcionales && "-rotate-90")}
            />
            {t("formulario.masCampos", { total: opcionales.length })}
          </button>
          {verOpcionales ? (
            <div className="mt-3 flex flex-col gap-4">
              {opcionales.map((campo) => (
                <Campo
                  key={campo.nombre}
                  campo={campo}
                  valor={estado[campo.nombre]}
                  alCambiar={cambiar(campo.nombre)}
                />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <button type="submit" disabled={enviando} className="btn-primary mt-1 self-start">
        {enviando ? t("app.cargando") : textoEnviar}
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
    className: "input-base",
  };

  return (
    <div>
      {/* El booleano pone su propia etiqueta al lado de la casilla: encima, y a
          dos centímetros, no se sabe qué se está marcando. */}
      {campo.tipo !== "booleano" ? (
        <label htmlFor={id} className="label-base">
          {campo.titulo}
          {campo.obligatorio ? <span className="text-danger"> *</span> : null}
        </label>
      ) : null}

      {campo.tipo === "booleano" ? (
        <label htmlFor={id} className="inline-flex items-center gap-2 text-xs text-ink">
          <input
            type="checkbox"
            id={id}
            aria-describedby={ayuda}
            checked={Boolean(valor)}
            onChange={(e) => alCambiar(e.target.checked)}
            className="h-4 w-4 rounded border-ink-dim accent-accent"
          />
          {campo.titulo}
        </label>
      ) : campo.tipo === "lista" ? (
        <select {...comun} value={String(valor ?? "")} onChange={(e) => alCambiar(e.target.value)}>
          <option value="">—</option>
          {campo.opciones.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : campo.tipo === "lista_multiple" ? (
        <Opciones campo={campo} valor={valor} alCambiar={alCambiar} ayuda={ayuda} />
      ) : campo.tipo === "etiquetas" ? (
        <Etiquetas campo={campo} valor={valor} alCambiar={alCambiar} id={id} ayuda={ayuda} />
      ) : campo.tipo === "objeto" ? (
        <Pares campo={campo} valor={valor} alCambiar={alCambiar} id={id} ayuda={ayuda} />
      ) : campo.tipo === "texto_largo" ? (
        <textarea
          {...comun}
          rows={4}
          maxLength={campo.maximo ?? undefined}
          value={String(valor ?? "")}
          onChange={(e) => alCambiar(e.target.value)}
        />
      ) : (
        <input
          {...comun}
          type={campo.tipo === "numero" ? "number" : campo.tipo === "fecha" ? "date" : "text"}
          maxLength={campo.maximo ?? undefined}
          value={String(valor ?? "")}
          onChange={(e) =>
            alCambiar(
              campo.tipo === "numero"
                ? e.target.value === ""
                  ? ""
                  : Number(e.target.value)
                : e.target.value,
            )
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

/** Lista de opciones cerradas: se marcan, no se escriben. */
function Opciones({
  campo,
  valor,
  alCambiar,
  ayuda,
}: {
  campo: CampoEsquema;
  valor: unknown;
  alCambiar: (v: unknown) => void;
  ayuda?: string;
}) {
  const puestos = Array.isArray(valor) ? valor.map(String) : [];
  return (
    <fieldset aria-describedby={ayuda} className="mt-1 flex flex-wrap gap-x-4 gap-y-1.5">
      <legend className="sr-only">{campo.titulo}</legend>
      {campo.opciones.map((opcion) => (
        <label key={opcion} className="inline-flex items-center gap-1.5 text-xs text-ink">
          <input
            type="checkbox"
            checked={puestos.includes(opcion)}
            onChange={(e) =>
              alCambiar(
                e.target.checked
                  ? [...puestos, opcion]
                  : puestos.filter((p) => p !== opcion),
              )
            }
            className="h-4 w-4 rounded border-ink-dim accent-accent"
          />
          {opcion}
        </label>
      ))}
    </fieldset>
  );
}

/** Lista de textos: uno a uno, cada uno una etiqueta que se puede quitar. */
function Etiquetas({
  campo,
  valor,
  alCambiar,
  id,
  ayuda,
}: {
  campo: CampoEsquema;
  valor: unknown;
  alCambiar: (v: unknown) => void;
  id: string;
  ayuda?: string;
}) {
  const { t } = useTranslation();
  const [borrador, setBorrador] = useState("");
  const puestos = Array.isArray(valor) ? valor.map(String) : [];

  function anadir() {
    const limpio = borrador.trim();
    if (!limpio || puestos.includes(limpio)) {
      setBorrador("");
      return;
    }
    alCambiar([...puestos, limpio]);
    setBorrador("");
  }

  function alTeclear(evento: KeyboardEvent<HTMLInputElement>) {
    // Intro y coma añaden. La coma también, porque es lo que la gente teclea sin
    // pensar cuando ve una lista — y si no hiciera nada, acabaría dentro del
    // valor.
    if (evento.key === "Enter" || evento.key === ",") {
      evento.preventDefault();
      anadir();
    } else if (evento.key === "Backspace" && !borrador && puestos.length) {
      alCambiar(puestos.slice(0, -1));
    }
  }

  return (
    <div>
      <div className="mt-1 flex gap-2">
        <input
          id={id}
          aria-describedby={ayuda}
          value={borrador}
          onChange={(e) => setBorrador(e.target.value)}
          onKeyDown={alTeclear}
          onBlur={anadir}
          placeholder={t("formulario.anadirValor")}
          className="input-base"
        />
        <button
          type="button"
          onClick={anadir}
          className="btn-secondary shrink-0"
          aria-label={t("formulario.anadirA", { campo: campo.titulo })}
        >
          <Icono nombre="add" tamano="sm" />
        </button>
      </div>
      {puestos.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {puestos.map((p) => (
            <li key={p}>
              <button
                type="button"
                onClick={() => alCambiar(puestos.filter((x) => x !== p))}
                className="badge badge-muted inline-flex items-center gap-1 hover:bg-danger/10"
                aria-label={t("formulario.quitarValor", { valor: p })}
              >
                {p}
                <Icono nombre="close" tamano="sm" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Objeto: pares clave/valor, con el JSON detrás de un interruptor. */
function Pares({
  campo,
  valor,
  alCambiar,
  id,
  ayuda,
}: {
  campo: CampoEsquema;
  valor: unknown;
  alCambiar: (v: unknown) => void;
  id: string;
  ayuda?: string;
}) {
  const { t } = useTranslation();
  const [crudo, setCrudo] = useState(false);
  const pares = useMemo(() => {
    if (valor && typeof valor === "object" && !Array.isArray(valor)) {
      return Object.entries(valor as Record<string, unknown>).map(([k, v]) => [k, String(v)]);
    }
    return [] as string[][];
  }, [valor]);

  function fijar(siguientes: string[][]) {
    const objeto: Record<string, unknown> = {};
    for (const [k, v] of siguientes) if (k) objeto[k] = v;
    alCambiar(objeto);
  }

  if (crudo) {
    return (
      <div>
        <textarea
          id={id}
          aria-describedby={ayuda}
          rows={4}
          value={typeof valor === "string" ? valor : JSON.stringify(valor ?? {}, null, 2)}
          onChange={(e) => alCambiar(intentarJson(e.target.value))}
          className="input-base font-mono text-3xs"
        />
        <button
          type="button"
          onClick={() => setCrudo(false)}
          className="btn-link mt-1"
        >
          {t("formulario.volverAPares")}
        </button>
      </div>
    );
  }

  const filas = [...pares, ["", ""]];
  return (
    <div>
      <div id={id} aria-describedby={ayuda} className="mt-1 flex flex-col gap-1.5">
        {filas.map(([clave, contenido], i) => (
          <div key={i} className="flex gap-2">
            <input
              value={clave}
              placeholder={t("formulario.clave")}
              aria-label={t("formulario.claveDe", { campo: campo.titulo })}
              onChange={(e) => {
                const siguientes = filas.map((f) => [...f]);
                siguientes[i]![0] = e.target.value;
                fijar(siguientes);
              }}
              className="input-base"
            />
            <input
              value={contenido}
              placeholder={t("formulario.valor")}
              aria-label={t("formulario.valorDe", { campo: campo.titulo })}
              onChange={(e) => {
                const siguientes = filas.map((f) => [...f]);
                siguientes[i]![1] = e.target.value;
                fijar(siguientes);
              }}
              className="input-base"
            />
          </div>
        ))}
      </div>
      {/* El JSON sigue estando para el caso raro —un objeto anidado— pero deja
          de ser lo primero que se ve. */}
      <button type="button" onClick={() => setCrudo(true)} className="btn-link mt-1">
        {t("formulario.editarComoJson")}
      </button>
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
