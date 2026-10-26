/**
 * Consola única de gobierno de la suite (CRM-00.01.07.06).
 *
 * Enseña CRM-00.01.07.03 (el alta y la baja de usuario en cascada, y sobre
 * todo las bajas sin aplicar), CRM-00.01.07.07 (la divergencia entre lo que
 * dice cada herramienta y lo que decimos nosotros), CRM-00.01.07.10 (la cola de
 * aprovisionamiento con su cuarentena y su reintento) y CRM-00.01.07.12 (la
 * auditoría transversal).
 *
 * Quien administra contecrm administra también el resto de herramientas de la
 * casa, y hasta ahora eso significaba cuatro pantallas y cuatro sitios donde dar
 * de baja a alguien que se va — que es justo el momento en el que olvidarse de
 * uno tiene consecuencias.
 *
 * Por eso esta pantalla enseña primero **las bajas sin aplicar**, que es lo único
 * que hay que mirar con prisa: una baja que no llegó es un acceso que sigue
 * abierto en otra herramienta, y eso no lo ve nadie hasta una auditoría.
 *
 * Y dos cosas que se pintan a propósito:
 *
 * **Sin herramientas conectadas no se dice «todo bien».** Un verde silencioso
 * haría creer que el cliente está en la suite cuando solo está en el CRM.
 *
 * **Esto no es un panel de control remoto.** Cada herramienta sigue mandando en
 * lo suyo; aquí se ve lo que cada una publica.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";
import { usePuedeOperar } from "@/lib/permisos";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";

interface Herramienta {
  herramienta: string;
  tipo: string;
  activa: boolean;
  estado: string;
  bajas_sin_aplicar: number;
  ultimo_error: string | null;
}

interface Panel {
  herramientas: Herramienta[];
  cuarentena: number;
  bajas_sin_aplicar: number;
  en_verde: boolean;
  sin_herramientas: boolean;
}

export function SuiteGobierno() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Panel | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [recargar, setRecargar] = useState(0);

  useEffect(() => {
    const control = new AbortController();
    llamar<Panel>("/api/v1/suite/panel", { signal: control.signal })
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [recargar]);

  if (fallo) return <Fallo error={fallo} />;
  if (!datos) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("suite.titulo")}
        entradilla={t("suite.intro")}
        icono="sync_alt"
      />

      {datos.sin_herramientas ? (
        /* Un verde silencioso haría creer que el cliente está en la suite
           cuando solo está en el CRM. */
        <Vacio
          titulo={t("suite.sinHerramientas")}
          detalle={t("suite.sinHerramientasPorque")}
        />
      ) : (
        <>
          {/* Lo primero y aparte: una baja sin aplicar es un acceso abierto. */}
          <p
            className={`mt-4 text-xs ${
              datos.bajas_sin_aplicar > 0 ? "text-danger" : "text-success"
            }`}
            role="status"
          >
            {datos.bajas_sin_aplicar > 0
              ? t("suite.bajasSinAplicar", { cuantas: datos.bajas_sin_aplicar })
              : t("suite.sinBajasPendientes")}
          </p>

          <Rejilla
            className="mt-4"
            cabeceras={[
              t("suite.herramienta"),
              t("suite.estado"),
              t("suite.bajas"),
              t("suite.ultimoError"),
            ]}
          >
            {datos.herramientas.map((h) => (
              <tr
                key={h.herramienta}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla className="text-ink">{h.herramienta}</Casilla>
                <Casilla
                  className={`${h.activa ? "text-success" : "text-ink-faint"}`}
                >
                  {h.estado}
                </Casilla>
                <Casilla
                  className={`${
                    h.bajas_sin_aplicar > 0 ? "text-danger" : "text-ink-muted"
                  }`}
                >
                  {h.bajas_sin_aplicar}
                </Casilla>
                <Casilla className="text-3xs text-ink-faint">
                  {h.ultimo_error ?? "—"}
                </Casilla>
              </tr>
            ))}
          </Rejilla>

          {datos.cuarentena > 0 ? (
            <>
              <p className="mt-3 text-2xs text-warning" role="status">
                {t("suite.cuarentena", { cuantas: datos.cuarentena })}
              </p>
              <Cuarentena alReintentar={() => setRecargar((n) => n + 1)} />
            </>
          ) : null}
        </>
      )}

      <p className="mt-6 text-3xs text-ink-faint">
        {t("suite.noEsControlRemoto")}
      </p>
    </>
  );
}

interface Apartado {
  id: string;
  herramienta: string;
  objeto: string;
  objeto_id: string;
  operacion: string;
  intentos: number;
  error: string | null;
  carga: Record<string, unknown>;
  gravedad: string;
}

/**
 * Lo apartado, con qué se mandó y con el botón de volver a intentarlo.
 *
 * Antes esta pantalla decía «hay 3 en cuarentena» y ahí se acababa: no había
 * forma de ver cuáles ni de reintentarlas, aunque las dos rutas existían en el
 * servidor desde el primer día. Un aviso sin salida enseña a quien lo lee a no
 * mirarlo, que es justo lo contrario de para lo que se apartó.
 *
 * Y se enseña **lo que se mandó**: sin eso, quien lo mira tiene que adivinar si
 * el problema es el dato o la herramienta.
 */
function Cuarentena({ alReintentar }: { alReintentar: () => void }) {
  const { t } = useTranslation();
  const puedeOperar = usePuedeOperar();
  const [filas, setFilas] = useState<Apartado[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [enviando, setEnviando] = useState("");

  useEffect(() => {
    const control = new AbortController();
    llamar<Apartado[]>("/api/v1/suite/cuarentena", { signal: control.signal })
      .then((r) => setFilas(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  async function reintentar(id: string) {
    setEnviando(id);
    try {
      await llamar(`/api/v1/suite/cuarentena/${id}/reintentar`, {
        metodo: "POST",
      });
      setFilas((previas) => (previas ?? []).filter((f) => f.id !== id));
      alReintentar();
    } catch (e) {
      setFallo(e);
    } finally {
      setEnviando("");
    }
  }

  if (fallo) return <Fallo error={fallo} />;
  if (!filas) return <Cargando />;

  const puede = puedeOperar("POST", "/api/v1/suite/cuarentena/{id}/reintentar");

  return (
    <Rejilla
      className="mt-2"
      cabeceras={[
        t("suite.herramienta"),
        t("suite.queSeMando"),
        t("suite.intentos"),
        t("suite.ultimoError"),
        "",
      ]}
    >
      {filas.map((f) => (
        <tr key={f.id} className="border-b border-ink-dim/30 last:border-0">
          <Casilla className="text-ink">{f.herramienta}</Casilla>
          <Casilla className="text-3xs text-ink-muted">
            {/* La baja se marca: es la única cuyo retraso deja un acceso
                abierto, y en una lista larga se pierde entre las demás. */}
            {f.gravedad === "alta" ? (
              <span className="text-danger">{t("suite.esUnaBaja")} </span>
            ) : null}
            {f.objeto}: {JSON.stringify(f.carga)}
          </Casilla>
          <Casilla className="text-ink-muted">{f.intentos}</Casilla>
          <Casilla className="text-3xs text-ink-faint">{f.error ?? "—"}</Casilla>
          <Casilla>
            {puede ? (
              <button
                type="button"
                onClick={() => void reintentar(f.id)}
                disabled={enviando === f.id}
                className="rounded border border-ink-dim/60 px-2 py-1 text-3xs text-ink disabled:opacity-50"
              >
                {enviando === f.id
                  ? t("suite.reintentando")
                  : t("suite.reintentar")}
              </button>
            ) : null}
          </Casilla>
        </tr>
      ))}
    </Rejilla>
  );
}
