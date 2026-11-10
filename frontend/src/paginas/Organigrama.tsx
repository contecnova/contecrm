/**
 * El organigrama: quién depende de quién (CRM-00.03.05.07).
 *
 * Medido el 10-11-2026: nada escribía el superior de nadie —SCIM ignoraba el
 * `manager` del directorio, el SSO no lo trae y no había pantalla—, así que en
 * una empresa sin directorio ningún presupuesto se podía aprobar (el motor
 * busca «el superior de quien lo envía») y la revisión de accesos caía entera
 * en el revisor por defecto.
 *
 * Aquí se ve el árbol, se fija o cambia el superior de cada persona —que se
 * mueve con todo su equipo—, se pasa el equipo de una persona a otra y no se
 * ofrece como superior a nadie que dependa de ella: un círculo no se puede ni
 * elegir, y el servidor lo rechaza igual si llega. De cada superior se dice de
 * dónde salió (el directorio o a mano) y si el próximo envío del directorio lo
 * pisará, que depende del ajuste `organigrama_externo_manda`.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { usePuedeOperar } from "@/lib/permisos";
import { cn } from "@/lib/utiles";

interface Persona {
  usuario_id: string;
  nombre: string;
  email: string;
  activa: boolean;
  roles: string[];
  superior_id: string | null;
  origen: "" | "manual" | "scim";
  fijado_at: string | null;
  fijado_por: string | null;
}

interface Arbol {
  personas: Persona[];
  truncado: boolean;
  tope: number;
  externo_manda: boolean;
}

/** Los que dependen de cada uno, directamente. */
function hijosPorSuperior(personas: Persona[]): Map<string, Persona[]> {
  const ids = new Set(personas.map((p) => p.usuario_id));
  const mapa = new Map<string, Persona[]>();
  for (const p of personas) {
    // Quien cuelga de alguien que no está en la lista sale como raíz: no se
    // esconde por tener un superior que no se ve.
    const clave = p.superior_id && ids.has(p.superior_id) ? p.superior_id : "";
    mapa.set(clave, [...(mapa.get(clave) ?? []), p]);
  }
  return mapa;
}

/** La persona y todo su equipo, a cualquier profundidad. */
function equipoDe(id: string, hijos: Map<string, Persona[]>): Set<string> {
  const salida = new Set<string>([id]);
  const pila = [id];
  while (pila.length) {
    for (const h of hijos.get(pila.pop() as string) ?? []) {
      if (!salida.has(h.usuario_id)) {
        salida.add(h.usuario_id);
        pila.push(h.usuario_id);
      }
    }
  }
  return salida;
}

export function Organigrama() {
  const { t } = useTranslation();
  const puede = usePuedeOperar();
  const [arbol, setArbol] = useState<Arbol | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [aviso, setAviso] = useState("");
  const [elegida, setElegida] = useState("");
  const [superior, setSuperior] = useState("");
  const [destinoEquipo, setDestinoEquipo] = useState("");
  const [busca, setBusca] = useState("");

  const cargar = useCallback(() => {
    llamar<Arbol>("/api/v1/organigrama")
      .then((r) => setArbol(r.datos))
      .catch((e) => setFallo(e));
  }, []);
  useEffect(cargar, [cargar]);

  const personas = useMemo(() => arbol?.personas ?? [], [arbol]);
  const porId = useMemo(
    () => new Map(personas.map((p) => [p.usuario_id, p])),
    [personas],
  );
  const hijos = useMemo(() => hijosPorSuperior(personas), [personas]);
  const persona = porId.get(elegida) ?? null;

  // Al elegir a alguien, el formulario arranca con lo que tiene.
  useEffect(() => {
    setSuperior(persona?.superior_id ?? "");
    setDestinoEquipo("");
  }, [persona]);

  const escribir = puede(
    "PUT",
    `/api/v1/organigrama/${elegida || "x"}/superior`,
  );
  const directos = persona ? (hijos.get(persona.usuario_id) ?? []) : [];
  // Ni ella ni nadie de su equipo puede ser su superior: sería un círculo.
  const prohibidos = useMemo(
    () => (persona ? equipoDe(persona.usuario_id, hijos) : new Set<string>()),
    [persona, hijos],
  );
  const candidatos = personas.filter(
    (p) => p.activa && !prohibidos.has(p.usuario_id),
  );
  // Para el equipo, el destino no puede estar dentro del equipo que se mueve
  // (la persona sí: no tendría sentido, y el servidor lo rechaza).
  const destinos = personas.filter(
    (p) => p.activa && !prohibidos.has(p.usuario_id),
  );

  const texto = busca.trim().toLowerCase();
  const coinciden = texto
    ? personas.filter(
        (p) =>
          p.nombre.toLowerCase().includes(texto) ||
          p.email.toLowerCase().includes(texto),
      )
    : [];

  async function guardarSuperior() {
    if (!persona) return;
    try {
      await llamar(`/api/v1/organigrama/${persona.usuario_id}/superior`, {
        metodo: "PUT",
        cuerpo: { superior_id: superior || null },
      });
      setAviso(
        superior
          ? t("organigrama.colgada", {
              persona: persona.nombre,
              superior: porId.get(superior)?.nombre ?? "",
            })
          : t("organigrama.deRaiz", { persona: persona.nombre }),
      );
      setFallo(null);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  async function moverEquipo() {
    if (!persona) return;
    try {
      const r = await llamar<{ movidas: number }>(
        `/api/v1/organigrama/${persona.usuario_id}/equipo`,
        { metodo: "POST", cuerpo: { a_id: destinoEquipo || null } },
      );
      setAviso(
        t("organigrama.equipoMovido", {
          n: r.datos.movidas,
          destino: destinoEquipo
            ? (porId.get(destinoEquipo)?.nombre ?? "")
            : t("organigrama.nadie"),
        }),
      );
      setFallo(null);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  if (fallo && !arbol) return <Fallo error={fallo} reintentar={cargar} />;
  if (!arbol) return <Cargando />;

  const sinSuperior = personas.filter((p) => p.activa && !p.superior_id);
  // Quien está en un círculo de datos viejos no cuelga de ninguna raíz y no
  // saldría en el árbol: se enseña aparte para que se pueda deshacer.
  const raices = hijos.get("") ?? [];
  const alcanzados = new Set<string>();
  for (const r of raices)
    for (const id of equipoDe(r.usuario_id, hijos)) alcanzados.add(id);
  const enCirculo = personas.filter((p) => !alcanzados.has(p.usuario_id));
  const deScim = personas.filter((p) => p.origen === "scim").length;
  const aMano = personas.filter((p) => p.origen === "manual").length;

  // Funciones que pintan y no componentes: un componente declarado dentro de
  // otro se monta de nuevo en cada render y pierde el foco del botón.
  function fila(p: Persona, nivel: number, vistos = new Set<string>()) {
    // Los vistos cortan un círculo: sin ellos, pintarlo no acabaría nunca.
    const suyos = (hijos.get(p.usuario_id) ?? []).filter(
      (h) => !vistos.has(h.usuario_id),
    );
    const camino = new Set(vistos).add(p.usuario_id);
    return (
      <li key={p.usuario_id}>
        <button
          type="button"
          onClick={() => setElegida(p.usuario_id)}
          aria-current={p.usuario_id === elegida ? "true" : undefined}
          className={cn(
            "flex w-full flex-wrap items-baseline gap-2 rounded px-2 py-1 text-left text-dato hover:bg-paper-light",
            p.usuario_id === elegida && "bg-paper-light font-semibold",
            !p.activa && "text-ink-faint",
          )}
          style={{ paddingLeft: `${nivel * 1.25 + 0.5}rem` }}
        >
          <Icono
            nombre={nivel === 0 ? "person" : "subdirectory_arrow_right"}
            tamano="sm"
          />
          <span className="min-w-0 break-words text-ink">{p.nombre}</span>
          {suyos.length ? (
            <span className="text-rotulo text-ink-faint">
              {t("organigrama.directos", { n: suyos.length })}
            </span>
          ) : null}
          {origen(p)}
          {!p.activa ? (
            <span className="chip-dato chip-dato--no">
              {t("organigrama.baja")}
            </span>
          ) : null}
        </button>
        {suyos.length ? (
          <ul>{suyos.map((h) => fila(h, nivel + 1, camino))}</ul>
        ) : null}
      </li>
    );
  }

  function origen(p: Persona) {
    if (p.origen === "scim")
      return <span className="chip-dato">{t("organigrama.deScim")}</span>;
    if (p.origen === "manual")
      return (
        <span className="chip-dato chip-dato--aviso">
          {t("organigrama.aMano")}
        </span>
      );
    return null;
  }

  return (
    <>
      <CabeceraPagina
        icono="supervisor_account"
        titulo={t("organigrama.titulo")}
        entradilla={t("organigrama.entradilla")}
        acciones={
          <Link to="/revision-accesos" className="btn-secondary">
            <Icono nombre="how_to_reg" tamano="sm" />
            {t("nav.revisionAccesos")}
          </Link>
        }
      />
      <div role="status" className="mb-3">
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
        {fallo ? <Fallo error={fallo} /> : null}
      </div>

      <p className="mb-2 text-dato text-ink-muted">
        {t("organigrama.resumen", {
          personas: personas.length,
          sinSuperior: sinSuperior.length,
          scim: deScim,
          mano: aMano,
        })}
      </p>
      <p className="mb-4 text-rotulo text-ink-faint">
        {arbol.externo_manda
          ? t("organigrama.externoManda")
          : t("organigrama.manoManda")}
      </p>
      {arbol.truncado ? (
        <p className="mb-4 text-dato text-warning">
          {t("organigrama.truncado", { tope: arbol.tope })}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section className="card min-w-0 p-4">
          <h2 className="section-label mb-2">{t("organigrama.arbol")}</h2>
          <label className="mb-3 flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("organigrama.buscar")}
            <input
              type="search"
              className="input-base"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </label>
          {personas.length === 0 ? (
            <Vacio titulo={t("organigrama.vacio")} compacto />
          ) : texto ? (
            <ul aria-label={t("organigrama.buscar")}>
              {coinciden.length === 0 ? (
                <li className="text-dato text-ink-faint">
                  {t("organigrama.nadieCoincide")}
                </li>
              ) : (
                coinciden.map((p) => (
                  <li key={p.usuario_id}>
                    <button
                      type="button"
                      className="flex w-full flex-wrap items-baseline gap-2 rounded px-2 py-1 text-left text-dato hover:bg-paper-light"
                      onClick={() => setElegida(p.usuario_id)}
                    >
                      <span className="text-ink">{p.nombre}</span>
                      <span className="text-rotulo text-ink-faint">
                        {p.superior_id
                          ? t("organigrama.dependeDe", {
                              superior: porId.get(p.superior_id)?.nombre ?? "",
                            })
                          : t("organigrama.sinSuperior")}
                      </span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          ) : (
            <>
              <ul aria-label={t("organigrama.arbol")}>
                {raices.map((p) => fila(p, 0))}
              </ul>
              {enCirculo.length ? (
                <>
                  <p className="mt-3 text-dato text-warning">
                    {t("organigrama.enCirculo", { n: enCirculo.length })}
                  </p>
                  <ul>{enCirculo.map((p) => fila(p, 0))}</ul>
                </>
              ) : null}
            </>
          )}
        </section>

        <section className="card min-w-0 p-4">
          <h2 className="section-label mb-2">{t("organigrama.persona")}</h2>
          {!persona ? (
            <Vacio titulo={t("organigrama.elige")} compacto />
          ) : (
            <>
              <p className="text-dato font-semibold text-ink">
                {persona.nombre}
              </p>
              <p className="mb-2 break-words text-rotulo text-ink-faint">
                {persona.email}
                {persona.roles.length ? ` · ${persona.roles.join(", ")}` : ""}
              </p>
              <p className="mb-3 flex flex-wrap items-center gap-2 text-rotulo text-ink-muted">
                {origen(persona)}
                {persona.origen === "manual" && persona.fijado_at
                  ? t("organigrama.fijadoEl", {
                      cuando: fechaHora(persona.fijado_at),
                      quien:
                        porId.get(persona.fijado_por ?? "")?.nombre ??
                        t("organigrama.alguien"),
                    })
                  : null}
                {persona.origen === "scim"
                  ? arbol.externo_manda
                    ? t("organigrama.scimLoPisa")
                    : t("organigrama.scimNoLoPisa")
                  : null}
              </p>

              <label className="mb-2 flex flex-col gap-1 text-rotulo text-ink-muted">
                {t("organigrama.superior")}
                <select
                  className="input-base"
                  value={superior}
                  disabled={!escribir}
                  onChange={(e) => setSuperior(e.target.value)}
                >
                  <option value="">{t("organigrama.sinSuperior")}</option>
                  {candidatos.map((p) => (
                    <option key={p.usuario_id} value={p.usuario_id}>
                      {p.nombre}
                    </option>
                  ))}
                </select>
              </label>
              <p className="mb-2 text-rotulo text-ink-faint">
                {t("organigrama.superiorAyuda", {
                  n: prohibidos.size - 1,
                })}
              </p>
              {escribir ? (
                <button
                  type="button"
                  className="btn-primary mb-4"
                  disabled={superior === (persona.superior_id ?? "")}
                  onClick={() => void guardarSuperior()}
                >
                  <Icono nombre="save" tamano="sm" />
                  {t("organigrama.guardar")}
                </button>
              ) : null}

              <h3 className="section-label mb-1 mt-2">
                {t("organigrama.suEquipo", { n: directos.length })}
              </h3>
              {directos.length === 0 ? (
                <p className="text-rotulo text-ink-faint">
                  {t("organigrama.sinEquipo")}
                </p>
              ) : (
                <>
                  <ul className="mb-2 text-dato text-ink">
                    {directos.map((d) => (
                      <li key={d.usuario_id}>{d.nombre}</li>
                    ))}
                  </ul>
                  {escribir ? (
                    <div className="flex flex-wrap items-end gap-2">
                      <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-rotulo text-ink-muted">
                        {t("organigrama.moverA")}
                        <select
                          className="input-base"
                          value={destinoEquipo}
                          onChange={(e) => setDestinoEquipo(e.target.value)}
                        >
                          <option value="">{t("organigrama.nadie")}</option>
                          {destinos.map((p) => (
                            <option key={p.usuario_id} value={p.usuario_id}>
                              {p.nombre}
                            </option>
                          ))}
                        </select>
                      </label>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => void moverEquipo()}
                      >
                        <Icono nombre="move_down" tamano="sm" />
                        {t("organigrama.moverEquipo")}
                      </button>
                    </div>
                  ) : null}
                </>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}
