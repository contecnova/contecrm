/**
 * Consola de agente: varios canales en una sola cola (CRM-07.04.03.18).
 *
 * El punto de la omnicanalidad no es tener cinco bandejas bonitas: es **una sola
 * cola**. Con una bandeja por canal, lo que pasa es que el correo se mira dos
 * veces al día y el chat todo el rato, y quien escribe por correo espera el
 * doble sin que nadie lo haya decidido.
 *
 * Por eso aquí el canal es una etiqueta, no una pestaña.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { ErrorApi, llamar } from "@/lib/api";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Link } from "react-router-dom";

interface Conversacion {
  conversacion_id: string;
  canal: string;
  asunto: string | null;
  estado: string;
  ultimo_mensaje_at: string | null;
}

interface Caso {
  caso_id: string;
  codigo: string;
  asunto: string;
  prioridad: string;
  estado: string;
  minutos_restantes: number | null;
}

/** Una fila de la cola, ya ordenada por el servidor. */
interface EnCola {
  tipo: "caso" | "conversacion";
  id: string;
  canal: string;
  asunto: string;
  estado: string;
  minutos_restantes: number | null;
  espera_min: number | null;
  vencido: boolean;
}

interface Consola {
  agente: { presencia: string };
  /** La cola única, **ya ordenada**. Ver abajo por qué no se ordena aquí. */
  cola: EnCola[];
  mis_casos: Caso[];
  mis_conversaciones: Conversacion[];
}

export function ConsolaAgente() {
  const { t } = useTranslation();
  const [consola, setConsola] = useState<Consola | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);

  // Una sola llamada y no dos: la propia API lo resuelve así a propósito, porque
  // una consola que abre seis peticiones tarda lo que tarde la más lenta y el
  // agente lo ve como un producto lento aunque cinco vayan rápido.
  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<Consola>("/api/v1/consola-agente", { signal: control.signal })
      .then((r) => setConsola(r.datos))
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!consola) return <Cargando />;

  // El orden lo da el SERVIDOR. Aquí se mezclaban las dos listas y se le daba
  // a todas las conversaciones la misma urgencia —una constante enorme—, así
  // que siempre iban al final y entre ellas quedaban por orden de llegada de
  // la consulta: la que llevaba tres días esperando podía salir detrás de la
  // de hace cinco minutos. Y el comentario de al lado decía lo contrario.
  //
  // Además esto se publica para empotrarse: si cada consola ordenara por su
  // cuenta, dos agentes con dos consolas atenderían en orden distinto.
  const cola = consola.cola ?? [];

  return (
    <div className="flex flex-col gap-4">
      <CabeceraPagina
        titulo={t("consolaAgente.titulo")}
        entradilla={t("consolaAgente.entradilla")}
        icono="headset_mic"
      />

      {cola.length === 0 ? (
        <Vacio titulo={t("consolaAgente.vacia")} detalle={t("consolaAgente.vaciaDetalle")} />
      ) : (
        <ul className="divide-y divide-ink-dim/30 overflow-hidden rounded-lg border border-ink-dim/40">
          {cola.map((c) => (
            <li key={`${c.tipo}:${c.id}`}>
              {/* La fila ENTERA es el enlace: en una consola se entra a
                  trabajar, y obligar a acertarle a un enlace de dos palabras es
                  trabajo de puntería que nadie pidió. Antes no se podía entrar
                  a ninguna parte — una consola de la que no se trabaja es un
                  informe. */}
              <Link
                to={
                  c.tipo === "caso"
                    ? `/m/casos/caso/${c.id}`
                    : `/m/conversaciones/conversacion/${c.id}`
                }
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2 hover:bg-paper-light"
              >
                {/* El canal es una etiqueta y no una pestaña: con una bandeja
                    por canal, el correo se mira dos veces al día y el chat todo
                    el rato, y quien escribe por correo espera el doble. */}
                <span className="badge badge-accent">{c.canal}</span>
                <span className="min-w-0 flex-1 truncate text-2xs text-ink">
                  {c.asunto || t("consolaAgente.sinAsunto")}
                </span>
                <span className="text-3xs text-ink-muted">{c.estado}</span>
                <Espera fila={c} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


/**
 * Lo que corre en esta fila.
 *
 * Son **dos relojes distintos** y se rotulan distinto a propósito: un caso
 * tiene un plazo —minutos para vencer, en negativo si ya venció— y una
 * conversación no tiene plazo, sólo tiempo esperando. Enseñar los dos como «5
 * min» haría creer que significan lo mismo, y uno es un compromiso y el otro
 * una antigüedad.
 */
function Espera({ fila }: { fila: EnCola }) {
  const { t } = useTranslation();
  if (fila.minutos_restantes !== null) {
    return (
      <span className={`font-mono text-3xs ${fila.vencido ? "text-danger" : "text-ink-muted"}`}>
        {t(fila.vencido ? "consolaAgente.vencidoHace" : "consolaAgente.venceEn", {
          minutos: Math.abs(fila.minutos_restantes),
        })}
      </span>
    );
  }
  if (fila.espera_min !== null) {
    return (
      <span className="font-mono text-3xs text-ink-muted">
        {t("consolaAgente.esperando", { minutos: fila.espera_min })}
      </span>
    );
  }
  // Ni plazo ni espera conocida. Se dice, porque un hueco se lee como «no
  // corre», y lo que pasa es que no lo sabemos.
  return <span className="text-3xs text-ink-faint">{t("consolaAgente.sinReloj")}</span>;
}
