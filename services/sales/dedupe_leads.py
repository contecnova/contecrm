"""Deduplicar un lead en el momento en que entra (CRM-01.01.03.03).

Antes de esto, la deduplicación de leads la hacía «el flujo de calidad
después», y en la práctica no la hacía nadie: la persona que rellenaba el
formulario dos veces —o que ya era cliente— entraba como lead nuevo, le
llamaban dos comerciales y el informe de conversión contaba dos.

Se mira contra **dos sitios**, porque son dos preguntas distintas:

* **Los leads** de este servicio: ¿ya nos había escrito? Por correo, por
  teléfono normalizado y por empresa + nombre parecidos.
* **Los contactos** del maestro (`party`), por HTTP: ¿ya es alguien que
  conocemos? Ningún servicio lee el esquema de otro, así que se pregunta a su
  API. Si no contesta, el alta **no se bloquea** y se dice que no se miró: un
  formulario que se cae porque otro servicio va lento pierde el lead entero.

**Qué es concluyente, y por qué no es lo mismo que en el maestro.** En un
contacto, el teléfono no bloquea —una centralita la comparten cincuenta
personas—. En un lead sí cuenta: quien deja su teléfono en un formulario deja
el suyo. El correo es concluyente en los dos sitios. El nombre y la empresa
parecidos sólo lo son por encima del umbral de bloqueo; por debajo, y por
encima del de sugerencia, salen como candidatos y no bloquean.

**Qué se hace con lo que se encuentra** depende de quién da de alta:

* En el **alta manual** se responde 409 con los candidatos y cómo seguir —usar
  el que hay, o repetir con `forzar=true`—, igual que cuentas y contactos.
* En la **captura automática** no hay nadie a quien preguntar. Según
  `lead_dedupe_captura`: `marcar` crea el lead y lo deja señalado como posible
  duplicado (no se pierde nada y una persona decide), `fusionar` no crea otro
  y anota lo que llegó en el lead que ya existía, y `nada` lo deja pasar.

La búsqueda va por índice —igualdad de correo y de teléfono, y la empresa
normalizada con un `LIKE` acotado— y no compara contra toda la tabla: un
formulario que tarda dos segundos es un formulario que se abandona.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from crmcore import normalizacion as norm
from crmcore.logging import get_logger
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from services.sales.modelos import Lead

logger = get_logger(__name__)

# Las señales que, en un lead, bastan solas. Ver la cabecera.
SENALES_CONCLUYENTES = frozenset({"email", "telefono"})


@dataclass(frozen=True, slots=True)
class CandidatoLead:
    """Un registro que podría ser el mismo que el lead que entra."""

    objeto: str  # lead | contacto
    id: str
    nombre: str
    similitud: float
    senales: tuple[str, ...]
    concluyente: bool

    def a_dict(self) -> dict[str, Any]:
        return {
            "objeto": self.objeto,
            "id": self.id,
            "nombre": self.nombre,
            "similitud": round(self.similitud, 3),
            "senales": list(self.senales),
            "concluyente": self.concluyente,
        }


@dataclass
class Resultado:
    """Lo encontrado, y si se pudo mirar en los dos sitios."""

    candidatos: list[CandidatoLead] = field(default_factory=list)
    # `False` cuando `party` no contestó o no está configurado. Se dice: un
    # «no hay duplicados» calculado sobre la mitad de las fuentes no es lo
    # mismo que uno calculado sobre las dos.
    contactos_consultados: bool = True

    @property
    def concluyentes(self) -> list[CandidatoLead]:
        return [c for c in self.candidatos if c.concluyente]

    def a_dict(self) -> dict[str, Any]:
        return {
            "candidatos": [c.a_dict() for c in self.candidatos],
            "contactos_consultados": self.contactos_consultados,
        }


def _ajustes(db: Session) -> dict[str, Any]:
    from crmcore.runtime import settings as rt

    from services.sales.ajustes import ajustes

    a = ajustes()

    def valor(clave: str) -> Any:
        efectivo = rt.efectivo(clave, db)
        return getattr(a, clave) if efectivo is None else efectivo

    # Por objeto con el que se compara (CRM-01.01.04.02): lo que el objeto no
    # diga sale del general. Se lee una vez por alta, no por candidato.
    from services.sales.golden_leads import _por_objeto, umbral_de

    por_objeto = _por_objeto(db)
    return {
        "sugerencia": umbral_de(db, "lead", "sugerencia", por_objeto=por_objeto),
        "bloqueo": umbral_de(db, "lead", "bloqueo", por_objeto=por_objeto),
        # Sin umbral propio frente al contacto, vale lo que `party` ya propone
        # con el suyo: no se filtra dos veces con dos listones.
        "contacto_sugerencia": (
            umbral_de(db, "contacto", "sugerencia", por_objeto=por_objeto)
            if (por_objeto.get("contacto") or {}).get("sugerencia") is not None
            else 0.0
        ),
        "contacto_bloqueo": umbral_de(db, "contacto", "bloqueo", por_objeto=por_objeto),
        "contactos": bool(valor("lead_dedupe_contactos")),
        "maximo": int(valor("lead_dedupe_max_candidatos")),
        "espera_s": float(valor("lead_dedupe_espera_s")),
    }


def _nombre_de(lead: Lead) -> str:
    persona = " ".join(p for p in (lead.nombre or "", lead.apellidos or "") if p).strip()
    if persona and lead.empresa:
        return f"{persona} · {lead.empresa}"
    return persona or lead.empresa or lead.email or str(lead.id)


def _clave(datos: dict[str, Any]) -> str:
    """Empresa y persona en una sola clave: «ACME · Ana Pérez»."""
    empresa = norm.clave_canonica_empresa(datos.get("empresa"))
    persona = norm.clave_canonica_persona(datos.get("nombre"), datos.get("apellidos"))
    return " ".join(p for p in (empresa, persona) if p)


def buscar_en_leads(
    db: Session,
    tenant_id: UUID,
    datos: dict[str, Any],
    *,
    sugerencia: float,
    bloqueo: float,
    excluir_id: UUID | None = None,
) -> list[CandidatoLead]:
    """Leads vivos que podrían ser este."""
    correo = norm.normalizar_email(datos.get("email"))
    telefono = norm.normalizar_telefono(datos.get("telefono"), str(datos.get("pais") or "ES"))
    clave = _clave(datos)
    empresa = norm.clave_canonica_empresa(datos.get("empresa"))

    vivos = [Lead.tenant_id == tenant_id, Lead.deleted_at.is_(None)]
    if excluir_id is not None:
        vivos.append(Lead.id != excluir_id)

    encontrados: dict[UUID, CandidatoLead] = {}
    criterios = []
    if correo:
        criterios.append(func.lower(Lead.email) == correo)
    digitos = "".join(c for c in telefono if c.isdigit())
    if len(digitos) >= 6:
        # El teléfono del lead se guarda como llegó —«600 111 222»—, así que se
        # criba por sus últimos dígitos sin separadores y se confirma
        # normalizando. La igualdad contra la columna cruda no casaba nunca.
        criterios.append(
            func.regexp_replace(Lead.telefono, r"\D", "", "g").like(f"%{digitos[-9:]}")
        )
    if empresa:
        primera = empresa.split()[0]
        criterios.append(func.lower(Lead.empresa).like(f"%{primera}%"))
    if not criterios:
        return []

    filas = db.execute(select(Lead).where(*vivos, or_(*criterios)).limit(200)).scalars().all()
    for lead in filas:
        senales: list[str] = []
        if correo and norm.normalizar_email(lead.email) == correo:
            senales.append("email")
        if telefono and norm.normalizar_telefono(lead.telefono, lead.pais or "ES") == telefono:
            senales.append("telefono")
        parecido = norm.similitud(clave, _clave(lead.__dict__)) if clave else 0.0
        if parecido >= sugerencia:
            senales.append("nombre")
        if not senales:
            continue
        concluyente = bool(SENALES_CONCLUYENTES & set(senales)) or parecido >= bloqueo
        encontrados[lead.id] = CandidatoLead(
            objeto="lead",
            id=str(lead.id),
            nombre=_nombre_de(lead),
            similitud=1.0 if SENALES_CONCLUYENTES & set(senales) else parecido,
            senales=tuple(senales),
            concluyente=concluyente,
        )
    return list(encontrados.values())


def buscar_en_contactos(
    tenant_id: UUID,
    datos: dict[str, Any],
    *,
    principal_id: Any,
    bloqueo: float,
    espera_s: float,
) -> list[CandidatoLead] | None:
    """Contactos del maestro que podrían ser esta persona. `None` si no se pudo
    preguntar —servicio sin dirección o sin respuesta—, que no es lo mismo que
    «no hay ninguno»."""
    from crmcore.errors import NoDisponible
    from crmcore.http.interno import invocar

    parametros = {
        k: str(datos.get(k) or "")
        for k in ("nombre", "apellidos", "email", "telefono")
        if datos.get(k)
    }
    if not any(parametros.get(k) for k in ("email", "telefono", "nombre")):
        return []
    try:
        respuesta = invocar(
            metodo="GET",
            ruta="/api/v1/data-quality/contacts/duplicates",
            parametros=parametros,
            tenant_id=tenant_id,
            principal_id=principal_id,
            permisos=["contact:read"],
            timeout_s=espera_s,
        )
    except NoDisponible as exc:
        logger.warning("sales.dedupe_contactos_sin_respuesta", error=str(exc)[:200])
        return None
    if not respuesta.get("ok") or not isinstance(respuesta.get("datos"), list):
        logger.warning("sales.dedupe_contactos_rechazado", estado=respuesta.get("estado"))
        return None

    salida: list[CandidatoLead] = []
    for c in respuesta["datos"]:
        senales = tuple(str(s) for s in c.get("senales") or ())
        similitud = float(c.get("similitud") or 0)
        salida.append(
            CandidatoLead(
                objeto="contacto",
                id=str(c.get("id")),
                nombre=str(c.get("nombre") or ""),
                similitud=similitud,
                senales=senales,
                concluyente=bool(SENALES_CONCLUYENTES & set(senales)) or similitud >= bloqueo,
            )
        )
    return salida


def buscar(
    db: Session,
    tenant_id: UUID,
    datos: dict[str, Any],
    *,
    principal_id: Any = None,
    excluir_id: UUID | None = None,
) -> Resultado:
    """Leads y contactos que podrían ser este lead, ordenados por certeza."""
    a = _ajustes(db)
    resultado = Resultado(
        candidatos=buscar_en_leads(
            db,
            tenant_id,
            datos,
            sugerencia=a["sugerencia"],
            bloqueo=a["bloqueo"],
            excluir_id=excluir_id,
        )
    )
    if a["contactos"]:
        contactos = buscar_en_contactos(
            tenant_id,
            datos,
            principal_id=principal_id or tenant_id,
            bloqueo=a["contacto_bloqueo"],
            espera_s=a["espera_s"],
        )
        if contactos is None:
            resultado.contactos_consultados = False
        else:
            # Lo que `party` propone con su propio listón se filtra con el del
            # lead frente al contacto: un tenant que exige más ahí no quiere
            # ver de candidato a un compañero de la misma empresa. Las señales
            # concluyentes pasan siempre.
            resultado.candidatos.extend(
                c for c in contactos if c.concluyente or c.similitud >= a["contacto_sugerencia"]
            )
    resultado.candidatos.sort(key=lambda c: (-int(c.concluyente), -c.similitud))
    resultado.candidatos = resultado.candidatos[: a["maximo"]]
    return resultado


def fusionar_en(db: Session, lead: Lead, datos: dict[str, Any], *, canal: str) -> Lead:
    """Anota lo que llega en un lead que ya existía, sin crear otro.

    Rellena huecos y no pisa: el lead que ya estaba puede tener datos que
    alguien corrigió a mano. Lo que llegó entero se guarda en
    `campos["capturas_fusionadas"]`, con su canal, para que nadie tenga que
    preguntarse qué pidió esta vez.
    """
    from datetime import datetime, timezone

    for campo in ("nombre", "apellidos", "empresa", "cargo", "telefono", "web", "pais"):
        if datos.get(campo) and not getattr(lead, campo, None):
            setattr(lead, campo, datos[campo])
    campos = dict(lead.campos or {})
    historial = list(campos.get("capturas_fusionadas") or [])
    historial.append(
        {
            "canal": canal,
            "at": datetime.now(timezone.utc).isoformat(),
            "datos": {k: v for k, v in datos.items() if k not in ("campos", "utm")},
        }
    )
    campos["capturas_fusionadas"] = historial[-20:]
    lead.campos = campos
    db.flush()
    return lead
