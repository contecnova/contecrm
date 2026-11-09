/**
 * Botones que bajan un documento de la colección como fichero JSON.
 *
 * Para los `GET` que no son una lista sino un documento —la política de
 * acceso en formato neutro (CRM-00.05.02.06)—: la pestaña los listaba como
 * una fila suelta o no los enseñaba. Dice qué se ha bajado, porque un fichero
 * que aparece en la carpeta de descargas no es un resultado que se vea.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Error as Fallo } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { llamar } from "@/lib/api";

export interface Descarga {
  ruta: string;
  nombre: string;
  fichero: string;
  detalle?: string;
}

export function Descargas({ descargas }: { descargas: Descarga[] }) {
  const { t } = useTranslation();
  const [bajando, setBajando] = useState("");
  const [hecho, setHecho] = useState("");
  const [fallo, setFallo] = useState<unknown>(null);

  async function bajar(d: Descarga) {
    setBajando(d.ruta);
    setFallo(null);
    setHecho("");
    try {
      const { datos } = await llamar<unknown>(d.ruta);
      const texto = JSON.stringify(datos, null, 2);
      const url = URL.createObjectURL(
        new Blob([texto], { type: "application/json" }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = d.fichero;
      a.click();
      URL.revokeObjectURL(url);
      setHecho(
        t("descargas.bajado", { fichero: d.fichero, bytes: texto.length }),
      );
    } catch (e) {
      setFallo(e);
    } finally {
      setBajando("");
    }
  }

  return (
    <div className="mb-3 flex flex-wrap items-start gap-3">
      {descargas.map((d) => (
        <div key={d.ruta} className="flex flex-col gap-1">
          <button
            type="button"
            className="btn-secondary"
            disabled={bajando === d.ruta}
            onClick={() => void bajar(d)}
          >
            <Icono nombre="download" tamano="sm" />
            {d.nombre}
          </button>
          {d.detalle ? (
            <span className="text-rotulo text-ink-faint">{d.detalle}</span>
          ) : null}
        </div>
      ))}
      <p role="status" aria-live="polite" className="text-dato text-ink-muted">
        {hecho}
      </p>
      {fallo ? <Fallo error={fallo} /> : null}
    </div>
  );
}
