/**
 * Proveedores: homologación, papeles, riesgo y a quién llamar
 * (CRM-07.04.03.31).
 *
 * Esta pantalla existe para contestar tres preguntas que se hacen con prisa:
 * **¿puedo encargarle esto hoy?**, **¿tiene los papeles?** y **¿a quién llamo si
 * falla a las once de la noche?**.
 *
 * Dos decisiones de cómo se pinta:
 *
 * **Lo vencido no se pinta igual que lo que va a vencer.** Uno es un problema que
 * está pasando ahora y el otro es una tarea para esta semana; con el mismo color,
 * el que está pasando se pierde entre los otros.
 *
 * **Y «no consta» no se pinta como «está bien».** Un proveedor sin documentos no
 * es uno en regla: es uno al que no se le ha pedido nada, y esa diferencia es la
 * que decide si alguien hace algo.
 *
 * **Se elige de una lista, no se teclea un identificador.** La pantalla pedía
 * «Identificador de la cuenta» en una caja vacía: para usarla había que salir a
 * buscar un UUID a otra pantalla, copiarlo y volver. Nadie hace eso con prisa —y
 * esta pantalla se abre siempre con prisa—, así que en la práctica no se podía
 * usar. La lista sale de `GET /api/v1/proveedores`, que ya existía y no la
 * llamaba nadie.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { filas, llamar, salvoCancelacion } from "@/lib/api";
import { cn } from "@/lib/utiles";

interface Documento {
  clave: string;
  nombre: string;
  vence: string;
  dias: number;
  bloquea: boolean;
}

/**
 * Un proveedor es una cuenta con el papel de proveedor, así que el listado
 * devuelve cuentas: el identificador viene en `id`, no en `cuenta_id`.
 */
interface Proveedor {
  id: string;
  nombre?: string;
  nombre_comercial?: string | null;
  roles?: string[];
}

interface EstadoDocumental {
  documentos: number;
  vencidos: Documento[];
  por_vencer: Documento[];
  sin_fecha_de_caducidad: string[];
  bloqueado: boolean;
  medible: boolean;
  aviso: string;
  porque: string;
}

export function Proveedores() {
  const { t } = useTranslation();
  const [cuenta, setCuenta] = useState("");
  const [proveedores, setProveedores] = useState<Proveedor[] | null>(null);
  const [datos, setDatos] = useState<EstadoDocumental | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [cargando, setCargando] = useState(false);

  useEffect(() => {
    const control = new AbortController();
    llamar<unknown>("/api/v1/proveedores?limite=200", { signal: control.signal })
      .then((r) => setProveedores(filas<Proveedor>(r.datos)))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  useEffect(() => {
    if (!cuenta) return;
    const control = new AbortController();
    setCargando(true);
    llamar<EstadoDocumental>(`/api/v1/proveedores/${cuenta}/documentos`, {
      signal: control.signal,
    })
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo))
      .finally(() => setCargando(false));
    return () => control.abort();
  }, [cuenta]);

  return (
    <>
      <CabeceraPagina
        titulo={t("proveedores.titulo")}
        entradilla={t("proveedores.intro")}
        icono="local_shipping"
      />

      {proveedores === null ? (
        <Cargando />
      ) : proveedores.length === 0 ? (
        /* Vacío de verdad: no hay ninguna cuenta marcada como proveedor. Se
           dice así, y no con una caja de texto que no lleva a ninguna parte. */
        <Vacio titulo={t("proveedores.sinProveedores")} detalle={t("proveedores.comoSeCrea")} />
      ) : (
        <nav className="mt-4 flex flex-wrap gap-2" aria-label={t("proveedores.cuenta")}>
          {proveedores.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setCuenta(p.id)}
              className={cn(
                "rounded-xl border px-3 py-1.5 text-xs",
                p.id === cuenta
                  ? "border-accent bg-accent/10 text-accent-text"
                  : "border-line text-ink hover:bg-paper-sunk",
              )}
            >
              {p.nombre_comercial || p.nombre || p.id}
            </button>
          ))}
        </nav>
      )}

      {fallo ? <Fallo error={fallo} /> : null}
      {cargando ? <Cargando /> : null}

      {datos && !datos.medible ? (
        /* «No consta» no se pinta como «está bien»: sin documentos no es un
           proveedor en regla, es uno al que no se le ha pedido nada. */
        <Vacio titulo={t("proveedores.sinDatos")} detalle={datos.aviso} />
      ) : null}

      {datos && datos.medible ? (
        <>
          <p
            className={`mt-4 text-xs ${datos.bloqueado ? "text-danger" : "text-success"}`}
            role="status"
          >
            {datos.porque}
          </p>

          {datos.vencidos.length > 0 ? (
            <section className="mt-4">
              <h2 className="text-xs font-medium text-danger">{t("proveedores.vencidos")}</h2>
              <ul className="mt-2 space-y-1">
                {datos.vencidos.map((d) => (
                  <li key={d.clave} className="text-2xs text-ink">
                    {d.nombre || d.clave} · {d.vence}
                    {d.bloquea ? (
                      <span className="ml-2 text-danger">{t("proveedores.bloquea")}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {datos.por_vencer.length > 0 ? (
            <section className="mt-4">
              <h2 className="text-xs font-medium text-warning">{t("proveedores.porVencer")}</h2>
              <ul className="mt-2 space-y-1">
                {datos.por_vencer.map((d) => (
                  <li key={d.clave} className="text-2xs text-ink-muted">
                    {d.nombre || d.clave} · {t("proveedores.enDias", { dias: d.dias })}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {datos.sin_fecha_de_caducidad.length > 0 ? (
            <section className="mt-4">
              <h2 className="text-xs font-medium text-ink-muted">{t("proveedores.sinFecha")}</h2>
              {/* Lo más peligroso no es lo vencido: es lo que nunca va a
                  aparecer en una lista de vencidos. */}
              <p className="mt-1 text-3xs text-ink-faint">{t("proveedores.sinFechaPorque")}</p>
              <p className="mt-1 text-2xs text-ink">
                {datos.sin_fecha_de_caducidad.join(", ")}
              </p>
            </section>
          ) : null}
        </>
      ) : null}
    </>
  );
}
