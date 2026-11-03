/**
 * La biblioteca de archivos (CRM-06.01.01.05).
 *
 * **La pregunta que no se podía contestar: «¿dónde está ese contrato?»**. Los
 * documentos se veían desde el registro del que cuelgan, y **sólo** desde ahí:
 * para encontrar uno había que acordarse antes de a qué cuenta pertenece, que
 * es justo lo que no se recuerda. En Salesforce «Archivos» es una pestaña
 * desde el primer día, y es donde va la gente a buscar un adjunto.
 *
 * **Lo que la hace honesta es decir de dónde cuelga cada uno.** Una lista de
 * nombres de fichero sin su registro es un listado de la base de datos: lo que
 * convierte «contrato-2026.pdf» en algo útil es «de Metalúrgica del Norte», y
 * el enlace para ir allí.
 *
 * **Y decir a qué servicio no se ha podido preguntar.** Los documentos los
 * guarda cada servicio en su esquema, el gateway los junta, y una lista corta
 * y una lista incompleta se leen igual: si falta alguno, se dice arriba.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar, salvoCancelacion } from "@/lib/api";
import { config } from "@/lib/config";
import { fecha, humanizar } from "@/lib/formato";
import { moduloDeObjeto } from "@/lib/modulos";
import { nombresDeRegistros, type NombresResueltos } from "@/lib/nombres";

interface Documento {
  id: string;
  objeto_tipo: string;
  objeto_id: string;
  nombre: string;
  extension: string;
  tamano: number;
  version: number;
  /** pendiente | limpio | infectado | omitido */
  analisis: string;
  descripcion: string;
  externo_sistema: string;
  created_at: string | null;
  servicio: string;
}

interface Respuesta {
  documentos: Documento[];
  cuantos: number;
  /** Servicios que no contestaron: puede haber documentos que no salen. */
  sin_respuesta: string[];
  hay_mas: boolean;
  aviso: string;
}

/**
 * El tamaño, en lo que lee una persona.
 *
 * En bytes no se lee: «1048576» obliga a contar ceros. Mil y no 1.024 a
 * propósito: lo que se pregunta aquí es si un fichero es grande, no cuántos
 * sectores ocupa.
 */
function tamanoLegible(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  const unidades = ["B", "kB", "MB", "GB"];
  let valor = bytes;
  let i = 0;
  while (valor >= 1000 && i < unidades.length - 1) {
    valor /= 1000;
    i += 1;
  }
  return `${valor.toFixed(i === 0 ? 0 : 1)} ${unidades[i]}`;
}

export function Archivos() {
  const { t } = useTranslation();
  const [buscar, setBuscar] = useState("");
  const [datos, setDatos] = useState<Respuesta | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  /** Cómo se llama el registro del que cuelga cada documento, y qué se ha
      podido mirar. */
  const [resueltos, setResueltos] = useState<NombresResueltos>({
    nombres: new Map(),
    preguntados: new Set(),
  });

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    // Con espera: una petición por pulsación son diez consultas para escribir
    // «contrato», y además cada una va a tres servicios.
    const espera = window.setTimeout(() => {
      const texto = buscar.trim();
      (async () => {
        const { datos: pagina } = await llamar<Respuesta>(
          `/api/v1/adjuntos?limite=100${texto ? `&buscar=${encodeURIComponent(texto)}` : ""}`,
          { signal: control.signal },
        );
        setDatos(pagina);
        // **Y de QUÉ registro cuelga cada uno.** Sin esto la columna decía
        // «Oportunidad» y nada más, que es media respuesta: lo que convierte
        // «pliego-tecnico.txt» en algo útil es de qué oportunidad es. Va
        // después de pintar la lista a propósito: los nombres son una mejora
        // de lo que ya se ve, no una condición para verlo.
        setResueltos(await nombresDeRegistros(pagina.documentos ?? [], control.signal));
      })().catch(salvoCancelacion(setFallo));
    }, 250);
    return () => {
      window.clearTimeout(espera);
      control.abort();
    };
  }, [buscar]);

  useEffect(cargar, [cargar]);

  const filas = useMemo(() => datos?.documentos ?? [], [datos]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;

  return (
    <>
      <CabeceraPagina
        titulo={t("archivos.titulo")}
        icono="folder_open"
        entradilla={t("archivos.entradilla")}
      />

      {/* La misma caja que en Conocimiento, con la misma clase y el mismo
          ancho: dos buscadores del producto que hacen lo mismo no pueden
          verse distintos. */}
      <div className="mb-3 max-w-md">
        <input
          type="search"
          value={buscar}
          onChange={(e) => setBuscar(e.target.value)}
          placeholder={t("archivos.buscar")}
          aria-label={t("archivos.buscar")}
          className="input-base"
        />
      </div>

      {/* Un servicio mudo se dice. Sin esto, una lista corta se lee como «no
          hay más documentos» y puede ser «no se ha podido preguntar». */}
      {datos && (datos.sin_respuesta.length > 0 || datos.hay_mas) ? (
        <p className="card mb-3 border-warning/40 p-3 text-dato text-warning" role="status">
          {datos.aviso}
        </p>
      ) : null}

      {!datos ? (
        <Cargando />
      ) : filas.length === 0 ? (
        <Vacio
          titulo={t(buscar.trim() ? "archivos.ningunoAsi" : "archivos.ninguno")}
          detalle={t(
            buscar.trim() ? "archivos.ningunoAsiPorque" : "archivos.ningunoPorque",
          )}
        />
      ) : (
        <Rejilla
          titulo={t("archivos.titulo")}
          cabeceras={[
            t("archivos.nombre"),
            t("archivos.de"),
            t("archivos.cuando"),
            t("archivos.tamano"),
          ]}
        >
          {filas.map((d) => {
            const modulo = moduloDeObjeto(d.objeto_tipo);
            const nombre = resueltos.nombres.get(d.objeto_id) ?? "";
            const infectado = d.analisis === "infectado";
            return (
              <tr key={d.id} className="border-b border-ink-dim/30 last:border-0">
                <Casilla>
                  <span className="flex items-center gap-1.5">
                    {/* El aviso del análisis va PEGADO al nombre: un fichero
                        infectado en una fila más de la lista se abre igual
                        que los demás. */}
                    {infectado ? (
                      <Icono nombre="dangerous" tamano="sm" className="shrink-0 text-danger" />
                    ) : null}
                    {d.externo_sistema ? (
                      <Icono
                        nombre="open_in_new"
                        tamano="sm"
                        className="shrink-0 text-ink-faint"
                      />
                    ) : null}
                    {infectado ? (
                      // Un infectado NO se enlaza: el servidor ya se niega a
                      // entregarlo, y ofrecer el enlace es ofrecer algo que
                      // contesta un error.
                      <span className="text-danger">{d.nombre}</span>
                    ) : (
                      <a
                        className="text-accent hover:underline"
                        href={`${config().apiBase}/api/v1/adjuntos/${encodeURIComponent(
                          d.objeto_tipo,
                        )}/${d.id}/contenido`}
                      >
                        {d.nombre}
                      </a>
                    )}
                    {d.version > 1 ? (
                      <span className="badge badge-muted">
                        {t("archivos.version", { version: d.version })}
                      </span>
                    ) : null}
                  </span>
                  {d.descripcion ? (
                    <p className="mt-0.5 text-rotulo text-ink-faint">{d.descripcion}</p>
                  ) : null}
                </Casilla>
                {/* De dónde cuelga. Es lo que convierte un nombre de fichero
                    en algo que sirve: «contrato-2026.pdf» no dice nada sin
                    «de una oportunidad», y menos sin el enlace para ir. */}
                <Casilla>
                  {nombre && modulo ? (
                    <Link
                      className="text-accent hover:underline"
                      to={`/m/${modulo}/${d.objeto_tipo}/${d.objeto_id}`}
                    >
                      {nombre}
                    </Link>
                  ) : (
                    // **Sin nombre no se enlaza.** El enlace llevaría a una
                    // ficha que contesta 404, y ofrecerlo es peor que no
                    // ofrecerlo. Y se dice por qué no se sabe: «ya no existe»
                    // sólo de lo que se ha podido mirar y no estaba.
                    <span className="text-ink-muted">
                      {humanizar(d.objeto_tipo)}
                      {" · "}
                      {t(
                        resueltos.preguntados.has(d.objeto_tipo)
                          ? "archivos.registroBorrado"
                          : "archivos.registroSinMirar",
                      )}
                    </span>
                  )}
                  {/* El tipo debajo cuando ya se sabe el nombre: «Metalúrgica
                      del Norte» no dice si es la cuenta o una oportunidad
                      suya, y son dos fichas distintas. */}
                  {nombre ? (
                    <p className="mt-0.5 text-rotulo text-ink-faint">
                      {humanizar(d.objeto_tipo)}
                    </p>
                  ) : null}
                </Casilla>
                <Casilla enUnaLinea className="text-ink-muted">
                  {fecha(d.created_at)}
                </Casilla>
                <Casilla enUnaLinea className="text-ink-muted">
                  {tamanoLegible(d.tamano)}
                </Casilla>
              </tr>
            );
          })}
        </Rejilla>
      )}
    </>
  );
}
