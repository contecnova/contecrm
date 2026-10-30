/**
 * Dónde me han mencionado (CRM-06.02.01.01).
 *
 * Mencionar a alguien en un comentario funcionaba: se guardaba, se notificaba
 * y se podía leer **abriendo el registro**. Lo que faltaba era el sitio donde
 * se ven todas, y sin él la función no existe en la práctica: nadie abre
 * cuarenta fichas por si acaso.
 *
 * **Los comentarios los guarda el servicio dueño del registro**, así que las
 * menciones de un servicio suelto son un tercio de las tuyas presentadas como
 * todas. Las junta el gateway, y **dice cuáles no ha podido preguntar**:
 * «no tienes menciones» y «no se ha podido preguntar» se leen igual y
 * significan lo contrario.
 *
 * **Un comentario interno va marcado.** Es el que no ve el cliente, y en una
 * lista mezclada con los demás se responde al que no toca.
 *
 * Y desde cada una se llega al registro: una mención sin el enlace obliga a
 * buscar el caso a mano, que es la mitad del trabajo que esta pantalla ahorra.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { moduloDeObjeto } from "@/lib/modulos";
import { fechaHora } from "@/lib/formato";

interface Mencion {
  id: string;
  objeto_tipo: string;
  objeto_id: string;
  cuerpo: string;
  autor_id: string | null;
  /** El que no ve el cliente: mezclado con los demás se contesta al que no toca. */
  interno: boolean;
  hilo_id?: string | null;
  cuando: string | null;
  servicio: string;
}

interface Respuesta {
  menciones: Mencion[];
  cuantas: number;
  /** Servicios que no contestaron: puede haber menciones que no salen. */
  sin_respuesta: string[];
  aviso: string;
}

export function Menciones() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Respuesta | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Respuesta>("/api/v1/comentarios/mis-menciones?limite=100", {
      signal: control.signal,
    })
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!datos) return <Cargando />;

  const menciones = datos.menciones ?? [];

  return (
    <>
      <CabeceraPagina
        titulo={t("menciones.titulo")}
        icono="alternate_email"
        entradilla={t("menciones.entradilla")}
      />

      {/* Un servicio mudo se dice: sin esto, una lista corta se lee como
          «no me han mencionado» y puede ser «no se ha podido preguntar». */}
      {datos.sin_respuesta.length > 0 ? (
        <p className="card mb-3 border-warning/40 p-3 text-2xs text-warning" role="status">
          {datos.aviso}
        </p>
      ) : null}

      {menciones.length === 0 ? (
        <Vacio
          titulo={t("menciones.ninguna")}
          detalle={
            datos.sin_respuesta.length > 0
              ? t("menciones.ningunaPeroMudos")
              : t("menciones.ningunaDeVerdad")
          }
        />
      ) : (
        <ul className="lista-acotada flex flex-col gap-2 pr-1">
          {menciones.map((m) => {
            const modulo = moduloDeObjeto(m.objeto_tipo);
            return (
              <li key={m.id} className="card p-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="chip-dato">{m.objeto_tipo}</span>
                  {m.interno ? (
                    <span className="badge badge-aviso">{t("menciones.interno")}</span>
                  ) : null}
                  <span className="flex-1" />
                  <span className="font-mono text-3xs text-ink-faint">
                    {fechaHora(m.cuando)}
                  </span>
                </div>
                <p className="mt-1 text-2xs text-ink">{m.cuerpo}</p>
                {/* El enlace al registro: sin él hay que buscarlo a mano, que
                    es la mitad del trabajo que esto ahorra. */}
                {modulo !== "" ? (
                  <Link
                    className="btn-link mt-1 inline-block text-3xs"
                    to={`/m/${modulo}/${m.objeto_tipo}/${m.objeto_id}`}
                  >
                    {t("menciones.abrir")}
                  </Link>
                ) : (
                  <span className="mt-1 inline-block font-mono text-3xs text-ink-faint">
                    {m.objeto_id}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
