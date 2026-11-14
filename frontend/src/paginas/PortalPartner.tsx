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
 * Canjear devuelve la **sesión del portal de partner** (desde el 14-11-2026,
 * COB-14; antes no abría ninguna y esta pantalla solo podía decir «no hay nada
 * más que abrir»). La sesión vive **solo en memoria**, como la del portal de
 * cliente: se entra desde un enlace, a ratos y a veces desde un ordenador
 * compartido. Recargar pide otro enlace.
 *
 * Con ella el partner ve sus registros de oportunidad y registra uno nuevo. Qué
 * partner es lo dice la sesión, no la pantalla: el servidor ignora cualquier
 * `partner_id` que se le mande.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { useTranslation } from "react-i18next";

import {
  Cargando,
  Error as Fallo,
  FalloCompacto,
  Vacio,
} from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { ErrorApi, llamar } from "@/lib/api";
import { config } from "@/lib/config";
import { fecha } from "@/lib/formato";

/** `POST /portal-partner/canjear`: la sesión y de quién es. */
interface Acceso {
  token: string;
  caduca_en_s: number;
  acceso_id: string;
  partner_id: string;
  nivel: string;
}

/** `GET /portal-partner/mis-registros`. */
interface Registro {
  id: string;
  cliente: string;
  estado: string;
  protegido_hasta: string | null;
  motivo: string | null;
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
              <p className="mt-1 text-rotulo text-ink-faint">
                {t("portalPartner.sesionEnMemoria")}
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

        {acceso ? <EspacioDelPartner sesion={acceso.token} /> : null}
      </div>
    </main>
  );
}

/** Lo que el partner hace con su sesión: ver sus registros y registrar uno. */
function EspacioDelPartner({ sesion }: { sesion: string }) {
  const { t } = useTranslation();
  const [registros, setRegistros] = useState<Registro[] | null>(null);
  const [falloLista, setFalloLista] = useState<unknown>(null);
  const [vuelta, setVuelta] = useState(0);

  const cargar = useCallback(
    (signal: AbortSignal) => {
      setFalloLista(null);
      llamar<{ registros: Registro[] }>(
        "/api/v1/portal-partner/mis-registros",
        { sesionExterna: sesion, signal },
      )
        .then((r) => setRegistros(r.datos.registros))
        .catch((error: unknown) => {
          if (!signal.aborted) setFalloLista(error);
        });
    },
    [sesion],
  );

  useEffect(() => {
    const control = new AbortController();
    cargar(control.signal);
    return () => control.abort();
  }, [cargar, vuelta]);

  return (
    <>
      <section className="card mt-4 p-4" aria-labelledby="partner-registros">
        <h2 id="partner-registros" className="section-label mb-2">
          {t("portalPartner.misRegistros")}
        </h2>
        {falloLista ? (
          <FalloCompacto
            error={falloLista}
            que={t("portalPartner.misRegistros")}
            reintentar={() => setVuelta((v) => v + 1)}
          />
        ) : registros === null ? (
          <Cargando />
        ) : registros.length === 0 ? (
          <Vacio compacto titulo={t("portalPartner.sinRegistros")} />
        ) : (
          <ul className="divide-y divide-line">
            {registros.map((r) => (
              <li key={r.id} className="py-2">
                <p className="font-medium text-ink">{r.cliente}</p>
                <p className="text-dato text-ink-muted">
                  {t(`portalPartner.estados.${r.estado}`, {
                    defaultValue: r.estado,
                  })}
                  {r.protegido_hasta
                    ? ` · ${t("portalPartner.protegidoHasta", {
                        fecha: fecha(r.protegido_hasta),
                      })}`
                    : ""}
                </p>
                {r.motivo ? (
                  <p className="text-rotulo text-ink-faint">{r.motivo}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
      <NuevoRegistro
        sesion={sesion}
        alRegistrar={() => setVuelta((v) => v + 1)}
      />
    </>
  );
}

function NuevoRegistro({
  sesion,
  alRegistrar,
}: {
  sesion: string;
  alRegistrar: () => void;
}) {
  const { t } = useTranslation();
  const [cliente, setCliente] = useState("");
  const [nif, setNif] = useState("");
  const [dominio, setDominio] = useState("");
  const [descripcion, setDescripcion] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [hecho, setHecho] = useState<string | null>(null);
  // El servidor exige NIF o dominio (el nombre no identifica a nadie). Se dice
  // junto a los campos, no solo deshabilitando el botón.
  const faltaIdentificador = !nif.trim() && !dominio.trim();

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setFallo(null);
    setHecho(null);
    setEnviando(true);
    try {
      const r = await llamar<{ estado: string; hay_conflicto: boolean }>(
        "/api/v1/portal-partner/registros",
        {
          metodo: "POST",
          sesionExterna: sesion,
          cuerpo: {
            cliente_nombre: cliente.trim(),
            nif: nif.trim() || null,
            dominio: dominio.trim() || null,
            descripcion: descripcion.trim(),
          },
        },
      );
      setHecho(
        r.datos.hay_conflicto
          ? t("portalPartner.registradoConConflicto")
          : t("portalPartner.registrado"),
      );
      setCliente("");
      setNif("");
      setDominio("");
      setDescripcion("");
      alRegistrar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="card mt-4 p-4" aria-labelledby="partner-nuevo">
      <h2 id="partner-nuevo" className="section-label mb-2">
        {t("portalPartner.registrar")}
      </h2>
      <form onSubmit={(e) => void enviar(e)} className="flex flex-col gap-2">
        <label htmlFor="partner-cliente" className="text-rotulo text-ink-muted">
          {t("portalPartner.cliente")}
        </label>
        <input
          id="partner-cliente"
          className="input-base"
          required
          maxLength={200}
          value={cliente}
          onChange={(e) => setCliente(e.target.value)}
        />
        <label htmlFor="partner-nif" className="text-rotulo text-ink-muted">
          {t("portalPartner.nif")}
        </label>
        <input
          id="partner-nif"
          className="input-base"
          value={nif}
          onChange={(e) => setNif(e.target.value)}
          aria-describedby="partner-identificador"
        />
        <label htmlFor="partner-dominio" className="text-rotulo text-ink-muted">
          {t("portalPartner.dominio")}
        </label>
        <input
          id="partner-dominio"
          className="input-base"
          value={dominio}
          onChange={(e) => setDominio(e.target.value)}
          aria-describedby="partner-identificador"
        />
        <p id="partner-identificador" className="text-rotulo text-ink-faint">
          {t("portalPartner.identificador")}
        </p>
        <label
          htmlFor="partner-descripcion"
          className="text-rotulo text-ink-muted"
        >
          {t("portalPartner.descripcion")}
        </label>
        <textarea
          id="partner-descripcion"
          className="input-base"
          rows={3}
          value={descripcion}
          onChange={(e) => setDescripcion(e.target.value)}
        />
        <div>
          <button
            type="submit"
            className="btn-primary"
            disabled={enviando || !cliente.trim() || faltaIdentificador}
            aria-busy={enviando}
          >
            {enviando ? t("app.cargando") : t("portalPartner.enviarRegistro")}
          </button>
        </div>
        {hecho ? (
          <p className="text-dato text-ink" role="status">
            {hecho}
          </p>
        ) : null}
        {fallo ? <Fallo error={fallo} /> : null}
      </form>
    </section>
  );
}
