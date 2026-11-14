/**
 * Notas, ficheros y conversaciones de la suite vinculados a un registro, por
 * referencia (CRM-06.01.03.08, CRM-06.01.03.09, CRM-06.01.03.12).
 *
 * Hasta el 09-11-2026 vincular devolvía un diccionario que no guardaba nadie:
 * la ficha no podía enseñar ninguna nota vinculada porque no había ninguna.
 * Ahora se guarda el enlace —sólo el enlace, nunca el contenido— y al abrirlo
 * se pregunta al origen si existe y si quien mira tiene acceso. Sin operación
 * declarada en el perfil se dice que no se puede comprobar: nunca «accesible».
 */

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmarBorrado } from "@/componentes/Edicion";
import { AvisoDeRecorte, Error as Fallo } from "@/componentes/Estados";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { listarPagina } from "@/lib/listados";

const TIPOS = ["nota", "fichero", "conversacion"] as const;

interface Referencia {
  id: string;
  tipo: string;
  referencia: string;
  nombre: string;
  ultimo_estado: string;
  comprobada_at: string | null;
  detalle: { resumen?: string; aviso?: string };
}

interface Apertura {
  estado: string;
  ver: boolean | null;
  que_decir?: string;
  url?: string | null;
}

export function ReferenciasDeSuite({
  objeto,
  objetoId,
}: {
  objeto: string;
  objetoId: string;
}) {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Referencia[] | null>(null);
  const [perfiles, setPerfiles] = useState<string[]>([]);
  // Si el servidor ha dicho que hay más perfiles que los cincuenta pedidos:
  // un desplegable cortado sin decirlo hace creer que el que falta no existe.
  const [hayMasPerfiles, setHayMasPerfiles] = useState(false);
  const [abierto, setAbierto] = useState(false);
  const [tipo, setTipo] = useState<string>("nota");
  const [referencia, setReferencia] = useState("");
  const [nombre, setNombre] = useState("");
  const [perfil, setPerfil] = useState("");
  const [resumen, setResumen] = useState("");
  const [exportable, setExportable] = useState(false);
  const [aperturas, setAperturas] = useState<Record<string, Apertura>>({});
  const [fallo, setFallo] = useState<unknown>(null);
  // El vínculo que se va a quitar, mientras se pregunta.
  const [quitando, setQuitando] = useState<Referencia | null>(null);
  const [borrando, setBorrando] = useState(false);

  const cargar = useCallback(() => {
    llamar<{ referencias: Referencia[] }>(
      `/api/v1/referencias-suite?objeto=${encodeURIComponent(objeto)}&objeto_id=${encodeURIComponent(objetoId)}`,
    )
      .then((r) => setFilas(r.datos.referencias ?? []))
      .catch(() => setFilas([]));
  }, [objeto, objetoId]);
  useEffect(cargar, [cargar]);
  useEffect(() => {
    void listarPagina<{ nombre?: string }>("/api/v1/suites/perfiles?limite=50")
      .then((p) => {
        setPerfiles(
          p.filas.map((x) => String(x.nombre ?? "")).filter(Boolean),
        );
        setHayMasPerfiles(p.siguiente !== "");
      })
      .catch(() => setPerfiles([]));
  }, []);

  async function guardar(e: FormEvent) {
    e.preventDefault();
    setFallo(null);
    try {
      await llamar("/api/v1/referencias-suite", {
        metodo: "POST",
        cuerpo: {
          tipo,
          objeto,
          objeto_id: objetoId,
          referencia: referencia.trim(),
          nombre: nombre.trim(),
          perfil,
          ...(tipo === "conversacion" ? { resumen, exportable } : {}),
        },
      });
      setReferencia("");
      setNombre("");
      setResumen("");
      setAbierto(false);
      cargar();
    } catch (err) {
      setFallo(err);
    }
  }

  async function abrir(id: string) {
    setFallo(null);
    try {
      const r = await llamar<Apertura>(
        `/api/v1/referencias-suite/${id}/abrir`,
        {
          metodo: "POST",
        },
      );
      setAperturas((a) => ({ ...a, [id]: r.datos }));
    } catch (err) {
      setFallo(err);
    }
  }

  async function quitar(id: string) {
    setFallo(null);
    setBorrando(true);
    try {
      await llamar(`/api/v1/referencias-suite/${id}`, { metodo: "DELETE" });
      setQuitando(null);
      cargar();
    } catch (err) {
      setFallo(err);
    } finally {
      setBorrando(false);
    }
  }

  return (
    <section className="card mb-4 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="section-label">{t("referenciasSuite.titulo")}</h2>
        {!abierto ? (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => setAbierto(true)}
          >
            {t("referenciasSuite.vincular")}
          </button>
        ) : null}
      </div>
      <p className="mt-1 text-rotulo text-ink-muted">
        {t("referenciasSuite.ayuda")}
      </p>

      {abierto ? (
        <form className="mt-3 grid gap-3 md:grid-cols-2" onSubmit={guardar}>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("referenciasSuite.tipo")}
            <select
              className="input-base"
              value={tipo}
              onChange={(e) => setTipo(e.target.value)}
            >
              {TIPOS.map((x) => (
                <option key={x} value={x}>
                  {t(`referenciasSuite.tipos.${x}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("referenciasSuite.perfil")}
            <select
              className="input-base"
              value={perfil}
              onChange={(e) => setPerfil(e.target.value)}
            >
              <option value="">{t("referenciasSuite.sinPerfil")}</option>
              {perfiles.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            {hayMasPerfiles ? (
              <AvisoDeRecorte cuantas={perfiles.length} />
            ) : null}
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("referenciasSuite.referencia")}
            <input
              className="input-base"
              required
              value={referencia}
              onChange={(e) => setReferencia(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("referenciasSuite.nombre")}
            <input
              className="input-base"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
            />
          </label>
          {tipo === "conversacion" ? (
            <>
              <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
                {t("referenciasSuite.resumen")}
                <input
                  className="input-base"
                  value={resumen}
                  onChange={(e) => setResumen(e.target.value)}
                />
              </label>
              <label className="flex items-center gap-2 text-dato text-ink">
                <input
                  type="checkbox"
                  checked={exportable}
                  onChange={(e) => setExportable(e.target.checked)}
                />
                {t("referenciasSuite.exportable")}
              </label>
            </>
          ) : null}
          <div className="flex gap-2 md:col-span-2">
            <button
              type="submit"
              className="btn-primary"
              disabled={!referencia.trim()}
            >
              {t("referenciasSuite.guardar")}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setAbierto(false)}
            >
              {t("referenciasSuite.cancelar")}
            </button>
          </div>
        </form>
      ) : null}

      {fallo ? <Fallo error={fallo} /> : null}

      {filas && filas.length === 0 ? (
        <p className="mt-3 text-rotulo text-ink-faint">
          {t("referenciasSuite.vacio")}
        </p>
      ) : null}
      {filas && filas.length > 0 ? (
        <div className="mt-3">
          <Rejilla
            compacta
            titulo={t("referenciasSuite.titulo")}
            cabeceras={[
              t("referenciasSuite.tipo"),
              t("referenciasSuite.nombre"),
              "",
              "",
            ]}
          >
            {filas.map((f) => {
              const a = aperturas[f.id];
              return (
                <tr key={f.id}>
                  <Casilla enUnaLinea>
                    {t(`referenciasSuite.tipos.${f.tipo}`, f.tipo)}
                  </Casilla>
                  <Casilla>
                    {f.nombre || f.referencia}
                    {f.detalle?.resumen ? (
                      <p className="text-rotulo text-ink-muted">
                        {f.detalle.resumen}
                      </p>
                    ) : null}
                    {a ? (
                      <p
                        role="status"
                        className={`text-rotulo ${a.ver ? "text-ink" : "text-ink-muted"}`}
                      >
                        {/* Lo que dice el servidor manda; el rótulo del
                            estado, sólo si no dice nada. */}
                        {a.que_decir ||
                          t(`referenciasSuite.estados.${a.estado}`, a.estado)}
                        {a.ver && a.url ? (
                          <>
                            {" "}
                            <a
                              className="text-accent underline"
                              href={a.url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {t("referenciasSuite.irAlOrigen")}
                            </a>
                          </>
                        ) : null}
                      </p>
                    ) : null}
                  </Casilla>
                  <Casilla enUnaLinea>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => void abrir(f.id)}
                    >
                      {t("referenciasSuite.abrir")}
                    </button>
                  </Casilla>
                  <Casilla enUnaLinea>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setQuitando(f)}
                    >
                      {t("referenciasSuite.quitar")}
                    </button>
                  </Casilla>
                </tr>
              );
            })}
          </Rejilla>
        </div>
      ) : null}
      {quitando ? (
        <div className="mt-3">
          <ConfirmarBorrado
            borrado={t("referenciasSuite.quitar")}
            aviso={t("referenciasSuite.quitarAviso", {
              nombre: quitando.nombre || quitando.referencia,
            })}
            enviando={borrando}
            alBorrar={() => void quitar(quitando.id)}
            alCancelar={() => setQuitando(null)}
          />
        </div>
      ) : null}
    </section>
  );
}
