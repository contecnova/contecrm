"""Problemas, telemetría y modelo canónico
(CRM-04.01.01.11, CRM-04.04.02.05, CRM-00.03.04.08, CRM-00.03.04.09).

Tres módulos distintos con el mismo hilo: **decidir solo lo que se puede decidir
sin equivocarse, y devolver lo demás para que lo mire alguien**. Las pruebas van
detrás de lo contrario:

  * el problema que se cierra con un apaño y vuelve en tres semanas,
  * la correlación que agrupa cien casos que no eran lo mismo,
  * el sensor que se vuelve loco y abre mil casos,
  * el que deja de emitir y no dispara nada porque no manda nada,
  * el eco de sincronización que rebota el mismo dato para siempre,
  * y «gana el más reciente» aplicado sin fechas comparables.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion

from services.integration import canonico as can
from services.integration import telemetria as tel
from services.service import problemas as prb
from services.service import servicio as svc


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _caso(uow: UnidadDeTrabajo, asunto: str = "No arranca", **kw: Any) -> Any:
    return svc.abrir_caso(uow, asunto=asunto, **kw)


# ── Problemas (CRM-04.01.01.11) ───────────────────────────────────────────


def test_un_problema_no_se_resuelve_con_un_apano(uow: UnidadDeTrabajo) -> None:
    """Cerrarlo con «reiniciamos el servicio» lo hace desaparecer de la lista y
    volver dentro de tres semanas con otro nombre."""
    problema = prb.abrir(uow, titulo="Caídas intermitentes")
    prb.registrar_causa(uow, problema.id, solucion_temporal="Reiniciar el servicio")
    with pytest.raises(ErrorValidacion):
        prb.resolver(uow, problema.id, solucion_definitiva="  ")
    assert uow.db.get(prb.Problema, problema.id).estado == "investigando"


def test_con_causa_y_apano_pasa_a_error_conocido(uow: UnidadDeTrabajo) -> None:
    """Es lo que permite que quien coge la llamada 101 sepa qué contestar."""
    problema = prb.abrir(uow, titulo="Caídas")
    actualizado = prb.registrar_causa(
        uow,
        problema.id,
        causa_raiz="Fuga de conexiones en el pool",
        solucion_temporal="Reiniciar cada noche",
    )
    assert actualizado.estado == "conocido"
    assert actualizado.error_conocido is True


def test_el_impacto_dice_si_solo_hay_apano(uow: UnidadDeTrabajo) -> None:
    problema = prb.abrir(uow, titulo="Caídas")
    prb.registrar_causa(uow, problema.id, causa_raiz="Pool", solucion_temporal="Reiniciar")
    impacto = prb.impacto(uow.db, uow.tenant_id, problema.id)
    assert impacto["solo_apano"] is True


def test_resolver_puede_cerrar_los_casos_vinculados(uow: UnidadDeTrabajo) -> None:
    problema = prb.abrir(uow, titulo="Caída general")
    uno = _caso(uow, "Cliente A no entra")
    dos = _caso(uow, "Cliente B no entra")
    prb.vincular(uow, problema.id, caso_id=uno.id)
    prb.vincular(uow, problema.id, caso_id=dos.id)
    salida = prb.resolver(
        uow,
        problema.id,
        solucion_definitiva="Ampliado el pool y desplegado",
        cerrar_casos=True,
        motivo_cierre="resuelto",
    )
    assert salida["cuantos"] == 2


def test_desvincular_exige_motivo_porque_es_informacion(uow: UnidadDeTrabajo) -> None:
    """Casi siempre significa que era otra cosa, y eso es un dato sobre la causa."""
    problema = prb.abrir(uow, titulo="Caída")
    caso = _caso(uow)
    prb.vincular(uow, problema.id, caso_id=caso.id)
    with pytest.raises(ErrorValidacion):
        prb.desvincular(uow, problema.id, caso_id=caso.id, motivo="")
    fila = prb.desvincular(uow, problema.id, caso_id=caso.id, motivo="Era otra avería")
    assert fila.desvinculado_at is not None


def test_los_desvinculados_se_siguen_viendo_en_el_impacto(uow: UnidadDeTrabajo) -> None:
    """Si no se vieran, nadie sabría que la correlación se equivocó veinte veces."""
    problema = prb.abrir(uow, titulo="Caída")
    uno, dos = _caso(uow, "A"), _caso(uow, "B")
    prb.vincular(uow, problema.id, caso_id=uno.id)
    prb.vincular(uow, problema.id, caso_id=dos.id)
    prb.desvincular(uow, problema.id, caso_id=dos.id, motivo="No era lo mismo")
    impacto = prb.impacto(uow.db, uow.tenant_id, problema.id)
    assert impacto["casos"] == 1 and impacto["desvinculados"] == 1


def test_la_correlacion_propone_y_no_agrupa(uow: UnidadDeTrabajo) -> None:
    """Agrupar solo cien casos que no eran lo mismo da a cien clientes una
    respuesta que no tiene que ver con su problema."""
    for i in range(4):
        _caso(uow, f"Sin servicio {i}", linea="redes")
    salida = prb.correlacionar(uow.db, uow.tenant_id, minimo=3)
    assert salida["propuestas"]
    assert salida["propuestas"][0]["cuantos"] == 4
    # Nada se ha vinculado solo.
    assert (
        uow.db.execute(
            prb.select(prb.CasoDeProblema).where(prb.CasoDeProblema.tenant_id == uow.tenant_id)
        )
        .scalars()
        .all()
        == []
    )


def test_la_correlacion_no_propone_por_debajo_del_minimo(uow: UnidadDeTrabajo) -> None:
    _caso(uow, "Uno", linea="redes")
    _caso(uow, "Dos", linea="redes")
    salida = prb.correlacionar(uow.db, uow.tenant_id, minimo=3)
    assert salida["propuestas"] == []
    assert salida["medible"] is True


def test_sin_casos_abiertos_la_correlacion_no_es_medible(uow: UnidadDeTrabajo) -> None:
    """No se dice que no haya incidentes: se dice que no había nada que mirar."""
    salida = prb.correlacionar(uow.db, uow.tenant_id)
    assert salida["medible"] is False


def test_comunicar_deja_constancia_del_alcance(uow: UnidadDeTrabajo) -> None:
    """«Ya avisamos» sin fecha ni alcance es lo mismo que no haber avisado."""
    problema = prb.abrir(uow, titulo="Caída")
    prb.vincular(uow, problema.id, caso_id=_caso(uow, "A").id)
    comunicacion = prb.comunicar(uow, problema.id, mensaje="Servicio restablecido")
    assert comunicacion.casos_alcanzados == 1


def test_un_problema_con_clientes_y_sin_comunicar_se_senala(uow: UnidadDeTrabajo) -> None:
    problema = prb.abrir(uow, titulo="Caída")
    prb.vincular(uow, problema.id, caso_id=_caso(uow, "A", cuenta_id=uuid4()).id)
    assert prb.impacto(uow.db, uow.tenant_id, problema.id)["sin_comunicar"] is True


# ── Telemetría (CRM-04.04.02.05) ──────────────────────────────────────────


def _dispositivo(uow: UnidadDeTrabajo, **kw: Any) -> tel.Dispositivo:
    base: dict[str, Any] = {"identificador": "SN-1", "cadencia_min": 10}
    base.update(kw)
    fila, _ = tel.registrar_dispositivo(uow, **base)
    return fila


def _regla(uow: UnidadDeTrabajo, **kw: Any) -> tel.ReglaTelemetria:
    base: dict[str, Any] = {
        "clave": "temp-alta",
        "condiciones": [{"atributo": "valor", "operador": ">", "valor": 80}],
        "accion": "caso",
        "severidad": "alta",
    }
    base.update(kw)
    return tel.crear_regla(uow, **base)


def test_una_lectura_de_un_aparato_desconocido_no_se_traga_en_silencio(
    uow: UnidadDeTrabajo,
) -> None:
    """Puede ser un alta que falta o un aparato que no es nuestro."""
    salida = tel.ingerir(uow, identificador="NO-EXISTE", metrica="temp", valor=Decimal(99))
    assert salida["aceptada"] is False and salida["porque"]


def test_una_lectura_que_no_cruza_umbral_lo_dice_y_no_se_guarda(
    uow: UnidadDeTrabajo,
) -> None:
    """Ocho millones de filas al día no caben en el esquema de un CRM."""
    _dispositivo(uow)
    _regla(uow)
    salida = tel.ingerir(uow, identificador="SN-1", metrica="temp", valor=Decimal(20))
    assert salida["aceptada"] is True
    assert salida["guardada"] is False
    assert salida["porque"]


def test_la_lectura_que_dispara_pide_un_caso_y_no_lo_da_por_creado(
    uow: UnidadDeTrabajo,
) -> None:
    """Lo crea el otro servicio y puede rechazarlo: decir «caso creado» sería
    afirmar algo que no consta."""
    _dispositivo(uow, activo_id=uuid4())
    _regla(uow)
    salida = tel.ingerir(uow, identificador="SN-1", metrica="temp", valor=Decimal(95))
    assert salida["disparos"][0]["resultado"] == "caso_pedido"
    assert "no consta creado" in salida["disparos"][0]["nota"]


def test_un_aparato_que_se_vuelve_loco_no_abre_mil_casos(uow: UnidadDeTrabajo) -> None:
    """Sin ventana de silencio, la primera avería de una flota tumba la cola."""
    _dispositivo(uow)
    _regla(uow, silencio_min=120)
    primera = tel.ingerir(uow, identificador="SN-1", metrica="temp", valor=Decimal(95))
    segunda = tel.ingerir(uow, identificador="SN-1", metrica="temp", valor=Decimal(96))
    tercera = tel.ingerir(uow, identificador="SN-1", metrica="temp", valor=Decimal(97))
    assert primera["disparos"][0]["resultado"] == "caso_pedido"
    assert segunda["disparos"][0]["resultado"] == "agrupada"
    assert "2 lecturas agrupadas" in tercera["disparos"][0]["porque"]


def test_un_pico_suelto_no_dispara_si_se_piden_repeticiones(
    uow: UnidadDeTrabajo,
) -> None:
    """Un pico de un segundo no es una avería, y abrir un caso por cada pico hace
    que se apague la regla entera."""
    _dispositivo(uow)
    _regla(uow, repeticiones=3)
    una = tel.ingerir(uow, identificador="SN-1", valor=Decimal(95))
    assert una["disparos"][0]["resultado"] == "acumulando"
    tel.ingerir(uow, identificador="SN-1", valor=Decimal(95))
    tercera = tel.ingerir(uow, identificador="SN-1", valor=Decimal(95))
    assert tercera["disparos"][0]["resultado"] == "caso_pedido"


def test_una_lectura_buena_rompe_la_racha(uow: UnidadDeTrabajo) -> None:
    """Tres lecturas malas salteadas entre buenas no son una avería sostenida."""
    _dispositivo(uow)
    _regla(uow, repeticiones=3)
    tel.ingerir(uow, identificador="SN-1", valor=Decimal(95))
    tel.ingerir(uow, identificador="SN-1", valor=Decimal(10))
    tel.ingerir(uow, identificador="SN-1", valor=Decimal(95))
    salida = tel.ingerir(uow, identificador="SN-1", valor=Decimal(95))
    assert salida["disparos"][0]["resultado"] == "acumulando"


def test_una_regla_con_operador_inventado_no_se_guarda(uow: UnidadDeTrabajo) -> None:
    """De una regla que no salta nunca nadie sospecha, porque «no ha habido
    averías»."""
    with pytest.raises(ErrorValidacion):
        tel.crear_regla(
            uow,
            clave="mala",
            condiciones=[{"atributo": "valor", "operador": "mayor_que", "valor": 80}],
        )


def test_una_regla_sin_condiciones_abriria_un_caso_por_lectura(
    uow: UnidadDeTrabajo,
) -> None:
    with pytest.raises(ErrorValidacion):
        tel.crear_regla(uow, clave="vacia", condiciones=[])


def test_el_silencio_se_detecta_y_se_separa_del_que_nunca_dio_senal(
    uow: UnidadDeTrabajo,
) -> None:
    """Un aparato roto y uno sin instalar no son lo mismo."""
    callado = _dispositivo(uow, identificador="SN-CALLADO", cadencia_min=10)
    callado.ultima_lectura_at = datetime.now(timezone.utc) - timedelta(hours=5)
    _dispositivo(uow, identificador="SN-NUEVO", cadencia_min=10)
    sin_cadencia = _dispositivo(uow, identificador="SN-SIN-CADENCIA", cadencia_min=None)
    uow.db.flush()

    salida = tel.silenciosos(uow.db, uow.tenant_id)
    assert [d["identificador"] for d in salida["callados"]] == ["SN-CALLADO"]
    assert [d["identificador"] for d in salida["nunca_han_dado_senal"]] == ["SN-NUEVO"]
    assert salida["sin_cadencia_declarada"] == [str(sin_cadencia.id)]
    assert salida["concluyente"] is False


def test_un_aparato_sin_cadencia_avisa_al_darlo_de_alta(uow: UnidadDeTrabajo) -> None:
    _, avisos = tel.registrar_dispositivo(uow, identificador="SN-2")
    assert any("dejado de dar señal" in a for a in avisos)


# ── Modelo canónico y sincronización (CRM-00.03.04.09, .08) ───────────────


def _objeto(uow: UnidadDeTrabajo) -> can.ObjetoCanonico:
    fila, _ = can.definir_objeto(
        uow,
        clave="cuenta",
        campos=[
            {"clave": "nombre", "tipo": "texto", "obligatorio": True},
            {"clave": "nif", "tipo": "texto"},
            {"clave": "email", "tipo": "texto"},
            {"clave": "telefono", "tipo": "texto"},
        ],
        claves_negocio=["nif"],
    )
    return fila


def _adaptador(uow: UnidadDeTrabajo, **kw: Any) -> can.Adaptador:
    base: dict[str, Any] = {
        "objeto": "cuenta",
        "sistema": "erp",
        "mapeo": {"nombre": "razon_social", "nif": "cif", "email": "mail", "telefono": "tel"},
        "politica": "manual",
    }
    base.update(kw)
    fila, _ = can.registrar_adaptador(uow, **base)
    return fila


def test_un_objeto_sin_claves_de_negocio_avisa(uow: UnidadDeTrabajo) -> None:
    """Dos sistemas sin identificador compartido no se pueden casar, y cada carga
    crea duplicados."""
    _, avisos = can.definir_objeto(
        uow, clave="contacto", campos=[{"clave": "nombre"}], claves_negocio=[]
    )
    assert any("duplicados" in a for a in avisos)


def test_un_mapeo_a_un_campo_inexistente_se_rechaza(uow: UnidadDeTrabajo) -> None:
    """Un campo mal escrito no falla: deja de sincronizarse en silencio."""
    _objeto(uow)
    with pytest.raises(ErrorValidacion):
        can.registrar_adaptador(
            uow, objeto="cuenta", sistema="erp", mapeo={"nombreee": "razon_social"}
        )


def test_los_campos_sin_mapear_se_avisan(uow: UnidadDeTrabajo) -> None:
    _objeto(uow)
    _, avisos = can.registrar_adaptador(
        uow, objeto="cuenta", sistema="crm_viejo", mapeo={"nombre": "name"}
    )
    assert any("sin mapear" in a for a in avisos)


def test_reciente_sin_campo_de_modificacion_avisa(uow: UnidadDeTrabajo) -> None:
    _objeto(uow)
    _, avisos = can.registrar_adaptador(
        uow, objeto="cuenta", sistema="erp", mapeo={"nombre": "razon_social"}, politica="reciente"
    )
    assert any("última modificación" in a for a in avisos)


def test_traducir_devuelve_aparte_lo_que_no_estaba_mapeado(uow: UnidadDeTrabajo) -> None:
    """Es la lista con la que se descubre que el cliente añadió un campo nuevo."""
    _objeto(uow)
    _adaptador(uow)
    salida = can.a_canonico(
        uow.db,
        uow.tenant_id,
        objeto="cuenta",
        sistema="erp",
        externo={"razon_social": "Acme SL", "cif": "B1", "descuento_especial": "12"},
    )
    assert salida["datos"] == {"nombre": "Acme SL", "nif": "B1"}
    assert salida["sin_mapear"] == {"descuento_especial": "12"}


def test_no_se_empareja_un_externo_ya_emparejado_con_otro(uow: UnidadDeTrabajo) -> None:
    """Reasignarlo en silencio haría que dos fichas se pisaran los datos."""
    _objeto(uow)
    _adaptador(uow)
    can.emparejar(uow, objeto="cuenta", sistema="erp", registro_id=uuid4(), id_externo="E-1")
    with pytest.raises(Conflicto):
        can.emparejar(uow, objeto="cuenta", sistema="erp", registro_id=uuid4(), id_externo="E-1")


def test_un_campo_que_solo_cambio_en_un_lado_se_propaga(uow: UnidadDeTrabajo) -> None:
    """No es un conflicto: es un hueco."""
    _objeto(uow)
    _adaptador(uow)
    can.emparejar(uow, objeto="cuenta", sistema="erp", registro_id=uuid4(), id_externo="E-1")
    salida = can.conciliar(
        uow,
        objeto="cuenta",
        sistema="erp",
        id_externo="E-1",
        nuestro={"nombre": "Acme SL", "email": "a@acme.com"},
        suyo={"nombre": "Acme SL", "telefono": "600"},
    )
    assert salida["escribir_fuera"] == {"email": "a@acme.com"}
    assert salida["escribir_dentro"] == {"telefono": "600"}
    assert salida["conflictos"] == []


def test_la_politica_por_campo_manda_sobre_la_general(uow: UnidadDeTrabajo) -> None:
    """El teléfono lo manda el ERP y el correo lo manda el CRM: esa es la
    discusión de siempre."""
    _objeto(uow)
    _adaptador(uow, politica="externo", politica_por_campo={"email": "nuestro"})
    can.emparejar(uow, objeto="cuenta", sistema="erp", registro_id=uuid4(), id_externo="E-1")
    salida = can.conciliar(
        uow,
        objeto="cuenta",
        sistema="erp",
        id_externo="E-1",
        nuestro={"email": "bueno@acme.com", "telefono": "600"},
        suyo={"email": "viejo@acme.com", "telefono": "911"},
    )
    assert salida["escribir_fuera"] == {"email": "bueno@acme.com"}
    assert salida["escribir_dentro"] == {"telefono": "911"}


def test_reciente_sin_fechas_comparables_se_para(uow: UnidadDeTrabajo) -> None:
    """Aplicarlo sin fechas sería echarlo a suertes y presentarlo como regla."""
    _objeto(uow)
    _adaptador(uow, politica="reciente")
    can.emparejar(uow, objeto="cuenta", sistema="erp", registro_id=uuid4(), id_externo="E-1")
    salida = can.conciliar(
        uow,
        objeto="cuenta",
        sistema="erp",
        id_externo="E-1",
        nuestro={"email": "a@acme.com"},
        suyo={"email": "b@acme.com"},
    )
    assert salida["conflictos"][0]["politica"] == "reciente"
    assert "falta la fecha" in salida["conflictos"][0]["porque"]


def test_reciente_con_fechas_decide(uow: UnidadDeTrabajo) -> None:
    _objeto(uow)
    _adaptador(uow, politica="reciente", campo_modificado="updated_at")
    can.emparejar(uow, objeto="cuenta", sistema="erp", registro_id=uuid4(), id_externo="E-1")
    ahora = datetime.now(timezone.utc)
    salida = can.conciliar(
        uow,
        objeto="cuenta",
        sistema="erp",
        id_externo="E-1",
        nuestro={"email": "nuevo@acme.com"},
        suyo={"email": "viejo@acme.com"},
        modificado_nuestro=ahora,
        modificado_suyo=ahora - timedelta(hours=2),
    )
    assert salida["escribir_fuera"] == {"email": "nuevo@acme.com"}
    assert salida["conflictos"] == []


def test_un_conflicto_manual_para_el_vinculo(uow: UnidadDeTrabajo) -> None:
    """Seguir sincronizando lo demás dejaría el registro mitad de uno y mitad de
    otro."""
    _objeto(uow)
    _adaptador(uow)
    can.emparejar(uow, objeto="cuenta", sistema="erp", registro_id=uuid4(), id_externo="E-1")
    salida = can.conciliar(
        uow,
        objeto="cuenta",
        sistema="erp",
        id_externo="E-1",
        nuestro={"email": "a@acme.com"},
        suyo={"email": "b@acme.com"},
    )
    assert salida["en_conflicto"] is True
    vinculo = uow.db.get(can.Vinculo, UUID(salida["vinculo_id"]))
    assert vinculo is not None and vinculo.en_conflicto is True


def test_el_mismo_conflicto_se_cuenta_y_no_se_duplica(uow: UnidadDeTrabajo) -> None:
    """Uno que se repite cien veces es un conflicto, no cien."""
    _objeto(uow)
    _adaptador(uow)
    can.emparejar(uow, objeto="cuenta", sistema="erp", registro_id=uuid4(), id_externo="E-1")
    for _ in range(3):
        can.conciliar(
            uow,
            objeto="cuenta",
            sistema="erp",
            id_externo="E-1",
            nuestro={"email": "a@acme.com"},
            suyo={"email": "b@acme.com"},
        )
    salida = can.pendientes(uow.db, uow.tenant_id)
    assert salida["cuantos"] == 1
    assert salida["conflictos"][0]["intentos"] == 3


def test_resolver_dice_donde_hay_que_escribirlo(uow: UnidadDeTrabajo) -> None:
    _objeto(uow)
    _adaptador(uow)
    can.emparejar(uow, objeto="cuenta", sistema="erp", registro_id=uuid4(), id_externo="E-1")
    can.conciliar(
        uow,
        objeto="cuenta",
        sistema="erp",
        id_externo="E-1",
        nuestro={"email": "a@acme.com"},
        suyo={"email": "b@acme.com"},
    )
    pendiente = can.pendientes(uow.db, uow.tenant_id)["conflictos"][0]
    salida = can.resolver_conflicto(uow, UUID(pendiente["conflicto_id"]), gana="externo")
    assert salida["valor"] == "b@acme.com"
    assert salida["escribir_en"] == "nuestro"
    assert salida["quedan_conflictos"] == 0


def test_el_eco_se_detecta_y_no_rebota(uow: UnidadDeTrabajo) -> None:
    """Sin esto, los dos sistemas se rebotan el mismo dato para siempre."""
    _objeto(uow)
    _adaptador(uow, politica="nuestro")
    can.emparejar(uow, objeto="cuenta", sistema="erp", registro_id=uuid4(), id_externo="E-1")
    primera = can.conciliar(
        uow,
        objeto="cuenta",
        sistema="erp",
        id_externo="E-1",
        nuestro={"email": "a@acme.com"},
        suyo={"email": "b@acme.com"},
    )
    assert primera["escribir_fuera"] == {"email": "a@acme.com"}
    # Lo que nos devuelve el ERP después es lo que acabamos de escribirle.
    segunda = can.conciliar(
        uow,
        objeto="cuenta",
        sistema="erp",
        id_externo="E-1",
        nuestro={"email": "a@acme.com"},
        suyo={"email": "a@acme.com"},
    )
    assert segunda["eco"] is True
    assert segunda["escribir_fuera"] == {} and segunda["escribir_dentro"] == {}


# ── La traducción de salida, que no tenía puerta ─────────────────────────


def test_la_traduccion_de_salida_se_alcanza_por_la_api() -> None:
    """`desde_canonico` estaba escrita, probada y **sin ninguna ruta**.

    Se podía traducir lo que llegaba de fuera y no había forma de obtener la
    traducción de salida. Quien tuviera que mandar algo a ese sistema se
    escribía el mapeo otra vez por su cuenta, y entonces hay dos mapeos del
    mismo adaptador: el que se queda atrás manda datos al campo equivocado y
    eso no se descubre hasta que alguien mira el sistema de destino.
    """
    import inspect

    from services.integration import api_telemetria

    fuente = inspect.getsource(api_telemetria)
    assert "desde_canonico" in fuente, (
        "la traducción de salida no se alcanza desde ninguna ruta: el mapeo "
        "solo sirve para entrar"
    )
    assert "traducir-salida" in fuente


def test_la_salida_respeta_la_direccion_declarada_por_campo(uow: UnidadDeTrabajo) -> None:
    """Lo marcado como «solo hacia dentro» no sale, aunque esté mapeado.

    Es la mitad que distingue un mapeo de una copia: hay campos que el sistema
    externo manda y no acepta —un identificador suyo, una fecha de alta— y
    devolvérselos es cómo se pisan datos que no son nuestros.
    """
    _objeto(uow)
    can.registrar_adaptador(
        uow,
        objeto="cuenta",
        sistema="erp",
        mapeo={"nombre": "razon_social", "nif": "cif"},
        direccion_por_campo={"nif": "hacia_dentro"},
    )

    salida = can.desde_canonico(
        uow.db,
        uow.tenant_id,
        objeto="cuenta",
        sistema="erp",
        datos={"nombre": "Acme SL", "nif": "B1", "inventado": "x"},
    )

    assert salida["datos"] == {"razon_social": "Acme SL"}
    # Lo que no viaja se DICE, no se tira: un campo que no llega al destino
    # tiene que verse, porque si no parece que se mandó.
    assert salida["no_viajan"] == ["inventado", "nif"]
