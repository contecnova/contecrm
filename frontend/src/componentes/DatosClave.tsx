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
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import {
  camposDe,
  contratoDe,
  fichaDe,
  type CampoEsquema,
} from "@/lib/contrato";
import { Seguir } from "@/componentes/Seguir";
import { escalar, humanizar, tieneDato, campoDelNombre } from "@/lib/formato";
import type { Recurso } from "@/lib/modulos";
import { cn } from "@/lib/utiles";

/** Cuántos datos clave caben sin que la fila deje de leerse de un vistazo. */
const CUANTOS = 5;

/**
 * Campos que son un RECORRIDO: se pasa por ellos en orden y hay un después.
 *
 * NO vale cualquier lista cerrada, y la diferencia importa. `AGRUPABLES` —la
 * lista con la que el listado decide por qué campo agrupar— lleva dentro
 * `estado`, `prioridad` y `tipo`, que para agrupar valen y para una ruta no:
 * una cuenta «Activa / Inactiva / Bloqueada» no recorre nada, y pintarlo como
 * un camino dice que de activa se pasa a inactiva y de ahí a bloqueada, que es
 * falso. Se vio al mirarlo: la ficha de una cuenta salió con esas tres en fila
 * y una marcada.
 *
 * Una etapa o una fase sí: están ordenadas por definición, y la pregunta que
 * contesta la ruta —cuánto queda y qué viene después— sólo tiene sentido ahí.
 */
const RECORRIDOS = ["etapa", "fase"] as const;

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
  for (const candidato of RECORRIDOS) {
    if (!(candidato in fila)) continue;
    const campo = campos.find((c) => c.nombre === candidato);
    if (campo && campo.opciones.length >= 3) return campo;
  }
  return null;
}

function Ruta({
  campo,
  pasos,
  valor,
}: {
  /** El nombre del campo, para decir de qué es la ruta. */
  campo: string;
  pasos: string[];
  valor: string;
}) {
  const { t } = useTranslation();
  const actual = pasos.indexOf(valor);
  return (
    <ol
      aria-label={t("ficha.ruta", { campo: humanizar(campo) })}
      className="flex min-w-0 flex-wrap items-stretch gap-px overflow-hidden rounded"
    >
      {pasos.map((opcion, i) => {
        const hecha = actual >= 0 && i < actual;
        const aqui = i === actual;
        return (
          <li
            key={opcion}
            aria-current={aqui ? "step" : undefined}
            className={cn(
              "flex items-center whitespace-nowrap px-3 py-1 text-dato",
              // Lo recorrido en azul, lo de ahora en azul oscuro y lo que
              // queda en gris. Tres tonos y no dos: sin el del medio no se
              // distingue dónde estás de lo que ya has pasado.
              aqui
                ? "bg-accent-soft font-semibold text-white"
                : hecha
                  ? "bg-accent/15 text-accent"
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
  seguible = true,
  distintivos,
  recorrido,
  volverA,
  camposClave,
}: {
  recurso: Recurso | undefined;
  /** El tipo del registro, que es lo que se pone encima del nombre. */
  tipo: string;
  nombre: string;
  fila: Record<string, unknown> | null;
  /** Editar, borrar y lo que el contrato permita. */
  acciones?: ReactNode;
  /**
   * Si este registro se puede seguir. Casi todos sí.
   *
   * **El botón vive aquí y no en cada pantalla a propósito.** Hay catorce
   * fichas con este panel, y ponerlo a mano en las catorce es catorce
   * ocasiones de olvidarlo — y la que se olvidara no la notaría nadie,
   * porque una ficha sin botón de seguir se ve igual que una ficha. Aquí lo
   * tienen todas, y la que llegue mañana también.
   *
   * Se apaga en lo que no es un registro de negocio: un objeto del modelo de
   * datos y una instancia de proceso no son cosas a las que uno «siga la
   * pista», y ofrecerlo ahí sería ofrecer algo que no sirve para nada.
   */
  seguible?: boolean;
  /**
   * Insignias bajo el nombre: el estado, los roles de una cuenta, su NIF.
   *
   * Van aquí y no como un dato clave más porque no son pares
   * etiqueta/valor: son marcas de lo que el registro ES, y en Lightning viven
   * pegadas al nombre por eso mismo.
   */
  distintivos?: ReactNode;
  /**
   * El recorrido cuando lo definen los DATOS y no el contrato.
   *
   * La ruta de etapas se saca del contrato: una lista cerrada con al menos
   * tres valores. Eso vale para los objetos cuyas etapas son fijas, y no vale
   * para el que más la necesita. **Medido el 02-11-2026**: la oportunidad no
   * declara `etapa` en su esquema —se cambia por un extremo aparte, con el
   * identificador de una etapa del pipeline, que es configuración de cada
   * tenant—, así que `campoDeEtapa` no encontraba nada y la ficha de una
   * oportunidad salía sin ruta. Es justo la pieza que en Salesforce define la
   * pantalla, y el comentario de la pantalla decía que la pintaba.
   *
   * Con esto, quien conoce sus pasos los trae. Sigue sin haber nada escrito
   * por objeto: los pasos son los que el tenant tenga configurados.
   */
  recorrido?: { campo: string; pasos: string[] } | null;
  /**
   * De dónde viene el registro: su listado y su identificador.
   *
   * Va aquí y no en cada pantalla para que **esté en el mismo sitio en todas
   * las fichas**. La genérica lo tenía y las tres de a medida no, así que
   * desde la de una cuenta no había forma de volver a Cuentas que no fuera el
   * menú de arriba o el botón del navegador.
   */
  volverA?: { a: string; titulo: string; id?: string };
  /**
   * Qué campos son los datos clave, cuando los del listado no valen aquí.
   *
   * Por defecto son las `columnas` preferidas del recurso, que es lo que hace
   * que el listado y la ficha digan lo mismo. Hay fichas donde ese reparto
   * miente: la de un segmento enseña **los alcanzables**, medidos ahora y con
   * su desglose, y el `tamano` guardado del listado sale a su lado con la
   * misma cara y otro significado. Dos números iguales con dos nombres
   * parecidos es peor que uno solo.
   */
  camposClave?: string[];
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
      if (vivo)
        setCampos(plantilla ? camposDe(documento, plantilla, "patch") : []);
    });
    return () => {
      vivo = false;
    };
  }, [recurso]);

  // Los datos mandan sobre el contrato: cuando quien pinta la ficha trae los
  // pasos es porque los ha leído de la configuración del tenant, que es más
  // concreta que una lista cerrada del esquema.
  const delContrato = fila ? campoDeEtapa(fila, campos) : null;
  const campoRecorrido = recorrido?.campo ?? delContrato?.nombre ?? "";
  const pasos =
    recorrido && recorrido.pasos.length >= 3
      ? recorrido.pasos
      : (delContrato?.opciones ?? []);
  const valorEtapa = campoRecorrido ? String(fila?.[campoRecorrido] ?? "") : "";

  // Los preferidos del recurso, quitando el que da nombre —ya es el título— y
  // la etapa, que se pinta como ruta y no como un par más.
  const titular = fila ? campoDelNombre(fila) : "";
  // La moneda del propio registro, cuando la declara: con ella los importes
  // salen con su símbolo, como la tarjeta que hay debajo en una oportunidad.
  const laMoneda = typeof fila?.moneda === "string" ? fila.moneda : "";
  // El identificador sale de la fila, no de la dirección: hay fichas que no
  // llevan el `id` en la ruta, y una `useParams` aquí dentro leería el de la
  // pantalla que la contenga, que no siempre es este registro.
  const idDelRegistro = typeof fila?.id === "string" ? fila.id : "";
  const puedeSeguirse = seguible && Boolean(tipo) && Boolean(idDelRegistro);
  const clave = (camposClave ?? recurso?.columnas ?? [])
    .filter((c) => c !== titular && c !== campoRecorrido && !/_id$/.test(c))
    .filter((c) => fila && tieneDato(fila[c]))
    .slice(0, CUANTOS);

  return (
    <>
      {volverA ? (
        <nav
          aria-label={t("ficha.deDonde")}
          className="mb-2 flex items-center gap-2 text-dato text-ink-faint"
        >
          <Link to={volverA.a} className="text-accent hover:underline">
            {volverA.titulo}
          </Link>
          {volverA.id ? (
            <span className="font-mono" title={volverA.id}>
              {volverA.id.slice(0, 8)}…
            </span>
          ) : null}
        </nav>
      ) : null}
      <header className="card mb-4 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {/* El TIPO encima y en pequeño, el nombre debajo y grande: es el
              orden de Salesforce y resuelve una ambigüedad real —«Acme» puede
              ser una cuenta, un lead o un caso, y el título solo no lo dice. */}
            <p className="text-rotulo font-semibold uppercase tracking-wide text-ink-faint">
              {humanizar(tipo)}
            </p>
            <h1 className="min-w-0 truncate text-pagina font-bold tracking-[-0.01em] text-ink">
              {nombre || humanizar(tipo)}
            </h1>
            {distintivos ? (
              <div className="mt-1 flex flex-wrap items-center gap-2">
                {distintivos}
              </div>
            ) : null}
          </div>
          {acciones || puedeSeguirse ? (
            <div className="flex shrink-0 items-center gap-2">
              {/* Seguir primero, a la izquierda de editar y borrar: es donde
                  lo pone Lightning, y además lo separa de lo que cambia el
                  registro — seguir no lo toca. */}
              {puedeSeguirse ? <Seguir objetoTipo={tipo} objetoId={idDelRegistro} /> : null}
              {acciones}
            </div>
          ) : null}
        </div>

        {pasos.length >= 3 && valorEtapa ? (
          <div className="mt-3">
            <Ruta campo={campoRecorrido} pasos={pasos} valor={valorEtapa} />
          </div>
        ) : null}

        {clave.length > 0 ? (
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 border-t border-ink-dim/50 pt-3 sm:grid-cols-3 lg:grid-cols-5">
            {clave.map((c) => (
              <div key={c} className="min-w-0">
                <dt
                  className="truncate text-rotulo text-ink-faint"
                  title={humanizar(c)}
                >
                  {humanizar(c)}
                </dt>
                <dd
                  className="truncate text-titulo text-ink"
                  title={escalar(fila?.[c], c, laMoneda)}
                >
                  {escalar(fila?.[c], c, laMoneda)}
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
    </>
  );
}
