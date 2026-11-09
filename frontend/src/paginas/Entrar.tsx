/**
 * Entrada al CRM (CRM-07.04.02.01, CRM-00.05.01.23, CRM-00.05.01.26).
 *
 * **El diseño es el de contecflow, carácter por carácter**: sus colores, su
 * tarjeta de 400 px con radio 20, sus campos de 44 px de alto y su separación
 * con «o».
 *
 * La tipografía ya NO es la suya. Al adoptar el sistema de diseño de
 * contecmind (29-09-2026) dejó de cargarse DM Sans, y una fuente que se nombra
 * y no está no es «idéntica»: es la del sistema. Queda pendiente decidir si
 * esta pantalla entera pasa también a contecmind — hoy el CRM se ve como
 * contecmind y su puerta como contecflow.
 *
 * Los valores van escritos y no leídos de los tokens, y ahora YA NO coinciden
 * —el sistema de diseño pasó a ser el de contecmind—: esta pantalla se
 * ve ANTES de entrar, cuando todavía no hay tema elegido, así que tiene que ser
 * oscura siempre. Leyendo los tokens saldría clara para quien tenga el tema
 * claro guardado, y contecflow no tiene pantalla de entrada clara.
 *
 * Cuatro caminos, y el orden no es casual: el proveedor de la organización va
 * primero porque en una instalación con SSO la contraseña local es la
 * excepción; la passkey va bajo el formulario porque quien la tiene la usa
 * siempre; y «no la recuerdo» vive **dentro** de la pantalla en vez de en otra,
 * porque quien no puede entrar no debería tener que navegar.
 *
 * El formulario **no valida credenciales**: manda y enseña lo que el servidor
 * conteste. Adivinar aquí si un correo existe sería filtrar quién tiene cuenta.
 */

import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ErrorApi, llamar } from "@/lib/api";
import { config } from "@/lib/config";
import { cn } from "@/lib/utiles";
import { admitePasskeys, firmarConPasskey } from "@/lib/webauthn";

// ── La puerta, con el sistema de diseño de la casa ───────────────────────
//
// Hasta el 02-11-2026 esta pantalla se pintaba con **12 colores propios, 18
// bloques de estilo en línea, 13 tamaños de letra y tres radios** —10, 12 y
// 20—, copiados a mano de contecflow. Su propio comentario lo decía: «hoy el
// CRM se ve como contecmind y su puerta como contecflow», y dejaba la decisión
// pendiente. Ahora el CRM se ve como Salesforce Lightning, así que la puerta
// se parecía todavía menos: radio 20 contra 4, otro azul, otra escala.
//
// Y era la primera pantalla que ve cualquiera.
//
// Ahora usa los tokens y las clases de la casa. Con eso gana tres cosas que
// no tenía: **respeta el tema** —claro u oscuro, el que cada quien tenga
// guardado, en vez de ser oscura siempre—, **entra en el gate de contraste**,
// que comprueba los tokens de texto en los dos temas, y **entra en la escala
// tipográfica**, que es lo que la tenía escribiendo rótulos a 11 px.
//
// Las claves son las mismas de antes para que el JSX no cambie: lo que
// cambia es que son clases y no una tabla de estilos.
const cl = {
  pagina:
    "relative flex min-h-screen flex-col items-center justify-center bg-paper-dark px-4 py-6",
  tarjeta: "card w-full max-w-[400px] px-8 py-9",
  logo: "mb-8 flex items-center justify-center gap-2.5",
  logoIcono:
    "grid h-10 w-10 shrink-0 place-items-center rounded bg-accent text-white",
  // Es un `h1` y no un `span` como en contecflow: quien navega con lector de
  // pantalla necesita que la página tenga un encabezado. Hay un gate que lo
  // comprueba y tenía razón al saltar.
  logoTexto: "m-0 text-pagina font-extrabold tracking-[-0.03em] text-ink",
  etiqueta:
    "mb-1.5 block text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-muted",
  campo:
    "h-11 w-full rounded border border-ink-dim bg-paper-sunk px-3.5 text-titulin text-ink outline-none transition-colors focus:border-accent",
  botonPrimario: "btn-primary h-11 w-full justify-center gap-2 text-titulin",
  botonSecundario:
    "btn-secondary h-11 w-full justify-center gap-2 text-titulin",
  avisoError:
    "flex items-start gap-2 rounded border border-danger/30 bg-danger/10 px-3.5 py-2.5 text-dato text-danger-text",
  avisoBien:
    "flex items-start gap-2 rounded border border-success/30 bg-success/10 px-3.5 py-2.5 text-dato text-success-text",
  separador: "my-1 flex items-center gap-3",
  separadorLinea: "h-px flex-1 bg-ink-dim",
  separadorTexto:
    "text-rotulo font-semibold uppercase tracking-[0.1em] text-ink-faint",
  pie: "mt-6 border-t border-ink-dim pt-5 text-center text-rotulo text-ink-faint",
  // NO `.btn-link`: esa clase es monoespaciada y en mayúsculas —sirve para una
  // acción secundaria de una barra—, y aquí dejaba «¿NO LA RECUERDAS?»
  // escrito como un código. Visto en la pantalla el 02-11-2026.
  enlace: "text-dato font-medium text-accent hover:underline",
  formulario: "flex flex-col gap-4",
  ayuda: "m-0 text-dato text-ink-muted",
} as const;

// ── Iconos, en línea y sin dependencia ────────────────────────────────────

function IconoOjo() {
  return (
    <svg
      width="17"
      height="17"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function IconoOjoTachado() {
  return (
    <svg
      width="17"
      height="17"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  );
}

function IconoPasskey() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="8" cy="8" r="4" />
      <path d="M12 8h4M18 6v4" />
      <path d="M4 20c0-2.5 1.8-4 4-4s4 1.5 4 4" />
    </svg>
  );
}

function IconoEscudo() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}

function IconoMarca() {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      // El blanco lo hereda de la pastilla de acento que lo contiene. Escrito
      // a mano se quedaba blanco aunque la marca cambiara de color, y además
      // era el único color literal que quedaba en una pantalla.
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="3" />
      <circle cx="5" cy="6" r="2" />
      <circle cx="19" cy="6" r="2" />
      <circle cx="5" cy="18" r="2" />
      <circle cx="19" cy="18" r="2" />
      <path d="M6.6 7.2 10 10.2M17.4 7.2 14 10.2M6.6 16.8 10 13.8M17.4 16.8 14 13.8" />
    </svg>
  );
}

type Vista = "entrar" | "olvidada";

export function Entrar({ alEntrar }: { alEntrar: () => void }) {
  const { t } = useTranslation();
  const [vista, setVista] = useState<Vista>("entrar");
  const [email, setEmail] = useState("");
  const [contrasena, setContrasena] = useState("");
  const [verContrasena, setVerContrasena] = useState(false);
  // El tenant es obligatorio y no se adivina: la misma persona puede estar en
  // varios y sus permisos son distintos en cada uno. Deducirlo del correo
  // obligaría a preguntar al servidor quién es antes de autenticarla, que es
  // filtrar en qué organizaciones tiene cuenta.
  const [tenant, setTenant] = useState("");
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [enviando, setEnviando] = useState(false);
  // El segundo paso: el servidor pide el código del segundo factor (porque la
  // empresa o el rol lo exigen, o porque el contexto de la entrada cambió).
  // Hasta el 09-11-2026 esta pantalla no mandaba nunca el código: con el
  // segundo factor exigido, nadie podía entrar desde el navegador.
  const [pideCodigo, setPideCodigo] = useState(false);
  const [codigo, setCodigo] = useState("");
  const [porQueCodigo, setPorQueCodigo] = useState("");
  // Recordar este equipo al pasar el segundo factor (CRM-00.05.01.20). Sin
  // esta casilla la MFA adaptativa (CRM-00.05.01.21) no servía de nada en el
  // navegador: ningún equipo quedaba de confianza, así que el código se pedía
  // SIEMPRE y nunca «sólo cuando cambia el contexto» —medido el 09-11-2026—.
  const [recordar, setRecordar] = useState(false);
  // Al pedirlo, el foco va al campo: es lo único que queda por hacer.
  useEffect(() => {
    if (pideCodigo) document.getElementById("entrar-codigo")?.focus();
  }, [pideCodigo]);
  const [conLlave, setConLlave] = useState(false);
  const [nueva, setNueva] = useState("");
  const hayPasskeys = admitePasskeys();

  // El token del enlace llega en la dirección. Se detecta al cargar para
  // enseñar directamente el paso de poner la contraseña nueva.
  const tokenDeReset =
    new URLSearchParams(window.location.search).get("restablecer") ?? "";
  useEffect(() => {
    if (tokenDeReset) setVista("olvidada");
  }, [tokenDeReset]);

  function comoTexto(fallo: unknown, porDefecto: string): string {
    const detalle = (fallo as { detalle?: string; message?: string })?.detalle;
    return detalle || (fallo as Error)?.message || porDefecto;
  }

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setError("");
    setEnviando(true);
    try {
      // Por `/sesion/entrar` y no por `/auth/login`: esta devuelve el token en
      // una cookie `HttpOnly` que ningún script puede leer. `/auth/login`
      // devuelve los tokens en el cuerpo, que es lo correcto para una
      // integración y lo peor posible para un navegador.
      await llamar("/api/v1/sesion/entrar", {
        metodo: "POST",
        cuerpo: {
          email,
          contrasena,
          tenant,
          huella_dispositivo: huellaDelNavegador(),
          ...(pideCodigo && codigo.trim() ? { codigo_mfa: codigo.trim() } : {}),
          ...(pideCodigo && codigo.trim() && recordar
            ? { recordar_dispositivo: true }
            : {}),
        },
      });
      alEntrar();
    } catch (fallo) {
      const cod = fallo instanceof ErrorApi ? fallo.codigo : "";
      if (
        cod === "auth.mfa_requerida" ||
        cod === "auth.factor_requerido_por_riesgo"
      ) {
        const det = (fallo as ErrorApi).detalle as {
          explicacion?: string;
        } | null;
        setPideCodigo(true);
        setPorQueCodigo(
          cod === "auth.factor_requerido_por_riesgo" && det?.explicacion
            ? det.explicacion
            : t("entrar.codigoPorQue"),
        );
        return;
      }
      setError(comoTexto(fallo, t("entrar.noSePudo")));
    } finally {
      setEnviando(false);
    }
  }

  async function entrarConLlave() {
    if (!tenant.trim()) {
      setError(t("entrar.faltaTenant"));
      return;
    }
    setError("");
    setConLlave(true);
    try {
      const reto = await llamar<Record<string, unknown>>(
        "/api/v1/auth/passkeys/entrar",
        {
          metodo: "POST",
          cuerpo: { tenant, email },
        },
      );
      const firmada = await firmarConPasskey(reto.datos as never);
      await llamar("/api/v1/sesion/entrar", {
        metodo: "POST",
        cuerpo: { tenant, passkey: firmada },
      });
      alEntrar();
    } catch (fallo) {
      // Cancelar el diálogo del sistema no es un fallo: no se enseña nada.
      if (fallo instanceof DOMException && fallo.name === "NotAllowedError")
        return;
      setError(comoTexto(fallo, t("entrar.llaveNoVale")));
    } finally {
      setConLlave(false);
    }
  }

  async function pedirEnlace(evento: FormEvent) {
    evento.preventDefault();
    setError("");
    setEnviando(true);
    try {
      await llamar("/api/v1/auth/restablecer", {
        metodo: "POST",
        cuerpo: { email, tenant },
      });
    } catch {
      // A propósito: se dice lo mismo salga como salga. Distinguirlo
      // convertiría esto en un comprobador de qué correos tienen cuenta.
    } finally {
      setEnviando(false);
      setAviso(t("entrar.enlaceEnviado"));
    }
  }

  async function ponerNueva(evento: FormEvent) {
    evento.preventDefault();
    setError("");
    setEnviando(true);
    try {
      await llamar("/api/v1/auth/restablecer/confirmar", {
        metodo: "POST",
        cuerpo: { token: tokenDeReset, contrasena: nueva },
      });
      setAviso(t("entrar.contrasenaCambiada"));
      setVista("entrar");
      window.history.replaceState({}, "", window.location.pathname);
    } catch (fallo) {
      setError(comoTexto(fallo, t("entrar.noSePudo")));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className={cl.pagina}>
      <div style={{ width: "100%", maxWidth: 400 }}>
        <div className={cl.tarjeta}>
          <div className={cl.logo}>
            {config().logotipo ? (
              <img
                src={config().logotipo}
                alt={config().nombre}
                style={{ height: 40 }}
              />
            ) : (
              <span className={cl.logoIcono}>
                <IconoMarca />
              </span>
            )}
            <h1 className={cl.logoTexto}>{config().nombre}</h1>
          </div>

          {vista === "olvidada" ? (
            tokenDeReset ? (
              /* ── Poner una contraseña nueva ───────────────────────── */
              <form onSubmit={ponerNueva} className={cl.formulario} noValidate>
                <p className={cl.ayuda}>{t("entrar.eligeNueva")}</p>
                <div>
                  <label className={cl.etiqueta} htmlFor="entrar-nueva">
                    {t("entrar.contrasenaNueva")}
                  </label>
                  <input
                    id="entrar-nueva"
                    type={verContrasena ? "text" : "password"}
                    required
                    minLength={12}
                    autoComplete="new-password"
                    value={nueva}
                    onChange={(e) => setNueva(e.target.value)}
                    className={cl.campo}
                  />
                  <p className="m-0 mt-1.5 text-rotulo text-ink-faint">
                    {t("entrar.minimoDoce")}
                  </p>
                </div>
                {error ? (
                  <div className={cl.avisoError} role="alert">
                    <span>⚠</span>
                    <span>{error}</span>
                  </div>
                ) : null}
                <button
                  type="submit"
                  disabled={enviando}
                  className={cn(cl.botonPrimario, enviando && "opacity-60")}
                >
                  {enviando ? t("app.cargando") : t("entrar.guardarContrasena")}
                </button>
              </form>
            ) : (
              /* ── Pedir el enlace ──────────────────────────────────── */
              <form onSubmit={pedirEnlace} className={cl.formulario} noValidate>
                <p className={cl.ayuda}>{t("entrar.recuperarAyuda")}</p>
                <div>
                  <label className={cl.etiqueta} htmlFor="olvido-tenant">
                    {t("entrar.tenant")}
                  </label>
                  <input
                    id="olvido-tenant"
                    type="text"
                    required
                    autoComplete="organization"
                    value={tenant}
                    onChange={(e) => setTenant(e.target.value)}
                    className={cl.campo}
                  />
                </div>
                <div>
                  <label className={cl.etiqueta} htmlFor="olvido-email">
                    {t("entrar.email")}
                  </label>
                  <input
                    id="olvido-email"
                    type="email"
                    required
                    autoComplete="username"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={cl.campo}
                  />
                </div>
                {aviso ? (
                  <div className={cl.avisoBien} role="status">
                    <span>✓</span>
                    <span>{aviso}</span>
                  </div>
                ) : null}
                <button
                  type="submit"
                  disabled={enviando}
                  className={cn(cl.botonPrimario, enviando && "opacity-60")}
                >
                  {enviando ? t("app.cargando") : t("entrar.mandarEnlace")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setVista("entrar");
                    setAviso("");
                    setError("");
                  }}
                  className="w-full text-center text-rotulo font-medium text-accent hover:underline"
                >
                  {t("entrar.volver")}
                </button>
              </form>
            )
          ) : (
            <>
              <a
                href="/api/v1/sso/iniciar"
                className={cn(cl.botonSecundario, "mb-1 no-underline")}
              >
                <IconoEscudo />
                <span>{t("entrar.sso")}</span>
              </a>

              {/* La separación dice que son caminos distintos y no pasos. Sin
                  ella, el botón de arriba parece el primer paso del formulario
                  de abajo. */}
              <div className={cl.separador}>
                <div className={cl.separadorLinea} />
                <span className={cl.separadorTexto}>{t("entrar.o")}</span>
                <div className={cl.separadorLinea} />
              </div>

              <form onSubmit={enviar} className={cl.formulario} noValidate>
                <div>
                  <label className={cl.etiqueta} htmlFor="entrar-tenant">
                    {t("entrar.tenant")}
                  </label>
                  <input
                    id="entrar-tenant"
                    type="text"
                    required
                    autoComplete="organization"
                    value={tenant}
                    onChange={(e) => setTenant(e.target.value)}
                    className={cl.campo}
                  />
                </div>

                <div>
                  <label className={cl.etiqueta} htmlFor="entrar-email">
                    {t("entrar.email")}
                  </label>
                  <input
                    id="entrar-email"
                    type="email"
                    required
                    autoComplete="username"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={cl.campo}
                  />
                </div>

                <div>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: 6,
                    }}
                  >
                    <label
                      className={cn(cl.etiqueta, "mb-0")}
                      htmlFor="entrar-contrasena"
                    >
                      {t("entrar.contrasena")}
                    </label>
                    {/* Aquí y no al final: quien no puede entrar lo busca justo
                        al lado del campo que no consigue rellenar. */}
                    <button
                      type="button"
                      onClick={() => {
                        setVista("olvidada");
                        setError("");
                        setAviso("");
                      }}
                      className={cl.enlace}
                    >
                      {t("entrar.olvidada")}
                    </button>
                  </div>
                  <div style={{ position: "relative" }}>
                    <input
                      id="entrar-contrasena"
                      type={verContrasena ? "text" : "password"}
                      required
                      autoComplete="current-password"
                      value={contrasena}
                      onChange={(e) => setContrasena(e.target.value)}
                      className={cn(cl.campo, "pr-11")}
                    />
                    {/* Enseñarla es lo que evita el tercer intento a ciegas con
                        una contraseña larga y un teclado que no se ve. */}
                    <button
                      type="button"
                      onClick={() => setVerContrasena((v) => !v)}
                      aria-label={t(
                        verContrasena ? "entrar.ocultar" : "entrar.ver",
                      )}
                      className="absolute right-3 top-1/2 flex -translate-y-1/2 items-center p-1 text-ink-muted hover:text-ink"
                    >
                      {verContrasena ? <IconoOjoTachado /> : <IconoOjo />}
                    </button>
                  </div>
                </div>

                {pideCodigo ? (
                  <div className="space-y-1">
                    <label
                      htmlFor="entrar-codigo"
                      className="text-rotulo text-ink-muted"
                    >
                      {t("entrar.codigo")}
                    </label>
                    <p role="status" className="text-rotulo text-ink-faint">
                      {porQueCodigo}
                    </p>
                    <input
                      id="entrar-codigo"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      required
                      value={codigo}
                      onChange={(e) => setCodigo(e.target.value)}
                      className={cl.campo}
                    />
                    <label className="flex items-center gap-2 text-rotulo text-ink-muted">
                      <input
                        type="checkbox"
                        checked={recordar}
                        onChange={(e) => setRecordar(e.target.checked)}
                      />
                      {t("entrar.recordarEquipo")}
                    </label>
                  </div>
                ) : null}

                {error ? (
                  <div className={cl.avisoError} role="alert">
                    <span>⚠</span>
                    <span>{error}</span>
                  </div>
                ) : null}
                {aviso ? (
                  <div className={cl.avisoBien} role="status">
                    <span>✓</span>
                    <span>{aviso}</span>
                  </div>
                ) : null}

                <button
                  type="submit"
                  disabled={enviando}
                  className={cn(cl.botonPrimario, enviando && "opacity-60")}
                >
                  {enviando ? t("app.cargando") : t("entrar.enviar")}
                </button>

                {hayPasskeys ? (
                  <button
                    type="button"
                    onClick={() => void entrarConLlave()}
                    disabled={conLlave}
                    className={cn(cl.botonSecundario, conLlave && "opacity-60")}
                  >
                    <IconoPasskey />
                    <span>
                      {conLlave ? t("app.cargando") : t("entrar.conPasskey")}
                    </span>
                  </button>
                ) : null}
              </form>
            </>
          )}

          <div className={cl.pie}>{t("entrar.pie")}</div>
        </div>
      </div>
    </div>
  );
}

/**
 * Una huella estable de este navegador, para que el servidor pueda recordar
 * un dispositivo de confianza y notar cuándo se entra desde otro. No es un
 * secreto ni identifica a la persona: un número al azar guardado aquí. Si el
 * navegador no deja guardar nada, se manda vacía y el servidor lo trata como
 * dispositivo nuevo.
 */
function huellaDelNavegador(): string {
  try {
    const guardada = localStorage.getItem("crm.huella_dispositivo");
    if (guardada) return guardada;
    const nueva = crypto.randomUUID();
    localStorage.setItem("crm.huella_dispositivo", nueva);
    return nueva;
  } catch {
    return "";
  }
}
