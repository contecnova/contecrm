"""El contrato protobuf, generado y no escrito a mano (CRM-00.02.01.03).

Portado en su postura de `contecpos/packages/contracts` (buf + protobuf), y lo
que se conserva de allí es la idea, no el montaje: **el contrato se comprueba
antes de commitear, no en un servidor de integración**, porque aquí no hay
ninguno.

Lo que se resuelve:

**El `.proto` sale del metamodelo.** Mantenerlo a mano al lado de la API REST
significa que los dos dicen cosas distintas en cuanto alguien añade un campo, y
el que se queda viejo es siempre el que menos gente mira. Es la misma regla que
ya se aplica al OpenAPI (CRM-00.02.01.04): generado desde el código.

**Los números de campo se asignan una vez y no se reutilizan nunca.** Esta es
LA trampa de protobuf, y es silenciosa: si el campo 7 era `descuento` (un
entero) y se borra, y mañana el campo 7 pasa a ser `id_zona` (otro entero), un
cliente viejo que mande un descuento escribe una zona. No falla, no avisa y no
hay nada en el log: el dato entra cambiado. Por eso lo que se borra queda
`reserved` para siempre, que es feo de leer y es la única forma de que eso no
pase.

**Y un cambio incompatible falla aquí.** Cambiar el tipo de un campo, quitar
uno sin reservarlo o pasar de singular a repetido rompe a quien ya consume, y
romper en el `make preflight` de quien lo escribe cuesta un minuto — romper en
producción cuesta una llamada del cliente que integró hace seis meses.

El transporte vive en `crmcore.rpc.servidor` y es opcional; esto no.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué tipo de protobuf corresponde a cada tipo del metamodelo. Lista cerrada: un
# tipo sin correspondencia NO cae a `string`. Caer a string es lo que convierte
# un decimal en una cadena que el otro lado parsea como puede, y en dinero eso
# acaba en una factura mal.
TIPO_PROTO = {
    "texto": "string",
    "texto_largo": "string",
    "numero": "int64",
    # El importe viaja como cadena a propósito: `double` no representa 0,1 y en
    # dinero eso se convierte en céntimos que no cuadran. Es lo mismo que hace
    # el JSON de la API, y por eso los dos contratos dicen lo mismo.
    "moneda": "string",
    "porcentaje": "string",
    # Fechas en ISO-8601, no en epoch: un epoch sin huso obliga al otro lado a
    # adivinar, y la mitad adivina mal.
    "fecha": "string",
    "fecha_hora": "string",
    "booleano": "bool",
    "lista": "string",
    "lista_multiple": "repeated string",
    "formula": "string",
    "lookup": "string",
    "geolocalizacion": "string",
    "json": "string",
    "fichero": "string",
    # El cifrado NO sale por gRPC. Ver `CAMPOS_QUE_NO_SALEN`.
    "email": "string",
    "telefono": "string",
    "url": "string",
}

# Tipos que existen en el metamodelo y que a propósito NO tienen hueco en el
# contrato. No es un olvido: un campo cifrado que sale por una superficie nueva
# es un secreto que viaja por un sitio donde nadie miró quién escucha.
CAMPOS_QUE_NO_SALEN = {
    "cifrado": (
        "Un campo cifrado no sale por gRPC. Lo que se guarda cifrado se descifra "
        "para quien tiene permiso y por el camino que ya se auditó, no por una "
        "superficie nueva."
    ),
}

# El primer número libre. Del 1 al 15 la codificación ocupa un byte en vez de
# dos, así que ahí van los campos que van en todos los mensajes.
PRIMER_NUMERO = 1

# protobuf reserva del 19000 al 19999 para sí mismo. Asignar ahí no da error al
# escribir el `.proto` y lo da al compilarlo, que es más tarde y más raro.
RANGO_PROHIBIDO = range(19000, 20000)


def _tipo_de(campo: dict[str, Any]) -> str:
    tipo = str(campo.get("tipo") or "")
    if tipo in CAMPOS_QUE_NO_SALEN:
        raise ErrorValidacion(
            f"El campo «{campo.get('clave')}» es de tipo «{tipo}» y no se publica: "
            + CAMPOS_QUE_NO_SALEN[tipo],
            error_code="rpc.tipo_no_publicable",
        )
    proto = TIPO_PROTO.get(tipo)
    if proto is None:
        raise ErrorValidacion(
            f"El tipo «{tipo}» del campo «{campo.get('clave')}» no tiene "
            "correspondencia en protobuf. No se cae a `string`: eso convierte un "
            "decimal en una cadena que el otro lado parsea como puede, y en importes "
            "acaba en una factura mal.",
            error_code="rpc.tipo_sin_correspondencia",
            detalle={"tipos_conocidos": sorted(TIPO_PROTO)},
        )
    return proto


def asignar_numeros(
    *,
    campos: list[dict[str, Any]],
    asignados: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Da número a cada campo **respetando los que ya tenía**.

    Los que ya estaban conservan el suyo aunque cambien de sitio en la lista: el
    orden del `.proto` es cosmético y el número es el contrato. Reordenar los
    campos y que se renumeren solos sería cambiar el significado de todos los
    mensajes que hay en vuelo sin tocar ni una línea de lógica.

    Y lo que **desaparece queda reservado**. Un número reutilizado no rompe nada
    visible: el mensaje se decodifica, el valor entra en el campo equivocado y
    nadie se entera hasta que alguien pregunta por qué ese cliente tiene una zona
    que no existe.
    """
    previos = dict(asignados or {})
    claves_ahora = {str(c.get("clave")) for c in campos}

    usados = set(previos.values())
    numeros: dict[str, int] = {}
    siguiente = PRIMER_NUMERO

    for campo in campos:
        clave = str(campo.get("clave"))
        if clave in previos:
            numeros[clave] = previos[clave]
            continue
        while siguiente in usados or siguiente in RANGO_PROHIBIDO:
            siguiente += 1
        numeros[clave] = siguiente
        usados.add(siguiente)
        siguiente += 1

    # Lo que estaba y ya no está. No vuelve a usarse jamás.
    reservados = sorted(n for clave, n in previos.items() if clave not in claves_ahora)
    nombres_reservados = sorted(c for c in previos if c not in claves_ahora)

    return {
        "numeros": numeros,
        "reservados": reservados,
        "nombres_reservados": nombres_reservados,
        "porque_reservados": (
            "Un número reutilizado no rompe nada visible: el mensaje se decodifica, el "
            "valor entra en el campo equivocado y no hay ni error ni log. Por eso lo "
            "que se borra no vuelve a usarse."
        ),
    }


def proto_de_objeto(
    *,
    objeto: str,
    campos: list[dict[str, Any]],
    asignados: dict[str, int] | None = None,
    paquete: str = "crm",
    version: int = 1,
) -> dict[str, Any]:
    """Genera el `.proto` de un objeto del metamodelo.

    Con su servicio: `Get`, `List`, `Create`, `Update` y `Watch`. El `Watch` es
    la razón de que esto exista y no baste con REST — un flujo abierto que va
    mandando cambios, que por HTTP hay que emular con sondeo o con SSE.
    """
    asignacion = asignar_numeros(campos=campos, asignados=asignados)
    numeros = asignacion["numeros"]
    nombre = "".join(p.capitalize() for p in objeto.replace("-", "_").split("_"))

    lineas: list[str] = [
        "// GENERADO desde el metamodelo. No se edita a mano: lo que se escriba",
        "// aquí desaparece en la siguiente generación, y mientras tanto dice algo",
        "// distinto de lo que hace la API.",
        'syntax = "proto3";',
        "",
        f"package {paquete}.{objeto}.v{version};",
        "",
        f"service {nombre}Service {{",
        f"  rpc Get({nombre}GetRequest) returns ({nombre});",
        f"  rpc List({nombre}ListRequest) returns (stream {nombre});",
        f"  rpc Create({nombre}) returns ({nombre});",
        f"  rpc Update({nombre}) returns ({nombre});",
        "  // El flujo abierto: es lo que no se puede hacer bien por HTTP sin",
        "  // sondear, y la razón de que exista esta superficie.",
        f"  rpc Watch({nombre}WatchRequest) returns (stream {nombre});",
        "}",
        "",
        f"message {nombre} {{",
    ]

    if asignacion["reservados"]:
        lineas.append(
            "  // Números de campos que existieron. No se reutilizan: reutilizar uno "
            "mete el valor en el campo equivocado sin error."
        )
        lineas.append(f"  reserved {', '.join(str(n) for n in asignacion['reservados'])};")
        nombres = ", ".join(f'"{n}"' for n in asignacion["nombres_reservados"])
        lineas.append(f"  reserved {nombres};")

    for campo in sorted(campos, key=lambda c: numeros[str(c.get("clave"))]):
        clave = str(campo.get("clave"))
        tipo = _tipo_de(campo)
        comentario = str(campo.get("etiqueta") or "").strip()
        if comentario:
            lineas.append(f"  // {comentario}")
        if not campo.get("obligatorio") and not tipo.startswith("repeated"):
            # `optional` en proto3 devuelve la presencia explícita: sin él, un
            # cero y un «no lo mando» son lo mismo, y en un `Update` eso borra
            # el dato que el cliente no pretendía tocar.
            lineas.append(f"  optional {tipo} {clave} = {numeros[clave]};")
        else:
            lineas.append(f"  {tipo} {clave} = {numeros[clave]};")
    lineas.append("}")
    lineas.append("")

    for sufijo, cuerpo in (
        ("GetRequest", ["  string id = 1;"]),
        (
            "ListRequest",
            [
                "  int32 limite = 1;",
                "  string cursor = 2;",
                "  string filtro = 3;",
            ],
        ),
        ("WatchRequest", ["  string desde_secuencia = 1;"]),
    ):
        lineas.append(f"message {nombre}{sufijo} {{")
        lineas.extend(cuerpo)
        lineas.append("}")
        lineas.append("")

    return {
        "objeto": objeto,
        "ruta": f"proto/{paquete}/{objeto}/v{version}/{objeto}.proto",
        "contenido": "\n".join(lineas),
        "numeros": numeros,
        "reservados": asignacion["reservados"],
    }


def comprobar_compatibilidad(
    *,
    antes: dict[str, Any],
    despues: dict[str, Any],
) -> dict[str, Any]:
    """Compara dos versiones del contrato y dice qué rompe a quien ya consume.

    Cada `antes`/`despues` es `{"numeros": {clave: n}, "tipos": {clave: t},
    "reservados": [n, ...]}`.

    Se devuelven **todos** los problemas y no el primero: quien está cambiando
    un contrato agradece ver las tres cosas de una vez mucho más que
    descubrirlas de una en una, con un intento fallido entre cada dos.

    Lo que se considera roto y por qué:

    * **Un número reutilizado para otro campo.** Es lo peor: no da error, el
      valor entra en el sitio equivocado y no hay traza.
    * **Un tipo cambiado.** Los que consumen con el `.proto` viejo decodifican
      basura o pierden el campo, según cómo caiga en el cable.
    * **Un campo quitado sin reservar su número.** Es la puerta a lo primero.
    * **Un campo que pasa de singular a repetido**, o al revés: el que lee lo ve
      vacío y se lo cree.
    """
    num_antes = dict(antes.get("numeros") or {})
    num_despues = dict(despues.get("numeros") or {})
    tipos_antes = dict(antes.get("tipos") or {})
    tipos_despues = dict(despues.get("tipos") or {})
    reservados = set(despues.get("reservados") or [])

    problemas: list[dict[str, str]] = []

    por_numero_antes = {n: c for c, n in num_antes.items()}
    for clave, numero in num_despues.items():
        anterior = por_numero_antes.get(numero)
        if anterior is not None and anterior != clave:
            problemas.append(
                {
                    "tipo": "numero_reutilizado",
                    "campo": clave,
                    "detalle": (
                        f"El número {numero} era de «{anterior}» y ahora es de " f"«{clave}»."
                    ),
                    "consecuencia": (
                        "Un cliente que aún mande el campo viejo escribirá en el nuevo. "
                        "No hay error ni log: el dato entra cambiado."
                    ),
                }
            )

    for clave, numero in num_antes.items():
        if clave in num_despues:
            if num_despues[clave] != numero:
                problemas.append(
                    {
                        "tipo": "numero_movido",
                        "campo": clave,
                        "detalle": f"«{clave}» pasó del número {numero} al "
                        f"{num_despues[clave]}.",
                        "consecuencia": (
                            "El número es el contrato; el nombre es cosmético. Moverlo "
                            "cambia el significado de todos los mensajes en vuelo."
                        ),
                    }
                )
            continue
        if numero not in reservados:
            problemas.append(
                {
                    "tipo": "campo_quitado_sin_reservar",
                    "campo": clave,
                    "detalle": f"«{clave}» ya no está y su número {numero} no está " "reservado.",
                    "consecuencia": (
                        "El siguiente campo que se añada puede coger ese número, y "
                        "entonces el valor entra en el campo equivocado sin error."
                    ),
                }
            )

    for clave, tipo in tipos_antes.items():
        nuevo = tipos_despues.get(clave)
        if nuevo is None or nuevo == tipo:
            continue
        repetido_antes = tipo.startswith("repeated")
        repetido_ahora = nuevo.startswith("repeated")
        problemas.append(
            {
                "tipo": "cardinalidad_cambiada"
                if repetido_antes != repetido_ahora
                else "tipo_cambiado",
                "campo": clave,
                "detalle": f"«{clave}» era `{tipo}` y ahora es `{nuevo}`.",
                "consecuencia": (
                    "Quien consume con el contrato viejo lo verá vacío y se lo creerá."
                    if repetido_antes != repetido_ahora
                    else "Quien consume con el contrato viejo decodifica basura o pierde "
                    "el campo, según cómo caiga en el cable."
                ),
            }
        )

    añadidos = sorted(set(num_despues) - set(num_antes))
    return {
        "compatible": not problemas,
        "problemas": problemas,
        "campos_nuevos": añadidos,
        "veredicto": (
            "Compatible: lo que se ha añadido lo ignora quien no lo conoce, que es "
            "justo lo que protobuf garantiza."
            if not problemas
            else f"{len(problemas)} cambios rompen a quien ya consume. Romper aquí "
            "cuesta un minuto; romper en producción cuesta la llamada del cliente que "
            "integró hace seis meses."
        ),
    }
