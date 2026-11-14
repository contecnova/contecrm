/**
 * Por dónde entran los casos, y qué se queda por el camino
 * (CRM-04.02.01.01, CRM-04.02.01.02, CRM-04.02.01.04, CRM-04.02.01.06,
 * CRM-04.02.01.07).
 *
 * Un canal de entrada es una puerta declarada: de dónde llega un mensaje y
 * cómo se traduce en un caso. El listado genérico los enseñaba con su nombre y
 * su tipo, y la pregunta que se hace delante de esta pantalla es otra: **qué
 * está entrando y qué se está tirando**.
 *
 * El número de descartados solo no se puede accionar, y es lo que esta
 * pantalla arregla: no distingue el caso bueno —el anti-bucle cortando un
 * bucle de respuestas automáticas, que es exactamente para lo que está— del
 * caso caro, que es una **trampa mal puesta tragándose clientes de verdad**. Y
 * la trampa se descarta contestando «aceptado» A PROPÓSITO, para no decirle al
 * robot qué campo cambiar: un canal mal configurado se come correos, contesta
 * que todo bien, y nadie se entera nunca.
 *
 * Por eso cada canal enseña su desglose por motivo, y el que más descarta sale
 * señalado cuando es la trampa.
 *
 * **Y las defensas van delante de las cifras.** El tope por hora, la dirección
 * propia y los campos obligatorios son lo que explica el número: un canal sin
 * dirección propia declarada no puede cortar su propio eco, y eso no se ve
 * mirando cuántos entraron.
 */

import { cn } from "@/lib/utiles";
import { useTranslation } from "react-i18next";

import {
  AvisoDeRecorte,
  Error as Fallo,
  FalloCompacto,
  Vacio,
} from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { useListaPaginada } from "@/lib/paginado";

interface Canal {
  id: string;
  clave: string;
  nombre: string;
  /** correo | formulario | chat | social | api | telefono | portal */
  tipo: string;
  activo: boolean;
  recibidos: number;
  descartados: number;
  /** El total solo no dice si lo que se tira es basura o son clientes. */
  descartados_por: Record<string, number>;
  mapeo: Record<string, unknown>;
  obligatorios: string[];
  campo_trampa: string;
  max_por_hora: number;
  direccion_propia: string;
}

/** Los motivos que `recibir()` conoce, en el orden en que los aplica. */
const MOTIVOS = [
  "trampa",
  "automatico",
  "propio",
  "tope",
  "incompleto",
] as const;

export function CanalesDeEntrada() {
  const { t } = useTranslation();
  // Por páginas y siguiendo el cursor: se pedían cien y se pintaban como
  // todos, así que el canal ciento uno no salía y nada lo decía.
  const lista = useListaPaginada<Canal>("/api/v1/canales-servicio?limite=100");
  const canales = lista.filas;

  if (lista.fallo) return <Fallo error={lista.fallo} reintentar={lista.recargar} />;

  return (
    <>
      <CabeceraPagina
        titulo={t("canales.titulo")}
        icono="inbox"
        entradilla={t("canales.entradilla")}
      />

      {!canales || canales.length === 0 ? (
        <Vacio
          titulo={t("canales.sinCanales")}
          detalle={t("canales.sinCanalesDetalle")}
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {canales.map((c) => {
            const porMotivo = c.descartados_por ?? {};
            const total = c.descartados ?? 0;
            // El reparto puede no sumar el total: los canales anteriores a
            // esta medida tienen el total y no el desglose, y repartirlo a
            // ojo sería inventarlo.
            const desglosado = MOTIVOS.reduce(
              (n, m) => n + (porMotivo[m] ?? 0),
              0,
            );
            const sinMotivo = Math.max(0, total - desglosado);
            const trampaManda =
              (porMotivo.trampa ?? 0) > 0 &&
              (porMotivo.trampa ?? 0) >=
                Math.max(...MOTIVOS.map((m) => porMotivo[m] ?? 0));

            return (
              <li key={c.id} className="card p-4">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="flex-1 text-titulo text-ink">
                    {c.nombre}
                  </span>
                  <span className="chip-dato">{c.tipo}</span>
                  <span
                    className={
                      c.activo ? "badge badge-muted" : "badge badge-aviso"
                    }
                  >
                    {t(c.activo ? "canales.escuchando" : "canales.apagado")}
                  </span>
                </div>

                <p className="mt-2 font-mono text-dato text-ink">
                  {t("canales.cifras", {
                    recibidos: c.recibidos,
                    descartados: total,
                  })}
                </p>

                {total > 0 ? (
                  <ul className="mt-1 flex flex-wrap gap-2">
                    {MOTIVOS.filter((m) => (porMotivo[m] ?? 0) > 0).map((m) => (
                      <li
                        key={m}
                        className={
                          m === "trampa"
                            ? "badge badge-aviso font-mono"
                            : "chip-dato font-mono"
                        }
                      >
                        {t(`canales.motivo.${m}`, { cuantos: porMotivo[m] })}
                      </li>
                    ))}
                    {/* Lo que no se sabe se dice. Un desglose que no suma el
                        total y no lo declara se lee como el total entero. */}
                    {sinMotivo > 0 ? (
                      <li className="chip-dato font-mono">
                        {t("canales.sinMotivo", { cuantos: sinMotivo })}
                      </li>
                    ) : null}
                  </ul>
                ) : null}

                {/* El aviso que justifica la pantalla: la trampa se descarta
                    contestando «aceptado», así que un falso positivo no deja
                    ni rastro del lado de quien escribió. */}
                {trampaManda ? (
                  <p className="mt-2 text-dato text-warning">
                    {t("canales.trampaManda")}
                  </p>
                ) : null}

                <dl className="mt-3 grid gap-x-4 gap-y-1 text-rotulo text-ink-faint sm:grid-cols-2">
                  <div>
                    <dt className="inline text-ink-muted">
                      {t("canales.tope")}
                    </dt>{" "}
                    <dd className="inline font-mono">{c.max_por_hora}</dd>
                  </div>
                  <div>
                    <dt className="inline text-ink-muted">
                      {t("canales.propia")}
                    </dt>{" "}
                    <dd
                      className={cn(
                        "inline",
                        c.direccion_propia && "font-mono",
                      )}
                    >
                      {c.direccion_propia || t("canales.sinPropia")}
                    </dd>
                  </div>
                  <div>
                    <dt className="inline text-ink-muted">
                      {t("canales.trampa")}
                    </dt>{" "}
                    {/* La monoespaciada es para el nombre del campo, que es
                        un identificador. «sin trampa» es una frase. */}
                    <dd className={cn("inline", c.campo_trampa && "font-mono")}>
                      {c.campo_trampa || t("canales.sinTrampa")}
                    </dd>
                  </div>
                  <div>
                    <dt className="inline text-ink-muted">
                      {t("canales.obligatorios")}
                    </dt>{" "}
                    <dd className="inline font-mono">
                      {(c.obligatorios ?? []).join(", ") ||
                        t("canales.ninguno")}
                    </dd>
                  </div>
                </dl>

                {/* Sin dirección propia, el canal de correo no puede cortar su
                    propio eco: el buzón se contesta a sí mismo. */}
                {c.tipo === "correo" && !c.direccion_propia ? (
                  <p className="mt-2 text-dato text-warning">
                    {t("canales.sinEco")}
                  </p>
                ) : null}

                <p className="mt-2 text-rotulo text-ink-faint">
                  {t("canales.mapea", {
                    cuantos: Object.keys(c.mapeo ?? {}).length,
                  })}
                </p>
              </li>
            );
          })}
        </ul>
      )}
      <FalloCompacto
        error={lista.falloAlCargarMas}
        que={t("canales.titulo")}
        reintentar={lista.cargarMas}
      />
      {canales && lista.hayMas ? (
        <AvisoDeRecorte
          cuantas={canales.length}
          alCargarMas={lista.cargarMas}
          cargando={lista.cargandoMas}
        />
      ) : null}
    </>
  );
}
