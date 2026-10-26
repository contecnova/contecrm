/**
 * Documentos que esperan tu decisión (RT-5).
 *
 * Es la bandeja unificada de CRM-00.03.05.13: lo que me toca decidir con el
 * contexto suficiente para decidirlo. Enseña además CRM-00.03.05.06 (las
 * cadenas y el quórum, tal como los resuelve el motor) y CRM-00.03.05.07 (quién
 * es el aprobador, que viene resuelto y no se deduce aquí).
 *
 * El motor de aprobación es de contecmind: quórum, segregación de funciones y
 * en qué orden firma cada uno viven allí. Esta pantalla **no lo reimplementa**,
 * ni siquiera un poco:
 *
 * **Los botones se pintan según `puedo_decidir`, que viene dado.** Es la
 * respuesta del propio motor, no una deducción de aquí. Calcularla en el
 * navegador —«si el estado es pendiente y no soy quien la pidió»— parece fácil
 * y se desincroniza el primer día que cambie una regla allí, enseñando botones
 * que dan 403. Un botón que falla al pulsarlo es peor que un botón que no está.
 *
 * **Y la bandeja es de quien pregunta.** Va con su token, así que nadie ve lo
 * que espera la firma de otro. No hay filtro por persona porque no hay nada que
 * filtrar: el listado ya llega acotado.
 *
 * Lo que sí es de aquí es avisar por correo. contecmind no conoce la dirección
 * de una persona del CRM —no tiene ficha suya, por diseño—, así que el único
 * que puede avisar es quien sabe a quién.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { usePuedeOperar } from "@/lib/permisos";

/** Las tres que acepta el gestor. Cualquier otra la para el servidor. */
const DECISIONES = ["approved", "rejected", "delegated"] as const;
type Decision = (typeof DECISIONES)[number];

interface Solicitud {
  id: string;
  document_id?: string | null;
  version_no?: number | null;
  entity_summary?: string | null;
  status: string;
  current_step?: number | null;
  requested_by_user_id?: string;
  puedo_decidir?: boolean;
}

export function Aprobaciones() {
  const { t } = useTranslation();
  const puedeOperar = usePuedeOperar();
  const [solicitudes, setSolicitudes] = useState<Solicitud[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [recargar, setRecargar] = useState(0);
  // Se pregunta ANTES si hay corpus en este despliegue. Sin esto, quien entra
  // en un CRM sin contecmind se encuentra un error rojo donde debería leer una
  // frase: no está roto, está apagado, y son dos cosas distintas.
  const [corpus, setCorpus] = useState<{
    activo?: boolean;
    alcanzable?: boolean;
    url?: string | null;
    error?: string | null;
    sin_el?: string;
  } | null>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<{
      activo?: boolean;
      alcanzable?: boolean;
      url?: string | null;
      error?: string | null;
      sin_el?: string;
    }>("/api/v1/documentos/estado", {
      signal: control.signal,
    })
      .then((r) => setCorpus(r.datos))
      .catch(salvoCancelacion(() => setCorpus({ activo: true })));
    return () => control.abort();
  }, []);

  useEffect(() => {
    // Ni apagado ni caído: pedir la bandeja a un gestor que no responde solo
    // sirve para cambiar una explicación clara por el error que salga primero
    // —y el que salía era «este tenant no tiene organización asignada», que
    // manda a configurar algo cuando lo que pasa es que contecmind no está—.
    if (corpus && (corpus.activo === false || corpus.alcanzable === false)) return;
    const control = new AbortController();
    llamar<{ items: Solicitud[] }>("/api/v1/documentos/aprobaciones/pendientes", {
      signal: control.signal,
    })
      .then((r) => setSolicitudes(r.datos.items ?? []))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [recargar, corpus]);

  // El permiso de aquí y el del motor son dos puertas distintas y las dos
  // cuentan: el CRM decide quién puede tocar documentos, y el gestor a quién le
  // toca esta solicitud.
  const puedeDecidirAqui = puedeOperar(
    "POST",
    "/api/v1/documentos/aprobaciones/x/decidir",
  );

  return (
    <>
      <CabeceraPagina
        titulo={t("aprobaciones.titulo")}
        icono="approval"
        entradilla={t("aprobaciones.intro")}
      />
      {corpus?.activo === false ? (
        <p className="mt-4 text-xs text-ink-muted">
          {t("aprobaciones.sinCorpus")}
          {corpus.sin_el ? ` ${corpus.sin_el}.` : ""}
        </p>
      ) : null}
      {corpus?.activo !== false && corpus?.alcanzable === false ? (
        // Con la dirección y el error del gestor: «no responde» a secas obliga
        // a abrir los logs para saber si es la URL, la red o que está parado.
        <p className="mt-4 text-xs text-ink-muted">
          {t("aprobaciones.corpusCaido", { url: corpus.url ?? "" })}
          {corpus.error ? ` (${corpus.error})` : ""}
        </p>
      ) : null}
      {fallo && corpus?.activo !== false && corpus?.alcanzable !== false ? (
        <Fallo error={fallo} />
      ) : null}
      <div className="mt-4">
        {solicitudes === null && !fallo && corpus === null ? <Cargando /> : null}
        {solicitudes !== null && solicitudes.length === 0 ? (
          <p className="text-xs text-ink-muted">{t("aprobaciones.nadaPendiente")}</p>
        ) : null}
        <ul className="space-y-2">
          {(solicitudes ?? []).map((s) => (
            <Fila
              key={s.id}
              solicitud={s}
              puedeDecidirAqui={puedeDecidirAqui}
              alDecidir={() => setRecargar((n) => n + 1)}
            />
          ))}
        </ul>
      </div>
    </>
  );
}

function Fila({
  solicitud,
  puedeDecidirAqui,
  alDecidir,
}: {
  solicitud: Solicitud;
  puedeDecidirAqui: boolean;
  alDecidir: () => void;
}) {
  const { t } = useTranslation();
  const [abierta, setAbierta] = useState<Decision | null>(null);
  const [comentario, setComentario] = useState("");
  const [delegarEn, setDelegarEn] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [resultado, setResultado] = useState<string | null>(null);

  const decidir = useCallback(async () => {
    if (!abierta) return;
    setEnviando(true);
    setFallo(null);
    try {
      const r = await llamar<{ status?: string }>(
        `/api/v1/documentos/aprobaciones/${solicitud.id}/decidir`,
        {
          metodo: "POST",
          cuerpo: {
            decision: abierta,
            comentario,
            delegar_en: abierta === "delegated" ? delegarEn : "",
          },
        },
      );
      // Aprobar NO siempre acaba en «publicado»: si el reindexado falla, la
      // versión queda aprobada y sigue publicada la anterior. Se enseña el
      // estado que contesta el gestor en vez de dar por hecho el final feliz,
      // que pintaría como roto algo que funciona.
      setResultado(r.datos.status ?? "");
      setAbierta(null);
      alDecidir();
    } catch (e) {
      setFallo(e);
    } finally {
      setEnviando(false);
    }
  }, [abierta, comentario, delegarEn, solicitud.id, alDecidir]);

  // Dos condiciones, y las dos tienen que darse: el permiso del CRM y el turno
  // según el motor.
  const puede = puedeDecidirAqui && solicitud.puedo_decidir !== false;

  return (
    <li className="rounded-lg border border-ink-dim/30 px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs text-ink">
            {solicitud.entity_summary || solicitud.document_id || solicitud.id}
          </p>
          <p className="text-3xs text-ink-faint">
            {t("aprobaciones.estado", { estado: solicitud.status })}
            {solicitud.version_no ? ` · v${solicitud.version_no}` : ""}
            {solicitud.current_step ? ` · ${t("aprobaciones.etapa", { n: solicitud.current_step })}` : ""}
          </p>
        </div>
        {puede ? (
          <div className="flex shrink-0 gap-1">
            {DECISIONES.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setAbierta(abierta === d ? null : d)}
                aria-pressed={abierta === d}
                className={`rounded border border-ink-dim/60 px-2 py-0.5 text-2xs ${
                  abierta === d ? "bg-paper-light text-ink" : "text-ink-muted"
                }`}
              >
                {t(`aprobaciones.decision.${d}`)}
              </button>
            ))}
          </div>
        ) : (
          // Se dice POR QUÉ no hay botones. Una fila sin ellos y sin
          // explicación se lee como una pantalla a medias.
          <span className="shrink-0 text-3xs text-ink-faint">
            {t("aprobaciones.noTeToca")}
          </span>
        )}
      </div>

      {abierta ? (
        <div className="mt-2 space-y-2 border-t border-ink-dim/30 pt-2">
          <label className="block text-3xs text-ink-faint" htmlFor={`c-${solicitud.id}`}>
            {t("aprobaciones.comentario")}
          </label>
          <textarea
            id={`c-${solicitud.id}`}
            value={comentario}
            onChange={(e) => setComentario(e.target.value)}
            rows={2}
            className="w-full rounded border border-ink-dim/60 bg-paper px-2 py-1 text-xs text-ink"
          />
          {abierta === "delegated" ? (
            <>
              <label className="block text-3xs text-ink-faint" htmlFor={`d-${solicitud.id}`}>
                {t("aprobaciones.delegarEn")}
              </label>
              <input
                id={`d-${solicitud.id}`}
                value={delegarEn}
                onChange={(e) => setDelegarEn(e.target.value)}
                className="w-full rounded border border-ink-dim/60 bg-paper px-2 py-1 text-xs text-ink"
              />
            </>
          ) : null}
          <button
            type="button"
            onClick={() => void decidir()}
            // Delegar sin decir en quién es la mitad de una decisión: el gestor
            // lo rechaza, así que se para antes.
            disabled={enviando || (abierta === "delegated" && !delegarEn.trim())}
            className="rounded border border-ink-dim/60 px-3 py-1 text-xs text-ink disabled:opacity-50"
          >
            {enviando ? t("aprobaciones.enviando") : t("aprobaciones.confirmar")}
          </button>
        </div>
      ) : null}

      {/* El contenedor está SIEMPRE, aunque vacío: un `role="status"` que
          aparece a la vez que su texto no siempre se lee, porque el lector
          puede no haber registrado la región cuando ya tiene contenido. */}
      <p role="status" className="mt-2 text-3xs text-ink-faint">
        {resultado !== null ? t("aprobaciones.decidida", { estado: resultado }) : ""}
      </p>
      {fallo ? <Fallo error={fallo} /> : null}
    </li>
  );
}

/**
 * El estado real de un documento del corpus.
 *
 * Lo que el enlace del CRM no sabe: si está indexado, si se indexó con avisos y
 * qué es. Se pregunta al abrirlo y no se guarda en el enlace, porque un estado
 * copiado envejece sin avisar y aquí envejecer significa enseñar «aprobado» de
 * una versión que ya no es la vigente.
 *
 * Si el gestor no contesta, esto se calla y no tumba el panel: la aprobación es
 * lo que se viene a hacer, y el estado es contexto.
 */
function EstadoDelDocumento({ documentoId }: { documentoId: string }) {
  const { t } = useTranslation();
  const [ficha, setFicha] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const control = new AbortController();
    llamar<Record<string, unknown>>(`/api/v1/documentos/ficha/${documentoId}`, {
      signal: control.signal,
    })
      .then((r) => setFicha(r.datos))
      .catch(salvoCancelacion(() => setFicha(null)));
    return () => control.abort();
  }, [documentoId]);

  if (!ficha) return null;
  const avisos = Array.isArray(ficha.partial_warnings) ? ficha.partial_warnings.length : 0;
  return (
    <p className="text-3xs text-ink-faint">
      {t("aprobaciones.indexado", { estado: String(ficha.status ?? "") })}
      {/* Los avisos se dicen. «Indexado» a secas cuando se cayeron las figuras
          o las tablas hace creer que la búsqueda lo encuentra todo. */}
      {avisos > 0 ? ` · ${t("aprobaciones.conAvisos", { n: avisos })}` : ""}
      {ficha.mime_type ? ` · ${String(ficha.mime_type)}` : ""}
    </p>
  );
}

/**
 * La aprobación de UN documento, para la ficha de un registro.
 *
 * Vive aquí y no en `Ficha.tsx` para que la bandeja y la ficha digan lo mismo
 * con las mismas palabras: son la misma información mirada desde dos sitios, y
 * dos implementaciones acaban discrepando justo en el matiz que importa —el de
 * «aprobado» contra «publicado»—.
 */
export function AprobacionDeDocumento({ documentoId }: { documentoId: string }) {
  const { t } = useTranslation();
  const puedeOperar = usePuedeOperar();
  const [estado, setEstado] = useState<{
    puedo_pedir?: boolean;
    control_state?: string;
    current_version_no?: number;
    requires_approval?: boolean;
    solicitud?: Solicitud | null;
  } | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [flujos, setFlujos] = useState<
    { id: string; name: string; exige_aprobadores?: boolean }[] | null
  >(null);
  const [flujo, setFlujo] = useState("");
  const [aprobadores, setAprobadores] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [recargar, setRecargar] = useState(0);

  useEffect(() => {
    const control = new AbortController();
    llamar<typeof estado & object>(`/api/v1/documentos/aprobacion/${documentoId}`, {
      signal: control.signal,
    })
      .then((r) => setEstado(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [documentoId, recargar]);

  useEffect(() => {
    const control = new AbortController();
    llamar<{ items: { id: string; name: string; exige_aprobadores?: boolean }[] }>(
      "/api/v1/documentos/aprobaciones/flujos",
      { signal: control.signal },
    )
      .then((r) => setFlujos(r.datos.items ?? []))
      // Quedarse sin flujos no impide pedir la aprobación: sin flujo se
      // resuelve el que toque. Por eso este fallo no tumba el panel.
      .catch(salvoCancelacion(() => setFlujos([])));
    return () => control.abort();
  }, []);

  const elegido = (flujos ?? []).find((f) => f.id === flujo);
  // Si el flujo elegido los exige, se piden ANTES de dejar enviar: el gestor
  // contesta 422 y ese error llegaría después de rellenar el formulario.
  const faltanAprobadores = Boolean(elegido?.exige_aprobadores) && !aprobadores.trim();

  const pedir = useCallback(async () => {
    setEnviando(true);
    setFallo(null);
    try {
      await llamar(`/api/v1/documentos/aprobacion/${documentoId}`, {
        metodo: "POST",
        cuerpo: {
          flujo_id: flujo,
          aprobadores: aprobadores
            .split(/[,\s]+/)
            .map((s) => s.trim())
            .filter(Boolean),
        },
      });
      setRecargar((n) => n + 1);
    } catch (e) {
      setFallo(e);
    } finally {
      setEnviando(false);
    }
  }, [documentoId, flujo, aprobadores]);

  if (fallo) return <Fallo error={fallo} />;
  if (estado === null) return <Cargando />;

  const solicitud = estado.solicitud;
  const puedePedirAqui = puedeOperar("POST", `/api/v1/documentos/aprobacion/${documentoId}`);

  return (
    <div className="space-y-2">
      <EstadoDelDocumento documentoId={documentoId} />
      <p className="text-3xs text-ink-faint">
        {t("aprobaciones.controlEstado", {
          estado: estado.control_state ?? "",
          version: estado.current_version_no ?? "",
        })}
      </p>
      {solicitud ? (
        <p role="status" className="text-xs text-ink">
          {t("aprobaciones.enCurso", { estado: solicitud.status })}
        </p>
      ) : estado.requires_approval === false ? (
        <p className="text-xs text-ink-muted">{t("aprobaciones.noLaNecesita")}</p>
      ) : (
        <Vacio />
      )}

      {!solicitud && estado.puedo_pedir && puedePedirAqui ? (
        <div className="space-y-2 border-t border-ink-dim/30 pt-2">
          <label className="block text-3xs text-ink-faint" htmlFor={`f-${documentoId}`}>
            {t("aprobaciones.flujo")}
          </label>
          <select
            id={`f-${documentoId}`}
            value={flujo}
            onChange={(e) => setFlujo(e.target.value)}
            className="w-full rounded border border-ink-dim/60 bg-paper px-2 py-1 text-xs text-ink"
          >
            {/* Sin elegir ninguno se resuelve el que toque, y eso se dice: un
                desplegable vacío se lee como «falta rellenar esto». */}
            <option value="">{t("aprobaciones.flujoElQueToque")}</option>
            {(flujos ?? []).map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
          <label className="block text-3xs text-ink-faint" htmlFor={`a-${documentoId}`}>
            {elegido?.exige_aprobadores
              ? t("aprobaciones.aprobadoresExigidos")
              : t("aprobaciones.aprobadores")}
          </label>
          <input
            id={`a-${documentoId}`}
            value={aprobadores}
            onChange={(e) => setAprobadores(e.target.value)}
            placeholder={t("aprobaciones.aprobadoresPista")}
            className="w-full rounded border border-ink-dim/60 bg-paper px-2 py-1 text-xs text-ink"
          />
          <button
            type="button"
            onClick={() => void pedir()}
            disabled={enviando || faltanAprobadores}
            className="rounded border border-ink-dim/60 px-3 py-1 text-xs text-ink disabled:opacity-50"
          >
            {enviando ? t("aprobaciones.enviando") : t("aprobaciones.pedir")}
          </button>
          {faltanAprobadores ? (
            <p className="text-3xs text-ink-faint">{t("aprobaciones.faltanAprobadores")}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
