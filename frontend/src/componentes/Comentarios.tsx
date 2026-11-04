/**
 * La conversación de un registro (CRM-06.02.01.01).
 *
 * **Estaba encerrada dentro de la ficha genérica.** El producto tiene quince
 * pantallas de registro: una genérica y catorce propias —caso, cuenta,
 * oportunidad, presupuesto, orden de trabajo…—. La conversación vivía como
 * una función privada de la genérica, así que en las catorce **no había
 * dónde escribir**: un agente abría un caso y no podía dejar una nota ni
 * contestar, con la API publicada, funcionando y alimentando las menciones.
 * Medido el 03-11-2026 abriendo un caso y buscando dónde escribir: cero cajas
 * de texto y un menú «Más» con una sola opción, «Eliminar».
 *
 * **Y donde sí existía, no llegaba.** Mandaba `{texto}` y la ruta espera
 * `{cuerpo}`: escribir un comentario contestaba **422**. Comprobado contra la
 * instalación servida.
 *
 * Vive aquí y se engancha a la barra de pestañas —la pieza que las quince
 * comparten— para que lo lleven todas y la que venga mañana. Ponerlo a mano
 * en cada una son catorce ocasiones de olvidarlo, y la que se olvidara no la
 * notaría nadie: una ficha sin conversación se ve igual que una ficha.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { usePersonas } from "@/lib/personas";

/** Lo que devuelve `/api/v1/comentarios/{tipo}/{id}`: hilos con sus mensajes. */
interface Hilo {
  hilo_id: string;
  resuelto: boolean;
  mensajes: {
    id: string;
    cuerpo: string;
    autor_id: string | null;
    interno: boolean;
    editado: boolean;
    borrado: boolean;
    cuando: string | null;
  }[];
}

export function Comentarios({ tipo, id }: { tipo: string; id: string }) {
  const { t } = useTranslation();
  const [hilos, setHilos] = useState<Hilo[] | null>(null);
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  // Lo que se canta al escribir. Sin esto, quien no ve la pantalla manda un
  // comentario y no sabe si ha salido.
  const [dicho, setDicho] = useState("");
  // Quién escribió cada uno. Sin esto la conversación son textos sueltos: lo
  // primero que se mira de un comentario es de quién es.
  const personas = usePersonas();
  const quien = (autor: string | null) =>
    (autor && personas[autor]?.nombre) || t("ficha.alguien");

  const cargar = useCallback(async () => {
    try {
      const r = await llamar<Hilo[]>(`/api/v1/comentarios/${tipo}/${id}`);
      setHilos(Array.isArray(r.datos) ? r.datos : []);
    } catch (error) {
      setFallo(error);
    }
  }, [tipo, id]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function enviar() {
    if (!texto.trim() || enviando) return;
    setEnviando(true);
    setFallo(null);
    try {
      // **`cuerpo`, que es como se llama el campo en la ruta.** Mandaba
      // `texto` y la respuesta era un 422: la caja existía, se escribía, se
      // pulsaba enviar y no pasaba nada.
      await llamar(`/api/v1/comentarios/${tipo}/${id}`, {
        metodo: "POST",
        cuerpo: { cuerpo: texto.trim(), interno: true },
      });
      setTexto("");
      setDicho(t("ficha.comentarioEnviado"));
      await cargar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <>
      <div className="flex gap-2">
        <label className="sr-only" htmlFor="comentario">
          {t("ficha.escribir")}
        </label>
        <input
          id="comentario"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          // Enviar con Intro: escribir una nota y tener que llevar la mano al
          // ratón es lo que hace que no se escriban.
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void enviar();
            }
          }}
          placeholder={t("ficha.escribir")}
          className="input-base flex-1"
        />
        <button
          type="button"
          onClick={() => void enviar()}
          disabled={enviando || !texto.trim()}
          className="btn-primary"
        >
          {t("ficha.enviar")}
        </button>
      </div>
      <p className="sr-only" role="status">
        {dicho}
      </p>
      {fallo ? (
        <div className="mt-3">
          <Fallo error={fallo} />
        </div>
      ) : null}
      {/* **Una conversación no es una tabla.** Se pintaba con el armazón de
          listados, que es el correcto para registros y el equivocado para
          esto: lo que devuelve la ruta son hilos con mensajes dentro, y en
          una rejilla salían `hilo_id`, `resuelto` y una columna «mensajes»
          que no se puede leer. Aquí se lee quién, cuándo y qué dijo, que es
          de lo que va. Y de paso deja de arrastrar la tabla al paquete de
          apertura, que es lo que pasó del presupuesto. */}
      <div className="mt-3">
        {hilos === null ? (
          <Cargando />
        ) : hilos.length === 0 ? (
          <Vacio compacto titulo={t("ficha.sinComentarios")} />
        ) : (
          <ol className="flex flex-col gap-2">
            {hilos.flatMap((h) =>
              h.mensajes
                .filter((m) => !m.borrado)
                .map((m) => (
                  <li key={m.id} className="card p-3">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="text-dato font-medium text-ink">
                        {quien(m.autor_id)}
                      </span>
                      {/* Un comentario interno va marcado: mezclado con los
                          demás se contesta al que no toca. */}
                      {m.interno ? (
                        <span className="badge badge-aviso">{t("ficha.interno")}</span>
                      ) : null}
                      {m.editado ? (
                        <span className="text-rotulo text-ink-faint">
                          {t("ficha.editado")}
                        </span>
                      ) : null}
                      <span className="flex-1" />
                      <span className="text-rotulo text-ink-faint">
                        {fechaHora(m.cuando)}
                      </span>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-dato text-ink">
                      {m.cuerpo}
                    </p>
                  </li>
                )),
            )}
          </ol>
        )}
      </div>
    </>
  );
}
