/**
 * Duplicados: la cola donde se DECIDEN, no donde se miran
 * (CRM-01.01.04.01, CRM-01.01.04.03).
 *
 * El barrido encontraba las parejas y el listado genérico las pintaba. Eso es
 * todo lo que había: dieciocho tarjetas con dos nombres y una probabilidad, y
 * ninguna forma de hacer nada con ellas. Una cola que sólo se mira se mira una
 * vez; a la semana nadie la abre, y mientras tanto el comercial sigue llamando
 * dos veces al mismo cliente.
 *
 * El servidor sabía hacerlo desde el primer día —fusionar eligiendo cuál se
 * queda, recordar que dos fichas **no** son la misma, o dejarlo para luego— y
 * no había botón. Circuito abierto: las dos mitades puestas y nada que las
 * uniera. Esta pantalla es la unión.
 *
 * Las decisiones, y por qué:
 *
 * - **Fusionar pide elegir cuál se queda.** No se elige solo: la que sobrevive
 *   es la que conserva el identificador que usan los sistemas de fuera, y eso
 *   no lo sabe un algoritmo. Y se confirma, porque mezclar el histórico de dos
 *   clientes es difícil de deshacer y el coste de equivocarse no es simétrico.
 * - **«No son la misma» se recuerda.** Si el siguiente barrido volviera a
 *   proponer lo mismo, la cola reaparecería entera y se dejaría de mirar.
 * - **Borrar una no es una opción, y se dice por qué.** Borrar la repetida
 *   tira su histórico —sus casos, sus oportunidades, lo que se habló— y deja
 *   huérfano lo que colgaba de ella. Fusionar hace lo que se quiere: una
 *   desaparece de las listas y lo suyo pasa a la que se queda.
 * - **Y se puede no hacer ninguna de las dos.** Si son dos empresas distintas
 *   que se parecen, lo que hace falta es cambiar algo en una para que dejen de
 *   parecerse; desde aquí se abre cada ficha.
 *
 * Lo que la pantalla enseña de cada pareja es **qué ha coincidido**, no sólo
 * cuánto: con un «87 %» a secas hay que abrir las dos fichas para saber qué se
 * está comparando, y entonces la cola cuesta más que el problema.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { ErrorApi, llamar, salvoCancelacion } from "@/lib/api";
import { listar } from "@/lib/listados";
import { humanizar } from "@/lib/formato";

interface Pareja {
  id: string;
  a_id: string;
  b_id: string;
  a_nombre: string;
  b_nombre: string;
  /** Ya en porcentaje: lo convierte el servidor. */
  probabilidad: number;
  senales: string[];
  concluyente: boolean;
  decision: string;
  decidido_at: string | null;
  nota: string;
}

interface Barrido {
  revisadas: number;
  propuestas: number;
  umbral: number;
}

const COLA = "/api/v1/data-quality/accounts/duplicates/cola";

export function Duplicados() {
  const { t } = useTranslation();
  const [parejas, setParejas] = useState<Pareja[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [soloPendientes, setSoloPendientes] = useState(true);
  const [trabajando, setTrabajando] = useState("");
  const [barrido, setBarrido] = useState<Barrido | null>(null);
  /** Qué ficha se queda en cada pareja. Sin elegir, no se puede fusionar. */
  const [superviviente, setSuperviviente] = useState<Record<string, string>>(
    {},
  );
  /** La pareja que está esperando el «sí, fusiona». */
  const [confirmando, setConfirmando] = useState("");

  const cargar = useCallback(
    (signal?: AbortSignal) => {
      setFallo(null);
      listar<Pareja>(`${COLA}?pendientes=${soloPendientes}&limite=100`, {
        signal,
      })
        .then(setParejas)
        .catch(salvoCancelacion(setFallo));
    },
    [soloPendientes],
  );

  useEffect(() => {
    const control = new AbortController();
    cargar(control.signal);
    return () => control.abort();
  }, [cargar]);

  async function buscar() {
    setTrabajando("barrido");
    try {
      const r = await llamar<Barrido>(
        "/api/v1/data-quality/accounts/duplicates/barrido",
        {
          metodo: "POST",
          cuerpo: {},
        },
      );
      setBarrido(r.datos);
      cargar();
    } catch (e: unknown) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      setTrabajando("");
    }
  }

  async function decidir(pareja: Pareja, decision: string) {
    setTrabajando(pareja.id);
    setConfirmando("");
    try {
      await llamar(`${COLA}/${pareja.id}`, {
        metodo: "POST",
        cuerpo: {
          decision,
          superviviente_id:
            decision === "fusionar" ? superviviente[pareja.id] : null,
          nota: "",
        },
      });
      cargar();
    } catch (e: unknown) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      setTrabajando("");
    }
  }

  if (fallo && !parejas)
    return <Fallo error={fallo} reintentar={() => cargar()} />;
  if (!parejas) return <Cargando />;

  return (
    <div className="flex flex-col gap-4">
      <CabeceraPagina
        titulo={t("duplicados.titulo")}
        entradilla={t("duplicados.entradilla")}
        icono="join_inner"
      />

      {fallo ? <Fallo error={fallo} /> : null}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn-secondary"
          disabled={trabajando !== ""}
          onClick={() => void buscar()}
        >
          <Icono nombre="search" tamano="sm" />
          {trabajando === "barrido"
            ? t("duplicados.buscando")
            : t("duplicados.buscar")}
        </button>
        <label className="flex items-center gap-2 text-2xs text-ink-muted">
          <input
            type="checkbox"
            checked={soloPendientes}
            onChange={(e) => setSoloPendientes(e.target.checked)}
          />
          {t("duplicados.soloPendientes")}
        </label>
        {/* Lo que ha hecho el barrido, en números. «Hecho» a secas no dice si
            ha mirado tres fichas o tres mil. */}
        <span
          role="status"
          aria-live="polite"
          className="text-2xs text-ink-faint"
        >
          {barrido
            ? t("duplicados.resultadoBarrido", {
                revisadas: barrido.revisadas,
                propuestas: barrido.propuestas,
              })
            : ""}
        </span>
      </div>

      {parejas.length === 0 ? (
        <Vacio
          icono="join_inner"
          titulo={t("duplicados.ninguna")}
          detalle={t("duplicados.ningunaDetalle")}
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {parejas.map((p) => (
            <li key={p.id}>
              <ParejaDeFichas
                pareja={p}
                elegida={superviviente[p.id] ?? ""}
                alElegir={(cual) =>
                  setSuperviviente((s) => ({ ...s, [p.id]: cual }))
                }
                ocupada={trabajando === p.id}
                confirmando={confirmando === p.id}
                alConfirmar={() => setConfirmando(p.id)}
                alCancelar={() => setConfirmando("")}
                alDecidir={(d) => void decidir(p, d)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ParejaDeFichas({
  pareja,
  elegida,
  alElegir,
  ocupada,
  confirmando,
  alConfirmar,
  alCancelar,
  alDecidir,
}: {
  pareja: Pareja;
  elegida: string;
  alElegir: (cual: string) => void;
  ocupada: boolean;
  confirmando: boolean;
  alConfirmar: () => void;
  alCancelar: () => void;
  alDecidir: (decision: string) => void;
}) {
  const { t } = useTranslation();
  const decidida = pareja.decision !== "";
  const absorbida = elegida === pareja.a_id ? pareja.b_nombre : pareja.a_nombre;

  return (
    <section className="card flex flex-col gap-3 p-4">
      <header className="flex flex-wrap items-center gap-2">
        <span
          className={
            pareja.concluyente ? "badge badge-danger" : "badge badge-warning"
          }
        >
          {t("duplicados.probabilidad", { pct: pareja.probabilidad })}
        </span>
        {/* En qué se parecen, al lado de cuánto. Sin esto hay que abrir las dos
            fichas para saber qué se está comparando. */}
        {pareja.senales.map((s) => (
          <span key={s} className="chip-dato">
            {humanizar(s)}
          </span>
        ))}
        {decidida ? (
          <span className="badge badge-muted ml-auto">
            {t(`duplicados.decision.${pareja.decision}`, pareja.decision)}
          </span>
        ) : null}
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        <Lado
          id={pareja.a_id}
          nombre={pareja.a_nombre}
          elegida={elegida === pareja.a_id}
          bloqueada={decidida}
          alElegir={() => alElegir(pareja.a_id)}
          nombreGrupo={pareja.id}
        />
        <Lado
          id={pareja.b_id}
          nombre={pareja.b_nombre}
          elegida={elegida === pareja.b_id}
          bloqueada={decidida}
          alElegir={() => alElegir(pareja.b_id)}
          nombreGrupo={pareja.id}
        />
      </div>

      {decidida ? null : confirmando ? (
        /* Lo que va a pasar, con los nombres puestos, antes de hacerlo.
           Mezclar el histórico de dos clientes es difícil de deshacer. */
        <div
          role="alertdialog"
          aria-label={t("duplicados.confirmarTitulo")}
          className="flex flex-col gap-2 rounded-lg border border-danger/40 bg-danger/5 p-3"
        >
          <p className="text-2xs text-ink">
            {t("duplicados.queVaAPasar", {
              absorbida,
              superviviente:
                elegida === pareja.a_id ? pareja.a_nombre : pareja.b_nombre,
            })}
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-danger"
              disabled={ocupada}
              onClick={() => alDecidir("fusionar")}
            >
              {t("duplicados.siFusiona")}
            </button>
            <button type="button" className="btn-ghost" onClick={alCancelar}>
              {t("duplicados.mejorNo")}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={ocupada || elegida === ""}
            onClick={alConfirmar}
          >
            {t("duplicados.fusionar")}
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={ocupada}
            onClick={() => alDecidir("no_es_duplicado")}
          >
            {t("duplicados.noSonLaMisma")}
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={ocupada}
            onClick={() => alDecidir("descartar")}
          >
            {t("duplicados.paraLuego")}
          </button>
          {/* Por qué no hay un «borrar ésta»: borrarla tira su histórico. */}
          <span className="text-3xs text-ink-faint">
            {elegida === ""
              ? t("duplicados.eligeCual")
              : t("duplicados.porQueNoBorrar")}
          </span>
        </div>
      )}
    </section>
  );
}

function Lado({
  id,
  nombre,
  elegida,
  bloqueada,
  alElegir,
  nombreGrupo,
}: {
  id: string;
  nombre: string;
  elegida: boolean;
  bloqueada: boolean;
  alElegir: () => void;
  nombreGrupo: string;
}) {
  const { t } = useTranslation();
  return (
    <div
      className={`flex flex-col gap-1 rounded-lg border p-3 ${
        elegida ? "border-accent/60 bg-accent/5" : "border-ink-dim/40"
      }`}
    >
      <p className="truncate text-sm text-ink">{nombre}</p>
      <div className="flex flex-wrap items-center gap-3 text-3xs">
        <Link
          to={`/m/cuentas/cuenta/${id}`}
          className="text-accent hover:underline"
        >
          {t("duplicados.abrirFicha")}
        </Link>
        {bloqueada ? null : (
          <label className="flex items-center gap-1.5 text-ink-muted">
            <input
              type="radio"
              name={`se-queda-${nombreGrupo}`}
              checked={elegida}
              onChange={alElegir}
            />
            {t("duplicados.seQuedaEsta")}
          </label>
        )}
      </div>
    </div>
  );
}
