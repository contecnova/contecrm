/**
 * Un artículo de conocimiento: a quién llega, en qué idiomas y si sirve
 * (CRM-04.03.01.02, CRM-04.03.01.03, CRM-04.03.01.06).
 *
 * La lista enseña el título, el estado y las vistas. Las tres preguntas que se
 * hacen delante de un artículo no las contesta una lista, y las tres las
 * contesta ya el servidor sin que nadie las enseñe.
 *
 * **«¿Quién puede ver esto?»** La audiencia es lo que separa un procedimiento
 * interno con nombres de clientes dentro de algo que está en el portal. Va
 * delante y con lo que significa, no como una palabra suelta: «cliente» no
 * dice por sí solo que eso se publica fuera.
 *
 * **«¿Las traducciones siguen diciendo lo mismo?»** Es el fallo caro de una
 * base multilingüe: se corrige el original, las traducciones se quedan como
 * estaban, y durante meses el cliente francés lee el procedimiento viejo
 * mientras el español lee el nuevo. El servidor ya calcula, por idioma, si está
 * sincronizada y **cuántas versiones por detrás** va. Eso segundo es lo que
 * dice si corre prisa: una por detrás es una errata, seis son otro artículo.
 *
 * **«¿Esto sirve?»** Y aquí la trampa está en el conjunto: la eficacia separa
 * los **dañinos** —muchas vistas y votos negativos, que son peores que no
 * tener artículo porque alguien los está siguiendo— de los **huérfanos**, que
 * no los usa nadie. Las dos cosas se ven igual en una lista ordenada por
 * vistas, y se arreglan al revés: uno se corrige y el otro se borra.
 *
 * La deflexión va con su aviso porque es **aproximada**, y lo dice el propio
 * servidor: un porcentaje de deflexión presentado como una medida es el número
 * con el que se justifica no contratar a nadie más en soporte.
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
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";

interface Articulo {
  articulo_id: string;
  clave: string;
  idioma: string;
  estado: string;
  titulo: string;
  cuerpo: string;
  version: number;
  utiles: number;
  inutiles: number;
  obsoleto: boolean;
  pendiente_de_revision: boolean;
  aviso: string;
}

interface Traduccion {
  idioma: string;
  articulo_id: string;
  estado: string;
  traducido_de_version: number;
  sincronizada: boolean;
  /** Lo que dice si corre prisa: una es una errata, seis son otro artículo. */
  versiones_por_detras: number;
}

interface Traducciones {
  articulo: string;
  idioma_original: string;
  version_publicada: number;
  traducciones: Traduccion[];
  desincronizadas: string[];
}

interface Eficacia {
  articulos: number;
  publicados: number;
  /** Muchas vistas y votos negativos: peor que no tener artículo. */
  dañinos: { clave: string; idioma: string; vistas: number; utiles: number; inutiles: number }[];
  huerfanos: { clave: string; idioma: string }[];
  caducados: { clave: string; idioma: string }[];
  vistas: number;
  usos_en_caso: number;
  deflexion_aproximada_pct: number | null;
  aviso_deflexion: string;
}

export function Articulo() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [articulo, setArticulo] = useState<Articulo | null>(null);
  const [traducciones, setTraducciones] = useState<Traducciones | null>(null);
  const [eficacia, setEficacia] = useState<Eficacia | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [editando, setEditando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const navegar = useNavigate();
  // Se edita lo que ES del artículo —su clave, su audiencia, sus canales, su
  // fecha de revisión—, no su texto: el texto va por VERSIONES, que es lo que
  // permite corregir uno publicado sin que el cliente vea el cambio a medias.
  const modulo = moduloDe("conocimiento");
  const recurso = modulo ? recursoDe(modulo, "articulo") : undefined;
  const { ruta, puedeEditar, puedeBorrar } = useEdicion(recurso, id);

  const cargar = useCallback(() => {
    const control = new AbortController();
    const { signal } = control;
    setFallo(null);
    llamar<Articulo>(`/api/v1/conocimiento/${id}`, { signal })
      .then((r) => setArticulo(r.datos))
      .catch(salvoCancelacion(setFallo));
    llamar<Traducciones>(`/api/v1/conocimiento/${id}/traducciones`, { signal })
      .then((r) => setTraducciones(r.datos))
      .catch(salvoCancelacion(() => setTraducciones(null)));
    // La eficacia es del conjunto, no de este artículo: se enseña aquí porque
    // es donde se decide qué hacer con él —corregirlo, borrarlo o revisarlo—,
    // y saber si está en la lista de dañinos es la mitad de esa decisión.
    llamar<Eficacia>("/api/v1/conocimiento/eficacia", { signal })
      .then((r) => setEficacia(r.datos))
      .catch(salvoCancelacion(() => setEficacia(null)));
    return () => control.abort();
  }, [id]);

  useEffect(cargar, [cargar]);

  async function borrar() {
    setBorrando(true);
    try {
      await llamar(ruta, { metodo: "DELETE" });
      navegar("/conocimiento");
    } catch (error) {
      setFallo(error);
      setConfirmando(false);
    } finally {
      setBorrando(false);
    }
  }

  if (fallo && !articulo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!articulo) return <Cargando />;

  const idiomas = traducciones?.traducciones ?? [];
  const atrasadas = idiomas.filter((x) => !x.sincronizada);
  const esDañino = (eficacia?.dañinos ?? []).some((d) => d.clave === articulo.clave);
  const esHuerfano = (eficacia?.huerfanos ?? []).some((d) => d.clave === articulo.clave);

  return (
    <>
      <CabeceraPagina
        titulo={articulo.titulo}
        icono="menu_book"
        entradilla={
          <span className="flex flex-wrap items-center gap-2">
            <span className="chip-dato">{articulo.estado}</span>
            <span className="chip-dato font-mono">{articulo.idioma}</span>
            <span className="text-2xs text-ink-muted">
              {t("articulo.version", { version: articulo.version })}
            </span>
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
          valores={articulo as unknown as Record<string, unknown>}
          alGuardar={() => {
            setEditando(false);
            cargar();
          }}
          alCancelar={() => setEditando(false)}
        />
      ) : null}

      {articulo.aviso ? (
        <p className="card mb-3 border-warning/40 p-3 text-2xs text-warning" role="status">
          {articulo.aviso}
        </p>
      ) : null}

      {/* Lo que decide qué hacer con el artículo, arriba. Un artículo dañino
          no es uno que no sirve: es uno que alguien está siguiendo. */}
      {esDañino ? (
        <p className="card mb-3 border-danger/40 p-3 text-2xs text-danger">
          {t("articulo.daniño")}
        </p>
      ) : null}
      {esHuerfano ? (
        <p className="card mb-3 p-3 text-2xs text-ink-muted">{t("articulo.huerfano")}</p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-4">
          <h2 className="text-sm font-medium text-ink">{t("articulo.quienLoVe")}</h2>
          <p className="mt-2 text-2xs text-ink">
            {t(`articulo.audiencia.${articulo.estado === "publicado" ? "publicado" : "borrador"}`)}
          </p>
          <p className="mt-2 font-mono text-2xs text-ink">
            {t("articulo.votos", {
              utiles: articulo.utiles,
              inutiles: articulo.inutiles,
            })}
          </p>
          {/* Lo pendiente de revisión no se esconde ni se oculta el artículo:
              ocultarlo deja al cliente sin respuesta y enseñarlo sin avisar le
              da una que puede estar vieja. */}
          {articulo.pendiente_de_revision ? (
            <p className="mt-2 text-2xs text-warning">{t("articulo.toca_revisar")}</p>
          ) : null}
          {articulo.obsoleto ? (
            <p className="mt-2 text-2xs text-warning">{t("articulo.obsoleto")}</p>
          ) : null}
        </section>

        <section className="card p-4">
          <h2 className="text-sm font-medium text-ink">{t("articulo.idiomas")}</h2>
          <p className="mt-1 text-3xs text-ink-faint">{t("articulo.porqueIdiomas")}</p>
          {idiomas.length === 0 ? (
            <Vacio titulo={t("articulo.sinTraducciones")} detalle="" />
          ) : (
            <ul className="mt-2 flex flex-col gap-1">
              {idiomas.map((x) => (
                <li key={x.idioma} className="flex items-baseline gap-2">
                  <span className="chip-dato font-mono">{x.idioma}</span>
                  <span className="flex-1 text-3xs text-ink-muted">{x.estado}</span>
                  {/* Cuántas versiones por detrás, no sólo «desincronizada»:
                      una es una errata y seis son otro artículo. */}
                  <span
                    className={
                      x.sincronizada
                        ? "font-mono text-3xs text-ink-muted"
                        : "font-mono text-3xs text-warning"
                    }
                  >
                    {x.sincronizada
                      ? t("articulo.alDia")
                      : t("articulo.porDetras", { cuantas: x.versiones_por_detras })}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {atrasadas.length > 0 ? (
            <p className="mt-2 text-2xs text-warning">
              {t("articulo.desincronizadas", { cuantas: atrasadas.length })}
            </p>
          ) : null}
        </section>

        {eficacia ? (
          <section className="card p-4 lg:col-span-2">
            <h2 className="text-sm font-medium text-ink">{t("articulo.eficacia")}</h2>
            <p className="mt-2 font-mono text-2xs text-ink">
              {t("articulo.conjunto", {
                publicados: eficacia.publicados,
                daninos: eficacia.dañinos.length,
                huerfanos: eficacia.huerfanos.length,
                caducados: eficacia.caducados.length,
              })}
            </p>
            {/* La deflexión con su aviso: es el número con el que se justifica
                no contratar a nadie más en soporte, y es aproximado. */}
            <p className="mt-2 font-mono text-lg text-ink">
              {eficacia.deflexion_aproximada_pct === null
                ? t("articulo.sinDeflexion")
                : t("articulo.deflexion", { pct: eficacia.deflexion_aproximada_pct })}
            </p>
            {eficacia.aviso_deflexion ? (
              <p className="mt-1 text-2xs text-ink-muted">{eficacia.aviso_deflexion}</p>
            ) : null}
          </section>
        ) : null}
      </div>
    </>
  );
}
