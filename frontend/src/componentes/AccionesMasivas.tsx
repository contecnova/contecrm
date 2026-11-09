/**
 * Lo que se hace con varias filas a la vez (CRM-00.02.01.11).
 *
 * El servidor tenía el lote desde el primer día —`POST /<colección>/masivo`,
 * con un punto de guardado por elemento y el informe de lo que falló— y la
 * pantalla no lo llamaba nunca: para cambiar el responsable de cuarenta leads
 * había que abrir cuarenta fichas. Además el lote vivía en `/cuentas/masivo`
 * mientras el listado usa `/accounts`, así que la pantalla no tenía cómo
 * encontrarlo; ahora se publica también junto a la colección.
 *
 * Las decisiones:
 *
 * - **Sólo se ofrece lo que el contrato dice que el lote admite.** La lista de
 *   operaciones es cerrada y viene del servidor: un «Borrar» que contesta 422
 *   después de pulsarlo es peor que no tenerlo.
 * - **Actualizar es UN campo**, elegido de un desplegable con los campos que la
 *   ficha deja editar. Es lo que se hace en lote de verdad —el responsable, el
 *   estado, una fecha—; un formulario entero para cuarenta registros invita a
 *   pisar lo que cada uno tenía.
 * - **Borrar se confirma** y va a la papelera, como el borrado de uno.
 * - **El informe se enseña tal cual**: cuántos sí, cuántos no y, de cada uno
 *   que falló, cuál era y por qué. Un «hecho» a secas sobre un lote con fallos
 *   es la frase que hace que nadie compruebe nada.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Formulario } from "@/componentes/Formulario";
import { ErrorApi, llamar } from "@/lib/api";
import type { CampoEsquema } from "@/lib/contrato";

interface Informe {
  total: number;
  creados: number;
  actualizados: number;
  borrados: number;
  fallidos: number;
  errores: { fila: number; motivo: string; codigo?: string }[];
  errores_no_mostrados?: number;
}

type Modo = "nada" | "actualizar" | "borrar";

export function AccionesMasivas({
  ruta,
  operaciones,
  ids,
  nombres,
  campos,
  alTerminar,
  alQuitar,
}: {
  /** `POST` del lote, ya resuelto contra el contrato. */
  ruta: string;
  /** Lo que el contrato dice que el lote admite. */
  operaciones: readonly string[];
  /** Los identificadores elegidos, en orden: el informe habla por posición. */
  ids: string[];
  /** Cómo se llama cada uno, para que el informe no hable de UUID. */
  nombres: Record<string, string>;
  /** Los campos que la ficha deja editar. */
  campos: CampoEsquema[];
  alTerminar: () => void;
  alQuitar: () => void;
}) {
  const { t } = useTranslation();
  const [modo, setModo] = useState<Modo>("nada");
  const [campo, setCampo] = useState("");
  const [enviando, setEnviando] = useState(false);
  // El informe se queda con los elegidos y sus nombres DE CUANDO SE LANZÓ: al
  // terminar se recarga la lista y se vacía la selección, y lo borrado ya no
  // está en ella para decir cómo se llamaba.
  const [informe, setInforme] = useState<{
    op: string;
    datos: Informe;
    ids: string[];
    nombres: Record<string, string>;
  } | null>(null);
  const [aviso, setAviso] = useState("");

  const puedeActualizar =
    operaciones.includes("actualizar") && campos.length > 0;
  const puedeBorrar = operaciones.includes("borrar");
  const elegido = campos.find((c) => c.nombre === campo) ?? null;

  async function lanzar(
    operacion: string,
    elementos: Record<string, unknown>[],
  ) {
    setEnviando(true);
    setAviso("");
    try {
      const r = await llamar<Informe>(ruta, {
        metodo: "POST",
        cuerpo: { operacion, elementos },
      });
      setInforme({ op: operacion, datos: r.datos, ids, nombres });
      setModo("nada");
      alTerminar();
    } catch (error) {
      if (error instanceof ErrorApi && error.codigo === "stepup.requerido") {
        // Borrar en lote pide volver a verificarse: se dice qué hacer en vez de
        // enseñar un «sin permiso» que no explica nada.
        setAviso(t("masivo.verificate"));
      } else {
        setAviso(
          error instanceof ErrorApi
            ? error.explicacion || error.titulo
            : t("masivo.noSePudo"),
        );
      }
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="card mb-3 p-4" aria-label={t("masivo.titulo")}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="section-label mr-2">
          {ids.length > 0
            ? t("masivo.elegidos", { count: ids.length })
            : t("masivo.resultado")}
        </h2>
        {puedeActualizar && ids.length > 0 ? (
          <button
            type="button"
            className={modo === "actualizar" ? "btn-primary" : "btn-secondary"}
            onClick={() =>
              setModo(modo === "actualizar" ? "nada" : "actualizar")
            }
          >
            {t("masivo.actualizarCampo")}
          </button>
        ) : null}
        {puedeBorrar && ids.length > 0 ? (
          <button
            type="button"
            className={modo === "borrar" ? "btn-danger" : "btn-secondary"}
            onClick={() => setModo(modo === "borrar" ? "nada" : "borrar")}
          >
            {t("masivo.borrar")}
          </button>
        ) : null}
        <button type="button" className="btn-ghost" onClick={alQuitar}>
          {ids.length > 0 ? t("masivo.quitarSeleccion") : t("masivo.cerrar")}
        </button>
      </div>

      {modo === "actualizar" && ids.length > 0 ? (
        <div className="mt-3 max-w-xl">
          <label htmlFor="masivo-campo" className="label-base">
            {t("masivo.queCampo")}
          </label>
          <select
            id="masivo-campo"
            value={campo}
            onChange={(e) => setCampo(e.target.value)}
            className="input-base"
          >
            <option value="">{t("masivo.eligeCampo")}</option>
            {campos.map((c) => (
              <option key={c.nombre} value={c.nombre}>
                {c.titulo || c.nombre}
              </option>
            ))}
          </select>
          {elegido ? (
            <div className="mt-3">
              <Formulario
                key={elegido.nombre}
                campos={[{ ...elegido, obligatorio: true }]}
                enviando={enviando}
                textoEnviar={t("masivo.aplicarA", { count: ids.length })}
                alEnviar={(v) =>
                  void lanzar(
                    "actualizar",
                    ids.map((id) => ({
                      id,
                      [elegido.nombre]: v[elegido.nombre],
                    })),
                  )
                }
              />
            </div>
          ) : null}
        </div>
      ) : null}

      {modo === "borrar" && ids.length > 0 ? (
        <div className="mt-3">
          <p className="text-dato text-ink">
            {t("masivo.confirmarBorrado", { count: ids.length })}
          </p>
          <button
            type="button"
            disabled={enviando}
            className="btn-danger mt-2"
            onClick={() =>
              void lanzar(
                "borrar",
                ids.map((id) => ({ id })),
              )
            }
          >
            {enviando
              ? t("app.cargando")
              : t("masivo.borrarN", { count: ids.length })}
          </button>
        </div>
      ) : null}

      {aviso ? (
        <p className="mt-3 text-dato text-danger" role="status">
          {aviso}
        </p>
      ) : null}

      {informe ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-3" role="status">
          <p className="text-dato text-ink">
            {t(
              informe.op === "borrar"
                ? "masivo.informeBorrado"
                : "masivo.informeActualizado",
              {
                hechos:
                  informe.op === "borrar"
                    ? informe.datos.borrados
                    : informe.datos.actualizados,
                total: informe.datos.total,
              },
            )}
          </p>
          {informe.datos.fallidos > 0 ? (
            <>
              <p className="mt-1 text-dato text-danger">
                {t("masivo.fallidos", { count: informe.datos.fallidos })}
              </p>
              <ul className="mt-1 divide-y divide-ink-dim/30">
                {informe.datos.errores.map((e) => {
                  const id = informe.ids[e.fila - 1] ?? "";
                  return (
                    <li key={`${e.fila}-${id}`} className="py-1 text-dato">
                      <span className="font-medium text-ink">
                        {informe.nombres[id] ||
                          id ||
                          t("masivo.fila", { fila: e.fila })}
                      </span>
                      <span className="ml-2 text-ink-muted">{e.motivo}</span>
                    </li>
                  );
                })}
              </ul>
              {informe.datos.errores_no_mostrados ? (
                <p className="text-rotulo text-ink-faint">
                  {t("masivo.noMostrados", {
                    count: informe.datos.errores_no_mostrados,
                  })}
                </p>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
