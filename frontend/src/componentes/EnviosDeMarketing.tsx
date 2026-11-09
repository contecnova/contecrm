/**
 * Lo que sale de una campaña o de un recorrido: cada persona a su hora y por su
 * canal, y cada clase por su dominio (CRM-02.02.02.05, CRM-02.03.01.07).
 *
 * Verificado pulsando el 09-11-2026: en la ficha de una campaña se programa el
 * envío y cada fila dice la hora local elegida, el canal, si salió del
 * historial, de lo que pidió la persona o del valor por defecto —y por qué—;
 * al despachar, el dominio, el remitente y el servidor por los que salió. El
 * mismo bloque está en el recorrido, con el nodo que programó cada envío.
 *
 * Dice **cuántos van a la hora general** delante de la lista: si son casi
 * todos, la personalización no está haciendo nada y conviene saberlo antes de
 * contarlo como una mejora.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo, Vacio } from "@/componentes/Estados";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { cn } from "@/lib/utiles";

interface Envio {
  id: string;
  objeto_id: string;
  nodo: string | null;
  canal: string;
  clase: string;
  plantilla: string;
  programado_at: string;
  hora_local: number;
  zona: string;
  como_hora: string | null;
  como_canal: string | null;
  porque: string | null;
  estado: string;
  motivo: string | null;
  dominio: string | null;
  remitente: string | null;
  flujo: string | null;
}

interface Listado {
  programados: number;
  omitidos: number;
  a_la_hora_general: number;
  personalizados: number;
  que_significa: string;
  por_estado: Record<string, number>;
  envios: Envio[];
}

const TONO: Record<string, string> = {
  enviado: "chip-dato--si",
  fallido: "chip-dato--mal",
  omitido: "chip-dato--aviso",
  programado: "",
};

export function EnviosProgramados({
  origen,
  origenId,
  recarga = 0,
}: {
  origen: "campana" | "recorrido";
  origenId: string;
  recarga?: number;
}) {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Listado | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");

  const cargar = useCallback(() => {
    llamar<Listado>(
      `/api/v1/envios-programados?origen=${origen}&origen_id=${origenId}`,
    )
      // Una respuesta sin `envios` se trata como vacía: la pantalla de la
      // campaña no se puede caer entera por este bloque.
      .then((r) => setDatos(Array.isArray(r.datos?.envios) ? r.datos : null))
      .catch(setFallo);
  }, [origen, origenId]);
  useEffect(cargar, [cargar, recarga]);

  async function despachar(forzar: boolean) {
    try {
      const r = await llamar<{ enviados: number; fallidos: number }>(
        "/api/v1/envios-programados/despachar",
        {
          metodo: "POST",
          cuerpo: { origen, origen_id: origenId, forzar },
        },
      );
      setAviso(
        t("mk.envios.despachados", {
          enviados: r.datos.enviados,
          fallidos: r.datos.fallidos,
        }),
      );
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <section className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="section-label">{t("mk.envios.titulo")}</h2>
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => void despachar(false)}
          >
            {t("mk.envios.despacharLosQueTocan")}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => void despachar(true)}
          >
            {t("mk.envios.despacharYa")}
          </button>
        </div>
      </div>
      <p className="mb-2 text-rotulo text-ink-faint">{t("mk.envios.ayuda")}</p>
      <div role="status">
        {aviso ? <p className="mb-2 text-dato text-success">{aviso}</p> : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      {!datos ? null : datos.envios.length === 0 ? (
        <Vacio titulo={t("mk.envios.ninguno")} compacto />
      ) : (
        <>
          <p className="mb-2 text-dato text-ink">
            {t("mk.envios.resumen", {
              programados: datos.programados,
              personalizados: datos.personalizados,
              general: datos.a_la_hora_general,
              omitidos: datos.omitidos,
            })}
          </p>
          <p className="mb-2 text-rotulo text-ink-faint">
            {datos.que_significa}
          </p>
          <Rejilla
            titulo={t("mk.envios.titulo")}
            compacta
            cabeceras={[
              t("mk.envios.persona"),
              t("mk.envios.cuando"),
              t("mk.envios.canal"),
              t("mk.envios.porque"),
              t("mk.envios.estado"),
              t("mk.envios.salida"),
            ]}
          >
            {datos.envios.map((e) => (
              <tr
                key={e.id}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla className="font-mono text-rotulo">
                  {e.objeto_id.slice(0, 8)}
                  {e.nodo ? (
                    <span className="ml-1 chip-dato">{e.nodo}</span>
                  ) : null}
                </Casilla>
                <Casilla>
                  {t("mk.envios.horaLocal", {
                    hora: String(e.hora_local).padStart(2, "0"),
                    zona: e.zona,
                  })}
                  <br />
                  <span className="text-rotulo text-ink-faint">
                    {fechaHora(e.programado_at)}
                  </span>
                </Casilla>
                <Casilla>
                  <span className="chip-dato">{e.canal}</span>{" "}
                  <span className="chip-dato">
                    {t(`mk.envios.clase.${e.clase}`, { defaultValue: e.clase })}
                  </span>
                </Casilla>
                <Casilla className="max-w-[22rem] text-rotulo">
                  <span className="chip-dato mr-1">
                    {t(`mk.envios.como.${e.como_hora ?? "por_defecto"}`, {
                      defaultValue: e.como_hora ?? "",
                    })}
                  </span>
                  {e.porque}
                </Casilla>
                <Casilla>
                  <span className={cn("chip-dato", TONO[e.estado] ?? "")}>
                    {t(`mk.envios.estados.${e.estado}`, {
                      defaultValue: e.estado,
                    })}
                  </span>
                  {e.motivo ? (
                    <p className="text-rotulo text-ink-faint">{e.motivo}</p>
                  ) : null}
                </Casilla>
                <Casilla className="text-rotulo">
                  {e.remitente ? (
                    <>
                      {e.remitente}
                      <br />
                      <span className="text-ink-faint">{e.flujo}</span>
                    </>
                  ) : (
                    "—"
                  )}
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        </>
      )}
    </section>
  );
}

interface Clase {
  clase: string;
  dominio: string | null;
  remitente: string | null;
  flujo: { origen: string; host: string | null; puerto: number; tls: string };
  autenticacion: {
    spf: boolean;
    dkim: boolean;
    dmarc: string | null;
  } | null;
  puede_salir: boolean;
  problemas: string[];
}

interface Separacion {
  promocional: Clase;
  transaccional: Clase;
  separados: boolean;
  mismo_flujo: boolean;
  aviso: string;
}

/** Por qué dominio, remitente y servidor sale cada clase (CRM-02.03.01.07). */
export function SalidaPorClase() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Separacion | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  useEffect(() => {
    llamar<Separacion>("/api/v1/correo/salida")
      .then((r) => setDatos(r.datos))
      .catch(setFallo);
  }, []);
  if (fallo) return <Fallo error={fallo} />;
  if (!datos?.promocional || !datos.transaccional) return null;
  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("mk.salida.titulo")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">{t("mk.salida.ayuda")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {[datos.promocional, datos.transaccional].map((c) => (
          <div
            key={c.clase}
            className="rounded-lg border border-ink-dim/40 p-3 text-dato"
          >
            <p className="font-medium text-ink">
              {t(`mk.envios.clase.${c.clase}`)}
            </p>
            <p>
              {t("mk.salida.dominio")}: {c.dominio ?? "—"}
            </p>
            <p>
              {t("mk.salida.remitente")}: {c.remitente ?? "—"}
            </p>
            <p>
              {t("mk.salida.flujo")}: {c.flujo.host ?? "—"} (
              {t(`mk.salida.origen.${c.flujo.origen}`)})
            </p>
            {c.autenticacion ? (
              <p className="mt-1 flex flex-wrap gap-1">
                <span
                  className={cn(
                    "chip-dato",
                    c.autenticacion.spf ? "chip-dato--si" : "chip-dato--mal",
                  )}
                >
                  SPF
                </span>
                <span
                  className={cn(
                    "chip-dato",
                    c.autenticacion.dkim ? "chip-dato--si" : "chip-dato--mal",
                  )}
                >
                  DKIM
                </span>
                <span
                  className={cn(
                    "chip-dato",
                    c.autenticacion.dmarc ? "chip-dato--si" : "chip-dato--mal",
                  )}
                >
                  DMARC {c.autenticacion.dmarc ?? ""}
                </span>
              </p>
            ) : null}
            {c.problemas.map((p) => (
              <p key={p} className="mt-1 text-rotulo text-warning">
                {p}
              </p>
            ))}
          </div>
        ))}
      </div>
      <p
        className={cn(
          "mt-2 text-dato",
          datos.separados && !datos.mismo_flujo
            ? "text-success"
            : "text-warning",
        )}
      >
        {datos.aviso || t("mk.salida.separados")}
      </p>
    </section>
  );
}

interface Plantilla {
  clave: string;
  nombre: string;
  clase: string;
}

/** El envío de una campaña: elegir la plantilla y programarla persona a persona. */
export function EnvioDeCampana({ campanaId }: { campanaId: string }) {
  const { t } = useTranslation();
  const [plantillas, setPlantillas] = useState<Plantilla[]>([]);
  const [plantilla, setPlantilla] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const [recarga, setRecarga] = useState(0);

  useEffect(() => {
    llamar<Plantilla[]>("/api/v1/correo/plantillas")
      .then((r) => {
        const filas = Array.isArray(r.datos) ? r.datos : [];
        setPlantillas(filas);
        if (filas[0]) setPlantilla(filas[0].clave);
      })
      .catch(() => setPlantillas([]));
  }, []);

  async function programar() {
    try {
      const r = await llamar<{
        programados: number;
        personalizados: number;
        a_la_hora_general: number;
        omitidos: number;
      }>(`/api/v1/campanas/${campanaId}/programar-envio`, {
        metodo: "POST",
        cuerpo: { plantilla },
      });
      setAviso(
        t("mk.envios.programado", {
          programados: r.datos.programados,
          personalizados: r.datos.personalizados,
          general: r.datos.a_la_hora_general,
          omitidos: r.datos.omitidos,
        }),
      );
      setFallo(null);
      setRecarga((n) => n + 1);
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <div className="flex flex-col gap-4 lg:col-span-2">
      <section className="card p-4">
        <h2 className="section-label mb-1">{t("mk.envios.programar")}</h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {t("mk.envios.programarAyuda")}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-dato text-ink-muted" htmlFor="mk-plantilla">
            {t("mk.envios.plantilla")}
          </label>
          <select
            id="mk-plantilla"
            className="input-base w-auto"
            value={plantilla}
            onChange={(e) => setPlantilla(e.target.value)}
          >
            {plantillas.map((p) => (
              <option key={p.clave} value={p.clave}>
                {p.nombre} · {p.clase}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn-primary"
            disabled={!plantilla}
            onClick={() => void programar()}
          >
            {t("mk.envios.programarBoton")}
          </button>
        </div>
        <div role="status">
          {aviso ? (
            <p className="mt-2 text-dato text-success">{aviso}</p>
          ) : null}
        </div>
        {fallo ? <Fallo error={fallo} /> : null}
      </section>
      <EnviosProgramados
        origen="campana"
        origenId={campanaId}
        recarga={recarga}
      />
      <SalidaPorClase />
    </div>
  );
}
