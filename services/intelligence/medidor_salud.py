"""Calcular las señales de salud de una cuenta con lo que el CRM ya sabe
(CRM-05.02.01.04).

**Qué había antes.** `salud.medir()` es una calculadora completa: recibe seis
señales de 0 a 100, las pondera, reparte el peso de las que faltan y dice cuánto
quedó sin medir. Lo que no había era nadie que produjera esas seis. `POST
/ia/salud` pedía las señales ya masticadas, así que la salud de cuenta existía
como mecanismo y estaba vacía para siempre: la lista de cuentas en riesgo salía
a cero y la ficha decía «no se ha medido» desde el primer día.

**Qué se puede medir y qué no.** De las seis señales, el CRM conoce enteras la
RELACIÓN y el SOPORTE, y bastante del PATROCINADOR y del VALOR. El USO necesita
telemetría del producto y el PAGO necesita el ERP; ninguno de los dos existe
aquí. No se inventan: se dejan ausentes y la máquina reparte su peso y lo dice.
Un 50 por defecto en `uso` se leería como «regular» y significa «no lo sabemos».

**De dónde salen los datos.** De la API del propio CRM, con una credencial de
solo lectura, no de las tablas de los otros servicios. Además de respetar la
frontera, es lo que hace que la salud vea exactamente lo que ve un lector: si un
campo está enmascarado por rol, aquí tampoco entra.

**Ningún umbral está en el código.** Cuántos días son «frío», cuánto resta un SLA
incumplido, cuándo un caso está enquistado: todo sale de `Settings` y se edita
desde Admin. Qué es un cliente sano depende del negocio, y escribirlo aquí sería
la opinión de quien lo escribió aplicada a todos.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _fecha(valor: Any) -> datetime | None:
    if not valor:
        return None
    try:
        f = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return f if f.tzinfo else f.replace(tzinfo=timezone.utc)


def _acotar(valor: float) -> float:
    return max(0.0, min(100.0, valor))


def relacion(actividades: list[dict[str, Any]], s: Any) -> float | None:
    """Cómo de viva está la relación: cuándo se habló y qué se dejó a medias.

    Sin ninguna actividad **no se puntúa cero**: se devuelve `None`. Cero diría
    «relación rota» y lo que pasa es que no consta ninguna — una cuenta recién
    creada saldría en riesgo el primer día.
    """
    if not actividades:
        return None

    fechas = [f for f in (_fecha(a.get("created_at")) for a in actividades) if f]
    if not fechas:
        return None
    dias = (_ahora() - max(fechas)).days

    fresco = int(s.salud_relacion_dias_frescura)
    frio = max(fresco + 1, int(s.salud_relacion_dias_frio))
    if dias <= fresco:
        base = 100.0
    elif dias >= frio:
        base = 0.0
    else:
        base = 100.0 * (frio - dias) / (frio - fresco)

    # Lo prometido y no cumplido resta aparte: no es lo mismo no hablarse que
    # haberle dicho a alguien que se le llamaba el martes.
    ahora = _ahora()
    vencidas = sum(
        1
        for a in actividades
        if str(a.get("estado") or "") in ("pendiente", "en_curso")
        and (_fecha(a.get("vence_at")) or ahora) < ahora
    )
    return _acotar(base - vencidas * int(s.salud_relacion_penalizacion_vencida))


def soporte(casos: list[dict[str, Any]], s: Any) -> float | None:
    """Fricción acumulada: lo abierto, lo enquistado y lo prometido que se rompió.

    Sin ningún caso **son 100 y no `None`**, al revés que la relación: «ninguna
    incidencia» sí es una medida, y una buena. Lo que no se sabe es distinto de
    lo que no ha pasado.
    """
    if casos is None:
        return None

    abiertos = [c for c in casos if str(c.get("estado") or "") not in ("cerrado", "resuelto")]
    ahora = _ahora()
    enquistados = sum(
        1
        for c in abiertos
        if (ahora - (_fecha(c.get("created_at")) or ahora)).days
        >= int(s.salud_soporte_dias_enquistado)
    )
    incumplidos = sum(
        1
        for c in casos
        if c.get("incumplio_primera_respuesta")
        or (
            (_fecha(c.get("vence_resolucion_at")) or ahora) < ahora
            and not _fecha(c.get("resuelto_at"))
        )
    )
    castigo = (
        len(abiertos) * int(s.salud_soporte_penalizacion_caso)
        # El enquistado cuenta doble: se le suma otra vez.
        + enquistados * int(s.salud_soporte_penalizacion_caso)
        + incumplidos * int(s.salud_soporte_penalizacion_sla)
    )
    return _acotar(100.0 - castigo)


def patrocinador(contactos: list[dict[str, Any]]) -> float | None:
    """Si sigue estando quien decide.

    Que se vaya el patrocinador es la señal de fuga que más se adelanta y la que
    casi nadie mira. Tres respuestas y no dos: hay decisor, hay gente pero
    ninguno marcado como tal, o no hay nadie —y esto último no es cero, es que no
    se sabe nada de esta cuenta—.
    """
    if not contactos:
        return None
    vivos = [c for c in contactos if not c.get("baja") and not c.get("deleted_at")]
    if not vivos:
        return 0.0
    decisores = [
        c
        for c in vivos
        if str(c.get("rol") or c.get("rol_compra") or "").lower()
        in ("decisor", "patrocinador", "firmante")
    ]
    return 100.0 if decisores else 50.0


def valor(contratos: list[dict[str, Any]], s: Any) -> float | None:
    """Negocio vivo y con continuidad, o contrato que se acaba sin ruido.

    Un contrato que vence dentro de poco, sin renovación automática y sin
    preaviso dado, es riesgo CON FECHA: lo más accionable que tiene una cartera.
    """
    if not contratos:
        return None
    vivos = [c for c in contratos if str(c.get("estado") or "") in ("vigente", "activo", "firmado")]
    if not vivos:
        return 0.0

    ahora = _ahora()
    dias_aviso = int(s.salud_valor_dias_preaviso)
    en_riesgo = sum(
        1
        for c in vivos
        if (fin := _fecha(c.get("fin")))
        and (fin - ahora).days <= dias_aviso
        and not c.get("renovacion_automatica")
        and not c.get("preaviso_dado")
    )
    return _acotar(100.0 - en_riesgo * int(s.salud_valor_penalizacion_vencimiento))


def senales_de(datos: dict[str, list[dict[str, Any]]], s: Any) -> dict[str, float]:
    """Las señales que se pueden calcular, sin las que no.

    Se omiten las que salen `None` en vez de mandarlas a cero: la calculadora
    reparte el peso de las ausentes entre las presentes y avisa de cuánto quedó
    sin medir, que es exactamente lo que hay que decir.
    """
    crudas = {
        "relacion": relacion(datos.get("actividades") or [], s),
        "soporte": soporte(datos.get("casos") or [], s),
        "patrocinador": patrocinador(datos.get("contactos") or []),
        "valor": valor(datos.get("contratos") or [], s),
    }
    return {k: round(v, 2) for k, v in crudas.items() if v is not None}


def pesos_de(s: Any) -> dict[str, int]:
    """Los pesos configurados. Ninguno vive en el código."""
    return {
        "uso": int(s.salud_peso_uso),
        "soporte": int(s.salud_peso_soporte),
        "relacion": int(s.salud_peso_relacion),
        "pago": int(s.salud_peso_pago),
        "valor": int(s.salud_peso_valor),
        "patrocinador": int(s.salud_peso_patrocinador),
    }


def umbrales_de(s: Any) -> dict[str, int]:
    return {
        "sana": int(s.salud_umbral_sana),
        "vigilar": int(s.salud_umbral_vigilar),
        "riesgo": int(s.salud_umbral_riesgo),
    }


def leer_del_crm(cli: Any, base: str, clave: str, cuenta_id: UUID) -> dict[str, list[dict]]:
    """Lo que hace falta de esa cuenta, por la API y con permisos de lector."""
    cabeceras = {"Authorization": f"Bearer {clave}"}
    salida: dict[str, list[dict]] = {}
    for nombre, ruta in (
        ("actividades", "/activities"),
        ("casos", "/casos"),
        ("contactos", "/contacts"),
        ("contratos", "/contratos"),
    ):
        r = cli.get(f"{base}{ruta}?cuenta_id={cuenta_id}&limite=200", headers=cabeceras)
        if r.status_code != 200:
            # Una parte que no contesta se deja AUSENTE, no a cero: su peso se
            # reparte y la respuesta dirá que faltó. Hundir la cuenta porque un
            # servicio estaba reiniciando sería el peor falso positivo.
            logger.warning("salud.origen_no_responde", parte=nombre, codigo_http=r.status_code)
            continue
        cuerpo = r.json()
        filas = cuerpo.get("items") if isinstance(cuerpo, dict) else cuerpo
        salida[nombre] = filas if isinstance(filas, list) else []
    return salida
