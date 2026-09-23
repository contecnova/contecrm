"""Mensajes protobuf construidos en memoria, sin paso de compilación
(CRM-00.02.01.03).

Lo normal en protobuf es escribir el `.proto`, pasarle `protoc` y commitear el
código generado. Aquí no vale: los objetos del CRM **los define cada tenant** en
el metamodelo, y un campo nuevo de un cliente no puede exigir recompilar y
volver a desplegar el producto.

Así que el descriptor se construye en memoria desde la misma declaración que
genera el `.proto` de texto. El fichero sigue existiendo —es lo que se le da al
que va a integrar—, pero **lo que el servidor usa se deriva de la declaración**,
y por eso no pueden decir cosas distintas.

Dos cosas que parecen detalles y no lo son:

**Presencia explícita en los opcionales.** Sin `optional`, en proto3 un cero y
un «no lo mando» son el mismo byte: ninguno. En un `Update` eso significa que
mandar tres campos borra los otros veinte, y el cliente nunca pretendió eso.

**Un campo que no está en el contrato es un error, no se ignora.** Protobuf
descarta lo desconocido por diseño, que está bien para leer y es malísimo para
escribir: quien manda `descuneto` cree que puso un descuento, y el CRM guarda la
ficha sin él y devuelve 200.
"""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from crmcore.errors import ErrorValidacion, PeticionMalFormada
from crmcore.logging import get_logger
from crmcore.rpc.esquema import CAMPOS_QUE_NO_SALEN, TIPO_PROTO, asignar_numeros

logger = get_logger(__name__)

_F = descriptor_pb2.FieldDescriptorProto

# Del tipo protobuf del contrato al código del descriptor. Solo los que aparecen
# en `TIPO_PROTO`: añadir uno aquí sin añadirlo allí daría un descriptor que no
# corresponde a ningún `.proto` publicado.
_CODIGO = {
    "string": _F.TYPE_STRING,
    "int64": _F.TYPE_INT64,
    "bool": _F.TYPE_BOOL,
    "double": _F.TYPE_DOUBLE,
}


def clase_de_objeto(
    *,
    objeto: str,
    campos: list[dict[str, Any]],
    asignados: dict[str, int] | None = None,
    paquete: str = "crm",
    version: int = 1,
) -> Any:
    """Construye la clase de mensaje de un objeto del metamodelo.

    Cada llamada usa su propio `DescriptorPool`. Compartir uno global haría que
    el objeto `contacto` del tenant A —con sus campos personalizados— colisionara
    con el del tenant B por tener el mismo nombre completo, y el segundo en
    registrarse se quedaría con el esquema del primero: un mensaje con los campos
    de otro cliente.
    """
    numeros = asignar_numeros(campos=campos, asignados=asignados)["numeros"]
    nombre = "".join(p.capitalize() for p in objeto.replace("-", "_").split("_"))

    fichero = descriptor_pb2.FileDescriptorProto()
    fichero.name = f"{paquete}/{objeto}/v{version}/{objeto}.proto"
    fichero.package = f"{paquete}.{objeto}.v{version}"
    fichero.syntax = "proto3"

    mensaje = fichero.message_type.add()
    mensaje.name = nombre

    for campo in sorted(campos, key=lambda c: numeros[str(c.get("clave"))]):
        clave = str(campo.get("clave"))
        tipo = str(campo.get("tipo") or "")
        if tipo in CAMPOS_QUE_NO_SALEN:
            raise ErrorValidacion(
                f"El campo «{clave}» no se publica: " + CAMPOS_QUE_NO_SALEN[tipo],
                error_code="rpc.tipo_no_publicable",
            )
        proto = TIPO_PROTO.get(tipo)
        if proto is None:
            raise ErrorValidacion(
                f"El tipo «{campo.get('tipo')}» del campo «{clave}» no tiene "
                "correspondencia en protobuf.",
                error_code="rpc.tipo_sin_correspondencia",
            )
        repetido = proto.startswith("repeated")
        escalar = proto.replace("repeated ", "")

        descriptor = mensaje.field.add()
        descriptor.name = clave
        descriptor.number = numeros[clave]
        descriptor.type = _CODIGO[escalar]
        descriptor.label = _F.LABEL_REPEATED if repetido else _F.LABEL_OPTIONAL

        if not repetido and not campo.get("obligatorio"):
            # Presencia explícita. Sin esto, un cero y un «no lo mando» son el
            # mismo byte, y un `Update` parcial borra lo que no venía.
            uno_de = mensaje.oneof_decl.add()
            uno_de.name = f"_{clave}"
            descriptor.proto3_optional = True
            descriptor.oneof_index = len(mensaje.oneof_decl) - 1

    pozo = descriptor_pool.DescriptorPool()
    descriptor_fichero = pozo.Add(fichero)
    return message_factory.GetMessageClass(descriptor_fichero.message_types_by_name[nombre])


def a_mensaje(clase: Any, datos: dict[str, Any]) -> Any:
    """Pasa un diccionario a mensaje, **fallando si sobra algo**.

    Protobuf descarta lo desconocido por diseño. Está bien al leer —así un
    cliente viejo sobrevive a un campo nuevo— y es malísimo al escribir: quien
    manda `descuneto` cree que puso un descuento, el CRM guarda la ficha sin él y
    contesta que todo ha ido bien.
    """
    conocidos = {campo.name for campo in clase.DESCRIPTOR.fields}
    sobran = sorted(set(datos) - conocidos)
    if sobran:
        raise PeticionMalFormada(
            f"Campos que no existen en el contrato: {', '.join(sobran)}. No se "
            "ignoran: quien escribe mal un nombre cree que mandó el dato, y lo que "
            "recibiría es un «todo bien» con la ficha sin ese campo.",
            error_code="rpc.campo_desconocido",
            detalle={"campos_del_contrato": sorted(conocidos)},
        )
    mensaje = clase()
    for clave, valor in datos.items():
        if valor is None:
            # Un nulo explícito es «no mando este campo», no «ponlo a cero».
            continue
        campo = clase.DESCRIPTOR.fields_by_name[clave]
        if campo.label == campo.LABEL_REPEATED:
            getattr(mensaje, clave).extend(valor)
        else:
            setattr(mensaje, clave, valor)
    return mensaje


def a_diccionario(mensaje: Any) -> dict[str, Any]:
    """Pasa un mensaje a diccionario **distinguiendo el vacío del ausente**.

    Un campo con presencia que no viene **no aparece** en el diccionario, y uno
    que viene a cero aparece con su cero. Devolver ceros por lo que no vino es lo
    que hace que un `Update` de dos campos ponga a cero los otros veinte.
    """
    salida: dict[str, Any] = {}
    for campo in mensaje.DESCRIPTOR.fields:
        if campo.label == campo.LABEL_REPEATED:
            valores = list(getattr(mensaje, campo.name))
            if valores:
                salida[campo.name] = valores
            continue
        if campo.has_presence and not mensaje.HasField(campo.name):
            continue
        salida[campo.name] = getattr(mensaje, campo.name)
    return salida
