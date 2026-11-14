/**
 * Calidad del dato sobre las fichas reales (09-11-2026).
 *
 * CRM-01.01.04.06 — golden record compuesto de lo que dice cada fuente sobre la
 * ficha (linaje, lo que tiene hoy, las fichas fusionadas en ella y las unidas
 * por identidad), con reglas por campo guardadas y el resultado guardado con
 * su procedencia; «Aplicar a la ficha» lo escribe. También del lead, que vive
 * en `sales`: sus fuentes son lo que tiene hoy, cada captura fusionada en él
 * (su canal) y cada lead señalado como su duplicado.
 * CRM-01.01.01.08 — enriquecimiento por un proveedor declarado sobre el
 * conector de Integraciones: pedir, revisar campo a campo y aplicar con el
 * proveedor como procedencia en el linaje.
 * CRM-01.01.05.02 — identidad entre canales: las señales se anotan solas al
 * guardar el contacto (y por API desde otros canales); aquí se proponen las
 * parejas con sus señales y se unen.
 * CRM-01.01.04.02 — umbral de coincidencia por objeto, con lo que sale del
 * general marcado como tal; el lead, frente a otros leads y frente a contactos.
 * CRM-01.01.04.04 — direcciones: se normalizan al guardar; para lo que ya
 * estaba, ver qué cambiaría y aplicarlo.
 *
 * Comprobado en el navegador el 09-11-2026 contra el tenant real.
 *
 * Medido antes de construirla: las cinco constaban hechas y calculaban sobre
 * lo que se tecleara —o no las llamaba nadie—. Va al lado de Duplicados porque
 * quien decide aquí es el mismo responsable del dato.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ConfirmarBorrado } from "@/componentes/Edicion";
import {
  AvisoDeRecorte,
  Cargando,
  Error as Fallo,
  Vacio,
} from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { listar, listarPagina } from "@/lib/listados";
import { fichaDeObjeto } from "@/lib/modulos";
import { cn } from "@/lib/utiles";

const BASE = "/api/v1/calidad-dato";
// El lead vive en `sales` y tiene sus mismas rutas colgadas de aquí.
const BASE_LEADS = "/api/v1/leads/calidad-dato";

/**
 * Cuántas candidatas a ficha buena se piden de cada servicio. Con nombre
 * porque se usa también para saber si la lista puede venir cortada.
 */
const CANDIDATAS_PEDIDAS = 50;
const OBJETOS = ["cuenta", "contacto"] as const;
type Objeto = (typeof OBJETOS)[number];
// La ficha buena y sus reglas también para el lead (CRM-01.01.04.06).
const OBJETOS_GOLDEN = [...OBJETOS, "lead"] as const;
type ObjetoGolden = (typeof OBJETOS_GOLDEN)[number];

function baseDe(objeto: ObjetoGolden): string {
  return objeto === "lead" ? BASE_LEADS : BASE;
}

interface Candidata {
  objeto: ObjetoGolden;
  objeto_id: string;
  nombre: string;
  // En un lead: las capturas fusionadas en él y los leads señalados como su
  // duplicado.
  fusionadas?: number;
  unidas?: number;
  capturas?: number;
  duplicados?: number;
  compuesto_at: string | null;
  aplicado_at: string | null;
}

interface Origen {
  fuente: string | null;
  estrategia: string;
  regla: string;
  porque: string;
  candidatos: { fuente: string; valor: unknown; origen: string }[];
}

interface Golden {
  objeto_id: string;
  valores: Record<string, unknown>;
  procedencia: Record<string, Origen>;
  a_revisar: { campo: string }[];
  aplicados: { campo: string }[];
  aplicado_at: string | null;
}

/** «a=1\nb=2» ↔ {a: "1", b: "2"}: lo que se teclea en las áreas de pares. */
function pares(texto: string): Record<string, string> {
  const salida: Record<string, string> = {};
  for (const linea of texto.split("\n")) {
    const [k, ...resto] = linea.split("=");
    if (k?.trim() && resto.join("=").trim())
      salida[k.trim()] = resto.join("=").trim();
  }
  return salida;
}
function aTexto(mapa: Record<string, unknown>): string {
  return Object.entries(mapa)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join("\n");
}
function texto(v: unknown): string {
  return v === null || v === undefined || v === "" ? "—" : String(v);
}

export function CalidadDelDato() {
  const { t } = useTranslation();
  return (
    <>
      <CabeceraPagina
        icono="verified"
        titulo={t("calidadDelDato.titulo")}
        entradilla={t("calidadDelDato.entradilla")}
        acciones={
          <Link to="/duplicados" className="btn-secondary">
            <Icono nombre="join_inner" tamano="sm" />
            {t("calidadDelDato.irDuplicados")}
          </Link>
        }
      />
      <GoldenRecord />
      <ReglasSupervivencia />
      <Identidad />
      <Enriquecimiento />
      <div className="grid gap-4 lg:grid-cols-2">
        <Umbrales />
        <Direcciones />
      </div>
    </>
  );
}

// ── Golden record ─────────────────────────────────────────────────────────

function GoldenRecord() {
  const { t } = useTranslation();
  const [candidatas, setCandidatas] = useState<Candidata[] | null>(null);
  // Si alguna de las dos listas ha llenado lo pedido. Estas rutas devuelven
  // una lista sin cursor, así que llenar la página es la única señal de que
  // puede haber más; sin decirlo, la que falta parece no tener problema.
  const [puedeHaberMas, setPuedeHaberMas] = useState(false);
  const [abierta, setAbierta] = useState<Candidata | null>(null);
  const [golden, setGolden] = useState<Golden | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const [trabajando, setTrabajando] = useState(false);

  const cargar = useCallback(() => {
    // Las de `party` y los leads de `sales`, cada uno por su lado: si uno no
    // contesta, lo del otro se enseña igual y el fallo se dice.
    void Promise.allSettled([
      listar<Candidata>(`${BASE}/golden/candidatas?limite=${CANDIDATAS_PEDIDAS}`),
      listar<Candidata>(
        `${BASE_LEADS}/golden/candidatas?limite=${CANDIDATAS_PEDIDAS}`,
      ),
    ]).then((r) => {
      setCandidatas(
        r.flatMap((x) => (x.status === "fulfilled" ? x.value : [])),
      );
      setPuedeHaberMas(
        r.some(
          (x) =>
            x.status === "fulfilled" && x.value.length >= CANDIDATAS_PEDIDAS,
        ),
      );
      const caido = r.find((x) => x.status === "rejected");
      setFallo(caido && caido.status === "rejected" ? caido.reason : null);
    });
  }, []);
  useEffect(cargar, [cargar]);

  async function componer(c: Candidata, aplicar: boolean) {
    setTrabajando(true);
    setFallo(null);
    setAviso("");
    try {
      const opciones = { metodo: "POST" as const, cuerpo: { aplicar } };
      const r =
        c.objeto === "lead"
          ? await llamar<Golden>(
              `${BASE_LEADS}/golden/lead/${c.objeto_id}/componer`,
              opciones,
            )
          : await llamar<Golden>(
              `${BASE}/golden/${c.objeto}/${c.objeto_id}/componer`,
              opciones,
            );
      setAbierta(c);
      setGolden(r.datos);
      if (aplicar)
        setAviso(
          r.datos.aplicados.length
            ? t("calidadDelDato.aplicados", { count: r.datos.aplicados.length })
            : t("calidadDelDato.sinCambios"),
        );
      cargar();
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("calidadDelDato.golden")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("calidadDelDato.goldenAyuda")}
      </p>
      {candidatas === null ? (
        <Cargando />
      ) : candidatas.length === 0 ? (
        <Vacio titulo={t("calidadDelDato.sinCandidatas")} compacto />
      ) : (
        <Rejilla
          titulo={t("calidadDelDato.golden")}
          cabeceras={[
            t("calidadDelDato.ficha"),
            t("calidadDelDato.fusionadas"),
            t("calidadDelDato.unidas"),
            t("calidadDelDato.compuesta"),
            "",
          ]}
        >
          {candidatas.map((c) => (
            <tr
              key={`${c.objeto}-${c.objeto_id}`}
              className={cn(
                "border-b border-ink-dim/30 last:border-0",
                abierta?.objeto_id === c.objeto_id && "bg-accent/5",
              )}
            >
              <Casilla>
                <Link
                  className="text-ink hover:text-accent hover:underline"
                  to={fichaDeObjeto(c.objeto, c.objeto_id)}
                >
                  {c.nombre || c.objeto_id.slice(0, 8)}
                </Link>
                <span className="ml-2 chip-dato">
                  {t(`calidadDelDato.objetos.${c.objeto}`)}
                </span>
              </Casilla>
              <Casilla className="text-center">
                {c.fusionadas ?? c.capturas ?? 0}
              </Casilla>
              <Casilla className="text-center">
                {c.unidas ?? c.duplicados ?? 0}
              </Casilla>
              <Casilla enUnaLinea>
                {c.compuesto_at
                  ? fechaHora(c.compuesto_at)
                  : t("calidadDelDato.nunca")}
              </Casilla>
              <Casilla enUnaLinea>
                <button
                  type="button"
                  className="btn-link"
                  disabled={trabajando}
                  onClick={() => void componer(c, false)}
                >
                  {t("calidadDelDato.componer")}
                </button>
              </Casilla>
            </tr>
          ))}
        </Rejilla>
      )}
      {candidatas && puedeHaberMas ? (
        <AvisoDeRecorte cuantas={candidatas.length} quiza />
      ) : null}
      <div role="status" className="mt-2">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      {abierta && golden ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="text-dato font-medium text-ink">
              {abierta.nombre}
              {golden.a_revisar.length ? (
                <span className="ml-2 chip-dato chip-dato--aviso">
                  {t("calidadDelDato.aRevisar", {
                    count: golden.a_revisar.length,
                  })}
                </span>
              ) : null}
            </p>
            <button
              type="button"
              className="btn-primary"
              disabled={trabajando}
              onClick={() => void componer(abierta, true)}
            >
              <Icono nombre="done_all" tamano="sm" />
              {t("calidadDelDato.aplicar")}
            </button>
          </div>
          <Rejilla
            titulo={abierta.nombre}
            cabeceras={[
              t("calidadDelDato.campo"),
              t("calidadDelDato.valor"),
              t("calidadDelDato.fuente"),
              t("calidadDelDato.regla"),
              t("calidadDelDato.otrasFuentes"),
            ]}
          >
            {Object.entries(golden.procedencia).map(([campo, o]) => {
              const revisar = golden.a_revisar.some((r) => r.campo === campo);
              const otras = o.candidatos.filter(
                (c) => String(c.valor) !== String(golden.valores[campo]),
              );
              return (
                <tr
                  key={campo}
                  className="border-b border-ink-dim/30 last:border-0"
                >
                  <Casilla enUnaLinea>
                    {campo}
                    {revisar ? (
                      <span className="ml-1 chip-dato chip-dato--aviso">!</span>
                    ) : null}
                  </Casilla>
                  <Casilla>{texto(golden.valores[campo])}</Casilla>
                  <Casilla enUnaLinea>
                    <span className="chip-dato">{o.fuente ?? "—"}</span>
                  </Casilla>
                  <Casilla className="text-ink-muted">
                    <span title={o.porque}>
                      {t(`calidadDelDato.estrategias.${o.estrategia}`)} ·{" "}
                      {o.regla}
                    </span>
                  </Casilla>
                  <Casilla className="text-ink-muted">
                    {otras.length
                      ? otras
                          .map((c) => `${c.fuente}: ${texto(c.valor)}`)
                          .join(" · ")
                      : "—"}
                  </Casilla>
                </tr>
              );
            })}
          </Rejilla>
        </div>
      ) : null}
    </section>
  );
}

// ── Reglas de supervivencia ───────────────────────────────────────────────

interface Regla {
  campo: string;
  estrategia: string;
  confianza_por_fuente: Record<string, number>;
}

function ReglasSupervivencia() {
  const { t } = useTranslation();
  const [objeto, setObjeto] = useState<ObjetoGolden>("cuenta");
  const [datos, setDatos] = useState<{
    reglas: Regla[];
    campos: string[];
    estrategias: string[];
  } | null>(null);
  const [campo, setCampo] = useState("*");
  const [estrategia, setEstrategia] = useState("mayor_confianza");
  const [confianzas, setConfianzas] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  // La regla que se va a quitar, mientras se pregunta.
  const [quitando, setQuitando] = useState<Regla | null>(null);
  const [borrando, setBorrando] = useState(false);

  const cargar = useCallback(() => {
    llamar<{ reglas: Regla[]; campos: string[]; estrategias: string[] }>(
      `${baseDe(objeto)}/golden/reglas/${objeto}`,
    )
      .then((r) => setDatos(r.datos))
      .catch(setFallo);
  }, [objeto]);
  useEffect(cargar, [cargar]);

  function editar(r: Regla) {
    setCampo(r.campo);
    setEstrategia(r.estrategia);
    setConfianzas(aTexto(r.confianza_por_fuente));
  }

  async function guardar() {
    setFallo(null);
    const numeros = Object.fromEntries(
      Object.entries(pares(confianzas)).map(([k, v]) => [k, Number(v)]),
    );
    try {
      await llamar(
        `${baseDe(objeto)}/golden/reglas/${objeto}/${encodeURIComponent(campo)}`,
        {
          metodo: "PUT",
          cuerpo: { estrategia, confianza_por_fuente: numeros, activa: true },
        },
      );
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function quitar(r: Regla) {
    setBorrando(true);
    try {
      await llamar(
        `${baseDe(objeto)}/golden/reglas/${objeto}/${encodeURIComponent(r.campo)}`,
        { metodo: "DELETE" },
      );
      setQuitando(null);
      cargar();
    } catch (e) {
      setFallo(e);
    } finally {
      setBorrando(false);
    }
  }

  // `*` es la regla por defecto: en la pregunta se nombra como en el selector.
  const nombreDeCampo = (c: string) =>
    c === "*" ? t("calidadDelDato.porDefecto") : c;

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("calidadDelDato.reglas")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("calidadDelDato.reglasAyuda")}
      </p>
      <label className="mb-3 flex w-64 flex-col gap-1 text-rotulo text-ink-muted">
        {t("calidadDelDato.objeto")}
        <select
          className="input-base"
          value={objeto}
          onChange={(e) => {
            setDatos(null);
            // Una pregunta abierta sobre otro objeto borraría la regla
            // equivocada: la ruta del DELETE sale del objeto elegido.
            setQuitando(null);
            setObjeto(e.target.value as ObjetoGolden);
          }}
        >
          {OBJETOS_GOLDEN.map((o) => (
            <option key={o} value={o}>
              {t(`calidadDelDato.objetos.${o}`)}
            </option>
          ))}
        </select>
      </label>
      {!datos ? (
        <Cargando />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            {datos.reglas.length === 0 ? (
              <p className="text-dato text-ink-muted">
                {t("calidadDelDato.sinReglas")}
              </p>
            ) : (
              <ul className="lista-acotada divide-y divide-ink-dim/30">
                {datos.reglas.map((r) => (
                  <li
                    key={r.campo}
                    className="flex items-start justify-between gap-2 py-2 text-dato"
                  >
                    <button
                      type="button"
                      className="text-left text-ink hover:text-accent hover:underline"
                      onClick={() => editar(r)}
                    >
                      <span className="font-medium">{r.campo}</span> ·{" "}
                      {t(`calidadDelDato.estrategias.${r.estrategia}`)}
                      <span className="block text-rotulo text-ink-faint">
                        {aTexto(r.confianza_por_fuente).replace(/\n/g, " · ") ||
                          "—"}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="btn-link shrink-0"
                      onClick={() => setQuitando(r)}
                    >
                      {t("calidadDelDato.quitar")}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {quitando ? (
              <div className="mt-3">
                <ConfirmarBorrado
                  borrado={t("calidadDelDato.quitarRegla", {
                    campo: nombreDeCampo(quitando.campo),
                  })}
                  aviso={t("calidadDelDato.quitarReglaAviso", {
                    campo: nombreDeCampo(quitando.campo),
                  })}
                  enviando={borrando}
                  alBorrar={() => void quitar(quitando)}
                  alCancelar={() => setQuitando(null)}
                />
              </div>
            ) : null}
          </div>
          <div className="grid gap-2">
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("calidadDelDato.campo")}
              <select
                className="input-base"
                value={campo}
                onChange={(e) => setCampo(e.target.value)}
              >
                <option value="*">{t("calidadDelDato.porDefecto")}</option>
                {datos.campos.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("calidadDelDato.estrategia")}
              <select
                className="input-base"
                value={estrategia}
                onChange={(e) => setEstrategia(e.target.value)}
              >
                {datos.estrategias.map((e) => (
                  <option key={e} value={e}>
                    {t(`calidadDelDato.estrategias.${e}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("calidadDelDato.confianzas")}
              <textarea
                className="input-base font-mono"
                rows={3}
                value={confianzas}
                placeholder="erp=90&#10;crm=60"
                onChange={(e) => setConfianzas(e.target.value)}
              />
              <span className="text-ink-faint">
                {t("calidadDelDato.confianzasAyuda")}
              </span>
            </label>
            <div>
              <button
                type="button"
                className="btn-primary"
                onClick={() => void guardar()}
              >
                {t("calidadDelDato.guardarRegla")}
              </button>
            </div>
          </div>
        </div>
      )}
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}

// ── Identidad entre canales ───────────────────────────────────────────────

interface Propuesta {
  a: string;
  b: string;
  a_nombre: string;
  b_nombre: string;
  puntuacion: number;
  senales: { tipo: string; peso: number; pista: string }[];
}

function Identidad() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<{
    propuestas: Propuesta[];
    umbral: number;
    /** Todas las que pasan el umbral, no solo las servidas (COB-16). */
    cuantas: number;
  } | null>(null);
  const [aviso, setAviso] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    llamar<{ propuestas: Propuesta[]; umbral: number; cuantas: number }>(
      `${BASE}/identidades/propuestas?limite=50`,
    )
      .then((r) => setDatos(r.datos))
      .catch(setFallo);
  }, []);
  useEffect(cargar, [cargar]);

  async function barrer() {
    setFallo(null);
    try {
      const r = await llamar<{ senales: number; contactos: number }>(
        `${BASE}/identidades/barrer`,
        { metodo: "POST" },
      );
      setAviso(t("calidadDelDato.barrido", r.datos));
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function unir(p: Propuesta) {
    setFallo(null);
    try {
      await llamar(`${BASE}/identidades/unir`, {
        metodo: "POST",
        cuerpo: {
          principal_id: p.a,
          secundario_id: p.b,
          senales: p.senales,
          puntuacion: p.puntuacion,
        },
      });
      setAviso(t("calidadDelDato.unida"));
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <section className="card mb-4 p-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="section-label">{t("calidadDelDato.identidad")}</h2>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => void barrer()}
        >
          <Icono nombre="fingerprint" tamano="sm" />
          {t("calidadDelDato.barrer")}
        </button>
      </div>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("calidadDelDato.identidadAyuda")}
        {datos
          ? ` ${t("calidadDelDato.umbralIdentidad", { umbral: datos.umbral })}`
          : ""}
      </p>
      <div role="status">
        {aviso ? <p className="mb-2 text-dato text-success">{aviso}</p> : null}
      </div>
      {!datos ? (
        <Cargando />
      ) : datos.propuestas.length === 0 ? (
        <Vacio titulo={t("calidadDelDato.sinPropuestas")} compacto />
      ) : (
        <Rejilla
          titulo={t("calidadDelDato.identidad")}
          cabeceras={[
            t("calidadDelDato.pareja"),
            t("calidadDelDato.senales"),
            t("calidadDelDato.puntuacion"),
            "",
          ]}
        >
          {datos.propuestas.map((p) => (
            <tr
              key={`${p.a}-${p.b}`}
              className="border-b border-ink-dim/30 last:border-0"
            >
              <Casilla>
                <Link
                  className="hover:text-accent hover:underline"
                  to={fichaDeObjeto("contacto", p.a)}
                >
                  {p.a_nombre || p.a.slice(0, 8)}
                </Link>
                {" · "}
                <Link
                  className="hover:text-accent hover:underline"
                  to={fichaDeObjeto("contacto", p.b)}
                >
                  {p.b_nombre || p.b.slice(0, 8)}
                </Link>
              </Casilla>
              <Casilla>
                {p.senales.map((s) => (
                  <span key={`${s.tipo}-${s.pista}`} className="mr-1 chip-dato">
                    {s.tipo} {s.pista}
                  </span>
                ))}
              </Casilla>
              <Casilla className="text-center">{p.puntuacion}</Casilla>
              <Casilla enUnaLinea>
                <button
                  type="button"
                  className="btn-link"
                  onClick={() => void unir(p)}
                >
                  {t("calidadDelDato.unir")}
                </button>
              </Casilla>
            </tr>
          ))}
        </Rejilla>
      )}
      {datos && datos.cuantas > datos.propuestas.length ? (
        <AvisoDeRecorte
          cuantas={datos.propuestas.length}
          detalle={t("calidadDelDato.propuestasPorPuntuacion")}
        />
      ) : null}
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}

// ── Enriquecimiento ───────────────────────────────────────────────────────

interface Perfil {
  clave: string;
  nombre: string;
  objeto: Objeto;
  conexion_id: string;
  operacion: string;
  parametros: Record<string, string>;
  mapeo: Record<string, string>;
  confianza: number;
  coste_por_consulta: number;
}

interface PropuestaEnr {
  id: string;
  perfil: string;
  objeto: Objeto;
  objeto_id: string;
  consultado_at: string;
  campos: {
    campo: string;
    actual: unknown;
    propuesto: unknown;
    tipo: "hueco" | "discrepancia" | "igual";
  }[];
}

const PERFIL_VACIO: Perfil = {
  clave: "",
  nombre: "",
  objeto: "cuenta",
  conexion_id: "",
  operacion: "",
  parametros: {},
  mapeo: {},
  confianza: 40,
  coste_por_consulta: 0,
};

function Enriquecimiento() {
  const { t } = useTranslation();
  const [perfiles, setPerfiles] = useState<Perfil[] | null>(null);
  const [conexiones, setConexiones] = useState<
    { id: string; nombre: string }[]
  >([]);
  const [fichas, setFichas] = useState<{ id: string; nombre: string }[]>([]);
  // Si el servidor ha dicho que hay más fichas que las cien pedidas: la que
  // no sale no se puede elegir, y sin decirlo parece que no existe.
  const [hayMasFichas, setHayMasFichas] = useState(false);
  const [propuestas, setPropuestas] = useState<PropuestaEnr[]>([]);
  const [editando, setEditando] = useState<Perfil>(PERFIL_VACIO);
  const [textoParam, setTextoParam] = useState("");
  const [textoMapeo, setTextoMapeo] = useState("");
  const [perfilPedir, setPerfilPedir] = useState("");
  const [fichaPedir, setFichaPedir] = useState("");
  const [marcados, setMarcados] = useState<Record<string, string[]>>({});
  const [aviso, setAviso] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    listar<Perfil>(`${BASE}/enriquecimiento/perfiles`)
      .then((p) => {
        setPerfiles(p);
        setPerfilPedir((actual) => actual || p[0]?.clave || "");
      })
      .catch((e) => {
        setPerfiles([]);
        setFallo(e);
      });
    listar<PropuestaEnr>(`${BASE}/enriquecimiento/propuestas?estado=pendiente`)
      .then((lista) => {
        setPropuestas(lista);
        // Por defecto, sólo los huecos: lo mismo que hace el servidor.
        setMarcados(
          Object.fromEntries(
            lista.map((p) => [
              p.id,
              p.campos.filter((c) => c.tipo === "hueco").map((c) => c.campo),
            ]),
          ),
        );
      })
      .catch(() => setPropuestas([]));
  }, []);
  useEffect(cargar, [cargar]);
  useEffect(() => {
    void listar<{ id: string; nombre: string }>(
      "/api/v1/integraciones/conexiones",
    )
      .then(setConexiones)
      .catch(() => setConexiones([]));
  }, []);
  const objetoPedir =
    perfiles?.find((p) => p.clave === perfilPedir)?.objeto ?? "cuenta";
  useEffect(() => {
    const ruta =
      objetoPedir === "cuenta" ? "/api/v1/accounts" : "/api/v1/contacts";
    void listarPagina<{ id: string; nombre?: string; nombre_completo?: string }>(
      `${ruta}?limite=100`,
    )
      .then((l) => {
        setFichas(
          l.filas.map((f) => ({
            id: f.id,
            nombre: f.nombre_completo || f.nombre || f.id,
          })),
        );
        setHayMasFichas(l.siguiente !== "");
      })
      .catch(() => setFichas([]));
  }, [objetoPedir]);

  function editar(p: Perfil) {
    setEditando(p);
    setTextoParam(aTexto(p.parametros));
    setTextoMapeo(aTexto(p.mapeo));
  }

  async function guardarPerfil() {
    setFallo(null);
    try {
      await llamar(
        `${BASE}/enriquecimiento/perfiles/${encodeURIComponent(editando.clave)}`,
        {
          metodo: "PUT",
          cuerpo: {
            ...editando,
            parametros: pares(textoParam),
            mapeo: pares(textoMapeo),
          },
        },
      );
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function pedir() {
    setFallo(null);
    setAviso("");
    try {
      await llamar(`${BASE}/enriquecimiento/${perfilPedir}/pedir`, {
        metodo: "POST",
        cuerpo: { objeto_ids: [fichaPedir] },
      });
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function decidir(p: PropuestaEnr, aplicar: boolean) {
    setFallo(null);
    try {
      await llamar(
        `${BASE}/enriquecimiento/propuestas/${p.id}/${aplicar ? "aplicar" : "descartar"}`,
        {
          metodo: "POST",
          cuerpo: aplicar ? { campos: marcados[p.id] ?? [] } : {},
        },
      );
      setAviso(
        t(aplicar ? "calidadDelDato.aplicada" : "calidadDelDato.descartada"),
      );
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  const nombreFicha = (id: string) =>
    fichas.find((f) => f.id === id)?.nombre ?? id.slice(0, 8);

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">
        {t("calidadDelDato.enriquecimiento")}
      </h2>
      <p className="mb-3 text-rotulo text-ink-faint">
        {t("calidadDelDato.enriquecimientoAyuda")}
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="section-label mb-1">{t("calidadDelDato.perfiles")}</h3>
          {perfiles === null ? (
            <Cargando />
          ) : perfiles.length === 0 ? (
            <p className="text-dato text-ink-muted">
              {t("calidadDelDato.sinPerfiles")}
            </p>
          ) : (
            <ul className="lista-acotada divide-y divide-ink-dim/30">
              {perfiles.map((p) => (
                <li key={p.clave} className="py-2 text-dato">
                  <button
                    type="button"
                    className="text-left text-ink hover:text-accent hover:underline"
                    onClick={() => editar(p)}
                  >
                    <span className="font-medium">{p.nombre}</span>{" "}
                    <span className="chip-dato">{p.clave}</span>
                  </button>
                  <span className="block text-rotulo text-ink-faint">
                    {t(`calidadDelDato.objetos.${p.objeto}`)} · {p.operacion} ·{" "}
                    {Object.keys(p.mapeo).join(", ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {perfiles?.length ? (
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
                {t("calidadDelDato.pedirPara")}
                <select
                  className="input-base"
                  value={perfilPedir}
                  onChange={(e) => setPerfilPedir(e.target.value)}
                >
                  {perfiles.map((p) => (
                    <option key={p.clave} value={p.clave}>
                      {p.nombre}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex min-w-[14rem] flex-1 flex-col gap-1 text-rotulo text-ink-muted">
                {t("calidadDelDato.elegirCuenta")}
                <select
                  className="input-base"
                  value={fichaPedir}
                  onChange={(e) => setFichaPedir(e.target.value)}
                >
                  <option value="">—</option>
                  {fichas.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.nombre}
                    </option>
                  ))}
                </select>
                {hayMasFichas ? (
                  <AvisoDeRecorte cuantas={fichas.length} />
                ) : null}
              </label>
              <button
                type="button"
                className="btn-primary"
                disabled={!fichaPedir || !perfilPedir}
                onClick={() => void pedir()}
              >
                <Icono nombre="travel_explore" tamano="sm" />
                {t("calidadDelDato.pedir")}
              </button>
            </div>
          ) : null}
        </div>
        <div className="grid gap-2">
          <h3 className="section-label">{t("calidadDelDato.nuevoPerfil")}</h3>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("calidadDelDato.clave")}
              <input
                className="input-base"
                value={editando.clave}
                onChange={(e) =>
                  setEditando({ ...editando, clave: e.target.value })
                }
              />
            </label>
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("calidadDelDato.nombre")}
              <input
                className="input-base"
                value={editando.nombre}
                onChange={(e) =>
                  setEditando({ ...editando, nombre: e.target.value })
                }
              />
            </label>
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("calidadDelDato.objeto")}
              <select
                className="input-base"
                value={editando.objeto}
                onChange={(e) =>
                  setEditando({ ...editando, objeto: e.target.value as Objeto })
                }
              >
                {OBJETOS.map((o) => (
                  <option key={o} value={o}>
                    {t(`calidadDelDato.objetos.${o}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("calidadDelDato.conexion")}
              <select
                className="input-base"
                value={editando.conexion_id}
                onChange={(e) =>
                  setEditando({ ...editando, conexion_id: e.target.value })
                }
              >
                <option value="">
                  {conexiones.length
                    ? "—"
                    : t("calidadDelDato.sinConexionesInt")}
                </option>
                {conexiones.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nombre}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("calidadDelDato.operacion")}
              <input
                className="input-base"
                value={editando.operacion}
                onChange={(e) =>
                  setEditando({ ...editando, operacion: e.target.value })
                }
              />
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
                {t("calidadDelDato.confianza")}
                <input
                  type="number"
                  min={0}
                  max={100}
                  className="input-base"
                  value={editando.confianza}
                  onChange={(e) =>
                    setEditando({
                      ...editando,
                      confianza: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
                {t("calidadDelDato.coste")}
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  className="input-base"
                  value={editando.coste_por_consulta}
                  onChange={(e) =>
                    setEditando({
                      ...editando,
                      coste_por_consulta: Number(e.target.value),
                    })
                  }
                />
              </label>
            </div>
          </div>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("calidadDelDato.parametros")}
            <textarea
              className="input-base font-mono"
              rows={2}
              value={textoParam}
              onChange={(e) => setTextoParam(e.target.value)}
            />
            <span className="text-ink-faint">
              {t("calidadDelDato.parametrosAyuda")}
            </span>
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("calidadDelDato.mapeo")}
            <textarea
              className="input-base font-mono"
              rows={3}
              value={textoMapeo}
              onChange={(e) => setTextoMapeo(e.target.value)}
            />
            <span className="text-ink-faint">
              {t("calidadDelDato.mapeoAyuda")}
            </span>
          </label>
          <div>
            <button
              type="button"
              className="btn-primary"
              disabled={
                !editando.clave.trim() ||
                !editando.nombre.trim() ||
                !editando.conexion_id ||
                !editando.operacion.trim()
              }
              onClick={() => void guardarPerfil()}
            >
              {t("calidadDelDato.guardarPerfil")}
            </button>
          </div>
        </div>
      </div>

      <h3 className="section-label mb-1 mt-4">
        {t("calidadDelDato.propuestas")}
      </h3>
      <div role="status">
        {aviso ? <p className="mb-2 text-dato text-success">{aviso}</p> : null}
      </div>
      {propuestas.length === 0 ? (
        <p className="text-dato text-ink-muted">
          {t("calidadDelDato.sinPropuestasEnr")}
        </p>
      ) : (
        <ul className="lista-acotada divide-y divide-ink-dim/30">
          {propuestas.map((p) => (
            <li key={p.id} className="py-2 text-dato">
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                <span>
                  <span className="font-medium text-ink">
                    {nombreFicha(p.objeto_id)}
                  </span>{" "}
                  <span className="chip-dato">{p.perfil}</span>{" "}
                  <span className="text-rotulo text-ink-faint">
                    {fechaHora(p.consultado_at)}
                  </span>
                </span>
                <span className="flex gap-2">
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={!(marcados[p.id] ?? []).length}
                    onClick={() => void decidir(p, true)}
                  >
                    {t("calidadDelDato.aplicarElegidos")}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => void decidir(p, false)}
                  >
                    {t("calidadDelDato.descartar")}
                  </button>
                </span>
              </div>
              <Rejilla
                titulo={p.perfil}
                compacta
                cabeceras={[
                  "",
                  t("calidadDelDato.campo"),
                  t("calidadDelDato.actual"),
                  t("calidadDelDato.propuesto"),
                  "",
                ]}
              >
                {p.campos.map((c) => {
                  const puesto = (marcados[p.id] ?? []).includes(c.campo);
                  return (
                    <tr
                      key={c.campo}
                      className="border-b border-ink-dim/30 last:border-0"
                    >
                      <Casilla>
                        <input
                          type="checkbox"
                          aria-label={c.campo}
                          disabled={c.tipo === "igual"}
                          checked={puesto}
                          onChange={(e) =>
                            setMarcados({
                              ...marcados,
                              [p.id]: e.target.checked
                                ? [...(marcados[p.id] ?? []), c.campo]
                                : (marcados[p.id] ?? []).filter(
                                    (x) => x !== c.campo,
                                  ),
                            })
                          }
                        />
                      </Casilla>
                      <Casilla enUnaLinea>{c.campo}</Casilla>
                      <Casilla>{texto(c.actual)}</Casilla>
                      <Casilla>{texto(c.propuesto)}</Casilla>
                      <Casilla enUnaLinea>
                        <span
                          className={cn(
                            "chip-dato",
                            c.tipo === "discrepancia" && "chip-dato--aviso",
                            c.tipo === "hueco" && "chip-dato--si",
                          )}
                        >
                          {t(`calidadDelDato.tipos.${c.tipo}`)}
                        </span>
                      </Casilla>
                    </tr>
                  );
                })}
              </Rejilla>
            </li>
          ))}
        </ul>
      )}
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}

// ── Umbrales por objeto ───────────────────────────────────────────────────

const TIPOS_UMBRAL = ["sugerencia", "bloqueo", "propuesta"] as const;
type TipoUmbral = (typeof TIPOS_UMBRAL)[number];
type UmbralesDe = Record<
  string,
  Partial<Record<TipoUmbral, { valor: number; propio: boolean }>>
>;

/**
 * Cada fila es un objeto que se compara, y quién guarda su umbral. Cuentas y
 * contactos los guarda `party`; el lead, `sales`, y se compara con otros
 * leads y con los contactos del maestro (CRM-01.01.04.02). El lead no tiene
 * cola de propuestas: su columna sale vacía.
 */
const FILAS_UMBRAL = [
  { clave: "cuenta", base: BASE, objeto: "cuenta" },
  { clave: "contacto", base: BASE, objeto: "contacto" },
  { clave: "leadLead", base: BASE_LEADS, objeto: "lead" },
  { clave: "leadContacto", base: BASE_LEADS, objeto: "contacto" },
] as const;

/** Cada servicio con su ruta escrita entera: así se sabe a cuál se pide. */
function pedirUmbrales(base: string, opciones?: Parameters<typeof llamar>[1]) {
  return base === BASE_LEADS
    ? llamar<UmbralesDe>(`${BASE_LEADS}/umbrales-duplicado`, opciones)
    : llamar<UmbralesDe>(`${BASE}/umbrales-duplicado`, opciones);
}

function Umbrales() {
  const { t } = useTranslation();
  const [umbrales, setUmbrales] = useState<Record<string, UmbralesDe> | null>(
    null,
  );
  const [propios, setPropios] = useState<Record<string, string>>({});
  const [tocados, setTocados] = useState<Set<string>>(new Set());
  const [aviso, setAviso] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  function tomar(base: string, u: UmbralesDe) {
    setUmbrales((previo) => ({ ...(previo ?? {}), [base]: u }));
    setPropios((previo) => {
      const p = { ...previo };
      for (const f of FILAS_UMBRAL) {
        if (f.base !== base) continue;
        for (const tipo of TIPOS_UMBRAL) {
          const u1 = u[f.objeto]?.[tipo];
          const clave = `${f.clave}.${tipo}`;
          if (u1?.propio) p[clave] = String(u1.valor);
          else delete p[clave];
        }
      }
      return p;
    });
  }

  useEffect(() => {
    // Cada servicio por su lado: si quien mira no puede ver los leads, las
    // filas de cuentas y contactos salen igual.
    for (const base of [BASE, BASE_LEADS])
      pedirUmbrales(base)
        .then((r) => tomar(base, r.datos))
        .catch((e) => {
          setUmbrales((previo) => previo ?? {});
          if (base === BASE) setFallo(e);
        });
  }, []);

  async function guardar() {
    setFallo(null);
    setAviso("");
    try {
      for (const base of tocados) {
        const por_objeto: Record<string, Record<string, number>> = {};
        for (const f of FILAS_UMBRAL) {
          if (f.base !== base) continue;
          for (const tipo of TIPOS_UMBRAL) {
            const v = propios[`${f.clave}.${tipo}`] ?? "";
            if (!v.trim()) continue;
            por_objeto[f.objeto] = {
              ...(por_objeto[f.objeto] ?? {}),
              [tipo]: Number(v),
            };
          }
        }
        const r = await pedirUmbrales(base, {
          metodo: "PUT",
          cuerpo: { por_objeto },
        });
        tomar(base, r.datos);
      }
      setTocados(new Set());
      setAviso(t("calidadDelDato.umbralesGuardados"));
    } catch (e) {
      setFallo(e);
    }
  }

  const filas = FILAS_UMBRAL.filter((f) => umbrales?.[f.base]?.[f.objeto]);

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("calidadDelDato.umbrales")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("calidadDelDato.umbralesAyuda")}
      </p>
      {!umbrales ? (
        fallo ? null : (
          <Cargando />
        )
      ) : (
        <>
          <Rejilla
            titulo={t("calidadDelDato.umbrales")}
            acotada={false}
            cabeceras={[
              t("calidadDelDato.objeto"),
              ...TIPOS_UMBRAL.map((x) => t(`calidadDelDato.tiposUmbral.${x}`)),
            ]}
          >
            {filas.map((f) => {
              const etiqueta = t(`calidadDelDato.filasUmbral.${f.clave}`);
              return (
                <tr
                  key={f.clave}
                  className="border-b border-ink-dim/30 last:border-0"
                >
                  <Casilla enUnaLinea>{etiqueta}</Casilla>
                  {TIPOS_UMBRAL.map((tipo) => {
                    const actual = umbrales[f.base]?.[f.objeto]?.[tipo];
                    if (!actual)
                      return (
                        <Casilla key={tipo} className="text-ink-faint">
                          —
                        </Casilla>
                      );
                    const clave = `${f.clave}.${tipo}`;
                    return (
                      <Casilla key={tipo}>
                        <input
                          type="number"
                          min={0}
                          max={1}
                          step="0.01"
                          className="input-base w-24"
                          aria-label={`${etiqueta} · ${t(`calidadDelDato.tiposUmbral.${tipo}`)}`}
                          placeholder={String(actual.valor)}
                          value={propios[clave] ?? ""}
                          onChange={(e) => {
                            setPropios({ ...propios, [clave]: e.target.value });
                            setTocados(new Set([...tocados, f.base]));
                          }}
                        />
                        <span className="block text-rotulo text-ink-faint">
                          {actual.propio
                            ? t("calidadDelDato.propio")
                            : `${actual.valor} ${t("calidadDelDato.general")}`}
                        </span>
                      </Casilla>
                    );
                  })}
                </tr>
              );
            })}
          </Rejilla>
          <div className="mt-2 flex items-center gap-3">
            <button
              type="button"
              className="btn-primary"
              disabled={tocados.size === 0}
              onClick={() => void guardar()}
            >
              {t("calidadDelDato.guardarUmbrales")}
            </button>
            <span role="status" className="text-dato text-success">
              {aviso}
            </span>
          </div>
        </>
      )}
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}

// ── Direcciones ───────────────────────────────────────────────────────────

interface Barrido {
  revisadas: number;
  a_cambiar: number;
  aplicado: boolean;
  cambios: {
    direccion_id: string;
    cambios: Record<string, { antes: unknown; despues: unknown }>;
  }[];
}

function Direcciones() {
  const { t } = useTranslation();
  const [barrido, setBarrido] = useState<Barrido | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [trabajando, setTrabajando] = useState(false);

  async function correr(aplicar: boolean) {
    setTrabajando(true);
    setFallo(null);
    try {
      const r = await llamar<Barrido>(
        `${BASE}/direcciones/normalizar?aplicar=${aplicar}`,
        { metodo: "POST" },
      );
      setBarrido(r.datos);
    } catch (e) {
      setFallo(e);
    } finally {
      setTrabajando(false);
    }
  }

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("calidadDelDato.direcciones")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("calidadDelDato.direccionesAyuda")}
      </p>
      <div className="mb-2 flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-secondary"
          disabled={trabajando}
          onClick={() => void correr(false)}
        >
          {t("calidadDelDato.verCambios")}
        </button>
        {barrido && !barrido.aplicado && barrido.a_cambiar > 0 ? (
          <button
            type="button"
            className="btn-primary"
            disabled={trabajando}
            onClick={() => void correr(true)}
          >
            {t("calidadDelDato.aplicarCambios", { n: barrido.a_cambiar })}
          </button>
        ) : null}
      </div>
      <div role="status">
        {barrido ? (
          <p className="mb-2 text-dato text-ink-muted">
            {barrido.aplicado
              ? t("calidadDelDato.aplicadas", { n: barrido.a_cambiar })
              : t("calidadDelDato.revisadas", {
                  revisadas: barrido.revisadas,
                  n: barrido.a_cambiar,
                })}
          </p>
        ) : null}
      </div>
      {barrido && barrido.cambios.length > 0 ? (
        <Rejilla
          titulo={t("calidadDelDato.direcciones")}
          compacta
          cabeceras={[
            t("calidadDelDato.campo"),
            t("calidadDelDato.antes"),
            t("calidadDelDato.despues"),
          ]}
        >
          {barrido.cambios.flatMap((c) =>
            Object.entries(c.cambios).map(([campo, par]) => (
              <tr
                key={`${c.direccion_id}-${campo}`}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla enUnaLinea>{campo}</Casilla>
                <Casilla className="text-ink-muted">{texto(par.antes)}</Casilla>
                <Casilla>{texto(par.despues)}</Casilla>
              </tr>
            )),
          )}
        </Rejilla>
      ) : null}
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}
