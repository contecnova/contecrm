/**
 * El grupo de empresas: el árbol, lo que cada hija comparte y lo que la matriz
 * ve de ellas (CRM-00.01.03.07).
 *
 * Hasta el 09-11-2026 la jerarquía era un campo del alta —«cuelga de»— que no
 * decía qué relación era, no se veía en ninguna parte y no servía para nada.
 * Aquí está el árbol con la relación de cada una (matriz–filial, franquicia,
 * holding), el permiso que da cada empresa hija a su matriz —lo decide ella y
 * sólo ella: el consumo y unos indicadores sumados, nunca registros— y el
 * agregado que ve la matriz, con las que no comparten dichas como tales y no
 * como cero. La plataforma, además, cuelga una empresa de otra.
 *
 * Comprobado el 09-11-2026 en pruebas de servidor: la filial no ve a sus
 * hermanas, colgar rechaza el círculo y la relación inventada, cambiar de
 * matriz borra lo compartido, la plataforma NO puede conceder por la hija
 * (403) y a la hija que no comparte ni se le pregunta.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { cifra } from "@/lib/formato";
import { listar } from "@/lib/listados";
import type { Sesion } from "@/lib/sesion";
import { cn } from "@/lib/utiles";

interface Nodo {
  id: string;
  slug: string;
  nombre: string;
  estado: string;
  padre_id: string | null;
  relacion: string | null;
  comparte: string[];
  nivel: number;
}

interface Arbol {
  tenant_id: string;
  relaciones: string[];
  nodos: Nodo[];
}

interface Indicador {
  nombre: string;
  valor: number | null;
  porque?: string;
}

interface Agregado {
  hijas: {
    id: string;
    nombre: string;
    relacion: string | null;
    comparte: string[];
    consumo: { filas: { metrica: string; cantidad: number }[] } | null;
    indicadores: Indicador[] | null;
  }[];
  totales: {
    consumo: { metrica: string; cantidad: number; unidad: string }[];
    indicadores: Indicador[];
  };
  no_comparten: string[];
}

const COMPARTIBLE = ["consumo", "indicadores"] as const;

export function GrupoDeEmpresas({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  const tenantId = sesion?.tenant_id ?? "";
  const plataforma = Boolean(sesion?.es_admin_plataforma);
  const [arbol, setArbol] = useState<Arbol | null>(null);
  const [agregado, setAgregado] = useState<Agregado | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const [comparte, setComparte] = useState<string[]>([]);
  const [tenants, setTenants] = useState<{ id: string; nombre: string }[]>([]);
  const [hija, setHija] = useState("");
  const [padre, setPadre] = useState("");
  const [relacion, setRelacion] = useState("matriz_filial");
  // La plataforma puede mirar el árbol de otra empresa; el resto, el suyo.
  const [mirado, setMirado] = useState("");
  const centro = mirado || tenantId;

  const cargar = useCallback(() => {
    if (!centro) return;
    llamar<Arbol>(`/api/v1/tenants/${centro}/jerarquia`)
      .then((r) => {
        setArbol(r.datos);
        const yo = r.datos.nodos.find((n) => n.id === tenantId);
        setComparte(yo?.comparte ?? []);
      })
      .catch((e) => setFallo(e));
    llamar<Agregado>(`/api/v1/tenants/${centro}/jerarquia/agregado`)
      .then((r) => setAgregado(r.datos))
      .catch(() => setAgregado(null));
  }, [centro, tenantId]);
  useEffect(cargar, [cargar]);
  useEffect(() => {
    if (!plataforma) return;
    void listar<{ id: string; nombre: string }>("/api/v1/tenants?limite=200")
      .then(setTenants)
      .catch(() => setTenants([]));
  }, [plataforma]);

  async function guardarComparticion() {
    try {
      await llamar(`/api/v1/tenants/${tenantId}/jerarquia/comparticion`, {
        metodo: "PUT",
        cuerpo: { comparte },
      });
      setAviso(t("grupoEmpresas.compartidoGuardado"));
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function colgar() {
    if (!hija) return;
    try {
      await llamar(`/api/v1/tenants/${hija}/jerarquia`, {
        metodo: "PUT",
        cuerpo: {
          tenant_padre_id: padre || null,
          relacion: padre ? relacion : null,
        },
      });
      setAviso(t("grupoEmpresas.colgada"));
      setMirado(hija);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !arbol) return <Fallo error={fallo} />;
  if (!arbol) return <Cargando />;

  const yo = arbol.nodos.find((n) => n.id === tenantId);
  const tienePadre = Boolean(yo?.padre_id);

  return (
    <>
      <CabeceraPagina
        icono="account_tree"
        titulo={t("grupoEmpresas.titulo")}
        entradilla={t("grupoEmpresas.entradilla")}
      />
      <div role="status" className="mb-3">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>
      {fallo ? <Fallo error={fallo} /> : null}

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-2">{t("grupoEmpresas.arbol")}</h2>
        {plataforma ? (
          <label className="mb-3 flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("grupoEmpresas.verArbolDe")}
            <select
              className="input-base max-w-[20rem]"
              value={centro}
              onChange={(e) => setMirado(e.target.value)}
            >
              {tenants.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.nombre}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {arbol.nodos.length <= 1 ? (
          <Vacio titulo={t("grupoEmpresas.sola")} compacto />
        ) : null}
        <ul aria-label={t("grupoEmpresas.arbol")} className="space-y-1">
          {arbol.nodos.map((n) => (
            <li
              key={n.id}
              className={cn(
                "flex flex-wrap items-baseline gap-2 text-dato",
                n.id === centro && "font-semibold",
              )}
              style={{ paddingLeft: `${n.nivel * 1.5}rem` }}
            >
              <Icono
                nombre={
                  n.nivel === 0 ? "corporate_fare" : "subdirectory_arrow_right"
                }
                tamano="sm"
              />
              <span className="text-ink">{n.nombre}</span>
              {n.relacion ? (
                <span className="chip-dato">
                  {t(`grupoEmpresas.relaciones.${n.relacion}`)}
                </span>
              ) : null}
              {n.padre_id ? (
                <span className="text-rotulo text-ink-faint">
                  {n.comparte.length
                    ? t("grupoEmpresas.comparteCon", {
                        que: n.comparte
                          .map((c) => t(`grupoEmpresas.compartible.${c}`))
                          .join(", "),
                      })
                    : t("grupoEmpresas.noComparte")}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("grupoEmpresas.queComparto")}</h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {tienePadre
            ? t("grupoEmpresas.quecompartoAyuda")
            : t("grupoEmpresas.sinPadre")}
        </p>
        <fieldset className="mb-3 flex flex-wrap gap-4" disabled={!tienePadre}>
          <legend className="sr-only">{t("grupoEmpresas.queComparto")}</legend>
          {COMPARTIBLE.map((c) => (
            <label key={c} className="flex items-center gap-2 text-dato">
              <input
                type="checkbox"
                checked={comparte.includes(c)}
                onChange={() =>
                  setComparte((xs) =>
                    xs.includes(c) ? xs.filter((x) => x !== c) : [...xs, c],
                  )
                }
              />
              {t(`grupoEmpresas.compartible.${c}`)}
            </label>
          ))}
        </fieldset>
        <button
          type="button"
          className="btn-primary"
          disabled={!tienePadre}
          onClick={() => void guardarComparticion()}
        >
          {t("grupoEmpresas.guardarComparticion")}
        </button>
      </section>

      <section className="card mb-4 p-4">
        <h2 className="section-label mb-1">{t("grupoEmpresas.agregado")}</h2>
        <p className="mb-2 text-rotulo text-ink-faint">
          {t("grupoEmpresas.agregadoAyuda")}
        </p>
        {!agregado || agregado.hijas.length === 0 ? (
          <Vacio titulo={t("grupoEmpresas.sinHijas")} compacto />
        ) : (
          <>
            <Rejilla
              titulo={t("grupoEmpresas.agregado")}
              cabeceras={[
                t("grupoEmpresas.empresa"),
                t("grupoEmpresas.relacion"),
                t("grupoEmpresas.compartible.consumo"),
                t("grupoEmpresas.compartible.indicadores"),
              ]}
            >
              {agregado.hijas.map((h) => (
                <tr
                  key={h.id}
                  className="border-b border-ink-dim/30 last:border-0"
                >
                  <Casilla className="font-medium text-ink">{h.nombre}</Casilla>
                  <Casilla>
                    {h.relacion
                      ? t(`grupoEmpresas.relaciones.${h.relacion}`)
                      : "—"}
                  </Casilla>
                  <Casilla>
                    {h.consumo
                      ? h.consumo.filas
                          .map((f) => `${f.metrica}: ${f.cantidad}`)
                          .join(" · ") || "—"
                      : t("grupoEmpresas.noCompartido")}
                  </Casilla>
                  <Casilla>
                    {h.indicadores
                      ? h.indicadores
                          .map(
                            (i) =>
                              `${i.nombre}: ${
                                i.valor === null
                                  ? t("grupoEmpresas.sinLeer")
                                  : cifra(i.valor)
                              }`,
                          )
                          .join(" · ")
                      : t("grupoEmpresas.noCompartido")}
                  </Casilla>
                </tr>
              ))}
            </Rejilla>
            <h3 className="section-label mb-1 mt-4">
              {t("grupoEmpresas.totales")}
            </h3>
            <ul className="text-dato text-ink">
              {agregado.totales.consumo.map((c) => (
                <li key={c.metrica}>
                  {c.metrica}: {cifra(c.cantidad)} {c.unidad}
                </li>
              ))}
              {agregado.totales.indicadores.map((i) => (
                <li key={i.nombre}>
                  {i.nombre}: {cifra(i.valor ?? 0)}
                </li>
              ))}
            </ul>
            {agregado.no_comparten.length ? (
              <p className="mt-2 text-rotulo text-ink-faint">
                {t("grupoEmpresas.noComparten", {
                  nombres: agregado.no_comparten.join(", "),
                })}
              </p>
            ) : null}
          </>
        )}
      </section>

      {plataforma ? (
        <section className="card mb-4 p-4">
          <h2 className="section-label mb-1">{t("grupoEmpresas.colgar")}</h2>
          <p className="mb-2 text-rotulo text-ink-faint">
            {t("grupoEmpresas.colgarAyuda")}
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("grupoEmpresas.empresa")}
              <select
                className="input-base min-w-[14rem]"
                value={hija}
                onChange={(e) => setHija(e.target.value)}
              >
                <option value="">—</option>
                {tenants.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.nombre}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("grupoEmpresas.cuelgaDe")}
              <select
                className="input-base min-w-[14rem]"
                value={padre}
                onChange={(e) => setPadre(e.target.value)}
              >
                <option value="">{t("grupoEmpresas.deNinguna")}</option>
                {tenants
                  .filter((x) => x.id !== hija)
                  .map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.nombre}
                    </option>
                  ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
              {t("grupoEmpresas.relacion")}
              <select
                className="input-base"
                value={relacion}
                disabled={!padre}
                onChange={(e) => setRelacion(e.target.value)}
              >
                {arbol.relaciones.map((r) => (
                  <option key={r} value={r}>
                    {t(`grupoEmpresas.relaciones.${r}`)}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn-primary"
              disabled={!hija}
              onClick={() => void colgar()}
            >
              {t("grupoEmpresas.guardarColgar")}
            </button>
          </div>
        </section>
      ) : null}
    </>
  );
}
