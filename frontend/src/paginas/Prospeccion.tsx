/**
 * Qué plantillas funcionan, y a quién le toca la próxima reunión
 * (CRM-03.03.01.06, CRM-03.03.01.07).
 *
 * **Una tasa de respuesta sin su número de envíos es ruido.** Con nueve
 * correos, un 33 % son tres respuestas y mañana puede ser un 11 %: ordenar
 * plantillas por ese porcentaje hace que la mejor sea siempre la que menos se
 * ha usado. El servidor marca cada plantilla como **concluyente** o no, y aquí
 * la que no lo es sale con su aviso y no compite con las demás.
 *
 * **Y la apertura se mira aparte, con su advertencia.** Contarla depende de un
 * píxel que la mitad de los clientes de correo bloquean, así que una apertura
 * baja puede ser una plantilla mala o un cliente de correo prudente. La
 * respuesta no tiene ese problema, y por eso es la que manda.
 *
 * **El reparto de reuniones consume turno.** Pedir «a quién le toca» no es una
 * consulta: avanza el round-robin. Por eso va con un botón y no se pide al
 * abrir — una pantalla que lo pidiera sola repartiría reuniones cada vez que
 * alguien la mira.
 *
 * Y un equipo sin nadie con disponibilidad **no reparte en silencio**: el
 * servidor contesta que no hay a quién, porque repartir entre cero personas
 * deja la reunión sin proponer y sin que nadie se entere.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { ErrorApi, llamar, salvoCancelacion } from "@/lib/api";

interface Plantilla {
  clave: string;
  nombre: string;
  enviados: number;
  respondidos: number;
  reuniones: number;
  tasa_respuesta: number | null;
  tasa_reunion: number | null;
  abiertos: number;
  /** La apertura depende de un píxel que media industria bloquea. */
  aviso_apertura: string;
  /** Con nueve envíos un 33 % es ruido, y el servidor lo dice. */
  concluyente: boolean;
  aviso: string;
}

interface Rendimiento {
  plantillas: Plantilla[];
  medible: boolean;
}

interface Hueco {
  desde: string;
  hasta: string;
}

interface Turno {
  usuario_id: string;
  equipo: string;
  /** Pedirlo AVANZA el round-robin: no es una consulta. */
  turno_consumido: boolean;
  huecos: Hueco[];
}

export function Prospeccion() {
  const { t } = useTranslation();
  const [rendimiento, setRendimiento] = useState<Rendimiento | null>(null);
  const [equipo, setEquipo] = useState("");
  const [turno, setTurno] = useState<Turno | null>(null);
  const [pidiendo, setPidiendo] = useState(false);
  const [sinNadie, setSinNadie] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Rendimiento>("/api/v1/plantillas-correo/rendimiento", {
      signal: control.signal,
    })
      .then((r) => setRendimiento(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  async function aQuienLeToca() {
    if (!equipo.trim()) return;
    setPidiendo(true);
    setSinNadie("");
    setTurno(null);
    try {
      const r = await llamar<Turno>("/api/v1/agenda/turno", {
        metodo: "POST",
        cuerpo: { equipo, dias: 5 },
      });
      setTurno(r.datos);
    } catch (error) {
      // Un equipo sin nadie disponible no es un fallo de la pantalla: es la
      // respuesta, y lleva dentro por qué.
      // `explicacion` y no `message`: la frase del servidor está escrita
      // para leerse —dice que repartir entre cero personas deja la reunión
      // sin proponer— y el título es sólo «No encontrado».
      setSinNadie(
        error instanceof ErrorApi
          ? error.explicacion || error.message
          : String(error),
      );
    } finally {
      setPidiendo(false);
    }
  }

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;

  const plantillas = rendimiento?.plantillas ?? [];
  const concluyentes = plantillas.filter((p) => p.concluyente);
  const pocas = plantillas.filter((p) => !p.concluyente);

  return (
    <>
      <CabeceraPagina
        titulo={t("prospeccion.titulo")}
        icono="forward_to_inbox"
        entradilla={t("prospeccion.entradilla")}
      />

      <section className="card mb-4 p-4">
        <h2 className="text-sm font-medium text-ink">{t("prospeccion.aQuienLeToca")}</h2>
        {/* Con botón y no al abrir: pedirlo AVANZA el round-robin, así que
            una pantalla que lo pidiera sola repartiría reuniones cada vez que
            alguien la mira. */}
        <p className="mt-1 text-3xs text-ink-faint">{t("prospeccion.porqueBoton")}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            className="input-base"
            value={equipo}
            aria-label={t("prospeccion.equipo")}
            placeholder={t("prospeccion.equipo")}
            onChange={(e) => setEquipo(e.target.value)}
          />
          <button
            type="button"
            className="btn-secundario"
            disabled={!equipo.trim() || pidiendo}
            onClick={() => void aQuienLeToca()}
          >
            {pidiendo ? t("prospeccion.pidiendo") : t("prospeccion.pedirTurno")}
          </button>
        </div>
        <div role="status" aria-live="polite">
          {sinNadie ? <p className="mt-2 text-2xs text-warning">{sinNadie}</p> : null}
          {turno ? (
            <div className="mt-2">
              <p className="font-mono text-2xs text-ink">
                {t("prospeccion.leToca", { usuario: turno.usuario_id })}
              </p>
              {/* Que el turno se ha consumido se dice: si no, alguien pulsa
                  tres veces para «ver» y se salta a dos del equipo. */}
              {turno.turno_consumido ? (
                <p className="mt-1 text-3xs text-warning">
                  {t("prospeccion.turnoConsumido")}
                </p>
              ) : null}
              <p className="mt-1 text-2xs text-ink-muted">
                {turno.huecos.length === 0
                  ? t("prospeccion.sinHuecos")
                  : t("prospeccion.huecos", { cuantos: turno.huecos.length })}
              </p>
            </div>
          ) : null}
        </div>
      </section>

      <section>
        <h2 className="text-sm font-medium text-ink">{t("prospeccion.plantillas")}</h2>
        <p className="mt-1 text-3xs text-ink-faint">{t("prospeccion.porqueConcluyente")}</p>
        {!rendimiento?.medible ? (
          <Vacio
            titulo={t("prospeccion.sinMedir")}
            detalle={t("prospeccion.sinMedirDetalle")}
          />
        ) : (
          <>
            {concluyentes.length === 0 ? (
              <Vacio titulo={t("prospeccion.ningunaConcluyente")} detalle="" />
            ) : (
              <ul className="lista-acotada mt-2 flex flex-col gap-2 pr-1">
                {concluyentes.map((p) => (
                  <li key={p.clave} className="card p-3">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="flex-1 text-sm text-ink">{p.nombre}</span>
                      <span className="font-mono text-2xs text-ink">
                        {t("prospeccion.tasas", {
                          respuesta: p.tasa_respuesta ?? "—",
                          reunion: p.tasa_reunion ?? "—",
                        })}
                      </span>
                    </div>
                    {/* El denominador al lado del porcentaje, siempre. */}
                    <p className="mt-1 font-mono text-3xs text-ink-muted">
                      {t("prospeccion.sobre", {
                        enviados: p.enviados,
                        respondidos: p.respondidos,
                        reuniones: p.reuniones,
                      })}
                    </p>
                    {p.aviso_apertura ? (
                      <p className="mt-1 text-3xs text-ink-faint">{p.aviso_apertura}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}

            {/* Las que no son concluyentes, APARTE y no mezcladas: ordenadas
                con las demás, la mejor sería siempre la que menos se ha
                usado. */}
            {pocas.length > 0 ? (
              <div className="mt-3">
                <p className="text-2xs text-warning">
                  {t("prospeccion.pocasVeces", { cuantas: pocas.length })}
                </p>
                <ul className="lista-acotada mt-1 flex flex-col gap-1 pr-1">
                  {pocas.map((p) => (
                    <li key={p.clave} className="flex items-baseline gap-2">
                      <span className="flex-1 text-2xs text-ink-muted">{p.nombre}</span>
                      <span className="font-mono text-3xs text-ink-faint">
                        {t("prospeccion.envios", { enviados: p.enviados })}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        )}
      </section>
    </>
  );
}
