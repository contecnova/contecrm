/**
 * Cuadros de mando (CRM-05.01.02.01, CRM-05.01.02.02, CRM-05.01.02.03).
 *
 * Los tipos de componente se piden al servidor, **no se escriben aquí**: dos
 * listas que tienen que coincidir acaban no coincidiendo, y la que se queda corta
 * es siempre la del front.
 *
 * El filtro de arriba es del cuadro entero y llega a todos los componentes menos
 * a los que se declaran inmunes. Y de cada componente se puede bajar al detalle:
 * un cuadro del que no se puede bajar obliga a rehacer la consulta a mano en otra
 * pantalla, y ahí ya no coinciden los números.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { ErrorApi, llamar } from "@/lib/api";
import { CabeceraPagina } from "@/componentes/Pagina";

interface Componente {
  informe?: string;
  tipo: string;
  titulo?: string;
  ignora_filtros?: boolean;
}

interface Cuadro {
  id: string;
  clave: string;
  nombre: string;
  descripcion: string;
  componentes: Componente[];
  por_defecto: boolean;
  propio: boolean;
}

export function Cuadros() {
  const { t } = useTranslation();
  const [cuadros, setCuadros] = useState<Cuadro[] | null>(null);
  const [abierto, setAbierto] = useState<string | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<Cuadro[]>("/api/v1/cuadros-mando", { signal: control.signal })
      .then((r) => {
        setCuadros(r.datos);
        const defecto = r.datos.find((c) => c.por_defecto) ?? r.datos[0];
        setAbierto(defecto ? defecto.id : null);
      })
      .catch((e: unknown) => {
        if (e instanceof ErrorApi) setFallo(e);
      });
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!cuadros) return <Cargando />;
  if (cuadros.length === 0)
    return (
      <div className="p-4">
        <Vacio titulo={t("cuadros.ninguno")} detalle={t("cuadros.ningunoDetalle")} />
      </div>
    );

  // El `find` puede no encontrar nada y `cuadros[0]` puede ser `undefined` para
  // TypeScript aunque ya sepamos que la lista no está vacía. Se resuelve con una
  // guarda explícita en vez de con `!`: la aserción calla al compilador y deja
  // la pantalla en blanco el día que la lista llegue vacía por otra vía.
  const actual = cuadros.find((c) => c.id === abierto) ?? cuadros[0];
  if (!actual) return <Cargando />;

  return (
    <div className="flex flex-col gap-4">
      <CabeceraPagina
        titulo={t("cuadros.titulo")}
        icono="dashboard"
        acciones={
          <>
            <label htmlFor="cuadros-elegir" className="sr-only">
              {t("cuadros.elegir")}
            </label>
            <select
              id="cuadros-elegir"
              value={actual.id}
              onChange={(e) => setAbierto(e.target.value)}
              className="input-sm"
            >
              {cuadros.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre}
                </option>
              ))}
            </select>
          </>
        }
      />

      {actual.descripcion ? (
        <p className="max-w-prose text-2xs text-ink-muted">{actual.descripcion}</p>
      ) : null}

      {actual.componentes.length === 0 ? (
        <Vacio titulo={t("cuadros.sinComponentes")} detalle={t("cuadros.sinComponentesDetalle")} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {actual.componentes.map((c, i) => (
            <article
              key={`${c.tipo}-${i}`}
              className="rounded-lg border border-ink-dim/40 bg-paper-light p-3"
            >
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="text-sm text-ink">{c.titulo ?? c.informe ?? c.tipo}</h2>
                <span className="text-3xs uppercase text-ink-faint">{c.tipo}</span>
              </div>
              {/* Que un componente ignore el filtro global se DICE: si no, quien
                  cambia el trimestre y ve una cifra que no se mueve concluye que
                  el filtro no funciona. */}
              {c.ignora_filtros ? (
                <p className="mt-1 text-3xs text-ink-faint">{t("cuadros.ignoraFiltros")}</p>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
