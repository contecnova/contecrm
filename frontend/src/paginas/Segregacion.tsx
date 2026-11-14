/**
 * Segregación de funciones: la matriz, quién está en conflicto y qué pasaría
 * (CRM-07.03.02.06).
 *
 * Existía entera por API —reglas, excepciones que caducan, violaciones en
 * vivo— y no tenía ninguna pantalla, así que no la usaba nadie. Pedido el
 * 09-11-2026 («un GRC mucho más potente, con una matriz de segregación como
 * la de Infor»): aquí está la matriz de reglas por roles —el rol que da los
 * dos lados es el conflicto que se arregla en el rol—, la lista de personas
 * en conflicto con su excepción, y el simulador que se mira ANTES de asignar.
 *
 * Las reglas se escriben aquí —«superconfigurable», se pidió—, y aquí se leen
 * las excepciones aprobadas: antes había un trozo en Seguridad y otro en
 * Cumplimiento que contestaban a la misma pregunta, y el de Seguridad no
 * marcaba nunca la excepción porque leía un campo que la API no manda.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import {
  AvisoDelDirectorio,
  Cargando,
  Error as Fallo,
  Vacio,
} from "@/componentes/Estados";
import { Opciones } from "@/componentes/Formulario";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { rotuloDeOpcion } from "@/lib/formato";
import type { CampoEsquema } from "@/lib/contrato";
import { listar, MAXIMO_POR_PAGINA } from "@/lib/listados";
import { useDirectorio } from "@/lib/personas";
import type { Directorio } from "@/lib/personas";
import { cn } from "@/lib/utiles";

interface FilaMatriz {
  regla: string;
  nombre: string;
  nivel: string;
  celdas: Record<string, "" | "a" | "b" | "ambos">;
  roles_en_conflicto: string[];
  personas_en_conflicto: number;
}

interface Violacion {
  usuario_id: string;
  regla: string;
  nombre: string;
  nivel: string;
  por_el_lado_a: string[];
  por_el_lado_b: string[];
  exceptuado: boolean;
}

interface Regla {
  codigo: string;
  nombre: string;
  descripcion: string;
  permisos_a: string[];
  permisos_b: string[];
  nivel: string;
  activa: boolean;
}

interface Excepcion {
  id: string;
  regla_codigo: string;
  usuario_id: string;
  motivo: string;
  caduca_at: string;
  vigente: boolean;
}

const NIVELES = ["bajo", "medio", "alto", "critico"] as const;

const TONO: Record<string, string> = {
  critico: "chip-dato--mal",
  alto: "chip-dato--mal",
  medio: "chip-dato--aviso",
  bajo: "",
};

export function Segregacion() {
  const { t } = useTranslation();
  const [matriz, setMatriz] = useState<{
    roles: string[];
    reglas: FilaMatriz[];
  } | null>(null);
  const [violaciones, setViolaciones] = useState<Violacion[]>([]);
  // Las personas salen del directorio de la sesión, que sigue el cursor: se
  // pedían las doscientas primeras y, pasado ese número, las demás no se
  // podían simular y su nombre salía recortado, sin aviso.
  const directorio = useDirectorio();
  const usuarios = directorio.personas ?? [];
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const [reglas, setReglas] = useState<Regla[]>([]);
  const [permisos, setPermisos] = useState<string[]>([]);
  // La regla que se está escribiendo: una existente o una nueva («»).
  const [editando, setEditando] = useState<Regla | null>(null);
  // Cada regla es un control preventivo del GRC (CRM-07.03.02.13): su código,
  // para ir del uno al otro. Desde el control se llega aquí con `?regla=`.
  const [controlDe, setControlDe] = useState<Record<string, string>>({});
  const [params] = useSearchParams();
  const pedida = params.get("regla") ?? "";

  const cargar = useCallback(() => {
    llamar<{ roles: string[]; reglas: FilaMatriz[] }>(
      "/api/v1/segregacion/matriz",
    )
      .then((r) => setMatriz(r.datos))
      .catch((e) => setFallo(e));
    llamar<Regla[]>("/api/v1/segregacion/reglas")
      .then((r) => setReglas(Array.isArray(r.datos) ? r.datos : []))
      .catch(() => setReglas([]));
    llamar<{ violaciones: Violacion[] }>("/api/v1/segregacion/violaciones")
      .then((r) => setViolaciones(r.datos?.violaciones ?? []))
      .catch(() => setViolaciones([]));
    llamar<{ codigo: string; origen: string; referencia: string }[]>(
      "/api/v1/grc/controles",
    )
      .then((r) =>
        setControlDe(
          Object.fromEntries(
            (Array.isArray(r.datos) ? r.datos : [])
              .filter((c) => c.origen === "segregacion")
              .map((c) => [c.referencia, c.codigo]),
          ),
        ),
      )
      .catch(() => setControlDe({}));
  }, []);
  useEffect(cargar, [cargar]);
  useEffect(() => {
    const regla = reglas.find((r) => r.codigo === pedida);
    if (regla) setEditando(regla);
  }, [reglas, pedida]);

  // Lo que se cambia aquí llega al GRC en el momento: controles, hallazgos y
  // evidencias. Si quien lo cambia no puede escribir en el GRC, se queda para
  // la próxima sincronización y no se le enseña un error que no es suyo.
  const recargar = useCallback(() => {
    void llamar("/api/v1/grc/segregacion/sincronizar", { metodo: "POST" })
      .catch(() => undefined)
      .finally(cargar);
  }, [cargar]);
  useEffect(() => {
    // Los permisos que se pueden elegir son los que dan los roles de verdad:
    // una regla con un permiso inventado no se cumple nunca y parece verde.
    void listar<{ permisos?: string[] }>(
      `/api/v1/roles?limite=${MAXIMO_POR_PAGINA}`,
    )
      .then((roles) =>
        setPermisos(
          [...new Set(roles.flatMap((r) => r.permisos ?? []))]
            .filter((p) => !p.includes("*"))
            .sort(),
        ),
      )
      .catch(() => setPermisos([]));
  }, []);

  const nombre = (id: string) => {
    const u = usuarios.find((x) => x.id === id);
    return u ? u.nombre || u.email : `${id.slice(0, 8)}…`;
  };

  async function deSerie() {
    try {
      const r = await llamar<{ anadidas: number }>(
        "/api/v1/segregacion/reglas/de-serie",
        {
          metodo: "POST",
        },
      );
      setAviso(t("segregacion.cargadas", { n: r.datos.anadidas }));
      recargar();
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !matriz) return <Fallo error={fallo} />;
  if (!matriz) return <Cargando />;

  // Sólo los roles que dan algún lado de alguna regla: con todos, las columnas
  // que importan quedaban fuera de la vista. Los que dan los dos lados, delante.
  const peso = (rol: string) =>
    matriz.reglas.some((f) => f.celdas[rol] === "ambos")
      ? 0
      : matriz.reglas.some((f) => f.celdas[rol])
        ? 1
        : 2;
  const roles = matriz.roles
    .filter((r) => peso(r) < 2)
    .sort((a, b) => peso(a) - peso(b));

  return (
    <>
      <CabeceraPagina
        icono="rule_settings"
        titulo={t("segregacion.titulo")}
        entradilla={t("segregacion.entradilla")}
        acciones={
          <>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void deSerie()}
            >
              <Icono nombre="library_add" tamano="sm" />
              {t("segregacion.deSerie")}
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() =>
                setEditando({
                  codigo: "",
                  nombre: "",
                  descripcion: "",
                  permisos_a: [],
                  permisos_b: [],
                  nivel: "alto",
                  activa: true,
                })
              }
            >
              <Icono nombre="add" tamano="sm" />
              {t("segregacion.nueva")}
            </button>
          </>
        }
      />
      <div role="status" className="mb-3">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("segregacion.matriz")}</h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {t("segregacion.matrizAyuda")}
        </p>
        {matriz.reglas.length === 0 ? (
          <Vacio titulo={t("segregacion.sinReglas")} compacto />
        ) : (
          <Rejilla
            titulo={t("segregacion.matriz")}
            acotada={false}
            cabeceras={[
              t("segregacion.regla"),
              t("segregacion.personas"),
              ...roles.map(rotuloDeOpcion),
            ]}
          >
            {matriz.reglas.map((f) => (
              <tr
                key={f.regla}
                className="border-b border-ink-dim/30 last:border-0"
              >
                <Casilla className="min-w-[16rem]">
                  <span className={cn("chip-dato mr-2", TONO[f.nivel] ?? "")}>
                    {t(`segregacion.niveles.${f.nivel}`)}
                  </span>
                  <button
                    type="button"
                    className="text-left text-ink hover:text-accent hover:underline"
                    title={t("segregacion.editar")}
                    onClick={() =>
                      setEditando(
                        reglas.find((r) => r.codigo === f.regla) ?? null,
                      )
                    }
                  >
                    {f.nombre}
                  </button>
                  {controlDe[f.regla] ? (
                    <Link
                      to={`/controles-grc?control=${encodeURIComponent(controlDe[f.regla] ?? "")}`}
                      className="btn-link ml-2 text-rotulo"
                      title={t("segregacion.suControl")}
                    >
                      {controlDe[f.regla]}
                    </Link>
                  ) : null}
                </Casilla>
                <Casilla className="text-center">
                  <span
                    className={cn(
                      "chip-dato",
                      f.personas_en_conflicto
                        ? "chip-dato--mal"
                        : "chip-dato--si",
                    )}
                  >
                    {f.personas_en_conflicto}
                  </span>
                </Casilla>
                {roles.map((rol) => {
                  const c = f.celdas[rol];
                  return (
                    <Casilla key={rol} className="text-center">
                      {c ? (
                        <span
                          className={cn(
                            "chip-dato",
                            c === "ambos" && "chip-dato--mal",
                          )}
                          title={t(`segregacion.celda.${c}`)}
                        >
                          {c === "ambos" ? "A+B" : c.toUpperCase()}
                        </span>
                      ) : (
                        <span className="text-ink-faint">·</span>
                      )}
                    </Casilla>
                  );
                })}
              </tr>
            ))}
          </Rejilla>
        )}
      </section>

      {editando ? (
        <EditorDeRegla
          key={editando.codigo || "nueva"}
          regla={editando}
          permisos={permisos}
          alCerrar={() => setEditando(null)}
          alGuardar={(codigo) => {
            setEditando(null);
            setAviso(t("segregacion.guardada", { codigo }));
            recargar();
          }}
        />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Conflictos
          violaciones={violaciones}
          nombre={nombre}
          alCambiar={recargar}
        />
        <Simulador directorio={directorio} roles={matriz.roles} />
      </div>
      <ExcepcionesAprobadas nombre={nombre} reglas={reglas} />
    </>
  );
}

function Conflictos({
  violaciones,
  nombre,
  alCambiar,
}: {
  violaciones: Violacion[];
  nombre: (id: string) => string;
  alCambiar: () => void;
}) {
  const { t } = useTranslation();
  const [abierta, setAbierta] = useState<string>("");
  const [motivo, setMotivo] = useState("");
  const [caduca, setCaduca] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  async function exceptuar(v: Violacion) {
    try {
      await llamar(`/api/v1/segregacion/reglas/${v.regla}/excepciones`, {
        metodo: "POST",
        cuerpo: { usuario_id: v.usuario_id, motivo, caduca_at: caduca },
      });
      setAbierta("");
      setMotivo("");
      setCaduca("");
      setFallo(null);
      alCambiar();
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("segregacion.conflictos")}</h2>
      {violaciones.length === 0 ? (
        <p className="text-dato text-ink-muted">
          {t("segregacion.sinConflictos")}
        </p>
      ) : (
        <ul className="lista-acotada divide-y divide-ink-dim/30" role="status">
          {violaciones.map((v) => {
            const clave = `${v.usuario_id}-${v.regla}`;
            return (
              <li key={clave} className="py-2 text-dato">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-medium text-ink">
                      {nombre(v.usuario_id)}
                    </span>
                    <span className={cn("chip-dato", TONO[v.nivel] ?? "")}>
                      {v.nombre}
                    </span>
                  </div>
                  {v.exceptuado ? (
                    <span className="chip-dato chip-dato--si">
                      {t("segregacion.exceptuado")}
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="btn-link shrink-0"
                      onClick={() => setAbierta(abierta === clave ? "" : clave)}
                    >
                      {t("segregacion.exceptuar")}
                    </button>
                  )}
                </div>
                <p className="text-rotulo text-ink-faint">
                  {t("segregacion.porQue", {
                    a: v.por_el_lado_a.join(", "),
                    b: v.por_el_lado_b.join(", "),
                  })}
                </p>
                {abierta === clave ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <input
                      className="input-base w-64"
                      value={motivo}
                      placeholder={t("segregacion.motivo")}
                      aria-label={t("segregacion.motivo")}
                      onChange={(e) => setMotivo(e.target.value)}
                    />
                    <input
                      type="date"
                      className="input-base w-auto"
                      value={caduca}
                      aria-label={t("segregacion.caduca")}
                      onChange={(e) => setCaduca(e.target.value)}
                    />
                    <button
                      type="button"
                      className="btn-primary"
                      disabled={!motivo.trim() || !caduca}
                      onClick={() => void exceptuar(v)}
                    >
                      {t("segregacion.aprobar")}
                    </button>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}

function Simulador({
  directorio,
  roles,
}: {
  directorio: Directorio;
  roles: string[];
}) {
  const { t } = useTranslation();
  const usuarios = directorio.personas ?? [];
  const [usuario, setUsuario] = useState("");
  const [elegidos, setElegidos] = useState<string[]>([]);
  const [resultado, setResultado] = useState<{
    conflictos_nuevos: { regla: string; nombre: string; nivel: string }[];
    limpio: boolean;
  } | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const campoRoles = {
    nombre: "roles",
    tipo: "lista_multiple",
    obligatorio: false,
    titulo: t("segregacion.roles"),
    descripcion: "",
    opciones: roles,
    maximo: null,
    formato: "",
    subcampos: [],
    referencia: "",
  } as CampoEsquema;

  async function simular() {
    try {
      const r = await llamar<NonNullable<typeof resultado>>(
        "/api/v1/segregacion/simular",
        {
          metodo: "POST",
          cuerpo: { usuario_id: usuario, roles: elegidos },
        },
      );
      setResultado(r.datos);
      setFallo(null);
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("segregacion.simulador")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">
        {t("segregacion.simuladorAyuda")}
      </p>
      <div className="space-y-2">
        <select
          className="input-base"
          value={usuario}
          aria-label={t("segregacion.persona")}
          onChange={(e) => setUsuario(e.target.value)}
        >
          <option value="">{t("segregacion.persona")}</option>
          {usuarios.map((u) => (
            <option key={u.id} value={u.id}>
              {u.nombre || u.email}
            </option>
          ))}
        </select>
        <AvisoDelDirectorio directorio={directorio} />
        <Opciones
          campo={campoRoles}
          valor={elegidos}
          alCambiar={(v) => setElegidos(v as string[])}
        />
        <button
          type="button"
          className="btn-primary"
          disabled={!usuario || elegidos.length === 0}
          onClick={() => void simular()}
        >
          {t("segregacion.comprobar")}
        </button>
      </div>
      <div role="status" className="mt-3">
        {resultado ? (
          resultado.limpio ? (
            <p className="text-dato text-success">{t("segregacion.limpio")}</p>
          ) : (
            <ul className="space-y-1">
              {resultado.conflictos_nuevos.map((c) => (
                <li key={c.regla} className="text-dato">
                  <span className={cn("chip-dato mr-2", TONO[c.nivel] ?? "")}>
                    {t(`segregacion.niveles.${c.nivel}`)}
                  </span>
                  {c.nombre}
                </li>
              ))}
            </ul>
          )
        ) : null}
        {fallo ? <Fallo error={fallo} /> : null}
      </div>
    </section>
  );
}

function EditorDeRegla({
  regla,
  permisos,
  alCerrar,
  alGuardar,
}: {
  regla: Regla;
  permisos: string[];
  alCerrar: () => void;
  alGuardar: (codigo: string) => void;
}) {
  const { t } = useTranslation();
  const nueva = !regla.codigo;
  const [r, setR] = useState<Regla>(regla);
  const [fallo, setFallo] = useState<unknown>(null);
  const campo = (nombre: string): CampoEsquema =>
    ({
      nombre,
      tipo: "lista_multiple",
      obligatorio: true,
      titulo: t(`segregacion.campos.${nombre}`),
      descripcion: "",
      // Los que ya lleva la regla se conservan aunque ningún rol los dé hoy.
      opciones: [...new Set([...permisos, ...r.permisos_a, ...r.permisos_b])],
      maximo: null,
      formato: "",
      subcampos: [],
      referencia: "",
    }) as CampoEsquema;
  const listo =
    r.codigo.trim() &&
    r.nombre.trim() &&
    r.permisos_a.length > 0 &&
    r.permisos_b.length > 0;

  async function guardar() {
    try {
      const { codigo, ...cuerpo } = r;
      await llamar(
        `/api/v1/segregacion/reglas/${encodeURIComponent(codigo.trim())}`,
        { metodo: "PUT", cuerpo },
      );
      alGuardar(codigo.trim());
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-2">
        {nueva ? t("segregacion.nueva") : r.nombre}
      </h2>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("segregacion.campos.codigo")}
          <input
            className="input-base"
            value={r.codigo}
            disabled={!nueva}
            placeholder="SOD-…"
            onChange={(e) => setR({ ...r, codigo: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("segregacion.campos.nombre")}
          <input
            className="input-base"
            value={r.nombre}
            onChange={(e) => setR({ ...r, nombre: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
          {t("segregacion.campos.descripcion")}
          <input
            className="input-base"
            value={r.descripcion}
            onChange={(e) => setR({ ...r, descripcion: e.target.value })}
          />
        </label>
        <div className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("segregacion.campos.permisos_a")}
          <Opciones
            campo={campo("permisos_a")}
            valor={r.permisos_a}
            alCambiar={(v) => setR({ ...r, permisos_a: v as string[] })}
          />
        </div>
        <div className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("segregacion.campos.permisos_b")}
          <Opciones
            campo={campo("permisos_b")}
            valor={r.permisos_b}
            alCambiar={(v) => setR({ ...r, permisos_b: v as string[] })}
          />
        </div>
        <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
          {t("segregacion.campos.nivel")}
          <select
            className="input-base"
            value={r.nivel}
            onChange={(e) => setR({ ...r, nivel: e.target.value })}
          >
            {NIVELES.map((n) => (
              <option key={n} value={n}>
                {t(`segregacion.niveles.${n}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 self-end text-dato text-ink">
          <input
            type="checkbox"
            checked={r.activa}
            onChange={(e) => setR({ ...r, activa: e.target.checked })}
          />
          {t("segregacion.campos.activa")}
        </label>
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={!listo}
          onClick={() => void guardar()}
        >
          {t("segregacion.guardar")}
        </button>
        <button type="button" className="btn-secondary" onClick={alCerrar}>
          {t("segregacion.cancelar")}
        </button>
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
    </section>
  );
}

/**
 * Por qué algunos conflictos están permitidos: el motivo escrito y hasta
 * cuándo. Una excepción que no se puede leer no es un control, es papeleo. Las
 * caducadas se pueden ver, que es lo que distingue «no hay ninguna» de «todas
 * vencieron».
 */
function ExcepcionesAprobadas({
  nombre,
  reglas,
}: {
  nombre: (id: string) => string;
  reglas: Regla[];
}) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Excepcion[] | null>(null);
  const [caducadas, setCaducadas] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    llamar<Excepcion[]>(
      `/api/v1/segregacion/excepciones?incluir_caducadas=${caducadas}`,
    )
      .then((r) => setFilas(Array.isArray(r.datos) ? r.datos : []))
      .catch((e) => setFallo(e));
  }, [caducadas]);

  const regla = (codigo: string) =>
    reglas.find((r) => r.codigo === codigo)?.nombre ?? codigo;

  return (
    <section className="card mt-4 p-4">
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <h2 className="section-label">{t("segregacion.excepciones")}</h2>
        <label className="flex items-center gap-2 text-rotulo text-ink-muted">
          <input
            type="checkbox"
            checked={caducadas}
            onChange={(e) => setCaducadas(e.target.checked)}
          />
          {t("segregacion.verCaducadas")}
        </label>
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      {filas === null ? null : filas.length === 0 ? (
        <p className="text-dato text-ink-muted">
          {t("segregacion.sinExcepciones")}
        </p>
      ) : (
        <ul className="lista-acotada divide-y divide-ink-dim/30">
          {filas.map((e) => (
            <li key={e.id} className="py-2 text-dato">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-medium text-ink">
                  {nombre(e.usuario_id)}
                </span>
                <span className="text-ink-muted">{regla(e.regla_codigo)}</span>
                <span
                  className={cn(
                    "chip-dato",
                    e.vigente ? "chip-dato--aviso" : "",
                  )}
                >
                  {t(e.vigente ? "segregacion.hasta" : "segregacion.caducada", {
                    fecha: e.caduca_at.slice(0, 10),
                  })}
                </span>
              </div>
              <p className="text-rotulo text-ink-faint">{e.motivo}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
