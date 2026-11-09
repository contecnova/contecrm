/**
 * `/abrir/:tipo/:id`: el enlace que llevan los avisos al chat
 * (CRM-06.01.01.03).
 *
 * El servidor sabe el objeto y su identificador, pero no en qué módulo se
 * enseña: eso es del front. Aquí se resuelve con la misma tabla que usa el
 * resto de la aplicación y se va a la ficha.
 */
import { useTranslation } from "react-i18next";
import { Navigate, useParams } from "react-router-dom";

import { Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { moduloDeObjeto } from "@/lib/modulos";

export function AbrirRegistro() {
  const { t } = useTranslation();
  const { tipo = "", id = "" } = useParams();
  const modulo = moduloDeObjeto(tipo);
  if (modulo && id) {
    return <Navigate replace to={`/m/${modulo}/${tipo}/${id}`} />;
  }
  // Un enlace a un objeto que ninguna pantalla enseña: se dice, con su
  // cabecera, en vez de dejar una página en blanco.
  return (
    <>
      <CabeceraPagina
        titulo={t("abrirRegistro.titulo")}
        entradilla={t("abrirRegistro.entradilla")}
      />
      <Vacio titulo={t("abrirRegistro.sinModulo", { tipo })} />
    </>
  );
}
