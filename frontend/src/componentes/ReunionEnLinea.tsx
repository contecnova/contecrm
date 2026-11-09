/**
 * «Crear reunión en línea», desde la ficha de una actividad o de un registro
 * (CRM-06.01.03.10).
 *
 * `POST /suites/reuniones` devolvía el endpoint y el cuerpo que **habría que**
 * mandar: no creaba ninguna sala. Ahora la crea en la suite que el tenant
 * tenga conectada —Microsoft 365/Teams o Google Meet, lo que declare su
 * perfil— y el enlace queda guardado en la actividad. Desde un registro, la
 * actividad de tipo reunión se crea con él.
 *
 * Antes de ofrecer el botón se pregunta si hay con qué: sin suite con
 * reuniones el botón sale **deshabilitado y con el motivo**, que es mejor que
 * esconderlo —lo escondido no se sabe que existe— y mejor que un botón que
 * siempre falla.
 *
 * El enlace es una credencial: se enseña aquí, en la ficha, y en ningún otro
 * sitio.
 */

import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { useSuperficie } from "@/lib/permisos";
import { cargarSesion } from "@/lib/sesion";

interface Proveedor {
  disponible: boolean;
  perfil?: string;
  sistema?: string;
  motivo?: string;
}

interface Sala {
  enlace: string;
  perfil: string;
  sistema?: string;
  creada_at?: string;
  guardada?: boolean;
  aviso?: string;
}

/** La reunión ya guardada en una actividad, si la tiene. */
export function reunionDe(
  fila: Record<string, unknown> | null | undefined,
): Sala | null {
  const detalles = (fila?.detalles ?? null) as Record<string, unknown> | null;
  const reunion = (detalles?.reunion ?? null) as Sala | null;
  return reunion && typeof reunion.enlace === "string" && reunion.enlace
    ? reunion
    : null;
}

export function ReunionEnLinea({
  actividadId,
  actividad,
  objeto,
  objetoId,
  alCrear,
  compacta = false,
}: {
  /** Ficha de una actividad: el enlace se guarda en ella. */
  actividadId?: string;
  actividad?: Record<string, unknown> | null;
  /** Ficha de un registro: se crea una actividad de reunión colgada de él. */
  objeto?: string;
  objetoId?: string;
  alCrear: () => void;
  /** Dentro de otra tarjeta: sin su propio recuadro. */
  compacta?: boolean;
}) {
  const { t } = useTranslation();
  const { tiene } = useSuperficie();
  const [proveedor, setProveedor] = useState<Proveedor | null>(null);
  const [abierto, setAbierto] = useState(false);
  const [asunto, setAsunto] = useState("");
  const [inicio, setInicio] = useState("");
  const [fin, setFin] = useState("");
  const [asistentes, setAsistentes] = useState("");
  const [organizador, setOrganizador] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [creada, setCreada] = useState<Sala | null>(null);

  useEffect(() => {
    let vivo = true;
    llamar<Proveedor>("/api/v1/suites/reuniones/proveedor")
      .then((r) => vivo && setProveedor(r.datos))
      .catch(() => vivo && setProveedor(null));
    return () => {
      vivo = false;
    };
  }, []);

  const guardada = creada ?? reunionDe(actividad);
  const desdeActividad = Boolean(actividadId);
  // En una actividad, lo que falte se toma de ella: sólo hace falta pedirlo
  // si la actividad no tiene hora.
  const faltaHora =
    !desdeActividad || !actividad?.inicio_at || !actividad?.fin_at;

  async function crear(evento: FormEvent) {
    evento.preventDefault();
    setEnviando(true);
    setFallo(null);
    try {
      const r = await llamar<Sala>("/api/v1/suites/reuniones", {
        metodo: "POST",
        cuerpo: {
          confirmada: true,
          ...(desdeActividad
            ? { actividad_id: actividadId }
            : { objeto, objeto_id: objetoId }),
          ...(asunto.trim() ? { asunto: asunto.trim() } : {}),
          ...(inicio ? { inicio: new Date(inicio).toISOString() } : {}),
          ...(fin ? { fin: new Date(fin).toISOString() } : {}),
          asistentes: asistentes
            .split(/[,;\s]+/)
            .map((a) => a.trim())
            .filter(Boolean),
          organizador: organizador.trim(),
        },
      });
      setCreada(r.datos);
      setAbierto(false);
      alCrear();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  if (!tiene("integration:write") && !guardada) return null;

  return (
    <section
      className={compacta ? "mb-3" : "card mb-4 p-4"}
      aria-labelledby="reunion-titulo"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="reunion-titulo" className="section-label">
          {t("reunionEnLinea.titulo")}
        </h2>
        {!guardada && !abierto ? (
          <button
            type="button"
            className="btn-primary"
            disabled={!proveedor?.disponible}
            onClick={() => {
              setAbierto(true);
              // Organiza quien pulsa, salvo que diga otra cuenta: con el campo
              // vacío, un perfil que la pide en la ruta llamaba a «/users//».
              void cargarSesion()
                .then((s) => setOrganizador((o) => o || s?.email || ""))
                .catch(() => undefined);
            }}
          >
            <Icono nombre="video_call" tamano="sm" />
            {t("reunionEnLinea.crear")}
          </button>
        ) : null}
      </div>

      <div role="status" className="mt-1">
        {guardada ? (
          <>
            <p className="text-dato text-ink">
              <a
                className="font-medium text-accent hover:underline"
                href={guardada.enlace}
                target="_blank"
                rel="noreferrer noopener"
              >
                {t("reunionEnLinea.entrar")}
              </a>{" "}
              <span className="text-rotulo text-ink-faint">
                {t("reunionEnLinea.creadaCon", {
                  perfil: guardada.sistema || guardada.perfil,
                  cuando: fechaHora(guardada.creada_at),
                })}
              </span>
            </p>
            <p className="text-rotulo text-ink-faint">
              {t("reunionEnLinea.credencial")}
            </p>
            {guardada.aviso ? (
              <p className="text-rotulo text-warning">{guardada.aviso}</p>
            ) : null}
          </>
        ) : proveedor && !proveedor.disponible ? (
          <p className="text-rotulo text-ink-faint">
            {t("reunionEnLinea.noDisponible", {
              motivo: proveedor.motivo ?? "",
            })}
          </p>
        ) : proveedor?.disponible ? (
          <p className="text-rotulo text-ink-faint">
            {t("reunionEnLinea.conQue", {
              perfil: proveedor.sistema || proveedor.perfil,
            })}
          </p>
        ) : null}
      </div>

      {abierto ? (
        <form
          className="mt-3 grid gap-2 md:grid-cols-2"
          onSubmit={(e) => void crear(e)}
        >
          {!desdeActividad ? (
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
              {t("reunionEnLinea.asunto")}
              <input
                className="input-base"
                value={asunto}
                required
                onChange={(e) => setAsunto(e.target.value)}
              />
            </label>
          ) : null}
          {faltaHora ? (
            <>
              <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
                {t("reunionEnLinea.inicio")}
                <input
                  className="input-base"
                  type="datetime-local"
                  value={inicio}
                  required
                  onChange={(e) => setInicio(e.target.value)}
                />
              </label>
              <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
                {t("reunionEnLinea.fin")}
                <input
                  className="input-base"
                  type="datetime-local"
                  value={fin}
                  required
                  onChange={(e) => setFin(e.target.value)}
                />
              </label>
            </>
          ) : null}
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("reunionEnLinea.asistentes")}
            <input
              className="input-base"
              value={asistentes}
              placeholder={t("reunionEnLinea.ejemploAsistentes")}
              onChange={(e) => setAsistentes(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("reunionEnLinea.organizador")}
            <input
              className="input-base"
              type="email"
              value={organizador}
              onChange={(e) => setOrganizador(e.target.value)}
            />
          </label>
          <div className="flex items-end gap-2 md:col-span-2">
            <button type="submit" className="btn-primary" disabled={enviando}>
              {t("reunionEnLinea.confirmar")}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setAbierto(false)}
            >
              {t("reunionEnLinea.cancelar")}
            </button>
          </div>
          <p className="text-rotulo text-ink-faint md:col-span-2">
            {t("reunionEnLinea.ayuda")}
          </p>
        </form>
      ) : null}

      {fallo ? (
        <div className="mt-2">
          <Fallo error={fallo} />
        </div>
      ) : null}
    </section>
  );
}
