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
 * **Y un campo que apunta a otro registro se busca, no se teclea.** `cuenta_id`
 * no es un texto: es un cliente. Pedir que se escriba
 * `01a0cd8c-880c-7f85-96bc-0f01dce176a2` no es un formulario, es un volcado de
 * la base con una etiqueta encima — y era lo que pedía «convertir un lead»,
 * que es de las acciones más frecuentes que hay.
 *
 * **No valida reglas de negocio.** Marca lo obligatorio y respeta el tipo y la
 * longitud que declara el esquema, porque eso es contrato; cualquier otra regla
 * —«el descuento no puede pasar del 30 %»— la comprueba el servicio, y
 * duplicarla aquí sería tener dos versiones de la misma regla.
 */

import { useEffect, useMemo, useState, type FormEvent, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import { filas, llamar, salvoCancelacion } from "@/lib/api";
import type { CampoEsquema } from "@/lib/contrato";
import { humanizar, importe, nombreDelRegistro } from "@/lib/formato";
import type { Recurso } from "@/lib/modulos";
import { recursoDeReferencia } from "@/lib/referencias";
import { cn } from "@/lib/utiles";

export interface Props {
  campos: CampoEsquema[];
  /**
   * El recurso que se está editando, si se sabe.
   *
   * Hace falta para los campos que apuntan a otro registro **del mismo tipo**
   * —el `padre_id` de una campaña es otra campaña—: sin saber desde dónde se
   * edita, no hay contra qué resolverlos y salían como un identificador suelto.
   */
  recurso?: Recurso | null;
  valores?: Record<string, unknown>;
  enviando?: boolean;
  textoEnviar: string;
  alEnviar: (valores: Record<string, unknown>) => void;
}

export function Formulario({
  campos,
  valores = {},
  enviando,
  textoEnviar,
  alEnviar,
  recurso,
}: Props) {
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
          propio={recurso}
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
                  propio={recurso}
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
  propio,
}: {
  campo: CampoEsquema;
  valor: unknown;
  alCambiar: (valor: unknown) => void;
  /** El recurso desde el que se edita, para resolver las auto-referencias. */
  propio?: Recurso | null;
}) {
  const id = `campo-${campo.nombre}`;
  const ayuda = campo.descripcion ? `${id}-ayuda` : undefined;
  const referencia = recursoDeReferencia(campo.nombre, campo.referencia, propio);
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
      ) : referencia ? (
        <Referencia campo={campo} recurso={referencia} valor={valor} alCambiar={alCambiar} id={id} ayuda={ayuda} />
      ) : campo.tipo === "lineas" ? (
        <Lineas campo={campo} valor={valor} alCambiar={alCambiar} ayuda={ayuda} />
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
/**
 * Una lista de cosas con estructura, editada como una tabla.
 *
 * Es el último sitio donde quedaba JSON en la cara: las líneas de una oferta
 * se pedían como `[{"referencia":"L1","precio_venta":1000,"coste":700,
 * "cantidad":1}]` en un textarea. Quien hace un presupuesto no escribe eso, y
 * el que lo intente se equivocará en una coma y no sabrá por qué no se guarda.
 *
 * Las columnas salen del esquema de la línea, como todo lo demás aquí: una
 * lista escrita a mano se queda corta el día que el servicio añada el
 * descuento, y ese campo ya no se podría rellenar desde ninguna pantalla.
 *
 * Al pie va la **suma de cada columna numérica**. No es un total calculado —el
 * precio final lo decide el servicio, con sus impuestos y sus descuentos— y
 * por eso se llama suma: dar un total aquí sería inventarse una cifra que
 * luego no cuadra con la del documento.
 */
function Lineas({
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
  const filas = Array.isArray(valor) ? (valor as Record<string, unknown>[]) : [];
  const columnas = campo.subcampos;

  const cambiar = (indice: number, nombre: string, nuevo: unknown) =>
    alCambiar(filas.map((f, i) => (i === indice ? { ...f, [nombre]: nuevo } : f)));

  const sumas = columnas.map((c) =>
    c.tipo === "numero"
      ? filas.reduce((total, f) => total + (Number(f[c.nombre]) || 0), 0)
      : null,
  );
  const haySumas = sumas.some((s) => s !== null) && filas.length > 0;

  return (
    <div className="space-y-2" aria-describedby={ayuda}>
      {filas.length > 0 ? (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full text-sm">
            <thead className="bg-paper-sunk text-ink-muted">
              <tr>
                {columnas.map((c) => (
                  <th key={c.nombre} className="px-3 py-2 text-left font-medium">
                    {c.titulo}
                    {c.obligatorio ? <span className="text-danger"> *</span> : null}
                  </th>
                ))}
                <th className="w-10 px-2 py-2" />
              </tr>
            </thead>
            <tbody>
              {filas.map((fila, indice) => (
                <tr key={indice} className="border-t border-line">
                  {columnas.map((c) => (
                    <td key={c.nombre} className="px-2 py-1">
                      {c.opciones.length > 0 ? (
                        <select
                          aria-label={`${c.titulo}, línea ${indice + 1}`}
                          className="w-full rounded-lg border border-line bg-paper px-2 py-1"
                          value={String(fila[c.nombre] ?? "")}
                          onChange={(e) => cambiar(indice, c.nombre, e.target.value)}
                        >
                          <option value="">—</option>
                          {c.opciones.map((o) => (
                            <option key={o} value={o}>
                              {humanizar(o)}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          aria-label={`${c.titulo}, línea ${indice + 1}`}
                          className="w-full rounded-lg border border-line bg-paper px-2 py-1"
                          type={c.tipo === "numero" ? "number" : c.tipo === "fecha" ? "date" : "text"}
                          value={String(fila[c.nombre] ?? "")}
                          onChange={(e) =>
                            cambiar(
                              indice,
                              c.nombre,
                              c.tipo === "numero"
                                ? e.target.value === ""
                                  ? ""
                                  : Number(e.target.value)
                                : e.target.value,
                            )
                          }
                        />
                      )}
                    </td>
                  ))}
                  <td className="px-2 py-1 text-right">
                    <button
                      type="button"
                      className="rounded-lg px-2 py-1 text-ink-muted hover:bg-paper-sunk hover:text-danger"
                      aria-label={`Quitar la línea ${indice + 1}`}
                      onClick={() => alCambiar(filas.filter((_, i) => i !== indice))}
                    >
                      <Icono nombre="close" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            {haySumas ? (
              <tfoot className="border-t border-line bg-paper-sunk">
                <tr>
                  {columnas.map((c, i) => (
                    <td key={c.nombre} className="px-3 py-2 text-ink-muted">
                      {sumas[i] === null ? (i === 0 ? "Suma" : "") : importe(sumas[i] as number)}
                    </td>
                  ))}
                  <td />
                </tr>
              </tfoot>
            ) : null}
          </table>
        </div>
      ) : (
        <p className="text-sm text-ink-muted">Todavía no hay ninguna línea.</p>
      )}
      <button
        type="button"
        className="rounded-xl border border-line px-3 py-1.5 text-sm hover:bg-paper-sunk"
        onClick={() =>
          alCambiar([...filas, Object.fromEntries(columnas.map((c) => [c.nombre, ""]))])
        }
      >
        <Icono nombre="add" /> Añadir línea
      </button>
    </div>
  );
}

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

/**
 * Elegir un registro de otro recurso, buscándolo por su nombre.
 *
 * Trae las primeras doscientas filas y filtra en el navegador. No es una
 * búsqueda en el servidor y conviene decirlo: en una tabla de cien mil clientes
 * esto encuentra solo entre los doscientos primeros. Se hace así porque los
 * listados no publican todos un parámetro de búsqueda, y un buscador que
 * funciona en casi todos los recursos es mejor que uno que solo funciona en
 * tres — pero hay que cambiarlo en cuanto los listados lo admitan.
 */
function Referencia({
  campo,
  recurso,
  valor,
  alCambiar,
  id,
  ayuda,
}: {
  campo: CampoEsquema;
  recurso: Recurso;
  valor: unknown;
  alCambiar: (v: unknown) => void;
  id: string;
  ayuda?: string;
}) {
  const { t } = useTranslation();
  const [opciones, setOpciones] = useState<Record<string, unknown>[] | null>(null);
  const [busqueda, setBusqueda] = useState("");
  const [fallo, setFallo] = useState(false);

  useEffect(() => {
    const control = new AbortController();
    llamar<unknown>(`${recurso.listar}?limite=200`, { signal: control.signal })
      .then((r) => setOpciones(filas<Record<string, unknown>>(r.datos)))
      .catch(salvoCancelacion(() => setFallo(true)));
    return () => control.abort();
  }, [recurso.listar]);

  const elegido = opciones?.find((o) => String(o.id) === String(valor ?? ""));
  const filtradas = (opciones ?? []).filter((o) =>
    nombreDelRegistro(o).toLowerCase().includes(busqueda.trim().toLowerCase()),
  );

  if (fallo) {
    // Si el listado no se puede leer, se deja escribir el identificador en vez
    // de bloquear el formulario: quien tenga el identificador podrá seguir.
    return (
      <input
        id={id}
        aria-describedby={ayuda}
        required={campo.obligatorio}
        value={String(valor ?? "")}
        onChange={(e) => alCambiar(e.target.value)}
        placeholder={t("formulario.identificadorAMano")}
        className="input-base font-mono text-3xs"
      />
    );
  }

  return (
    <div>
      {elegido ? (
        <p className="mt-1 flex items-center gap-2">
          <span className="chip-dato chip-dato--si">{nombreDelRegistro(elegido)}</span>
          <button type="button" onClick={() => alCambiar("")} className="btn-link">
            {t("formulario.cambiar")}
          </button>
        </p>
      ) : (
        <>
          <input
            id={id}
            aria-describedby={ayuda}
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder={t("formulario.buscarRegistro", { recurso: recurso.nombre.toLowerCase() })}
            className="input-base"
            autoComplete="off"
          />
          {/* El valor real, para que el formulario lo siga exigiendo cuando es
              obligatorio: el buscador de arriba no es el campo. */}
          <input type="hidden" value={String(valor ?? "")} required={campo.obligatorio} readOnly />
          {opciones === null ? (
            <p className="mt-1 text-3xs text-ink-faint">{t("app.cargando")}</p>
          ) : (
            <ul className="mt-1 max-h-44 overflow-y-auto rounded-lg border border-ink-dim/60">
              {filtradas.slice(0, 40).map((o) => (
                <li key={String(o.id)}>
                  <button
                    type="button"
                    onClick={() => {
                      alCambiar(String(o.id));
                      setBusqueda("");
                    }}
                    className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-2xs text-ink hover:bg-paper-light"
                  >
                    <span className="truncate">{nombreDelRegistro(o) || String(o.id)}</span>
                  </button>
                </li>
              ))}
              {filtradas.length === 0 ? (
                <li className="px-2.5 py-2 text-3xs text-ink-faint">
                  {t("formulario.sinCoincidencias")}
                </li>
              ) : null}
            </ul>
          )}
        </>
      )}
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
