/**
 * Llamar desde la ficha y anotar al colgar (CRM-03.03.01.05, CRM-04.02.01.05).
 *
 * Hasta el 09-11-2026 el marcador era una función que «preparaba» la llamada
 * con lo que tecleaba quien llamaba y no sonaba ningún teléfono. Ahora el botón
 * pide al marcador, que pregunta a party si la persona pidió no ser llamada,
 * aplica la política de grabación del tenant y pide a la centralita conectada
 * que marque. La llamada queda guardada y, al colgar, registrada sola como
 * actividad; aquí sólo se anota lo que sabe la persona: cómo fue y qué se dijo.
 */
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { llamar } from "@/lib/api";

const RESULTADOS = [
  "hablado",
  "buzon",
  "no_contesta",
  "numero_erroneo",
  "persona_equivocada",
  "pide_que_no_le_llamen",
  "reprogramar",
] as const;

interface Llamada {
  id: string;
  estado: string;
  id_externo: string | null;
  error: string | null;
}

interface Preparada {
  se_graba: boolean;
  porque: string;
}

interface Colgada {
  aplicadas: string[];
  pendientes: string[];
  que_falta: string;
}

/** El de la ficha de una cuenta: el teléfono es el de la cuenta. */
export function MarcadorDeCuenta({ cuentaId }: { cuentaId: string }) {
  const [telefono, setTelefono] = useState("");
  useEffect(() => {
    const control = new AbortController();
    llamar<{ telefono?: string | null }>(`/api/v1/accounts/${cuentaId}`, {
      signal: control.signal,
    })
      .then((r) => setTelefono(String(r.datos.telefono ?? "")))
      .catch(() => setTelefono(""));
    return () => control.abort();
  }, [cuentaId]);
  return <Marcador cuentaId={cuentaId} telefonos={[telefono]} compacto />;
}

export function Marcador({
  contactoId,
  cuentaId,
  telefonos,
  compacto = false,
}: {
  contactoId?: string;
  cuentaId?: string;
  telefonos: string[];
  /** Sin tarjeta propia: para ir dentro de otra. */
  compacto?: boolean;
}) {
  const { t } = useTranslation();
  const numeros = telefonos.filter((x) => x && x.trim());
  // Lo elegido, o el primero: en la cuenta el teléfono llega después de montar,
  // y fijarlo sólo al montar dejaba el botón apagado con el número a la vista.
  const [elegido, setNumero] = useState("");
  const [consiente, setConsiente] = useState(false);
  const [llamada, setLlamada] = useState<Llamada | null>(null);
  const [preparada, setPreparada] = useState<Preparada | null>(null);
  const [resultado, setResultado] = useState<string>("hablado");
  const [nota, setNota] = useState("");
  const [proxima, setProxima] = useState("");
  const [colgada, setColgada] = useState<Colgada | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [enviando, setEnviando] = useState(false);

  const numero = numeros.includes(elegido) ? elegido : (numeros[0] ?? "");
  if (numeros.length === 0) return null;

  async function marcar() {
    setFallo(null);
    setColgada(null);
    setEnviando(true);
    try {
      const r = await llamar<{ llamada: Llamada; preparada: Preparada }>(
        "/api/v1/marcador/llamar",
        {
          metodo: "POST",
          cuerpo: {
            numero,
            contacto_id: contactoId ?? null,
            cuenta_id: cuentaId ?? null,
            consiente_grabacion: consiente,
          },
        },
      );
      setLlamada(r.datos.llamada);
      setPreparada(r.datos.preparada);
    } catch (e) {
      setFallo(e);
    } finally {
      setEnviando(false);
    }
  }

  async function anotar(e: FormEvent) {
    e.preventDefault();
    if (!llamada) return;
    setFallo(null);
    setEnviando(true);
    try {
      const r = await llamar<Colgada>("/api/v1/marcador/colgar", {
        metodo: "POST",
        cuerpo: {
          llamada_id: llamada.id,
          resultado,
          nota,
          proxima_fecha: proxima || null,
        },
      });
      setColgada(r.datos);
      setLlamada(null);
      setNota("");
      setProxima("");
    } catch (err) {
      setFallo(err);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className={compacto ? "mb-3" : "card mb-4 p-4"}>
      <h2 className="section-label">{t("marcador.titulo")}</h2>
      {!llamada ? (
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("marcador.numero")}
            <select
              className="input-base"
              value={numero}
              onChange={(e) => setNumero(e.target.value)}
            >
              {numeros.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-dato text-ink">
            <input
              type="checkbox"
              checked={consiente}
              onChange={(e) => setConsiente(e.target.checked)}
            />
            {t("marcador.consiente")}
          </label>
          <button
            type="button"
            className="btn-primary"
            onClick={() => void marcar()}
            disabled={enviando || !numero}
          >
            <Icono nombre="call" />
            {t("marcador.llamar")}
          </button>
        </div>
      ) : (
        <form className="mt-2 grid gap-3 md:grid-cols-2" onSubmit={anotar}>
          <p role="status" className="text-dato text-ink md:col-span-2">
            {llamada.error
              ? t("marcador.noSalio", { error: llamada.error })
              : t("marcador.enCurso", { numero })}
            {preparada ? (
              <span className="block text-rotulo text-ink-muted">
                {preparada.se_graba
                  ? t("marcador.seGraba")
                  : t("marcador.noSeGraba")}
              </span>
            ) : null}
          </p>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("marcador.resultado")}
            <select
              className="input-base"
              value={resultado}
              onChange={(e) => setResultado(e.target.value)}
            >
              {RESULTADOS.map((r) => (
                <option key={r} value={r}>
                  {t(`marcador.resultados.${r}`)}
                </option>
              ))}
            </select>
          </label>
          {resultado === "reprogramar" ? (
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("marcador.proxima")}
              <input
                type="date"
                className="input-base"
                required
                value={proxima}
                onChange={(e) => setProxima(e.target.value)}
              />
            </label>
          ) : null}
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
            {t("marcador.nota")}
            <textarea
              className="input-base"
              rows={2}
              value={nota}
              onChange={(e) => setNota(e.target.value)}
            />
          </label>
          <div className="flex gap-2 md:col-span-2">
            <button type="submit" className="btn-primary" disabled={enviando}>
              {t("marcador.anotar")}
            </button>
          </div>
        </form>
      )}
      {colgada ? (
        <div role="status" className="mt-3 text-rotulo text-ink-muted">
          <p>{t("marcador.anotada")}</p>
          {colgada.que_falta ? <p>{colgada.que_falta}</p> : null}
          {colgada.aplicadas.map((a) => (
            <p key={a} className="text-ink">
              {a}
            </p>
          ))}
          {colgada.pendientes.map((a) => (
            <p key={a} className="text-danger">
              {a}
            </p>
          ))}
        </div>
      ) : null}
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}
