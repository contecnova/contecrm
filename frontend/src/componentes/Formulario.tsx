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

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { EditorDeCondiciones } from "@/componentes/EditorDeCondiciones";
import { ErrorApi, filas, llamar, salvoCancelacion } from "@/lib/api";
import type { CampoEsquema } from "@/lib/contrato";
import { cifra, nombreDelRegistro, rotuloDeOpcion } from "@/lib/formato";
import type { Recurso } from "@/lib/modulos";
import { moduloDeObjeto } from "@/lib/modulos";
import { recursoDeReferencia } from "@/lib/referencias";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utiles";
import {
  NO_SABE_BUSCAR,
  PAUSA_AL_TECLEAR_MS,
  rutaConBusqueda,
} from "@/lib/buscar";
import { useOpciones } from "@/lib/vocabularios";

/** Los tipos que ocupan las dos columnas de la rejilla. */
const ANCHOS = new Set([
  "texto_largo",
  "lineas",
  "objeto",
  "lista_multiple",
  "etiquetas",
]);

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
  /**
   * Lo que falló al guardar, si falló.
   *
   * Lo tiene la pantalla —es quien llama a la API— y se lo pasa al
   * formulario, que es quien sabe dónde va cada campo. Sin esto, un 422 que
   * dice exactamente qué campo falta acaba como un aviso genérico encima del
   * formulario, y quien lo lee tiene que adivinar cuál de veintinueve es.
   */
  fallo?: unknown;
  enviando?: boolean;
  textoEnviar: string;
  alEnviar: (valores: Record<string, unknown>) => void;
  /**
   * `forzar` no se ofrece como casilla: sólo como «Es otro, crearlo igual»
   * tras un 409 por duplicado. Lo pide el alta.
   */
  forzarTrasElAviso?: boolean;
  /**
   * Campos que van delante aunque no sean obligatorios: los que ya vienen
   * rellenos por el camino por el que se llegó. Un valor puesto y escondido
   * en «Más campos» no se ve, y lo que no se ve no se puede comprobar.
   */
  delante?: readonly string[];
}

export function Formulario({
  campos,
  valores = {},
  enviando,
  textoEnviar,
  alEnviar,
  recurso,
  fallo,
  forzarTrasElAviso = false,
  delante: pedidosDelante = [],
}: Props) {
  const { t } = useTranslation();
  /** Qué dijo el servidor de cada campo, por su nombre. */
  const fallosPorCampo = useMemo(() => {
    const mapa = new Map<string, string>();
    if (fallo instanceof ErrorApi) {
      for (const f of fallo.campos)
        if (!mapa.has(f.campo)) mapa.set(f.campo, f.mensaje);
    }
    return mapa;
  }, [fallo]);
  const [estado, setEstado] = useState<Record<string, unknown>>(valores);
  const [verOpcionales, setVerOpcionales] = useState(false);

  /**
   * Qué se enseña delante y qué se recoge en «Más campos».
   *
   * **Delante van los obligatorios.** Es lo correcto al dar de alta: lo que el
   * servidor exige, y lo demás detrás para no convertir un alta en una
   * declaración de la renta.
   *
   * **Pero al EDITAR no hay obligatorios.** El `PATCH` del contrato los
   * declara todos opcionales —se manda lo que se cambia—, así que la lista de
   * delante salía vacía y el formulario quedaba **sin un solo campo**: un
   * recuadro con «Más campos (29)», «Guardar cambios» y nada que guardar.
   * Medido el 03-11-2026 pulsando «Editar» en una oportunidad.
   *
   * Cuando no hay obligatorios, delante van las **columnas preferidas del
   * recurso**, que es la importancia que el producto ya declara y la misma
   * que usa el listado. Y si el recurso tampoco las declara, se enseñan
   * todos: un formulario que no enseña nada no es un formulario.
   */
  const { obligatorios, opcionales } = useMemo(() => {
    // En un alta, `forzar` no es un dato del registro: es la decisión de
    // crearlo aunque se parezca a otro, y se toma DESPUÉS de ver los
    // candidatos, con el botón del 409. Como casilla suelta entre los campos
    // invita a marcarla por si acaso y saltarse la deduplicación sin haber
    // visto nada. Sólo lo esconde quien lo pide: en otras operaciones
    // —mover de etapa saltando criterios— `forzar` es el formulario.
    const visibles = forzarTrasElAviso
      ? campos.filter((c) => c.nombre !== "forzar")
      : campos;
    const exigidos = visibles.filter((c) => c.obligatorio);
    const preferidas = new Set([
      ...(recurso?.columnas ?? []),
      ...(recurso?.alta ?? []),
    ]);
    if (exigidos.length > 0) {
      // **Y con ellos, lo que el recurso declara importante y lo que ya viene
      // relleno.** Con sólo los obligatorios, el alta de una oportunidad era
      // «Nombre» y nada más: el importe y la fecha de cierre —sin los que no
      // cuenta en ninguna previsión— iban detrás de «Más campos (10)», y había
      // que abrirlo en cada alta. Medido el 10-11-2026 (tarea T03).
      const ponerDelante = new Set([...preferidas, ...pedidosDelante]);
      const esDelante = (c: CampoEsquema) =>
        c.obligatorio || ponerDelante.has(c.nombre);
      return {
        obligatorios: visibles.filter(esDelante),
        opcionales: visibles.filter((c) => !esDelante(c)),
      };
    }
    const delanteDeclarado = new Set([...preferidas, ...pedidosDelante]);
    const delante = visibles.filter((c) => delanteDeclarado.has(c.nombre));
    if (delante.length === 0) return { obligatorios: visibles, opcionales: [] };
    return {
      obligatorios: delante,
      opcionales: visibles.filter((c) => !delanteDeclarado.has(c.nombre)),
    };
    // `pedidosDelante` por su contenido: llega como una lista nueva en cada
    // pintado y, por referencia, recalcularía esto a cada tecla.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campos, recurso, forzarTrasElAviso, pedidosDelante.join(",")]);

  function enviar(evento: FormEvent) {
    evento.preventDefault();
    alEnviar(limpiar());
  }

  /**
   * «Es otro, crearlo igual» (CRM-01.01.03.03).
   *
   * El servidor contesta 409 con los candidatos cuando lo que se da de alta se
   * parece demasiado a algo que ya existe —una cuenta con el mismo NIF, un
   * contacto con el mismo correo, un lead que ya escribió—, y dice cómo
   * seguir: usar el que hay o repetir con `forzar`. El formulario no ofrecía
   * lo segundo en ningún alta, así que un caso legítimo —dos sociedades del
   * mismo grupo— no tenía salida desde la pantalla. Se ofrece **sólo si el
   * alta admite `forzar`**: un botón que el servidor va a rechazar es peor que
   * no tenerlo.
   */
  const duplicado = useMemo(() => candidatosDe(fallo), [fallo]);
  const admiteForzar = campos.some(
    (c) => c.nombre === "forzar" && c.tipo === "booleano",
  );

  function limpiar(): Record<string, unknown> {
    // Se quitan los vacíos que no son obligatorios: mandar cadenas vacías
    // sobrescribiría con "" campos que el servidor tenía a nulo, y eso borra
    // datos sin que nadie lo haya pedido.
    const limpio: Record<string, unknown> = {};
    for (const campo of campos) {
      const valor = estado[campo.nombre];
      // Una casilla no tiene «vacío»: sin marcar es `false`, que es lo que
      // enseña. Se mandaba `undefined` —que el JSON se come— y una acción
      // con un único booleano obligatorio salía como `{}` y volvía con 422
      // «activa: Falta este campo». Medido el 09-11-2026 al apagar una
      // automatización desde su ficha.
      if (campo.tipo === "booleano" && valor === undefined) {
        if (campo.obligatorio) limpio[campo.nombre] = false;
        continue;
      }
      const vacio =
        valor === undefined ||
        valor === "" ||
        (Array.isArray(valor) && valor.length === 0) ||
        (valor !== null &&
          typeof valor === "object" &&
          Object.keys(valor).length === 0);
      if (vacio) {
        if (campo.obligatorio) limpio[campo.nombre] = valor;
        continue;
      }
      limpio[campo.nombre] = valor;
    }
    return limpio;
  }

  if (campos.length === 0) {
    // Se dice, no se enseña un formulario vacío: uno vacío presentado como
    // «este recurso no pide nada» haría crear registros incompletos.
    return (
      <p className="text-dato text-ink-faint">{t("formulario.sinContrato")}</p>
    );
  }

  const cambiar = (nombre: string) => (v: unknown) =>
    setEstado((previo) => ({ ...previo, [nombre]: v }));

  // Las condiciones de una regla miran campos de SU objetivo: con él escrito,
  // el editor ofrece los campos propios de ese objeto (CRM-00.04.03.05).
  const objetoDeCondiciones = campos.some((c) => c.nombre === "objetivo")
    ? String(estado.objetivo ?? "")
    : undefined;

  return (
    <form onSubmit={enviar} className="flex flex-col gap-4">
      {/* Dos columnas en cuanto hay sitio. Una sola a ochocientos píxeles de
          ancho hace que un email ocupe lo mismo que una descripción, y un alta
          de treinta campos se va al doble de largo. Lo que necesita el ancho
          entero lo pide él (`campo-ancho`). */}
      <div className="rejilla-formulario">
        {obligatorios.map((campo) => (
          <Campo
            key={campo.nombre}
            campo={campo}
            valor={estado[campo.nombre]}
            alCambiar={cambiar(campo.nombre)}
            propio={recurso}
            fallo={fallosPorCampo.get(campo.nombre)}
            objetoDeCondiciones={objetoDeCondiciones}
          />
        ))}
      </div>

      {opcionales.length > 0 ? (
        <div className="border-t border-ink-dim/30 pt-3">
          <button
            type="button"
            onClick={() => setVerOpcionales((v) => !v)}
            aria-expanded={verOpcionales}
            className="inline-flex items-center gap-1.5 text-dato text-ink-muted hover:text-ink"
          >
            <Icono
              nombre="keyboard_arrow_down"
              tamano="sm"
              className={cn(
                "transition-transform",
                !verOpcionales && "-rotate-90",
              )}
            />
            {t("formulario.masCampos", { total: opcionales.length })}
          </button>
          {verOpcionales ? (
            <div className="rejilla-formulario mt-3">
              {opcionales.map((campo) => (
                <Campo
                  key={campo.nombre}
                  campo={campo}
                  valor={estado[campo.nombre]}
                  alCambiar={cambiar(campo.nombre)}
                  propio={recurso}
                  fallo={fallosPorCampo.get(campo.nombre)}
                  objetoDeCondiciones={objetoDeCondiciones}
                />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {duplicado ? (
        <div
          role="status"
          className="rounded-lg border border-warning/40 bg-warning/5 p-3"
        >
          <p className="text-dato font-medium text-ink">
            {duplicado.explicacion || t("formulario.pareceDuplicado")}
          </p>
          <ul className="mt-2 divide-y divide-ink-dim/30">
            {duplicado.candidatos.map((c) => {
              const objeto = c.objeto || recurso?.objeto || "";
              const modulo = objeto ? moduloDeObjeto(objeto) : "";
              return (
                <li
                  key={`${objeto}-${c.id}`}
                  className="flex flex-wrap items-baseline gap-x-3 py-1.5"
                >
                  {modulo ? (
                    <Link
                      to={`/m/${modulo}/${objeto}/${c.id}`}
                      className="text-dato text-accent hover:underline"
                    >
                      {c.nombre || c.id}
                    </Link>
                  ) : (
                    <span className="text-dato text-ink">
                      {c.nombre || c.id}
                    </span>
                  )}
                  {c.objeto ? (
                    <span className="chip-dato">{c.objeto}</span>
                  ) : null}
                  <span className="text-rotulo text-ink-faint">
                    {t("formulario.coincide", {
                      senales: c.senales.join(", "),
                      parecido: Math.round(c.similitud * 100),
                    })}
                  </span>
                  {c.concluyente ? (
                    <span className="chip-dato chip-dato--aviso">
                      {t("formulario.concluyente")}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
          {duplicado.sinContactos ? (
            <p className="mt-2 text-rotulo text-warning">
              {t("formulario.sinMirarContactos")}
            </p>
          ) : null}
          {admiteForzar ? (
            <button
              type="button"
              disabled={enviando}
              onClick={() => alEnviar({ ...limpiar(), forzar: true })}
              className="btn-secondary mt-3"
            >
              {t("formulario.esOtroCrearIgual")}
            </button>
          ) : null}
        </div>
      ) : null}

      <button
        type="submit"
        disabled={enviando}
        className="btn-primary mt-1 self-start"
      >
        {enviando ? t("app.cargando") : textoEnviar}
      </button>
    </form>
  );
}

/** Un registro que el servidor dice que podría ser el que se está dando de alta. */
export interface CandidatoDuplicado {
  id: string;
  nombre: string;
  objeto: string;
  similitud: number;
  senales: string[];
  concluyente: boolean;
}

/**
 * Los candidatos de un 409 por duplicado, o `null` si el fallo es otra cosa.
 *
 * Se mira la FORMA del detalle —una lista `candidatos`— y no el código de
 * error: cuentas, contactos y leads responden cada uno con el suyo, y una
 * lista de códigos se queda corta con el siguiente objeto que deduplique.
 */
export function candidatosDe(fallo: unknown): {
  explicacion: string;
  candidatos: CandidatoDuplicado[];
  sinContactos: boolean;
} | null {
  if (!(fallo instanceof ErrorApi) || fallo.estado !== 409) return null;
  const detalle = (fallo.detalle ?? {}) as Record<string, unknown>;
  if (!Array.isArray(detalle.candidatos)) return null;
  const candidatos = (detalle.candidatos as Record<string, unknown>[]).map(
    (c) => ({
      id: String(c.id ?? ""),
      nombre: String(c.nombre ?? ""),
      objeto: String(c.objeto ?? ""),
      similitud: Number(c.similitud ?? 0),
      senales: Array.isArray(c.senales) ? c.senales.map(String) : [],
      concluyente: Boolean(c.concluyente),
    }),
  );
  return {
    explicacion: fallo.explicacion,
    candidatos,
    sinContactos: detalle.contactos_consultados === false,
  };
}

function Campo({
  campo,
  valor,
  alCambiar,
  propio,
  fallo,
  objetoDeCondiciones,
}: {
  campo: CampoEsquema;
  valor: unknown;
  alCambiar: (valor: unknown) => void;
  /** El recurso desde el que se edita, para resolver las auto-referencias. */
  propio?: Recurso | null;
  /** Lo que el servidor dice de ESTE campo, si ha dicho algo. */
  fallo?: string;
  /** El objeto de la regla, si el formulario lo pide: ver `EditorDeCondiciones`. */
  objetoDeCondiciones?: string;
}) {
  const id = `campo-${campo.nombre}`;
  const ayuda = campo.descripcion ? `${id}-ayuda` : undefined;
  const idFallo = fallo ? `${id}-fallo` : undefined;
  const referencia = recursoDeReferencia(
    campo.nombre,
    campo.referencia,
    propio,
  );
  const comun = {
    id,
    // Los dos: la ayuda dice qué poner y el fallo qué pasó. Quedarse con uno
    // deja a quien no ve la pantalla sin una de las dos.
    "aria-describedby": [ayuda, idFallo].filter(Boolean).join(" ") || undefined,
    "aria-invalid": fallo ? true : undefined,
    required: campo.obligatorio,
    className: cn("input-base", fallo && "border-danger"),
  };

  return (
    // Lo que necesita el ancho entero lo pide. Un texto largo, una lista de
    // líneas o un objeto en media columna se convierten en una caja estrecha
    // con scroll, que es peor que no partir el formulario.
    <div className={cn(ANCHOS.has(campo.tipo) && "campo-ancho")}>
      {/* El booleano pone su propia etiqueta al lado de la casilla: encima, y a
          dos centímetros, no se sabe qué se está marcando. */}
      {campo.tipo !== "booleano" ? (
        <label htmlFor={id} className="label-base">
          {campo.titulo}
          {/* Sin asterisco. Los obligatorios van en su propio grupo y los
              opcionales en otro, así que marcar cada uno con un asterisco rojo
              no distingue nada: en el primer grupo lo llevan todos. Lo que
              separa los dos grupos es dónde están, que se ve sin leer. */}
        </label>
      ) : null}

      {/* La ayuda ENCIMA del campo, no debajo.
          Debajo llega cuando ya se ha escrito: «el nombre comercial con el que
          factura» sirve para decidir qué poner, no para comprobarlo después. */}
      {campo.descripcion && campo.tipo !== "booleano" ? (
        <p id={ayuda} className="mb-1 text-rotulo text-ink-faint">
          {campo.descripcion}
        </p>
      ) : null}

      {/* Lo que el servidor dice de este campo, PEGADO al campo. Antes se
          perdía: la respuesta trae `errors: [{campo, mensaje}]` y el cliente
          se quedaba sólo con el título —«Los datos enviados no son
          válidos»—, así que la pantalla decía que algo estaba mal y no cuál.
          Medido el 03-11-2026 dando de alta un segmento: faltaba
          «definicion» y en pantalla no salía esa palabra por ningún lado. */}
      {fallo ? (
        <p id={idFallo} className="mb-1 text-rotulo text-danger" role="alert">
          {fallo}
        </p>
      ) : null}

      {campo.tipo === "booleano" ? (
        // `py-1.5` para que la casilla caiga a la altura de la caja de al
        // lado: sin eso flota a media celda y la fila se lee torcida.
        <label
          htmlFor={id}
          className="inline-flex items-center gap-2 py-1.5 text-titulin text-ink"
        >
          <input
            type="checkbox"
            id={id}
            aria-describedby={ayuda}
            // Sin tocar, lo que hará el servidor: una casilla vacía que el
            // servidor lee como «sí» dice lo contrario de lo que va a pasar.
            checked={
              valor === undefined ? campo.porDefecto === true : Boolean(valor)
            }
            onChange={(e) => alCambiar(e.target.checked)}
            className="h-4 w-4 rounded border-ink-dim accent-accent"
          />
          {campo.titulo}
        </label>
      ) : campo.tipo === "lista" ? (
        <Desplegable
          comun={comun}
          campo={campo}
          valor={valor}
          alCambiar={alCambiar}
        />
      ) : campo.tipo === "lista_multiple" ? (
        <Opciones
          campo={campo}
          valor={valor}
          alCambiar={alCambiar}
          ayuda={ayuda}
        />
      ) : campo.tipo === "etiquetas" ? (
        <Etiquetas
          campo={campo}
          valor={valor}
          alCambiar={alCambiar}
          id={id}
          ayuda={ayuda}
        />
      ) : referencia ? (
        <Referencia
          campo={campo}
          recurso={referencia}
          valor={valor}
          alCambiar={alCambiar}
          id={id}
          ayuda={ayuda}
        />
      ) : campo.nombre === "condiciones" &&
        objetoDeCondiciones !== undefined &&
        (campo.tipo === "objeto" || campo.tipo === "lineas") ? (
        <EditorDeCondiciones
          id={id}
          valor={valor}
          alCambiar={alCambiar}
          objeto={objetoDeCondiciones}
          ayuda={ayuda}
        />
      ) : campo.tipo === "lineas" ? (
        <Lineas
          campo={campo}
          valor={valor}
          alCambiar={alCambiar}
          ayuda={ayuda}
        />
      ) : campo.tipo === "objeto" ? (
        <Pares
          campo={campo}
          valor={valor}
          alCambiar={alCambiar}
          id={id}
          ayuda={ayuda}
        />
      ) : campo.tipo === "texto_largo" ? (
        // Tres líneas y no cuatro: con cuatro, tres campos de prosa seguidos ya
        // no caben en la pantalla y el formulario se recorre a rueda. Crece al
        // escribir, así que lo que se gana en el caso corto no se pierde en el
        // largo.
        <textarea
          {...comun}
          rows={3}
          maxLength={campo.maximo ?? undefined}
          value={String(valor ?? "")}
          onChange={(e) => alCambiar(e.target.value)}
        />
      ) : (
        <input
          {...comun}
          type={
            campo.tipo === "numero"
              ? "number"
              : campo.tipo === "fecha"
                ? "date"
                : "text"
          }
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
    </div>
  );
}

/** Lista de opciones cerradas: se marcan, no se escriben. */
export function Opciones({
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
  // Un desplegable con casillas, no un muro de casillas a la vista: con doce
  // opciones el formulario se llenaba de algo que casi nunca se toca. Cerrado
  // dice lo elegido; abierto, se marca y se desmarca sin que se cierre.
  const { t } = useTranslation();
  const puestos = Array.isArray(valor) ? valor.map(String) : [];
  const [abierto, setAbierto] = useState(false);
  const caja = useRef<HTMLDivElement>(null);
  const disparador = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!abierto) return;
    function alPulsar(e: MouseEvent) {
      if (!caja.current?.contains(e.target as Node)) setAbierto(false);
    }
    function alTeclear(e: globalThis.KeyboardEvent) {
      if (e.key !== "Escape") return;
      setAbierto(false);
      disparador.current?.focus();
    }
    document.addEventListener("mousedown", alPulsar);
    document.addEventListener("keydown", alTeclear);
    return () => {
      document.removeEventListener("mousedown", alPulsar);
      document.removeEventListener("keydown", alTeclear);
    };
  }, [abierto]);

  const resumen = puestos.map((o) => rotuloDeOpcion(o)).join(", ");
  return (
    <div className="relative" ref={caja}>
      <button
        ref={disparador}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={abierto}
        aria-describedby={ayuda}
        aria-label={campo.titulo}
        onClick={() => setAbierto((v) => !v)}
        className="input-base flex items-center justify-between gap-2 text-left"
      >
        <span
          className={cn("truncate", resumen ? "text-ink" : "text-ink-faint")}
        >
          {resumen || t("formulario.elegirVarios")}
        </span>
        <Icono nombre={abierto ? "expand_less" : "expand_more"} tamano="sm" />
      </button>
      {abierto ? (
        <ul
          role="listbox"
          aria-multiselectable="true"
          aria-label={campo.titulo}
          className="absolute left-0 right-0 z-popover mt-1 max-h-64 overflow-y-auto rounded-xl border border-ink-dim/60 bg-paper p-1 shadow-elevation-3"
        >
          {campo.opciones.map((opcion) => {
            const marcada = puestos.includes(opcion);
            return (
              <li key={opcion} role="option" aria-selected={marcada}>
                <label className="flex cursor-pointer items-center gap-2 rounded px-3 py-1.5 text-dato text-ink hover:bg-paper-light">
                  <input
                    type="checkbox"
                    checked={marcada}
                    onChange={(e) =>
                      alCambiar(
                        e.target.checked
                          ? [...puestos, opcion]
                          : puestos.filter((p) => p !== opcion),
                      )
                    }
                    className="h-4 w-4 rounded border-ink-dim accent-accent"
                  />
                  {rotuloDeOpcion(opcion)}
                </label>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
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
  const { t } = useTranslation();
  const filas = Array.isArray(valor)
    ? (valor as Record<string, unknown>[])
    : [];
  const columnas = campo.subcampos;

  // Una celda vacía no se manda: `""` donde el servicio espera un número o
  // una lista es un 422, y lo que no se rellena debe tomar su valor por defecto.
  const cambiar = (indice: number, nombre: string, nuevo: unknown) =>
    alCambiar(
      filas.map((f, i) => {
        if (i !== indice) return f;
        const resto = { ...f };
        delete resto[nombre];
        return nuevo === "" ? resto : { ...resto, [nombre]: nuevo };
      }),
    );

  const sumas = columnas.map((c) =>
    c.tipo === "numero"
      ? filas.reduce((total, f) => total + (Number(f[c.nombre]) || 0), 0)
      : null,
  );
  const haySumas = sumas.some((s) => s !== null) && filas.length > 0;

  return (
    <div className="space-y-2" aria-describedby={ayuda}>
      {filas.length > 0 ? (
        // El armazón de la casa, no una tabla a mano: aquí estaba escrita
        // con `text-titulo` clavado, mientras la tabla de resultados usaba
        // `text-dato` y la de un listado el token de densidad. Tres tamaños
        // para lo mismo — la divergencia que `Rejilla` vino a cerrar y que se
        // había vuelto a abrir en dos sitios. Medido el 03-11-2026.
        //
        // Sin acotar: un formulario no se recorre con barra propia, se
        // rellena de arriba abajo.
        <Rejilla
          acotada={false}
          pie={
            haySumas ? (
              <tr>
                {columnas.map((c, i) => (
                  <Casilla key={c.nombre} className="text-ink-muted">
                    {sumas[i] === null
                      ? i === 0
                        ? t("formulario.suma")
                        : ""
                      : cifra(sumas[i] as number)}
                  </Casilla>
                ))}
                <Casilla />
              </tr>
            ) : null
          }
          cabeceras={[
            ...columnas.map((c) => (
              <span key={c.nombre}>
                {c.titulo}
                {c.obligatorio ? <span className="text-danger"> *</span> : null}
              </span>
            )),
            <span key="quitar" className="sr-only">
              {t("formulario.quitarLinea")}
            </span>,
          ]}
        >
          {filas.map((fila, indice) => (
            <tr key={indice} className="border-t border-ink-dim/30">
              {columnas.map((c) => (
                <td key={c.nombre} className="px-2 py-1">
                  {c.tipo === "booleano" ? (
                    // Sí o no es una casilla: escrito a mano llegaba como
                    // texto y el servicio lo rechazaba.
                    <input
                      type="checkbox"
                      aria-label={`${c.titulo}, línea ${indice + 1}`}
                      checked={fila[c.nombre] === true}
                      onChange={(e) =>
                        cambiar(indice, c.nombre, e.target.checked)
                      }
                    />
                  ) : c.tipo === "lista_multiple" ? (
                    <Opciones
                      campo={c}
                      valor={fila[c.nombre]}
                      alCambiar={(v) => cambiar(indice, c.nombre, v)}
                    />
                  ) : c.tipo === "etiquetas" ? (
                    // Una lista de textos, separada por comas, y se manda como
                    // lista: un texto donde va una lista daba 422 siempre.
                    <input
                      aria-label={`${c.titulo}, línea ${indice + 1}`}
                      className="w-full rounded-lg border border-ink-dim/60 bg-paper px-2 py-1"
                      value={
                        Array.isArray(fila[c.nombre])
                          ? (fila[c.nombre] as unknown[]).join(", ")
                          : String(fila[c.nombre] ?? "")
                      }
                      placeholder={t("formulario.separadoPorComas")}
                      onChange={(e) =>
                        cambiar(
                          indice,
                          c.nombre,
                          e.target.value
                            .split(",")
                            .map((s) => s.trim())
                            .filter(Boolean),
                        )
                      }
                    />
                  ) : c.opciones.length > 0 ? (
                    <select
                      aria-label={`${c.titulo}, línea ${indice + 1}`}
                      className="w-full rounded-lg border border-ink-dim/60 bg-paper px-2 py-1"
                      value={String(fila[c.nombre] ?? "")}
                      onChange={(e) =>
                        cambiar(indice, c.nombre, e.target.value)
                      }
                    >
                      <option value="">—</option>
                      {c.opciones.map((o) => (
                        <option key={o} value={o}>
                          {rotuloDeOpcion(o)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      aria-label={`${c.titulo}, línea ${indice + 1}`}
                      className="w-full rounded-lg border border-ink-dim/60 bg-paper px-2 py-1"
                      type={
                        c.tipo === "numero"
                          ? "number"
                          : c.tipo === "fecha"
                            ? "date"
                            : "text"
                      }
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
                  onClick={() =>
                    alCambiar(filas.filter((_, i) => i !== indice))
                  }
                >
                  <Icono nombre="close" />
                </button>
              </td>
            </tr>
          ))}
        </Rejilla>
      ) : (
        <p className="text-titulo text-ink-muted">
          {t("formulario.sinLineas")}
        </p>
      )}
      <button
        type="button"
        className="rounded-xl border border-ink-dim/60 px-3 py-1.5 text-titulo hover:bg-paper-sunk"
        onClick={() =>
          alCambiar([
            ...filas,
            // Vacía de verdad: sólo las casillas, que valen «no».
            Object.fromEntries(
              columnas
                .filter((c) => c.tipo === "booleano")
                .map((c) => [c.nombre, false]),
            ),
          ])
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
      return Object.entries(valor as Record<string, unknown>).map(([k, v]) => [
        k,
        String(v),
      ]);
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
          value={
            typeof valor === "string"
              ? valor
              : JSON.stringify(valor ?? {}, null, 2)
          }
          onChange={(e) => alCambiar(intentarJson(e.target.value))}
          className="input-base font-mono text-rotulo"
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
      <div
        id={id}
        aria-describedby={ayuda}
        className="mt-1 flex flex-col gap-1.5"
      >
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
      <button
        type="button"
        onClick={() => setCrudo(true)}
        className="btn-link mt-1"
      >
        {t("formulario.editarComoJson")}
      </button>
    </div>
  );
}

/**
 * Una lista cerrada: la del contrato, o la del vocabulario de la empresa.
 *
 * El valor viaja tal cual; lo que se lee es el rótulo: «Descuento tardío», no
 * «descuento_tardio»; y en un vocabulario, el que le haya puesto la empresa.
 */
function Desplegable({
  comun,
  campo,
  valor,
  alCambiar,
}: {
  comun: Record<string, unknown>;
  campo: CampoEsquema;
  valor: unknown;
  alCambiar: (v: unknown) => void;
}) {
  const { t } = useTranslation();
  const opciones = useOpciones(campo, valor);
  return (
    <select
      {...comun}
      value={String(valor ?? "")}
      onChange={(e) => alCambiar(e.target.value)}
    >
      <option value="">{opciones === null ? t("app.cargando") : "—"}</option>
      {(opciones ?? []).map((o) => (
        <option key={o.valor} value={o.valor}>
          {o.etiqueta}
        </option>
      ))}
    </select>
  );
}

/**
 * Elegir un registro de otro recurso: un desplegable con buscador.
 *
 * Cerrado es un campo más del formulario, con el nombre de lo elegido; abierto,
 * una capa con el buscador arriba y las opciones debajo, con el mismo aspecto
 * que el selector de vistas de las listas. Hasta el 05-11-2026 era un buscador
 * con la lista siempre abierta debajo, cuarenta filas ocupando el formulario
 * aunque no se fuera a tocar el campo: lo vio quien lo usa y tenía razón.
 *
 * Al abrir enseña las primeras filas, para elegir sin escribir. **Lo que se
 * escribe se busca en el servidor** (`?buscar=`): antes filtraba esas
 * doscientas en el navegador, y con más clientes el que se buscaba no salía
 * —medido el 10-11-2026—. Mientras llega la respuesta se filtra lo que hay,
 * para que la lista no se quede quieta; y un listado que no sabe buscar
 * (`NO_SABE_BUSCAR`) sigue filtrando lo cargado, como antes.
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
  const [opciones, setOpciones] = useState<Record<string, unknown>[] | null>(
    null,
  );
  const [busqueda, setBusqueda] = useState("");
  // Lo que contestó el servidor a lo escrito, y si ese listado sabe buscar.
  const [encontradas, setEncontradas] = useState<
    Record<string, unknown>[] | null
  >(null);
  const [buscaEnServidor, setBuscaEnServidor] = useState(true);
  // El elegido, guardado: puede venir de una búsqueda y no estar entre las
  // primeras filas, y entonces el campo no sabría cómo se llama.
  const [elegidoAhora, setElegidoAhora] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [fallo, setFallo] = useState(false);
  const [abierto, setAbierto] = useState(false);
  const [activa, setActiva] = useState(0);
  const caja = useRef<HTMLDivElement>(null);
  const disparador = useRef<HTMLButtonElement>(null);
  const buscador = useRef<HTMLInputElement>(null);
  const lista = `${id}-opciones`;

  // Al abrir, el foco va al buscador: se abre para buscar. Con un efecto y no
  // con `autoFocus`, que también lo pondría al montar la página.
  useEffect(() => {
    if (abierto) buscador.current?.focus();
  }, [abierto]);

  useEffect(() => {
    const control = new AbortController();
    // Con `limite` para traer bastantes, y sin él si la ruta no lo admite: el
    // árbol de categorías de caso contestaba 422 («esta operación no mira
    // limite») y el desplegable se quedaba vacío. Medido el 10-11-2026 al abrir
    // un caso: la categoría no se podía elegir.
    llamar<unknown>(`${recurso.listar}?limite=200`, { signal: control.signal })
      .catch((error: unknown) => {
        if (
          error instanceof ErrorApi &&
          error.codigo === "peticion.parametro_desconocido"
        )
          return llamar<unknown>(recurso.listar, { signal: control.signal });
        throw error;
      })
      .then((r) => setOpciones(filas<Record<string, unknown>>(r.datos)))
      .catch(salvoCancelacion(() => setFallo(true)));
    return () => control.abort();
  }, [recurso.listar]);

  useEffect(() => {
    const texto = busqueda.trim();
    if (!texto || !buscaEnServidor) {
      setEncontradas(null);
      return;
    }
    const control = new AbortController();
    const espera = window.setTimeout(() => {
      llamar<unknown>(rutaConBusqueda(recurso.listar, texto, 50), {
        signal: control.signal,
      })
        .then((r) => setEncontradas(filas<Record<string, unknown>>(r.datos)))
        .catch(
          salvoCancelacion((error: unknown) => {
            // Si no sabe buscar, se filtra lo cargado; cualquier otro fallo
            // también, pero sin dejar de intentarlo con lo siguiente.
            if (error instanceof ErrorApi && NO_SABE_BUSCAR.has(error.codigo))
              setBuscaEnServidor(false);
            setEncontradas(null);
          }),
        );
    }, PAUSA_AL_TECLEAR_MS);
    return () => {
      window.clearTimeout(espera);
      control.abort();
    };
  }, [busqueda, buscaEnServidor, recurso.listar]);

  useEffect(() => {
    if (!abierto) return;
    function alPulsar(e: MouseEvent) {
      if (!caja.current?.contains(e.target as Node)) setAbierto(false);
    }
    document.addEventListener("mousedown", alPulsar);
    return () => document.removeEventListener("mousedown", alPulsar);
  }, [abierto]);

  const elegido =
    opciones?.find((o) => String(o.id) === String(valor ?? "")) ??
    (elegidoAhora && String(elegidoAhora.id) === String(valor ?? "")
      ? elegidoAhora
      : undefined);
  const filtradas = (
    encontradas ??
    (opciones ?? []).filter((o) =>
      nombreDelRegistro(o)
        .toLowerCase()
        .includes(busqueda.trim().toLowerCase()),
    )
  ).slice(0, 50);

  function cerrar() {
    setAbierto(false);
    setBusqueda("");
    // El foco vuelve al campo: si se queda en el aire, quien va con teclado
    // tiene que recorrer el formulario entero para volver aquí.
    disparador.current?.focus();
  }

  function elegir(o: Record<string, unknown>) {
    setElegidoAhora(o);
    alCambiar(String(o.id));
    cerrar();
  }

  function alTeclear(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiva((i) => Math.min(i + 1, filtradas.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiva((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      // Enter elige; no envía el formulario a medias.
      e.preventDefault();
      const o = filtradas[activa];
      if (o) elegir(o);
    } else if (e.key === "Escape") {
      e.preventDefault();
      cerrar();
    }
  }

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
        className="input-base font-mono text-rotulo"
      />
    );
  }

  const rotulo = elegido
    ? nombreDelRegistro(elegido) || String(elegido.id)
    : valor
      ? // Elegido pero fuera de los doscientos primeros: se dice, y no se
        // enseña el campo como vacío.
        t("formulario.registroFueraDeLista")
      : "";

  return (
    <div className="relative" ref={caja}>
      <div className="relative">
        <button
          ref={disparador}
          id={id}
          type="button"
          role="combobox"
          aria-haspopup="listbox"
          aria-expanded={abierto}
          aria-controls={lista}
          aria-describedby={ayuda}
          onClick={() => {
            setActiva(0);
            setAbierto((v) => !v);
          }}
          className="input-base flex items-center justify-between gap-2 pr-16 text-left"
        >
          <span
            className={cn("truncate", rotulo ? "text-ink" : "text-ink-faint")}
          >
            {opciones === null && !rotulo
              ? t("app.cargando")
              : rotulo ||
                t("formulario.elegirRegistro", { recurso: recurso.nombre })}
          </span>
        </button>
        <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-faint">
          <Icono nombre={abierto ? "expand_less" : "expand_more"} tamano="sm" />
        </span>
        {valor && !campo.obligatorio ? (
          <button
            type="button"
            onClick={() => alCambiar("")}
            aria-label={t("formulario.quitarEleccion", { campo: campo.titulo })}
            className="absolute right-8 top-1/2 -translate-y-1/2 rounded p-0.5 text-ink-faint hover:text-ink"
          >
            <Icono nombre="close" tamano="sm" />
          </button>
        ) : null}
      </div>
      {/* El valor real, para que el formulario lo siga exigiendo cuando es
          obligatorio: el botón de arriba no es el campo. */}
      <input
        type="hidden"
        value={String(valor ?? "")}
        required={campo.obligatorio}
        readOnly
      />
      {abierto ? (
        <div className="absolute left-0 right-0 z-popover mt-1 rounded-xl border border-ink-dim/60 bg-paper p-1 shadow-elevation-3">
          <input
            ref={buscador}
            value={busqueda}
            onChange={(e) => {
              setBusqueda(e.target.value);
              setActiva(0);
            }}
            onKeyDown={alTeclear}
            placeholder={t("formulario.buscarEnLista")}
            aria-label={t("formulario.buscarEnLista")}
            aria-controls={lista}
            aria-activedescendant={
              filtradas[activa] ? `${lista}-${activa}` : undefined
            }
            className="input-base mb-1"
            autoComplete="off"
          />
          <ul
            id={lista}
            role="listbox"
            aria-label={campo.titulo}
            className="max-h-64 overflow-y-auto"
          >
            {opciones === null ? (
              <li className="px-3 py-1.5 text-rotulo text-ink-faint">
                {t("app.cargando")}
              </li>
            ) : filtradas.length === 0 ? (
              <li className="px-3 py-1.5 text-rotulo text-ink-faint">
                {t("formulario.sinCoincidencias")}
              </li>
            ) : (
              filtradas.map((o, i) => {
                const marcada = String(o.id) === String(valor ?? "");
                return (
                  <li
                    key={String(o.id)}
                    id={`${lista}-${i}`}
                    role="option"
                    aria-selected={marcada}
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setActiva(i)}
                    onClick={() => elegir(o)}
                    // El teclado va por el buscador (flechas e Intro, con
                    // `aria-activedescendant`); esto cubre a quien llegue a
                    // la opción por otro camino, como un lector de pantalla.
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        elegir(o);
                      }
                    }}
                    className={cn(
                      "cursor-pointer truncate rounded px-3 py-1.5 text-dato",
                      marcada
                        ? "bg-accent/10 font-semibold text-accent"
                        : i === activa
                          ? "bg-paper-light text-ink"
                          : "text-ink",
                    )}
                  >
                    {nombreDelRegistro(o) || String(o.id)}
                  </li>
                );
              })
            )}
          </ul>
        </div>
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
