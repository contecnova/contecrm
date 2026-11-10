/**
 * Lo que esta persona quiere recibir, y a qué hora abre.
 *
 * Dos respuestas que el servidor daba y ninguna pantalla pedía, y las dos se
 * preguntan delante del contacto: antes de meterlo en una campaña o de
 * escribirle a mano.
 *
 * **El centro de preferencias** se lee por su correo, que es como lo guarda
 * marketing: lo que eligió la persona y, en las que no tocó, lo que vale por
 * defecto, dicho como tal. Las obligatorias salen **como obligatorias y no
 * como una casilla apagada**: una casilla que no se puede desmarcar se lee
 * como un engaño. Se cambia aquí mismo cuando la persona lo pide por teléfono,
 * y el cambio queda con su origen.
 *
 * **La mejor hora** con pocos datos no recomienda nada, y se dice: con tres
 * aperturas, la hora que saldría es la de esos tres correos y no un hábito.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { llamar, salvoCancelacion } from "@/lib/api";
import { usePuedeOperar } from "@/lib/permisos";

interface Categoria {
  clave: string;
  nombre: string;
  descripcion?: string | null;
  obligatoria: boolean;
  acepta: boolean;
  elegida_por_la_persona: boolean;
}

interface MejorHora {
  hora: number | null;
  zona?: string;
  muestras: number;
  concluyente: boolean;
  aviso?: string;
}

export function CorreoDelContacto({
  contactoId,
  email,
}: {
  contactoId: string;
  email: string;
}) {
  const { t } = useTranslation();
  const puedeOperar = usePuedeOperar();
  const [categorias, setCategorias] = useState<Categoria[] | null>(null);
  const [hora, setHora] = useState<MejorHora | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [guardando, setGuardando] = useState("");
  const [recargar, setRecargar] = useState(0);
  const puedeCambiar = puedeOperar("PUT", "/api/v1/preferencias");

  useEffect(() => {
    const control = new AbortController();
    llamar<MejorHora>(
      `/api/v1/canales-marketing/mejor-hora?objeto_id=${encodeURIComponent(contactoId)}`,
      { signal: control.signal },
    )
      .then((r) => setHora(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [contactoId]);

  useEffect(() => {
    if (!email) return;
    const control = new AbortController();
    llamar<{ categorias: Categoria[] }>(
      `/api/v1/preferencias?email=${encodeURIComponent(email)}`,
      { signal: control.signal },
    )
      .then((r) => setCategorias(r.datos.categorias ?? []))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [email, recargar]);

  const cambiar = useCallback(
    async (categoria: Categoria, acepta: boolean) => {
      setGuardando(categoria.clave);
      setFallo(null);
      try {
        await llamar("/api/v1/preferencias", {
          metodo: "PUT",
          // `origen` dice que lo cambió alguien de dentro en nombre de la
          // persona, no ella desde su centro de preferencias.
          cuerpo: {
            email,
            elecciones: { [categoria.clave]: acepta },
            origen: "ficha",
          },
        });
        setRecargar((n) => n + 1);
      } catch (e) {
        setFallo(e);
      } finally {
        setGuardando("");
      }
    },
    [email],
  );

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("correoContacto.titulo")}</h2>
      {fallo ? <Fallo error={fallo} /> : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-1 text-titulin font-medium text-ink">
            {t("correoContacto.preferencias")}
          </h3>
          {!email ? (
            <p className="text-dato text-ink-faint">
              {t("correoContacto.sinEmail")}
            </p>
          ) : categorias !== null && categorias.length === 0 ? (
            <p className="text-dato text-ink-faint">
              {t("correoContacto.sinCategorias")}
            </p>
          ) : (
            <ul className="flex flex-col gap-1">
              {(categorias ?? []).map((c) => (
                <li key={c.clave} className="text-dato">
                  {c.obligatoria ? (
                    <span className="text-ink">
                      {c.nombre}{" "}
                      <span className="chip-dato">
                        {t("correoContacto.obligatoria")}
                      </span>
                    </span>
                  ) : (
                    <label className="flex items-baseline gap-2 text-ink">
                      <input
                        type="checkbox"
                        checked={c.acepta}
                        disabled={!puedeCambiar || guardando === c.clave}
                        onChange={(e) => void cambiar(c, e.target.checked)}
                      />
                      <span>{c.nombre}</span>
                      <span className="text-rotulo text-ink-faint">
                        {c.elegida_por_la_persona
                          ? t("correoContacto.elegida")
                          : t("correoContacto.porDefecto")}
                      </span>
                    </label>
                  )}
                  {c.descripcion ? (
                    <span className="block text-rotulo text-ink-muted">
                      {c.descripcion}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="mb-1 text-titulin font-medium text-ink">
            {t("correoContacto.mejorHora")}
          </h3>
          {hora ? (
            hora.concluyente && hora.hora !== null ? (
              <p className="text-dato text-ink">
                {t("correoContacto.abreA", {
                  hora: String(hora.hora).padStart(2, "0"),
                  zona: hora.zona ?? "",
                  muestras: hora.muestras,
                })}
              </p>
            ) : (
              <p className="text-dato text-ink-faint">
                {hora.aviso ||
                  t("correoContacto.sinHora", { muestras: hora.muestras })}
              </p>
            )
          ) : null}
        </div>
      </div>
    </section>
  );
}
