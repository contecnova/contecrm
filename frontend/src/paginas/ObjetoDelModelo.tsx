/**
 * Un objeto del modelo de datos, con todo lo suyo (CRM-00.04.01.02,
 * CRM-00.04.01.04, CRM-00.04.01.05, CRM-00.04.01.06, CRM-00.04.01.07,
 * CRM-00.04.01.08, CRM-00.04.01.09, CRM-00.04.01.10, CRM-00.04.03.01,
 * CRM-00.04.03.02, CRM-00.04.03.03, CRM-00.04.03.04, CRM-00.04.03.06,
 * CRM-00.04.03.07, CRM-00.04.03.10, CRM-00.04.03.11, CRM-00.04.03.12).
 *
 * **La familia entera estaba publicada y sin puerta.** El módulo «Modelo de
 * datos» listaba los objetos y ahí se acababa: las filas no abrían, y como los
 * paneles de una ficha se construyen a partir de los `GET` que devuelven
 * lista, los campos de un objeto, sus validaciones, sus tipos de registro, sus
 * límites y la trazabilidad del esquema no se alcanzaban desde ninguna
 * pantalla. Lo que se puede hacer por API —añadir un campo, publicarlo,
 * renombrarlo, materializarlo— no se podía ni mirar.
 *
 * **Por qué una pantalla a medida y no la ficha genérica.** Las rutas hijas de
 * un objeto se dirigen por su **nombre** (`/objetos/{nombre}/describe`) y la
 * ficha genérica pasa el identificador: los paneles habrían salido en 404,
 * que es peor que no tenerlos. Aquí se abre por identificador —que es lo que
 * lleva la fila—, se lee el nombre de la respuesta y con él se pide lo demás.
 *
 * **Y es una pregunta, no un volcado.** La que se hace de verdad delante de un
 * modelo de datos es «¿puedo quitar este campo?», y sin la trazabilidad la
 * respuesta es siempre «no lo sé» — que es como un modelo acaba con
 * trescientos campos de los que nadie recuerda la mitad. Por eso el panel que
 * manda es el de los campos **con sus escrituras al lado**, y los que no se
 * han escrito nunca salen marcados.
 *
 * **Y lo que una empresa puede cambiar sin escribir código llegaba hasta
 * aquí y se paraba.** Estaba todo publicado y sin puerta: el formulario que
 * le toca a cada rol, lo que la IA entiende de este objeto, qué campos ya
 * justifican una columna real, la máquina de estados, cómo se renombra un
 * campo sin romper a quien llama por el nombre viejo, y cómo se lleva esta
 * configuración a otro entorno. Seis preguntas que se hacen delante de un
 * modelo de datos y que sólo se podían contestar por API.
 *
 * Cada panel enseña **lo que devuelve su ruta**, no una promesa: la cobertura
 * semántica sale con su porcentaje y con los campos que faltan por nombre, y
 * los candidatos a columna salen con sus escrituras. Un panel que dijera «la
 * IA entiende tus datos» sin el número sería justo lo que este producto llama
 * en otro sitio «la razón de la mayoría de los proyectos de IA
 * decepcionantes».
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import {
  BotonesDeRegistro,
  ConfirmarBorrado,
  FormularioDeEdicion,
  useEdicion,
} from "@/componentes/Edicion";
import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { escalar } from "@/lib/formato";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";

interface Previsualizacion {
  version_actual: number;
  version_al_publicar: number;
  anadidos?: unknown[];
  retirados?: unknown[];
  cambiados?: unknown[];
  /** Nulo cuando no se ha podido contar, que no es lo mismo que cero. */
  registros: number | null;
  registros_sin_rellenar?: number | null;
  avisos?: string[];
  hay_cambios: boolean;
  seguro: boolean;
}

interface Objeto {
  id: string;
  nombre: string;
  etiqueta: string;
  etiqueta_plural: string;
  descripcion: string;
  origen: string;
  icono: string;
  activo: boolean;
  estados: Record<string, unknown>;
}

interface Campo {
  id: string;
  nombre: string;
  etiqueta: string;
  tipo: string;
  obligatorio: boolean;
  unico: boolean;
  solo_lectura: boolean;
  sensibilidad: string;
  deprecado: boolean;
}

interface Regla {
  id: string;
  nombre: string;
  mensaje: string;
  momento: string;
  activa: boolean;
}

interface Describe {
  objeto: Objeto;
  campos: Campo[];
  reglas: Regla[];
  layouts: Record<string, unknown>[];
}

interface Limites {
  campos: number;
  tope: number;
  pct: number;
  en_aviso: boolean;
  al_llegar: string;
}

interface CampoRastreado {
  campo: string;
  tipo: string;
  creado_at: string | null;
  deprecado: boolean;
  escrituras: number;
  ultima_escritura_at: string | null;
  materializado: boolean;
  se_puede_retirar: boolean;
}

interface Trazabilidad {
  objeto: string;
  campos: CampoRastreado[];
  sin_usar: string[];
  publicaciones: {
    version: number;
    at: string | null;
    nota: string;
    campos: number;
  }[];
}

interface Diseno {
  hay_diseno: boolean;
  nombre?: string;
  secciones?: unknown[];
  porque: string;
}

interface Semantica {
  campos: unknown[];
  fuera_por_sensibles: string[];
  fuera_por_internos: string[];
  sin_describir: string[];
  aviso: string;
  cobertura: {
    medible: boolean;
    campos?: number;
    explotables?: number;
    pct?: number;
    que_significa?: string;
    porque?: string;
  };
}

interface Candidatos {
  umbral: number;
  candidatos: { campo: string; escrituras: number }[];
  por_que_no_siempre: string;
}

/** Lo que analytics publica de este objeto para informes. */
interface ModeloSemantico {
  objetos: { nombre: string; campos: unknown[] }[];
  excluidos_por_sensibilidad: string[];
  motivo_exclusion: string;
}

interface TipoRegistro {
  clave: string;
  nombre: string;
  por_defecto: boolean;
  campos_ocultos: string[];
}

export function ObjetoDelModelo() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [objeto, setObjeto] = useState<Objeto | null>(null);
  const [describe, setDescribe] = useState<Describe | null>(null);
  const [limites, setLimites] = useState<Limites | null>(null);
  const [rastro, setRastro] = useState<Trazabilidad | null>(null);
  const [tipos, setTipos] = useState<TipoRegistro[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const navegar = useNavigate();
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  // El mismo recurso que lista el módulo, para que editar pase por la misma
  // ruta y el mismo contrato que el listado.
  const moduloModelo = moduloDe("modelo");
  const recurso = moduloModelo ? recursoDe(moduloModelo, "objeto") : undefined;
  const { ruta, puedeEditar, puedeBorrar } = useEdicion(recurso, id);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    // Primero el objeto, por su identificador —que es lo que lleva la fila del
    // listado—, y con su NOMBRE se pide lo demás: las rutas hijas se dirigen
    // por nombre, y mandarles el identificador da un 404 en cada panel.
    llamar<Objeto>(`/api/v1/metadata/objetos/${id}`, { signal: control.signal })
      .then(({ datos }) => {
        setObjeto(datos);
        const nombre = encodeURIComponent(datos.nombre);
        // En paralelo y cada una con su propio fallo: que no se pueda leer la
        // trazabilidad no puede dejar sin ver los campos, que es a lo que se
        // entra.
        void llamar<Describe>(`/api/v1/metadata/objetos/${nombre}/describe`, {
          signal: control.signal,
        })
          .then((r) => setDescribe(r.datos))
          .catch(salvoCancelacion(setFallo));
        void llamar<Limites>(`/api/v1/metadata/objetos/${nombre}/limites`, {
          signal: control.signal,
        })
          .then((r) => setLimites(r.datos))
          .catch(() => undefined);
        void llamar<Trazabilidad>(
          `/api/v1/metadata/objetos/${nombre}/trazabilidad`,
          {
            signal: control.signal,
          },
        )
          .then((r) => setRastro(r.datos))
          .catch(() => undefined);
        void llamar<TipoRegistro[]>(
          `/api/v1/metadata/objetos/${nombre}/tipos`,
          {
            signal: control.signal,
          },
        )
          .then((r) => setTipos(r.datos))
          .catch(() => undefined);
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  // Al cambiar de objeto se sale de edición: esta pantalla no se desmonta al
  // ir de uno a otro, y el «¿seguro?» a medias quedaría apuntando al nuevo.
  useEffect(() => {
    setEditando(false);
    setConfirmando(false);
  }, [id]);

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/m/modelo");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !objeto) return <Fallo error={fallo} reintentar={cargar} />;
  if (!objeto) return <Cargando />;

  const escrituras = new Map((rastro?.campos ?? []).map((c) => [c.campo, c]));

  return (
    <>
      <CabeceraPagina
        titulo={objeto.etiqueta || objeto.nombre}
        icono={objeto.icono || "schema"}
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <span className="badge badge-muted">{objeto.nombre}</span>
            {/* De dónde sale: lo que trae el producto no se toca igual que lo
                que añadió esta empresa. */}
            <span className="chip-dato">{objeto.origen}</span>
            {objeto.descripcion ? (
              <span className="text-2xs text-ink-faint">
                {objeto.descripcion}
              </span>
            ) : null}
          </span>
        }
      />

      {!editando ? (
        <div className="mb-3">
          <BotonesDeRegistro
            puedeEditar={puedeEditar}
            puedeBorrar={puedeBorrar}
            alEditar={() => setEditando(true)}
            alBorrar={() => setConfirmando(true)}
          />
        </div>
      ) : null}

      {confirmando ? (
        <ConfirmarBorrado
          enviando={borrando}
          alBorrar={() => void borrar()}
          alCancelar={() => setConfirmando(false)}
        />
      ) : null}

      {editando && recurso ? (
        <FormularioDeEdicion
          recurso={recurso}
          ruta={ruta}
          valores={objeto as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      {fallo ? (
        <div className="mb-3">
          <Fallo error={fallo} reintentar={cargar} />
        </div>
      ) : null}

      {/* ── Cuánto sitio queda ──────────────────────────────────────────── */}
      {limites ? (
        <section className="card mb-4 p-4">
          <h2 className="section-label mb-1">{t("modeloDatos.limites")}</h2>
          <p
            className={
              limites.en_aviso
                ? "text-sm font-medium text-danger"
                : "text-sm font-medium text-ink"
            }
          >
            {t("modeloDatos.camposDeTope", {
              campos: limites.campos,
              tope: limites.tope,
            })}
          </p>
          {/* Qué pasa al llegar, dicho antes de llegar: un tope que sólo se
              explica cuando se alcanza se explica tarde. */}
          <p className="mt-1 text-3xs text-ink-muted">{limites.al_llegar}</p>
        </section>
      ) : null}

      {/* ── Qué pasaría al publicar ─────────────────────────────────────
          Va ANTES de los campos a propósito: se mira justo después de tocar
          uno y antes de pulsar publicar, que es el único momento en el que
          sirve de algo. */}
      <QuePasaSiPublico objeto={objeto.nombre} />

      {/* ── Los campos, con sus escrituras al lado ──────────────────────── */}
      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("modeloDatos.campos")}</h2>
        <p className="mb-3 text-3xs text-ink-faint">
          {t("modeloDatos.camposAyuda")}
        </p>
        {!describe ? <Cargando /> : null}
        {describe && describe.campos.length === 0 ? (
          <Vacio titulo={t("modeloDatos.sinCampos")} compacto />
        ) : null}
        {describe && describe.campos.length > 0 ? (
          <ul className="divide-y divide-ink-dim/30">
            {describe.campos.map((campo) => {
              const uso = escrituras.get(campo.nombre);
              return (
                <li
                  key={campo.id}
                  className="flex flex-wrap items-baseline gap-x-3 py-1.5"
                >
                  <span className="text-2xs font-medium text-ink">
                    {campo.etiqueta || campo.nombre}
                  </span>
                  <span className="text-3xs text-ink-faint">
                    {campo.nombre}
                  </span>
                  <span className="chip-dato">{campo.tipo}</span>
                  {/* Un campo CALCULADO no se teclea: su fórmula se valida al
                      guardarla, no al leer el primer registro. Verlo marcado
                      es lo que evita que alguien busque por qué «no se puede
                      rellenar». */}
                  {campo.tipo === "formula" || campo.tipo === "rollup" ? (
                    <span className="chip-dato chip-dato--si">
                      {t("modeloDatos.calculado")}
                    </span>
                  ) : null}
                  {campo.obligatorio ? (
                    <span className="chip-dato">
                      {t("modeloDatos.obligatorio")}
                    </span>
                  ) : null}
                  {campo.unico ? (
                    <span className="chip-dato">{t("modeloDatos.unico")}</span>
                  ) : null}
                  {campo.solo_lectura ? (
                    <span className="chip-dato">
                      {t("modeloDatos.soloLectura")}
                    </span>
                  ) : null}
                  {campo.sensibilidad && campo.sensibilidad !== "normal" ? (
                    <span className="chip-dato chip-dato--no">
                      {campo.sensibilidad}
                    </span>
                  ) : null}
                  {campo.deprecado ? (
                    <span className="chip-dato chip-dato--no">
                      {t("modeloDatos.deprecado")}
                    </span>
                  ) : null}
                  {/* Lo que contesta «¿puedo quitarlo?»: cuántas veces se ha
                      ESCRITO. Leer mide quién mira; escribir mide si el campo
                      se rellena. */}
                  {uso ? (
                    <span
                      className={
                        uso.escrituras === 0
                          ? "text-3xs text-danger"
                          : "text-3xs text-ink-muted"
                      }
                    >
                      {uso.escrituras === 0
                        ? t("modeloDatos.nuncaEscrito")
                        : t("modeloDatos.escrituras", {
                            cuantas: uso.escrituras,
                          })}
                    </span>
                  ) : null}
                  {uso?.materializado ? (
                    <span className="chip-dato chip-dato--si">
                      {t("modeloDatos.materializado")}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : null}
        {rastro && rastro.sin_usar.length > 0 ? (
          <p className="mt-3 text-3xs text-ink-muted">
            <Icono nombre="info" />{" "}
            {t("modeloDatos.sinUsar", { cuantos: rastro.sin_usar.length })}
          </p>
        ) : null}
        {/* Que un campo añadido aquí entre solo en la API no es una promesa
            del folleto: las escrituras de arriba las cuenta la API al
            recibirlas, así que un número mayor que cero ES la prueba. */}
        <p className="mt-3 text-3xs text-ink-faint">
          <span className="font-medium text-ink-muted">
            {t("modeloDatos.yaEstaEnLaApi")}
          </span>{" "}
          {t("modeloDatos.yaEstaEnLaApiAyuda")}
        </p>
      </section>

      {/* ── Validaciones y tipos de registro ────────────────────────────── */}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-4">
          <h2 className="section-label mb-1">{t("modeloDatos.reglas")}</h2>
          <p className="mb-2 text-3xs text-ink-faint">
            {t("modeloDatos.reglasAyuda")}
          </p>
          {describe && describe.reglas.length === 0 ? (
            <Vacio titulo={t("modeloDatos.sinReglas")} compacto />
          ) : null}
          <ul className="divide-y divide-ink-dim/30">
            {(describe?.reglas ?? []).map((regla) => (
              <li key={regla.id} className="py-1.5">
                <div className="flex flex-wrap items-baseline gap-x-3">
                  <span className="text-2xs font-medium text-ink">
                    {regla.nombre}
                  </span>
                  <span className="chip-dato">{regla.momento}</span>
                  {!regla.activa ? (
                    <span className="chip-dato chip-dato--no">
                      {t("modeloDatos.apagada")}
                    </span>
                  ) : null}
                </div>
                {/* El mensaje que verá quien la incumpla: es la mitad de la
                    regla, y sin él no se puede juzgar si está bien escrita. */}
                <p className="text-3xs text-ink-muted">{regla.mensaje}</p>
              </li>
            ))}
          </ul>
        </section>

        <section className="card p-4">
          <h2 className="section-label mb-1">{t("modeloDatos.tipos")}</h2>
          <p className="mb-2 text-3xs text-ink-faint">
            {t("modeloDatos.tiposAyuda")}
          </p>
          {tipos && tipos.length === 0 ? (
            <Vacio titulo={t("modeloDatos.sinTipos")} compacto />
          ) : null}
          <ul className="divide-y divide-ink-dim/30">
            {(tipos ?? []).map((tipo) => (
              <li
                key={tipo.clave}
                className="flex flex-wrap items-baseline gap-x-3 py-1.5"
              >
                <span className="text-2xs font-medium text-ink">
                  {tipo.nombre}
                </span>
                <span className="text-3xs text-ink-faint">{tipo.clave}</span>
                {tipo.por_defecto ? (
                  <span className="chip-dato chip-dato--si">
                    {t("modeloDatos.porDefecto")}
                  </span>
                ) : null}
                {tipo.campos_ocultos.length > 0 ? (
                  <span className="text-3xs text-ink-muted">
                    {t("modeloDatos.ocultos", {
                      cuantos: tipo.campos_ocultos.length,
                    })}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      </div>

      {/* ── Lo que esta empresa puede cambiar sin escribir código ───────
          Van juntos porque se miran juntos: quién ve qué formulario, qué
          entiende la IA, qué campo ya pide columna, por qué estados pasa el
          registro y cómo se lleva todo esto a otro entorno. */}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <ElDisenoQueTeToca objeto={objeto.nombre} />
        <LoQueEntiendeLaIa objeto={objeto.nombre} />
        <CamposQueYaPidenColumna objeto={objeto.nombre} />
        <LaMaquinaDeEstados estados={objeto.estados} />
        <RenombrarYLlevarse objeto={objeto.nombre} rastro={rastro} />
      </div>

      {/* ── Qué se publicó y cuándo ─────────────────────────────────────── */}
      {rastro && rastro.publicaciones.length > 0 ? (
        <section className="card mt-4 p-4">
          <h2 className="section-label mb-1">
            {t("modeloDatos.publicaciones")}
          </h2>
          <p className="mb-2 text-3xs text-ink-faint">
            {t("modeloDatos.publicacionesAyuda")}
          </p>
          <ul className="divide-y divide-ink-dim/30">
            {rastro.publicaciones.map((pub) => (
              <li
                key={pub.version}
                className="flex flex-wrap items-baseline gap-x-3 py-1.5"
              >
                <span className="text-2xs font-medium text-ink">
                  v{pub.version}
                </span>
                <span className="text-3xs text-ink-faint">
                  {escalar(pub.at, "at")}
                </span>
                <span className="text-3xs text-ink-muted">
                  {t("modeloDatos.camposEnPublicacion", {
                    cuantos: pub.campos,
                  })}
                </span>
                {pub.nota ? (
                  <span className="text-3xs text-ink-muted">{pub.nota}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

/**
 * Qué pasaría al publicar este esquema (`CRM-00.04.03.09`).
 *
 * Quien añade un campo obligatorio a un objeto con ochenta mil registros no
 * sabe que los ochenta mil se quedan sin rellenar — y no lo sabe hasta que
 * alguien intenta guardar uno viejo y no puede. Esto lo dice antes, que es la
 * diferencia entre una decisión y una sorpresa.
 *
 * El servidor lo contestaba desde el principio y no había dónde preguntarlo.
 *
 * **Y cuando no se puede contar, se dice.** «No se ha podido contar» y «no
 * afecta a nadie» se pintan igual y significan lo contrario: el primero pide
 * mirar, el segundo deja publicar tranquilo.
 */
function QuePasaSiPublico({ objeto }: { objeto: string }) {
  const { t } = useTranslation();
  const [previo, setPrevio] = useState<Previsualizacion | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Previsualizacion>(
      `/api/v1/metadata/objetos/${encodeURIComponent(objeto)}/previsualizar`,
      { signal: control.signal },
    )
      .then((r) => setPrevio(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [objeto]);

  if (fallo) return null;
  if (!previo) return null;

  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("modeloDatos.alPublicar")}</h2>
      {!previo.hay_cambios ? (
        <p className="text-2xs text-ink-muted">
          {t("modeloDatos.sinCambiosQuePublicar")}
        </p>
      ) : (
        <>
          <p className="text-2xs text-ink-muted">
            {t("modeloDatos.deLaVersionALa", {
              de: previo.version_actual,
              a: previo.version_al_publicar,
            })}
          </p>
          <ul className="mt-2 flex flex-wrap gap-2 text-3xs">
            <Cuantos clave="modeloDatos.anadidos" lista={previo.anadidos} />
            <Cuantos clave="modeloDatos.retirados" lista={previo.retirados} />
            <Cuantos clave="modeloDatos.cambiados" lista={previo.cambiados} />
          </ul>
          <p className="mt-2 text-2xs text-ink">
            {/* El recuento, y la diferencia entre no haber podido contar y que
                no afecte a nadie. */}
            {previo.registros === null
              ? t("modeloDatos.noSeHaPodidoContar")
              : t("modeloDatos.afectaA", {
                  registros: previo.registros,
                  sin: previo.registros_sin_rellenar ?? 0,
                })}
          </p>
          {previo.avisos?.length ? (
            <ul className="mt-2 flex flex-col gap-1">
              {previo.avisos.map((a, i) => (
                <li key={i} className="text-2xs text-warning">
                  {a}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-2xs text-success">
              {t("modeloDatos.publicarEsSeguro")}
            </p>
          )}
        </>
      )}
    </section>
  );
}

/**
 * El formulario que le toca a quien mira, y por qué ése (CRM-00.04.03.01).
 *
 * El diseñador deja arrastrar campos, secciones, pestañas y condiciones de
 * visibilidad, y guarda un diseño por rol. Lo que no había era forma de ver
 * **cuál se aplica**: con dos diseños, la pregunta que llega a soporte es
 * siempre «¿por qué yo veo otra pantalla?», y contestarla obligaba a mirar la
 * base de datos.
 *
 * El «por qué» viene de la propia ruta y se enseña tal cual, incluido el caso
 * incómodo —«no hay ninguno marcado por defecto, así que sale el único que
 * hay»—, que es el que conviene leer antes de que haya dos.
 */
function ElDisenoQueTeToca({ objeto }: { objeto: string }) {
  const { t } = useTranslation();
  const [diseno, setDiseno] = useState<Diseno | null>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Diseno>(
      `/api/v1/metadata/objetos/${encodeURIComponent(objeto)}/diseno`,
      { signal: control.signal },
    )
      .then((r) => setDiseno(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, [objeto]);

  if (!diseno) return null;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("modeloDatos.diseno")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">
        {t("modeloDatos.disenoAyuda")}
      </p>
      {diseno.hay_diseno ? (
        <div className="flex flex-wrap items-baseline gap-x-3">
          <span className="text-2xs font-medium text-ink">{diseno.nombre}</span>
          <span className="chip-dato">
            {t("modeloDatos.secciones", {
              cuantas: diseno.secciones?.length ?? 0,
            })}
          </span>
        </div>
      ) : (
        <Vacio titulo={t("modeloDatos.sinDiseno")} compacto />
      )}
      {/* El motivo lo da la ruta: cuál se aplica y por qué ése. */}
      <p className="mt-2 text-2xs text-ink-muted">{diseno.porque}</p>
    </section>
  );
}

/**
 * Lo que la IA entiende de este objeto, con su número (CRM-00.04.03.07) y
 * cómo sale en informes (CRM-00.04.03.06).
 *
 * **Con la cobertura delante, no sin ella.** Un campo `cmp_2` de tipo lista
 * con valores `A`, `B` y `C` es perfecto para el CRM y basura para cualquier
 * cosa que tenga que razonar sobre él. Con el 30 % de los campos descritos la
 * IA entiende el 30 %, y la diferencia entre eso y lo que la gente cree que
 * compró es lo que convierte un proyecto de IA en una decepción.
 *
 * Los que faltan salen **por su nombre**: un porcentaje dice cuánto queda, una
 * lista dice qué hacer esta tarde.
 */
function LoQueEntiendeLaIa({ objeto }: { objeto: string }) {
  const { t } = useTranslation();
  const [sem, setSem] = useState<Semantica | null>(null);
  const [informes, setInformes] = useState<ModeloSemantico | null>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Semantica>(
      `/api/v1/metadata/objetos/${encodeURIComponent(objeto)}/semantica`,
      { signal: control.signal },
    )
      .then((r) => setSem(r.datos))
      .catch(() => undefined);
    // Y lo mismo visto desde informes: es OTRO servicio el que decide qué
    // puede explotar, así que preguntárselo a metadata sería contestar por él.
    llamar<ModeloSemantico>(
      `/api/v1/analitica/modelo-semantico?objeto=${encodeURIComponent(objeto)}`,
      { signal: control.signal },
    )
      .then((r) => setInformes(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, [objeto]);

  if (!sem) return null;
  const cob = sem.cobertura;
  const deInformes = informes?.objetos?.find((o) => o.nombre === objeto);

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("modeloDatos.ia")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">{t("modeloDatos.iaAyuda")}</p>
      {!cob.medible ? (
        <Vacio titulo={t("modeloDatos.iaNoMedible")} compacto />
      ) : (
        <>
          <p
            className={
              (cob.pct ?? 0) < 70
                ? "text-sm font-medium text-warning"
                : "text-sm font-medium text-ink"
            }
          >
            {t("modeloDatos.iaCobertura", {
              pct: cob.pct,
              explotables: cob.explotables,
              campos: cob.campos,
            })}
          </p>
          <p className="mt-1 text-3xs text-ink-muted">{cob.que_significa}</p>
        </>
      )}
      {/* Lo que se queda fuera, y por qué. Recortarlo en silencio hace que
          quien pregunte por un campo concluya que el dato no existe. */}
      {sem.fuera_por_sensibles.length + sem.fuera_por_internos.length > 0 ? (
        <p className="mt-2 text-3xs text-ink-muted">
          {t("modeloDatos.iaFuera", {
            sensibles: sem.fuera_por_sensibles.length,
            internos: sem.fuera_por_internos.length,
          })}
        </p>
      ) : null}
      {sem.sin_describir.length > 0 ? (
        <p className="mt-1 text-3xs text-warning">
          {t("modeloDatos.iaSinDescribir", {
            campos: sem.sin_describir.join(", "),
          })}
        </p>
      ) : null}

      {deInformes ? (
        <div className="mt-3 border-t border-ink-dim/30 pt-2">
          <h3 className="text-2xs font-medium text-ink">
            {t("modeloDatos.enInformes")}
          </h3>
          <p className="text-3xs text-ink-faint">
            {t("modeloDatos.enInformesAyuda")}
          </p>
          <p className="mt-1 text-2xs text-ink-muted">
            {t("modeloDatos.enInformesCuantos", {
              cuantos: deInformes.campos.length,
            })}
            {informes && informes.excluidos_por_sensibilidad.length > 0
              ? ` · ${t("modeloDatos.enInformesFuera", {
                  cuantos: informes.excluidos_por_sensibilidad.length,
                })}`
              : ""}
          </p>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Qué campos ya justifican una columna de verdad (CRM-00.04.03.04).
 *
 * Materializar **no** es la norma y por eso esto es un panel y no un botón
 * grande: un cambio de tabla compartida por mil empresas las bloquea a todas.
 * La excepción se decide con una medida —las escrituras— y no con la
 * intuición de quien nota su lista lenta.
 *
 * El umbral viene de la ruta, no de aquí: es configuración del tenant.
 */
function CamposQueYaPidenColumna({ objeto }: { objeto: string }) {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Candidatos | null>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Candidatos>(
      `/api/v1/metadata/objetos/${encodeURIComponent(objeto)}/candidatos-columna`,
      { signal: control.signal },
    )
      .then((r) => setDatos(r.datos))
      // Pide `metadata:write`: quien sólo lee no ve este panel, y eso es
      // correcto — no es información que le sirva de nada.
      .catch(() => undefined);
    return () => control.abort();
  }, [objeto]);

  if (!datos) return null;

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("modeloDatos.columna")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">
        {t("modeloDatos.columnaAyuda")}
      </p>
      {datos.candidatos.length === 0 ? (
        <p className="text-2xs text-ink-muted">
          {t("modeloDatos.columnaNinguno", { umbral: datos.umbral })}
        </p>
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {datos.candidatos.map((c) => (
            <li
              key={c.campo}
              className="flex flex-wrap items-baseline gap-x-3 py-1.5"
            >
              <span className="text-2xs font-medium text-ink">{c.campo}</span>
              <span className="text-3xs text-ink-muted">
                {t("modeloDatos.columnaEscrituras", { cuantas: c.escrituras })}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-3xs text-ink-faint">{datos.por_que_no_siempre}</p>
    </section>
  );
}

/**
 * La máquina de estados del objeto (CRM-00.04.01.07).
 *
 * Se guardaba en el objeto y no se veía en ninguna parte. Sin ella, cualquier
 * estado salta a cualquier otro y el histórico deja de significar nada: una
 * oportunidad puede volver de «ganada» a «sin contactar» y nadie se entera de
 * que el embudo que se mira cada lunes está contando eso.
 */
function LaMaquinaDeEstados({ estados }: { estados: Record<string, unknown> }) {
  const { t } = useTranslation();
  const claves = Object.keys(estados ?? {});

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("modeloDatos.estados")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">
        {t("modeloDatos.estadosAyuda")}
      </p>
      {claves.length === 0 ? (
        <Vacio titulo={t("modeloDatos.sinEstados")} compacto />
      ) : (
        <ul className="divide-y divide-ink-dim/30">
          {claves.map((estado) => {
            const destinos = estados[estado];
            const lista = Array.isArray(destinos) ? destinos.map(String) : [];
            return (
              <li
                key={estado}
                className="flex flex-wrap items-baseline gap-x-2 py-1.5"
              >
                <span className="text-2xs font-medium text-ink">{estado}</span>
                {/* Un estado sin salidas es final, y decirlo importa: en una
                    lista de transiciones se lee como un hueco. */}
                {lista.length === 0 ? (
                  <span className="chip-dato">
                    {t("modeloDatos.estadoFinal")}
                  </span>
                ) : (
                  <>
                    <span className="text-3xs text-ink-faint">
                      {t("modeloDatos.estadoVaA")}
                    </span>
                    {lista.map((d) => (
                      <span key={d} className="chip-dato">
                        {d}
                      </span>
                    ))}
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/**
 * Renombrar y retirar sin romper a nadie (CRM-00.04.01.10), y llevarse la
 * configuración a otro entorno (CRM-00.04.03.10).
 *
 * Renombrar un campo deja el viejo puesto y escribiendo en los dos: lo que ya
 * llama por el nombre antiguo —una integración, un informe guardado, un
 * script de alguien— sigue funcionando. Lo que faltaba era **saber cuándo se
 * puede retirar el viejo**, y eso no es una fecha: es que nadie lo escriba.
 * Sale de la trazabilidad, que ya se lee en esta pantalla.
 *
 * El paquete se descarga desde el navegador y lleva **configuración, nunca
 * datos**: uno que arrastrara registros convertiría una promoción a
 * producción en una fuga, porque los datos de pruebas suelen ser copias
 * anonimizadas a medias de clientes reales.
 */
function RenombrarYLlevarse({
  objeto,
  rastro,
}: {
  objeto: string;
  rastro: Trazabilidad | null;
}) {
  const { t } = useTranslation();
  const [bajando, setBajando] = useState(false);
  // Qué se ha bajado, para decirlo. Un fichero que aparece en la carpeta de
  // descargas no es un resultado para quien no ve la pantalla, y tampoco para
  // quien la ve: sin esto, «¿ha ido bien?» se contesta abriendo el fichero.
  const [bajado, setBajado] = useState("");
  const retirables = (rastro?.campos ?? []).filter((c) => c.se_puede_retirar);

  async function descargar() {
    setBajando(true);
    try {
      const { datos } = await llamar<Record<string, unknown>>(
        `/api/v1/metadata/paquete?objeto=${encodeURIComponent(objeto)}`,
      );
      const objetos = Array.isArray(datos.objetos) ? datos.objetos : [];
      setBajado(
        t("modeloDatos.paqueteContiene", {
          objetos: objetos.length,
          campos: objetos.reduce(
            (n: number, o: unknown) =>
              n +
              (Array.isArray((o as { campos?: unknown[] }).campos)
                ? (o as { campos: unknown[] }).campos.length
                : 0),
            0,
          ),
        }),
      );
      const blob = new Blob([JSON.stringify(datos, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `paquete-${objeto}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setBajando(false);
    }
  }

  return (
    <section className="card p-4">
      <h2 className="section-label mb-1">{t("modeloDatos.renombrar")}</h2>
      <p className="mb-2 text-3xs text-ink-faint">
        {t("modeloDatos.renombrarAyuda")}
      </p>
      {retirables.length > 0 ? (
        <p className="text-2xs text-ink">
          {t("modeloDatos.sePuedeRetirar", { cuantos: retirables.length })}
        </p>
      ) : (
        <p className="text-2xs text-ink-muted">
          {t("modeloDatos.noSePuedeRetirarTodavia")}
        </p>
      )}

      <div className="mt-3 border-t border-ink-dim/30 pt-2">
        <h3 className="text-2xs font-medium text-ink">
          {t("modeloDatos.paquete")}
        </h3>
        <p className="text-3xs text-ink-faint">
          {t("modeloDatos.paqueteAyuda")}
        </p>
        <button
          type="button"
          className="btn btn-secundario mt-2"
          onClick={() => void descargar()}
          disabled={bajando}
        >
          <Icono nombre="download" /> {t("modeloDatos.paqueteDescargar")}
        </button>
        {/* Qué llevaba el fichero, anunciado: un fichero en la carpeta de
            descargas no dice si se ha bajado lo que se quería. */}
        <p role="status" aria-live="polite" className="mt-2 text-2xs text-ink-muted">
          {bajado}
        </p>
      </div>
    </section>
  );
}

function Cuantos({ clave, lista }: { clave: string; lista?: unknown[] }) {
  const { t } = useTranslation();
  if (!lista?.length) return null;
  return <li className="chip-dato">{t(clave, { cuantos: lista.length })}</li>;
}
