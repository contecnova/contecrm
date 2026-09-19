"""Localización por tenant: formatos, husos y moneda (CRM-00.01.04.07).

Lo que defienden estas pruebas es una sola cosa, dicha de varias maneras: una
preferencia **guardada y no aplicada** es peor que no tenerla. El cliente la
configura, la ve guardada, y el sistema sigue enseñando lo mismo de antes. Nadie
lo llama avería porque no hay error: simplemente no pasa nada.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from crmcore import i18n

# 23:30 UTC del 18. En media Europa ya es el día 19, así que este instante
# distingue «se está aplicando el huso» de «se está recortando la cadena».
MUESTRA = datetime(2026, 9, 18, 23, 30, tzinfo=timezone.utc)


def _es() -> i18n.Localizacion:
    return i18n.Localizacion(
        idioma="es", zona="Europe/Madrid", formato_fecha="dd/mm/aaaa", moneda="EUR"
    )


def _en() -> i18n.Localizacion:
    return i18n.Localizacion(
        idioma="en", zona="America/New_York", formato_fecha="mm/dd/aaaa", moneda="USD"
    )


# ── Husos ─────────────────────────────────────────────────────────────────


def test_la_fecha_se_calcula_en_la_zona_y_no_recortando_la_cadena() -> None:
    """El error clásico: un instante UTC de las 23:30 del 18 es el 19 en Madrid
    y el 18 en Nueva York. Recortar la cadena antes de convertir lo fecharía mal
    en un vencimiento de SLA o en una fecha de cierre."""
    assert _es().fecha(MUESTRA) == "19/09/2026"
    assert _en().fecha(MUESTRA) == "09/18/2026"


def test_la_hora_se_convierte_a_la_zona_del_tenant() -> None:
    assert _es().fecha_hora(MUESTRA) == "19/09/2026 01:30"
    assert _en().fecha_hora(MUESTRA) == "09/18/2026 19:30"


def test_un_instante_sin_zona_se_trata_como_utc_y_no_como_hora_del_servidor() -> None:
    """Todo lo que esta base guarda es UTC. Asumir la hora del servidor haría
    que el mismo dato se viera distinto según qué réplica atienda la petición,
    que es de los fallos más difíciles de creer cuando se reporta."""
    ingenuo = datetime(2026, 9, 18, 23, 30)
    assert _es().fecha_hora(ingenuo) == _es().fecha_hora(MUESTRA)


def test_una_zona_invalida_cae_a_utc_en_vez_de_reventar() -> None:
    """Un ajuste mal escrito por un administrador no puede impedir que salga un
    correo. Se avisa en el log, que es lo que permite corregirlo."""
    loc = i18n.Localizacion(zona="Europa/Madriz")
    assert str(loc.zona) == "UTC"
    assert loc.fecha_hora(MUESTRA) == "18/09/2026 23:30"


def test_una_fecha_sin_hora_no_se_desplaza() -> None:
    """Una `date` no tiene instante: convertirla de zona la movería un día sin
    que nadie lo hubiera pedido."""
    assert _en().fecha(date(2026, 9, 18)) == "09/18/2026"


def test_lo_vacio_se_queda_vacio() -> None:
    """«01/01/1970» donde no hay fecha es peor que un hueco: parece un dato."""
    assert _es().fecha(None) == ""
    assert _es().fecha_hora(None) == ""
    assert _es().numero(None) == ""
    assert _es().importe(None) == ""


# ── Números e importes ────────────────────────────────────────────────────


def test_los_separadores_cambian_con_el_idioma() -> None:
    assert _es().numero(Decimal("1234567.5")) == "1.234.567,50"
    assert _en().numero(Decimal("1234567.5")) == "1,234,567.50"


def test_ningun_separador_se_sustituye_dos_veces() -> None:
    """Sustituir comas por puntos y puntos por comas sobre el mismo texto deja
    todos los separadores iguales. Con este número se ve enseguida."""
    assert _es().numero(Decimal("1000.01")) == "1.000,01"
    assert _en().numero(Decimal("1000.01")) == "1,000.01"


def test_el_simbolo_va_donde_lo_espera_cada_idioma() -> None:
    """«$1,234.50» y «1.234,50 €» los lee bien cada uno; el cruzado lo lee mal
    alguno de los dos."""
    assert _es().importe(Decimal("1234.5")) == "1.234,50 €"
    assert _en().importe(Decimal("1234.5")) == "$1,234.50"


def test_una_moneda_sin_simbolo_se_escribe_con_su_codigo() -> None:
    """«1.234,50 CLP» se entiende. Un símbolo inventado, no."""
    assert _es().importe(Decimal("1234.5"), "CLP") == "1.234,50 CLP"


def test_un_valor_que_no_es_numero_se_devuelve_tal_cual() -> None:
    """Formatear no puede perder un dato: si no se sabe tratar, se enseña."""
    assert _es().numero("no soy un número") == "no soy un número"


# ── Calendario ────────────────────────────────────────────────────────────


def test_la_semana_empieza_donde_diga_el_tenant() -> None:
    """Una vista semanal que siempre empieza en lunes descoloca todas las
    columnas a un tenant estadounidense."""
    assert i18n.Localizacion(primer_dia=0).dias_de_la_semana()[0] == 0
    assert i18n.Localizacion(primer_dia=6).dias_de_la_semana() == [6, 0, 1, 2, 3, 4, 5]


# ── Aplicación: las plantillas ────────────────────────────────────────────


def test_formatear_valores_entra_en_las_estructuras_anidadas() -> None:
    """Los datos de una plantilla llegan como `{"oportunidad": {...}}`, así que
    formatear solo el primer nivel dejaría sin tocar justo lo que se escribe."""
    datos = {
        "oportunidad": {"importe": Decimal("15000"), "cierre": date(2026, 12, 31)},
        "lineas": [{"total": Decimal("1234.5")}],
        "creada": MUESTRA,
        "nombre": "ACME",
    }
    salida = i18n.formatear_valores(datos, _es())

    assert salida["oportunidad"]["importe"] == "15.000,00"
    assert salida["oportunidad"]["cierre"] == "31/12/2026"
    assert salida["lineas"][0]["total"] == "1.234,50"
    assert salida["creada"] == "19/09/2026 01:30"
    assert salida["nombre"] == "ACME"


@pytest.mark.db
def test_una_plantilla_enviada_lleva_las_fechas_del_tenant(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es «aplicarlo en los envíos».

    Sin esto, el correo enseña `2026-09-18 23:30:00+00:00` en mitad de una
    frase, que es la forma más rápida de que un cliente deje de confiar en los
    avisos automáticos.
    """
    from crmcore.runtime import settings as rt

    from services.tenancy.catalogos import Plantilla, render

    rt.fijar(db, "zona_horaria", "Europe/Madrid", ambito="tenant", ambito_id=str(tenant_id))
    rt.fijar(db, "formato_fecha", "dd/mm/aaaa", ambito="tenant", ambito_id=str(tenant_id))
    db.flush()

    plantilla = Plantilla(
        tenant_id=tenant_id,
        clave="aviso",
        idioma="es",
        tipo="correo",
        nombre="Aviso",
        asunto="Cita el {{cuando}}",
        cuerpo="Importe: {{importe}}",
    )
    db.add(plantilla)
    db.flush()

    asunto, cuerpo = render(plantilla, {"cuando": MUESTRA, "importe": Decimal("1234.5")}, db=db)
    assert asunto == "Cita el 19/09/2026 01:30"
    assert cuerpo == "Importe: 1.234,50"


@pytest.mark.db
def test_el_idioma_de_la_plantilla_manda_sobre_el_del_contexto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Quien eligió la plantilla en inglés quiere los números en inglés, aunque
    el tenant sea español: la plantilla es la que sabe a quién se dirige."""
    from services.tenancy.catalogos import Plantilla, render

    plantilla = Plantilla(
        tenant_id=tenant_id,
        clave="aviso-en",
        idioma="en",
        tipo="correo",
        nombre="Notice",
        asunto="",
        cuerpo="Total: {{importe}}",
    )
    db.add(plantilla)
    db.flush()

    _asunto, cuerpo = render(plantilla, {"importe": Decimal("1234.5")}, db=db)
    assert cuerpo == "Total: 1,234.50"


# ── Aplicación: el contrato para los frontends ────────────────────────────


@pytest.mark.db
def test_la_resolucion_atraviesa_la_jerarquia_de_ajustes(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Lo que fije el tenant gana sobre lo del despliegue. Sin esto, la
    jerarquía existiría en la tabla y no en la pantalla."""
    from crmcore.runtime import settings as rt

    rt.fijar(db, "idioma", "en", ambito="tenant", ambito_id=str(tenant_id))
    rt.fijar(db, "zona_horaria", "America/New_York", ambito="tenant", ambito_id=str(tenant_id))
    rt.fijar(db, "formato_fecha", "mm/dd/aaaa", ambito="tenant", ambito_id=str(tenant_id))
    db.flush()

    loc = i18n.resolver(db)
    assert loc.idioma == "en"
    assert loc.fecha_hora(MUESTRA) == "09/18/2026 19:30"


@pytest.mark.db
def test_los_ejemplos_que_publica_la_api_coinciden_con_lo_que_formatea(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Los ejemplos del endpoint son el contrato, no decoración: un frontend
    comprueba con ellos que su formateo coincide con el del servidor sin
    reimplementar la jerarquía de ajustes. Si divergen, dejan de servir."""
    from services.tenancy.api_catalogos import localizacion

    loc = i18n.resolver(db)
    respuesta = localizacion(db, None)  # type: ignore[arg-type]

    assert respuesta["ejemplos"]["fecha"] == loc.fecha(MUESTRA)
    assert respuesta["ejemplos"]["fecha_hora"] == loc.fecha_hora(MUESTRA)
    assert respuesta["ejemplos"]["importe"] == loc.importe(Decimal("1234567.5"))
    assert respuesta["zona_horaria"] == str(loc.zona)


# ── Replicación entre servicios ───────────────────────────────────────────


@pytest.mark.db
def test_fijar_un_ajuste_emite_el_evento_que_lo_replica(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin este evento, un ajuste escrito desde la consola vive solo en el
    esquema de `tenancy`.

    La tabla `ajustes_runtime` está en el esquema de CADA servicio y ninguno lee
    el de otro. Antes de esto, `party` seguía formateando con el valor de `.env`
    para siempre mientras el administrador veía su cambio guardado. Y el
    comentario del código decía que las réplicas se enteraban «por el evento
    `ajuste.cambiado`», que **no lo emitía nadie**: solo existía como acción de
    auditoría con ese nombre.
    """
    from crmcore.bus.modelos import EventoSaliente
    from crmcore.runtime import settings as rt
    from sqlalchemy import select

    rt.fijar(db, "idioma", "pt", ambito="tenant", ambito_id=str(tenant_id))
    db.flush()

    salientes = (
        db.execute(select(EventoSaliente).where(EventoSaliente.tipo == rt.AJUSTE_CAMBIADO))
        .scalars()
        .all()
    )
    assert len(salientes) == 1
    assert salientes[0].sobre["data"] == {
        "clave": "idioma",
        "ambito": "tenant",
        "ambito_id": str(tenant_id),
        "valor": "pt",
        "quitado": False,
    }
    # Va en la MISMA transacción que la escritura: o se guarda el ajuste y sale
    # el evento, o no pasa ninguna de las dos cosas.
    assert salientes[0].tenant_id == tenant_id


@pytest.mark.db
def test_consumir_el_evento_aplica_el_valor_en_este_servicio(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es el otro extremo: lo que hace cada servicio al recibirlo."""
    import asyncio

    from crmcore.runtime import settings as rt

    asyncio.run(
        rt.consumir_ajuste(
            {
                "data": {
                    "clave": "formato_fecha",
                    "ambito": "tenant",
                    "ambito_id": str(tenant_id),
                    "valor": "aaaa-mm-dd",
                    "quitado": False,
                }
            }
        )
    )
    # El 18 y no el 19: solo se ha replicado el FORMATO, no el huso, así que la
    # fecha sigue calculándose en UTC. Comprobarlo así aísla lo que se replica.
    assert i18n.resolver(db).fecha(MUESTRA) == "2026-09-18"


@pytest.mark.db
def test_consumirlo_dos_veces_deja_el_mismo_estado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La entrega es at-least-once: recibir el mismo evento dos veces tiene que
    ser inocuo, o cada reintento del bus corrompería la configuración."""
    import asyncio

    from crmcore.runtime import settings as rt
    from sqlalchemy import func, select

    mensaje = {
        "data": {
            "clave": "idioma",
            "ambito": "tenant",
            "ambito_id": str(tenant_id),
            "valor": "fr",
            "quitado": False,
        }
    }
    asyncio.run(rt.consumir_ajuste(mensaje))
    asyncio.run(rt.consumir_ajuste(mensaje))

    filas = db.execute(
        select(func.count()).select_from(rt.AjusteRuntime).where(rt.AjusteRuntime.clave == "idioma")
    ).scalar_one()
    assert filas == 1
    assert i18n.resolver(db).idioma == "fr"


@pytest.mark.db
def test_aplicar_un_ajuste_recibido_no_vuelve_a_emitirlo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si el consumidor llamara a `fijar`, cada servicio reemitiría el evento al
    aplicarlo y el bus entraría en un bucle que crece con el número de
    servicios."""
    import asyncio

    from crmcore.bus.modelos import EventoSaliente
    from crmcore.runtime import settings as rt
    from sqlalchemy import func, select

    asyncio.run(
        rt.consumir_ajuste(
            {
                "data": {
                    "clave": "idioma",
                    "ambito": "tenant",
                    "ambito_id": str(tenant_id),
                    "valor": "de",
                    "quitado": False,
                }
            }
        )
    )
    emitidos = db.execute(
        select(func.count())
        .select_from(EventoSaliente)
        .where(EventoSaliente.tipo == rt.AJUSTE_CAMBIADO)
    ).scalar_one()
    assert emitidos == 0


@pytest.mark.db
def test_una_clave_que_este_servicio_no_conoce_se_ignora_sin_ruido(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una versión más nueva puede declarar ajustes que esta no tiene. Fallar
    llenaría la cola de fallidos con mensajes correctos."""
    import asyncio

    from crmcore.runtime import settings as rt

    asyncio.run(
        rt.consumir_ajuste({"data": {"clave": "ajuste_del_futuro", "ambito": "tenant", "valor": 1}})
    )
