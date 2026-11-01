/**
 * El panel de datos clave de una ficha, y la ruta de etapas.
 *
 * Es la pieza que más se mira de un CRM y la que contecrm no tenía: al abrir un
 * registro había un título, un identificador recortado y, debajo, las pestañas.
 * Para saber en qué estado estaba una oportunidad, de quién era una cuenta o
 * cuándo vencía un caso había que entrar en la pestaña de datos y leer una
 * tabla de pares. Salesforce pone eso **arriba y siempre visible**, y por eso
 * su ficha se entiende de un vistazo. Se copia.
 *
 * Dos cosas:
 *
 * **Los datos clave.** Hasta cinco campos con su rótulo, en una fila. Cuáles
 * no es una lista nueva: son las `columnas` preferidas que el recurso ya
 * declara en `recursos.ts` —las mismas que salen en el listado—, quitando la
 * que da nombre al registro, que ya es el título. Si el producto decide que de
 * una oportunidad importan el importe y la etapa, importan en los dos sitios.
 *
 * **La ruta.** Cuando el registro tiene un campo de etapa, sus valores se
 * pintan como un camino con la posición actual marcada, en vez de como una
 * palabra suelta. Una etapa dice dónde estás; una ruta dice además **cuánto
 * queda y qué viene después**, que es la pregunta que de verdad se hace quien
 * mira una oportunidad.
 *
 * Qué campo es el de etapa lo decide `campoDeEtapa`, que reutiliza la misma
 * lista `AGRUPABLES` con la que el listado decide por qué campo agrupar en la
 * vista de columnas. Dos formas de detectar lo mismo acabarían discrepando, y
 * entonces el tablero y la ficha dirían cosas distintas del mismo registro.
 */

import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AGRUPABLES } from "@/componentes/Vistas";
import { camposDe, contratoDe, fichaDe, type CampoEsquema } from "@/lib/contrato";
import { escalar, humanizar, tieneDato, campoDelNombre } from "@/lib/formato";
import type { Recurso } from "@/lib/modulos";
import { cn } from "@/lib/utiles";

/** Cuántos datos clave caben sin que la fila deje de leerse de un vistazo. */
const CUANTOS = 5;

/**
 * El campo que lleva la etapa de este registro, si lo tiene.
 *
 * Tiene que ser una lista cerrada del contrato con al menos tres valores: con
 * dos no hay camino que recorrer —es un interruptor— y sin opciones declaradas
 * no se sabe ni el orden ni lo que falta, que es justo lo que aporta la ruta.
 */
export function campoDeEtapa(
  fila: Record<string, unknown>,
  campos: CampoEsquema[],
): CampoEsquema | null {
  for (const candidato of AGRUPABLES) {
    if (!(candidato in fila)) continue;
    const campo = campos.find((c) => c.nombre === candidato);
    if (campo && campo.opciones.length >= 3) return campo;
  }
  return null;
}

function Ruta({ campo, valor }: { campo: CampoEsquema; valor: string }) {
  const { t } = useTranslation();
  const actual = campo.opciones.indexOf(valor);
  return (
    <ol
      aria-label={t("ficha.ruta", { campo: humanizar(campo.nombre) })}
      className="flex min-w-0 flex-wrap items-stretch gap-px overflow-hidden rounded"
    >
      {campo.opciones.map((opcion, i) => {
        const hecha = actual >= 0 && i < actual;
        const aqui = i === actual;
        return (
          <li
            key={opcion}
            aria-current={aqui ? "step" : undefined}
            className={cn(
              "flex items-center whitespace-nowrap px-3 py-1 text-2xs",
              // Lo recorrido en azul, lo de ahora en azul oscuro y lo que
              // queda en gris. Tres tonos y no dos: sin el del medio no se
              // distingue dónde estás de lo que ya has pasado.
              aqui
                ? "bg-accent-soft font-semibold text-white"
                : hecha
                  ? "bg-accent/15 text-accent-text"
                  : "bg-paper-light text-ink-muted",
            )}
          >
            {humanizar(opcion)}
          </li>
        );
      })}
    </ol>
  );
}

export function DatosClave({
  recurso,
  tipo,
  nombre,
  fila,
  acciones,
}: {
  recurso: Recurso | undefined;
  /** El tipo del registro, que es lo que se pone encima del nombre. */
  tipo: string;
  nombre: string;
  fila: Record<string, unknown> | null;
  /** Editar, borrar y lo que el contrato permita. */
  acciones?: ReactNode;
}) {
  const { t } = useTranslation();
  const [campos, setCampos] = useState<CampoEsquema[]>([]);

  // El contrato está en caché, así que esto no cuesta una petición por ficha.
  // Se pide aquí y no se recibe por prop porque quien pinta la ficha no lo
  // tiene: sólo lo cargaba el formulario de edición, y sólo mientras editas.
  useEffect(() => {
    if (!recurso) return;
    let vivo = true;
    void contratoDe(recurso.servicio).then((documento) => {
      // La ruta del registro se le pide al contrato y no se compone: cada
      // servicio nombra su parámetro por su objeto —`{oportunidad_id}`—, así
      // que buscar `/{id}` no encuentra nada.
      const plantilla = fichaDe(documento, recurso.listar);
      if (vivo) setCampos(plantilla ? camposDe(documento, plantilla, "patch") : []);
    });
    return () => {
      vivo = false;
    };
  }, [recurso]);

  const etapa = fila ? campoDeEtapa(fila, campos) : null;
  const valorEtapa = etapa ? String(fila?.[etapa.nombre] ?? "") : "";

  // Los preferidos del recurso, quitando el que da nombre —ya es el título— y
  // la etapa, que se pinta como ruta y no como un par más.
  const titular = fila ? campoDelNombre(fila) : "";
  const clave = (recurso?.columnas ?? [])
    .filter((c) => c !== titular && c !== etapa?.nombre && !/_id$/.test(c))
    .filter((c) => fila && tieneDato(fila[c]))
    .slice(0, CUANTOS);

  return (
    <header className="card mb-4 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {/* El TIPO encima y en pequeño, el nombre debajo y grande: es el
              orden de Salesforce y resuelve una ambigüedad real —«Acme» puede
              ser una cuenta, un lead o un caso, y el título solo no lo dice. */}
          <p className="text-3xs font-semibold uppercase tracking-wide text-ink-faint">
            {humanizar(tipo)}
          </p>
          <h1 className="min-w-0 truncate text-xl-em font-bold tracking-[-0.01em] text-ink">
            {nombre || humanizar(tipo)}
          </h1>
        </div>
        {acciones ? <div className="flex shrink-0 items-center gap-2">{acciones}</div> : null}
      </div>

      {etapa && valorEtapa ? (
        <div className="mt-3">
          <Ruta campo={etapa} valor={valorEtapa} />
        </div>
      ) : null}

      {clave.length > 0 ? (
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 border-t border-ink-dim/50 pt-3 sm:grid-cols-3 lg:grid-cols-5">
          {clave.map((c) => (
            <div key={c} className="min-w-0">
              <dt className="truncate text-3xs text-ink-faint" title={humanizar(c)}>
                {humanizar(c)}
              </dt>
              <dd className="truncate text-sm text-ink" title={escalar(fila?.[c], c)}>
                {escalar(fila?.[c], c)}
              </dd>
            </div>
          ))}
        </dl>
      ) : fila === null ? (
        // Mientras carga no se pinta un esqueleto: el panel ya tiene su alto
        // con el título, y una fila de cajas grises que desaparece al segundo
        // mueve todo lo de abajo justo cuando alguien va a pulsar.
        <p className="sr-only">{t("app.cargando")}</p>
      ) : null}
    </header>
  );
}
