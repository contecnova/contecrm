/**
 * Segundo factor verificado por el proveedor de la empresa (CRM-00.05.01.22).
 *
 * Hasta el 09-11-2026 había tres perfiles fijos genéricos que no llamaban a
 * nadie. Aquí se declara el proveedor —Okta Verify, Twilio Verify, Duo, RSA o
 * el que sea— como un perfil: dirección, autenticación, cuerpo y dónde
 * contesta. Las cuatro plantillas son datos que rellenan el formulario; el
 * login pregunta al perfil activo cuando el código no es el TOTP propio.
 *
 * Comprobado el 09-11-2026 contra un doble HTTP local: alta desde plantilla,
 * datos de la persona, «Probar» con un código bueno y uno malo, y la entrada
 * con contraseña y el código del proveedor sin TOTP propio.
 *
 * El secreto entra y no sale: la API sólo dice si lo hay.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  AvisoDelDirectorio,
  Error as Fallo,
  Vacio,
} from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { useDirectorio } from "@/lib/personas";

export interface PerfilMfa {
  id?: string;
  nombre: string;
  plantilla: string;
  activo: boolean;
  url: string;
  metodo: string;
  formato: string;
  autenticacion: {
    tipo?: string;
    usuario?: string;
    cabecera?: string;
    valor?: string;
  };
  tiene_secreto?: boolean;
  cabeceras: Record<string, string>;
  cuerpo: Record<string, unknown>;
  variables: Record<string, string>;
  campos_persona: string[];
  respuesta: { campo?: string; validos?: string[] };
  ultima_prueba_at?: string | null;
  ultima_prueba?: { valido?: boolean; motivo?: string };
  nota?: string;
}

interface Resultado {
  valido: boolean;
  estado_http: number | null;
  motivo: string;
  peticion: unknown;
}

interface Usuario {
  id: string;
  nombre: string;
  email: string;
}

const MARCAS = "{{codigo}}, {{email}}, {{usuario}}, {{var.X}}, {{persona.X}}";
const METODOS = ["POST", "PUT", "GET"];
const FORMATOS = ["json", "form"];
const AUTS = ["ninguna", "basica", "bearer", "cabecera"];

const VACIO: PerfilMfa = {
  nombre: "",
  plantilla: "",
  activo: false,
  url: "https://",
  metodo: "POST",
  formato: "json",
  autenticacion: { tipo: "ninguna" },
  cabeceras: {},
  cuerpo: { codigo: "{{codigo}}" },
  variables: {},
  campos_persona: [],
  respuesta: { campo: "", validos: [] },
};

const lista = (texto: string) =>
  texto
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

export function SegundoFactorPorProveedor({
  puedeCambiar,
}: {
  puedeCambiar: boolean;
}) {
  const { t } = useTranslation();
  const [perfiles, setPerfiles] = useState<PerfilMfa[] | null>(null);
  const [plantillas, setPlantillas] = useState<Record<string, PerfilMfa>>({});
  // Las personas a las que se vincula un perfil o con las que se prueba,
  // del directorio de la sesión: se pedían las doscientas primeras y las
  // demás no se podían elegir sin que nada lo dijera.
  const directorio = useDirectorio();
  const usuarios = directorio.personas ?? [];
  const [editando, setEditando] = useState<PerfilMfa | null>(null);
  const [aviso, setAviso] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    llamar<{ items: PerfilMfa[] }>("/api/v1/mfa-proveedor/perfiles")
      .then((r) => setPerfiles(r.datos.items ?? []))
      .catch((e) => {
        setPerfiles([]);
        setFallo(e);
      });
  }, []);
  useEffect(cargar, [cargar]);
  useEffect(() => {
    llamar<Record<string, PerfilMfa>>("/api/v1/mfa-proveedor/plantillas")
      .then((r) => setPlantillas(r.datos ?? {}))
      .catch(() => setPlantillas({}));
  }, []);

  async function borrar(p: PerfilMfa) {
    if (
      !p.id ||
      !window.confirm(
        t("seguridad.proveedor.borrarSeguro", { nombre: p.nombre }),
      )
    )
      return;
    try {
      await llamar(`/api/v1/mfa-proveedor/perfiles/${p.id}`, {
        metodo: "DELETE",
      });
      setAviso(t("seguridad.proveedor.borrado"));
      setEditando(null);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  function desdePlantilla(clave: string) {
    const base = clave ? plantillas[clave] : undefined;
    setAviso("");
    setEditando(
      base
        ? { ...VACIO, ...base, plantilla: clave, activo: false }
        : { ...VACIO },
    );
  }

  return (
    <section className="card p-4" aria-labelledby="mfa-proveedor-titulo">
      <h2 id="mfa-proveedor-titulo" className="section-label mb-1">
        {t("seguridad.proveedor.titulo")}
      </h2>
      <p className="mb-3 text-rotulo text-ink-faint">
        {t("seguridad.proveedor.ayuda")}
      </p>
      <div role="status" className="mb-2">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}

      {perfiles === null ? null : perfiles.length === 0 ? (
        <Vacio titulo={t("seguridad.proveedor.ninguno")} compacto />
      ) : (
        <Rejilla
          titulo={t("seguridad.proveedor.titulo")}
          acotada={false}
          cabeceras={[
            t("seguridad.proveedor.nombre"),
            t("seguridad.proveedor.plantilla"),
            t("seguridad.proveedor.activo"),
            t("seguridad.proveedor.url"),
            t("seguridad.proveedor.ultimaPrueba"),
            "",
          ]}
        >
          {perfiles.map((p) => (
            <tr key={p.id} className="border-b border-ink-dim/30 last:border-0">
              <Casilla>{p.nombre}</Casilla>
              <Casilla>
                {plantillas[p.plantilla]?.nombre ?? p.plantilla}
              </Casilla>
              <Casilla>
                {p.activo ? (
                  <span className="chip-dato chip-dato--si">
                    {t("seguridad.proveedor.activo")}
                  </span>
                ) : (
                  "—"
                )}
              </Casilla>
              <Casilla className="font-mono text-rotulo">{p.url}</Casilla>
              <Casilla>
                {p.ultima_prueba_at ? (
                  <span
                    className={
                      p.ultima_prueba?.valido
                        ? "chip-dato chip-dato--si"
                        : "chip-dato chip-dato--mal"
                    }
                    title={p.ultima_prueba?.motivo}
                  >
                    {p.ultima_prueba?.valido
                      ? t("seguridad.proveedor.vale")
                      : t("seguridad.proveedor.noVale")}
                  </span>
                ) : (
                  <span className="text-ink-faint">
                    {t("seguridad.proveedor.sinProbar")}
                  </span>
                )}
              </Casilla>
              <Casilla className="whitespace-nowrap text-right">
                <button
                  type="button"
                  className="btn-secondary mr-2"
                  onClick={() => {
                    setAviso("");
                    setEditando(p);
                  }}
                >
                  <Icono nombre="edit" tamano="sm" />
                  {t("seguridad.proveedor.editar")}
                </button>
                {puedeCambiar ? (
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => void borrar(p)}
                  >
                    <Icono nombre="delete" tamano="sm" />
                    {t("seguridad.proveedor.borrar")}
                  </button>
                ) : null}
              </Casilla>
            </tr>
          ))}
        </Rejilla>
      )}

      {puedeCambiar ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select
            className="input-base"
            aria-label={t("seguridad.proveedor.desdePlantilla")}
            value=""
            onChange={(e) =>
              desdePlantilla(e.target.value === "_" ? "" : e.target.value)
            }
          >
            <option value="">{t("seguridad.proveedor.desdePlantilla")}</option>
            <option value="_">{t("seguridad.proveedor.sinPlantilla")}</option>
            {Object.entries(plantillas).map(([clave, p]) => (
              <option key={clave} value={clave}>
                {p.nombre}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {editando ? <AvisoDelDirectorio directorio={directorio} /> : null}
      {editando ? (
        <Editor
          key={editando.id ?? `nuevo-${editando.plantilla}`}
          inicial={editando}
          puedeCambiar={puedeCambiar}
          usuarios={usuarios}
          alGuardar={(p) => {
            setAviso(t("seguridad.proveedor.guardado"));
            setEditando(p);
            cargar();
          }}
          alCancelar={() => setEditando(null)}
        />
      ) : null}
    </section>
  );
}

function Editor({
  inicial,
  puedeCambiar,
  usuarios,
  alGuardar,
  alCancelar,
}: {
  inicial: PerfilMfa;
  puedeCambiar: boolean;
  usuarios: Usuario[];
  alGuardar: (p: PerfilMfa) => void;
  alCancelar: () => void;
}) {
  const { t } = useTranslation();
  const [p, setP] = useState<PerfilMfa>(inicial);
  const [secreto, setSecreto] = useState("");
  const [cuerpo, setCuerpo] = useState(
    JSON.stringify(inicial.cuerpo ?? {}, null, 2),
  );
  const [cabeceras, setCabeceras] = useState(
    JSON.stringify(inicial.cabeceras ?? {}, null, 2),
  );
  const [campos, setCampos] = useState(
    (inicial.campos_persona ?? []).join(", "),
  );
  const [validos, setValidos] = useState(
    (inicial.respuesta?.validos ?? []).join(", "),
  );
  const [guardando, setGuardando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [errorJson, setErrorJson] = useState("");
  const aut = p.autenticacion ?? { tipo: "ninguna" };

  async function guardar() {
    setFallo(null);
    setErrorJson("");
    let cuerpoJ: Record<string, unknown>;
    let cabecerasJ: Record<string, string>;
    try {
      cuerpoJ = JSON.parse(cuerpo || "{}");
    } catch {
      setErrorJson(
        t("seguridad.proveedor.jsonMal", {
          campo: t("seguridad.proveedor.cuerpo", { marcas: "" }),
        }),
      );
      return;
    }
    try {
      cabecerasJ = JSON.parse(cabeceras || "{}");
    } catch {
      setErrorJson(
        t("seguridad.proveedor.jsonMal", {
          campo: t("seguridad.proveedor.cabeceras"),
        }),
      );
      return;
    }
    setGuardando(true);
    try {
      const datos = {
        nombre: p.nombre,
        plantilla: p.plantilla,
        activo: p.activo,
        url: p.url,
        metodo: p.metodo,
        formato: p.formato,
        autenticacion: aut,
        secreto,
        cabeceras: cabecerasJ,
        cuerpo: cuerpoJ,
        variables: p.variables ?? {},
        campos_persona: lista(campos),
        respuesta: { campo: p.respuesta?.campo ?? "", validos: lista(validos) },
      };
      const r = p.id
        ? await llamar<PerfilMfa>(`/api/v1/mfa-proveedor/perfiles/${p.id}`, {
            metodo: "PUT",
            cuerpo: datos,
          })
        : await llamar<PerfilMfa>("/api/v1/mfa-proveedor/perfiles", {
            metodo: "POST",
            cuerpo: datos,
          });
      setSecreto("");
      alGuardar(r.datos);
    } catch (e) {
      setFallo(e);
    } finally {
      setGuardando(false);
    }
  }

  const campo = (
    etiqueta: string,
    valor: string,
    alCambiar: (v: string) => void,
    extra: { tipo?: string; ayuda?: string; mono?: boolean } = {},
  ) => (
    <label className="flex flex-col gap-1 text-rotulo">
      <span className="text-ink-muted">{etiqueta}</span>
      <input
        className={extra.mono ? "input-base font-mono" : "input-base"}
        type={extra.tipo ?? "text"}
        aria-label={etiqueta}
        value={valor}
        disabled={!puedeCambiar}
        onChange={(e) => alCambiar(e.target.value)}
        autoComplete="off"
      />
      {extra.ayuda ? (
        <span className="text-ink-faint">{extra.ayuda}</span>
      ) : null}
    </label>
  );

  const desplegable = (
    etiqueta: string,
    valor: string,
    opciones: string[],
    alCambiar: (v: string) => void,
    rotulo: (o: string) => string = (o) => o,
  ) => (
    <label className="flex flex-col gap-1 text-rotulo">
      <span className="text-ink-muted">{etiqueta}</span>
      <select
        className="input-base"
        value={valor}
        disabled={!puedeCambiar}
        onChange={(e) => alCambiar(e.target.value)}
      >
        {opciones.map((o) => (
          <option key={o} value={o}>
            {rotulo(o)}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="mt-4 flex flex-col gap-4 border-t border-ink-dim/30 pt-4">
      {p.nota ? <p className="text-rotulo text-ink-faint">{p.nota}</p> : null}
      <div className="grid gap-3 md:grid-cols-2">
        {campo(t("seguridad.proveedor.nombre"), p.nombre, (v) =>
          setP({ ...p, nombre: v }),
        )}
        <label className="flex items-center gap-2 text-rotulo">
          <input
            type="checkbox"
            checked={p.activo}
            disabled={!puedeCambiar}
            onChange={(e) => setP({ ...p, activo: e.target.checked })}
          />
          <span>
            {t("seguridad.proveedor.activo")}
            <span className="block text-ink-faint">
              {t("seguridad.proveedor.activoAyuda")}
            </span>
          </span>
        </label>
        {campo(
          t("seguridad.proveedor.url"),
          p.url,
          (v) => setP({ ...p, url: v }),
          {
            mono: true,
          },
        )}
        <div className="grid grid-cols-2 gap-3">
          {desplegable(
            t("seguridad.proveedor.metodo"),
            p.metodo,
            METODOS,
            (v) => setP({ ...p, metodo: v }),
          )}
          {desplegable(
            t("seguridad.proveedor.formato"),
            p.formato,
            FORMATOS,
            (v) => setP({ ...p, formato: v }),
          )}
        </div>
        {desplegable(
          t("seguridad.proveedor.autenticacion"),
          aut.tipo ?? "ninguna",
          AUTS,
          (v) => setP({ ...p, autenticacion: { ...aut, tipo: v } }),
          (o) => t(`seguridad.proveedor.autTipos.${o}`),
        )}
        {aut.tipo === "basica"
          ? campo(t("seguridad.proveedor.autUsuario"), aut.usuario ?? "", (v) =>
              setP({ ...p, autenticacion: { ...aut, usuario: v } }),
            )
          : null}
        {aut.tipo === "cabecera" ? (
          <>
            {campo(
              t("seguridad.proveedor.autCabecera"),
              aut.cabecera ?? "",
              (v) => setP({ ...p, autenticacion: { ...aut, cabecera: v } }),
            )}
            {campo(
              t("seguridad.proveedor.autValor", { marca: "{{secreto}}" }),
              aut.valor ?? "",
              (v) => setP({ ...p, autenticacion: { ...aut, valor: v } }),
              { mono: true },
            )}
          </>
        ) : null}
        {aut.tipo !== "ninguna"
          ? campo(t("seguridad.proveedor.secreto"), secreto, setSecreto, {
              tipo: "password",
              ayuda: p.tiene_secreto
                ? t("seguridad.proveedor.secretoGuardado")
                : t("seguridad.proveedor.secretoNuevo"),
            })
          : null}
      </div>

      {Object.keys(p.variables ?? {}).length > 0 ? (
        <div>
          <h3 className="section-label mb-2">
            {t("seguridad.proveedor.variables")}
          </h3>
          <div className="grid gap-3 md:grid-cols-2">
            {Object.entries(p.variables).map(([k, v]) => (
              <div key={k}>
                {campo(k, String(v ?? ""), (nuevo) =>
                  setP({ ...p, variables: { ...p.variables, [k]: nuevo } }),
                )}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-rotulo">
          <span className="text-ink-muted">
            {t("seguridad.proveedor.cuerpo", { marcas: MARCAS })}
          </span>
          <textarea
            className="input-base min-h-[8rem] font-mono"
            value={cuerpo}
            disabled={!puedeCambiar}
            onChange={(e) => setCuerpo(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-rotulo">
          <span className="text-ink-muted">
            {t("seguridad.proveedor.cabeceras")}
          </span>
          <textarea
            className="input-base min-h-[8rem] font-mono"
            value={cabeceras}
            disabled={!puedeCambiar}
            onChange={(e) => setCabeceras(e.target.value)}
          />
        </label>
        {campo(t("seguridad.proveedor.camposPersona"), campos, setCampos)}
        {campo(
          t("seguridad.proveedor.respuestaCampo"),
          p.respuesta?.campo ?? "",
          (v) => setP({ ...p, respuesta: { ...p.respuesta, campo: v } }),
          { mono: true },
        )}
        {campo(t("seguridad.proveedor.respuestaValidos"), validos, setValidos)}
      </div>

      {errorJson ? (
        <p className="text-dato text-danger" role="alert">
          {errorJson}
        </p>
      ) : null}
      {fallo ? <Fallo error={fallo} /> : null}
      {puedeCambiar ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            disabled={guardando || !p.nombre.trim()}
            onClick={() => void guardar()}
          >
            {guardando
              ? t("seguridad.proveedor.guardando")
              : t("seguridad.proveedor.guardar")}
          </button>
          <button type="button" className="btn-secondary" onClick={alCancelar}>
            {t("seguridad.proveedor.cancelar")}
          </button>
        </div>
      ) : null}

      {p.id ? (
        <Personas perfil={p} usuarios={usuarios} puedeCambiar={puedeCambiar} />
      ) : null}
      {p.id && puedeCambiar ? <Probar perfil={p} usuarios={usuarios} /> : null}
    </div>
  );
}

function Personas({
  perfil,
  usuarios,
  puedeCambiar,
}: {
  perfil: PerfilMfa;
  usuarios: Usuario[];
  puedeCambiar: boolean;
}) {
  const { t } = useTranslation();
  const [vinculos, setVinculos] = useState<
    { usuario_id: string; datos: Record<string, string> }[]
  >([]);
  const [quien, setQuien] = useState("");
  const [datos, setDatos] = useState<Record<string, string>>({});
  const [hecho, setHecho] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    llamar<{ items: { usuario_id: string; datos: Record<string, string> }[] }>(
      `/api/v1/mfa-proveedor/perfiles/${perfil.id}/personas`,
    )
      .then((r) => setVinculos(r.datos.items ?? []))
      .catch(() => setVinculos([]));
  }, [perfil.id]);
  useEffect(cargar, [cargar]);

  if ((perfil.campos_persona ?? []).length === 0) return null;
  const nombre = (id: string) => {
    const u = usuarios.find((x) => x.id === id);
    return u ? u.nombre || u.email : `${id.slice(0, 8)}…`;
  };

  async function guardar() {
    setFallo(null);
    setHecho(false);
    try {
      await llamar(
        `/api/v1/mfa-proveedor/perfiles/${perfil.id}/personas/${quien}`,
        {
          metodo: "PUT",
          cuerpo: { datos },
        },
      );
      setHecho(true);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <h3 className="section-label">{t("seguridad.proveedor.personas")}</h3>
      <p className="text-rotulo text-ink-faint">
        {t("seguridad.proveedor.personasAyuda")}
      </p>
      {vinculos.length === 0 ? (
        <Vacio titulo={t("seguridad.proveedor.nadieVinculado")} compacto />
      ) : (
        <Rejilla
          titulo={t("seguridad.proveedor.personas")}
          acotada={false}
          cabeceras={[
            t("seguridad.proveedor.persona"),
            ...perfil.campos_persona,
          ]}
        >
          {vinculos.map((v) => (
            <tr
              key={v.usuario_id}
              className="border-b border-ink-dim/30 last:border-0"
            >
              <Casilla>{nombre(v.usuario_id)}</Casilla>
              {perfil.campos_persona.map((c) => (
                <Casilla key={c} className="font-mono">
                  {v.datos[c] ?? "—"}
                </Casilla>
              ))}
            </tr>
          ))}
        </Rejilla>
      )}
      {puedeCambiar ? (
        <div className="flex flex-wrap items-end gap-2">
          <select
            className="input-base"
            aria-label={t("seguridad.proveedor.persona")}
            value={quien}
            onChange={(e) => {
              setQuien(e.target.value);
              setDatos(
                vinculos.find((v) => v.usuario_id === e.target.value)?.datos ??
                  {},
              );
            }}
          >
            <option value="">{t("seguridad.proveedor.elegirPersona")}</option>
            {usuarios.map((u) => (
              <option key={u.id} value={u.id}>
                {u.nombre || u.email}
              </option>
            ))}
          </select>
          {perfil.campos_persona.map((c) => (
            <input
              key={c}
              className="input-base font-mono"
              aria-label={c}
              placeholder={c}
              value={datos[c] ?? ""}
              onChange={(e) => setDatos({ ...datos, [c]: e.target.value })}
            />
          ))}
          <button
            type="button"
            className="btn-secondary"
            disabled={!quien}
            onClick={() => void guardar()}
          >
            {t("seguridad.proveedor.vincular")}
          </button>
          <span role="status" className="text-rotulo text-success">
            {hecho ? t("seguridad.proveedor.vinculado") : ""}
          </span>
        </div>
      ) : null}
      {fallo ? <Fallo error={fallo} /> : null}
    </div>
  );
}

function Probar({
  perfil,
  usuarios,
}: {
  perfil: PerfilMfa;
  usuarios: Usuario[];
}) {
  const { t } = useTranslation();
  const [quien, setQuien] = useState("");
  const [codigo, setCodigo] = useState("");
  const [probando, setProbando] = useState(false);
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  async function probar() {
    setProbando(true);
    setFallo(null);
    setResultado(null);
    try {
      const r = await llamar<Resultado>(
        `/api/v1/mfa-proveedor/perfiles/${perfil.id}/probar`,
        { metodo: "POST", cuerpo: { usuario_id: quien, codigo } },
      );
      setResultado(r.datos);
    } catch (e) {
      setFallo(e);
    } finally {
      setProbando(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <h3 className="section-label">{t("seguridad.proveedor.probar")}</h3>
      <p className="text-rotulo text-ink-faint">
        {t("seguridad.proveedor.probarAyuda")}
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <select
          className="input-base"
          aria-label={t("seguridad.proveedor.persona")}
          value={quien}
          onChange={(e) => setQuien(e.target.value)}
        >
          <option value="">{t("seguridad.proveedor.elegirPersona")}</option>
          {usuarios.map((u) => (
            <option key={u.id} value={u.id}>
              {u.nombre || u.email}
            </option>
          ))}
        </select>
        <input
          className="input-base font-mono"
          aria-label={t("seguridad.proveedor.codigo")}
          placeholder={t("seguridad.proveedor.codigo")}
          value={codigo}
          inputMode="numeric"
          autoComplete="one-time-code"
          onChange={(e) => setCodigo(e.target.value)}
        />
        <button
          type="button"
          className="btn-primary"
          disabled={!quien || !codigo.trim() || probando}
          onClick={() => void probar()}
        >
          {probando
            ? t("seguridad.proveedor.probando")
            : t("seguridad.proveedor.probar")}
        </button>
      </div>
      <div role="status">
        {resultado ? (
          <div className="flex flex-col gap-1">
            <p
              className={
                resultado.valido
                  ? "text-dato text-success"
                  : "text-dato text-danger"
              }
            >
              {resultado.valido
                ? t("seguridad.proveedor.resultadoVale")
                : t("seguridad.proveedor.resultadoNoVale")}{" "}
              {resultado.estado_http !== null
                ? t("seguridad.proveedor.http", {
                    estado: resultado.estado_http,
                  })
                : null}
            </p>
            <p className="text-rotulo text-ink-muted">{resultado.motivo}</p>
            {resultado.peticion ? (
              <details>
                <summary className="cursor-pointer text-rotulo text-ink-muted">
                  {t("seguridad.proveedor.peticion")}
                </summary>
                <pre className="mt-1 overflow-x-auto text-rotulo">
                  {JSON.stringify(resultado.peticion, null, 2)}
                </pre>
              </details>
            ) : null}
          </div>
        ) : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
    </div>
  );
}
