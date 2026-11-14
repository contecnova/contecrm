/**
 * Traspasar la cartera de una persona a otra (CRM-07.01.01.07).
 *
 * Es lo que hace falta cuando alguien deja la empresa o cambia de cartera, y
 * existía sólo por API —`POST /party-admin/transferir-propiedad`, con
 * simulación— para cuentas, contactos y actividades. Los leads y las
 * oportunidades, que son de ventas, no tenían traspaso: ahora `sales` publica
 * la misma ruta sobre los suyos y esta pantalla llama a las dos.
 *
 * Es un asistente de tres pasos, y el orden importa:
 *
 * 1. **De quién y a quién**, elegidos de la lista de personas —no tecleando un
 *    identificador—.
 * 2. **Simular**: cuántos registros de cada tipo se moverían, servicio a
 *    servicio. Mil cuentas y tres oportunidades es una cosa, y al revés es
 *    otra; quien lo ejecuta tiene que verlo antes.
 * 3. **Confirmar** con un motivo, que queda en la auditoría. El botón sólo se
 *    enciende después de simular y mientras no se cambie la pareja: confirmar
 *    algo distinto de lo que se ha visto es justo lo que se quiere evitar.
 *
 * Si un servicio contesta mal —sin permiso, caído— se dice en su fila y no se
 * esconde: un traspaso que movió las cuentas y no las oportunidades deja a la
 * persona nueva con media cartera.
 *
 * Comprobado en el navegador el 09-11-2026: simular entre dos personas
 * (1 cuenta en Clientes, 1 lead en Ventas) y confirmar con motivo.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AvisoDelDirectorio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { ErrorApi, llamar } from "@/lib/api";
import { humanizar } from "@/lib/formato";
import { useDirectorio } from "@/lib/personas";

/** Dónde se traspasa, servicio a servicio. Cada uno mueve lo suyo. */
export const RUTAS_DE_TRASPASO = [
  { servicio: "clientes", ruta: "/api/v1/party-admin/transferir-propiedad" },
  { servicio: "ventas", ruta: "/api/v1/sales-admin/transferir-propiedad" },
] as const;

interface Resultado {
  servicio: string;
  movidos: Record<string, number>;
  total: number;
  error: string;
}

export function TransferirPropiedad() {
  const { t } = useTranslation();
  // El directorio y no `usePersonas`: éste no dice ni que está cargando ni
  // que ha fallado, y los dos desplegables salían con sólo «Elige» —igual
  // que si no hubiera nadie a quien traspasar— (auditoría 13-11-2026, UX-11).
  const directorio = useDirectorio();
  const [de, setDe] = useState("");
  const [a, setA] = useState("");
  const [motivo, setMotivo] = useState("");
  const [simulacion, setSimulacion] = useState<{
    de: string;
    a: string;
    resultados: Resultado[];
  } | null>(null);
  const [hecho, setHecho] = useState<Resultado[] | null>(null);
  const [enviando, setEnviando] = useState(false);

  const ordenadas = directorio.personas ?? [];
  const cargandoPersonas = directorio.personas === null && !directorio.fallo;

  async function lanzar(simular: boolean): Promise<Resultado[]> {
    return Promise.all(
      RUTAS_DE_TRASPASO.map(async ({ servicio, ruta }) => {
        try {
          const r = await llamar<{
            movidos: Record<string, number>;
            total: number;
          }>(ruta, {
            metodo: "POST",
            cuerpo: { de_usuario: de, a_usuario: a, simular, motivo },
          });
          return {
            servicio,
            movidos: r.datos.movidos,
            total: r.datos.total,
            error: "",
          };
        } catch (error) {
          return {
            servicio,
            movidos: {},
            total: 0,
            error:
              error instanceof ErrorApi
                ? error.explicacion || error.titulo
                : t("propiedad.noContesta"),
          };
        }
      }),
    );
  }

  async function simular() {
    setEnviando(true);
    setHecho(null);
    try {
      setSimulacion({ de, a, resultados: await lanzar(true) });
    } finally {
      setEnviando(false);
    }
  }

  async function confirmar() {
    setEnviando(true);
    try {
      setHecho(await lanzar(false));
      setSimulacion(null);
    } finally {
      setEnviando(false);
    }
  }

  const vigente = simulacion && simulacion.de === de && simulacion.a === a;
  const totalSimulado =
    simulacion?.resultados.reduce((n, r) => n + r.total, 0) ?? 0;
  const listo = Boolean(de && a && de !== a);

  return (
    <>
      <CabeceraPagina
        icono="swap_horiz"
        titulo={t("propiedad.titulo")}
        entradilla={t("propiedad.entradilla")}
      />

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">{t("propiedad.paso1")}</h2>
        <div className="flex flex-wrap items-end gap-4">
          <Elegir
            id="propiedad-de"
            rotulo={t("propiedad.de")}
            valor={de}
            alCambiar={setDe}
            personas={ordenadas}
            cargando={cargandoPersonas}
          />
          <Elegir
            id="propiedad-a"
            rotulo={t("propiedad.a")}
            valor={a}
            alCambiar={setA}
            personas={ordenadas.filter((p) => p.id !== de)}
            cargando={cargandoPersonas}
          />
          <button
            type="button"
            className="btn-secondary"
            disabled={!listo || enviando}
            onClick={() => void simular()}
          >
            {t("propiedad.simular")}
          </button>
        </div>
        <AvisoDelDirectorio directorio={directorio} />
        {de && a && de === a ? (
          <p className="mt-2 text-dato text-warning" role="status">
            {t("propiedad.mismaPersona")}
          </p>
        ) : null}
      </section>

      {simulacion ? (
        <section className="card mb-4 p-4" role="status">
          <h2 className="section-label mb-1">{t("propiedad.paso2")}</h2>
          <Movidos resultados={simulacion.resultados} />
          <p className="mt-2 text-dato text-ink">
            {t("propiedad.totalSimulado", { count: totalSimulado })}
          </p>
          {totalSimulado > 0 && vigente ? (
            <div className="mt-3 max-w-xl">
              <label htmlFor="propiedad-motivo" className="label-base">
                {t("propiedad.motivo")}
              </label>
              <input
                id="propiedad-motivo"
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                placeholder={t("propiedad.motivoEjemplo")}
                className="input-base"
              />
              <button
                type="button"
                className="btn-primary mt-3"
                disabled={enviando || motivo.trim().length < 5}
                onClick={() => void confirmar()}
              >
                {t("propiedad.confirmar", { count: totalSimulado })}
              </button>
            </div>
          ) : null}
          {!vigente ? (
            <p className="mt-2 text-dato text-warning">
              {t("propiedad.cambiaste")}
            </p>
          ) : null}
        </section>
      ) : null}

      {hecho ? (
        <section className="card p-4" role="status">
          <h2 className="section-label mb-1">{t("propiedad.hecho")}</h2>
          <Movidos resultados={hecho} />
        </section>
      ) : null}
    </>
  );
}

function Elegir({
  id,
  rotulo,
  valor,
  alCambiar,
  personas,
  cargando,
}: {
  id: string;
  rotulo: string;
  valor: string;
  alCambiar: (v: string) => void;
  personas: { id: string; nombre: string; email: string }[];
  cargando: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="min-w-[16rem]">
      <label htmlFor={id} className="label-base">
        {rotulo}
      </label>
      <select
        id={id}
        value={valor}
        onChange={(e) => alCambiar(e.target.value)}
        disabled={cargando}
        aria-busy={cargando}
        className="input-base"
      >
        <option value="">
          {cargando ? t("app.cargando") : t("propiedad.elige")}
        </option>
        {personas.map((p) => (
          <option key={p.id} value={p.id}>
            {p.nombre ? `${p.nombre} · ${p.email}` : p.email}
          </option>
        ))}
      </select>
    </div>
  );
}

interface FilaMovida {
  clave: string;
  servicio: string;
  tipo: string;
  cuantos: number | null;
  error: string;
}

/** Cuántos de cada tipo, servicio a servicio, con lo que falló a la vista. */
function Movidos({ resultados }: { resultados: Resultado[] }) {
  const { t } = useTranslation();
  const filas = resultados.flatMap((r): FilaMovida[] =>
    r.error
      ? [
          {
            clave: `${r.servicio}-error`,
            servicio: r.servicio,
            tipo: "",
            cuantos: null,
            error: r.error,
          },
        ]
      : Object.keys(r.movidos).length === 0
        ? [
            {
              clave: `${r.servicio}-nada`,
              servicio: r.servicio,
              tipo: "",
              cuantos: 0,
              error: "",
            },
          ]
        : Object.entries(r.movidos).map(([tipo, cuantos]) => ({
            clave: `${r.servicio}-${tipo}`,
            servicio: r.servicio,
            tipo,
            cuantos,
            error: "",
          })),
  );
  return (
    <Rejilla
      titulo={t("propiedad.paso2")}
      cabeceras={[
        t("propiedad.servicio"),
        t("propiedad.tipo"),
        t("propiedad.cuantos"),
      ]}
    >
      {filas.map((f) => (
        <tr key={f.clave} className="border-b border-ink-dim/30 last:border-0">
          <Casilla enUnaLinea>{t(`propiedad.servicios.${f.servicio}`)}</Casilla>
          <Casilla>
            {f.error ? (
              <span className="text-danger">{f.error}</span>
            ) : f.tipo ? (
              humanizar(f.tipo)
            ) : (
              <span className="text-ink-faint">{t("propiedad.nada")}</span>
            )}
          </Casilla>
          <Casilla enUnaLinea>{f.cuantos ?? "—"}</Casilla>
        </tr>
      ))}
    </Rejilla>
  );
}
