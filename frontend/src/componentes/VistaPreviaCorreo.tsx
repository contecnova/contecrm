/**
 * La plantilla como le llegaría a un contacto de verdad, en varios clientes de
 * correo, con su puntuación de spam explicada (CRM-02.03.01.02,
 * CRM-02.03.01.06).
 *
 * `GET /correo/plantillas/{clave}/componer` no tenía pantalla y devolvía los
 * bloques en JSON; la personalización se probaba con datos tecleados y el spam
 * eran seis palabras. Aquí se elige un contacto y el correo se monta con **sus**
 * datos y los de su cuenta —de `party`— y con las recomendaciones que salen del
 * historial de su cuenta en `sales`. Se pinta en cada cliente configurado
 * (ancho, imágenes bloqueadas, modo oscuro) y la puntuación de spam lista cada
 * regla que ha sumado y por qué.
 *
 * Verificado pulsando el 09-11-2026 en la ficha de una plantilla.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo, FalloCompacto } from "@/componentes/Estados";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { useCargasSecundarias } from "@/lib/cargaSecundaria";
import { cn } from "@/lib/utiles";

interface Cliente {
  clave: string;
  nombre: string;
  ancho: number;
  html: string;
}

interface Regla {
  regla: string;
  grupo: string;
  puntos: number;
  porque: string;
}

interface Vista {
  clase: string;
  asunto: string;
  sin_dato: string[];
  bloques_que_faltan: string[];
  aviso_datos: string;
  datos: {
    contacto?: Record<string, unknown>;
    cuenta?: Record<string, unknown>;
  };
  recomendaciones: {
    productos: { nombre: string; sku?: string; porque: string }[];
    contenidos: { nombre: string; porque: string }[];
    porque: string;
  };
  clientes: Cliente[];
  spam: {
    puntos: number;
    umbral: number;
    veredicto: "bien" | "dudoso" | "basura";
    reglas: Regla[];
  };
  salida: {
    dominio: string | null;
    remitente: string | null;
    problemas: string[];
  };
}

interface Contacto {
  id: string;
  nombre_completo?: string;
  nombre?: string;
  email?: string | null;
}

const TONO = {
  bien: "chip-dato--si",
  dudoso: "chip-dato--aviso",
  basura: "chip-dato--mal",
} as const;

export function VistaPreviaCorreo({
  clave,
  idioma,
}: {
  clave: string;
  idioma: string;
}) {
  const { t } = useTranslation();
  const [buscar, setBuscar] = useState("");
  const [contactos, setContactos] = useState<Contacto[]>([]);
  // Los contactos para elegir, con su fallo a la vista: un desplegable vacío
  // por una búsqueda que no llegó se lee como «nadie se llama así».
  const { seguir, estado: estadoDe } = useCargasSecundarias();
  const [contacto, setContacto] = useState("");
  const [vista, setVista] = useState<Vista | null>(null);
  const [cliente, setCliente] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);
  // Si a ESTA persona se le puede mandar ESTA plantilla: bloques, sus
  // preferencias y su consentimiento, en una sola comprobación. La que se
  // olvida siempre es la de las preferencias, y el resultado es un correo a
  // quien se dio de baja.
  const [envio, setEnvio] = useState<{
    se_puede_mandar: boolean;
    motivos: string[];
  } | null>(null);

  useEffect(() => {
    const control = new AbortController();
    seguir("contactos", () =>
      llamar<{ items?: Contacto[] }>(
        `/api/v1/contacts?limite=20&buscar=${encodeURIComponent(buscar)}`,
        { signal: control.signal },
      ).then((r) => setContactos(r.datos?.items ?? [])),
    );
    return () => control.abort();
  }, [buscar, seguir]);

  useEffect(() => {
    const control = new AbortController();
    const parametros = new URLSearchParams({ idioma });
    if (contacto) parametros.set("contacto_id", contacto);
    llamar<Vista>(
      `/api/v1/correo/plantillas/${encodeURIComponent(clave)}/vista-previa?${parametros}`,
      { signal: control.signal },
    )
      .then((r) => {
        if (!Array.isArray(r.datos?.clientes) || !r.datos.spam) return;
        setVista(r.datos);
        setFallo(null);
        setCliente((actual) => actual || r.datos.clientes[0]?.clave || "");
      })
      .catch((e) => {
        if (!control.signal.aborted) setFallo(e);
      });
    return () => control.abort();
  }, [clave, idioma, contacto]);

  const email = contactos.find((c) => c.id === contacto)?.email ?? "";
  useEffect(() => {
    setEnvio(null);
    if (!email) return;
    const control = new AbortController();
    llamar<{ se_puede_mandar: boolean; motivos: string[] }>(
      `/api/v1/correo/comprobar-envio?email=${encodeURIComponent(email)}&plantilla=${encodeURIComponent(clave)}&idioma=${encodeURIComponent(idioma)}`,
      { signal: control.signal },
    )
      .then((r) => setEnvio(r.datos))
      .catch((e) => {
        if (!control.signal.aborted) setFallo(e);
      });
    return () => control.abort();
  }, [email, clave, idioma]);

  const elegido = vista?.clientes.find((c) => c.clave === cliente);
  return (
    <section className="card mb-4 p-4">
      <h2 className="section-label mb-1">{t("mk.vista.titulo")}</h2>
      <p className="mb-2 text-rotulo text-ink-faint">{t("mk.vista.ayuda")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          className="input-base w-56"
          value={buscar}
          placeholder={t("mk.vista.buscarContacto")}
          aria-label={t("mk.vista.buscarContacto")}
          onChange={(e) => setBuscar(e.target.value)}
        />
        <select
          className="input-base w-auto"
          aria-label={t("mk.vista.contacto")}
          value={contacto}
          onChange={(e) => setContacto(e.target.value)}
        >
          <option value="">{t("mk.vista.sinContacto")}</option>
          {contactos.map((c) => (
            <option key={c.id} value={c.id}>
              {c.nombre_completo ?? c.nombre} {c.email ? `· ${c.email}` : ""}
            </option>
          ))}
        </select>
      </div>
      <FalloCompacto
        {...estadoDe("contactos")}
        que={t("mk.vista.contactosParaElegir")}
      />
      {envio ? (
        <p
          role="status"
          className={`mt-2 text-dato ${envio.se_puede_mandar ? "text-success" : "text-danger"}`}
        >
          {envio.se_puede_mandar
            ? t("mk.vista.sePuedeMandar", { email })
            : t("mk.vista.noSePuedeMandar", {
                email,
                motivos: envio.motivos.join(" · "),
              })}
        </p>
      ) : null}
      {fallo ? <Fallo error={fallo} /> : null}
      {vista ? (
        <div role="status" className="mt-3 grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <p className="text-dato text-ink">
              <span className="text-ink-muted">{t("mk.vista.asunto")}:</span>{" "}
              {vista.asunto}
            </p>
            {vista.aviso_datos ? (
              <p className="text-rotulo text-warning">{vista.aviso_datos}</p>
            ) : null}
            {vista.sin_dato.length ? (
              <p className="text-rotulo text-warning">
                {t("mk.vista.sinDato", { campos: vista.sin_dato.join(", ") })}
              </p>
            ) : null}
            {vista.bloques_que_faltan.length ? (
              <p className="text-rotulo text-warning">
                {t("mk.vista.faltan", {
                  bloques: vista.bloques_que_faltan.join(", "),
                })}
              </p>
            ) : null}
            <div
              className="mt-2 flex flex-wrap gap-1"
              role="tablist"
              aria-label={t("mk.vista.clientes")}
            >
              {vista.clientes.map((c) => (
                <button
                  key={c.clave}
                  type="button"
                  role="tab"
                  aria-selected={c.clave === cliente}
                  className={cn(
                    "chip-dato",
                    c.clave === cliente && "chip-dato--si",
                  )}
                  onClick={() => setCliente(c.clave)}
                >
                  {c.nombre} · {c.ancho}px
                </button>
              ))}
            </div>
            {elegido ? (
              <div className="mt-2 overflow-auto rounded-lg border border-ink-dim/40">
                <iframe
                  title={`${t("mk.vista.titulo")} · ${elegido.nombre}`}
                  sandbox=""
                  srcDoc={elegido.html}
                  style={{ width: elegido.ancho, height: 420 }}
                  className="block border-0"
                />
              </div>
            ) : null}
          </div>
          <div className="flex flex-col gap-3">
            <div>
              <h3 className="section-label mb-1">{t("mk.vista.spam")}</h3>
              <p className="text-dato">
                <span className={cn("chip-dato", TONO[vista.spam.veredicto])}>
                  {t(`mk.vista.veredicto.${vista.spam.veredicto}`)}
                </span>{" "}
                {t("mk.vista.puntos", {
                  puntos: vista.spam.puntos,
                  umbral: vista.spam.umbral,
                })}
              </p>
              {vista.spam.reglas.length ? (
                <Rejilla
                  titulo={t("mk.vista.spam")}
                  compacta
                  cabeceras={[t("mk.vista.regla"), t("mk.vista.suma")]}
                >
                  {vista.spam.reglas.map((r, i) => (
                    <tr
                      key={`${r.regla}-${i}`}
                      className="border-b border-ink-dim/30 last:border-0"
                    >
                      <Casilla className="text-rotulo">
                        <span className="chip-dato mr-1">
                          {t(`mk.vista.grupos.${r.grupo}`, {
                            defaultValue: r.grupo,
                          })}
                        </span>
                        {r.porque}
                      </Casilla>
                      <Casilla className="font-mono">{r.puntos}</Casilla>
                    </tr>
                  ))}
                </Rejilla>
              ) : (
                <p className="text-rotulo text-ink-faint">
                  {t("mk.vista.sinReglas")}
                </p>
              )}
            </div>
            <div>
              <h3 className="section-label mb-1">
                {t("mk.vista.recomendaciones")}
              </h3>
              <p className="text-rotulo text-ink-faint">
                {vista.recomendaciones.porque}
              </p>
              <ul className="text-dato">
                {vista.recomendaciones.productos.map((p) => (
                  <li key={p.nombre}>
                    {p.nombre}{" "}
                    <span className="text-rotulo text-ink-faint">
                      {p.porque}
                    </span>
                  </li>
                ))}
                {vista.recomendaciones.contenidos.map((c) => (
                  <li key={c.nombre}>
                    {c.nombre}{" "}
                    <span className="text-rotulo text-ink-faint">
                      {c.porque}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="section-label mb-1">{t("mk.vista.saleDe")}</h3>
              <p className="text-dato">
                {t(`mk.envios.clase.${vista.clase}`)} ·{" "}
                {vista.salida.remitente ?? "—"} ({vista.salida.dominio ?? "—"})
              </p>
              {vista.salida.problemas.map((p) => (
                <p key={p} className="text-rotulo text-warning">
                  {p}
                </p>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
