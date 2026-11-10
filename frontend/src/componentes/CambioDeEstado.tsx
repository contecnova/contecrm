/**
 * El estado de un registro, y a cuáles se puede pasar desde él (CRM-00.04.01.07).
 *
 * Con la configuración de la empresa: su nombre y su color, y sólo los
 * destinos que su máquina permite desde el estado actual. Es lo que hace
 * alcanzables los estados propios —«En pausa»—: se podían declarar en
 * Administrar y no había desde dónde llegar a ellos. Si pasar a uno pide
 * motivo, se pide aquí; si tiene su propio camino —ganar, convertir—, lo dice
 * el servidor.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import { ErrorApi, llamar, salvoCancelacion } from "@/lib/api";
import { rotuloDeOpcion } from "@/lib/formato";

interface Config {
  estados: {
    clave: string;
    nombre: string;
    color: string;
    activo: boolean;
    significado?: string;
  }[];
  transiciones: Record<string, string[]>;
  exigen_motivo: string[];
  /**
   * Los estados a los que se llega con su acción —«Enviar», «Convertir»— y no
   * con este desplegable, con cuál es. No se ofrecen: el servidor los rechaza,
   * y ofrecerlos era prometer lo que no se puede hacer desde aquí (medido el
   * 10-11-2026 con «Enviado» en el presupuesto, tarea T05).
   */
  con_su_camino: Record<string, string>;
}

/**
 * Qué objetos de cada servicio tienen estados configurables, una vez por
 * servicio y sesión de la pantalla.
 *
 * Antes se pedía `/{servicio}/estados/{objeto}` para TODO registro con campo
 * `estado` y se contaba con el 404 para no pintar nada: la ficha de un sandbox
 * pedía `/tenancy/estados/sandbox` y dejaba un 404 en cada visita —medido el
 * 09-11-2026—, que es ruido en la consola y un falso aviso para quien vigila
 * los errores. Preguntando primero la lista, sólo se pide lo que existe.
 */
const objetosConEstados = new Map<string, Promise<Set<string>>>();

function conEstados(servicio: string): Promise<Set<string>> {
  const hay = objetosConEstados.get(servicio);
  if (hay) return hay;
  const pedida = llamar<{ items?: { objeto: string }[] }>(
    `/api/v1/${servicio}/estados`,
  )
    .then((r) => new Set((r.datos?.items ?? []).map((i) => i.objeto)))
    .catch(() => {
      // Un fallo no se recuerda: la siguiente ficha lo vuelve a intentar.
      objetosConEstados.delete(servicio);
      return new Set<string>();
    });
  objetosConEstados.set(servicio, pedida);
  return pedida;
}

export function CambioDeEstado({
  servicio,
  objeto,
  ruta,
  estado,
  alCambiar,
}: {
  servicio: string;
  objeto: string;
  /** La ruta del registro; la acción es `{ruta}/estado`. */
  ruta: string;
  estado: string;
  alCambiar: () => void;
}) {
  const { t } = useTranslation();
  const [conf, setConf] = useState<Config | null>(null);
  const [abierto, setAbierto] = useState(false);
  const [pidiendoMotivo, setPidiendoMotivo] = useState<string>("");
  const [motivo, setMotivo] = useState("");
  const [fallo, setFallo] = useState("");
  const caja = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const control = new AbortController();
    // Un objeto sin estados configurables no se pide: no se pinta.
    conEstados(servicio)
      .then((objetos) => {
        if (!objetos.has(objeto)) return null;
        return llamar<Config>(`/api/v1/${servicio}/estados/${objeto}`, {
          signal: control.signal,
        });
      })
      // Lo que no venga cuenta como vacío: la cabecera de una ficha no puede
      // caerse por una respuesta a medias.
      .then((r) =>
        setConf(
          r && Array.isArray(r.datos?.estados)
            ? {
                estados: r.datos.estados,
                transiciones: r.datos.transiciones ?? {},
                exigen_motivo: r.datos.exigen_motivo ?? [],
                con_su_camino: r.datos.con_su_camino ?? {},
              }
            : null,
        ),
      )
      .catch(salvoCancelacion(() => setConf(null)));
    return () => control.abort();
  }, [servicio, objeto]);

  useEffect(() => {
    if (!abierto) return;
    const fuera = (e: MouseEvent) => {
      if (!caja.current?.contains(e.target as Node)) setAbierto(false);
    };
    document.addEventListener("mousedown", fuera);
    return () => document.removeEventListener("mousedown", fuera);
  }, [abierto]);

  if (!conf) return null;
  const de = (clave: string) => conf.estados.find((e) => e.clave === clave);
  const nombre = (clave: string) => de(clave)?.nombre || rotuloDeOpcion(clave);
  const significado = (clave: string) => de(clave)?.significado ?? clave;
  const destinos = (conf.transiciones[estado] ?? []).filter(
    (d) =>
      de(d)?.activo !== false &&
      // Entre dos que significan lo mismo no hay acción que rehacer.
      (!conf.con_su_camino[d] || significado(d) === significado(estado)),
  );
  const color = de(estado)?.color;

  async function mover(destino: string, conMotivo: string) {
    setFallo("");
    try {
      await llamar(`${ruta}/estado`, {
        metodo: "POST",
        cuerpo: { estado: destino, motivo: conMotivo },
      });
      setPidiendoMotivo("");
      setMotivo("");
      alCambiar();
    } catch (e) {
      setFallo(e instanceof ErrorApi ? e.message : String(e));
    }
  }

  function elegir(destino: string) {
    setAbierto(false);
    if (conf!.exigen_motivo.includes(destino)) setPidiendoMotivo(destino);
    else void mover(destino, "");
  }

  return (
    <div
      className="relative inline-flex flex-wrap items-center gap-2"
      ref={caja}
    >
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={abierto}
        disabled={destinos.length === 0}
        onClick={() => setAbierto((v) => !v)}
        className="chip-dato"
        title={t("cambioEstado.cambiar")}
      >
        {color ? (
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: color }}
            aria-hidden="true"
          />
        ) : null}
        {nombre(estado)}
        {destinos.length > 0 ? (
          <Icono nombre={abierto ? "expand_less" : "expand_more"} tamano="sm" />
        ) : null}
      </button>
      {abierto ? (
        <ul
          role="listbox"
          aria-label={t("cambioEstado.cambiar")}
          className="absolute left-0 top-full z-popover mt-1 min-w-48 rounded-xl border border-ink-dim/60 bg-paper p-1 shadow-elevation-3"
        >
          {destinos.map((d) => (
            <li key={d} role="option" aria-selected={false}>
              <button
                type="button"
                onClick={() => elegir(d)}
                className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-left text-dato text-ink hover:bg-paper-light"
              >
                {de(d)?.color ? (
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ backgroundColor: de(d)?.color }}
                    aria-hidden="true"
                  />
                ) : null}
                {nombre(d)}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {pidiendoMotivo ? (
        <span className="inline-flex items-center gap-2">
          <input
            className="input-base w-64"
            value={motivo}
            placeholder={t("cambioEstado.motivo", {
              estado: nombre(pidiendoMotivo),
            })}
            aria-label={t("cambioEstado.motivo", {
              estado: nombre(pidiendoMotivo),
            })}
            onChange={(e) => setMotivo(e.target.value)}
          />
          <button
            type="button"
            className="btn-primary"
            disabled={!motivo.trim()}
            onClick={() => void mover(pidiendoMotivo, motivo)}
          >
            {t("cambioEstado.confirmar")}
          </button>
          <button
            type="button"
            className="btn-link"
            onClick={() => setPidiendoMotivo("")}
          >
            {t("cambioEstado.cancelar")}
          </button>
        </span>
      ) : null}
      <span role="status" className="text-rotulo text-danger">
        {fallo}
      </span>
    </div>
  );
}
