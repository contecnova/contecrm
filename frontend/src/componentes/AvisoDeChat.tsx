/**
 * El acceso al chat desde la barra, con lo que tienes sin leer (CRM-06.02.02.02).
 *
 * Un chat al que solo se llega entrando en su pantalla es un chat que nadie
 * mira: quien escribe no sabe si le van a leer hoy o el jueves, y acaba
 * mandando un correo «por si acaso». El aviso es lo que lo convierte en un
 * canal de trabajo — es lo que hace cualquier sistema con mensajería y lo que
 * en contecflow ya funciona así.
 *
 * El número se pide a un extremo propio y no al listado de conversaciones:
 * pintar un contador no puede costar traerse los nombres de todos los canales
 * privados en los que está la persona.
 *
 * Y se refresca por reloj, no por SSE. La entrega en vivo de la pantalla de
 * chat sí va por SSE, pero mantener una conexión abierta desde **todas** las
 * pantallas, toda la jornada y por cada pestaña, es un coste que no compensa
 * para un número que puede tardar medio minuto en subir.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { llamar } from "@/lib/api";

/** Cada cuánto se vuelve a preguntar. */
const SEGUNDOS = 30;

export function AvisoDeChat() {
  const { t } = useTranslation();
  const [sinLeer, setSinLeer] = useState(0);

  useEffect(() => {
    let vivo = true;
    const preguntar = () => {
      void llamar<{ mensajes: number }>("/api/v1/chat/sin-leer")
        .then((r) => {
          if (vivo) setSinLeer(r.datos?.mensajes ?? 0);
        })
        // En silencio: un fallo al contar mensajes no puede llenar de errores
        // una barra que está en todas las pantallas.
        .catch(() => undefined);
    };
    preguntar();
    const reloj = window.setInterval(preguntar, SEGUNDOS * 1000);
    return () => {
      vivo = false;
      window.clearInterval(reloj);
    };
  }, []);

  // El número entero hasta 9 y «9+» a partir de ahí: un «137» no cabe en la
  // pastilla y, para decidir si mirar, «muchos» y «137» dicen lo mismo.
  const rotulo = sinLeer > 9 ? "9+" : String(sinLeer);

  return (
    <Link
      to="/chat"
      className="btn-icon relative text-ink-muted hover:bg-paper-light hover:text-ink"
      aria-label={sinLeer > 0 ? t("chat.sinLeerAviso", { count: sinLeer }) : t("nav.chat")}
      title={sinLeer > 0 ? t("chat.sinLeerAviso", { count: sinLeer }) : t("nav.chat")}
    >
      <Icono nombre="forum" />
      {sinLeer > 0 ? (
        <span
          // `aria-hidden` porque lo que dice ya está en la etiqueta del enlace:
          // sin esto, un lector de pantalla leería el número dos veces y la
          // segunda sin decir de qué.
          aria-hidden
          className="absolute -right-0.5 -top-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-3xs font-bold text-white dark:text-paper-sunk"
        >
          {rotulo}
        </span>
      ) : null}
    </Link>
  );
}
