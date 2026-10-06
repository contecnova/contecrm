"""Superficie del corpus documental (RT-5).

Fábrica, como adjuntos y comentarios: cada servicio la monta declarando de qué
objetos suyos se pueden enlazar documentos. Así la misma superficie vale para
cuentas, oportunidades y casos sin copiarla, y un servicio no puede enlazar
documentos a objetos que no son suyos.

**Lo que sale del CRM y lo que sale del gestor**, que conviene no confundir:

  * La **lista** de documentos de un registro sale del CRM, sin llamar a nadie:
    una ficha que depende de un servicio externo para pintar una lista tarda lo
    que tarde ese servicio.
  * El **estado real** —versión publicada, si está obsoleto— y la **búsqueda**
    salen del gestor, con la identidad del usuario. Cachear un «aprobado» sería
    enseñar una versión vigente que ya no lo es, y alguien firmaría por ella.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status
from pydantic import BaseModel, Field

import crmcore.documental.trabajos_analisis  # noqa: F401 — registra el ejecutor
from crmcore.errors import ErrorValidacion
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso

# El `import` de arriba no es decorativo: el ejecutor del análisis se registra al
# importar su módulo, y hacerlo DENTRO de la ruta lo dejaría registrado solo en
# el proceso web. El worker, que es quien lo ejecuta, no lo tendría — y `encolar`
# rechazaría el tipo o, peor, el trabajo quedaría encolado para siempre sin nadie
# que lo coja. Es el mismo error que ya se pagó con otros ejecutores.


class AnalisisDeRamaIn(BaseModel):
    """Qué ramas analizar y qué se le pide a cada una."""

    carpetas: list[str] = Field(
        ..., min_length=1, description="Identificadores de carpeta en el gestor documental"
    )
    que: str = Field(
        "resumen",
        pattern="^(resumen|conceptos)$",
        description="«resumen» de la rama, o los «conceptos» que aparecen en ella",
    )
    pregunta: str = Field(
        "",
        max_length=500,
        description="Para acotar el resumen a algo concreto. Vacío, resume la rama entera",
    )
    con_subcarpetas: bool = True


class EnlaceEntrada(BaseModel):
    documento_id: str = Field(max_length=120, description="Identificador en el gestor documental")
    titulo: str = Field("", max_length=300)
    tipo: str = Field("", max_length=60)
    rol: str = Field(
        "",
        max_length=80,
        description=(
            "Para qué está enlazado: «contrato marco», «certificado ISO». Es del "
            "CRM y no del gestor: el mismo documento puede ser el contrato de "
            "una cuenta y el anexo de otra."
        ),
    )
    sistema: str = Field("contecmind", max_length=60)
    etiqueta: str = Field(
        "",
        max_length=200,
        description=(
            "Nombre legible del registro. Si viene, el documento se **coloca en "
            "la carpeta de este registro** en el gestor y el enlace guarda a "
            "cuál. Sin etiqueta el documento se enlaza donde esté"
        ),
    )


class PedirAprobacion(BaseModel):
    aprobadores: list[str] = Field(
        default_factory=list,
        description=(
            "Quién tiene que aprobarlo, por su identificador en el gestor — el "
            "que devuelve el canje. Se eligen al PEDIR la aprobación y no al "
            "configurar el flujo: quién firma un contrato depende del contrato"
        ),
    )
    flujo_id: str = Field("", description="Vacío = el que corresponda por configuración")
    version: int | None = Field(None, description="Vacío = la versión vigente")


class DecidirAprobacion(BaseModel):
    decision: str = Field(..., description="approved · rejected · delegated")
    comentario: str = Field("", max_length=2000)
    delegar_en: str = Field(
        "", description="Solo con `delegated`: a quién, por su identificador en el gestor"
    )


class OrganizacionEntrada(BaseModel):
    organizacion: str = Field(
        min_length=1,
        max_length=120,
        description="Identificador de la organización de este tenant en el gestor",
    )


def crear_router_documental(objetos: set[str]) -> APIRouter:
    """Monta el corpus documental para los objetos que el servicio posee."""
    router = APIRouter(prefix="/documentos", tags=["corpus documental"])

    def _validar(objeto_tipo: str) -> None:
        if objeto_tipo not in objetos:
            raise ErrorValidacion(
                f"Este servicio no enlaza documentos de «{objeto_tipo}»",
                error_code="documental.objeto_no_admitido",
                detalle={"admitidos": sorted(objetos)},
            )

    @router.get(
        "/estado",
        summary="Si hay corpus documental en este despliegue",
        description=(
            "Dice también **qué sigue funcionando sin él**: los adjuntos de los "
            "registros son otra cosa y no dependen del gestor. Sin esa línea, un "
            "estado que dice «no alcanzable» hace pensar que no se puede "
            "adjuntar nada, y sí se puede."
        ),
    )
    def estado_documental(_: AutenticadoDep) -> Any:
        from crmcore.documental import cliente

        return cliente.estado()

    # Todo lo de aprobación va ANTES de `/{objeto_tipo}/{objeto_id}`, y no es
    # cosmético: tiene los mismos dos tramos, FastAPI casa por orden de
    # declaración y la de parámetros se lo tragaba. El síntoma era un 422
    # diciendo que «aprobaciones» no es un tipo de objeto admitido, que no
    # menciona el problema por ninguna parte.
    #
    # Ojo con `/aprobacion/{documento_id}`: también quedaba tapada, y ahí no
    # basta con mirar las rutas FIJAS. Una ruta con parámetro puede tapar a
    # otra con parámetro cuando la de delante es más general —`{objeto_tipo}`
    # se traga el literal «aprobacion»—, y eso no se ve leyendo el fichero.
    @router.get(
        "/aprobaciones/pendientes",
        summary="Lo que espera MI decisión",
        description=(
            "Los avisos por correo los manda el CRM y no el gestor, y no es un "
            "reparto caprichoso: el gestor **no conoce el correo** de una persona "
            "del CRM —no tiene ficha suya, por diseño— así que el único que puede "
            "avisar es quien sabe a quién."
        ),
    )
    def aprobaciones_pendientes(db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.documental import cliente

        return {
            "items": cliente.aprobaciones_pendientes(
                token_usuario=_token_del_usuario(db, principal)
            )
        }

    @router.get(
        "/aprobaciones/flujos",
        summary="Los flujos de aprobación entre los que elegir",
    )
    def flujos_de_aprobacion(db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.documental import cliente

        return {
            "items": cliente.flujos_de_aprobacion(token_usuario=_token_del_usuario(db, principal))
        }

    @router.get(
        "/ficha/{documento_id}",
        summary="El estado real de un documento del corpus",
        description=(
            "Lo que el enlace del CRM **no** sabe: si está indexado, si se indexó "
            "con avisos, de qué tipo es y cuánto ocupa. Se pregunta al abrirlo y "
            "no se copia en el enlace: un «aprobado» caducado en una pantalla del "
            "CRM es peor que no enseñar el estado, porque alguien firmará algo "
            "creyendo que la versión vigente es otra.\n\n"
            "**No devuelve el texto extraído.** El gestor lo trae en esta misma "
            "respuesta y puede ser un contrato entero: pasarlo por aquí convierte "
            "una consulta de estado en una descarga, y el CRM no tiene nada que "
            "hacer con él — quien quiera el contenido va al gestor."
        ),
    )
    def ficha_de_documento(documento_id: str, db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.documental import cliente

        ficha = cliente.ficha(documento_id, token_usuario=_token_del_usuario(db, principal))
        return {k: v for k, v in ficha.items() if k != "extracted_text"}

    # ── Aprobación de un documento ───────────────────────────────────────
    #
    # El motor vive en el gestor —quórum, segregación de funciones, recorrido
    # del grafo— y aquí solo se pasa. Lo que sí es del CRM es QUIÉN aprueba:
    # los aprobadores son personas de aquí, elegidas al pedir la aprobación.

    @router.get(
        "/aprobacion/{documento_id}",
        summary="Cómo va la aprobación de un documento",
        description=(
            "Trae también **si quien pregunta puede pedirla**. Ese cálculo no se "
            "hace aquí: haría falta copiar el quórum, la segregación de funciones "
            "y el recorrido del grafo, y esa copia se desincroniza el día que "
            "cambie una regla — enseñando un botón que da 403."
        ),
    )
    def ver_aprobacion(documento_id: str, db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.documental import cliente

        return cliente.aprobacion_de(documento_id, token_usuario=_token_del_usuario(db, principal))

    @router.post(
        "/aprobacion/{documento_id}",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(exige_permiso("documento:enlazar"))],
        summary="Pedir la aprobación de un documento",
        description=(
            "Los aprobadores se eligen **al pedirla**, no al configurar el flujo: "
            "quién tiene que firmar un contrato depende del contrato, no del tipo "
            "de documento.\n\n"
            "Si el flujo elegido exige aprobadores y no se dan, el gestor "
            "contesta 422. Por eso el listado de flujos dice cuáles los exigen: "
            "la pantalla los pide **antes** de dejar enviar, en vez de dejar que "
            "alguien rellene el formulario y se coma el error."
        ),
    )
    def pedir_aprobacion(
        documento_id: str,
        db: DbDep,
        principal: AutenticadoDep,
        datos: PedirAprobacion = Body(...),
    ) -> Any:
        from crmcore.documental import cliente

        return cliente.pedir_aprobacion(
            documento_id,
            token_usuario=_token_del_usuario(db, principal),
            aprobadores=datos.aprobadores,
            flujo_id=datos.flujo_id,
            version=datos.version,
        )

    @router.get(
        "/{objeto_tipo}/{objeto_id}",
        summary="Documentos enlazados a un registro",
        description=(
            "Sale del CRM, **sin llamar al gestor**: una ficha que depende de un "
            "servicio externo para pintar una lista tarda lo que tarde ese "
            "servicio. El estado real se pide al abrir el documento."
        ),
    )
    def listar(objeto_tipo: str, objeto_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
        from crmcore.documental import documentos_de

        _validar(objeto_tipo)
        return documentos_de(db, objeto_tipo=objeto_tipo, objeto_id=objeto_id)

    @router.post(
        "/{objeto_tipo}/{objeto_id}",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(exige_permiso("documento:enlazar"))],
        summary="Enlazar un documento del corpus con un registro",
        description=(
            "Guarda **el enlace y el contexto**, nunca una copia del documento: "
            "duplicarlo crearía dos verdades que divergen en cuanto alguien "
            "publique una versión nueva allí, y la del CRM sería la vieja sin "
            "decirlo."
        ),
    )
    def crear_enlace(
        objeto_tipo: str,
        objeto_id: UUID,
        uow: UowDep,
        principal: AutenticadoDep,
        datos: EnlaceEntrada = Body(...),
    ) -> Any:
        from crmcore.documental import enlazar

        _validar(objeto_tipo)
        campos = datos.model_dump()
        etiqueta = str(campos.pop("etiqueta", "") or "")

        # Colocar el documento en la carpeta del registro se hace AQUÍ y no en
        # el navegador: son dos llamadas al gestor —resolver la carpeta y mover
        # el documento— y hacerlas desde el front dejaría el enlace creado y el
        # documento sin colocar en cuanto una de las dos fallara a medias.
        carpeta_id = ""
        if etiqueta:
            carpeta_id = _colocar_en_la_carpeta(
                uow.db,
                principal,
                objeto_tipo=objeto_tipo,
                etiqueta=etiqueta,
                documento_id=campos["documento_id"],
            )

        enlace = enlazar(
            uow.db,
            tenant_id=principal.tenant_id,
            objeto_tipo=objeto_tipo,
            objeto_id=objeto_id,
            por=principal.id,
            carpeta_id=carpeta_id,
            **campos,
        )
        return {
            "id": str(enlace.id),
            "documento_id": enlace.documento_id,
            "carpeta_id": enlace.carpeta_id,
        }

    @router.delete(
        "/{objeto_tipo}/{objeto_id}/{enlace_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(exige_permiso("documento:desenlazar"))],
        summary="Quitar el enlace (no borra el documento)",
        description=(
            "El CRM no es dueño del documento. Borrarlo allí desde aquí sería que "
            "un usuario del CRM destruyera el contrato que otro departamento "
            "guardó, sin pasar por las reglas de ese gestor.\n\n"
            "Un **bloqueo legal** sobre el registro impide quitar el enlace: un "
            "bloqueo que permite desenlazar la prueba y luego decir «aquí no "
            "consta» no es un bloqueo."
        ),
    )
    def borrar_enlace(objeto_tipo: str, objeto_id: UUID, enlace_id: UUID, uow: UowDep) -> None:
        from crmcore.documental import quitar_enlace

        _validar(objeto_tipo)
        quitar_enlace(uow.db, enlace_id, objeto_id=objeto_id)

    @router.get(
        "/buscar",
        summary="Buscar en el corpus, con la identidad de quien pregunta",
        description=(
            "La búsqueda la resuelve el gestor **con un token del usuario**, no "
            "con la credencial de la aplicación: así aplica sus propios permisos "
            "y cada uno ve lo que vería entrando al gestor. Buscar con la "
            "credencial le enseñaría el corpus entero del tenant."
        ),
    )
    def buscar_corpus(
        db: DbDep,
        principal: AutenticadoDep,
        q: str = Query(..., min_length=1, max_length=300),
        limite: int = Query(20, ge=1, le=100),
    ) -> Any:
        from crmcore.documental import cliente, organizacion_de

        organizacion = organizacion_de(db, principal.tenant_id)
        token = cliente.canjear_token(
            organizacion=organizacion,
            sujeto=str(principal.id),
            rol=cliente.rol_para(principal.permisos, principal.es_admin_plataforma),
        )
        return {"resultados": cliente.buscar(q, token_usuario=token.token, limite=limite)}

    @router.post(
        "/analisis-de-rama",
        # Escribe —encola un trabajo que consume modelo— y por eso pide permiso.
        # El gate de arquitectura lo cazó: una ruta de escritura sin permiso es
        # la que cualquiera con sesión puede disparar, y aquí cada disparo son
        # minutos de GPU del cliente.
        dependencies=[Depends(exige_permiso("documento:leer"))],
        summary="Pedir el resumen (o los conceptos) de una rama del corpus",
        description=(
            "**Se encola y devuelve la ficha del trabajo**, no el resumen. Pasa "
            "por el modelo de lenguaje, y el de embeddings puede tardar minutos "
            "en cargar en frío: hacerlo dentro de la petición da un 504 con el "
            "trabajo hecho y tirado — y encima funcionaría en pruebas, con el "
            "modelo caliente, para fallar el lunes por la mañana.\n\n"
            "El resultado trae las **citas agrupadas por documento**. Las del "
            "gestor son de fragmento, y varias salen del mismo fichero: pintarlas "
            "tal cual da una lista con el mismo documento cuatro veces, que "
            "parece un fallo y no lo es. Las huérfanas —cuyo documento ya no "
            "está— se marcan y no se esconden: un resumen apoyado en algo que ha "
            "desaparecido es información, no ruido.\n\n"
            "Lo resuelve el gestor **con un token del usuario**, así que cada uno "
            "analiza lo que vería entrando al gestor."
        ),
    )
    def analizar_rama_documental(
        cuerpo: AnalisisDeRamaIn, uow: UowDep, principal: AutenticadoDep
    ) -> Any:
        from crmcore.documental import cliente, organizacion_de
        from crmcore.documental.trabajos_analisis import encolar_analisis

        organizacion = organizacion_de(uow.db, principal.tenant_id)
        token = cliente.canjear_token(
            organizacion=organizacion,
            sujeto=str(principal.id),
            rol=cliente.rol_para(principal.permisos, principal.es_admin_plataforma),
        )
        trabajo = encolar_analisis(
            uow.db,
            tenant_id=principal.tenant_id,
            carpetas=cuerpo.carpetas,
            token_usuario=token.token,
            que=cuerpo.que,
            pregunta=cuerpo.pregunta,
            con_subcarpetas=cuerpo.con_subcarpetas,
            pedido_por=principal.id,
        )
        return {
            "trabajo_id": str(trabajo.id),
            "estado": trabajo.estado,
            "ramas": len(cuerpo.carpetas),
            "donde_se_mira": "GET /api/v1/trabajos/{trabajo_id}",
        }

    @router.get(
        "/organizacion",
        summary="A qué organización del gestor se mapea este tenant",
        description=(
            "Sin mapeo no se llama al gestor, así que esto es lo primero que hay "
            "que mirar cuando el corpus «no aparece» en un tenant concreto."
        ),
    )
    def ver_organizacion(db: DbDep, principal: AutenticadoDep) -> Any:
        from sqlalchemy import select

        from crmcore.documental.enlaces import OrganizacionDocumental

        fila = db.execute(
            select(OrganizacionDocumental).where(
                OrganizacionDocumental.tenant_id == principal.tenant_id
            )
        ).scalar_one_or_none()
        if fila is None:
            return {"mapeada": False, "organizacion": "", "estado": "sin_mapear"}
        return {
            "mapeada": True,
            "organizacion": fila.organizacion,
            "estado": fila.estado,
            "ultimo_error": fila.ultimo_error,
        }

    @router.put(
        "/organizacion",
        dependencies=[Depends(exige_permiso("documento:admin"))],
        summary="Mapear este tenant a una organización del gestor",
        description=(
            "Se declara, no se deriva del identificador del tenant: derivarlo "
            "convertiría el aislamiento entre clientes en una convención, y una "
            "convención no para a nadie."
        ),
    )
    def fijar_organizacion(
        datos: OrganizacionEntrada, uow: UowDep, principal: AutenticadoDep
    ) -> Any:
        from crmcore.documental import mapear_organizacion

        fila = mapear_organizacion(
            uow.db, tenant_id=principal.tenant_id, organizacion=datos.organizacion
        )
        return {"mapeada": True, "organizacion": fila.organizacion, "estado": fila.estado}

    # ── El árbol de carpetas ─────────────────────────────────────────────
    #
    # Todo lo de aquí llama al gestor con un token del USUARIO. Es lo mismo que
    # en la búsqueda y por lo mismo, pero aquí se nota más: el árbol que ve
    # alguien es el que vería entrando al gestor, con sus huecos. Una carpeta que
    # no puede leer no aparece — ni ella ni lo que cuelga — y eso no es una lista
    # incompleta, es el filtro haciendo su trabajo.

    def _token_del_usuario(db: Any, principal: Any) -> str:
        from crmcore.documental import cliente, organizacion_de

        organizacion = organizacion_de(db, principal.tenant_id)
        return cliente.canjear_token(
            organizacion=organizacion,
            sujeto=str(principal.id),
            rol=cliente.rol_para(principal.permisos, principal.es_admin_plataforma),
        ).token

    @router.get(
        "/carpetas",
        summary="Las carpetas del corpus que este usuario puede ver",
        description=(
            "Con la identidad de quien pregunta, así que **el árbol puede tener "
            "huecos**: una carpeta denegada no aparece, ni ella ni lo que cuelga "
            "de ella. No es paginación ni un fallo — es el permiso.\n\n"
            "Sin `padre` devuelve la raíz del área configurada."
        ),
    )
    def listar_carpetas(
        db: DbDep,
        principal: AutenticadoDep,
        padre: str = Query("", max_length=120, description="Carpeta de la que colgar"),
    ) -> Any:
        from crmcore.documental import cliente

        return {
            "items": cliente.carpetas(
                token_usuario=_token_del_usuario(db, principal), padre_id=padre or None
            )
        }

    @router.get(
        "/carpetas/{carpeta_id}/documentos",
        summary="Los documentos de una carpeta",
        description=(
            "Ya viene filtrado por los permisos del usuario, así que **no hace "
            "falta preguntar permisos por fila** para pintarlo. Una rama sin "
            "documentos visibles devuelve cero resultados y no un error: "
            "distinguir «vacía» de «todo denegado» con un código propio ya sería "
            "decirle a quien pregunta que ahí hay algo que no puede ver."
        ),
    )
    def documentos_de_carpeta(
        carpeta_id: str,
        db: DbDep,
        principal: AutenticadoDep,
        con_subcarpetas: bool = Query(False),
    ) -> Any:
        from crmcore.documental import cliente

        return {
            "items": cliente.documentos_de_carpeta(
                carpeta_id,
                token_usuario=_token_del_usuario(db, principal),
                con_subcarpetas=con_subcarpetas,
            )
        }

    @router.get(
        "/carpetas/{carpeta_id}/permisos",
        summary="Por qué este usuario puede o no puede hacer algo con la carpeta",
        description=(
            "**Para la ficha de una carpeta, no para pintar un listado.** El "
            "listado de documentos ya viene filtrado, así que preguntarlo por "
            "fila sería pedir dos veces lo mismo y convertir una pantalla de "
            "cincuenta filas en cincuenta llamadas de red.\n\n"
            "El motivo es un **código** (`area`, `grant_here`, `grant_above`, "
            "`doc_allow`, `doc_deny`, `no_area`), no una frase: el gestor no "
            "traduce, y una frase suya llegaría en castellano a los demás "
            "idiomas. Lo traduce el front."
        ),
    )
    def permisos_de_carpeta(carpeta_id: str, db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.documental import cliente

        return {
            "permisos": cliente.permisos_de_carpeta(
                carpeta_id, token_usuario=_token_del_usuario(db, principal)
            ),
            "motivos_conocidos": list(cliente.MOTIVOS_DE_PERMISO),
        }

    @router.get(
        "/{objeto_tipo}/{objeto_id}/carpeta",
        summary="La carpeta del corpus donde van los documentos de este registro",
        description=(
            "Se resuelve recorriendo la plantilla configurada "
            "(`DMS_CARPETA_PLANTILLA`) y se **crea si no existe**, salvo que se "
            "pida solo mirar. El identificador se guarda en cada enlace: si "
            "luego alguien mueve o renombra la carpeta en el gestor, el CRM "
            "sigue apuntando a la misma y no crea otra al lado.\n\n"
            "El nombre a enseñar se pide al gestor y no se copia aquí: una ruta "
            "guardada enseñaría «Clientes / ACME» un mes después de que la "
            "renombraran, y nadie lo notaría."
        ),
    )
    def carpeta_del_registro(
        objeto_tipo: str,
        objeto_id: UUID,
        db: DbDep,
        principal: AutenticadoDep,
        etiqueta: str = Query(
            ...,
            min_length=1,
            max_length=200,
            description="Nombre legible del registro: es lo que da nombre a su carpeta",
        ),
        crear: bool = Query(True, description="Crearla si no existe"),
    ) -> Any:
        from crmcore.documental import cliente

        _validar(objeto_tipo)
        carpeta_id = cliente.carpeta_de_registro(
            objeto=objeto_tipo,
            etiqueta=etiqueta,
            token_usuario=_token_del_usuario(db, principal),
            crear=crear,
        )
        return {"carpeta_id": carpeta_id or "", "existe": bool(carpeta_id)}

    @router.get(
        "/buscar-en-rama",
        summary="Buscar dentro de una rama del corpus",
        description=(
            "La misma búsqueda, acotada. Existe aparte de `/buscar` porque "
            "«buscar en los documentos de esta cuenta» y «buscar en el corpus» "
            "son dos preguntas distintas, y una pantalla tiene que poder decir "
            "cuál está haciendo."
        ),
    )
    def buscar_en_rama(
        db: DbDep,
        principal: AutenticadoDep,
        q: str = Query(..., min_length=1, max_length=300),
        carpeta: str = Query("", max_length=120),
        con_subcarpetas: bool = Query(True),
        limite: int = Query(20, ge=1, le=100),
    ) -> Any:
        from crmcore.documental import cliente

        return {
            "resultados": cliente.buscar_en_rama(
                q,
                token_usuario=_token_del_usuario(db, principal),
                carpeta_id=carpeta or None,
                con_subcarpetas=con_subcarpetas,
                limite=limite,
            )
        }

    @router.post(
        "/aprobaciones/{solicitud_id}/decidir",
        dependencies=[Depends(exige_permiso("documento:enlazar"))],
        summary="Aprobar, rechazar o delegar",
        description=(
            "**Aprobar no siempre acaba en «publicado».** Si el reindexado del "
            "fichero falla, la versión queda aprobada, sigue publicada la anterior "
            "y la publicación se puede reintentar. Es correcto: una pantalla que "
            "espere «publicado» pintaría como roto algo que funciona."
        ),
    )
    def decidir_aprobacion(
        solicitud_id: str,
        db: DbDep,
        principal: AutenticadoDep,
        datos: DecidirAprobacion = Body(...),
    ) -> Any:
        from crmcore.documental import cliente

        return cliente.decidir_aprobacion(
            solicitud_id,
            token_usuario=_token_del_usuario(db, principal),
            decision=datos.decision,
            comentario=datos.comentario,
            delegar_en=datos.delegar_en,
        )

    @router.post(
        "/aprobaciones/{solicitud_id}/cancelar",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(exige_permiso("documento:enlazar"))],
        summary="Cancelar una solicitud de aprobación",
    )
    def cancelar_aprobacion(solicitud_id: str, db: DbDep, principal: AutenticadoDep) -> None:
        from crmcore.documental import cliente

        cliente.cancelar_aprobacion(solicitud_id, token_usuario=_token_del_usuario(db, principal))

    return router


def _colocar_en_la_carpeta(
    db: Any,
    principal: Any,
    *,
    objeto_tipo: str,
    etiqueta: str,
    documento_id: str,
) -> str:
    """Lleva el documento a la carpeta de su registro y devuelve cuál es.

    **Un fallo aquí no impide enlazar.** El enlace es del CRM y vale por sí
    solo; colocar el documento es organización del gestor. Si el gestor está
    caído o el usuario no puede escribir en esa carpeta, se enlaza igual y se
    anota — lo contrario sería que no se pueda registrar un contrato en una
    cuenta porque el corpus está en mantenimiento.
    """
    from crmcore.documental import cliente, organizacion_de

    try:
        token = cliente.canjear_token(
            organizacion=organizacion_de(db, principal.tenant_id),
            sujeto=str(principal.id),
            rol=cliente.rol_para(principal.permisos, principal.es_admin_plataforma),
        ).token
        carpeta_id = cliente.carpeta_de_registro(
            objeto=objeto_tipo, etiqueta=etiqueta, token_usuario=token, crear=True
        )
        if not carpeta_id:
            return ""
        cliente.mover_documento(documento_id, carpeta_id=carpeta_id, token_usuario=token)
        return carpeta_id
    except Exception as exc:  # noqa: BLE001 — organizar no puede impedir enlazar
        from crmcore.logging import get_logger

        get_logger(__name__).warning(
            "documental.sin_colocar",
            objeto=objeto_tipo,
            documento=documento_id,
            error=str(exc)[:200],
        )
        return ""
