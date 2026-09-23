"""gRPC y protobuf: el contrato y el transporte (CRM-00.02.01.03)."""

from crmcore.rpc.esquema import (
    TIPO_PROTO,
    asignar_numeros,
    comprobar_compatibilidad,
    proto_de_objeto,
)

__all__ = [
    "TIPO_PROTO",
    "asignar_numeros",
    "comprobar_compatibilidad",
    "proto_de_objeto",
]
