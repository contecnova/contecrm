/**
 * Abrir el enlace del portal de partner (CRM-03.04.01.02).
 *
 * El correo apunta a `/portal-partner?tenant=…&t=…` desde el 13-11-2026 y esa
 * dirección no la trataba nadie: caía en el portal de clientes —la ruta empieza
 * por `/portal`—, que pedía otro enlace distinto. El partner abría su correo y
 * llegaba a una pantalla que no era la suya.
 *
 * Va fuera del marco y **sin cookie**, como decidir una aprobación desde el
 * correo: quien la abre no es un empleado, y con la cookie de una sesión
 * caducada en el navegador el gateway le contestaría «tu sesión ha caducado».
 *
 * Abrir la página **no canjea** el enlace: es de un solo uso, y los escáneres
 * de correo abren los enlaces para revisarlos. Una página que lo canjeara al
 * cargarse lo gastaría por ellos, y el partner llegaría a «este enlace ya no
 * sirve». Se canjea pulsando.
 *
 * **Lo que no hay todavía**, y se dice en pantalla en vez de esconderlo:
 * `POST /portal-partner/canjear` comprueba el enlace y devuelve el acceso, pero
 * no abre ninguna sesión —ni token en la respuesta ni cookie del gateway—, y
 * el front no tiene pantallas de partner. Así que esto confirma el acceso y
 * explica que no hay nada más que abrir; no lleva a ningún sitio que no exista.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { ErrorApi, llamar } from "@/lib/api";
import { config } from "@/lib/config";

/** `POST /portal-partner/canjear`. */
interface Acceso {
  acceso_id: string;
  partner_id: string;
  nivel: string;
}

/** Un enlace que no vale se dice como tal: el servidor da **el mismo error**
 * para usado, caducado o desconocido, a propósito, y aquí no se adivina cuál. */
function esEnlaceQueNoVale(error: unknown): boolean {
  return (
    error instanceof ErrorApi &&
    (error.codigo === "partners.enlace_no_valido" ||
      error.estado === 401 ||
      error.estado === 422)
  );
}

export function PortalPartner() {
  const { t } = useTranslation();
  const parametros = new URLSearchParams(window.location.search);
  const tenant = parametros.get("tenant") ?? "";
  const token = parametros.get("t") ?? "";
  const [invalido, setInvalido] = useState(!tenant || !token);
  const [enviando, setEnviando] = useState(false);
  const [acceso, setAcceso] = useState<Acceso | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [email, setEmail] = useState("");
  const [pedido, setPedido] = useState(false);
  const [falloAlPedir, setFalloAlPedir] = useState<unknown>(null);
  const resultado = useRef<HTMLDivElement>(null);

  // El resultado recibe el foco: el botón que se pulsó desaparece, y quien
  // navega con teclado o lector se quedaría sin saber dónde está.
  useEffect(() => {
    if (acceso || (invalido && tenant && token)) resultado.current?.focus();
  }, [acceso, invalido, tenant, token]);

  async function canjear() {
    setEnviando(true);
    setFallo(null);
    try {
      const r = await llamar<Acceso>("/api/v1/portal-partner/canjear", {
        metodo: "POST",
        cuerpo: { tenant, token },
        sinCookie: true,
        encolable: false,
      });
      setAcceso(r.datos);
      // El token ya está gastado: fuera de la dirección, para que no quede en
      // el historial ni se comparta al copiar la barra.
      window.history.replaceState({}, "", window.location.pathname);
    } catch (error) {
      if (esEnlaceQueNoVale(error)) setInvalido(true);
      else setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  async function pedirOtro(evento: FormEvent) {
    evento.preventDefault();
    setFalloAlPedir(null);
    setEnviando(true);
    try {
      // La respuesta es la misma tenga o no acceso ese correo; aquí tampoco
      // se distingue, o la pantalla diría quién es partner.
      await llamar("/api/v1/portal-partner/entrar", {
        metodo: "POST",
        cuerpo: { tenant, email: email.trim() },
        sinCookie: true,
        encolable: false,
      });
      setPedido(true);
    } catch (error) {
      setFalloAlPedir(error);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main className="min-h-screen bg-paper-sunk px-4 py-10">
      <div className="mx-auto max-w-xl">
        <p className="mb-4 text-rotulo font-semibold uppercase tracking-[0.055em] text-ink-muted">
          {config().nombre}
        </p>
        <h1 className="mb-1 text-pagina font-bold text-ink">
          {t("portalPartner.titulo")}
        </h1>
        <p className="mb-6 text-dato text-ink-muted">
          {t("portalPartner.entradilla")}
        </p>

        <div
          ref={resultado}
          tabIndex={-1}
          aria-live="polite"
          className="outline-none"
        >
          {acceso ? (
            <section className="card p-4">
              <p className="flex items-center gap-2 font-medium text-ink">
                <Icono nombre="task_alt" tamano="sm" />
                {t("portalPartner.confirmado")}
              </p>
              {acceso.nivel ? (
                <p className="mt-1 text-dato text-ink-muted">
                  {t("portalPartner.nivel", { nivel: acceso.nivel })}
                </p>
              ) : null}
              <p className="mt-3 text-dato text-ink">
                {t("portalPartner.sinPantallas")}
              </p>
            </section>
          ) : invalido ? (
            <section className="card p-4">
              <p className="flex items-center gap-2 font-medium text-ink">
                <Icono nombre="link_off" tamano="sm" />
                {t("portalPartner.invalido")}
              </p>
              <p className="mt-1 text-dato text-ink-muted">
                {tenant
                  ? t("portalPartner.invalidoDetalle")
                  : t("portalPartner.incompleto")}
              </p>
            </section>
          ) : null}
        </div>

        {!acceso && !invalido ? (
          <section className="card p-4">
            <p className="text-dato text-ink">
              {t("portalPartner.antesDeEntrar")}
            </p>
            <button
              type="button"
              className="btn-primary mt-3"
              disabled={enviando}
              aria-busy={enviando}
              onClick={() => void canjear()}
            >
              <Icono nombre="login" tamano="sm" />
              {enviando ? t("app.cargando") : t("portalPartner.entrar")}
            </button>
            <p className="mt-3 text-rotulo text-ink-faint">
              {t("portalPartner.unSoloUso")}
            </p>
            {fallo ? (
              <div className="mt-3">
                <Fallo error={fallo} />
              </div>
            ) : null}
          </section>
        ) : null}

        {/* Pedir otro enlace sin salir de aquí: quien llega con uno caducado
            no tiene otra puerta, porque el portal no tiene pantalla de
            entrada. Solo si se sabe de qué empresa es: el tenant viene en el
            enlace y no se le pide a quien no lo conoce. */}
        {invalido && tenant ? (
          <section className="card mt-4 p-4">
            <h2 className="section-label mb-2">
              {t("portalPartner.pedirOtro")}
            </h2>
            {pedido ? (
              <p className="text-dato text-ink" role="status">
                {t("portalPartner.pedido")}
              </p>
            ) : (
              <form
                onSubmit={(e) => void pedirOtro(e)}
                className="flex flex-col gap-2"
              >
                <label
                  htmlFor="portal-partner-email"
                  className="text-rotulo text-ink-muted"
                >
                  {t("portalPartner.email")}
                </label>
                <input
                  id="portal-partner-email"
                  type="email"
                  required
                  autoComplete="email"
                  className="input-base"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
                <div>
                  <button
                    type="submit"
                    className="btn-primary"
                    disabled={enviando || !email.trim()}
                  >
                    {enviando ? t("app.cargando") : t("portalPartner.mandar")}
                  </button>
                </div>
                {falloAlPedir ? <Fallo error={falloAlPedir} /> : null}
              </form>
            )}
          </section>
        ) : null}
      </div>
    </main>
  );
}
