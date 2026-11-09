/**
 * Las credenciales de una conexión: fijarlas, rotarlas y probar la conexión
 * (CRM-00.01.04.08).
 *
 * `PUT /integraciones/conexiones/{id}/credenciales` existía, cifraba y
 * versionaba, y no lo llamaba ninguna pantalla: la ficha genérica sólo ofrece
 * las acciones `POST`, así que la única forma de poner la clave del ERP era la
 * API. Aquí se fija **con los campos que pide su tipo de autenticación** —un
 * `client_secret` para OAuth, un usuario y una contraseña para básica—, y lo
 * que se enseña de la guardada es **cuándo y quién**, nunca el valor: ni
 * enmascarado, porque un valor tapado tiene la forma de un dato y alguien
 * acaba copiándolo como si fuera la clave.
 *
 * Y al lado, «Probar la conexión»: es como se descubre una credencial
 * caducada antes de que falle un proceso de negocio.
 */

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { llamar } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { useSuperficie } from "@/lib/permisos";
import { nombreDe, usePersonas } from "@/lib/personas";

interface Campo {
  clave: string;
  secreto: boolean;
}

interface Version {
  version: number;
  activa: boolean;
  fijada_at: string | null;
  fijada_por: string | null;
  rotada_at: string | null;
  caduca_at: string | null;
  claves: string[];
}

interface Estado {
  auth_tipo: string;
  campos: Campo[];
  actual: Version | null;
  anteriores: Version[];
  se_puede_probar: boolean;
  prueba: {
    probada_at: string | null;
    ok: boolean | null;
    detalle: string | null;
  };
}

export function CredencialesDeConexion({ conexionId }: { conexionId: string }) {
  const { t } = useTranslation();
  const { tiene } = useSuperficie();
  const personas = usePersonas();
  const [estado, setEstado] = useState<Estado | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [abierto, setAbierto] = useState(false);
  const [valores, setValores] = useState<Record<string, string>>({});
  const [caduca, setCaduca] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso] = useState("");

  const ruta = `/api/v1/integraciones/conexiones/${conexionId}/credenciales`;

  const cargar = useCallback(() => {
    llamar<Estado>(ruta)
      .then((r) => setEstado(r.datos))
      .catch(setFallo);
  }, [ruta]);
  useEffect(cargar, [cargar]);

  async function guardar(evento: FormEvent) {
    evento.preventDefault();
    setEnviando(true);
    setFallo(null);
    try {
      const r = await llamar<{ version: number; rotada: boolean }>(ruta, {
        metodo: "PUT",
        cuerpo: {
          valores,
          caduca_at: caduca ? new Date(caduca).toISOString() : null,
        },
      });
      // Lo tecleado se olvida en cuanto se guarda: un secreto que se queda en
      // el estado de la pantalla es un secreto que sale en una captura.
      setValores({});
      setCaduca("");
      setAbierto(false);
      setAviso(
        r.datos.rotada
          ? t("credenciales.rotada", { version: r.datos.version })
          : t("credenciales.fijada"),
      );
      cargar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  async function probar() {
    setEnviando(true);
    setFallo(null);
    try {
      const r = await llamar<{ ok: boolean; detalle: string }>(
        `/api/v1/integraciones/conexiones/${conexionId}/probar`,
        { metodo: "POST" },
      );
      setAviso(
        r.datos.ok
          ? t("credenciales.pruebaBien", { detalle: r.datos.detalle })
          : t("credenciales.pruebaMal", { detalle: r.datos.detalle }),
      );
      cargar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  if (!estado) {
    return fallo ? (
      <section className="card mb-4 p-4">
        <Fallo error={fallo} reintentar={cargar} />
      </section>
    ) : null;
  }

  const puedeFijar = tiene("integracion:credenciales");
  const actual = estado.actual;
  const completo = estado.campos.every((c) => (valores[c.clave] ?? "").trim());

  return (
    <section className="card mb-4 p-4" aria-labelledby="credenciales-titulo">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="credenciales-titulo" className="section-label">
          {t("credenciales.titulo")}
        </h2>
        <div className="flex flex-wrap gap-2">
          {estado.se_puede_probar ? (
            <button
              type="button"
              className="btn-secondary"
              disabled={enviando}
              onClick={() => void probar()}
            >
              <Icono nombre="network_check" tamano="sm" />
              {t("credenciales.probar")}
            </button>
          ) : null}
          {puedeFijar && estado.campos.length > 0 && !abierto ? (
            <button
              type="button"
              className="btn-primary"
              onClick={() => setAbierto(true)}
            >
              <Icono nombre="key" tamano="sm" />
              {actual ? t("credenciales.rotar") : t("credenciales.fijar")}
            </button>
          ) : null}
        </div>
      </div>

      <p className="mb-2 text-rotulo text-ink-faint">
        {t("credenciales.tipo", { tipo: estado.auth_tipo })}
        {estado.campos.length === 0 ? ` ${t("credenciales.sinCampos")}` : ""}
      </p>

      {/* Cuándo y quién: es todo lo que se puede contar de un secreto que no se
          enseña. Si nunca se fijó se dice, que es la causa más común de una
          integración que no trae nada. */}
      <div role="status">
        {actual ? (
          <p className="text-dato text-ink">
            {t("credenciales.actual", {
              version: actual.version,
              cuando: fechaHora(actual.fijada_at),
              quien: actual.fijada_por
                ? nombreDe(personas, actual.fijada_por)
                : t("credenciales.nadie"),
            })}
            {actual.caduca_at
              ? ` ${t("credenciales.caduca", { cuando: fechaHora(actual.caduca_at) })}`
              : ` ${t("credenciales.sinCaducidad")}`}
          </p>
        ) : estado.campos.length > 0 ? (
          <p className="text-dato text-warning">{t("credenciales.ninguna")}</p>
        ) : null}
        {actual && actual.claves.length ? (
          <p className="text-rotulo text-ink-faint">
            {t("credenciales.claves", { claves: actual.claves.join(", ") })}
          </p>
        ) : null}
        {estado.prueba.probada_at ? (
          <p
            className={
              estado.prueba.ok
                ? "text-rotulo text-success"
                : "text-rotulo text-danger"
            }
          >
            {t("credenciales.ultimaPrueba", {
              cuando: fechaHora(estado.prueba.probada_at),
              detalle: estado.prueba.detalle ?? "",
            })}
          </p>
        ) : null}
        {aviso ? <p className="text-dato text-success">{aviso}</p> : null}
      </div>

      {estado.anteriores.length ? (
        <details className="mt-2 text-rotulo text-ink-faint">
          <summary className="cursor-pointer">
            {t("credenciales.anteriores", { n: estado.anteriores.length })}
          </summary>
          <ul className="mt-1 space-y-0.5">
            {estado.anteriores.map((v) => (
              <li key={v.version}>
                {t("credenciales.anterior", {
                  version: v.version,
                  cuando: fechaHora(v.fijada_at),
                  quien: v.fijada_por
                    ? nombreDe(personas, v.fijada_por)
                    : t("credenciales.nadie"),
                  rotada: fechaHora(v.rotada_at),
                })}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {abierto ? (
        <form
          className="mt-3 grid gap-2 md:grid-cols-2"
          onSubmit={(e) => void guardar(e)}
          autoComplete="off"
        >
          {estado.campos.map((c) => (
            <label
              key={c.clave}
              className="flex flex-col gap-1 text-rotulo text-ink-muted"
            >
              {t(`credenciales.campos.${c.clave}`, { defaultValue: c.clave })}
              <input
                className="input-base"
                type={c.secreto ? "password" : "text"}
                // `new-password` y no `off`: es lo único que impide de verdad
                // que el navegador rellene el campo con la contraseña de la
                // sesión del CRM.
                autoComplete={c.secreto ? "new-password" : "off"}
                value={valores[c.clave] ?? ""}
                onChange={(e) =>
                  setValores({ ...valores, [c.clave]: e.target.value })
                }
              />
            </label>
          ))}
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("credenciales.caducaCampo")}
            <input
              className="input-base"
              type="date"
              value={caduca}
              onChange={(e) => setCaduca(e.target.value)}
            />
          </label>
          <div className="flex items-end gap-2 md:col-span-2">
            <button
              type="submit"
              className="btn-primary"
              disabled={!completo || enviando}
            >
              {t("credenciales.guardar")}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setValores({});
                setAbierto(false);
              }}
            >
              {t("credenciales.cancelar")}
            </button>
          </div>
          <p className="text-rotulo text-ink-faint md:col-span-2">
            {t("credenciales.ayudaRotar")}
          </p>
        </form>
      ) : null}

      {fallo ? (
        <div className="mt-2">
          <Fallo error={fallo} />
        </div>
      ) : null}
    </section>
  );
}
