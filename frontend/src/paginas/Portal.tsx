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

import { config } from "@/lib/config";

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
      ...(opciones.cuerpo === undefined ? {} : { "Content-Type": "application/json" }),
      ...(opciones.metodo && opciones.metodo !== "GET"
        ? { "Idempotency-Key": crypto.randomUUID() }
        : {}),
    },
    body: opciones.cuerpo === undefined ? undefined : JSON.stringify(opciones.cuerpo),
  });
  const texto = await respuesta.text();
  const cuerpo = texto ? JSON.parse(texto) : null;
  if (!respuesta.ok) {
    throw new Error(
      (cuerpo && (cuerpo.detail || cuerpo.title)) || "No se ha podido completar la operación",
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

function Entrada({ token, alEntrar }: { token: string; alEntrar: (s: Sesion) => void }) {
  const [email, setEmail] = useState("");
  const [estado, setEstado] = useState<"" | "enviando" | "enviado">("");
  const [fallo, setFallo] = useState("");

  const canjear = useCallback(
    async (t: string) => {
      try {
        const respuesta = await fetch(`${config().apiBase}/api/v1/portal/sesion`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify({ token: t }),
        });
        if (!respuesta.ok) throw new Error("El enlace ya no vale. Pide otro.");
        alEntrar((await respuesta.json()) as Sesion);
      } catch (error) {
        setFallo(error instanceof Error ? error.message : "El enlace ya no vale. Pide otro.");
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
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
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
      <h1 className="mb-1 text-center text-xl font-semibold text-ink">Tu área de cliente</h1>
      <p className="mb-6 text-center text-2xs text-ink-faint">
        Tus peticiones y lo que has hablado con nosotros.
      </p>

      <div className="card p-5">
        {estado === "enviado" ? (
          <p role="status" className="text-xs text-ink">
            Si ese correo es de un cliente nuestro, le hemos mandado un enlace para entrar. El
            enlace vale una sola vez y caduca pronto.
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
            <button type="submit" disabled={estado === "enviando"} className="btn-primary w-full">
              {estado === "enviando" ? "Enviando…" : "Mandarme un enlace para entrar"}
            </button>
          </form>
        )}
        {fallo ? (
          <p role="alert" className="mt-3 text-2xs text-danger">
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
      setFallo(error instanceof Error ? error.message : "No se ha podido cargar");
    }
  }, [sesion.token]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8">
      <header className="mb-6 flex items-baseline justify-between gap-3">
        <h1 className="text-lg font-semibold text-ink">Tu área de cliente</h1>
        <button type="button" onClick={alSalir} className="text-2xs text-ink-faint hover:text-ink">
          Salir
        </button>
      </header>

      {fallo ? (
        <p role="alert" className="mb-4 text-2xs text-danger">
          {fallo}
        </p>
      ) : null}

      <NuevaPeticion sesion={sesion} alCrear={cargar} />
      <MisCasos casos={casos} />
      {/* Las demás secciones, **las que este acceso concede y no más**. El
          servidor ya dice cuáles en `sesion.secciones`, y lo dice justo para
          que el portal no pinte botones que luego dan 403.

          Hasta el 27-10-2026 esta pantalla enseñaba dos —peticiones y
          conversación— y las otras seis estaban publicadas y servidas sin que
          el cliente pudiera verlas: lo que su empresa tiene instalado, sus
          contratos, sus pedidos, los artículos que puede leer, la comunidad y
          quién más de su empresa tiene acceso. */}
      {sesion.secciones.map((seccion) => (
        <Seccion key={seccion} seccion={seccion} sesion={sesion} />
      ))}
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
const SECCIONES: Record<string, { ruta: string; titulo: string; vacio: string }> = {
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
const TITULO = ["nombre", "titulo", "asunto", "nombre_completo", "codigo", "referencia"];
const DEBAJO = ["estado", "categoria", "tipo", "email", "numero_serie", "vence_at", "fecha"];

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
        setFallo(error instanceof Error ? error.message : "No se ha podido cargar");
      });
    return () => {
      vivo = false;
    };
  }, [definicion, sesion.token]);

  // Una sección que el servidor concede y este portal no sabe pintar no se
  // inventa: no se enseña nada. Enseñar un recuadro vacío con su rótulo se lee
  // como que no hay datos.
  if (!definicion) return null;

  return (
    <section className="card mb-4 p-4">
      <h2 className="mb-3 text-xs font-medium uppercase tracking-wide text-ink-faint">
        {definicion.titulo}
      </h2>
      {fallo ? (
        <p role="alert" className="text-2xs text-danger">
          {fallo}
        </p>
      ) : filas === null ? (
        <p className="text-2xs text-ink-faint">Cargando…</p>
      ) : filas.length === 0 ? (
        <p className="text-2xs text-ink-faint">{definicion.vacio}</p>
      ) : (
        <ul className="space-y-2">
          {filas.map((fila, i) => (
            <li key={String(fila.id ?? i)} className="rounded-lg bg-paper-sunk px-3 py-2">
              <p className="text-xs text-ink">{texto(fila, TITULO) || "—"}</p>
              {texto(fila, DEBAJO) ? (
                <p className="text-3xs text-ink-faint">{texto(fila, DEBAJO)}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function NuevaPeticion({ sesion, alCrear }: { sesion: Sesion; alCrear: () => void }) {
  const [asunto, setAsunto] = useState("");
  const [descripcion, setDescripcion] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [hecho, setHecho] = useState("");

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (!asunto.trim()) return;
    setEnviando(true);
    try {
      const caso = await pedir<{ codigo: string }>("/api/v1/portal/mi/casos", sesion.token, {
        metodo: "POST",
        cuerpo: { asunto: asunto.trim(), descripcion: descripcion.trim() },
      });
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
      <h2 className="mb-3 text-xs font-medium uppercase tracking-wide text-ink-faint">
        Pedir algo
      </h2>
      {/* `role="status"` y no un párrafo a secas: quien no ve la pantalla
          necesita enterarse de que la petición ha entrado y con qué código, que
          es justo lo que hay que decir por teléfono después. */}
      <p role="status" className="mb-3 text-xs text-success">
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
        <button type="submit" disabled={enviando || !asunto.trim()} className="btn-primary">
          {enviando ? "Enviando…" : "Enviar la petición"}
        </button>
      </form>
    </section>
  );
}

function MisCasos({ casos }: { casos: Caso[] | null }) {
  return (
    <section className="card mb-4 p-4">
      <h2 className="mb-3 text-xs font-medium uppercase tracking-wide text-ink-faint">
        Tus peticiones
      </h2>
      {casos === null ? (
        <p className="text-2xs text-ink-faint">Cargando…</p>
      ) : casos.length === 0 ? (
        <p className="text-2xs text-ink-faint">Todavía no has pedido nada.</p>
      ) : (
        <ul className="space-y-2">
          {casos.map((c) => (
            <li key={c.caso_id} className="rounded-lg bg-paper-sunk px-3 py-2">
              <p className="text-xs text-ink">{c.asunto}</p>
              <p className="text-3xs text-ink-faint">
                {c.codigo} · {c.estado}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
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
      <h2 className="mb-3 text-xs font-medium uppercase tracking-wide text-ink-faint">
        Hablar con nosotros
      </h2>
      {hilo === null ? (
        <p className="mb-3 text-2xs text-ink-faint">Cargando…</p>
      ) : hilo.length === 0 ? (
        <p className="mb-3 text-2xs text-ink-faint">Aquí aparecerá lo que hablemos.</p>
      ) : (
        <ul className="mb-3 space-y-2">
          {hilo.map((m, i) => {
            const mio = m.direccion === "entrante";
            return (
              <li
                key={m.id ?? i}
                className={`max-w-[85%] rounded-xl px-3 py-2 text-xs ${
                  mio ? "ml-auto bg-accent/10 text-ink" : "bg-paper-sunk text-ink"
                }`}
              >
                <p className="mb-0.5 text-3xs text-ink-faint">{mio ? "Tú" : "Nosotros"}</p>
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
        <button type="submit" disabled={enviando || !texto.trim()} className="btn-primary shrink-0">
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

function MisPapeles({ sesion }: { sesion: Sesion }) {
  const [esProveedor, setEsProveedor] = useState(false);
  const [documentos, setDocumentos] = useState<Documento[] | null>(null);
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
      const estado = await pedir<{ vencidos?: Documento[]; por_vencer?: Documento[] }>(
        "/api/v1/proveedores/mi/documentos",
        sesion.token,
      );
      setDocumentos([...(estado.vencidos ?? []), ...(estado.por_vencer ?? [])]);
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
      <h2 className="mb-3 text-xs font-medium uppercase tracking-wide text-ink-faint">
        Tus papeles con nosotros
      </h2>
      {documentos === null ? (
        <p className="mb-3 text-2xs text-ink-faint">Cargando…</p>
      ) : documentos.length === 0 ? (
        <p className="mb-3 text-2xs text-ink-faint">No hay nada pendiente de renovar.</p>
      ) : (
        <ul className="mb-3 space-y-1.5">
          {documentos.map((d, i) => (
            <li key={d.clave ?? i} className="rounded-lg bg-paper-sunk px-3 py-2 text-xs text-ink">
              {d.nombre || d.clave}
              <span className="ml-2 text-3xs text-ink-faint">
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

      <p role="status" className="mb-2 text-2xs text-success">
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
