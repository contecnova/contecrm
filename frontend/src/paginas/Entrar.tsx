/**
 * Entrada al CRM (CRM-07.04.02.01).
 *
 * Dos caminos, y el de la organización va primero a propósito: en una
 * instalación con SSO, la contraseña local es la excepción, y ponerla arriba
 * invita a usarla cuando existe un proveedor corporativo detrás.
 *
 * El formulario **no valida credenciales**: manda y enseña lo que el servidor
 * conteste. Adivinar aquí si un correo existe sería filtrar quién tiene cuenta.
 */

import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { llamar } from "@/lib/api";
import { config } from "@/lib/config";

export function Entrar({ alEntrar }: { alEntrar: () => void }) {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [contrasena, setContrasena] = useState("");
  // El tenant es obligatorio y no se adivina: la misma persona puede estar en
  // varios y sus permisos son distintos en cada uno. Deducirlo del correo
  // obligaría a preguntar al servidor quién es antes de autenticarla, que es
  // filtrar en qué organizaciones tiene cuenta.
  const [tenant, setTenant] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setFallo(null);
    setEnviando(true);
    try {
      // Por `/sesion/entrar` y no por `/auth/login`: esta devuelve el token en
      // una cookie `HttpOnly` que ningún script puede leer. `/auth/login`
      // devuelve los tokens en el cuerpo, que es lo correcto para una
      // integración y lo peor posible para un navegador.
      await llamar("/api/v1/sesion/entrar", {
        metodo: "POST",
        cuerpo: { email, contrasena, tenant },
      });
      alEntrar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="mx-auto mt-16 w-full max-w-sm">
      <h1 className="text-lg font-medium text-ink">{config().nombre}</h1>
      <p className="mt-1 text-2xs text-ink-faint">{t("entrar.titulo")}</p>

      <a
        href="/api/v1/sso/iniciar"
        className="mt-6 block rounded-xl bg-accent px-4 py-2.5 text-center text-xs text-paper hover:bg-accent-soft"
      >
        {t("entrar.sso")}
      </a>

      <form onSubmit={enviar} className="mt-6 flex flex-col gap-3">
        <label className="text-2xs text-ink-muted">
          {t("entrar.email")}
          <input
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-ink-dim/60 bg-paper px-3 py-2 text-xs text-ink"
          />
        </label>
        <label className="text-2xs text-ink-muted">
          {t("entrar.tenant")}
          <input
            type="text"
            required
            autoComplete="organization"
            value={tenant}
            onChange={(e) => setTenant(e.target.value)}
            className="mt-1 w-full rounded-lg border border-ink-dim/60 bg-paper px-3 py-2 text-xs text-ink"
          />
        </label>
        <label className="text-2xs text-ink-muted">
          {t("entrar.contrasena")}
          <input
            type="password"
            required
            autoComplete="current-password"
            value={contrasena}
            onChange={(e) => setContrasena(e.target.value)}
            className="mt-1 w-full rounded-lg border border-ink-dim/60 bg-paper px-3 py-2 text-xs text-ink"
          />
        </label>
        <button
          type="submit"
          disabled={enviando}
          className="rounded-lg border border-ink-dim/60 px-4 py-2 text-xs text-ink hover:bg-paper-light disabled:opacity-50"
        >
          {t("entrar.enviar")}
        </button>
      </form>

      {fallo ? (
        <div className="mt-4">
          <Fallo error={fallo} />
        </div>
      ) : null}
    </div>
  );
}
