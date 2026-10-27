/**
 * Un objeto del modelo de datos, con todo lo suyo (CRM-00.04.01.02,
 * CRM-00.04.01.05, CRM-00.04.01.06, CRM-00.04.01.08, CRM-00.04.01.09,
 * CRM-00.04.03.03, CRM-00.04.03.11, CRM-00.04.03.12).
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
  publicaciones: { version: number; at: string | null; nota: string; campos: number }[];
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
        void llamar<Trazabilidad>(`/api/v1/metadata/objetos/${nombre}/trazabilidad`, {
          signal: control.signal,
        })
          .then((r) => setRastro(r.datos))
          .catch(() => undefined);
        void llamar<TipoRegistro[]>(`/api/v1/metadata/objetos/${nombre}/tipos`, {
          signal: control.signal,
        })
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
              <span className="text-2xs text-ink-faint">{objeto.descripcion}</span>
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
              limites.en_aviso ? "text-sm font-medium text-danger" : "text-sm font-medium text-ink"
            }
          >
            {t("modeloDatos.camposDeTope", { campos: limites.campos, tope: limites.tope })}
          </p>
          {/* Qué pasa al llegar, dicho antes de llegar: un tope que sólo se
              explica cuando se alcanza se explica tarde. */}
          <p className="mt-1 text-3xs text-ink-muted">{limites.al_llegar}</p>
        </section>
      ) : null}

      {/* ── Los campos, con sus escrituras al lado ──────────────────────── */}
      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("modeloDatos.campos")}</h2>
        <p className="mb-3 text-3xs text-ink-faint">{t("modeloDatos.camposAyuda")}</p>
        {!describe ? <Cargando /> : null}
        {describe && describe.campos.length === 0 ? (
          <Vacio titulo={t("modeloDatos.sinCampos")} compacto />
        ) : null}
        {describe && describe.campos.length > 0 ? (
          <ul className="divide-y divide-ink-dim/30">
            {describe.campos.map((campo) => {
              const uso = escrituras.get(campo.nombre);
              return (
                <li key={campo.id} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
                  <span className="text-2xs font-medium text-ink">
                    {campo.etiqueta || campo.nombre}
                  </span>
                  <span className="text-3xs text-ink-faint">{campo.nombre}</span>
                  <span className="chip-dato">{campo.tipo}</span>
                  {campo.obligatorio ? (
                    <span className="chip-dato">{t("modeloDatos.obligatorio")}</span>
                  ) : null}
                  {campo.unico ? <span className="chip-dato">{t("modeloDatos.unico")}</span> : null}
                  {campo.solo_lectura ? (
                    <span className="chip-dato">{t("modeloDatos.soloLectura")}</span>
                  ) : null}
                  {campo.sensibilidad && campo.sensibilidad !== "normal" ? (
                    <span className="chip-dato chip-dato--no">{campo.sensibilidad}</span>
                  ) : null}
                  {campo.deprecado ? (
                    <span className="chip-dato chip-dato--no">{t("modeloDatos.deprecado")}</span>
                  ) : null}
                  {/* Lo que contesta «¿puedo quitarlo?»: cuántas veces se ha
                      ESCRITO. Leer mide quién mira; escribir mide si el campo
                      se rellena. */}
                  {uso ? (
                    <span
                      className={
                        uso.escrituras === 0 ? "text-3xs text-danger" : "text-3xs text-ink-muted"
                      }
                    >
                      {uso.escrituras === 0
                        ? t("modeloDatos.nuncaEscrito")
                        : t("modeloDatos.escrituras", { cuantas: uso.escrituras })}
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
            <Icono nombre="info" /> {t("modeloDatos.sinUsar", { cuantos: rastro.sin_usar.length })}
          </p>
        ) : null}
      </section>

      {/* ── Validaciones y tipos de registro ────────────────────────────── */}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-4">
          <h2 className="section-label mb-1">{t("modeloDatos.reglas")}</h2>
          <p className="mb-2 text-3xs text-ink-faint">{t("modeloDatos.reglasAyuda")}</p>
          {describe && describe.reglas.length === 0 ? (
            <Vacio titulo={t("modeloDatos.sinReglas")} compacto />
          ) : null}
          <ul className="divide-y divide-ink-dim/30">
            {(describe?.reglas ?? []).map((regla) => (
              <li key={regla.id} className="py-1.5">
                <div className="flex flex-wrap items-baseline gap-x-3">
                  <span className="text-2xs font-medium text-ink">{regla.nombre}</span>
                  <span className="chip-dato">{regla.momento}</span>
                  {!regla.activa ? (
                    <span className="chip-dato chip-dato--no">{t("modeloDatos.apagada")}</span>
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
          <p className="mb-2 text-3xs text-ink-faint">{t("modeloDatos.tiposAyuda")}</p>
          {tipos && tipos.length === 0 ? (
            <Vacio titulo={t("modeloDatos.sinTipos")} compacto />
          ) : null}
          <ul className="divide-y divide-ink-dim/30">
            {(tipos ?? []).map((tipo) => (
              <li key={tipo.clave} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
                <span className="text-2xs font-medium text-ink">{tipo.nombre}</span>
                <span className="text-3xs text-ink-faint">{tipo.clave}</span>
                {tipo.por_defecto ? (
                  <span className="chip-dato chip-dato--si">{t("modeloDatos.porDefecto")}</span>
                ) : null}
                {tipo.campos_ocultos.length > 0 ? (
                  <span className="text-3xs text-ink-muted">
                    {t("modeloDatos.ocultos", { cuantos: tipo.campos_ocultos.length })}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      </div>

      {/* ── Qué se publicó y cuándo ─────────────────────────────────────── */}
      {rastro && rastro.publicaciones.length > 0 ? (
        <section className="card mt-4 p-4">
          <h2 className="section-label mb-1">{t("modeloDatos.publicaciones")}</h2>
          <p className="mb-2 text-3xs text-ink-faint">{t("modeloDatos.publicacionesAyuda")}</p>
          <ul className="divide-y divide-ink-dim/30">
            {rastro.publicaciones.map((pub) => (
              <li key={pub.version} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
                <span className="text-2xs font-medium text-ink">v{pub.version}</span>
                <span className="text-3xs text-ink-faint">{escalar(pub.at, "at")}</span>
                <span className="text-3xs text-ink-muted">
                  {t("modeloDatos.camposEnPublicacion", { cuantos: pub.campos })}
                </span>
                {pub.nota ? <span className="text-3xs text-ink-muted">{pub.nota}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}
