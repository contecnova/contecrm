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
import { Icono } from "@/componentes/Icono";
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
    // Centrada de verdad, en una tarjeta. Antes era texto suelto pegado arriba
    // a la izquierda del ancho máximo: la primera pantalla del producto, y la
    // que peor contaba lo que hay detrás.
    <div className="flex min-h-screen items-center justify-center bg-paper-dark px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          {config().logotipo ? (
            <img
              src={config().logotipo}
              alt={config().nombre}
              className="mx-auto mb-3 h-8"
            />
          ) : null}
          <h1 className="text-xl font-semibold text-ink">{config().nombre}</h1>
          <p className="mt-1 text-xs text-ink-muted">{t("entrar.titulo")}</p>
        </div>

        <div className="card p-6">
          <a
            href="/api/v1/sso/iniciar"
            className="btn-primary flex w-full items-center justify-center gap-2"
          >
            <Icono nombre="shield_person" tamano="sm" />
            {t("entrar.sso")}
          </a>

          {/* La separación dice que son dos caminos y no dos pasos. Sin ella, el
              botón de arriba parece el primer paso del formulario de abajo. */}
          <div className="my-5 flex items-center gap-3">
            <span className="h-px flex-1 bg-ink-dim/60" />
            <span className="text-3xs uppercase tracking-wide text-ink-faint">
              {t("entrar.o")}
            </span>
            <span className="h-px flex-1 bg-ink-dim/60" />
          </div>

          <form onSubmit={enviar} className="flex flex-col gap-3">
            <div>
              <label htmlFor="entrar-tenant" className="label-base">
                {t("entrar.tenant")}
              </label>
              <input
                id="entrar-tenant"
                type="text"
                required
                autoComplete="organization"
                value={tenant}
                onChange={(e) => setTenant(e.target.value)}
                className="input-base"
              />
            </div>
            <div>
              <label htmlFor="entrar-email" className="label-base">
                {t("entrar.email")}
              </label>
              <input
                id="entrar-email"
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-base"
              />
            </div>
            <div>
              <label htmlFor="entrar-contrasena" className="label-base">
                {t("entrar.contrasena")}
              </label>
              <input
                id="entrar-contrasena"
                type="password"
                required
                autoComplete="current-password"
                value={contrasena}
                onChange={(e) => setContrasena(e.target.value)}
                className="input-base"
              />
            </div>
            <button type="submit" disabled={enviando} className="btn-secondary mt-1 w-full">
              {enviando ? t("app.cargando") : t("entrar.enviar")}
            </button>
          </form>

          {fallo ? (
            <div className="mt-4">
              <Fallo error={fallo} />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
