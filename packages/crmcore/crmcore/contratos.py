"""Contract testing interno, dirigido por el consumidor (CRM-00.03.01.03).

Reutiliza la idea de `contecpos:packages/contracts` (buf), traducida a lo que
aquí une de verdad a los servicios: **el evento**. Entre servicios no hay
llamadas directas ni lecturas cruzadas de base —eso lo impide el gate de
arquitectura—, así que el único contrato que puede romperse en silencio es el
sobre de un evento.

**Por qué dirigido por el consumidor.** El catálogo de eventos
(`crmcore.events.catalogo`) ya dice lo que cada productor *declara* publicar.
Eso no basta: el productor no sabe qué campos lee cada consumidor, así que puede
quitar uno creyendo que no lo usa nadie. El daño no se ve al desplegar —el
productor sigue verde— sino en el consumidor, días después, y cuando aparece no
se relaciona con el cambio. Aquí cada consumidor declara **qué campos necesita y
para qué**, y eso convierte «creo que nadie usa ese campo» en una comprobación.

Se verifican tres cosas, y cada una tapa un agujero distinto:

1. **Estático (`verificar`)**: para cada consumo declarado, que el evento tenga
   productor, que el productor declare todos los campos que el consumo pide y
   que la versión alcance. Corre en el preflight, así que rompe antes de salir.
2. **En ejecución (`comprobar_emision`)**: que lo que se publica de verdad lleve
   los campos declarados. Sin esto, un productor puede declarar un campo en el
   catálogo y no ponerlo nunca en `data`; el estático lo daría por bueno porque
   ambos lados declaran lo mismo — y lo que ambos declaran es mentira.
3. **Observado (`campos_observados`)**: los campos que se han visto salir de
   verdad durante las pruebas. Es lo que permite decir qué parte del contrato
   está *comprobada* y no solo escrita, sin aparentar que todo lo está.

Lo que **no** hace: inventar el contrato leyendo el código. Un contrato deducido
es una foto de lo que hay, no un acuerdo, y no sirve para impedir el cambio que
lo rompe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from crmcore.events import catalogo


@dataclass(frozen=True, slots=True)
class Consumo:
    """Lo que un servicio necesita de un evento ajeno."""

    consumidor: str
    evento: str
    # Campos de `data` de los que depende el consumidor. Solo los que LEE: meter
    # de más convierte el contrato en una copia del productor y deja de servir
    # para decidir qué se puede quitar.
    campos: tuple[str, ...] = ()
    # Para qué los usa. Va aquí y no en un comentario porque es lo que lee quien
    # se plantea quitar un campo, y es lo único que le dice si puede.
    motivo: str = ""
    version_minima: int = 1
    # Un consumo opcional no rompe si falta: el consumidor sabe seguir sin él.
    # Marcarlo es lo que permite añadir campos nuevos sin coordinar despliegues.
    obligatorio: bool = True


@dataclass(frozen=True, slots=True)
class Incumplimiento:
    """Una promesa que no se sostiene, con quién la hizo y a quién afecta."""

    clase: str
    evento: str
    consumidor: str
    detalle: str
    campos: tuple[str, ...] = ()

    def __str__(self) -> str:  # pragma: no cover - formato
        return f"[{self.clase}] {self.evento} → {self.consumidor}: {self.detalle}"


_CONSUMOS: list[Consumo] = []
# Campos que se han visto salir de verdad, por evento. Se llena desde
# `comprobar_emision`, así que durante la suite de pruebas queda la huella real.
_OBSERVADOS: dict[str, set[str]] = {}


def declarar_consumo(consumo: Consumo) -> Consumo:
    """Declara el consumo. Repetirlo exactamente igual no lo duplica: los
    módulos que lo declaran se importan desde varios sitios, y un contrato
    contado dos veces inflaría la cobertura sin añadir ninguna garantía."""
    if consumo not in _CONSUMOS:
        _CONSUMOS.append(consumo)
    return consumo


def consumos() -> list[Consumo]:
    return sorted(_CONSUMOS, key=lambda c: (c.evento, c.consumidor))


def consumidores_de(evento: str) -> list[Consumo]:
    return [c for c in _CONSUMOS if c.evento == evento]


def limpiar() -> None:
    """Deja el registro como estaba. Solo pruebas."""
    _CONSUMOS.clear()
    _OBSERVADOS.clear()


# ── 1. Verificación estática ──────────────────────────────────────────────


def verificar() -> list[Incumplimiento]:
    """Contrasta cada consumo declarado con lo que su productor promete."""
    fallos: list[Incumplimiento] = []
    for consumo in consumos():
        tipo = catalogo.obtener(consumo.evento)
        if tipo is None:
            fallos.append(
                Incumplimiento(
                    clase="evento_sin_productor",
                    evento=consumo.evento,
                    consumidor=consumo.consumidor,
                    detalle=(
                        "Nadie declara publicar este evento. O el consumidor "
                        "espera algo que ya no existe, o el productor lo emite "
                        "sin declararlo, y entonces no hay contrato que romper "
                        "porque no hay contrato."
                    ),
                )
            )
            continue

        if tipo.productor == consumo.consumidor:
            fallos.append(
                Incumplimiento(
                    clase="consumo_de_si_mismo",
                    evento=consumo.evento,
                    consumidor=consumo.consumidor,
                    detalle=(
                        "Un servicio no necesita un contrato consigo mismo: "
                        "declararlo infla la cobertura sin protegerse de nada."
                    ),
                )
            )
            continue

        faltan = tuple(c for c in consumo.campos if c not in tipo.campos)
        if faltan and consumo.obligatorio:
            fallos.append(
                Incumplimiento(
                    clase="campo_no_publicado",
                    evento=consumo.evento,
                    consumidor=consumo.consumidor,
                    campos=faltan,
                    detalle=(
                        f"«{tipo.productor}» no publica {', '.join(faltan)}, y "
                        f"«{consumo.consumidor}» lo necesita para: "
                        f"{consumo.motivo or 'sin motivo declarado'}."
                    ),
                )
            )

        if consumo.version_minima > tipo.version:
            fallos.append(
                Incumplimiento(
                    clase="version_insuficiente",
                    evento=consumo.evento,
                    consumidor=consumo.consumidor,
                    detalle=(
                        f"El consumidor pide v{consumo.version_minima} y el "
                        f"productor publica v{tipo.version}."
                    ),
                )
            )
    return fallos


def contratos_sin_consumidor() -> list[str]:
    """Eventos internos que nadie consume.

    No es un fallo: puede ser un evento nuevo cuyo consumidor está por llegar, o
    un gancho para integradores. Se saca aparte para que se vea, porque un
    evento que no consume nadie y no sale a webhooks es código que se mantiene
    sin que nadie lo necesite.
    """
    consumidos = {c.evento for c in _CONSUMOS}
    return sorted(t.tipo for t in catalogo.todos() if not t.publico and t.tipo not in consumidos)


# ── 2. Verificación en ejecución ──────────────────────────────────────────


def comprobar_emision(tipo: str, data: dict[str, Any]) -> list[str]:
    """Campos que el contrato promete y la emisión no trae.

    Devuelve la lista en vez de lanzar porque quien llama decide qué hacer: el
    productor la convierte en error, y la anotación de observados se hace
    igualmente para que la huella no dependa de que todo esté bien.
    """
    declarado = catalogo.obtener(tipo)
    if declarado is None:
        return []

    presentes = {k for k, v in (data or {}).items() if v is not None}
    _OBSERVADOS.setdefault(tipo, set()).update(presentes)

    exigidos = set(declarado.campos)
    for consumo in consumidores_de(tipo):
        if consumo.obligatorio:
            exigidos.update(consumo.campos)
    return sorted(exigidos - presentes)


def campos_observados(tipo: str) -> set[str]:
    return set(_OBSERVADOS.get(tipo, set()))


# ── 3. Cobertura ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class Cobertura:
    """Cuánto del contrato se ha visto cumplirse, no cuánto está escrito."""

    eventos: int = 0
    eventos_observados: int = 0
    campos_prometidos: int = 0
    campos_observados: int = 0
    sin_observar: list[str] = field(default_factory=list)

    @property
    def porcentaje(self) -> float:
        if not self.campos_prometidos:
            return 0.0
        return round(100 * self.campos_observados / self.campos_prometidos, 1)


def cobertura() -> Cobertura:
    """Qué parte del contrato se ha comprobado de verdad.

    Se mide sobre los campos que los consumidores declaran necesitar, no sobre
    todos los del catálogo: lo que importa es si se ha visto llegar lo que
    alguien espera. Un 100 % de campos declarados sin una sola emisión observada
    sería un informe que dice que todo va bien sin haber mirado.
    """
    salida = Cobertura()
    por_evento: dict[str, set[str]] = {}
    for consumo in consumos():
        if consumo.obligatorio:
            por_evento.setdefault(consumo.evento, set()).update(consumo.campos)

    for evento, campos in sorted(por_evento.items()):
        salida.eventos += 1
        vistos = campos_observados(evento)
        if vistos:
            salida.eventos_observados += 1
        salida.campos_prometidos += len(campos)
        salida.campos_observados += len(campos & vistos)
        faltan = sorted(campos - vistos)
        if faltan:
            salida.sin_observar.append(f"{evento}: {', '.join(faltan)}")
    return salida


def informe() -> dict[str, Any]:
    """Lo que se enseña: lo verificado, lo incumplido y lo no comprobado."""
    fallos = verificar()
    cob = cobertura()
    return {
        "consumos_declarados": len(_CONSUMOS),
        "incumplimientos": [
            {
                "clase": f.clase,
                "evento": f.evento,
                "consumidor": f.consumidor,
                "campos": list(f.campos),
                "detalle": f.detalle,
            }
            for f in fallos
        ],
        "cobertura_pct": cob.porcentaje,
        "campos_prometidos": cob.campos_prometidos,
        "campos_observados": cob.campos_observados,
        "sin_observar": cob.sin_observar,
        "eventos_internos_sin_consumidor": contratos_sin_consumidor(),
        "en_verde": not fallos,
    }
