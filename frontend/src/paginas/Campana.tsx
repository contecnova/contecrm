/**
 * Una campaña: qué prometió, qué está pasando y qué costó cada cosa
 * (CRM-02.02.01.02, CRM-02.02.01.04, CRM-02.02.01.05, CRM-02.02.01.07).
 *
 * El listado de marketing enseña el estado, el canal y cuánta gente tiene
 * dentro. Delante de una campaña las preguntas son otras cuatro, y ninguna la
 * contesta una lista.
 *
 * **«¿Va como dijimos que iría?»** Los objetivos se guardan al crearla y sin
 * ponerlos al lado del real no sirven de nada: una campaña con 400 clics es
 * buena si prometía 300 y mala si prometía 2.000, y el número solo se lee
 * igual en los dos casos. Un objetivo declarado sobre algo que el embudo no
 * mide sale diciendo que no se puede comparar, en vez de contra cero.
 *
 * **«¿Cuánto nos ha costado cada cosa?»** Coste por lead y por conversión con
 * el gasto delante, y el ROI **sólo cuando se puede medir**: sin ingresos
 * atribuidos no hay ROI, y un 0 % y un «no se sabe» se leen igual y significan
 * lo contrario. El propio servidor lo dice con `roi_medible` y su aviso.
 *
 * **«¿Quiénes son los 40 que hicieron clic?»** El embudo dice cuántos hay en
 * cada estado; para quien lleva la campaña la diferencia entre eso y poder
 * llamarlos es toda. Por eso la lista de miembros se filtra por estado: la de
 * una campaña de veinte mil no la mira nadie, la de los que abrieron y no
 * respondieron sí.
 *
 * **Y si es un evento, si apareció la gente.** Inscritos, asistieron y —la que
 * importa— **sin marcar**: una tasa de asistencia calculada ignorando a los
 * que nadie marcó es una tasa inventada, y el servidor por eso manda `medible`.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import {
  BotonesDeRegistro,
  ConfirmarBorrado,
  FormularioDeEdicion,
  useEdicion,
} from "@/componentes/Edicion";
import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";

interface Consumo {
  campana: string;
  presupuesto: string | null;
  gasto: string;
  gasto_propio: string;
  gasto_descendientes: string;
  restante: string | null;
  consumido_pct: number | null;
  sobrepasado: boolean;
  sin_presupuesto: boolean;
  hijos_presupuestados_de_mas: unknown[];
}

interface Rendimiento {
  campana: string;
  gasto: string;
  leads: number;
  convertidos: number;
  coste_por_lead: string | null;
  coste_por_conversion: string | null;
  ingresos_atribuidos: string | null;
  roi_pct: number | null;
  /** Sin ingresos atribuidos no hay ROI, y un 0 % diría lo contrario. */
  roi_medible: boolean;
  plan_vs_real: Record<string, { objetivo: number; real: number | null }>;
  aviso: string;
}

interface Embudo {
  campana: string;
  miembros: number;
  excluidos: number;
  embudo: Record<string, number>;
  conversion_pct: number | null;
}

interface Miembro {
  objeto: string;
  objeto_id: string;
  estado: string;
  fuente_alta: string;
  asistio: boolean | null;
  alta_at: string | null;
  estado_at: string | null;
}

interface Evento {
  campana: string;
  aforo: number | null;
  inscritos: number;
  asistieron: number;
  no_aparecieron: number;
  /** Lo que hace que la tasa sea una medida y no una estimación. */
  sin_marcar: number;
  tasa_asistencia_pct: number | null;
  medible: boolean;
}

export function Campana() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [consumo, setConsumo] = useState<Consumo | null>(null);
  const [rendimiento, setRendimiento] = useState<Rendimiento | null>(null);
  const [embudo, setEmbudo] = useState<Embudo | null>(null);
  const [evento, setEvento] = useState<Evento | null>(null);
  const [miembros, setMiembros] = useState<Miembro[]>([]);
  const [estado, setEstado] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const navegar = useNavigate();
  // La edición existía en la ficha genérica y no se pierde al traerse la
  // campaña a su propia pantalla: el contrato publica `PATCH`, y quitarla
  // aquí sería retirar algo que funcionaba sin que nadie lo decidiera.
  const modulo = moduloDe("campanas");
  const recurso = modulo ? recursoDe(modulo, "campana") : undefined;
  const { ruta, puedeEditar, puedeBorrar } = useEdicion(recurso, id);

  const cargar = useCallback(() => {
    const control = new AbortController();
    const { signal } = control;
    setFallo(null);
    llamar<Consumo>(`/api/v1/campanas/${id}/consumo`, { signal })
      .then((r) => setConsumo(r.datos))
      .catch(salvoCancelacion(setFallo));
    llamar<Rendimiento>(`/api/v1/campanas/${id}/rendimiento`, { signal })
      .then((r) => setRendimiento(r.datos))
      .catch(salvoCancelacion(() => setRendimiento(null)));
    llamar<Embudo>(`/api/v1/campanas/${id}/embudo`, { signal })
      .then((r) => setEmbudo(r.datos))
      .catch(salvoCancelacion(() => setEmbudo(null)));
    // El evento sólo existe si la campaña lo es: que no conteste no es un
    // fallo de la pantalla, es que esta campaña no es una feria.
    llamar<Evento>(`/api/v1/campanas/${id}/evento`, { signal })
      .then((r) => setEvento(r.datos))
      .catch(salvoCancelacion(() => setEvento(null)));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  const verMiembros = useCallback(
    (cual: string) => {
      setEstado(cual);
      void llamar<Miembro[]>(
        `/api/v1/campanas/${id}/miembros?estado=${cual}&limite=200`,
      )
        .then((r) => setMiembros(r.datos ?? []))
        .catch(() => setMiembros([]));
    },
    [id],
  );

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/m/campanas");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !consumo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!consumo) return <Cargando />;

  const plan = Object.entries(rendimiento?.plan_vs_real ?? {});
  const estados = Object.entries(embudo?.embudo ?? {});

  return (
    <>
      <CabeceraPagina
        titulo={consumo.campana}
        icono="campaign"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            {/* El gasto propio y el de los hijos, separados: una campaña que
                no ha gastado nada y cuyas tácticas se han comido el
                presupuesto se lee como barata si se suman. */}
            <span className="chip-dato font-mono">
              {t("campana.gasto", {
                gasto: consumo.gasto,
                propio: consumo.gasto_propio,
                hijos: consumo.gasto_descendientes,
              })}
            </span>
            {consumo.sin_presupuesto ? (
              <span className="badge badge-muted">{t("campana.sinPresupuesto")}</span>
            ) : (
              <span className={consumo.sobrepasado ? "badge badge-aviso" : "badge badge-muted"}>
                {t("campana.consumido", { pct: consumo.consumido_pct ?? 0 })}
              </span>
            )}
          </span>
        }
      />

      {!editando ? (
        <div className="mb-3">
          <BotonesDeRegistro
            puedeEditar={puedeEditar}
            puedeBorrar={puedeBorrar}
            alEditar={() => setEditando(true)}
            alBorrar={() => setConfirmando(true)}
          />
        </div>
      ) : null}

      {confirmando ? (
        <ConfirmarBorrado
          enviando={borrando}
          alBorrar={() => void borrar()}
          alCancelar={() => setConfirmando(false)}
        />
      ) : null}

      {editando && recurso ? (
        <FormularioDeEdicion
          recurso={recurso}
          ruta={ruta}
          valores={consumo as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      {consumo.sobrepasado ? (
        <p className="card mb-4 border-warning/40 p-3 text-2xs text-warning" role="status">
          {t("campana.sobrepasado", { restante: consumo.restante ?? "—" })}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-4">
          <h2 className="text-sm font-medium text-ink">{t("campana.planVsReal")}</h2>
          <p className="mt-1 text-3xs text-ink-faint">{t("campana.porquePlan")}</p>
          {plan.length === 0 ? (
            <Vacio titulo={t("campana.sinObjetivos")} detalle="" />
          ) : (
            <ul className="mt-2 flex flex-col gap-1">
              {plan.map(([clave, datos]) => (
                <li key={clave} className="flex items-baseline gap-2">
                  <span className="flex-1 text-2xs text-ink">{clave}</span>
                  {/* Un objetivo sobre algo que el embudo no mide NO se compara
                      contra cero: se dice que no se puede comparar. */}
                  <span className="font-mono text-2xs text-ink-muted">
                    {datos.real === null
                      ? t("campana.noComparable", { objetivo: datos.objetivo })
                      : t("campana.deObjetivo", {
                          real: datos.real,
                          objetivo: datos.objetivo,
                        })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card p-4">
          <h2 className="text-sm font-medium text-ink">{t("campana.coste")}</h2>
          {!rendimiento ? (
            <Vacio titulo={t("campana.sinRendimiento")} detalle="" />
          ) : (
            <>
              <p className="mt-2 font-mono text-2xs text-ink">
                {t("campana.porLead", {
                  lead: rendimiento.coste_por_lead ?? "—",
                  conversion: rendimiento.coste_por_conversion ?? "—",
                })}
              </p>
              {/* El ROI sólo cuando se puede medir. Sin ingresos atribuidos un
                  0 % y un «no se sabe» se leen igual y son lo contrario. */}
              <p className="mt-1 font-mono text-lg text-ink">
                {rendimiento.roi_medible
                  ? t("campana.roi", { pct: rendimiento.roi_pct })
                  : t("campana.roiNoMedible")}
              </p>
              {rendimiento.aviso ? (
                <p className="mt-1 text-2xs text-warning">{rendimiento.aviso}</p>
              ) : null}
            </>
          )}
        </section>

        <section className="card p-4 lg:col-span-2">
          <h2 className="text-sm font-medium text-ink">{t("campana.embudo")}</h2>
          {!embudo ? (
            <Vacio titulo={t("campana.sinEmbudo")} detalle="" />
          ) : (
            <>
              <p className="mt-1 font-mono text-3xs text-ink-muted">
                {t("campana.miembros", {
                  miembros: embudo.miembros,
                  excluidos: embudo.excluidos,
                })}
              </p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {estados.map(([cual, cuantos]) => (
                  <li key={cual}>
                    {/* Se puede pinchar: el embudo dice CUÁNTOS y lo que hace
                        falta es QUIÉNES, que es con quien se puede llamar. */}
                    <button
                      type="button"
                      className={estado === cual ? "badge badge-muted" : "chip-dato"}
                      onClick={() => verMiembros(cual)}
                    >
                      {t("campana.enEstado", { estado: cual, cuantos })}
                    </button>
                  </li>
                ))}
              </ul>
              {estado ? (
                <div className="mt-3" role="status" aria-live="polite">
                  <p className="text-3xs text-ink-faint">
                    {t("campana.quienes", { estado, cuantos: miembros.length })}
                  </p>
                  <ul className="lista-acotada mt-1 flex flex-col gap-1 pr-1">
                    {miembros.map((m) => (
                      <li key={m.objeto_id} className="flex items-baseline gap-2">
                        <span className="flex-1 font-mono text-3xs text-ink">
                          {m.objeto_id}
                        </span>
                        {/* De dónde salió: un miembro metido a mano y uno que
                            entró por el segmento no se tratan igual. */}
                        <span className="chip-dato">{m.fuente_alta}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          )}
        </section>

        {evento ? (
          <section className="card p-4 lg:col-span-2">
            <h2 className="text-sm font-medium text-ink">{t("campana.evento")}</h2>
            <p className="mt-2 font-mono text-2xs text-ink">
              {t("campana.asistencia", {
                inscritos: evento.inscritos,
                asistieron: evento.asistieron,
                faltaron: evento.no_aparecieron,
                aforo: evento.aforo ?? "—",
              })}
            </p>
            {/* Los sin marcar van delante de la tasa: una tasa calculada
                ignorándolos es una tasa inventada. */}
            {evento.sin_marcar > 0 ? (
              <p className="mt-1 text-2xs text-warning">
                {t("campana.sinMarcar", { cuantos: evento.sin_marcar })}
              </p>
            ) : null}
            <p className="mt-1 font-mono text-lg text-ink">
              {evento.medible
                ? t("campana.tasa", { pct: evento.tasa_asistencia_pct })
                : t("campana.tasaNoMedible")}
            </p>
          </section>
        ) : null}
      </div>
    </>
  );
}
