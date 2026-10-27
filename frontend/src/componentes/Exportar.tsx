/**
 * Bajarse un listado a una hoja de cálculo (CRM-05.01.01.07).
 *
 * **Estaba todo hecho menos el botón.** El servidor publica
 * `GET {colección}/exportar` en setenta colecciones, con los filtros de la URL
 * aplicados, las columnas propias del tenant incluidas, la misma proyección
 * por rol que el listado —un CSV que enseña el teléfono que la ficha tapa es
 * la vía más fácil de saltarse la protección, y la más silenciosa—, la marca
 * de origen puesta y el aviso de recorte. El manual de usuario lo describe
 * entero desde hace meses. Y no había forma de pedirlo desde ninguna pantalla:
 * setenta rutas publicadas y cero botones.
 *
 * Tres decisiones que no son de estilo:
 *
 *   · **el botón sale si la colección publica la ruta**, leído de la
 *     superficie. Una lista escrita a mano se quedaría corta en la colección
 *     número setenta y uno, que es justo la que alguien querrá exportar;
 *   · **se manda la URL que se está mirando**, filtros incluidos. Exportar
 *     «todo» cuando en pantalla hay un recorte es la forma de que alguien
 *     mande un fichero con mucho más de lo que creía;
 *   · y **el paso de verificación se explica**. El servidor pide el segundo
 *     factor otra vez para una exportación masiva, y un 401 pintado como «no
 *     autorizado» hace pensar que falta un permiso. Son dos cosas distintas, y
 *     «vuelve a verificarte» y «configúrate un segundo factor» también.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Icono } from "@/componentes/Icono";
import { config } from "@/lib/config";
import { ErrorApi } from "@/lib/api";
import { useSuperficie } from "@/lib/permisos";
import type { Operacion } from "@/lib/superficie";

/** Lo que el servidor manda cuando hace falta volver a verificarse. */
interface Stepup {
  descripcion?: string;
  validez_minutos?: number;
  tiene_factor?: boolean;
}

export function Exportar({
  listar,
  nombre,
  consulta,
}: {
  /** La colección: `/api/v1/cuentas`. */
  listar: string;
  /** Para el nombre del fichero y el rótulo accesible. */
  nombre: string;
  /** Los filtros puestos ahora mismo, tal cual viajan en la URL. */
  consulta: string;
}) {
  const { t } = useTranslation();
  const { superficie } = useSuperficie();
  const [bajando, setBajando] = useState(false);
  const [aviso, setAviso] = useState<string>("");

  // Mientras la superficie no ha llegado no se ofrece: enseñarlo y quitarlo un
  // segundo después mueve los botones bajo el cursor.
  const publicada = (superficie?.operaciones as Operacion[] | undefined)?.some(
    (o) => o.metodo.toUpperCase() === "GET" && o.ruta === `${listar}/exportar`,
  );
  if (!publicada) return null;

  async function bajar() {
    setBajando(true);
    setAviso("");
    try {
      const q = new URLSearchParams(consulta);
      q.set("formato", "csv");
      // Por `fetch` y no por un `<a href>`: con un enlace, un 401 de
      // reverificación abre una pestaña con el JSON del error, y quien lo ve
      // no entiende nada.
      const r = await fetch(`${config().apiBase}${listar}/exportar?${q}`, {
        headers: { Accept: "text/csv" },
        credentials: "include",
      });
      if (!r.ok) {
        const cuerpo = await r.text();
        let codigo = "";
        let detalle: Stepup = {};
        try {
          const json = JSON.parse(cuerpo);
          codigo = String(json.error_code ?? json.codigo ?? "");
          detalle = (json.detalle ?? {}) as Stepup;
        } catch {
          // Un cuerpo que no es JSON no cambia lo que hay que decir.
        }
        if (codigo === "stepup.requerido") {
          setAviso(
            detalle.tiene_factor
              ? t("exportar.vuelveAVerificarte", { minutos: detalle.validez_minutos ?? 15 })
              : t("exportar.sinSegundoFactor"),
          );
          return;
        }
        throw new ErrorApi(r.status, codigo, t("exportar.noSePudo"), detalle, cuerpo.slice(0, 300));
      }

      // Si el servidor ha llegado al tope, se dice ANTES de que el fichero
      // acabe en un correo. Un CSV cortado en silencio es el que alguien manda
      // creyendo que lleva todo.
      const truncada = r.headers.get("X-Exportacion-Truncada") === "1";
      const cuantas = r.headers.get("X-Exportacion-Filas") ?? "";

      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = `${nombre.toLowerCase().replace(/\s+/g, "-")}.csv`;
      enlace.click();
      // Sin esto el blob se queda en memoria hasta que se recargue la página, y
      // exportar cinco listados seguidos deja cinco ficheros enteros dentro.
      URL.revokeObjectURL(url);
      // Qué se ha bajado, dicho: el fichero aparece en la carpeta de descargas
      // sin que la pantalla cambie, y quien lo pulsa no sabe si ha pasado algo.
      setAviso(truncada ? t("exportar.cortado", { cuantas }) : t("exportar.listo"));
    } catch (error) {
      setAviso(error instanceof ErrorApi ? error.titulo : t("exportar.noSePudo"));
    } finally {
      setBajando(false);
    }
  }

  return (
    <span className="flex items-center gap-2">
      <button
        type="button"
        className="btn-secondary"
        onClick={() => void bajar()}
        disabled={bajando}
        aria-label={t("exportar.deQue", { nombre })}
      >
        <Icono nombre="download" /> {bajando ? t("exportar.bajando") : t("exportar.boton")}
      </button>
      {/* En voz alta: el resultado de pulsar esto no se ve en la pantalla, y
          sin anunciarlo quien usa lector de pantalla no se entera de nada. */}
      {aviso ? (
        <span className="text-3xs text-ink-muted" role="status" aria-live="polite">
          {aviso}
        </span>
      ) : null}
    </span>
  );
}
