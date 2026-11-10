/**
 * El portal, visto por quien **no trabaja aquí** (CRM-04.03.02.01).
 *
 * Existía la API del portal y no existía el portal: todas sus rutas pedían una
 * sesión de empleado, así que un cliente no podía entrar y quien quisiera un
 * portal tenía que montar un intermediario que guardase credenciales de
 * empleado para servir a sus clientes. Eso no es un portal.
 *
 * Esta pantalla es deliberadamente distinta del CRM: sin menú lateral, sin
 * paleta de comandos, sin nada que insinúe que hay más detrás. Quien entra aquí
 * es un cliente, no un usuario con menos permisos, y una interfaz que parece el
 * CRM recortado invita a buscar lo que no está.
 *
 * La sesión vive **solo en memoria**. Un portal se usa a ratos y muchas veces
 * desde un ordenador compartido: guardar el token haría que el siguiente que se
 * siente entre sin pedir nada. Recargar pide el enlace otra vez, que es lo
 * correcto aquí aunque sería insoportable en el CRM.
 */

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { config } from "@/lib/config";
import { fechaHora } from "@/lib/formato";

interface Sesion {
  token: string;
  nivel: string;
  secciones: string[];
}

interface Caso {
  caso_id: string;
  codigo: string;
  asunto: string;
  estado: string;
  abierto_at: string | null;
  /** «pendiente» cuando se le pide que lo dé por bueno; «aceptado» si lo dio. */
  validacion_cliente?: string | null;
  /** La resolución del agente, sólo mientras espera su conformidad. */
  resolucion?: string | null;
}

interface Mensaje {
  id?: string;
  canal?: string;
  direccion?: string;
  cuerpo?: string;
  created_at?: string;
  interno?: boolean;
}

async function pedir<T>(
  ruta: string,
  token: string,
  opciones: { metodo?: string; cuerpo?: unknown } = {},
): Promise<T> {
  const respuesta = await fetch(`${config().apiBase}${ruta}`, {
    method: opciones.metodo ?? "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      ...(opciones.cuerpo === undefined
        ? {}
        : { "Content-Type": "application/json" }),
      ...(opciones.metodo && opciones.metodo !== "GET"
        ? { "Idempotency-Key": crypto.randomUUID() }
        : {}),
    },
    body:
      opciones.cuerpo === undefined
        ? undefined
        : JSON.stringify(opciones.cuerpo),
  });
  const texto = await respuesta.text();
  const cuerpo = texto ? JSON.parse(texto) : null;
  if (!respuesta.ok) {
    throw new Error(
      (cuerpo && (cuerpo.detail || cuerpo.title)) ||
        "No se ha podido completar la operación",
    );
  }
  return cuerpo as T;
}

export function Portal() {
  const [sesion, setSesion] = useState<Sesion | null>(null);

  // El enlace llega por correo con el token en la dirección. Se canjea solo: un
  // portal que además pide pulsar «entrar» añade un paso a quien ya ha hecho el
  // esfuerzo de abrir el correo.
  const token = new URLSearchParams(window.location.search).get("t") ?? "";

  if (!sesion) return <Entrada token={token} alEntrar={setSesion} />;
  return <Dentro sesion={sesion} alSalir={() => setSesion(null)} />;
}

function Entrada({
  token,
  alEntrar,
}: {
  token: string;
  alEntrar: (s: Sesion) => void;
}) {
  const [email, setEmail] = useState("");
  const [estado, setEstado] = useState<"" | "enviando" | "enviado">("");
  const [fallo, setFallo] = useState("");

  const canjear = useCallback(
    async (t: string) => {
      try {
        const respuesta = await fetch(
          `${config().apiBase}/api/v1/portal/sesion`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Idempotency-Key": crypto.randomUUID(),
            },
            body: JSON.stringify({ token: t }),
          },
        );
        if (!respuesta.ok) throw new Error("El enlace ya no vale. Pide otro.");
        alEntrar((await respuesta.json()) as Sesion);
      } catch (error) {
        setFallo(
          error instanceof Error
            ? error.message
            : "El enlace ya no vale. Pide otro.",
        );
      }
    },
    [alEntrar],
  );

  useEffect(() => {
    if (token) void canjear(token);
  }, [token, canjear]);

  async function pedirEnlace(evento: FormEvent) {
    evento.preventDefault();
    setEstado("enviando");
    setFallo("");
    try {
      await fetch(`${config().apiBase}/api/v1/portal/enlace`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ email }),
      });
    } finally {
      // Se dice lo mismo salga como salga: distinguirlo convertiría esto en un
      // comprobador de qué correos son clientes de esta empresa.
      setEstado("enviado");
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-4 py-10">
      <h1 className="mb-1 text-center text-grande font-semibold text-ink">
        Tu área de cliente
      </h1>
      <p className="mb-6 text-center text-dato text-ink-faint">
        Tus peticiones y lo que has hablado con nosotros.
      </p>

      <div className="card p-5">
        {estado === "enviado" ? (
          <p role="status" className="text-titulin text-ink">
            Si ese correo es de un cliente nuestro, le hemos mandado un enlace
            para entrar. El enlace vale una sola vez y caduca pronto.
          </p>
        ) : (
          <form onSubmit={pedirEnlace}>
            <label htmlFor="portal-email" className="label-base">
              Tu correo electrónico
            </label>
            <input
              id="portal-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-base mb-3"
              autoComplete="email"
            />
            {/* Sin contraseña a propósito: un cliente que entra tres veces al
                año no recuerda una contraseña, y lo que hace es reutilizar la
                del correo. El enlace de un solo uso evita las dos cosas. */}
            <button
              type="submit"
              disabled={estado === "enviando"}
              className="btn-primary w-full"
            >
              {estado === "enviando"
                ? "Enviando…"
                : "Mandarme un enlace para entrar"}
            </button>
          </form>
        )}
        {fallo ? (
          <p role="alert" className="mt-3 text-dato text-danger">
            {fallo}
          </p>
        ) : null}
      </div>
    </main>
  );
}

function Dentro({ sesion, alSalir }: { sesion: Sesion; alSalir: () => void }) {
  const [casos, setCasos] = useState<Caso[] | null>(null);
  const [hilo, setHilo] = useState<Mensaje[] | null>(null);
  const [fallo, setFallo] = useState("");

  const cargar = useCallback(async () => {
    try {
      const [c, h] = await Promise.all([
        pedir<Caso[]>("/api/v1/portal/mi/casos", sesion.token),
        pedir<Mensaje[]>("/api/v1/portal/mi/conversacion", sesion.token),
      ]);
      setCasos(c);
      setHilo(h);
    } catch (error) {
      setFallo(
        error instanceof Error ? error.message : "No se ha podido cargar",
      );
    }
  }, [sesion.token]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8">
      <header className="mb-6 flex items-baseline justify-between gap-3">
        <h1 className="text-grande font-semibold text-ink">
          Tu área de cliente
        </h1>
        <button
          type="button"
          onClick={alSalir}
          className="text-dato text-ink-faint hover:text-ink"
        >
          Salir
        </button>
      </header>

      {fallo ? (
        <p role="alert" className="mb-4 text-dato text-danger">
          {fallo}
        </p>
      ) : null}

      <NuevaPeticion sesion={sesion} alCrear={cargar} />
      <MisCasos casos={casos} sesion={sesion} alCambiar={cargar} />
      {/* Las demás secciones, **las que este acceso concede y no más**. El
          servidor ya dice cuáles en `sesion.secciones`, y lo dice justo para
          que el portal no pinte botones que luego dan 403.

          Hasta el 27-10-2026 esta pantalla enseñaba dos —peticiones y
          conversación— y las otras seis estaban publicadas y servidas sin que
          el cliente pudiera verlas: lo que su empresa tiene instalado, sus
          contratos, sus pedidos, los artículos que puede leer, la comunidad y
          quién más de su empresa tiene acceso. */}
      {sesion.secciones.map((seccion) =>
        // Los encargos no son una lista y ya: cada uno se abre para ver por
        // dónde va, así que tienen su propio bloque.
        seccion === "encargos" ? (
          <MisEncargos key={seccion} sesion={sesion} />
        ) : (
          <Seccion key={seccion} seccion={seccion} sesion={sesion} />
        ),
      )}
      {/* Y si además es proveedora, sus papeles: es la parte que más se usa de
          un portal de proveedor, porque perseguir certificados caducados es
          trabajo de alguien todos los meses y el único que puede resolverlo es
          el propio proveedor. */}
      <MisPapeles sesion={sesion} />
      <Conversacion sesion={sesion} hilo={hilo} alEscribir={cargar} />
    </main>
  );
}

/**
 * Qué enseña cada sección del portal, y de dónde.
 *
 * El mapa es ruta y rótulo, nada más: lo que se pinta de cada fila sale del
 * propio registro. Un componente por sección serían seis pantallas que dicen
 * lo mismo con otro nombre, y la que menos se mire será la que se quede sin
 * arreglar.
 *
 * `casos` y `conversacion` no están: tienen su propio sitio arriba, con el
 * formulario de pedir y el de escribir.
 */
const SECCIONES: Record<
  string,
  { ruta: string; titulo: string; vacio: string }
> = {
  conocimiento: {
    ruta: "/api/v1/portal/mi/conocimiento",
    titulo: "Ayuda",
    vacio: "Todavía no hay artículos publicados para ti.",
  },
  comunidad: {
    ruta: "/api/v1/portal/mi/comunidad",
    titulo: "Comunidad",
    vacio: "Nadie ha abierto ningún hilo todavía.",
  },
  activos: {
    ruta: "/api/v1/portal/mi/activos",
    titulo: "Lo que tenéis instalado",
    vacio: "No consta nada instalado a nombre de tu empresa.",
  },
  contratos: {
    ruta: "/api/v1/portal/mi/contratos",
    titulo: "Vuestros contratos",
    vacio: "No consta ningún contrato.",
  },
  pedidos: {
    ruta: "/api/v1/portal/mi/pedidos",
    titulo: "Vuestros pedidos",
    vacio: "No consta ningún pedido.",
  },
  contactos: {
    ruta: "/api/v1/portal/mi/contactos",
    titulo: "Quién más entra de tu empresa",
    vacio: "Eres la única persona con acceso.",
  },
};

/** Lo que se enseña de una fila, por orden de a qué se mira primero. */
const TITULO = [
  "nombre",
  "titulo",
  "asunto",
  "nombre_completo",
  "codigo",
  "referencia",
];
const DEBAJO = [
  "estado",
  "categoria",
  "tipo",
  "email",
  "numero_serie",
  "vence_at",
  "fecha",
];

function texto(fila: Record<string, unknown>, campos: string[]): string {
  for (const campo of campos) {
    const valor = fila[campo];
    if (typeof valor === "string" && valor.trim()) return valor;
    if (typeof valor === "number") return String(valor);
  }
  return "";
}

function Seccion({ seccion, sesion }: { seccion: string; sesion: Sesion }) {
  const definicion = SECCIONES[seccion];
  const [filas, setFilas] = useState<Record<string, unknown>[] | null>(null);
  const [fallo, setFallo] = useState("");
  const [vuelta, setVuelta] = useState(0);

  useEffect(() => {
    if (!definicion) return;
    let vivo = true;
    void pedir<unknown>(definicion.ruta, sesion.token)
      .then((datos) => {
        if (!vivo) return;
        // La API devuelve a veces la lista pelada y a veces un sobre con
        // `items`: se admiten las dos en vez de obligar a cada extremo a
        // cambiar, que es lo que dejaría media sección en blanco sin error.
        const lista = Array.isArray(datos)
          ? datos
          : ((datos as { items?: unknown[] })?.items ?? []);
        setFilas(lista as Record<string, unknown>[]);
      })
      .catch((error: unknown) => {
        if (!vivo) return;
        // Se dice. Una sección que el acceso concede y no se puede leer es un
        // problema de quien lo dio, y callarlo deja al cliente creyendo que no
        // tiene nada.
        setFallo(
          error instanceof Error ? error.message : "No se ha podido cargar",
        );
      });
    return () => {
      vivo = false;
    };
  }, [definicion, sesion.token, vuelta]);

  // Una sección que el servidor concede y este portal no sabe pintar no se
  // inventa: no se enseña nada. Enseñar un recuadro vacío con su rótulo se lee
  // como que no hay datos.
  if (!definicion) return null;

  return (
    <section className="card mb-4 p-4">
      <h2 className="mb-3 text-titulin font-medium uppercase tracking-wide text-ink-faint">
        {definicion.titulo}
      </h2>
      {seccion === "comunidad" ? (
        <PreguntarALaComunidad
          sesion={sesion}
          alPublicar={() => setVuelta((v) => v + 1)}
        />
      ) : null}
      {fallo ? (
        <p role="alert" className="text-dato text-danger">
          {fallo}
        </p>
      ) : filas === null ? (
        <p className="text-dato text-ink-faint">Cargando…</p>
      ) : filas.length === 0 ? (
        <p className="text-dato text-ink-faint">{definicion.vacio}</p>
      ) : (
        <ul className="lista-acotada space-y-2 pr-1">
          {filas.map((fila, i) => (
            <li
              key={String(fila.id ?? i)}
              className="rounded-lg bg-paper-sunk px-3 py-2"
            >
              <p className="text-titulin text-ink">
                {texto(fila, TITULO) || "—"}
              </p>
              {texto(fila, DEBAJO) ? (
                <p className="text-rotulo text-ink-faint">
                  {texto(fila, DEBAJO)}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface Encargo {
  id: string;
  referencia: string;
  referencia_transportista: string | null;
  proveedor: string;
  estado: string;
  prometido_para: string | null;
  completado_at: string | null;
  va_tarde: boolean;
}

interface Seguimiento {
  hitos: {
    estado: string;
    descripcion: string | null;
    lugar: string | null;
    at: string;
  }[];
  incidencias: { tipo: string; abierta: boolean; descripcion: string | null }[];
  va_tarde: boolean;
  sin_novedad: boolean;
}

/**
 * Los encargos de su empresa y por dónde va cada uno (CRM-00.04.05.06).
 *
 * El seguimiento para el cliente existía y sólo lo podía pedir un empleado
 * pasando la cuenta por la dirección: el cliente no llegaba. Aquí la cuenta
 * sale de su sesión, y lo que no es suyo da «no existe». Lo que se ve lo
 * decide el servidor: ni coste, ni proveedor alternativo, ni notas internas.
 */
function MisEncargos({ sesion }: { sesion: Sesion }) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Encargo[] | null>(null);
  const [fallo, setFallo] = useState("");
  const [abierto, setAbierto] = useState<string | null>(null);
  const [seguimiento, setSeguimiento] = useState<Seguimiento | null>(null);

  useEffect(() => {
    let vivo = true;
    void pedir<Encargo[]>("/api/v1/portal/mi/encargos", sesion.token)
      .then((datos) => vivo && setFilas(Array.isArray(datos) ? datos : []))
      .catch(
        (error: unknown) =>
          vivo &&
          // Sin `t` dentro: este efecto depende sólo del token. Con `t` en
          // las dependencias, una `t` nueva en cada render repite la
          // petición sin parar.
          setFallo(error instanceof Error ? error.message : " "),
      );
    return () => {
      vivo = false;
    };
  }, [sesion.token]);

  async function ver(id: string) {
    if (abierto === id) {
      setAbierto(null);
      return;
    }
    setAbierto(id);
    setSeguimiento(null);
    try {
      setSeguimiento(
        await pedir<Seguimiento>(
          `/api/v1/portal/mi/encargos/${id}/seguimiento`,
          sesion.token,
        ),
      );
    } catch (error) {
      setFallo(
        error instanceof Error ? error.message : t("portalEncargos.fallo"),
      );
    }
  }

  // Con la localización del tenant, como el resto del producto.
  const cuando = (valor: string | null) => (valor ? fechaHora(valor) : "");

  return (
    <section className="card mb-4 p-4" aria-labelledby="portal-encargos">
      <h2
        id="portal-encargos"
        className="mb-3 text-titulin font-medium uppercase tracking-wide text-ink-faint"
      >
        {t("portalEncargos.titulo")}
      </h2>
      {fallo ? (
        <p role="alert" className="text-dato text-danger">
          {fallo.trim() || t("portalEncargos.fallo")}
        </p>
      ) : filas === null ? (
        <p className="text-dato text-ink-faint">
          {t("portalEncargos.cargando")}
        </p>
      ) : filas.length === 0 ? (
        <p className="text-dato text-ink-faint">{t("portalEncargos.vacio")}</p>
      ) : (
        <ul className="lista-acotada space-y-2 pr-1">
          {filas.map((e) => (
            <li key={e.id} className="rounded-lg bg-paper-sunk px-3 py-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-titulin text-ink">
                  {e.referencia}
                  {e.referencia_transportista
                    ? ` · ${e.referencia_transportista}`
                    : ""}
                </p>
                <button
                  type="button"
                  className="text-dato text-ink-faint hover:text-ink"
                  aria-expanded={abierto === e.id}
                  onClick={() => void ver(e.id)}
                >
                  {abierto === e.id
                    ? t("portalEncargos.ocultar")
                    : t("portalEncargos.verSeguimiento")}
                </button>
              </div>
              <p className="text-rotulo text-ink-faint">
                {e.estado}
                {e.prometido_para
                  ? ` · ${t("portalEncargos.prometido", { cuando: cuando(e.prometido_para) })}`
                  : ""}
              </p>
              {e.va_tarde ? (
                <p className="text-rotulo text-warning">
                  {t("portalEncargos.vaTarde")}
                </p>
              ) : null}
              {abierto === e.id ? (
                <div role="status" className="mt-2">
                  {seguimiento === null ? (
                    <p className="text-rotulo text-ink-faint">
                      {t("portalEncargos.cargando")}
                    </p>
                  ) : (
                    <>
                      {seguimiento.hitos.length === 0 ? (
                        <p className="text-rotulo text-ink-faint">
                          {t("portalEncargos.sinHitos")}
                        </p>
                      ) : (
                        <ol className="space-y-1">
                          {seguimiento.hitos.map((h, i) => (
                            <li
                              key={`${h.at}-${i}`}
                              className="text-rotulo text-ink"
                            >
                              {cuando(h.at)} · {h.descripcion || h.estado}
                              {h.lugar ? ` · ${h.lugar}` : ""}
                            </li>
                          ))}
                        </ol>
                      )}
                      {seguimiento.incidencias.map((inc, i) => (
                        <p
                          key={`${inc.tipo}-${i}`}
                          className={
                            inc.abierta
                              ? "text-rotulo text-warning"
                              : "text-rotulo text-ink-faint"
                          }
                        >
                          {inc.abierta
                            ? t("portalEncargos.incidenciaAbierta", {
                                tipo: inc.descripcion || inc.tipo,
                              })
                            : t("portalEncargos.incidenciaCerrada", {
                                tipo: inc.descripcion || inc.tipo,
                              })}
                        </p>
                      ))}
                      {seguimiento.sin_novedad ? (
                        <p className="text-rotulo text-warning">
                          {t("portalEncargos.sinNovedad")}
                        </p>
                      ) : null}
                    </>
                  )}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function NuevaPeticion({
  sesion,
  alCrear,
}: {
  sesion: Sesion;
  alCrear: () => void;
}) {
  const [asunto, setAsunto] = useState("");
  const [descripcion, setDescripcion] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [hecho, setHecho] = useState("");

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (!asunto.trim()) return;
    setEnviando(true);
    try {
      const caso = await pedir<{ codigo: string }>(
        "/api/v1/portal/mi/casos",
        sesion.token,
        {
          metodo: "POST",
          cuerpo: { asunto: asunto.trim(), descripcion: descripcion.trim() },
        },
      );
      // Se enseña el código: es con lo que el cliente se va a referir a esto
      // cuando llame por teléfono, y sin él tiene que describirlo otra vez.
      setHecho(caso.codigo);
      setAsunto("");
      setDescripcion("");
      alCrear();
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="card mb-4 p-4">
      <h2 className="mb-3 text-titulin font-medium uppercase tracking-wide text-ink-faint">
        Pedir algo
      </h2>
      {/* `role="status"` y no un párrafo a secas: quien no ve la pantalla
          necesita enterarse de que la petición ha entrado y con qué código, que
          es justo lo que hay que decir por teléfono después. */}
      <p role="status" className="mb-3 text-titulin text-success">
        {hecho ? `Recibido. Tu petición es la ${hecho}.` : ""}
      </p>
      <form onSubmit={enviar}>
        <input
          value={asunto}
          onChange={(e) => setAsunto(e.target.value)}
          placeholder="Qué necesitas"
          aria-label="Qué necesitas"
          className="input-base mb-2"
        />
        <textarea
          value={descripcion}
          onChange={(e) => setDescripcion(e.target.value)}
          placeholder="Cuéntanoslo con detalle (opcional)"
          aria-label="Cuéntanoslo con detalle"
          rows={3}
          className="input-base mb-2"
        />
        <button
          type="submit"
          disabled={enviando || !asunto.trim()}
          className="btn-primary"
        >
          {enviando ? "Enviando…" : "Enviar la petición"}
        </button>
      </form>
    </section>
  );
}

function MisCasos({
  casos,
  sesion,
  alCambiar,
}: {
  casos: Caso[] | null;
  sesion: Sesion;
  alCambiar: () => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="card mb-4 p-4">
      <h2 className="mb-3 text-titulin font-medium uppercase tracking-wide text-ink-faint">
        Tus peticiones
      </h2>
      {casos === null ? (
        <p className="text-dato text-ink-faint">Cargando…</p>
      ) : casos.length === 0 ? (
        <p className="text-dato text-ink-faint">Todavía no has pedido nada.</p>
      ) : (
        <ul className="lista-acotada space-y-2 pr-1">
          {casos.map((c) => (
            <li key={c.caso_id} className="rounded-lg bg-paper-sunk px-3 py-2">
              <p className="text-titulin text-ink">{c.asunto}</p>
              <p className="text-rotulo text-ink-faint">
                {c.codigo} · {c.estado}
                {c.validacion_cliente === "aceptado"
                  ? ` · ${t("portalCierre.aceptado")}`
                  : ""}
              </p>
              {c.validacion_cliente === "pendiente" ? (
                <ValidarCierre
                  caso={c}
                  sesion={sesion}
                  alTerminar={alCambiar}
                />
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * El cliente da por bueno el cierre, o no (CRM-04.01.01.09).
 *
 * El agente podía cerrar «pendiente de que el cliente lo dé por bueno» y aquí
 * no había por dónde contestar: el caso se quedaba pendiente para siempre.
 * «No» pide qué sigue pasando, porque es lo primero que leerá quien lo retome.
 */
function ValidarCierre({
  caso,
  sesion,
  alTerminar,
}: {
  caso: Caso;
  sesion: Sesion;
  alTerminar: () => void;
}) {
  const { t } = useTranslation();
  const [diciendoQueNo, setDiciendoQueNo] = useState(false);
  const [comentario, setComentario] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState("");

  async function contestar(conforme: boolean) {
    setEnviando(true);
    setFallo("");
    try {
      await pedir(
        `/api/v1/portal/mi/casos/${caso.caso_id}/validar-cierre`,
        sesion.token,
        { metodo: "POST", cuerpo: { conforme, comentario } },
      );
      alTerminar();
    } catch (error) {
      setFallo(
        error instanceof Error ? error.message : t("portalCierre.fallo"),
      );
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="mt-2 border-t border-ink-dim/30 pt-2">
      <p className="text-dato font-medium text-ink">
        {t("portalCierre.pregunta")}
      </p>
      {caso.resolucion ? (
        <p className="mt-1 text-dato text-ink-muted">
          <span className="text-rotulo text-ink-faint">
            {t("portalCierre.resolucion")}:{" "}
          </span>
          {caso.resolucion}
        </p>
      ) : null}
      {diciendoQueNo ? (
        <form
          className="mt-2 flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void contestar(false);
          }}
        >
          <label
            className="text-rotulo text-ink-faint"
            htmlFor={`no-${caso.caso_id}`}
          >
            {t("portalCierre.queSigue")}
          </label>
          <textarea
            id={`no-${caso.caso_id}`}
            value={comentario}
            onChange={(e) => setComentario(e.target.value)}
            required
            rows={3}
            className="input-base"
            aria-describedby={`no-${caso.caso_id}-ayuda`}
          />
          <p
            id={`no-${caso.caso_id}-ayuda`}
            className="text-rotulo text-ink-faint"
          >
            {t("portalCierre.queSigueAyuda")}
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              disabled={enviando || !comentario.trim()}
              className="btn-primary"
            >
              {enviando
                ? t("portalCierre.enviando")
                : t("portalCierre.enviarNo")}
            </button>
            <button
              type="button"
              onClick={() => setDiciendoQueNo(false)}
              className="btn-secondary"
            >
              {t("portalCierre.cancelar")}
            </button>
          </div>
        </form>
      ) : (
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={enviando}
            onClick={() => void contestar(true)}
            className="btn-primary"
          >
            {enviando ? t("portalCierre.enviando") : t("portalCierre.si")}
          </button>
          <button
            type="button"
            disabled={enviando}
            onClick={() => setDiciendoQueNo(true)}
            className="btn-secondary"
          >
            {t("portalCierre.no")}
          </button>
        </div>
      )}
      {fallo ? (
        <p role="alert" className="mt-2 text-dato text-danger">
          {fallo}
        </p>
      ) : null}
    </div>
  );
}

function Conversacion({
  sesion,
  hilo,
  alEscribir,
}: {
  sesion: Sesion;
  hilo: Mensaje[] | null;
  alEscribir: () => void;
}) {
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (!texto.trim()) return;
    setEnviando(true);
    try {
      await pedir("/api/v1/portal/mi/conversacion", sesion.token, {
        metodo: "POST",
        cuerpo: { texto: texto.trim() },
      });
      setTexto("");
      alEscribir();
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="card p-4">
      <h2 className="mb-3 text-titulin font-medium uppercase tracking-wide text-ink-faint">
        Hablar con nosotros
      </h2>
      {hilo === null ? (
        <p className="mb-3 text-dato text-ink-faint">Cargando…</p>
      ) : hilo.length === 0 ? (
        <p className="mb-3 text-dato text-ink-faint">
          Aquí aparecerá lo que hablemos.
        </p>
      ) : (
        <ul className="lista-acotada mb-3 space-y-2 pr-1">
          {hilo.map((m, i) => {
            const mio = m.direccion === "entrante";
            return (
              <li
                key={m.id ?? i}
                className={`max-w-[85%] rounded-xl px-3 py-2 text-titulin ${
                  mio
                    ? "ml-auto bg-accent/10 text-ink"
                    : "bg-paper-sunk text-ink"
                }`}
              >
                <p className="mb-0.5 text-rotulo text-ink-faint">
                  {mio ? "Tú" : "Nosotros"}
                </p>
                {m.cuerpo}
              </li>
            );
          })}
        </ul>
      )}
      <form onSubmit={enviar} className="flex gap-2">
        <input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Escribe aquí"
          aria-label="Escribe aquí"
          className="input-base"
        />
        <button
          type="submit"
          disabled={enviando || !texto.trim()}
          className="btn-primary shrink-0"
        >
          Enviar
        </button>
      </form>
    </section>
  );
}

interface Documento {
  clave?: string;
  nombre?: string;
  /** Cuándo caduca, tal como lo llama el estado documental. */
  vence?: string | null;
  dias?: number;
}

interface Homologacion {
  id: string;
  categoria: string;
  estado: string;
  valida_hasta: string | null;
}

function MisPapeles({ sesion }: { sesion: Sesion }) {
  const [esProveedor, setEsProveedor] = useState(false);
  const [documentos, setDocumentos] = useState<Documento[] | null>(null);
  // Para qué está homologado y hasta cuándo. Sin esto el proveedor sabía qué
  // papel le caducaba pero no QUÉ dejaba de poder servir si caducaba.
  const [homologaciones, setHomologaciones] = useState<Homologacion[] | null>(
    null,
  );
  const [subiendo, setSubiendo] = useState(false);
  const [hecho, setHecho] = useState("");
  const [clave, setClave] = useState("");
  const [referencia, setReferencia] = useState("");
  const [hasta, setHasta] = useState("");

  const cargar = useCallback(async () => {
    try {
      const quien = await pedir<{ es_proveedor: boolean }>(
        "/api/v1/proveedores/mi/resumen",
        sesion.token,
      );
      setEsProveedor(quien.es_proveedor);
      if (!quien.es_proveedor) return;
      const estado = await pedir<{
        vencidos?: Documento[];
        por_vencer?: Documento[];
      }>("/api/v1/proveedores/mi/documentos", sesion.token);
      setDocumentos([...(estado.vencidos ?? []), ...(estado.por_vencer ?? [])]);
      // Aparte y sin tumbar lo anterior: que no se puedan leer las
      // homologaciones no puede esconder qué papel está vencido.
      pedir<Homologacion[]>(
        "/api/v1/proveedores/mi/homologaciones",
        sesion.token,
      )
        .then(setHomologaciones)
        .catch(() => setHomologaciones([]));
    } catch {
      // Quien no es proveedor recibe un error aquí, y eso no es un fallo que
      // haya que enseñarle: sencillamente esta sección no es para él.
      setEsProveedor(false);
    }
  }, [sesion.token]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  if (!esProveedor) return null;

  async function subir(evento: FormEvent) {
    evento.preventDefault();
    if (!clave.trim() || !referencia.trim()) return;
    setSubiendo(true);
    try {
      await pedir("/api/v1/proveedores/mi/documentos", sesion.token, {
        metodo: "POST",
        cuerpo: {
          clave: clave.trim(),
          nombre: clave.trim(),
          referencia: referencia.trim(),
          valido_hasta: hasta || null,
        },
      });
      setHecho("Recibido. Lo tenemos actualizado.");
      setClave("");
      setReferencia("");
      setHasta("");
      await cargar();
    } finally {
      setSubiendo(false);
    }
  }

  return (
    <section className="card mb-4 p-4">
      <h2 className="mb-3 text-titulin font-medium uppercase tracking-wide text-ink-faint">
        Tus papeles con nosotros
      </h2>
      {documentos === null ? (
        <p className="mb-3 text-dato text-ink-faint">Cargando…</p>
      ) : documentos.length === 0 ? (
        <p className="mb-3 text-dato text-ink-faint">
          No hay nada pendiente de renovar.
        </p>
      ) : (
        <ul className="lista-acotada mb-3 space-y-1.5 pr-1">
          {documentos.map((d, i) => (
            <li
              key={d.clave ?? i}
              className="rounded-lg bg-paper-sunk px-3 py-2 text-titulin text-ink"
            >
              {d.nombre || d.clave}
              <span className="ml-2 text-rotulo text-ink-faint">
                {d.vence
                  ? (d.dias ?? 0) < 0
                    ? `venció el ${d.vence}`
                    : `vence el ${d.vence}`
                  : "sin fecha"}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3 className="mb-2 text-titulin font-medium text-ink">
        Para qué estás homologado
      </h3>
      {homologaciones === null ? (
        <p className="mb-3 text-dato text-ink-faint">Cargando…</p>
      ) : homologaciones.length === 0 ? (
        <p className="mb-3 text-dato text-ink-faint">
          No consta ninguna homologación a tu nombre.
        </p>
      ) : (
        <ul className="lista-acotada mb-3 space-y-1.5 pr-1">
          {homologaciones.map((h) => (
            <li
              key={h.id}
              className="flex flex-wrap items-baseline gap-x-2 rounded-lg bg-paper-sunk px-3 py-2 text-titulin text-ink"
            >
              <span>{h.categoria}</span>
              <span className="chip-dato">{h.estado}</span>
              <span className="text-rotulo text-ink-faint">
                {h.valida_hasta
                  ? `hasta el ${h.valida_hasta}`
                  : "sin fecha de fin"}
              </span>
            </li>
          ))}
        </ul>
      )}

      <p role="status" className="mb-2 text-dato text-success">
        {hecho}
      </p>
      <form onSubmit={subir} className="grid gap-2 sm:grid-cols-3">
        <input
          value={clave}
          onChange={(e) => setClave(e.target.value)}
          placeholder="Qué papel es"
          aria-label="Qué papel es"
          className="input-base"
        />
        <input
          value={referencia}
          onChange={(e) => setReferencia(e.target.value)}
          placeholder="Referencia o enlace"
          aria-label="Referencia o enlace"
          className="input-base"
        />
        <input
          type="date"
          value={hasta}
          onChange={(e) => setHasta(e.target.value)}
          aria-label="Válido hasta"
          className="input-base"
        />
        <button
          type="submit"
          disabled={subiendo || !clave.trim() || !referencia.trim()}
          className="btn-primary sm:col-span-3"
        >
          {subiendo ? "Enviando…" : "Mandar el papel renovado"}
        </button>
      </form>
    </section>
  );
}

/**
 * Preguntar en la comunidad (CRM-04.03.02.04).
 *
 * La comunidad se leía y no se podía escribir: la ruta para que el cliente
 * abra un hilo existía y el portal no la ofrecía (medido el 10-11-2026). Lo
 * que se pregunta entra en moderación antes de que lo vea nadie más.
 */
function PreguntarALaComunidad({
  sesion,
  alPublicar,
}: {
  sesion: Sesion;
  alPublicar: () => void;
}) {
  const { t } = useTranslation();
  const [titulo, setTitulo] = useState("");
  const [cuerpo, setCuerpo] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso] = useState("");

  async function publicar(evento: FormEvent) {
    evento.preventDefault();
    if (!titulo.trim()) return;
    setEnviando(true);
    setAviso("");
    try {
      await pedir("/api/v1/portal/mi/comunidad", sesion.token, {
        metodo: "POST",
        cuerpo: { titulo, cuerpo },
      });
      setTitulo("");
      setCuerpo("");
      setAviso(t("portalComunidad.enviada"));
      alPublicar();
    } catch (error) {
      setAviso(
        error instanceof Error ? error.message : t("portalComunidad.fallo"),
      );
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={publicar} className="mb-3 flex flex-col gap-2">
      <input
        value={titulo}
        onChange={(e) => setTitulo(e.target.value)}
        placeholder={t("portalComunidad.titulo")}
        aria-label={t("portalComunidad.titulo")}
        className="input-base"
      />
      <textarea
        value={cuerpo}
        onChange={(e) => setCuerpo(e.target.value)}
        placeholder={t("portalComunidad.cuerpo")}
        aria-label={t("portalComunidad.cuerpo")}
        rows={2}
        className="input-base"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="submit"
          disabled={enviando || !titulo.trim()}
          className="btn-secondary"
        >
          {enviando
            ? t("portalComunidad.enviando")
            : t("portalComunidad.publicar")}
        </button>
        {aviso ? (
          <span role="status" className="text-rotulo text-ink-muted">
            {aviso}
          </span>
        ) : null}
      </div>
    </form>
  );
}
