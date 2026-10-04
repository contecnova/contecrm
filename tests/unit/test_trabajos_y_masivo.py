"""Operaciones masivas (CRM-00.02.01.11) y trabajos asíncronos (CRM-00.02.01.12).

Lo que estas pruebas defienden son tres promesas que, si no se cumplen, hacen
más daño que no tener la funcionalidad:

  * **El informe no miente.** Si dice «9.910 creados», hay 9.910 en la base. Una
    fila mala no puede llevarse por delante a las buenas ni al revés.
  * **El cursor es una promesa, no una estimación.** Un trabajo que se corta y
    se reanuda no repite lo ya hecho ni se salta lo que faltaba.
  * **El camino masivo no puede hacer más que el individual.** Ni saltarse la
    validación, ni los permisos, ni los eventos de dominio.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos import trabajos as tj
from crmcore.datos.masivas import Informe
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.http.masivo_router import RecursoMasivo, aplicar
from crmcore.http.trabajos_router import RETRY_AFTER_S

from services.party.masivo import CUENTAS
from services.party.modelos import Cuenta


def _uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _elementos(cuantos: int, desde: int = 0) -> list[dict[str, Any]]:
    return [{"nombre": f"Empresa {i} S.L."} for i in range(desde, desde + cuantos)]


# ── El informe parcial ────────────────────────────────────────────────────


@pytest.mark.db
def test_una_fila_mala_no_se_lleva_por_delante_a_las_buenas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es la razón de ser del punto de guardado por elemento.

    Sin él, la fila que viola una restricción aborta la transacción de Postgres
    y las anteriores —ya escritas— desaparecen: el informe diría «3 creadas» y
    en la base no habría ninguna.
    """
    informe = Informe()
    elementos = [
        {"nombre": "Buena Uno S.L."},
        # Sin nombre: el esquema `CrearCuenta` lo exige, así que revienta al
        # validar, antes de tocar la base.
        {"sector_codigo": "6201"},
        {"nombre": "Buena Dos S.L."},
    ]
    aplicar(_uow(db, tenant_id), CUENTAS, "crear", elementos, informe=informe)
    db.flush()

    assert informe.total == 3
    assert informe.creados == 2
    assert informe.fallidos == 1
    assert informe.errores[0]["fila"] == 2
    # Y lo que dice el informe está de verdad en la base.
    nombres = set(db.execute(Cuenta.__table__.select().with_only_columns(Cuenta.nombre)).scalars())
    assert nombres == {"Buena Uno S.L.", "Buena Dos S.L."}


@pytest.mark.db
def test_la_fila_del_error_es_la_del_fichero_y_no_la_del_trozo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Quien corrige está mirando su hoja de cálculo.

    Decirle «fila 2» cuando es la 202 del fichero le hace corregir la línea
    equivocada, que es peor que no decirle nada.
    """
    informe = Informe()
    aplicar(
        _uow(db, tenant_id),
        CUENTAS,
        "crear",
        [{"nombre": "Vale S.L."}, {}],
        informe=informe,
        desplazamiento=200,
    )
    assert informe.errores[0]["fila"] == 202


@pytest.mark.db
def test_el_informe_recorta_los_errores_pero_no_el_recuento(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un fichero con todo mal no puede producir una respuesta ilegible; pero
    decir «200 errores» cuando hay 300 haría corregir a medias."""
    from crmcore.datos.masivas import MAX_ERRORES_DEVUELTOS

    informe = Informe()
    malos = [{} for _ in range(MAX_ERRORES_DEVUELTOS + 40)]
    aplicar(_uow(db, tenant_id), CUENTAS, "crear", malos, informe=informe)

    assert informe.fallidos == MAX_ERRORES_DEVUELTOS + 40
    assert len(informe.errores) == MAX_ERRORES_DEVUELTOS
    assert informe.a_dict()["errores_no_mostrados"] == 40


@pytest.mark.db
def test_los_eventos_de_una_fila_que_falla_no_se_publican(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un `account.created` de una cuenta cuyo punto de guardado se deshizo es
    un evento que ningún consumidor podrá resolver: buscará la cuenta y no
    estará.

    El recurso es de mentira a propósito. La primera versión de esta prueba
    usaba cuentas de verdad con un campo demasiado largo, y resultó ser una
    prueba **vacía**: Pydantic rechazaba la fila antes de que se emitiera nada,
    así que habría pasado igual sin la limpieza de eventos. Para probar el
    descarte hace falta un alta que emita y falle DESPUÉS, y eso solo se
    construye a mano.
    """

    def _emite_y_revienta(uow: UnidadDeTrabajo, elemento: dict[str, Any]) -> UUID:
        registro_id = uuid4()
        uow.emitir("prueba.creado", subject=("prueba", registro_id), data=dict(elemento))
        if elemento.get("revienta"):
            raise RuntimeError("falla después de emitir")
        return registro_id

    recurso = RecursoMasivo(
        recurso=f"emisor{uuid4().hex[:6]}",
        objeto="emisor",
        permisos={"crear": "x:write"},
        crear=_emite_y_revienta,
    )
    uow = _uow(db, tenant_id)
    informe = Informe()
    aplicar(
        uow,
        recurso,
        "crear",
        [{"n": "buena"}, {"n": "mala", "revienta": True}, {"n": "otra buena"}],
        informe=informe,
    )

    assert informe.creados == 2 and informe.fallidos == 1
    assert [e["data"]["n"] for e in uow._pendientes] == ["buena", "otra buena"]


# ── upsert ────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_el_upsert_reconoce_por_identificador_fiscal_antes_que_por_nombre(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un NIF identifica; un nombre solo se parece. Al revés, dos sociedades del
    mismo grupo con nombre casi igual se fundirían sin que nadie lo pidiera."""
    uow = _uow(db, tenant_id)
    informe = Informe()
    aplicar(
        uow,
        CUENTAS,
        "crear",
        [
            {
                "nombre": "ACME Ibérica S.L.",
                "identificadores": [{"tipo": "cif", "valor": "B12345674"}],
            }
        ],
        informe=informe,
    )
    db.flush()
    assert informe.creados == 1

    # Mismo NIF, nombre distinto: es la misma empresa, se actualiza.
    segundo = Informe()
    aplicar(
        uow,
        CUENTAS,
        "upsert",
        [
            {
                "nombre": "ACME Ibérica, Sociedad Limitada",
                "identificadores": [{"tipo": "cif", "valor": "B12345674"}],
            }
        ],
        informe=segundo,
    )
    db.flush()

    assert segundo.actualizados == 1 and segundo.creados == 0
    assert db.query(Cuenta).count() == 1


@pytest.mark.db
def test_el_upsert_sin_clave_falla_en_vez_de_crear_un_duplicado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    informe = Informe()
    aplicar(_uow(db, tenant_id), CUENTAS, "upsert", [{"sector_codigo": "6201"}], informe=informe)

    assert informe.fallidos == 1
    assert "masivo.sin_clave" in informe.errores[0]["codigo"]


@pytest.mark.db
def test_un_recurso_que_no_declara_buscar_no_admite_upsert() -> None:
    """Y se dice, en vez de hacer un alta y llamarla actualización."""
    from services.party.masivo import CONTACTOS

    assert CONTACTOS.admite("crear")
    assert not CONTACTOS.admite("upsert")
    assert not CONTACTOS.admite("borrar")


def test_el_upsert_exige_el_permiso_de_crear_y_no_el_de_actualizar() -> None:
    """Es el más fuerte de los dos que puede acabar ejecutando. Con el de
    actualizar bastaría para dar de alta por la puerta de atrás."""
    assert CUENTAS.permiso_de("upsert") == CUENTAS.permisos["crear"]


def test_ningun_recurso_masivo_pide_un_permiso_que_su_ruta_individual_no_pida() -> None:
    """El camino masivo no puede habilitar nada nuevo.

    Se comprueba contra los permisos que de verdad usan las rutas de uno en uno,
    leídos del propio `api.py`: una lista escrita a mano aquí envejecería.
    """
    import re
    from pathlib import Path

    from services.party.masivo import RECURSOS as DE_PARTY
    from services.sales.masivo import RECURSOS as DE_SALES

    raiz = Path(__file__).resolve().parents[2]
    for servicio, recursos in (("party", DE_PARTY), ("sales", DE_SALES)):
        fuente = (raiz / "services" / servicio / "api.py").read_text(encoding="utf-8")
        en_rutas = set(re.findall(r'exige_permiso\("([^"]+)"\)', fuente))
        for recurso in recursos:
            for operacion, permiso in recurso.permisos.items():
                assert permiso in en_rutas, (
                    f"{servicio}.{recurso.recurso}.{operacion} pide «{permiso}», "
                    f"que ninguna ruta individual de {servicio} exige"
                )


# ── Trabajos: ciclo de vida ───────────────────────────────────────────────


@pytest.mark.db
def test_encolar_un_tipo_sin_ejecutor_se_rechaza_al_aceptarlo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Y no al ejecutarlo. Así el error lo ve quien lo puede arreglar, en la
    misma respuesta, y no un log de madrugada."""
    from crmcore.errors import ErrorValidacion

    with pytest.raises(ErrorValidacion, match="ejecutor"):
        tj.encolar(db, tenant_id=tenant_id, tipo="inventado.masivo", entrada={})


@pytest.mark.db
def test_un_trabajo_avanza_por_tandas_y_termina(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    trabajo = tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": _elementos(7)},
        total=7,
    )
    db.commit()

    # Tandas de tres: 3 + 3 + 1, y una vuelta más que devuelve «no queda nada».
    vueltas = 0
    while tj.avanzar(db, trabajo, tanda_max=3):
        vueltas += 1
        assert vueltas < 10, "el trabajo no converge"

    assert trabajo.estado == "completado"
    assert trabajo.ok == 7 and trabajo.fallidos == 0
    assert trabajo.cursor == trabajo.total == 7
    assert db.query(Cuenta).count() == 7


@pytest.mark.db
def test_un_trabajo_interrumpido_se_reanuda_donde_estaba(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La prueba del cursor, que es lo que separa esto de una barra de progreso.

    Se simula la muerte del worker dejando de llamar a `avanzar` a mitad y
    recargando el trabajo desde la base, que es todo lo que sobrevive.
    """
    trabajo = tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": _elementos(10)},
        total=10,
    )
    db.commit()

    tj.avanzar(db, trabajo, tanda_max=4)
    assert trabajo.cursor == 4
    assert db.query(Cuenta).count() == 4

    # Aquí «muere» el worker. Otro lo relee y sigue.
    db.expunge_all()
    retomado = tj.leer(db, trabajo.id)
    assert retomado.cursor == 4

    while tj.avanzar(db, retomado, tanda_max=4):
        pass

    # Ni repite las cuatro primeras ni se salta las seis que faltaban.
    assert db.query(Cuenta).count() == 10
    assert retomado.ok == 10


@pytest.mark.db
def test_el_total_se_cierra_con_lo_que_de_verdad_se_proceso(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si se anuncian 1.000 y el lote traía 3, dejar el 1.000 haría que la ficha
    dijera «0,3 %» sobre un trabajo terminado."""
    trabajo = tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": _elementos(3)},
        total=1_000,
    )
    db.commit()
    while tj.avanzar(db, trabajo, tanda_max=50):
        pass

    assert trabajo.total == 3
    assert tj.a_dict(trabajo)["porcentaje"] == 100.0


@pytest.mark.db
def test_sin_total_conocido_el_porcentaje_es_nulo_y_no_cero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Son cosas distintas, y confundirlas deja una barra clavada en el cero
    mientras el trabajo avanza bien."""
    trabajo = tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": []},
    )
    assert tj.a_dict(trabajo)["porcentaje"] is None


@pytest.mark.db
def test_los_errores_de_un_trabajo_se_acumulan_entre_tandas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    elementos = [{"nombre": "Buena S.L."}, {}, {"nombre": "Otra S.L."}, {}]
    trabajo = tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": elementos},
        total=4,
    )
    db.commit()
    while tj.avanzar(db, trabajo, tanda_max=2):
        pass

    assert trabajo.ok == 2 and trabajo.fallidos == 2
    # Las filas son las del lote entero, no las de cada tanda.
    assert [e["fila"] for e in trabajo.errores] == [2, 4]


@pytest.mark.db
def test_un_ejecutor_que_revienta_deja_el_trabajo_fallido_y_no_colgado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un trabajo «ejecutando» para siempre es el peor modo de fallo: nadie lo
    llama avería."""

    def _explota(_db: Any, _trabajo: Any, _tope: int) -> Any:
        raise RuntimeError("la base se ha ido")

    tj.registrar_ejecutor("prueba.explota", _explota)
    trabajo = tj.encolar(db, tenant_id=tenant_id, tipo="prueba.explota", entrada={})
    db.commit()

    assert tj.avanzar(db, trabajo, tanda_max=10) is False
    recargado = tj.leer(db, trabajo.id)
    assert recargado.estado == "fallido"
    assert "la base se ha ido" in recargado.error
    assert recargado.tomado_hasta is None


@pytest.mark.db
def test_cancelar_un_trabajo_ya_terminado_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.errors import Conflicto

    trabajo = tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": _elementos(1)},
        total=1,
    )
    db.commit()
    while tj.avanzar(db, trabajo, tanda_max=10):
        pass

    with pytest.raises(Conflicto, match="ya está"):
        tj.cancelar(db, trabajo.id)


@pytest.mark.db
def test_cancelar_a_media_ejecucion_conserva_lo_ya_escrito(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una importación cancelada a la mitad ha metido media importación. Decir
    otra cosa —o deshacerlo en silencio— sería peor que ambas."""
    trabajo = tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": _elementos(10)},
        total=10,
    )
    db.commit()
    tj.avanzar(db, trabajo, tanda_max=4)

    tj.cancelar(db, trabajo.id)
    assert tj.avanzar(db, trabajo, tanda_max=4) is False

    recargado = tj.leer(db, trabajo.id)
    assert recargado.estado == "cancelado"
    # Las cuatro de la primera tanda siguen, más las cuatro de la tanda que ya
    # estaba comprometida cuando llegó la cancelación.
    assert db.query(Cuenta).count() == recargado.cursor
    assert recargado.cursor >= 4


# ── Toma de lote y bloqueo ────────────────────────────────────────────────


@pytest.mark.db
def test_un_trabajo_tomado_no_lo_coge_otro_worker(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": _elementos(1)},
        total=1,
    )
    db.commit()

    primero = tj.tomar_lote(db, worker_id="w-1", lote=10)
    assert len(primero) == 1
    assert tj.tomar_lote(db, worker_id="w-2", lote=10) == []


@pytest.mark.db
def test_un_bloqueo_caducado_lo_recupera_otro_worker(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es toda la recuperación que hace falta, y es automática: no hay un
    procedimiento de rescate que alguien tenga que acordarse de lanzar."""
    from datetime import datetime, timedelta, timezone

    trabajo = tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": _elementos(1)},
        total=1,
    )
    db.commit()
    tj.tomar_lote(db, worker_id="w-muerto", lote=10)

    # El worker murió: su bloqueo caduca sin que nadie lo suelte.
    trabajo.tomado_hasta = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    recuperados = tj.tomar_lote(db, worker_id="w-vivo", lote=10)
    assert [t.id for t in recuperados] == [trabajo.id]
    assert recuperados[0].tomado_por == "w-vivo"


@pytest.mark.db
def test_soltar_libera_el_bloqueo_sin_cerrar_el_trabajo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que hace un apagado limpio: sin esto, un despliegue cuesta minutos
    de parada de algo que se sabía que iba a pasar."""
    trabajo = tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": _elementos(2)},
        total=2,
    )
    db.commit()
    tj.tomar_lote(db, worker_id="w-1", lote=10)

    tj.soltar(db, trabajo)
    assert trabajo.tomado_hasta is None
    assert trabajo.estado in tj.ESTADOS_VIVOS
    assert len(tj.tomar_lote(db, worker_id="w-2", lote=10)) == 1


# ── Retención y callback ──────────────────────────────────────────────────


@pytest.mark.db
def test_un_trabajo_caducado_se_borra_de_verdad(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La entrada guarda los datos que subió el cliente. Conservarlos pasado el
    plazo es justo lo que el plazo impide."""
    from datetime import datetime, timedelta, timezone

    trabajo = tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": _elementos(1)},
        total=1,
    )
    db.commit()
    while tj.avanzar(db, trabajo, tanda_max=10):
        pass
    trabajo.expira_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    assert tj.purgar_caducados(db) == 1
    assert db.get(tj.Trabajo, trabajo.id) is None


@pytest.mark.db
def test_un_trabajo_vivo_no_se_purga_aunque_haya_caducado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Borrar un trabajo en vuelo dejaría al worker escribiendo contra una fila
    que ya no existe, y al cliente sondeando un 404 sin explicación."""
    from datetime import datetime, timedelta, timezone

    trabajo = tj.encolar(
        db,
        tenant_id=tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={"operacion": "crear", "elementos": _elementos(1)},
        total=1,
    )
    trabajo.expira_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

    assert tj.purgar_caducados(db) == 0


@pytest.mark.db
def test_una_url_de_aviso_interna_se_rechaza_al_encolar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El aviso lo dispara el worker desde la red interna: sin guard, este campo
    sería un SSRF con persistencia. Y se rechaza al aceptar el trabajo, no al
    dispararlo, porque para entonces el cliente ya se fue creyendo que le
    avisarían."""
    from crmcore.errors import ErrorValidacion

    with pytest.raises(ErrorValidacion):
        tj.encolar(
            db,
            tenant_id=tenant_id,
            tipo=CUENTAS.tipo_trabajo,
            entrada={"operacion": "crear", "elementos": []},
            callback_url="http://169.254.169.254/latest/meta-data/",
        )


def test_la_firma_del_aviso_es_la_misma_que_la_de_los_webhooks() -> None:
    """Dos implementaciones del mismo HMAC divergen, y la integración que
    verifica bien los webhooks acaba rechazando los avisos sin que nadie
    entienda por qué."""
    from crmcore.security import firma as comun

    from services.eventing import entrega

    assert entrega.firmar is comun.firmar
    assert entrega.H_FIRMA == comun.H_FIRMA


def test_el_aviso_firmado_se_verifica_y_un_reenvio_viejo_no() -> None:
    import time

    from crmcore.security.firma import H_FIRMA, H_MOMENTO, cabeceras_firmadas, verificar_firma

    cuerpo = b'{"estado":"completado"}'
    cabeceras = cabeceras_firmadas(cuerpo, "secreto-de-prueba")
    momento = int(cabeceras[H_MOMENTO])

    assert verificar_firma(cuerpo, "secreto-de-prueba", cabeceras[H_FIRMA], momento)
    # El mismo mensaje capturado y reenviado fuera de ventana no vale.
    assert not verificar_firma(
        cuerpo,
        "secreto-de-prueba",
        cabeceras[H_FIRMA],
        int(time.time()) - 10_000,
    )


# ── Registro de ejecutores ────────────────────────────────────────────────


def test_registrar_dos_ejecutores_para_el_mismo_tipo_se_rechaza() -> None:
    """En un proceso que importa varios servicios —las pruebas— el segundo
    registro pisaría al primero, y el trabajo de un servicio se ejecutaría
    contra el esquema de otro."""

    def _uno(_db: Any, _t: Any, _n: int) -> Any:
        return None

    def _otro(_db: Any, _t: Any, _n: int) -> Any:
        return None

    tj.registrar_ejecutor("prueba.colision", _uno)
    tj.registrar_ejecutor("prueba.colision", _uno)  # el mismo, no pasa nada
    with pytest.raises(RuntimeError, match="ya tiene ejecutor"):
        tj.registrar_ejecutor("prueba.colision", _otro)


def test_todo_recurso_masivo_montado_tiene_su_ejecutor_registrado() -> None:
    """El worker es otro proceso y no monta routers: si el registro dependiera
    de montarlos, arrancaría sin conocer un solo tipo y los trabajos se
    quedarían encolados para siempre. Pasó al escribir el worker."""
    import services.party.api  # noqa: F401
    import services.sales.api  # noqa: F401
    from services.party.masivo import RECURSOS as DE_PARTY
    from services.sales.masivo import RECURSOS as DE_SALES

    for recurso in (*DE_PARTY, *DE_SALES):
        assert tj.ejecutor_de(recurso.tipo_trabajo) is not None, recurso.recurso


def test_montar_un_router_masivo_sin_ejecutor_falla_al_arrancar() -> None:
    """Y no al primer 202: un servicio que expone el camino diferido sin
    ejecutor aceptaría trabajos que nadie va a ejecutar."""
    from crmcore.http.masivo_router import crear_router_masivo

    huerfano = RecursoMasivo(
        recurso=f"huerfano{uuid4().hex[:6]}",
        objeto="huerfano",
        permisos={"crear": "x:write"},
        crear=lambda _uow, _e: uuid4(),
    )
    with pytest.raises(RuntimeError, match="sin haber registrado su ejecutor"):
        crear_router_masivo(huerfano)


# ── El contrato por HTTP ──────────────────────────────────────────────────


@pytest.fixture
def api_party(db: Any, tenant_id: UUID) -> Any:
    """La API real de `party`, montada con la factoría de producción.

    No un router suelto: lo que hay que comprobar es el arreglo completo —la
    dependencia de permisos, la unidad de trabajo, el middleware de idempotencia
    y el manejador de errores—, y un montaje parcial pasaría sin que el sistema
    funcionara.
    """
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas
    from crmcore.service import crear_servicio
    from starlette.testclient import TestClient

    from services.party.api import ROUTERS

    app = crear_servicio(
        nombre="party",
        descripcion="party para pruebas de operaciones masivas",
        routers=ROUTERS,
        necesita_bus=False,
    )
    usuario = uuid4()

    class _Cliente:
        def __init__(self) -> None:
            self.http = TestClient(app)

        def llamar(self, metodo: str, ruta: str, permisos: str = "*:*", **kwargs: Any) -> Any:
            # Firmadas, como las manda el gateway: sin firma el servicio trata la
            # petición como anónima —que es lo que impide que cualquiera se
            # declare de otro tenant—, así que una prueba sin firmar no probaría
            # nada.
            cabeceras = firmar_cabeceras_internas(
                {H_TENANT: str(tenant_id), H_USER: str(usuario), H_PERMISOS: permisos},
                get_settings().secret_key.get_secret_value(),
            )
            return self.http.request(metodo, f"/api/v1{ruta}", headers=cabeceras, **kwargs)

    return _Cliente()


@pytest.mark.db
def test_un_lote_correcto_responde_207_con_el_informe(api_party: Any) -> None:
    respuesta = api_party.llamar(
        "POST",
        "/cuentas/masivo",
        json={
            "operacion": "crear",
            "elementos": [{"nombre": "Alfa S.L."}, {"nombre": "Beta S.L."}],
        },
    )
    assert respuesta.status_code == 207
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 2 and cuerpo["creados"] == 2 and cuerpo["fallidos"] == 0


@pytest.mark.db
def test_un_lote_a_medias_responde_207_igual_y_lo_dice(api_party: Any) -> None:
    """207 también cuando todo va bien: el cliente lee el informe siempre igual
    y no tiene que tratar dos formas distintas de éxito."""
    respuesta = api_party.llamar(
        "POST",
        "/cuentas/masivo",
        json={"operacion": "crear", "elementos": [{"nombre": "Gamma S.L."}, {}]},
    )
    assert respuesta.status_code == 207
    cuerpo = respuesta.json()
    assert cuerpo["creados"] == 1 and cuerpo["fallidos"] == 1
    assert cuerpo["errores"][0]["fila"] == 2


@pytest.mark.db
def test_sin_el_permiso_de_la_operacion_se_rechaza(api_party: Any) -> None:
    """El permiso depende del cuerpo, no de la ruta: quien solo puede leer no
    puede dar de alta en lote."""
    respuesta = api_party.llamar(
        "POST",
        "/cuentas/masivo",
        permisos="account:read",
        json={"operacion": "crear", "elementos": [{"nombre": "Delta S.L."}]},
    )
    assert respuesta.status_code == 403


@pytest.mark.db
def test_pasado_el_tope_sincrono_se_dice_como_pedirlo_en_diferido(api_party: Any) -> None:
    """Un 413 a secas deja al integrador adivinando. El error trae la ruta
    exacta del camino que sí acepta el lote."""
    import os

    from crmcore.config import limpiar_cache_settings

    os.environ["BULK_MAX_ITEMS"] = "3"
    limpiar_cache_settings()
    try:
        respuesta = api_party.llamar(
            "POST",
            "/cuentas/masivo",
            json={"operacion": "crear", "elementos": [{"nombre": f"E{i} S.L."} for i in range(5)]},
        )
    finally:
        del os.environ["BULK_MAX_ITEMS"]
        limpiar_cache_settings()

    assert respuesta.status_code == 413
    cuerpo = respuesta.json()
    assert cuerpo["error_code"] == "masivo.lote_excesivo"
    assert cuerpo["detalle"]["alternativa"] == "POST /cuentas/masivo?modo=asincrono"


@pytest.mark.db
def test_el_camino_diferido_responde_202_con_location_y_se_puede_sondear(
    api_party: Any,
) -> None:
    aceptado = api_party.llamar(
        "POST",
        "/cuentas/masivo?modo=asincrono",
        json={"operacion": "crear", "elementos": [{"nombre": "Epsilon S.L."}]},
    )
    assert aceptado.status_code == 202
    ficha = aceptado.json()
    # La ruta PÚBLICA, con prefijo y servicio: quien sigue esta cabecera está
    # fuera y entra por el gateway, y `/trabajos/{id}` a secas es ambiguo —los
    # trabajos los tienen varios servicios— así que devolvía un 404 a quien
    # hacía lo que la cabecera decía.
    assert aceptado.headers["location"] == f"/api/v1/party/trabajos/{ficha['id']}"
    assert ficha["estado"] == "encolado"

    sondeo = api_party.llamar("GET", f"/party/trabajos/{ficha['id']}", permisos="account:import")
    assert sondeo.status_code == 200
    # Mientras no ha terminado, el servidor dice cada cuánto volver a preguntar:
    # sin esto cada cliente elige su intervalo y el que elige 200 ms convierte
    # una importación en una denegación de servicio contra su propio CRM.
    assert sondeo.headers["retry-after"] == str(RETRY_AFTER_S)


@pytest.mark.db
def test_una_operacion_que_el_recurso_no_admite_dice_cuales_si(api_party: Any) -> None:
    respuesta = api_party.llamar(
        "POST",
        "/contactos/masivo",
        json={"operacion": "borrar", "elementos": [{"id": str(uuid4())}]},
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["detalle"]["admitidas"] == ["crear"]


@pytest.mark.db
def test_un_lote_vacio_se_rechaza(api_party: Any) -> None:
    """Aceptarlo devolvería un informe de cero filas que parece un éxito, y quien
    subió un fichero mal leído creería que se importó."""
    respuesta = api_party.llamar(
        "POST", "/cuentas/masivo", json={"operacion": "crear", "elementos": []}
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["error_code"] == "masivo.lote_vacio"


# ── Aislamiento entre tenants en el worker ────────────────────────────────


@pytest.mark.db
def test_un_trabajo_no_puede_tocar_el_registro_de_otro_tenant(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Regresión de una fuga real de ESCRITURA entre tenants.

    El worker tomaba el lote con una sesión de sistema —correcto, hay que mirar
    los trabajos de todos— y **ejecutaba el trabajo en esa misma sesión**. Una
    sesión de sistema aparta al guard del ORM a propósito, y RLS con
    `app.current_tenant` vacío tampoco filtra: la red era exactamente ninguna.

    Un trabajo de operación masiva del tenant B con el identificador de una
    cuenta del tenant A la habría actualizado. Lo encontró el fuzzing
    sistemático de rutas (`test_fuzzing_tenant.py`) el día que se escribió.

    La corrección es que cada trabajo se ejecute en una sesión atada a SU
    tenant. Esta prueba recorre el camino entero del worker para comprobarlo,
    porque comprobar la función de dentro no habría cazado el fallo: el fallo
    estaba en qué sesión se le pasaba.
    """
    from crmcore.datos.trabajos_worker import _procesar
    from crmcore.db.session import nueva_sesion

    import services.party.masivo  # noqa: F401 — registra los ejecutores

    # Una cuenta del tenant A.
    ajena = Cuenta(tenant_id=tenant_id, nombre="Ajena S.L.", clave_canonica="ajena")
    db.add(ajena)
    db.commit()

    # Un trabajo del tenant B que intenta renombrarla.
    trabajo = tj.encolar(
        db,
        tenant_id=otro_tenant_id,
        tipo=CUENTAS.tipo_trabajo,
        entrada={
            "operacion": "actualizar",
            "elementos": [{"id": str(ajena.id), "nombre": "Secuestrada S.L."}],
        },
        total=1,
    )
    db.commit()

    _procesar(trabajo.id, otro_tenant_id, tanda_max=10)

    # La cuenta ajena sigue como estaba…
    comprobacion = nueva_sesion(tenant_id)
    try:
        assert comprobacion.get(Cuenta, ajena.id).nombre == "Ajena S.L."
    finally:
        comprobacion.close()

    # …y el trabajo lo cuenta como fallo, que es lo honesto: para el tenant B
    # ese identificador sencillamente no existe.
    db.expunge_all()
    recargado = tj.leer(db, trabajo.id)
    assert recargado.fallidos == 1 and recargado.ok == 0


@pytest.mark.db
def test_el_guard_esta_puesto_en_cualquier_proceso_que_abra_una_sesion(
    db: Any, tenant_id: UUID
) -> None:
    """El guard se instalaba solo en la factoría de servicio, y un worker nunca
    la llama: abría sesiones sin la red del ORM. Ahora lo instala el propio
    fabricante de sesiones, así que cubre API, workers, scripts y pruebas."""
    from crmcore.db.session import get_sessionmaker
    from crmcore.tenancy.guard import _al_ejecutar
    from sqlalchemy.orm import Session

    get_sessionmaker()
    from sqlalchemy import event

    assert event.contains(Session, "do_orm_execute", _al_ejecutar)


def test_la_ventana_de_la_firma_sale_de_la_configuracion(monkeypatch: Any) -> None:
    """Era una constante mientras el ajuste existía y no lo leía nadie.

    `WEBHOOK_FIRMA_VENTANA_S` está documentado en el manual de referencia como
    configurable entre 30 y 3600 segundos, y `verificar_firma` usaba un 300
    escrito en el código. Quien la bajara para apretar el anti-replay, o la
    subiera porque sus máquinas van desfasadas, cambiaba un número que no hacía
    nada.

    Se comprueba con un mensaje **viejo**: con la ventana corta se rechaza y con
    la ventana larga se acepta. Sin las dos mitades, un cambio que rechazara
    todo pasaría igual.
    """
    import time

    from crmcore.config import get_settings
    from crmcore.security.firma import firmar, verificar_firma

    cuerpo = b'{"hola": "mundo"}'
    hace_un_rato = int(time.time()) - 200
    firma = firmar(cuerpo, "secreto-de-prueba", hace_un_rato)

    monkeypatch.setenv("WEBHOOK_FIRMA_VENTANA_S", "60")
    get_settings.cache_clear()
    assert not verificar_firma(
        cuerpo, "secreto-de-prueba", firma, hace_un_rato
    ), "con la ventana en 60 s, un mensaje de hace 200 s tendría que rechazarse"

    monkeypatch.setenv("WEBHOOK_FIRMA_VENTANA_S", "600")
    get_settings.cache_clear()
    assert verificar_firma(cuerpo, "secreto-de-prueba", firma, hace_un_rato), (
        "con la ventana en 600 s tendría que aceptarse: si no, la ventana no se "
        "está leyendo y lo que hay es un rechazo constante"
    )
    get_settings.cache_clear()
