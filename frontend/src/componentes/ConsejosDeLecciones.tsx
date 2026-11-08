/**
 * Lo que dicen las lecciones aprendidas de una oportunidad abierta
 * (CRM-03.01.01.16, CRM-03.01.01.17).
 *
 * Los avisos que salieron en sus momentos clave, las lecciones del mismo
 * cliente y las parecidas por significado de cualquier otro, y —si se pide—
 * el «haz esto / no hagas esto» de la IA, cada consejo con la lección de la
 * que sale. Con la forma de los demás paneles de la ficha.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { ErrorApi, llamar, salvoCancelacion } from "@/lib/api";
import { cn } from "@/lib/utiles";

interface LeccionCitada {
  id: string;
  titulo: string;
  resultado: string;
  que_hariamos_distinto: string;
  por_que: string;
  parecido: number | null;
}

interface Aviso {
  id: string;
  momento: string;
  titulo: string;
  detalle: string;
}

interface Consejos {
  mismo_cliente: LeccionCitada[];
  parecidas: LeccionCitada[];
  busqueda_por_significado: { usada: boolean; porque?: string };
  avisos: Aviso[];
}

interface ConsejoIA {
  tipo: "haz" | "no_hagas";
  texto: string;
  leccion_id: string;
  leccion: { titulo: string };
}

function Leccion({ l }: { l: LeccionCitada }) {
  const { t } = useTranslation();
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 py-1.5 text-dato">
      <span
        className={cn(
          "chip-dato",
          l.resultado === "perdida" ? "chip-dato--mal" : "chip-dato--si",
        )}
      >
        {t(`leccion.resultado.${l.resultado}`)}
      </span>
      <Link
        to={`/m/lecciones/leccion/${l.id}`}
        className="font-medium text-accent hover:underline"
      >
        {l.titulo}
      </Link>
      {l.parecido != null ? (
        <span className="text-rotulo text-ink-faint">
          {t("consejos.parecido", { n: Math.round(l.parecido * 100) })}
        </span>
      ) : null}
      {l.que_hariamos_distinto ? (
        <span className="w-full text-ink-muted">{l.que_hariamos_distinto}</span>
      ) : null}
    </li>
  );
}

export function ConsejosDeLecciones({ id }: { id: string }) {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Consejos | null>(null);
  const [ia, setIa] = useState<{
    consejos: ConsejoIA[];
    descartados: number;
    porque?: string;
  } | null>(null);
  const [pidiendo, setPidiendo] = useState(false);
  const [fallo, setFallo] = useState<string>("");

  useEffect(() => {
    const control = new AbortController();
    llamar<Consejos>(`/api/v1/opportunities/${id}/consejos`, {
      signal: control.signal,
    })
      // Lo que no venga cuenta como vacío: un panel de la ficha no puede
      // tumbar la ficha entera por una respuesta a medias.
      .then((r) =>
        setDatos({
          mismo_cliente: r.datos?.mismo_cliente ?? [],
          parecidas: r.datos?.parecidas ?? [],
          avisos: r.datos?.avisos ?? [],
          busqueda_por_significado: r.datos?.busqueda_por_significado ?? {
            usada: true,
          },
        }),
      )
      .catch(salvoCancelacion(() => setDatos(null)));
    return () => control.abort();
  }, [id]);

  async function pedirIA() {
    setPidiendo(true);
    setFallo("");
    try {
      const r = await llamar<NonNullable<typeof ia>>(
        `/api/v1/opportunities/${id}/consejos/ia`,
        { metodo: "POST" },
      );
      setIa({
        consejos: r.datos?.consejos ?? [],
        descartados: r.datos?.descartados ?? 0,
        porque: r.datos?.porque,
      });
    } catch (e) {
      setFallo(e instanceof ErrorApi ? e.message : String(e));
    } finally {
      setPidiendo(false);
    }
  }

  if (!datos) return null;
  const hay =
    datos.avisos.length + datos.mismo_cliente.length + datos.parecidas.length >
    0;

  return (
    <section className="card mb-4 p-4" aria-label={t("consejos.titulo")}>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="section-label">{t("consejos.titulo")}</h2>
        {hay ? (
          <button
            type="button"
            className="btn-secondary"
            disabled={pidiendo}
            onClick={() => void pedirIA()}
          >
            <Icono nombre="auto_awesome" tamano="sm" />
            {pidiendo ? t("consejos.pidiendo") : t("consejos.conIA")}
          </button>
        ) : null}
      </div>

      {!hay ? (
        <p className="text-dato text-ink-muted">{t("consejos.ninguna")}</p>
      ) : null}

      {datos.avisos.length > 0 ? (
        <ul className="divide-y divide-ink-dim/30">
          {datos.avisos.map((a) => (
            <li key={a.id} className="py-1.5 text-dato">
              <span className="chip-dato chip-dato--aviso">
                {t(`consejos.momento.${a.momento}`)}
              </span>{" "}
              <span className="font-medium text-ink">{a.titulo}</span>
              <p className="whitespace-pre-line text-ink-muted">{a.detalle}</p>
            </li>
          ))}
        </ul>
      ) : null}

      {/* Se anuncia: el resultado aparece al pulsar, y quien no ve la
          pantalla tiene que enterarse. */}
      <div role="status">
        {fallo ? <p className="mt-2 text-rotulo text-danger">{fallo}</p> : null}
        {ia ? (
          <div className="mt-2 border-t border-ink-dim/30 pt-2">
            {ia.consejos.length === 0 ? (
              <p className="text-dato text-ink-muted">
                {ia.porque ?? t("consejos.iaSinNada")}
              </p>
            ) : (
              <ul className="divide-y divide-ink-dim/30">
                {ia.consejos.map((c, i) => (
                  <li
                    key={i}
                    className="flex flex-wrap items-baseline gap-x-3 py-1.5 text-dato"
                  >
                    <span
                      className={cn(
                        "chip-dato",
                        c.tipo === "haz" ? "chip-dato--si" : "chip-dato--mal",
                      )}
                    >
                      {t(`consejos.tipo.${c.tipo}`)}
                    </span>
                    <span className="text-ink">{c.texto}</span>
                    <Link
                      to={`/m/lecciones/leccion/${c.leccion_id}`}
                      className="text-rotulo text-accent hover:underline"
                    >
                      {t("consejos.deLaLeccion", { titulo: c.leccion.titulo })}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            {ia.descartados > 0 ? (
              <p className="mt-1 text-rotulo text-ink-faint">
                {t("consejos.descartados", { n: ia.descartados })}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      {datos.mismo_cliente.length > 0 ? (
        <>
          <h3 className="mt-3 text-rotulo font-medium text-ink-muted">
            {t("consejos.mismoCliente")}
          </h3>
          <ul className="divide-y divide-ink-dim/30">
            {datos.mismo_cliente.map((l) => (
              <Leccion key={l.id} l={l} />
            ))}
          </ul>
        </>
      ) : null}

      {datos.parecidas.length > 0 ? (
        <>
          <h3 className="mt-3 text-rotulo font-medium text-ink-muted">
            {t("consejos.parecidas")}
          </h3>
          <ul className="divide-y divide-ink-dim/30">
            {datos.parecidas.map((l) => (
              <Leccion key={l.id} l={l} />
            ))}
          </ul>
        </>
      ) : null}

      {!datos.busqueda_por_significado.usada ? (
        <p className="mt-2 text-rotulo text-ink-faint">
          {t("consejos.sinBusqueda", {
            porque: datos.busqueda_por_significado.porque ?? "",
          })}
        </p>
      ) : null}
    </section>
  );
}
