/**
 * Entrada al CRM (CRM-07.04.02.01, CRM-00.05.01.23, CRM-00.05.01.26).
 *
 * **El diseño es el de contecflow, carácter por carácter**: la misma tipografía
 * (DM Sans), los mismos colores, la misma tarjeta de 400 px con radio 20, los
 * mismos campos de 44 px de alto y la misma separación con «o». Se pidió que
 * fuera exacto y aquí exacto significa los mismos valores, no unos parecidos:
 * por eso van escritos, y no traducidos a los tokens de este producto —que son
 * otros y darían otra pantalla—.
 *
 * Es la única pantalla del CRM que se sale del sistema de diseño, y se sale a
 * propósito: se ve antes de entrar, no tiene marco alrededor y es la que
 * comparten las dos soluciones de la casa.
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

import { useEffect, useState, type CSSProperties, type FocusEvent, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { llamar } from "@/lib/api";
import { config } from "@/lib/config";
import { admitePasskeys, firmarConPasskey } from "@/lib/webauthn";

// ── Los valores de contecflow, tal cual ──────────────────────────────────
//
// Copiados de su `index.css` y de su `LoginPage.tsx`. Escritos y no derivados
// de variables porque son de la OTRA solución: si se leyeran de las de aquí,
// la pantalla dejaría de ser la misma en cuanto una de las dos cambiara un
// color, y lo que se ha pedido es que sean idénticas.
const C = {
  fondo: "#080c14", // --surface-0
  tarjeta: "#0d1220", // --surface-1
  campo: "#111827", // --surface-2
  borde: "#1e2d45", // --surface-4
  texto1: "#f0f4ff",
  texto2: "#a8b8d4",
  texto3: "#7689a8",
  texto4: "#4a5a78",
  acento: "#4f8ef7",
  peligro: "#f87171",
  peligroFondo: "rgba(248, 113, 113, 0.08)",
  peligroBorde: "rgba(248, 113, 113, 0.2)",
  exito: "#34d399",
  exitoFondo: "rgba(52, 211, 153, 0.08)",
  exitoBorde: "rgba(52, 211, 153, 0.2)",
  fuente: "'DM Sans', 'Geist', system-ui, sans-serif",
} as const;

const st: Record<string, CSSProperties> = {
  pagina: {
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    background: C.fondo,
    padding: "24px 16px",
    position: "relative",
    fontFamily: C.fuente,
  },
  tarjeta: {
    width: "100%",
    maxWidth: 400,
    background: C.tarjeta,
    border: `1px solid ${C.borde}`,
    borderRadius: 20,
    padding: "36px 32px",
    boxShadow: "0 8px 40px rgba(0,0,0,0.35)",
  },
  logo: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    marginBottom: 32,
  },
  logoIcono: {
    width: 40,
    height: 40,
    background: C.acento,
    borderRadius: 12,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  // Es un `h1` y no un `span` como en contecflow: se ve igual —mismo tamaño,
  // mismo peso, mismo interletrado, margen a cero— y quien navega con lector de
  // pantalla necesita que la página tenga un encabezado. Hay un gate que lo
  // comprueba y tenía razón al saltar.
  logoTexto: {
    fontSize: 22,
    fontWeight: 800,
    color: C.texto1,
    letterSpacing: "-0.03em",
    margin: 0,
    lineHeight: 1.2,
  },
  etiqueta: {
    display: "block",
    fontSize: 11,
    fontWeight: 600,
    color: C.texto3,
    marginBottom: 6,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
  },
  campo: {
    width: "100%",
    height: 44,
    padding: "0 14px",
    background: C.campo,
    border: `1px solid ${C.borde}`,
    borderRadius: 12,
    color: C.texto1,
    fontSize: 14,
    fontFamily: "inherit",
    outline: "none",
    boxSizing: "border-box",
    transition: "border-color 0.15s",
  },
  botonPrimario: {
    width: "100%",
    height: 44,
    background: C.acento,
    color: "#fff",
    border: "none",
    borderRadius: 12,
    fontWeight: 700,
    fontSize: 14,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    transition: "opacity 0.15s",
    fontFamily: "inherit",
  },
  botonSecundario: {
    width: "100%",
    height: 44,
    background: "transparent",
    color: C.texto2,
    border: `1px solid ${C.borde}`,
    borderRadius: 12,
    fontWeight: 600,
    fontSize: 14,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    transition: "background 0.15s, border-color 0.15s",
    fontFamily: "inherit",
  },
  avisoError: {
    background: C.peligroFondo,
    border: `1px solid ${C.peligroBorde}`,
    borderRadius: 10,
    padding: "10px 14px",
    color: C.peligro,
    fontSize: 13,
    display: "flex",
    alignItems: "flex-start",
    gap: 8,
  },
  avisoBien: {
    background: C.exitoFondo,
    border: `1px solid ${C.exitoBorde}`,
    borderRadius: 10,
    padding: "10px 14px",
    color: C.exito,
    fontSize: 13,
    display: "flex",
    alignItems: "flex-start",
    gap: 8,
  },
  separador: { display: "flex", alignItems: "center", gap: 12, margin: "4px 0" },
  separadorLinea: { flex: 1, height: 1, background: C.borde },
  separadorTexto: {
    fontSize: 11,
    fontWeight: 600,
    color: C.texto4,
    textTransform: "uppercase",
    letterSpacing: "0.1em",
  },
  pie: {
    marginTop: 24,
    paddingTop: 20,
    borderTop: `1px solid ${C.borde}`,
    textAlign: "center",
    fontSize: 12,
    color: C.texto4,
  },
  enlace: {
    background: "none",
    border: "none",
    color: C.acento,
    fontSize: 13,
    cursor: "pointer",
    padding: 0,
    fontFamily: "inherit",
    fontWeight: 500,
  },
  formulario: { display: "flex", flexDirection: "column", gap: 16 },
  ayuda: { fontSize: 13, color: C.texto2, margin: 0 },
};

// ── Iconos, en línea y sin dependencia ────────────────────────────────────

function IconoOjo() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function IconoOjoTachado() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  );
}

function IconoPasskey() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="4" />
      <path d="M12 8h4M18 6v4" />
      <path d="M4 20c0-2.5 1.8-4 4-4s4 1.5 4 4" />
    </svg>
  );
}

function IconoEscudo() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}

function IconoMarca() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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
  const [conLlave, setConLlave] = useState(false);
  const [nueva, setNueva] = useState("");
  const hayPasskeys = admitePasskeys();

  // El token del enlace llega en la dirección. Se detecta al cargar para
  // enseñar directamente el paso de poner la contraseña nueva.
  const tokenDeReset = new URLSearchParams(window.location.search).get("restablecer") ?? "";
  useEffect(() => {
    if (tokenDeReset) setVista("olvidada");
  }, [tokenDeReset]);

  function entra(e: FocusEvent<HTMLInputElement>) {
    e.target.style.borderColor = C.acento;
  }
  function sale(e: FocusEvent<HTMLInputElement>) {
    e.target.style.borderColor = C.borde;
  }

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
        cuerpo: { email, contrasena, tenant },
      });
      alEntrar();
    } catch (fallo) {
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
      const reto = await llamar<Record<string, unknown>>("/api/v1/auth/passkeys/entrar", {
        metodo: "POST",
        cuerpo: { tenant, email },
      });
      const firmada = await firmarConPasskey(reto.datos as never);
      await llamar("/api/v1/sesion/entrar", {
        metodo: "POST",
        cuerpo: { tenant, passkey: firmada },
      });
      alEntrar();
    } catch (fallo) {
      // Cancelar el diálogo del sistema no es un fallo: no se enseña nada.
      if (fallo instanceof DOMException && fallo.name === "NotAllowedError") return;
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
      await llamar("/api/v1/auth/restablecer", { metodo: "POST", cuerpo: { email, tenant } });
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
    <div style={st.pagina}>
      <div style={{ width: "100%", maxWidth: 400 }}>
        <div style={st.tarjeta}>
          <div style={st.logo}>
            {config().logotipo ? (
              <img src={config().logotipo} alt={config().nombre} style={{ height: 40 }} />
            ) : (
              <span style={st.logoIcono}>
                <IconoMarca />
              </span>
            )}
            <h1 style={st.logoTexto}>{config().nombre}</h1>
          </div>

          {vista === "olvidada" ? (
            tokenDeReset ? (
              /* ── Poner una contraseña nueva ───────────────────────── */
              <form onSubmit={ponerNueva} style={st.formulario} noValidate>
                <p style={st.ayuda}>{t("entrar.eligeNueva")}</p>
                <div>
                  <label style={st.etiqueta} htmlFor="entrar-nueva">
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
                    style={st.campo}
                    onFocus={entra}
                    onBlur={sale}
                  />
                  <p style={{ ...st.ayuda, fontSize: 12, marginTop: 6, color: C.texto4 }}>
                    {t("entrar.minimoDoce")}
                  </p>
                </div>
                {error ? (
                  <div style={st.avisoError} role="alert">
                    <span>⚠</span>
                    <span>{error}</span>
                  </div>
                ) : null}
                <button
                  type="submit"
                  disabled={enviando}
                  style={{ ...st.botonPrimario, opacity: enviando ? 0.6 : 1 }}
                >
                  {enviando ? t("app.cargando") : t("entrar.guardarContrasena")}
                </button>
              </form>
            ) : (
              /* ── Pedir el enlace ──────────────────────────────────── */
              <form onSubmit={pedirEnlace} style={st.formulario} noValidate>
                <p style={st.ayuda}>{t("entrar.recuperarAyuda")}</p>
                <div>
                  <label style={st.etiqueta} htmlFor="olvido-tenant">
                    {t("entrar.tenant")}
                  </label>
                  <input
                    id="olvido-tenant"
                    type="text"
                    required
                    autoComplete="organization"
                    value={tenant}
                    onChange={(e) => setTenant(e.target.value)}
                    style={st.campo}
                    onFocus={entra}
                    onBlur={sale}
                  />
                </div>
                <div>
                  <label style={st.etiqueta} htmlFor="olvido-email">
                    {t("entrar.email")}
                  </label>
                  <input
                    id="olvido-email"
                    type="email"
                    required
                    autoComplete="username"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    style={st.campo}
                    onFocus={entra}
                    onBlur={sale}
                  />
                </div>
                {aviso ? (
                  <div style={st.avisoBien} role="status">
                    <span>✓</span>
                    <span>{aviso}</span>
                  </div>
                ) : null}
                <button
                  type="submit"
                  disabled={enviando}
                  style={{ ...st.botonPrimario, opacity: enviando ? 0.6 : 1 }}
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
                  style={{ ...st.enlace, textAlign: "center", width: "100%", fontSize: 12 }}
                >
                  {t("entrar.volver")}
                </button>
              </form>
            )
          ) : (
            <>
              <a
                href="/api/v1/sso/iniciar"
                style={{ ...st.botonSecundario, textDecoration: "none", marginBottom: 4 }}
              >
                <IconoEscudo />
                <span>{t("entrar.sso")}</span>
              </a>

              {/* La separación dice que son caminos distintos y no pasos. Sin
                  ella, el botón de arriba parece el primer paso del formulario
                  de abajo. */}
              <div style={st.separador}>
                <div style={st.separadorLinea} />
                <span style={st.separadorTexto}>{t("entrar.o")}</span>
                <div style={st.separadorLinea} />
              </div>

              <form onSubmit={enviar} style={st.formulario} noValidate>
                <div>
                  <label style={st.etiqueta} htmlFor="entrar-tenant">
                    {t("entrar.tenant")}
                  </label>
                  <input
                    id="entrar-tenant"
                    type="text"
                    required
                    autoComplete="organization"
                    value={tenant}
                    onChange={(e) => setTenant(e.target.value)}
                    style={st.campo}
                    onFocus={entra}
                    onBlur={sale}
                  />
                </div>

                <div>
                  <label style={st.etiqueta} htmlFor="entrar-email">
                    {t("entrar.email")}
                  </label>
                  <input
                    id="entrar-email"
                    type="email"
                    required
                    autoComplete="username"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    style={st.campo}
                    onFocus={entra}
                    onBlur={sale}
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
                    <label style={{ ...st.etiqueta, marginBottom: 0 }} htmlFor="entrar-contrasena">
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
                      style={st.enlace}
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
                      style={{ ...st.campo, paddingRight: 44 }}
                      onFocus={entra}
                      onBlur={sale}
                    />
                    {/* Enseñarla es lo que evita el tercer intento a ciegas con
                        una contraseña larga y un teclado que no se ve. */}
                    <button
                      type="button"
                      onClick={() => setVerContrasena((v) => !v)}
                      aria-label={t(verContrasena ? "entrar.ocultar" : "entrar.ver")}
                      style={{
                        position: "absolute",
                        right: 12,
                        top: "50%",
                        transform: "translateY(-50%)",
                        background: "none",
                        border: "none",
                        color: C.texto3,
                        cursor: "pointer",
                        padding: 4,
                        display: "flex",
                        alignItems: "center",
                      }}
                    >
                      {verContrasena ? <IconoOjoTachado /> : <IconoOjo />}
                    </button>
                  </div>
                </div>

                {error ? (
                  <div style={st.avisoError} role="alert">
                    <span>⚠</span>
                    <span>{error}</span>
                  </div>
                ) : null}
                {aviso ? (
                  <div style={st.avisoBien} role="status">
                    <span>✓</span>
                    <span>{aviso}</span>
                  </div>
                ) : null}

                <button
                  type="submit"
                  disabled={enviando}
                  style={{ ...st.botonPrimario, opacity: enviando ? 0.6 : 1 }}
                >
                  {enviando ? t("app.cargando") : t("entrar.enviar")}
                </button>

                {hayPasskeys ? (
                  <button
                    type="button"
                    onClick={() => void entrarConLlave()}
                    disabled={conLlave}
                    style={{ ...st.botonSecundario, opacity: conLlave ? 0.6 : 1 }}
                  >
                    <IconoPasskey />
                    <span>{conLlave ? t("app.cargando") : t("entrar.conPasskey")}</span>
                  </button>
                ) : null}
              </form>
            </>
          )}

          <div style={st.pie}>{t("entrar.pie")}</div>
        </div>
      </div>
    </div>
  );
}
