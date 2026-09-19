"""Cuentas y contactos en lote (CRM-00.02.01.11).

Aquí no hay lógica de negocio: hay **adaptadores**. Cada uno valida el elemento
con el mismo esquema Pydantic que usa el alta de una en una y llama a la misma
función de `servicio.py`.

Es deliberado hasta el punto de ser aburrido, y ese es el objetivo. Un camino
masivo que escribe directamente en la tabla —que es como se suele hacer, porque
es más rápido— se salta la detección de duplicados, la normalización del
teléfono, el recálculo de calidad, la auditoría, el índice de búsqueda y el
evento de dominio. El resultado es un maestro de clientes con diez mil fichas
que ninguna pantalla habría dejado guardar, y un buscador que no las encuentra.

El precio es que importar es más lento que un `COPY`. Se paga a sabiendas: la
importación es donde entra el 90 % del dato sucio de un CRM, y es justo donde no
conviene apagar las defensas.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion
from crmcore.http.masivo_router import RecursoMasivo, registrar_recursos
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.party import administracion as admin
from services.party import servicio as svc
from services.party.esquemas import ActualizarCuenta, CrearContacto, CrearCuenta


def _crear_cuenta(uow: UnidadDeTrabajo, elemento: dict[str, Any]) -> UUID:
    datos = CrearCuenta.model_validate(elemento)
    payload = datos.model_dump(exclude={"identificadores", "forzar"})
    cuenta = svc.crear_cuenta(
        uow,
        identificadores=[i.model_dump() for i in datos.identificadores],
        forzar=datos.forzar,
        **payload,
    )
    return cuenta.id


def _actualizar_cuenta(uow: UnidadDeTrabajo, cuenta_id: UUID, campos: dict[str, Any]) -> None:
    datos = ActualizarCuenta.model_validate(campos)
    svc.actualizar_cuenta(uow, cuenta_id, datos.model_dump(exclude_unset=True, exclude_none=True))


def _borrar_cuenta(uow: UnidadDeTrabajo, cuenta_id: UUID) -> None:
    from crmcore.authz.principal import principal_actual

    # A la papelera, como el borrado de una sola. Un borrado masivo definitivo
    # es la operación que más veces se lanza por error y la única que no tiene
    # vuelta: que el camino en lote sea más destructivo que el individual sería
    # exactamente al revés de lo razonable.
    admin.borrar_cuenta(uow.db, cuenta_id, por=principal_actual().id)


def _buscar_cuenta(db: Session, elemento: dict[str, Any]) -> UUID | None:
    """Encuentra la cuenta que un `upsert` tiene que actualizar.

    Por identificador fiscal primero y por clave canónica después, y en ese
    orden porque un NIF identifica y un nombre solo se parece. Al revés, dos
    sociedades distintas del mismo grupo con nombre casi igual se fusionarían
    sin que nadie lo pidiera.
    """
    from services.party.modelos import Cuenta, IdentificadorFiscal
    from services.party.normalizacion import clave_canonica_empresa

    if elemento.get("id"):
        return UUID(str(elemento["id"]))

    for identificador in elemento.get("identificadores") or []:
        valor = str(identificador.get("valor", "")).strip().upper()
        if not valor:
            continue
        fila = db.execute(
            select(IdentificadorFiscal.cuenta_id).where(IdentificadorFiscal.valor == valor)
        ).scalar_one_or_none()
        if fila:
            return fila

    nombre = str(elemento.get("nombre", "")).strip()
    if not nombre:
        raise ErrorValidacion(
            "Un upsert necesita «id», un identificador fiscal o al menos el nombre",
            error_code="masivo.sin_clave",
        )
    return db.execute(
        select(Cuenta.id).where(
            Cuenta.clave_canonica == clave_canonica_empresa(nombre),
            Cuenta.deleted_at.is_(None),
            Cuenta.fusionada_en_id.is_(None),
        )
    ).scalar_one_or_none()


def _crear_contacto(uow: UnidadDeTrabajo, elemento: dict[str, Any]) -> UUID:
    datos = CrearContacto.model_validate(elemento)
    payload = datos.model_dump(exclude={"cuenta_id", "rol", "forzar"})
    contacto = svc.crear_contacto(
        uow, cuenta_id=datos.cuenta_id, rol=datos.rol, forzar=datos.forzar, **payload
    )
    return contacto.id


CUENTAS = RecursoMasivo(
    recurso="cuentas",
    objeto="cuenta",
    # Los mismos permisos que las rutas de una en una, exactamente. El camino
    # masivo no puede habilitar nada que el individual no habilite: si lo
    # hiciera, «dar de alta mil cuentas» sería un permiso más fácil de conseguir
    # que «dar de alta una».
    permisos={
        "crear": "account:write",
        "actualizar": "account:write",
        "borrar": "account:delete",
    },
    crear=_crear_cuenta,
    actualizar=_actualizar_cuenta,
    borrar=_borrar_cuenta,
    buscar=_buscar_cuenta,
)

# Los contactos no ofrecen `upsert`: no hay una clave que identifique a una
# persona con la fiabilidad con la que un NIF identifica a una empresa. El
# correo se comparte (info@, el del jefe), cambia de empresa y se reutiliza. Un
# upsert por correo acabaría pisando la ficha de otra persona, y ese error no se
# ve hasta que alguien recibe la comunicación equivocada.
# Tampoco ofrece borrado, y no por olvido: **la API no tiene borrado de
# contacto de uno en uno**. `administracion.borrar_contacto` existe y se usa
# desde la baja del tenant, pero ninguna ruta lo expone. Ofrecerlo aquí daría al
# camino masivo una capacidad que el individual no tiene, que es justo lo que
# este módulo dice no hacer. Cuando exista `DELETE /contactos/{id}`, se añade.
CONTACTOS = RecursoMasivo(
    recurso="contactos",
    objeto="contacto",
    permisos={"crear": "contact:write"},
    crear=_crear_contacto,
)

RECURSOS = (CUENTAS, CONTACTOS)

# Importar este módulo registra los ejecutores. Lo hacen la API y el worker, que
# son procesos distintos y ninguno se puede fiar del otro.
registrar_recursos(RECURSOS)
