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

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { Formulario } from "@/componentes/Formulario";
import { camposDe, contratoDe, fichaDe, type CampoEsquema } from "@/lib/contrato";
import { llamar } from "@/lib/api";
import type { Recurso } from "@/lib/modulos";
import { usePuedeOperar } from "@/lib/permisos";
import { MenuDeAcciones, type OpcionDeMenu } from "@/componentes/MenuDeAcciones";

/**
 * Qué se puede hacer con este registro, según el contrato y el permiso.
 *
 * Las dos cosas y no solo el permiso: tener `cuenta:write` no significa que el
 * objeto admita `PATCH`, y ofrecer un botón de editar donde el servidor no
 * tiene esa operación es prometer algo que acaba en 405.
 */
export function useEdicion(recurso: Recurso | undefined, id: string) {
  const puedeOperar = usePuedeOperar();
  const ruta = recurso ? `${recurso.listar}/${id}` : "";
  return {
    ruta,
    puedeEditar: Boolean(ruta) && puedeOperar("PATCH", ruta),
    puedeBorrar: Boolean(ruta) && puedeOperar("DELETE", ruta),
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
export function BotonesDeRegistro({
  puedeEditar,
  puedeBorrar,
  alEditar,
  alBorrar,
  extra = [],
}: {
  puedeEditar: boolean;
  puedeBorrar: boolean;
  alEditar: () => void;
  alBorrar: () => void;
  extra?: OpcionDeMenu[];
}) {
  const { t } = useTranslation();
  const opciones: OpcionDeMenu[] = [
    ...extra,
    ...(puedeBorrar
      ? [
          {
            clave: "__borrar",
            nombre: t("ficha.eliminar"),
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

export function ConfirmarBorrado({
  enviando,
  alBorrar,
  alCancelar,
}: {
  enviando: boolean;
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
      aria-label={t("ficha.eliminar")}
    >
      <p className="text-xs text-ink">{t("ficha.confirmarBorrado")}</p>
      <div className="mt-3 flex gap-2">
        <button type="button" onClick={alBorrar} disabled={enviando} className="btn-danger">
          {t("ficha.eliminarDeVerdad")}
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
  valores,
  alGuardar,
  alCancelar,
}: {
  recurso: Recurso;
  ruta: string;
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
      const plantilla = fichaDe(documento, recurso.listar);
      if (vivo) setCampos(plantilla ? camposDe(documento, plantilla, "patch") : []);
    });
    return () => {
      vivo = false;
    };
  }, [recurso]);

  async function guardar(nuevos: Record<string, unknown>) {
    setEnviando(true);
    try {
      await llamar(ruta, { metodo: "PATCH", cuerpo: nuevos });
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
          <p className="text-2xs text-ink-muted">{t("ficha.sinCamposEditables")}</p>
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
