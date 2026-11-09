/**
 * Probar la API contra un sandbox con datos sintéticos (CRM-00.02.01.15).
 *
 * Hasta el 09-11-2026 `POST /integracion/sandbox` devolvía un diccionario y no
 * creaba nada, y no había dónde probar una llamada. Aquí se crea el sandbox de
 * verdad —un tenant hijo, datos generados del contrato y una clave de API que
 * sólo abre ese tenant— y debajo está la consola: método, una ruta del contrato
 * publicado, cuerpo, y la respuesta tal cual.
 *
 * La consola llama **con la clave del sandbox y sin la sesión**: es lo que
 * prueba la integración que se va a escribir, y lo que garantiza que lo que se
 * rompa aquí se rompe en datos inventados. Comprobado el 09-11-2026 con pruebas
 * contra `party` (lo generado del contrato se acepta con 201) y con un doble de
 * los servicios (todo lo de dentro, clave incluida, va al tenant del sandbox).
 *
 * El secreto de la clave se guarda sólo en memoria: se enseña una vez, como
 * cualquier clave, y se puede pegar una que ya se tenga.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { filas as filasDe, llamar } from "@/lib/api";
import { config } from "@/lib/config";
import { contratoDe, type Documento } from "@/lib/contrato";
import { fechaHora } from "@/lib/formato";

interface ObjetoGenerado {
  objeto: string;
  servicio?: string;
  creadas: number;
  pedidas?: number;
  error: string;
}

interface SandboxCreado {
  sandbox_id: string;
  tenant_sandbox_id: string;
  objetos: ObjetoGenerado[];
  filas: number;
  caduca_at: string;
  alcance: string;
  credencial: {
    secreto?: string;
    prefijo?: string;
    expira_at?: string | null;
    error?: string;
  };
}

interface Respuesta {
  estado: number;
  ms: number;
  cuerpo: string;
}

const METODOS = ["GET", "POST", "PATCH", "PUT", "DELETE"] as const;

export function SandboxDeApi() {
  const { t } = useTranslation();
  const [nombre, setNombre] = useState(t("sandboxApi.nombrePorDefecto"));
  const [objetos, setObjetos] = useState("");
  const [filas, setFilas] = useState("");
  const [creando, setCreando] = useState(false);
  const [creado, setCreado] = useState<SandboxCreado | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const [clave, setClave] = useState("");
  const [servicios, setServicios] = useState<string[]>([]);
  const [servicio, setServicio] = useState("party");
  const [contrato, setContrato] = useState<Documento | null>(null);
  const [metodo, setMetodo] = useState<string>("GET");
  const [ruta, setRuta] = useState("");
  const [cuerpo, setCuerpo] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [respuesta, setRespuesta] = useState<Respuesta | null>(null);

  useEffect(() => {
    llamar<unknown>("/api/v1/servicios")
      .then((r) =>
        setServicios(
          filasDe<{ servicio: string }>(r.datos)
            .map((s) => s.servicio)
            .filter(Boolean),
        ),
      )
      .catch(() => setServicios([]));
  }, []);

  useEffect(() => {
    setContrato(null);
    void contratoDe(servicio).then(setContrato);
  }, [servicio]);

  // Las rutas del contrato que admiten el método elegido: ofrecer una que no
  // lo admite es invitar a un 405 que no prueba nada.
  const rutas = useMemo(
    () =>
      Object.entries(contrato?.paths ?? {})
        .filter(([, ops]) =>
          Boolean((ops as Record<string, unknown>)[metodo.toLowerCase()]),
        )
        .map(([p]) => p)
        .sort(),
    [contrato, metodo],
  );

  async function crear() {
    setCreando(true);
    setFallo(null);
    try {
      const r = await llamar<SandboxCreado>("/api/v1/integracion/sandbox", {
        metodo: "POST",
        cuerpo: {
          nombre,
          objetos: objetos
            .split(",")
            .map((o) => o.trim())
            .filter(Boolean),
          ...(Number(filas) > 0 ? { filas_por_objeto: Number(filas) } : {}),
        },
      });
      setCreado(r.datos);
      if (r.datos.credencial.secreto) setClave(r.datos.credencial.secreto);
    } catch (e) {
      setFallo(e);
    } finally {
      setCreando(false);
    }
  }

  async function enviar() {
    setEnviando(true);
    setRespuesta(null);
    const inicio = performance.now();
    try {
      const conCuerpo =
        metodo !== "GET" && metodo !== "DELETE" && cuerpo.trim();
      // Sin `credentials`: la llamada la hace la clave del sandbox, y con la
      // cookie de la sesión delante se estaría probando como uno mismo, en la
      // empresa real.
      const r = await fetch(`${config().apiBase}${ruta}`, {
        method: metodo,
        credentials: "omit",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${clave.trim()}`,
          ...(conCuerpo ? { "Content-Type": "application/json" } : {}),
          ...(metodo !== "GET"
            ? { "Idempotency-Key": crypto.randomUUID() }
            : {}),
        },
        body: conCuerpo ? cuerpo : undefined,
      });
      const texto = await r.text();
      let bonito = texto;
      try {
        bonito = JSON.stringify(JSON.parse(texto), null, 2);
      } catch {
        // No era JSON: se enseña tal cual llegó.
      }
      setRespuesta({
        estado: r.status,
        ms: Math.round(performance.now() - inicio),
        cuerpo: bonito,
      });
    } catch (e) {
      setRespuesta({
        estado: 0,
        ms: Math.round(performance.now() - inicio),
        cuerpo: String(e),
      });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <>
      <CabeceraPagina
        icono="terminal"
        titulo={t("sandboxApi.titulo")}
        entradilla={t("sandboxApi.entradilla")}
      />

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("sandboxApi.crear")}</h2>
        <p className="mb-3 text-rotulo text-ink-faint">
          {t("sandboxApi.crearAyuda")}
        </p>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-dato text-ink-muted">
            {t("sandboxApi.nombre")}
            <input
              className="input-base mt-1 w-full"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
            />
          </label>
          <label className="text-dato text-ink-muted">
            {t("sandboxApi.objetos")}
            <input
              className="input-base mt-1 w-full"
              placeholder={t("sandboxApi.objetosAyuda")}
              value={objetos}
              onChange={(e) => setObjetos(e.target.value)}
            />
          </label>
          <label className="text-dato text-ink-muted">
            {t("sandboxApi.filas")}
            <input
              type="number"
              min={1}
              max={500}
              className="input-base mt-1 w-full"
              placeholder={t("sandboxApi.filasAyuda")}
              value={filas}
              onChange={(e) => setFilas(e.target.value)}
            />
          </label>
        </div>
        <button
          type="button"
          className="btn-primary mt-3"
          disabled={creando || !nombre.trim()}
          onClick={() => void crear()}
        >
          <Icono nombre="science" tamano="sm" />
          {creando ? t("sandboxApi.creando") : t("sandboxApi.crearBoton")}
        </button>
        <div role="status" className="mt-3">
          {fallo ? <Fallo error={fallo} /> : null}
          {creado ? (
            <>
              <p className="text-dato text-success">
                {t("sandboxApi.creado", {
                  filas: creado.filas,
                  caduca: fechaHora(creado.caduca_at),
                })}
              </p>
              <p className="text-rotulo text-ink-muted">{creado.alcance}</p>
            </>
          ) : null}
        </div>
        {creado ? (
          <>
            <Rejilla
              titulo={t("sandboxApi.datos")}
              cabeceras={[
                t("sandboxApi.objeto"),
                t("sandboxApi.servicio"),
                t("sandboxApi.creadas"),
                t("sandboxApi.error"),
              ]}
            >
              {creado.objetos.map((o) => (
                <tr
                  key={o.objeto}
                  className="border-b border-ink-dim/30 last:border-0"
                >
                  <Casilla>{o.objeto}</Casilla>
                  <Casilla>{o.servicio ?? "—"}</Casilla>
                  <Casilla className="text-right">
                    {o.pedidas ? `${o.creadas} / ${o.pedidas}` : o.creadas}
                  </Casilla>
                  <Casilla className="text-rotulo text-danger">
                    {o.error}
                  </Casilla>
                </tr>
              ))}
            </Rejilla>
            {creado.credencial.secreto ? (
              <div className="mt-3 rounded border border-warning/40 p-3">
                <p className="section-label mb-1">
                  {t("sandboxApi.credencial")}
                </p>
                <code className="block break-all text-dato text-ink">
                  {creado.credencial.secreto}
                </code>
                <p className="mt-1 text-rotulo text-ink-muted">
                  {t("sandboxApi.soloUnaVez")}
                </p>
              </div>
            ) : (
              <p className="mt-3 text-dato text-danger">
                {t("sandboxApi.sinCredencial", {
                  motivo: creado.credencial.error ?? "",
                })}
              </p>
            )}
          </>
        ) : null}
      </section>

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("sandboxApi.consola")}</h2>
        <p className="mb-3 text-rotulo text-ink-faint">
          {t("sandboxApi.consolaAyuda")}
        </p>
        <label className="block text-dato text-ink-muted">
          {t("sandboxApi.clave")}
          <input
            type="password"
            autoComplete="off"
            className="input-base mt-1 w-full"
            placeholder="crm_…"
            value={clave}
            onChange={(e) => setClave(e.target.value)}
          />
        </label>
        <div className="mt-3 grid gap-3 md:grid-cols-[10rem_8rem_1fr]">
          <label className="text-dato text-ink-muted">
            {t("sandboxApi.servicio")}
            <select
              className="input-base mt-1 w-full"
              value={servicio}
              onChange={(e) => setServicio(e.target.value)}
            >
              {(servicios.length ? servicios : [servicio]).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="text-dato text-ink-muted">
            {t("sandboxApi.metodo")}
            <select
              className="input-base mt-1 w-full"
              value={metodo}
              onChange={(e) => setMetodo(e.target.value)}
            >
              {METODOS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="text-dato text-ink-muted">
            {t("sandboxApi.rutaDelContrato")}
            <select
              className="input-base mt-1 w-full"
              value=""
              onChange={(e) => setRuta(e.target.value)}
            >
              <option value="">
                {contrato
                  ? t("sandboxApi.elegirRuta", { n: rutas.length })
                  : t("sandboxApi.cargandoContrato")}
              </option>
              {rutas.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="mt-3 block text-dato text-ink-muted">
          {t("sandboxApi.ruta")}
          <input
            className="input-base mt-1 w-full font-mono"
            value={ruta}
            placeholder="/api/v1/accounts"
            onChange={(e) => setRuta(e.target.value)}
          />
        </label>
        {metodo !== "GET" && metodo !== "DELETE" ? (
          <label className="mt-3 block text-dato text-ink-muted">
            {t("sandboxApi.cuerpo")}
            <textarea
              className="input-base mt-1 h-32 w-full font-mono"
              value={cuerpo}
              placeholder='{"nombre": "…"}'
              onChange={(e) => setCuerpo(e.target.value)}
            />
          </label>
        ) : null}
        <button
          type="button"
          className="btn-primary mt-3"
          disabled={enviando || !clave.trim() || !ruta.startsWith("/api/")}
          onClick={() => void enviar()}
        >
          <Icono nombre="send" tamano="sm" />
          {enviando ? t("sandboxApi.enviando") : t("sandboxApi.enviar")}
        </button>
        <div role="status" className="mt-3">
          {respuesta ? (
            <>
              <p
                className={
                  respuesta.estado >= 200 && respuesta.estado < 300
                    ? "text-dato text-success"
                    : "text-dato text-danger"
                }
              >
                {t("sandboxApi.respuesta", {
                  estado: respuesta.estado,
                  ms: respuesta.ms,
                })}
              </p>
              <pre className="lista-acotada mt-1 overflow-auto rounded bg-paper-sunk p-3 font-mono text-rotulo text-ink">
                {respuesta.cuerpo}
              </pre>
            </>
          ) : null}
        </div>
      </section>
    </>
  );
}
