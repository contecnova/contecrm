/**
 * Editar y borrar un registro, igual en todas las pantallas que lo enseñan.
 *
 * Vivía dentro de `Ficha.tsx`, la ficha genérica. El efecto es el que tiene
 * siempre que una capacidad vive dentro de una pantalla en vez de en una
 * pieza: **las pantallas a medida se quedaron sin ella**. Un cliente abierto
 * desde `/m/cuentas/cuenta/{id}` —que es la ficha de cliente de verdad, la que
 * se usa— no tenía forma de cambiar un teléfono, un sector ni un responsable,
 * aunque el servidor admitiera el `PATCH` y la propia pantalla enseñara, al
 * lado, que faltaban cuatro campos por rellenar.
 *
 * Qué campos se pueden tocar **lo dice el contrato**, no una lista escrita
 * aquí: son los del `PATCH`, que no son los del alta —hay cosas que se fijan al
 * crear y no se cambian después— y ofrecer los que el servidor rechaza es
 * prometer una edición que acaba en 422.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useInRouterContext, useLocation, useNavigate } from "react-router-dom";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { Formulario } from "@/componentes/Formulario";
import {
  camposDe,
  contratoDe,
  fichaDe,
  type CampoEsquema,
} from "@/lib/contrato";
import { llamar } from "@/lib/api";
import type { Recurso } from "@/lib/modulos";
import { moduloDe } from "@/lib/modulos";
import { recursoDe } from "@/lib/recursos";
import { comoRotulo } from "@/lib/formato";
import { usePuedeOperar, useSuperficie } from "@/lib/permisos";
import { operacionDe } from "@/lib/superficie";
import {
  MenuDeAcciones,
  type OpcionDeMenu,
} from "@/componentes/MenuDeAcciones";

/**
 * Qué se puede hacer con este registro, según el contrato y el permiso.
 *
 * Las dos cosas y no solo el permiso: tener `cuenta:write` no significa que el
 * objeto admita `PATCH`, y ofrecer un botón de editar donde el servidor no
 * tiene esa operación es prometer algo que acaba en 405.
 */
export function useEdicion(recurso: Recurso | undefined, id: string) {
  const puedeOperar = usePuedeOperar();
  const { superficie } = useSuperficie();
  const ruta = recurso ? `${recurso.listar}/${id}` : "";
  const puedeBorrar =
    Boolean(ruta) &&
    !recurso?.borrado_oculto_porque &&
    puedeOperar("DELETE", ruta);
  return {
    ruta,
    puedeEditar: Boolean(ruta) && puedeOperar("PATCH", ruta),
    puedeBorrar,
    // **Lo que hace el DELETE, dicho como lo dice el contrato.** De 124
    // operaciones DELETE, muchas no borran: «Enviar una cuenta a la papelera»,
    // «Revocar una clave», «Cerrar una sesión», «Dar de baja a un usuario». Con
    // «Eliminar» para todas, quien da de baja a alguien cree que lo está
    // borrando, y quien manda una cuenta a la papelera no sabe que se recupera.
    borrado: puedeBorrar
      ? comoRotulo(operacionDe(superficie, "DELETE", ruta)?.resumen)
      : "",
  };
}

/**
 * Los botones de un registro: editar delante, borrar dentro del menú.
 *
 * **Borrar no puede ser el segundo botón.** Medido en el navegador sobre ocho
 * fichas —cuentas, oportunidades, casos, conocimiento, campo, proveedores,
 * segmentos y campañas—: en las ocho «Eliminar» salía en la posición 2, en
 * rojo, delante de cualquier acción útil. Es la única de la barra que no se
 * deshace y estaba en el sitio más fácil de pulsar sin querer.
 *
 * Ahora baja al menú, al final y separada por una raya. Sigue estando a un
 * clic de donde estaba: lo que cambia es que hay que ir a buscarla.
 *
 * `extra` son las acciones del contrato, que las decide quien pinta la barra.
 */
type PropsDeBotones = {
  puedeEditar: boolean;
  puedeBorrar: boolean;
  /** Lo que hace el DELETE de este registro, de `useEdicion`. */
  borrado?: string;
  alEditar: () => void;
  alBorrar: () => void;
  extra?: OpcionDeMenu[];
};

export function BotonesDeRegistro(props: PropsDeBotones) {
  // Fuera de un router —una prueba que pinta sólo los botones— no hay ficha
  // de la que duplicar, y `useLocation` no se puede llamar. Se decide qué
  // componente pintar, no qué hooks llamar.
  return useInRouterContext() ? (
    <BotonesEnLaFicha {...props} />
  ) : (
    <Botones {...props} duplicar={[]} />
  );
}

function BotonesEnLaFicha(props: PropsDeBotones) {
  return <Botones {...props} duplicar={useDuplicar()} />;
}

function Botones({
  puedeEditar,
  puedeBorrar,
  borrado = "",
  alEditar,
  alBorrar,
  extra = [],
  duplicar,
}: PropsDeBotones & { duplicar: OpcionDeMenu[] }) {
  const { t } = useTranslation();
  const opciones: OpcionDeMenu[] = [
    ...extra,
    ...duplicar,
    ...(puedeBorrar
      ? [
          {
            clave: "__borrar",
            nombre: borrado || t("ficha.eliminar"),
            alElegir: alBorrar,
            destructiva: true,
          },
        ]
      : []),
  ];
  if (!puedeEditar && opciones.length === 0) return null;
  return (
    <MenuDeAcciones opciones={opciones} etiqueta={t("acciones.titulo")}>
      {puedeEditar ? (
        <button type="button" onClick={alEditar} className="btn-secondary">
          {t("ficha.editar")}
        </button>
      ) : null}
    </MenuDeAcciones>
  );
}

/**
 * «Duplicar» en cualquier ficha (CRM-07.01.01.07), sin que cada pantalla lo
 * tenga que pedir.
 *
 * Abre el alta del listado con los valores de este registro
 * (`?duplicar=<id>`): lo que se copia lo decide el contrato del alta, y pasa
 * por todo lo que pasa un alta —la deduplicación incluida, que con una copia
 * casi siempre salta y ofrece «Es otro, crearlo igual»—.
 *
 * Sale de la dirección de la ficha (`/m/<módulo>/<tipo>/<id>`) porque es lo
 * único que todas las fichas comparten: hay doce pantallas de registro
 * escritas a mano, y pedirles a todas que pasen el recurso es cómo se queda
 * alguna sin el botón. **No se ofrece** cuando el servidor tiene su propio
 * duplicar —la oportunidad, que copia también sus líneas—, que ya sale entre
 * las acciones: dos «Duplicar» que hacen cosas distintas no se sabe cuál
 * pulsar. Ni cuando el alta va por clave: la copia chocaría con el original.
 */
function useDuplicar(): OpcionDeMenu[] {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const navegar = useNavigate();
  const puedeOperar = usePuedeOperar();
  const { superficie } = useSuperficie();
  const partes = /^\/m\/([^/]+)\/([^/]+)\/([^/]+)$/.exec(pathname);
  if (!partes || !superficie) return [];
  const [, rutaModulo = "", tipo = "", id = ""] = partes;
  const modulo = moduloDe(rutaModulo);
  const recurso = modulo ? recursoDe(modulo, tipo) : undefined;
  if (!recurso || recurso.crear?.includes("{")) return [];
  const listar = recurso.listar.split("?")[0] ?? "";
  if (operacionDe(superficie, "POST", `${listar}/${id}/duplicar`)) return [];
  if (!puedeOperar("POST", recurso.crear ?? listar)) return [];
  return [
    {
      clave: "__duplicar",
      nombre: t("ficha.duplicar"),
      alElegir: () =>
        navegar(
          `/m/${rutaModulo}?r=${encodeURIComponent(recurso.nombre)}&duplicar=${encodeURIComponent(id)}`,
        ),
    },
  ];
}

export function ConfirmarBorrado({
  enviando,
  borrado = "",
  alBorrar,
  alCancelar,
}: {
  enviando: boolean;
  /** Lo que hace el DELETE de este registro, de `useEdicion`. */
  borrado?: string;
  alBorrar: () => void;
  alCancelar: () => void;
}) {
  const { t } = useTranslation();
  return (
    // Se pregunta antes de borrar, y se dice qué se borra. Un borrado sin
    // confirmación es un borrado que alguien hará sin querer.
    <div
      className="card mb-3 border-danger/40 p-4"
      role="alertdialog"
      aria-label={borrado || t("ficha.eliminar")}
    >
      <p className="text-titulin text-ink">
        {borrado
          ? t("ficha.confirmarOperacion", { accion: borrado })
          : t("ficha.confirmarBorrado")}
      </p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={alBorrar}
          disabled={enviando}
          className="btn-danger"
        >
          {borrado || t("ficha.eliminarDeVerdad")}
        </button>
        <button type="button" onClick={alCancelar} className="btn-secondary">
          {t("modulo.cancelar")}
        </button>
      </div>
    </div>
  );
}

export function FormularioDeEdicion({
  recurso,
  ruta,
  plantilla: plantillaDada,
  metodo = "PATCH",
  valores,
  alGuardar,
  alCancelar,
}: {
  recurso: Recurso;
  ruta: string;
  /**
   * La operación de editar, cuando no sale de la ficha. Una fila sin ficha
   * —sin `GET /{id}`— se edita igual, pero su plantilla no la encuentra
   * `fichaDe`, que busca algo que se lee.
   */
  plantilla?: string;
  /** `PUT` en las que se escriben enteras por clave: ajustes, riesgos, controles. */
  metodo?: "PATCH" | "PUT";
  valores: Record<string, unknown>;
  /** Se llama con el registro ya guardado, para que la pantalla se refresque. */
  alGuardar: () => void;
  alCancelar: () => void;
}) {
  const { t } = useTranslation();
  const [campos, setCampos] = useState<CampoEsquema[] | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    let vivo = true;
    void contratoDe(recurso.servicio).then((documento) => {
      // La ruta se le pide al contrato en vez de componerla: cada servicio
      // nombra el parámetro por su objeto —`{oportunidad_id}`— y buscando
      // `/{id}` no aparecía la operación, así que el formulario de edición
      // salía sin ningún campo y no había nada que guardar.
      const plantilla = plantillaDada ?? fichaDe(documento, recurso.listar);
      if (vivo)
        setCampos(plantilla ? camposDe(documento, plantilla, metodo) : []);
    });
    return () => {
      vivo = false;
    };
  }, [recurso, plantillaDada, metodo]);

  async function guardar(nuevos: Record<string, unknown>) {
    setEnviando(true);
    try {
      await llamar(ruta, { metodo, cuerpo: nuevos });
      setFallo(null);
      alGuardar();
    } catch (error) {
      setFallo(error);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="card mb-3 p-4">
      {fallo ? (
        <div className="mb-3">
          <Fallo error={fallo} />
        </div>
      ) : null}
      {campos ? (
        campos.length ? (
          <Formulario
            fallo={fallo}
            recurso={recurso}
            campos={campos}
            valores={valores}
            enviando={enviando}
            textoEnviar={t("ficha.guardar")}
            alEnviar={(v) => void guardar(v)}
          />
        ) : (
          // El contrato no declara ningún campo modificable. Se dice, en vez de
          // enseñar un formulario vacío con un botón de guardar que no guarda
          // nada: quien lo pulsara creería que ha cambiado algo.
          <p className="text-dato text-ink-muted">
            {t("ficha.sinCamposEditables")}
          </p>
        )
      ) : (
        <Cargando />
      )}
      <button type="button" onClick={alCancelar} className="btn-link mt-3">
        {t("modulo.cancelar")}
      </button>
    </div>
  );
}
