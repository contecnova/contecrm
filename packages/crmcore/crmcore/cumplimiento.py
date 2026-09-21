"""RAT, mapa de datos personales e informes de cumplimiento
(CRM-07.03.01.04, CRM-07.03.01.07).

El registro de actividades de tratamiento que exige el RGPD se hace casi siempre
en una hoja de cálculo, a mano, y describe el sistema que alguien recordaba el
día que lo escribió. A los seis meses describe otro sistema.

Aquí sale del **propio modelo**: cada columna declara su sensibilidad, cada
servicio sabe qué objetos tiene, y de ahí se compone el mapa de datos personales
sin que nadie lo transcriba. Lo que no se puede derivar —la finalidad, la base
legal, el plazo— sí se declara, porque son decisiones y no datos técnicos; pero
se declara **junto al objeto**, no en un documento aparte que se queda viejo.

La diferencia práctica: cuando alguien añade un campo con datos personales, el
mapa lo recoge solo. Con la hoja de cálculo, ese campo no existe para el RAT
hasta que alguien se acuerda — y nadie se acuerda.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Sensibilidades que cuentan como dato personal a efectos del RAT. `especial`
# son las categorías del artículo 9 —salud, biometría, convicciones— y se
# separan porque su régimen legal es distinto: no basta el interés legítimo.
PERSONALES = frozenset({"personal", "especial"})


@dataclass(frozen=True, slots=True)
class Tratamiento:
    """Una actividad de tratamiento declarada sobre un objeto.

    Lo que no se puede derivar del código y hay que decidir: para qué se tratan
    los datos, con qué base legal, cuánto se guardan y quién los recibe. Va
    **junto al objeto** y no en un documento aparte, que es lo que hace que se
    actualice cuando el objeto cambia.
    """

    objeto: str
    finalidad: str
    base_legal: str
    plazo: str
    # Quién más los ve: encargados, subencargados, destinatarios.
    destinatarios: tuple[str, ...] = ()
    # Fuera del EEE, si los hay, con la garantía que lo ampara.
    transferencias: tuple[str, ...] = ()
    responsable: str = ""


_tratamientos: dict[str, Tratamiento] = {}


def declarar(tratamiento: Tratamiento) -> None:
    """Declara la actividad de tratamiento de un objeto.

    Lo llama cada servicio al importarse, junto a sus modelos. Así el RAT vive
    en el mismo sitio que el objeto y se cambia con él; en un documento aparte,
    lo que se actualiza es el objeto y lo que se queda viejo es el documento.
    """
    _tratamientos[tratamiento.objeto] = tratamiento


@dataclass
class CampoPersonal:
    objeto: str
    campo: str
    sensibilidad: str
    cifrado: bool = False


def mapa_de_datos(modelos: dict[str, type]) -> list[CampoPersonal]:
    """Los campos con datos personales, leídos del modelo.

    Del modelo y no de una lista: una lista se queda desfasada al primer campo
    nuevo, y ese campo no existiría para el RAT hasta que alguien se acordara —
    y nadie se acuerda.
    """
    salida: list[CampoPersonal] = []
    for objeto, modelo in modelos.items():
        tabla = getattr(modelo, "__table__", None)
        if tabla is None:
            continue
        for columna in tabla.columns:
            info = columna.info or {}
            sensibilidad = str(info.get("sensibilidad", ""))
            if sensibilidad in PERSONALES:
                salida.append(
                    CampoPersonal(
                        objeto=objeto,
                        campo=columna.name,
                        sensibilidad=sensibilidad,
                        cifrado=bool(info.get("cifrado")),
                    )
                )
    return sorted(salida, key=lambda c: (c.objeto, c.campo))


def registro_de_tratamiento(modelos: dict[str, type]) -> dict[str, Any]:
    """El RAT compuesto: lo derivado del modelo y lo declarado a mano.

    **Lo que falta se dice**, y es la parte que hace que esto valga para algo:
    un objeto con campos personales y sin tratamiento declarado sale en la lista
    de huecos. Un RAT que presenta como completo lo que no lo está es peor que
    no tenerlo, porque nadie vuelve a mirarlo.
    """
    campos = mapa_de_datos(modelos)
    por_objeto: dict[str, list[CampoPersonal]] = {}
    for campo in campos:
        por_objeto.setdefault(campo.objeto, []).append(campo)

    actividades = []
    sin_declarar = []
    for objeto, suyos in sorted(por_objeto.items()):
        tratamiento = _tratamientos.get(objeto)
        if tratamiento is None:
            sin_declarar.append(objeto)
            continue
        actividades.append(
            {
                "objeto": objeto,
                "finalidad": tratamiento.finalidad,
                "base_legal": tratamiento.base_legal,
                "plazo": tratamiento.plazo,
                "responsable": tratamiento.responsable,
                "destinatarios": list(tratamiento.destinatarios),
                "transferencias": list(tratamiento.transferencias),
                "categorias": sorted({c.sensibilidad for c in suyos}),
                "campos": [
                    {"campo": c.campo, "sensibilidad": c.sensibilidad, "cifrado": c.cifrado}
                    for c in suyos
                ],
                # Las categorías especiales se señalan aparte: su régimen legal
                # es distinto y un RAT que las mezcla con el resto esconde
                # exactamente lo que un auditor va a mirar primero.
                "categorias_especiales": any(c.sensibilidad == "especial" for c in suyos),
            }
        )

    # Y al revés: tratamientos declarados sobre objetos que ya no tienen datos
    # personales. Suele significar que el objeto cambió y el RAT no.
    huerfanos = sorted(set(_tratamientos) - set(por_objeto))

    return {
        "generado_at": datetime.now(timezone.utc).isoformat(),
        "actividades": actividades,
        "campos_personales": len(campos),
        "objetos_sin_tratamiento_declarado": sin_declarar,
        "tratamientos_sobre_objetos_sin_datos_personales": huerfanos,
        "completo": not sin_declarar and not huerfanos,
    }


def informe_de_cumplimiento(db: Any, tenant_id: UUID, modelos: dict[str, type]) -> dict[str, Any]:
    """Lo que un auditor pide, junto y sin tener que pedirlo (CRM-07.03.01.07).

    Se compone de lo que ya existe —GRC, audit trail, certificados, políticas—
    en vez de mantener un informe aparte. Un informe que se rellena a mano dice
    lo que alguien quería que dijera; este dice lo que hay.

    Cuando una parte no se puede leer **se dice**, en vez de omitirla: un
    apartado ausente se lee como «no aplica», y la diferencia entre eso y «no se
    ha podido comprobar» es justo la que importa en una auditoría.
    """
    informe: dict[str, Any] = {
        "generado_at": datetime.now(timezone.utc).isoformat(),
        "tenant": str(tenant_id),
        "rat": registro_de_tratamiento(modelos),
        "avisos": [],
    }

    partes: dict[str, Any] = {}
    for nombre, fn in sorted(_APARTADOS.items()):
        try:
            partes[nombre] = fn(db, tenant_id)
        except Exception as exc:  # noqa: BLE001 — un apartado ilegible se dice
            partes[nombre] = {"medible": False, "motivo": str(exc)[:200]}
            informe["avisos"].append(f"No se ha podido componer «{nombre}»")
    informe.update(partes)
    if not informe["rat"]["completo"]:
        informe["avisos"].append(
            "El registro de tratamiento tiene huecos: hay objetos con datos "
            "personales sin actividad declarada"
        )
    return informe


# ── Apartados ─────────────────────────────────────────────────────────────

# El informe se compone de apartados registrados, no de una lista escrita aquí.
# El motivo no es elegancia: los dos apartados que más pesan —cobertura de
# controles y certificados de destrucción— viven en `tenancy`, y que el núcleo
# los importara pondría al núcleo a depender de un servicio. Eso rompe la regla
# que sostiene el despliegue independiente, y el gate de arquitectura lo caza.
# Invertido, cada servicio aporta lo suyo y el núcleo no conoce a ninguno.
_APARTADOS: dict[str, Any] = {}


def registrar_apartado(nombre: str, fn: Any) -> None:
    """Da de alta un apartado del informe. `fn(db, tenant_id) -> dict`."""
    _APARTADOS[nombre] = fn


def apartados() -> list[str]:
    return sorted(_APARTADOS)


def _auditoria(db: Any, tenant_id: UUID) -> dict[str, Any]:
    from crmcore.audit import verificar

    return {"verificacion": verificar(db, tenant_id)}


def _politicas(db: Any, tenant_id: UUID) -> dict[str, Any]:
    from crmcore.authz.politicas import cargar

    activas = cargar(db, tenant_id)
    return {"activas": len(activas), "nombres": sorted(p.nombre for p in activas)}


registrar_apartado("integridad_del_audit_trail", _auditoria)
registrar_apartado("politicas_de_acceso", _politicas)


def limpiar_tratamientos() -> None:
    """Vacía lo declarado. Para las pruebas."""
    _tratamientos.clear()
