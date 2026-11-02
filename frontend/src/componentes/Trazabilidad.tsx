/**
 * La trazabilidad de un registro: qué cambió y cómo estaba.
 *
 * Vivían dentro de la ficha genérica, que es desde donde se usaban. Salen de
 * ahí porque las tres fichas de a medida —cuenta, oportunidad y caso— también
 * tienen que poder enseñarlas: la pregunta «esto antes no decía esto» no es
 * menos urgente en una oportunidad que en una visita, y dejarlas dentro de una
 * pantalla obligaba a que las demás importaran de una página, que es un bucle.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";

interface CambioDeCampo {
  campo: string;
  valor_anterior: string | null;
  valor_nuevo: string | null;
  actor?: string | null;
  origen?: string | null;
  cuando?: string | null;
}

interface HistorialCampos {
  cambios: CambioDeCampo[];
  cuantos: number;
  que_significa: string;
}

/**
 * Qué ha cambiado en este registro, campo a campo.
 *
 * **Se escribía y no lo leía nadie.** Cada edición anota el campo, el valor
 * anterior, el nuevo, quién lo hizo y **desde dónde** —la pantalla, la API o
 * una automatización—, y ninguna ruta lo devolvía. Es la primera pregunta de
 * cualquier discusión sobre un registro: «esto antes no decía esto».
 *
 * El **origen** es la mitad que casi nunca se guarda y la que la zanja: no es
 * lo mismo que lo cambiara una persona a que lo pisara una sincronización
 * todas las noches, y sin saberlo se culpa a quien pasaba por ahí.
 *
 * Plegado y cargado **sólo al abrirlo**: es trazabilidad, no contenido, y
 * pedirlo en cada ficha abierta sería una llamada por registro que casi nadie
 * mira. Y cuando está vacío, el servidor dice cuál de las dos cosas es —este
 * registro no se ha tocado, o este servicio no lleva ese histórico—, que con
 * la lista vacía se ven igual.
 */
export function HistorialDeCampos({
  servicio,
  objeto,
  objetoId,
}: {
  servicio: string;
  objeto: string;
  objetoId: string;
}) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const [datos, setDatos] = useState<HistorialCampos | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<HistorialCampos>(
      `/api/v1/${servicio}/rastro/campos/${objeto}/${objetoId}`,
      { signal: control.signal },
    )
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [servicio, objeto, objetoId]);

  useEffect(() => {
    if (!abierto || datos) return undefined;
    return cargar();
  }, [abierto, datos, cargar]);

  return (
    <details
      className="mt-3"
      onToggle={(e) => setAbierto(e.currentTarget.open)}
    >
      <summary className="cursor-pointer text-rotulo text-ink-faint">
        {t("ficha.queHaCambiado")}
      </summary>
      {fallo ? <Fallo error={fallo} reintentar={cargar} /> : null}
      {abierto && !datos && !fallo ? <Cargando /> : null}
      {datos ? (
        datos.cambios.length === 0 ? (
          <Vacio
            titulo={t("ficha.sinCambios")}
            detalle={datos.que_significa}
            compacto
          />
        ) : (
          <ul className="card mt-2 flex flex-col gap-2 p-4">
            {datos.cambios.map((c, i) => (
              <li key={`${c.campo}-${i}`} className="text-dato">
                <span className="text-ink">{c.campo}</span>:{" "}
                <span className="text-ink-faint line-through">
                  {c.valor_anterior ?? "—"}
                </span>{" "}
                → <span className="text-ink">{c.valor_nuevo ?? "—"}</span>
                {/* El origen al lado del cambio, no en otra columna: es lo que
                    distingue «lo cambió alguien» de «lo pisó una
                    sincronización», y es la diferencia que zanja la
                    discusión. */}
                {c.origen ? (
                  <span className="ml-2 chip-dato">{c.origen}</span>
                ) : null}
              </li>
            ))}
          </ul>
        )
      ) : null}
    </details>
  );
}

interface Reconstruido {
  objeto: string;
  hasta: string | null;
  hechos: number;
  estado: Record<string, unknown>;
  hechos_compensados: number;
  porque: string;
}

interface Cuadra {
  cuadra: boolean;
  diferencias: { campo: string; reconstruido: unknown; vivo: unknown }[];
  que_significa: string;
}

/**
 * Cómo estaba este registro en un momento dado (CRM-00.05.04.06).
 *
 * La pregunta que resuelve llega siempre tarde: **«¿cómo estaba esto el 3 de
 * marzo?»**. El historial de campos dice qué cambió; no dice cómo era el
 * conjunto, y reconstruirlo a mano encadenando cambios sale mal en cuanto hay
 * una fusión o un borrado por medio.
 *
 * **Y lo que de verdad importa es la comprobación de que cuadra.** Una
 * reconstrucción que no coincide con la tabla viva significa que alguien
 * escribió en la tabla sin pasar por el rastro —un script de corrección, una
 * migración, un arreglo a mano un viernes— y a partir de ahí el rastro deja de
 * ser una prueba sin que nadie se entere, porque sigue contestando con la
 * misma seguridad.
 *
 * Plegado y cargado sólo al abrirlo: el rastro completo está encendido en muy
 * pocos objetos a propósito —guardar todos los hechos de todo multiplica la
 * escritura por algo que casi nadie consulta— y pedirlo en cada ficha sería
 * una llamada por registro abierto que casi siempre contestaría «aquí no hay».
 */
export function ComoEstabaEsto({
  servicio,
  objeto,
  objetoId,
}: {
  servicio: string;
  objeto: string;
  objetoId: string;
}) {
  const { t } = useTranslation();
  const [abierto, setAbierto] = useState(false);
  const [estado, setEstado] = useState<Reconstruido | null>(null);
  const [cuadra, setCuadra] = useState<Cuadra | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    if (!abierto) return;
    const control = new AbortController();
    setFallo(null);
    llamar<Reconstruido>(`/api/v1/${servicio}/rastro/${objeto}/${objetoId}`, {
      signal: control.signal,
    })
      .then((r) => setEstado(r.datos))
      // Un objeto sin rastro completo contesta 404 a propósito, y eso no es un
      // error: es que nadie lo encendió para este objeto.
      .catch(salvoCancelacion(setFallo));
    void llamar<Cuadra>(
      `/api/v1/${servicio}/rastro/${objeto}/${objetoId}/cuadra`,
      { signal: control.signal },
    )
      .then((r) => setCuadra(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, [abierto, servicio, objeto, objetoId]);

  return (
    <details
      className="card mt-4 p-4"
      onToggle={(e) => setAbierto((e.target as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer text-dato font-medium text-ink">
        {t("ficha.comoEstaba")}
      </summary>
      {fallo ? (
        <p className="mt-2 text-dato text-ink-muted">
          {t("ficha.sinRastroCompleto")}
        </p>
      ) : null}
      {estado ? (
        <>
          <p className="mt-2 text-dato text-ink-muted">
            {t("ficha.hechos", {
              cuantos: estado.hechos,
              compensados: estado.hechos_compensados,
            })}
          </p>
          {/* Los compensados se aplican y se anulan, no se saltan: saltarlos
              daría el estado que habría habido si nadie se hubiera equivocado,
              que no es lo que pasó. */}
          <p className="mt-1 text-rotulo text-ink-faint">{estado.porque}</p>
        </>
      ) : null}
      {cuadra ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-2">
          <p
            className={
              cuadra.cuadra ? "text-dato text-success" : "text-dato text-danger"
            }
          >
            {cuadra.cuadra ? t("ficha.cuadra") : t("ficha.noCuadra")}
          </p>
          <p className="mt-1 text-rotulo text-ink-muted">{cuadra.que_significa}</p>
          {(cuadra.diferencias ?? []).length > 0 ? (
            <ul className="mt-1 divide-y divide-ink-dim/30">
              {(cuadra.diferencias ?? []).map((d) => (
                <li
                  key={d.campo}
                  className="flex flex-wrap items-baseline gap-x-2 py-1 text-rotulo"
                >
                  <span className="font-medium text-ink">{d.campo}</span>
                  <span className="text-ink-faint">
                    {String(d.reconstruido ?? "—")}
                  </span>
                  <span className="text-ink-muted">
                    ≠ {String(d.vivo ?? "—")}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}
