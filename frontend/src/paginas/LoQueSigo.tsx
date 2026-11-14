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
 *
 * **Dejar de seguir no se pregunta: se deshace.** Es lo contrario de un
 * borrado: no se pierde nada que no se recupere con un clic —volver a seguir
 * restaura el motivo que tenía y, al responsable, le quita el silencio; está
 * en `crmcore/datos/seguimiento.py`—, y es una lista que se poda de varias en
 * varias. Preguntar cada vez enseña a contestar «sí» sin leer, que es lo que
 * deja sin defensa a las preguntas que sí importan. Lo que sí hacía falta es
 * poder volver: la fila desaparece al dejarla, y sin ella el único camino era
 * buscar el registro y abrir su ficha.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import {
  AvisoDeRecorte,
  Cargando,
  Error as Fallo,
  Vacio,
} from "@/componentes/Estados";
import { Icono } from "@/componentes/Icono";
import { CabeceraPagina } from "@/componentes/Pagina";
import { llamar, salvoCancelacion } from "@/lib/api";
import { humanizar } from "@/lib/formato";
import { MAXIMO_POR_PAGINA } from "@/lib/listados";
import { nombresDeRegistros } from "@/lib/nombres";
import { moduloDeObjeto } from "@/lib/modulos";

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
  /** Se ha podido mirar y no estaba: el registro se ha borrado. */
  desaparecido: boolean;
}

export function LoQueSigo() {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Fila[] | null>(null);
  // Si el servidor dijo que se siguen más registros de los que caben en una
  // página: sin decirlo, lo que no cabe se lee como «ya no lo sigo».
  const [hayMas, setHayMas] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);
  const [quitando, setQuitando] = useState("");
  // Lo que se canta al dejar de seguir. Sin esto, quien no ve la pantalla
  // pulsa el botón y la fila desaparece sin que nada se lo diga.
  const [dicho, setDicho] = useState("");
  // El último que se ha dejado de seguir, para poder volver a seguirlo.
  const [dejada, setDejada] = useState<Fila | null>(null);
  const deshacer = useRef<HTMLButtonElement>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    setFallo(null);
    setFilas(null);
    (async () => {
      const { datos } = await llamar<Pagina<Seguimiento>>(
        `/api/v1/seguimientos?limite=${MAXIMO_POR_PAGINA}`,
        { signal: control.signal },
      );
      const seguidos = datos.items ?? [];
      setHayMas(Boolean(datos.siguiente));
      // Resolver los nombres es lo mismo que hace la biblioteca de archivos,
      // así que vive en un sitio: dos copias de «dime cómo se llaman estos
      // registros» acaban resolviendo distinto.
      const { nombres, preguntados } = await nombresDeRegistros(seguidos, control.signal);
      setFilas(
        seguidos.map((s) => {
          const ruta = moduloDeObjeto(s.objeto_tipo);
          const nombre = nombres.get(s.objeto_id) ?? "";
          return {
            ...s,
            nombre,
            // **«Ya no existe» sólo si se ha podido mirar.** Antes se decía
            // de todo lo que no traía nombre, y eso incluye lo que no se ha
            // podido preguntar —un tipo sin pantalla, un listado que no
            // contesta—: afirmar que el registro de alguien se ha borrado
            // cuando sigue ahí es la peor de las dos equivocaciones.
            desaparecido: !nombre && preguntados.has(s.objeto_tipo),
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
      setDicho(
        fila.nombre ? t("seguir.dejadoDe", { nombre: fila.nombre }) : t("seguir.dejado"),
      );
      setDejada(fila);
      cargar();
    } catch (error) {
      setFallo(error);
    } finally {
      setQuitando("");
    }
  }

  async function volver(fila: Fila) {
    try {
      // Con su motivo de antes: si era responsable, el servidor le quita el
      // silencio; si lo seguía a mano, vuelve a seguirlo a mano.
      await llamar("/api/v1/seguimientos", {
        metodo: "POST",
        cuerpo: {
          objeto_tipo: fila.objeto_tipo,
          objeto_id: fila.objeto_id,
          motivo: fila.motivo,
        },
      });
      setDejada(null);
      setDicho(t("seguir.vuelto"));
      cargar();
    } catch (error) {
      setFallo(error);
    }
  }

  // El foco va a «Volver a seguirlo» en cuanto aparece: la fila que tenía el
  // foco ya no está, y sin esto quien usa teclado empieza desde arriba.
  useEffect(() => {
    if (dejada && filas) deshacer.current?.focus();
  }, [dejada, filas]);

  if (fallo && !filas) return <Fallo error={fallo} reintentar={cargar} />;
  if (!filas) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("seguir.loQueSigo")}
        icono="notifications_active"
        entradilla={t("seguir.entradilla")}
      />

      <div className={dejada ? "mb-3 flex flex-wrap items-center gap-3" : undefined}>
        <p className={dejada ? "text-dato text-ink" : "sr-only"} role="status">
          {dicho}
        </p>
        {dejada ? (
          <button
            ref={deshacer}
            type="button"
            className="btn-secondary"
            onClick={() => void volver(dejada)}
          >
            <Icono nombre="notifications_active" tamano="sm" />
            {t("seguir.deshacer")}
          </button>
        ) : null}
      </div>

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
                  <span className="text-dato text-ink-muted">
                    {t(f.desaparecido ? "seguir.yaNoEsta" : "seguir.noSeHaPodidoMirar")}
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
      {filas.length > 0 && hayMas ? (
        <AvisoDeRecorte cuantas={filas.length} />
      ) : null}

      {fallo ? (
        <div className="mt-3">
          <Fallo error={fallo} />
        </div>
      ) : null}
    </>
  );
}
