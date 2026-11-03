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
import { Tabla } from "@/componentes/Tabla";
import { llamar } from "@/lib/api";

export function Comentarios({ tipo, id }: { tipo: string; id: string }) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Record<string, unknown>[] | null>(null);
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  // Lo que se canta al escribir. Sin esto, quien no ve la pantalla manda un
  // comentario y no sabe si ha salido.
  const [dicho, setDicho] = useState("");

  const cargar = useCallback(async () => {
    try {
      const r = await llamar<Record<string, unknown>[]>(
        `/api/v1/comentarios/${tipo}/${id}`,
      );
      setFilas(Array.isArray(r.datos) ? r.datos : []);
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
      <div className="mt-3">
        {filas === null ? (
          <Cargando />
        ) : filas.length === 0 ? (
          <Vacio compacto titulo={t("ficha.sinComentarios")} />
        ) : (
          <Tabla filas={filas} titulo={t("ficha.comentarios")} />
        )}
      </div>
    </>
  );
}
