/**
 * Lo que sigo: la vuelta del botón «Seguir».
 *
 * **Lo que había, medido el 03-11-2026.** `/api/v1/seguimientos` sólo salía
 * como una pestaña del módulo de administración, y ahí lo que se lee es
 * «cuenta · propietario · sí»: el tipo, el motivo y si está silenciado, **sin
 * el nombre del registro y sin forma de abrirlo**. Quien sigue cinco cuentas
 * ve que sigue cinco cuentas y no cuáles. Eso no es una vuelta: es un recuento.
 *
 * Aquí se resuelven los nombres. **Una llamada por tipo de objeto, no una por
 * registro**: los listados aceptan `id__en=a,b,c`, así que cinco cuentas y tres
 * casos son dos llamadas. Una por registro serían ocho y crecerían con lo que
 * siga cada uno.
 *
 * **Lo que ya no existe se dice, no se cae de la lista.** Un registro seguido
 * puede haberse borrado —en la instalación servida hay tres así—, y quitarlo
 * en silencio deja una lista más corta que el contador sin que nadie sepa por
 * qué. Sale con su aviso y con el botón de dejar de seguirlo, que es lo único
 * que se puede hacer con él.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { humanizar, nombreDelRegistro } from "@/lib/formato";
import { moduloDe, moduloDeObjeto } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";

interface Seguimiento {
  id: string;
  objeto_tipo: string;
  objeto_id: string;
  motivo: string;
  silenciado: boolean;
}

interface Pagina<T> {
  items: T[];
  siguiente: string | null;
  hay_mas: boolean;
}

/** Un seguimiento con lo que se ha podido averiguar del registro. */
interface Fila extends Seguimiento {
  /** El nombre del registro, o cadena vacía si ya no está. */
  nombre: string;
  /** A dónde lleva, o cadena vacía si no hay ficha a la que llevar. */
  a: string;
}

/**
 * Los nombres de un montón de registros del mismo tipo, de una vez.
 *
 * Devuelve lo que ha podido: un tipo sin módulo declarado —o un listado que
 * falla— deja esos registros sin nombre, y eso se enseña como «ya no está» o
 * como el tipo a secas, nunca como si no existieran.
 */
async function nombresDe(
  objetoTipo: string,
  ids: string[],
  signal: AbortSignal,
): Promise<Map<string, string>> {
  const nombres = new Map<string, string>();
  const ruta = moduloDeObjeto(objetoTipo);
  if (!ruta) return nombres;
  const modulo = moduloDe(ruta);
  const recurso = modulo ? recursoDe(modulo, objetoTipo) : undefined;
  if (!recurso) return nombres;
  try {
    const { datos } = await llamar<Pagina<Record<string, unknown>>>(
      `${recurso.listar}?id__en=${ids.join(",")}&limite=200`,
      { signal },
    );
    for (const fila of datos.items ?? []) {
      const id = String(fila.id ?? "");
      if (id) nombres.set(id, nombreDelRegistro(fila));
    }
  } catch {
    // Un tipo que no contesta no puede dejar la pantalla entera sin pintar:
    // lo suyo sale sin nombre y lo demás sigue leyéndose.
  }
  return nombres;
}

export function LoQueSigo() {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Fila[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [quitando, setQuitando] = useState("");
  // Lo que se canta al dejar de seguir. Sin esto, quien no ve la pantalla
  // pulsa el botón y la fila desaparece sin que nada se lo diga.
  const [dicho, setDicho] = useState("");

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    setFilas(null);
    (async () => {
      const { datos } = await llamar<Pagina<Seguimiento>>(
        "/api/v1/seguimientos?limite=200",
        { signal: control.signal },
      );
      const seguidos = datos.items ?? [];
      const porTipo = new Map<string, string[]>();
      for (const s of seguidos) {
        porTipo.set(s.objeto_tipo, [...(porTipo.get(s.objeto_tipo) ?? []), s.objeto_id]);
      }
      const nombres = new Map<string, string>();
      for (const [tipo, ids] of porTipo) {
        for (const [id, nombre] of await nombresDe(tipo, ids, control.signal)) {
          nombres.set(id, nombre);
        }
      }
      setFilas(
        seguidos.map((s) => {
          const ruta = moduloDeObjeto(s.objeto_tipo);
          const nombre = nombres.get(s.objeto_id) ?? "";
          return {
            ...s,
            nombre,
            a: ruta && nombre ? `/m/${ruta}/${s.objeto_tipo}/${s.objeto_id}` : "",
          };
        }),
      );
    })().catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  async function dejar(fila: Fila) {
    setQuitando(fila.id);
    try {
      await llamar(
        `/api/v1/seguimientos/${encodeURIComponent(fila.objeto_tipo)}/${encodeURIComponent(
          fila.objeto_id,
        )}`,
        { metodo: "DELETE" },
      );
      setDicho(t("seguir.dejado"));
      cargar();
    } catch (error) {
      setFallo(error);
    } finally {
      setQuitando("");
    }
  }

  if (fallo && !filas) return <Fallo error={fallo} reintentar={cargar} />;
  if (!filas) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("seguir.loQueSigo")}
        icono="notifications_active"
        entradilla={t("seguir.entradilla")}
      />

      <p className="sr-only" role="status">
        {dicho}
      </p>

      {filas.length === 0 ? (
        <Vacio
          titulo={t("seguir.nadaSeguido")}
          detalle={t("seguir.nadaSeguidoPorque")}
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {filas.map((f) => (
            <li key={f.id} className="card flex items-center gap-3 p-3">
              <span className="chip-dato shrink-0">{humanizar(f.objeto_tipo)}</span>
              <span className="min-w-0 flex-1">
                {f.a ? (
                  // Sin `btn-link`: esa clase va en MAYÚSCULAS —es la de «VER
                  // TODAS», que nombra una acción—, y aquí lo que se enseña es
                  // el nombre de un cliente. «PEDRITO CONSULTORA» no es como
                  // se llama nadie.
                  <Link className="text-dato text-accent hover:underline" to={f.a}>
                    {f.nombre}
                  </Link>
                ) : (
                  // Sin nombre: o ya no existe, o su tipo no tiene ficha. Las
                  // dos cosas se dicen; ninguna se esconde quitando la fila.
                  <span className="text-dato text-ink-muted">
                    {t("seguir.yaNoEsta")}
                  </span>
                )}
              </span>
              {f.motivo === "propietario" ? (
                <span className="badge">{t("seguir.motivoPropietario")}</span>
              ) : null}
              {f.silenciado ? (
                <span className="badge badge-aviso">{t("seguir.silenciadoAqui")}</span>
              ) : null}
              <button
                type="button"
                onClick={() => void dejar(f)}
                disabled={quitando === f.id}
                className="btn-icon shrink-0 text-ink-faint hover:bg-paper-light hover:text-ink"
                aria-label={t("seguir.dejar")}
                title={t("seguir.dejar")}
              >
                <Icono nombre="notifications_off" tamano="sm" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {fallo ? (
        <div className="mt-3">
          <Fallo error={fallo} />
        </div>
      ) : null}
    </>
  );
}
