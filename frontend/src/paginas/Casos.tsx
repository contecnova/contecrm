/**
 * Casos: la bandeja de quien atiende, con el reloj del SLA (CRM-07.04.03.17).
 *
 * **Lo que va a incumplir se separa de lo que ya incumplió.** Son dos trabajos
 * distintos: lo primero se puede salvar y lo segundo hay que explicarlo. Una
 * bandeja que los mezcla hace que se atienda por orden de llegada, que es el
 * único orden que garantiza incumplir los dos.
 *
 * **El reparto lo hace el servidor.** Antes se hacía aquí, y traía tres cosas
 * mal a la vez: el corte entre «en riesgo» y el resto eran cuatro horas
 * escritas en una expresión —iguales para todos los clientes del despliegue—;
 * los totales se contaban sobre la página traída, así que decía «3
 * incumplidos» habiendo cincuenta; y leía campos que la API no devuelve
 * —`vence_at`, `numero`, `escalado`—, con lo que **todos los casos caían en
 * «el resto»** y el reloj decía siempre «sin SLA».
 *
 * **El reloj se pinta aquí y el vencimiento lo da el servidor.** La pantalla
 * cuenta; no decide cuándo vence. Si lo decidiera, dos navegadores con la hora
 * mal darían dos incumplimientos distintos del mismo caso.
 *
 * **Y desde aquí se abre el caso.** Una bandeja de la que no se puede entrar a
 * trabajar es un informe.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { ErrorApi, llamar, salvoCancelacion } from "@/lib/api";

interface Caso {
  id: string;
  codigo: string | null;
  asunto: string;
  estado: string;
  prioridad: string;
  severidad: string;
  cuenta_id: string | null;
  equipo: string | null;
  vence_resolucion_at: string | null;
  incumplio_resolucion: boolean;
}

interface Monton {
  total: number;
  casos: Caso[];
}

interface Bandeja {
  riesgo_horas: number;
  ahora: string;
  incumplidos: Monton;
  en_riesgo: Monton;
  resto: Monton;
}

export function Casos() {
  const { t } = useTranslation();
  const [bandeja, setBandeja] = useState<Bandeja | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Bandeja>("/api/v1/casos/bandeja", { signal: control.signal })
      .then((r) => setBandeja(r.datos))
      .catch(salvoCancelacion((e) => setFallo(e as ErrorApi)));
    return () => control.abort();
  }, []);

  if (fallo) return <Fallo error={fallo} />;
  if (!bandeja) return <Cargando />;

  const vacia =
    bandeja.incumplidos.total + bandeja.en_riesgo.total + bandeja.resto.total === 0;

  return (
    <div className="flex flex-col gap-5">
      <CabeceraPagina
        titulo={t("casos.titulo")}
        // Se dice con qué antelación avisa, porque si no, ver un caso en «en
        // riesgo» y otro parecido fuera no tiene explicación posible.
        entradilla={t("casos.entradillaConUmbral", { horas: bandeja.riesgo_horas })}
        icono="confirmation_number"
      />

      {vacia ? (
        <Vacio titulo={t("casos.ninguno")} detalle={t("casos.ningunoDetalle")} />
      ) : (
        <>
          <Monton
            titulo={t("casos.incumplidos")}
            monton={bandeja.incumplidos}
            tono="danger"
            vacio={t("casos.ningunoIncumplido")}
          />
          <Monton
            titulo={t("casos.enRiesgo")}
            monton={bandeja.en_riesgo}
            tono="warning"
            vacio={t("casos.ningunoEnRiesgo")}
          />
          <Monton titulo={t("casos.resto")} monton={bandeja.resto} tono="normal" vacio="" />
        </>
      )}
    </div>
  );
}

function Monton({
  titulo,
  monton,
  tono,
  vacio,
}: {
  titulo: string;
  monton: Monton;
  tono: "danger" | "warning" | "normal";
  vacio: string;
}) {
  const { t } = useTranslation();
  const color =
    tono === "danger" ? "text-danger" : tono === "warning" ? "text-warning" : "text-ink";
  const escondidos = monton.total - monton.casos.length;

  return (
    <section>
      <h2 className={`text-sm font-medium ${color}`}>
        {titulo}{" "}
        {/* El total es el de TODO, no el de lo que cabe en pantalla. */}
        <span className="text-ink-faint">({monton.total})</span>
      </h2>

      {monton.total === 0 ? (
        vacio ? (
          <p className="mt-1 text-3xs text-ink-faint">{vacio}</p>
        ) : null
      ) : (
        <>
          <ul className="mt-2 divide-y divide-ink-dim/30 overflow-hidden rounded-lg border border-ink-dim/40">
            {monton.casos.map((c) => (
              <li key={c.id}>
                {/* La fila ENTERA es el enlace: en una bandeja se entra a
                    trabajar, y obligar a acertarle a un enlace de dos palabras
                    es trabajo de puntería que nadie pidió. */}
                <Link
                  to={`/m/casos/caso/${c.id}`}
                  className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2 hover:bg-paper-light"
                >
                  <span className="font-mono text-3xs text-ink-faint">{c.codigo || "—"}</span>
                  <span className="min-w-0 flex-1 truncate text-2xs text-ink">{c.asunto}</span>
                  <span className="text-3xs text-ink-muted">{c.estado}</span>
                  {c.prioridad === "alta" || c.prioridad === "urgente" ? (
                    <span className="badge badge-warning">{c.prioridad}</span>
                  ) : null}
                  <Reloj vence={c.vence_resolucion_at} incumplio={c.incumplio_resolucion} />
                </Link>
              </li>
            ))}
          </ul>
          {escondidos > 0 ? (
            // Decir cuántos quedan fuera, y no dejar que la lista parezca
            // completa: es la diferencia entre recortar y mentir.
            <p className="mt-1 text-3xs text-ink-faint">
              {t("casos.yMas", { count: escondidos })}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

/**
 * El reloj del SLA.
 *
 * Cuenta desde el vencimiento que da el servidor. **No lo calcula**: si lo
 * calculara, dos navegadores con la hora mal darían dos incumplimientos
 * distintos del mismo caso.
 */
function Reloj({ vence, incumplio }: { vence: string | null; incumplio: boolean }) {
  const { t } = useTranslation();
  const [ahora, setAhora] = useState(() => Date.now());

  useEffect(() => {
    const reloj = window.setInterval(() => setAhora(Date.now()), 30_000);
    return () => window.clearInterval(reloj);
  }, []);

  // Marcado por el motor de SLA: ya incumplió, aunque su fecha se haya movido
  // después. Enseñar «vence en 48 h» sobre un caso incumplido sería negar el
  // incumplimiento.
  if (incumplio) {
    return <span className="font-mono text-3xs text-danger">{t("casos.incumplido")}</span>;
  }
  if (!vence) return <span className="text-3xs text-ink-faint">{t("casos.sinSla")}</span>;

  const restan = Date.parse(vence) - ahora;
  const horas = Math.floor(Math.abs(restan) / 3600_000);
  const minutos = Math.floor((Math.abs(restan) % 3600_000) / 60_000);
  const texto = `${horas}h ${minutos}m`;
  return (
    <span className={`font-mono text-3xs ${restan < 0 ? "text-danger" : "text-ink-muted"}`}>
      {restan < 0 ? t("casos.vencidoHace", { tiempo: texto }) : t("casos.vence", { tiempo: texto })}
    </span>
  );
}
