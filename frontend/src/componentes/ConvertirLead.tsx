/**
 * Convertir un lead en cliente, contacto y oportunidad, en un solo paso
 * (CRM-01.01.03.01).
 *
 * **Lo que había.** La acción del contrato pedía una cuenta **que ya existiera**
 * —el maestro de clientes es de `party` y ventas no escribe en él—, así que
 * convertir el lead de una empresa nueva obligaba a salir, dar de alta el
 * cliente en otra pantalla, dar de alta el contacto en otra, volver al lead y
 * elegir los dos en dos desplegables. Medido el 10-11-2026 (tarea T02): la
 * tarea más típica de un comercial no se podía terminar desde la ficha. En
 * Salesforce es un botón y un diálogo con todo propuesto.
 *
 * **Lo que hace ahora.** Propone lo que el lead ya dice —la empresa como
 * cliente, la persona como contacto, una oportunidad con el nombre de la
 * empresa— y lo crea en orden con las mismas rutas de siempre: el cliente y el
 * contacto en `party`, la conversión en `sales`. Nada de escribir en el esquema
 * de otro servicio.
 *
 * **Si ya existe el cliente**, se ofrece usarlo: se busca por el nombre de la
 * empresa y, si hay uno que se llama exactamente así, sale elegido. Dar de alta
 * un segundo «Talleres Pons» es el duplicado que más cuesta deshacer después.
 *
 * **Si algo falla a medias** —el cliente se creó y la conversión no—, lo creado
 * se queda elegido: repetir no crea otro.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Error as Fallo } from "@/componentes/Estados";
import { llamar } from "@/lib/api";

interface Lead {
  nombre?: string | null;
  apellidos?: string | null;
  empresa?: string | null;
  email?: string | null;
  telefono?: string | null;
  cargo?: string | null;
}

interface Candidata {
  id: string;
  nombre: string;
}

/** Para comparar nombres: sin acentos, sin mayúsculas y sin espacios de más. */
function plano(texto: string): string {
  return texto
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function ConvertirLead({
  leadId,
  lead,
  alCancelar,
}: {
  leadId: string;
  lead: Lead;
  alCancelar: () => void;
}) {
  const { t } = useTranslation();
  const navegar = useNavigate();
  const persona = [lead.nombre, lead.apellidos].filter(Boolean).join(" ");
  const empresa = (lead.empresa ?? "").trim() || persona;

  const [candidatas, setCandidatas] = useState<Candidata[]>([]);
  const [cuentaElegida, setCuentaElegida] = useState<string>(""); // "" = nueva
  const [nombreCuenta, setNombreCuenta] = useState(empresa);
  const [conContacto, setConContacto] = useState(Boolean(lead.nombre));
  const [conOportunidad, setConOportunidad] = useState(true);
  const [nombreOportunidad, setNombreOportunidad] = useState(empresa);
  const [importe, setImporte] = useState("");
  const [cierre, setCierre] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  // Lo ya creado en un intento anterior, para no crearlo dos veces.
  const [creados, setCreados] = useState<{
    cuenta?: string;
    contacto?: string;
  }>({});

  // Los clientes que ya se llaman como la empresa del lead.
  useEffect(() => {
    if (!empresa) return;
    const control = new AbortController();
    llamar<{
      resultados: { objeto: string; registro_id: string; titulo: string }[];
    }>(`/api/v1/buscar?q=${encodeURIComponent(empresa)}&limite=20`, {
      signal: control.signal,
    })
      .then(({ datos }) => {
        const suyas = (datos?.resultados ?? [])
          .filter((r) => r.objeto === "cuenta")
          .slice(0, 5)
          .map((r) => ({ id: r.registro_id, nombre: r.titulo }));
        setCandidatas(suyas);
        const igual = suyas.find((c) => plano(c.nombre) === plano(empresa));
        if (igual) setCuentaElegida(igual.id);
      })
      // Sin buscador se propone crearla, que es lo que se haría a mano.
      .catch(() => undefined);
    return () => control.abort();
  }, [empresa]);

  async function convertir() {
    setEnviando(true);
    setFallo(null);
    try {
      let cuentaId = cuentaElegida || creados.cuenta;
      if (!cuentaId) {
        const { datos } = await llamar<{ id: string }>("/api/v1/accounts", {
          metodo: "POST",
          cuerpo: { nombre: nombreCuenta.trim() || empresa },
        });
        cuentaId = datos.id;
        setCreados((c) => ({ ...c, cuenta: datos.id }));
      }
      let contactoId = creados.contacto;
      if (conContacto && !contactoId) {
        const { datos } = await llamar<{ id: string }>("/api/v1/contacts", {
          metodo: "POST",
          cuerpo: {
            nombre: lead.nombre || persona || empresa,
            apellidos: lead.apellidos || undefined,
            email: lead.email || undefined,
            telefono: lead.telefono || undefined,
            cargo: lead.cargo || undefined,
            cuenta_id: cuentaId,
          },
        });
        contactoId = datos.id;
        setCreados((c) => ({ ...c, contacto: datos.id }));
      }
      const { datos } = await llamar<{
        cuenta_id: string;
        oportunidad_id: string | null;
      }>(`/api/v1/leads/${leadId}/convertir`, {
        metodo: "POST",
        cuerpo: {
          cuenta_id: cuentaId,
          contacto_id: contactoId ?? null,
          crear_oportunidad: conOportunidad,
          nombre_oportunidad: conOportunidad
            ? nombreOportunidad.trim() || null
            : null,
          importe: conOportunidad && importe ? Number(importe) : null,
          fecha_cierre: conOportunidad && cierre ? cierre : null,
        },
      });
      // Se sigue por donde sigue el trabajo: la oportunidad si la hay, y si
      // no, el cliente.
      navegar(
        datos.oportunidad_id
          ? `/m/oportunidades/oportunidad/${datos.oportunidad_id}`
          : `/m/cuentas/cuenta/${datos.cuenta_id}`,
      );
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  const nuevaYaCreada = Boolean(creados.cuenta && !cuentaElegida);

  return (
    <section className="card mb-4 p-4" aria-labelledby="convertir-lead-titulo">
      <h2 id="convertir-lead-titulo" className="section-label mb-1">
        {t("convertirLead.titulo")}
      </h2>
      <p className="mb-3 text-dato text-ink-muted">
        {t("convertirLead.entradilla")}
      </p>

      <form
        className="grid gap-4 md:grid-cols-3"
        onSubmit={(e) => {
          e.preventDefault();
          void convertir();
        }}
      >
        {/* ── El cliente ── */}
        <fieldset className="min-w-0 space-y-2">
          <legend className="label-base">{t("convertirLead.cliente")}</legend>
          <label className="flex items-center gap-2 text-dato text-ink">
            <input
              type="radio"
              name="cuenta"
              checked={!cuentaElegida}
              onChange={() => setCuentaElegida("")}
            />
            {nuevaYaCreada
              ? t("convertirLead.yaCreada")
              : t("convertirLead.crearCliente")}
          </label>
          {!cuentaElegida && !nuevaYaCreada ? (
            <input
              aria-label={t("convertirLead.nombreCliente")}
              value={nombreCuenta}
              onChange={(e) => setNombreCuenta(e.target.value)}
              required
              className="input-base"
            />
          ) : null}
          {candidatas.length ? (
            <p className="text-rotulo text-ink-faint">
              {t("convertirLead.yaExisten")}
            </p>
          ) : null}
          {candidatas.map((c) => (
            <label
              key={c.id}
              className="flex items-center gap-2 text-dato text-ink"
            >
              <input
                type="radio"
                name="cuenta"
                checked={cuentaElegida === c.id}
                onChange={() => setCuentaElegida(c.id)}
              />
              <span className="truncate">
                {t("convertirLead.usar", { nombre: c.nombre })}
              </span>
            </label>
          ))}
        </fieldset>

        {/* ── El contacto ── */}
        <fieldset className="min-w-0 space-y-2">
          <legend className="label-base">{t("convertirLead.contacto")}</legend>
          <label className="flex items-center gap-2 text-dato text-ink">
            <input
              type="checkbox"
              checked={conContacto}
              onChange={(e) => setConContacto(e.target.checked)}
            />
            {t("convertirLead.crearContacto")}
          </label>
          {conContacto ? (
            <p className="text-dato text-ink-muted">
              {[persona, lead.email, lead.telefono]
                .filter(Boolean)
                .join(" · ") || t("convertirLead.sinPersona")}
            </p>
          ) : null}
        </fieldset>

        {/* ── La oportunidad ── */}
        <fieldset className="min-w-0 space-y-2">
          <legend className="label-base">
            {t("convertirLead.oportunidad")}
          </legend>
          <label className="flex items-center gap-2 text-dato text-ink">
            <input
              type="checkbox"
              checked={conOportunidad}
              onChange={(e) => setConOportunidad(e.target.checked)}
            />
            {t("convertirLead.crearOportunidad")}
          </label>
          {conOportunidad ? (
            <>
              <input
                aria-label={t("convertirLead.nombreOportunidad")}
                value={nombreOportunidad}
                onChange={(e) => setNombreOportunidad(e.target.value)}
                className="input-base"
              />
              <div className="grid grid-cols-2 gap-2">
                <label className="min-w-0">
                  <span className="label-base">
                    {t("convertirLead.importe")}
                  </span>
                  <input
                    type="number"
                    min={0}
                    step="any"
                    value={importe}
                    onChange={(e) => setImporte(e.target.value)}
                    className="input-base"
                  />
                </label>
                <label className="min-w-0">
                  <span className="label-base">
                    {t("convertirLead.cierre")}
                  </span>
                  <input
                    type="date"
                    value={cierre}
                    onChange={(e) => setCierre(e.target.value)}
                    className="input-base"
                  />
                </label>
              </div>
            </>
          ) : null}
        </fieldset>

        <div className="flex flex-wrap gap-2 md:col-span-3">
          <button type="submit" disabled={enviando} className="btn-primary">
            {enviando ? t("app.cargando") : t("convertirLead.convertir")}
          </button>
          <button type="button" onClick={alCancelar} className="btn-secondary">
            {t("modulo.cancelar")}
          </button>
        </div>
      </form>

      {fallo ? (
        <div className="mt-3">
          <Fallo error={fallo} />
        </div>
      ) : null}
    </section>
  );
}
