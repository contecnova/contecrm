/**
 * La conversación de este registro, desde su ficha (CRM-06.02.02.02).
 *
 * Es lo que distingue el chat de contecrm de poner un enlace a una herramienta
 * de mensajería: se habla de **esta** oportunidad con el importe y la etapa a
 * la vista, y lo que se decida queda donde está el registro. Un chat aparte
 * obliga a copiar un enlace y a que quien lo recibe cambie de aplicación, y ahí
 * es donde se pierde el porqué de las decisiones.
 *
 * El botón no abre nada hasta que se pulsa: crear la conversación de cada
 * registro que alguien abra llenaría la lista de conversaciones vacías, y una
 * lista así deja de mirarse.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Icono } from "@/componentes/Icono";
import { llamar } from "@/lib/api";

export function HablarDeEsto({ objeto, objetoId }: { objeto: string; objetoId: string }) {
  const { t } = useTranslation();
  const navegar = useNavigate();
  const [abriendo, setAbriendo] = useState(false);
  const [fallo, setFallo] = useState("");

  async function abrir() {
    setAbriendo(true);
    setFallo("");
    try {
      const { datos } = await llamar<{ id: string }>(
        `/api/v1/chat/conversaciones/de/${objeto}/${objetoId}`,
      );
      navegar(`/chat?c=${datos.id}`);
    } catch {
      setFallo(t("chat.noSePudoAbrir"));
    } finally {
      setAbriendo(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => void abrir()}
        disabled={abriendo}
        className="rounded-xl border border-line px-3 py-1.5 text-xs text-ink hover:bg-paper-sunk disabled:opacity-50"
      >
        <Icono nombre="forum" /> {t("chat.hablarDeEsto")}
      </button>
      {fallo ? (
        <p className="mt-1 text-3xs text-danger" role="status">
          {fallo}
        </p>
      ) : null}
    </>
  );
}
