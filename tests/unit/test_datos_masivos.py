"""Papelera, importación masiva y transferencia de propiedad.

Cubre CRM-00.06.02.04 (papelera con restauración en cascada),
CRM-07.01.01.07 (transferencia masiva de propiedad) y CRM-07.01.01.08
(importación con validación previa y reversión).

Lo que estas pruebas defienden es un principio: **primero se valida y se enseña
qué va a pasar, y solo después se ejecuta**. Una importación que empieza a
escribir y falla a la mitad deja un maestro de clientes en un estado que nadie
sabe describir.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from services.party import administracion as admin
from services.party import normalizacion as norm
from services.party.modelos import Actividad, Contacto, Cuenta, IdentificadorFiscal


def _cuenta(db: Any, tenant_id: UUID, nombre: str, **extra: Any) -> Cuenta:
    cuenta = Cuenta(
        tenant_id=tenant_id,
        nombre=nombre,
        clave_canonica=norm.clave_canonica_empresa(nombre),
        **extra,
    )
    db.add(cuenta)
    db.flush()
    return cuenta


# ── Papelera ──────────────────────────────────────────────────────────────


def test_borrar_arrastra_las_actividades_y_restaurar_las_devuelve(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """CRM-00.06.02.04: restaurar a medias es peor que no restaurar.

    Una cuenta que vuelve sin su historial parece completa, y nadie nota que
    falta la mitad hasta que hace falta.
    """
    cuenta = _cuenta(db, tenant_id, "ACME Ibérica, S.L.")
    db.add_all(
        [
            Actividad(
                tenant_id=tenant_id, tipo="llamada", asunto="Primera toma", cuenta_id=cuenta.id
            ),
            Actividad(
                tenant_id=tenant_id, tipo="nota", asunto="Notas de la visita", cuenta_id=cuenta.id
            ),
        ]
    )
    db.flush()

    entrada = admin.borrar_cuenta(db, cuenta.id)
    db.flush()

    assert cuenta.deleted_at is not None
    assert entrada.cascada.get("actividades") and len(entrada.cascada["actividades"]) == 2
    assert db.query(Actividad).filter(Actividad.deleted_at.is_(None)).count() == 0

    admin.restaurar_entrada(db, entrada.id)
    db.flush()

    assert cuenta.deleted_at is None
    assert db.query(Actividad).filter(Actividad.deleted_at.is_(None)).count() == 2


def test_no_se_restaura_lo_que_ya_estaba_borrado_antes(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La cascada guarda QUÉ se borró con la cabecera, no «todos los hijos».

    Sin esa distinción, restaurar resucitaría también lo que alguien había
    borrado a propósito semanas antes.
    """
    from datetime import datetime, timezone

    cuenta = _cuenta(db, tenant_id, "Con historia")
    vieja = Actividad(
        tenant_id=tenant_id,
        tipo="nota",
        asunto="Borrada hace tiempo",
        cuenta_id=cuenta.id,
        deleted_at=datetime.now(timezone.utc),
    )
    viva = Actividad(tenant_id=tenant_id, tipo="llamada", asunto="Viva", cuenta_id=cuenta.id)
    db.add_all([vieja, viva])
    db.flush()

    entrada = admin.borrar_cuenta(db, cuenta.id)
    db.flush()
    assert len(entrada.cascada.get("actividades", [])) == 1

    admin.restaurar_entrada(db, entrada.id)
    db.flush()
    assert viva.deleted_at is None
    assert vieja.deleted_at is not None, "la que ya estaba borrada debe seguir borrada"


def test_no_se_borra_dos_veces(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """La segunda vez responde 404, no 409, y está bien que sea así.

    Una cuenta en la papelera se comporta como inexistente para la API: quien la
    busca debe ir a la papelera. Devolver 409 («ya borrada») confirmaría su
    existencia a quien quizá no debería saberla.
    """
    from crmcore.errors import NoEncontrado

    cuenta = _cuenta(db, tenant_id, "Una sola vez")
    admin.borrar_cuenta(db, cuenta.id)
    db.flush()
    with pytest.raises(NoEncontrado) as exc:
        admin.borrar_cuenta(db, cuenta.id)
    assert exc.value.error_code == "party.cuenta_no_encontrada"


def test_la_purga_respeta_el_plazo(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Lo que aún no ha cumplido su plazo no se destruye."""
    cuenta = _cuenta(db, tenant_id, "Recién borrada")
    admin.borrar_cuenta(db, cuenta.id)
    db.flush()

    purgados = admin.purgar_vencidos(db, tenant_id, motivo="purga programada de prueba")
    assert purgados == {}
    assert db.get(Cuenta, cuenta.id) is not None


def test_la_purga_destruye_lo_vencido_y_queda_auditada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from datetime import datetime, timedelta, timezone

    from crmcore.audit.modelos import ApunteAuditoria

    cuenta = _cuenta(db, tenant_id, "Vencida")
    entrada = admin.borrar_cuenta(db, cuenta.id)
    entrada.purgable_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.flush()

    purgados = admin.purgar_vencidos(db, tenant_id, motivo="retención cumplida, purga mensual")
    db.flush()

    assert purgados.get("cuenta") == 1
    assert db.get(Cuenta, cuenta.id) is None
    assert (
        db.query(ApunteAuditoria).filter_by(accion="datos.purga").count() == 1
    ), "destruir datos de un cliente tiene que quedar auditado"


# ── Transferencia de propiedad ────────────────────────────────────────────


def test_la_transferencia_simulada_no_toca_nada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Quien la ejecuta necesita ver cuánto va a mover antes de moverlo."""
    from crmcore.ids import nuevo_id

    ana, luis = nuevo_id(), nuevo_id()
    for n in range(3):
        _cuenta(db, tenant_id, f"Cuenta {n}", owner_id=ana)
    db.flush()

    resumen = admin.transferir(
        db, tenant_id=tenant_id, de_usuario=ana, a_usuario=luis, motivo="prueba", simular=True
    )
    assert resumen == {"cuentas": 3}
    assert db.query(Cuenta).filter_by(owner_id=ana).count() == 3, "la simulación no mueve nada"


def test_la_transferencia_mueve_todos_los_objetos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Hacerlo objeto por objeto garantiza que alguno se olvide.

    Y un registro sin dueño es invisible para las reglas de visibilidad por
    propietario: desaparece sin que nadie lo borre.
    """
    from crmcore.ids import nuevo_id

    ana, luis = nuevo_id(), nuevo_id()
    _cuenta(db, tenant_id, "Su cuenta", owner_id=ana)
    db.add(
        Contacto(
            tenant_id=tenant_id,
            nombre="Su",
            apellidos="contacto",
            nombre_completo="Su contacto",
            clave_canonica="contacto su",
            owner_id=ana,
        )
    )
    db.flush()

    resumen = admin.transferir(
        db,
        tenant_id=tenant_id,
        de_usuario=ana,
        a_usuario=luis,
        motivo="Ana deja la empresa el 30 de septiembre",
    )
    db.flush()

    assert resumen == {"cuentas": 1, "contactos": 1}
    assert db.query(Cuenta).filter_by(owner_id=ana).count() == 0
    assert db.query(Contacto).filter_by(owner_id=luis).count() == 1


# ── Importación ───────────────────────────────────────────────────────────


FILAS = [
    {"nombre": "Alfa Construcciones, S.L.", "nif": "A58818501", "email": "info@alfa.es"},
    {"nombre": "Beta Servicios SA", "nif": "B12345674"},
    {"nombre": "", "nif": "A58818501"},  # sin nombre: inválida
    {"nombre": "Gamma", "nif": "12345678A"},  # NIF con letra incorrecta
]


def test_la_importacion_simula_por_defecto(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """La operación destructiva se pide a propósito.

    Quien llame por error con un fichero de prueba recibe un informe, no un
    maestro de clientes contaminado.
    """
    informe = admin.importar_cuentas(db, FILAS)
    db.flush()

    assert informe.total == 4
    assert informe.creados == 2
    assert informe.fallidos == 2
    assert db.query(Cuenta).count() == 0, "la simulación no escribe"
    # Y dice exactamente qué fila falla y por qué.
    motivos = {e["fila"]: e["errores"][0] for e in informe.errores}
    assert "obligatorio" in motivos[3]
    assert "no es un NIF" in motivos[4]


def test_la_importacion_real_carga_lo_bueno_y_reporta_lo_malo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Que noventa filas estén mal no es razón para no cargar las 9.910 buenas."""
    informe = admin.importar_cuentas(db, FILAS, simular=False)
    db.flush()

    assert informe.creados == 2 and informe.fallidos == 2
    assert db.query(Cuenta).count() == 2
    assert db.query(IdentificadorFiscal).count() == 2


def test_la_importacion_reconoce_lo_que_ya_existe_por_su_identificador(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Dos filas con el mismo NIF son la misma entidad aunque el nombre difiera."""
    admin.importar_cuentas(db, [FILAS[0]], simular=False)
    db.flush()

    informe = admin.importar_cuentas(
        db,
        [{"nombre": "ALFA CONSTRUCCIONES SOCIEDAD LIMITADA", "nif": "A-58818501"}],
        simular=False,
    )
    db.flush()
    assert informe.omitidos == 1 and informe.creados == 0
    assert db.query(Cuenta).count() == 1


def test_actualizar_rellena_huecos_pero_no_pisa(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una importación que sobrescribe deja el maestro a merced del último fichero.

    Y el último casi nunca es el más completo. Para sobrescribir a propósito
    está la edición, que deja historial campo a campo.
    """
    admin.importar_cuentas(
        db, [{"nombre": "Alfa", "nif": "A58818501", "email": "bueno@alfa.es"}], simular=False
    )
    db.flush()

    admin.importar_cuentas(
        db,
        [{"nombre": "Alfa", "nif": "A58818501", "email": "otro@alfa.es", "web": "https://alfa.es"}],
        simular=False,
        actualizar=True,
    )
    db.flush()

    cuenta = db.query(Cuenta).one()
    assert cuenta.email == "bueno@alfa.es", "no se pisa lo que ya había"
    assert cuenta.web == "https://alfa.es", "sí se rellena el hueco"


def test_un_fichero_sin_las_columnas_obligatorias_falla_entero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es un error del fichero, no de sus filas: decirlo cien mil veces no ayuda."""
    from crmcore.errors import ErrorValidacion

    with pytest.raises(ErrorValidacion) as exc:
        admin.importar_cuentas(db, [{"razon_social": "Alfa"}])
    assert exc.value.error_code == "importacion.columnas_faltan"
    assert exc.value.detalle["faltan"] == ["nombre"]


def test_un_lote_demasiado_grande_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin tope, una carga de un millón de filas bloquea el servicio para todos."""
    from crmcore.errors import ErrorValidacion

    with pytest.raises(ErrorValidacion) as exc:
        admin.importar_cuentas(db, [{"nombre": f"C{i}"} for i in range(1001)])
    assert exc.value.error_code == "importacion.lote_demasiado_grande"


def test_el_informe_no_devuelve_errores_sin_fin(db: Any, tenant_id: UUID) -> None:
    """Un fichero con todo mal produciría una respuesta imposible de leer.

    El recuento sigue siendo exacto; lo que se recorta es la lista.
    """
    from crmcore.datos.masivas import Informe, _masivas_errores_devueltos

    informe = Informe(total=1000)
    for fila in range(1, 1001):
        informe.anotar_error(fila, "validacion")
    d = informe.a_dict()
    assert informe.fallidos == 1000
    assert len(d["errores"]) == _masivas_errores_devueltos()
    assert d["errores_no_mostrados"] == 1000 - _masivas_errores_devueltos()
