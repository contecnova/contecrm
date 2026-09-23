/**
 * Lo que se puede hacer con este registro, y hacerlo.
 *
 * Los botones y sus formularios salen del contrato, no de una lista escrita a
 * mano: la superficie dice qué acciones admite el servidor sobre esta ruta y
 * qué permiso exige cada una, y el OpenAPI dice qué campos pide. Una acción
 * nueva en el servidor aparece aquí sola.
 *
 * **Se pide confirmación de lo que no se deshace.** Descartar un lead, cerrar
 * un caso o fusionar dos cuentas no son pulsaciones que se puedan retirar, y un
 * botón que actúa al primer clic es un botón que alguien pulsa sin querer.
 *
 * **Y se dice qué contestó el servidor.** Una acción que no dice nada deja a
 * quien la ejecuta sin saber si pasó algo: la mitad de estas devuelven un
 * resultado —qué se creó, qué quedó pendiente— y esconderlo sería tirar la
 * respuesta a la basura.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { Formulario } from "@/componentes/Formulario";
import { Icono } from "@/componentes/Icono";
import { Link } from "react-router-dom";

import { llamar } from "@/lib/api";
import { escalar, humanizar } from "@/lib/formato";
import { MODULOS, type Recurso } from "@/lib/modulos";
import { objetoDe, recursoDeReferencia } from "@/lib/referencias";
import { camposDe, contratoDe, type CampoEsquema } from "@/lib/contrato";
import { type Accion } from "@/lib/acciones";

/**
 * Acciones que no se pueden deshacer y se preguntan antes.
 *
 * Por el verbo de la ruta y no por una lista de rutas concretas: `descartar`,
 * `cerrar` o `anular` significan lo mismo los ejecute quien los ejecute, y una
 * lista por ruta se queda corta con el primer recurso nuevo.
 */
const IRREVERSIBLES = /^(descartar|cerrar|anular|cancelar|fusionar|purgar|revocar|baja|destruir)/;

/**
 * Lo que devolvió la acción, escrito para una persona.
 *
 * Los identificadores que salen —«se ha creado la oportunidad
 * 01a0ce88-…»— se convierten en un enlace a esa ficha cuando se sabe de qué
 * objeto son. Un UUID suelto obliga a copiarlo y buscarlo a mano, que es
 * exactamente lo que el sistema tenía que ahorrar.
 */
function Resultado({ datos }: { datos: unknown }) {
  const { t } = useTranslation();
  if (!datos || typeof datos !== "object") return null;
  const pares = Object.entries(datos as Record<string, unknown>).filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );
  if (pares.length === 0) return null;

  return (
    <dl className="mt-2 space-y-1">
      {pares.map(([clave, valor]) => {
        const recurso = recursoDeReferencia(clave);
        const objeto = objetoDe(clave);
        const modulo = recurso ? moduloDelRecurso(recurso) : null;
        const enlazable =
          recurso && modulo && objeto && typeof valor === "string" && UUID_SUELTO.test(valor);
        return (
          <div key={clave} className="flex items-baseline justify-between gap-3">
            <dt className="shrink-0 text-3xs text-ink-faint">{humanizar(clave)}</dt>
            <dd className="truncate text-2xs text-ink">
              {enlazable ? (
                <Link
                  to={`/m/${modulo}/${objeto}/${valor}`}
                  className="text-accent hover:underline"
                >
                  {t("acciones.abrir")}
                </Link>
              ) : typeof valor === "object" ? (
                JSON.stringify(valor)
              ) : (
                escalar(valor, clave)
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

const UUID_SUELTO = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** En qué módulo vive un recurso, para poder componer la ruta de su ficha. */
function moduloDelRecurso(recurso: Recurso): string | null {
  for (const modulo of MODULOS) {
    if (modulo.recursos.includes(recurso)) return modulo.ruta;
  }
  return null;
}

export function Acciones({
  acciones,
  servicio,
  alTerminar,
}: {
  acciones: Accion[];
  /** Servicio dueño, para leer su contrato. */
  servicio: string;
  /** Se llama tras ejecutar, para que la ficha recargue. */
  alTerminar: () => void;
}) {
  const { t } = useTranslation();
  const [abierta, setAbierta] = useState<Accion | null>(null);
  const [campos, setCampos] = useState<CampoEsquema[] | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [resultado, setResultado] = useState<unknown>(null);
  const [confirmada, setConfirmada] = useState(false);

  useEffect(() => {
    if (!abierta) return;
    let vivo = true;
    setCampos(null);
    void contratoDe(servicio).then((documento) => {
      if (vivo) setCampos(camposDe(documento, abierta.plantilla, "post"));
    });
    return () => {
      vivo = false;
    };
  }, [abierta, servicio]);

  if (acciones.length === 0) return null;

  async function ejecutar(valores: Record<string, unknown>) {
    if (!abierta) return;
    setEnviando(true);
    setFallo(null);
    try {
      const r = await llamar<unknown>(abierta.ruta, { metodo: "POST", cuerpo: valores });
      setResultado(r.datos ?? { hecho: true });
      setAbierta(null);
      setConfirmada(false);
      alTerminar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  const irreversible = abierta ? IRREVERSIBLES.test(abierta.clave) : false;

  return (
    <section className="mb-3" aria-label={t("acciones.titulo")}>
      <div className="flex flex-wrap gap-2">
        {acciones.map((a) => (
          <button
            key={a.ruta}
            type="button"
            onClick={() => {
              setAbierta(a);
              setConfirmada(false);
              setResultado(null);
              setFallo(null);
            }}
            className={abierta?.ruta === a.ruta ? "btn-primary" : "btn-secondary"}
          >
            {a.nombre}
          </button>
        ))}
      </div>

      {resultado ? (
        <div className="card mt-3 border-success/40 p-3" role="status">
          <p className="inline-flex items-center gap-1.5 text-xs text-success">
            <Icono nombre="check_circle" tamano="sm" />
            {t("acciones.hecho")}
          </p>
          {/* Lo que contestó el servidor, en legible. La mitad de estas acciones
              devuelven algo que importa —qué se creó, qué quedó pendiente— y
              esconderlo sería tirar la respuesta; pero enseñarla en JSON con
              UUID dentro es lo mismo que esconderla. */}
          <Resultado datos={resultado} />
        </div>
      ) : null}

      {abierta ? (
        <div className="card mt-3 p-4">
          <h3 className="text-xs font-medium text-ink">{abierta.nombre}</h3>

          {irreversible && !confirmada ? (
            <div className="mt-3" role="alertdialog" aria-label={abierta.nombre}>
              <p className="text-2xs text-ink-muted">{t("acciones.noSeDeshace")}</p>
              <div className="mt-3 flex gap-2">
                <button type="button" onClick={() => setConfirmada(true)} className="btn-danger">
                  {t("acciones.entendido")}
                </button>
                <button
                  type="button"
                  onClick={() => setAbierta(null)}
                  className="btn-secondary"
                >
                  {t("modulo.cancelar")}
                </button>
              </div>
            </div>
          ) : campos === null ? (
            <Cargando />
          ) : (
            <div className="mt-3">
              {campos.length === 0 ? (
                // Sin campos no se enseña un formulario vacío: se ejecuta y ya.
                <button
                  type="button"
                  disabled={enviando}
                  onClick={() => void ejecutar({})}
                  className="btn-primary"
                >
                  {enviando ? t("app.cargando") : abierta.nombre}
                </button>
              ) : (
                <Formulario
                  campos={campos}
                  enviando={enviando}
                  textoEnviar={abierta.nombre}
                  alEnviar={(v) => void ejecutar(v)}
                />
              )}
              <button
                type="button"
                onClick={() => setAbierta(null)}
                className="btn-link mt-3"
              >
                {t("modulo.cancelar")}
              </button>
            </div>
          )}

          {fallo ? (
            <div className="mt-3">
              <Fallo error={fallo} />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
