"""Anonimizar y seudonimizar para entornos no productivos (CRM-00.05.03.05).

Un entorno de pruebas con datos reales es una copia de la base de clientes en
una máquina con menos vigilancia, con más gente dentro y sin las mismas
políticas. Es la fuga más habitual y la que menos se investiga, porque nadie la
llama fuga: la llama «la copia de preproducción».

Dos decisiones que deciden si esto sirve:

**Es consistente.** El mismo valor da siempre el mismo sustituto dentro del
mismo entorno. Sin eso, el correo de un contacto sería distinto en la tabla de
contactos y en la de actividades, las relaciones se romperían y el entorno no
serviría para probar nada — que es como acaban reponiendo los datos reales «solo
esta vez».

**No es reversible.** El sustituto sale de un HMAC con una sal **del entorno**,
no de un cifrado: si se pudiera deshacer, el entorno de pruebas seguiría
conteniendo los datos, solo que con un paso más. Y la sal es del entorno, así
que dos copias distintas dan valores distintos y cruzarlas no reconstruye nada.

Qué se anonimiza sale de la **sensibilidad declarada en el modelo**, no de una
lista de campos: una lista se queda desfasada al primer campo nuevo, y el campo
nuevo entraría con dato real sin que nadie lo decidiera.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Sensibilidades que NO pueden salir de producción. `interno` y `publico` se
# quedan: anonimizar el nombre de una etapa de pipeline haría el entorno
# inservible y no protege a nadie.
SENSIBLES = frozenset({"personal", "especial", "confidencial"})

# Cómo se sustituye cada tipo de dato. La forma se conserva —un correo sigue
# pareciendo un correo— porque un entorno donde los correos son «xxx» no sirve
# para probar el envío de correos, que es justo lo que se prueba ahí.
FORMAS = {
    "email": lambda h: f"{h[:12]}@ejemplo.invalid",
    "telefono": lambda h: "+34" + "".join(str(int(c, 16) % 10) for c in h[:9]),
    "nombre": lambda h: f"Persona {h[:8].upper()}",
    "texto": lambda h: f"anon-{h[:16]}",
    "identificador_fiscal": lambda h: h[:8].upper(),
}


def seudonimo(valor: Any, *, sal: str, forma: str = "texto") -> Any:
    """El sustituto estable de un valor. Mismo valor y misma sal, mismo resultado.

    Vacío se queda vacío: inventar un correo donde no había ninguno cambiaría
    los recuentos de completitud del dato, y alguien concluiría que el entorno
    de pruebas tiene mejores datos que producción.
    """
    if valor in (None, ""):
        return valor
    huella = hmac.new(sal.encode(), str(valor).encode(), hashlib.sha256).hexdigest()
    constructor = FORMAS.get(forma, FORMAS["texto"])
    return constructor(huella)


def forma_de(nombre_campo: str) -> str:
    """Adivina la forma por el nombre del campo, que es lo que hay.

    Se adivina y se dice que se adivina: la alternativa —declararla campo a
    campo— es la lista que se queda desfasada. Lo que no se reconoce cae en
    `texto`, que es seguro: sustituye igual, solo que sin conservar la forma.
    """
    n = nombre_campo.lower()
    if "email" in n or "correo" in n:
        return "email"
    if "telefono" in n or "movil" in n or "phone" in n:
        return "telefono"
    if "nif" in n or "cif" in n or "fiscal" in n or "vat" in n:
        return "identificador_fiscal"
    if "nombre" in n or "apellido" in n:
        return "nombre"
    return "texto"


def campos_sensibles(modelo: type) -> list[str]:
    """Los campos que el modelo declara sensibles.

    Sale del propio modelo (`info={"sensibilidad": ...}`) y no de una lista
    aparte: con una lista, el campo nuevo entraría con dato real sin que nadie
    lo decidiera, y eso es exactamente cómo un entorno de pruebas acaba con
    datos de clientes.
    """
    tabla = getattr(modelo, "__table__", None)
    if tabla is None:
        return []
    return [
        columna.name
        for columna in tabla.columns
        if str((columna.info or {}).get("sensibilidad", "")) in SENSIBLES
    ]


def anonimizar_fila(
    fila: dict[str, Any], modelo: type, *, sal: str, campos: list[str] | None = None
) -> dict[str, Any]:
    """Devuelve la fila con los campos sensibles sustituidos.

    No modifica la original: anonimizar en el sitio sobre un objeto de
    SQLAlchemy lo marcaría como sucio y el siguiente `flush` escribiría los
    valores anónimos **en producción**, que es el peor accidente imaginable de
    una herramienta cuyo propósito es proteger datos.
    """
    objetivo = campos if campos is not None else campos_sensibles(modelo)
    if not objetivo:
        return dict(fila)
    salida = dict(fila)
    for campo in objetivo:
        if campo in salida:
            salida[campo] = seudonimo(salida[campo], sal=sal, forma=forma_de(campo))
    return salida


def sal_de_entorno(nombre_entorno: str, secreto: str) -> str:
    """La sal de un entorno concreto.

    Distinta por entorno a propósito: dos copias anonimizadas del mismo
    producción dan valores distintos, así que cruzarlas no reconstruye nada. Si
    la sal fuera la misma, juntar dos copias con campos distintos anonimizados
    devolvería el registro entero.
    """
    return hmac.new(secreto.encode(), f"anon:{nombre_entorno}".encode(), hashlib.sha256).hexdigest()
