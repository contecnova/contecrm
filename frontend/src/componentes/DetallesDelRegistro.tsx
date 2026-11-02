/**
 * La pestaña «Detalles» de una ficha: los campos del registro y su rastro.
 *
 * Es el reparto de Lightning —«Relacionado» es lo que cuelga, «Detalles» son
 * los campos— y vivía dentro de la ficha genérica. Sale de ahí porque las tres
 * fichas de a medida **no tenían forma de enseñar los campos**: la de una
 * cuenta enseña su 360 —qué ha pasado, qué cuelga, cómo está—, y para leer su
 * teléfono o su web había que pulsar «Editar». Medido el 02-11-2026.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Retenidos } from "@/componentes/Estados";
import { Celda } from "@/componentes/Tabla";
import { ComoEstabaEsto, HistorialDeCampos } from "@/componentes/Trazabilidad";
import { llamar, salvoCancelacion } from "@/lib/api";
import { escalar, esIdentificadorTecnico, humanizar } from "@/lib/formato";

export function DetallesDelRegistro({
  fila: yaCargada,
  retenidos: yaRetenidos,
  enmascarados: yaEnmascarados,
  ruta,
  objeto,
  servicio,
  id,
}: {
  /**
   * El registro, si quien pinta la pestaña ya lo tiene.
   *
   * La ficha genérica lo carga para el panel de cabecera, así que pedirlo otra
   * vez aquí sería una llamada de más por ficha abierta. Las tres de a medida
   * cargan la vista agregada —el 360 de una cuenta, no sus campos— y por eso
   * no lo tienen: ésas pasan `ruta` y esta pieza lo pide ella.
   */
  fila?: Record<string, unknown> | null;
  retenidos?: string[];
  enmascarados?: string[];
  /** La ruta del registro, para pedirlo cuando no viene dado. */
  ruta?: string;
  /** Tipo del registro (`cuenta`, `oportunidad`…), para su trazabilidad. */
  objeto: string;
  servicio: string;
  id: string;
}) {
  const { t } = useTranslation();
  const [pedida, setPedida] = useState<Record<string, unknown> | null>(null);
  const [retenidosPedidos, setRetenidosPedidos] = useState<string[]>([]);
  const [tapadosPedidos, setTapadosPedidos] = useState<string[]>([]);
  const [fallo, setFallo] = useState<unknown>(null);

  // Sólo si hace falta, y sólo al abrir la pestaña: este componente se monta
  // cuando alguien pulsa «Detalles», no antes.
  useEffect(() => {
    if (yaCargada || !ruta) return undefined;
    const control = new AbortController();
    llamar<Record<string, unknown>>(ruta, { signal: control.signal })
      .then((r) => {
        setPedida(r.datos);
        setRetenidosPedidos(r.retenidos);
        setTapadosPedidos(r.enmascarados);
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [yaCargada, ruta]);

  const fila = yaCargada ?? pedida;
  const retenidos = yaCargada ? (yaRetenidos ?? []) : retenidosPedidos;
  const enmascarados = yaCargada ? (yaEnmascarados ?? []) : tapadosPedidos;

  if (fallo && !fila) return <Fallo error={fallo} />;
  if (!fila) return <Cargando />;

  return (
    <>
      {/* Los datos como ficha, no como una tabla de una sola fila: una tabla
          horizontal de veinte columnas para UN registro obliga a desplazarse
          para leer sus propios campos. */}
      <dl className="card grid gap-x-8 gap-y-3 p-4 sm:grid-cols-2">
        {Object.entries(fila)
          .filter(
            ([clave]) => clave !== "campos" && !esIdentificadorTecnico(clave),
          )
          .map(([clave, valor]) => (
            <Campo key={clave} clave={clave} valor={valor} />
          ))}
      </dl>

      {/* Los identificadores, detrás de un desplegable. Ocupaban la mitad de
          la ficha y no dicen nada a quien la mira, pero quien abre una
          incidencia de soporte los necesita enteros. */}
      <details className="mt-2">
        <summary className="cursor-pointer text-rotulo text-ink-faint">
          {t("ficha.identificadores")}
        </summary>
        <dl className="card mt-2 grid gap-x-8 gap-y-2 p-4 sm:grid-cols-2">
          {Object.entries(fila)
            .filter(([clave]) => esIdentificadorTecnico(clave))
            .map(([clave, valor]) => (
              <Campo key={clave} clave={clave} valor={valor} monoespaciado />
            ))}
        </dl>
      </details>

      <Retenidos campos={retenidos} enmascarados={enmascarados} />

      {/* Qué ha cambiado en ESTE registro, campo a campo. Plegado y cargado
          sólo al abrirlo: es trazabilidad, no contenido, y pedirlo en cada
          ficha abierta sería una llamada más por registro que casi nadie mira.
          Pero cuando hace falta es lo primero que se pregunta —«esto antes no
          decía esto»—, y hasta el 29-10-2026 se escribía y no lo devolvía
          ninguna ruta. */}
      {objeto && servicio ? (
        <HistorialDeCampos servicio={servicio} objeto={objeto} objetoId={id} />
      ) : null}

      {/* Y cómo estaba el registro ENTERO en un momento dado, para los objetos
          que tienen el rastro completo encendido. El historial de campos dice
          qué cambió; no dice cómo era el conjunto, y reconstruirlo a mano
          encadenando cambios sale mal en cuanto hay una fusión por medio. */}
      {objeto && servicio ? (
        <ComoEstabaEsto servicio={servicio} objeto={objeto} objetoId={id} />
      ) : null}
    </>
  );
}

function Campo({
  clave,
  valor,
  monoespaciado = false,
}: {
  clave: string;
  valor: unknown;
  monoespaciado?: boolean;
}) {
  // El rótulo encima y el valor debajo, como el panel de datos clave de
  // arriba y como la pestaña «Detalles» de Lightning. Estaban enfrentados a
  // los dos extremos de la fila: en una pantalla ancha quedaban 900 px entre
  // «Nombre» y «Ana», y emparejar rótulo y valor a esa distancia no se hace
  // de un vistazo. Dos sitios del producto que enseñan lo mismo —aquí y
  // arriba— ahora lo colocan igual.
  return (
    <div className="min-w-0">
      <dt className="truncate text-rotulo text-ink-faint" title={humanizar(clave)}>
        {humanizar(clave)}
      </dt>
      <dd
        className={`truncate text-dato text-ink ${monoespaciado ? "font-mono text-rotulo text-ink-muted" : ""}`}
        title={String(valor ?? "")}
      >
        {/* Un valor compuesto se pinta con el MISMO renderizador que la tabla.
            Aquí iba `JSON.stringify(valor)`, así que la ficha de un registro
            enseñaba `{"esquema":"CNAE","codigo":"2932"}` donde la tabla del
            listado enseña dos etiquetas legibles. La misma información, en dos
            pantallas del mismo producto, con dos formatos — y el de la ficha
            nadie lo lee de un vistazo. */}
        {valor === null || valor === undefined || valor === "" ? (
          <span className="text-ink-faint">—</span>
        ) : typeof valor === "object" ? (
          <Celda valor={valor} campo={clave} />
        ) : (
          escalar(valor, clave)
        )}
      </dd>
    </div>
  );
}
