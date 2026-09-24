"""Nadie ve el registro de otro, en TODAS las rutas (CRM-00.01.02.05).

Había pruebas de aislamiento, pero eran las rutas que alguien eligió probar. Eso
deja el punto ciego donde más duele: la ruta nueva que nadie se acordó de
añadir a la lista. Esta suite no tiene lista — **recorre la aplicación real de
cada servicio** y prueba todas las rutas que reciben un identificador.

Cómo funciona:

  1. Se levanta cada servicio con su factoría de producción.
  2. De su OpenAPI se sacan las rutas con exactamente un parámetro de ruta que
     sea un identificador (`/cuentas/{cuenta_id}`).
  3. Del nombre del parámetro se deduce el objeto (`cuenta_id` → `Cuenta`) y se
     inserta una fila de ese objeto **del tenant A**.
  4. Se llama a la ruta con ese identificador **como tenant B**, con permisos
     de administrador para que lo que se compruebe sea el aislamiento y no la
     autorización.
  5. Se exige **404**. No 403, y desde luego no 200.

**Por qué 404 y no 403.** Un 403 confirma que el registro existe. Enumerando
identificadores, un competidor con una cuenta en el mismo sistema puede
averiguar cuántos clientes tiene otro y, con los códigos secuenciales que usan
muchos CRM, hasta su ritmo de altas. El 404 no distingue «no existe» de «no es
tuyo», que es exactamente lo que se quiere.

**Lo que hace que esta suite no se degrade:** las rutas cuyo objeto no se puede
resolver no se ignoran en silencio. Se listan, y una lista no vacía sin
justificación hace fallar la prueba. Sin eso, el día que alguien añada
`/expedientes/{expediente_id}` sin modelo `Expediente`, la ruta dejaría de
probarse y nadie se enteraría — que es el modo exacto en que esta clase de
suites se convierte en decoración.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.base import Base
from starlette.testclient import TestClient

# Servicios con modelo de negocio propio y rutas por identificador. `gateway` se
# queda fuera a propósito: no tiene datos, solo reenvía, y el permiso lo aplica
# el servicio destino.
# `metadata` se queda fuera y conviene decir por qué: direcciona TODO por
# nombre (`/objetos/{objeto}/campos/{nombre}`), no por identificador, así que no
# hay identificador ajeno que enumerar. Su aislamiento lo cubre el guard del
# ORM, que tiene sus propias pruebas.
SERVICIOS = ("party", "sales", "orchestrator", "tenancy", "identity")

# Parámetros de ruta que NO identifican una fila de este servicio, con el motivo.
# Se listan para que la resolución automática no tenga que adivinar y, sobre
# todo, para que su ausencia de cobertura sea una decisión escrita y no un
# hueco.
PARAMETROS_NO_FILA = {
    "tenant_id": "es el tenant mismo; su aislamiento lo prueba `test_baja_tenant`",
    "objeto_tipo": "no es un identificador, es el nombre de un tipo",
    "clave": "las tablas de decisión y los ajustes se direccionan por clave, no por id",
    "objeto": "nombre de objeto del metamodelo",
    "nombre": "nombre de un recurso de configuración",
    "version": "número de versión, no identificador",
    "codigo": "código de catálogo, no identificador",
    "slug": "identificador legible del tenant",
    "usuario_id": "la pertenencia de un usuario a un tenant la prueba `test_sso`",
    "capacidad_id": (
        "es un identificador del catálogo funcional (CRM-07.03.02), que es el mismo\n        para todos los tenants y no contiene dato de ninguno: la respuesta que sí\n        es de cada uno —qué controles la cubren— sale filtrada por tenant"
    ),
}

# Rutas que responden algo distinto de 404 por un motivo legítimo, con él
# escrito. La lista está vacía y conviene que siga estándolo: cada entrada es un
# sitio por el que se puede averiguar que un registro ajeno existe.
EXENTAS: dict[str, str] = {}

# Parámetros cuyo modelo no se llama como ellos. Se escriben porque la
# alternativa —renombrar el parámetro de la ruta— cambiaría el contrato público
# de la API para comodidad de una prueba.
ALIAS_MODELO = {
    "instancia_id": "instanciaproceso",
    "tarea_id": "tareahumana",
    "linea_id": "lineaoportunidad",
    "regla_id": "reglaenrutamiento",
    "definicion_id": "definicionproceso",
    "suscripcion_id": "suscripcion",
    "membresia_id": "membresia",
    "proveedor_id": "proveedoridentidad",
    "entrada_id": "entradapapelera",
    # La pareja propuesta en la cola de duplicados. Se llama «candidato» en la
    # ruta porque es como se lee —«decidir este candidato»— y el modelo lleva el
    # objeto dentro para no chocar con el candidato que devuelve la búsqueda al
    # crear, que no es una fila sino un resultado calculado.
    "candidato_id": "candidatoduplicado",
    "bloqueo_id": "bloqueolegal",
    "calendario_id": "calendariolaboral",
    "clave_id": "claveapi",
    # La migración de aislamiento se llama así y no «migracion» a secas porque
    # ya hay otra cosa que migra —la convivencia con el sistema antiguo— y dos
    # clases con el mismo nombre acabarían tapándose la una a la otra.
    "migracion_id": "migracionaislamiento",
    "solicitud_id": "solicitudderechos",
    "relacion_id": "relacioncuenta",
    "direccion_id": "direccion",
    "identificador_id": "identificadorfiscal",
    "miembro_id": "miembroequipocuenta",
    "canal_id": "canalcaptura",
    # Los nombres que `montar_ficha` deriva del objeto y que no coinciden con
    # la clase: se declaran aquí para que la ruta SÍ se pruebe, en vez de
    # quedarse fuera en silencio, que es lo que este gate existe para impedir.
    "canal_captura_id": "canalcaptura",
    "aislamiento_id": "aislamientotenant",
    "migracion_aislamiento_id": "migracionaislamiento",
    # SCIM llama «Group» al rol; el nombre viene del RFC 7644 y renombrarlo
    # rompería el contrato con los IdP.
    "grupo_id": "roltenant",
    "dispositivo_id": "dispositivoconfianza",
    "sincronizacion_id": "sincronizacionsuite",
    "incidencia_id": "incidenciaencargo",
    # La aprobación NO se llama `solicitud_id` en la ruta: ese nombre ya es de
    # las solicitudes de derechos de `party`, y dos rutas con el mismo parámetro
    # apuntando a objetos distintos dejan este gate sin poder resolver ninguna.
    "aprobacion_id": "solicitudaprobacion",
    "presupuesto_id": "presupuesto",
    "suscripcion_cliente_id": "suscripcioncliente",
    "pedido_id": "pedido",
    "sobre_id": "sobre",
    "informe_id": "informe",
}


def _modelos_por_nombre() -> dict[str, Any]:
    """Todos los modelos con `tenant_id`, indexados por su nombre en minúsculas.

    **Un nombre repetido para el gate en seco**, en vez de dejar que uno pise al
    otro. Dos clases llamadas igual en servicios distintos —pasó con
    `Suscripcion`, la de los webhooks y la comercial— hacen que este diccionario
    se quede con una sola, y la ruta de la otra se deja de probar sin que falle
    nada: el gate seguiría en verde sin mirar esa tabla, que es la peor forma de
    perder una comprobación.
    """
    modelos: dict[str, Any] = {}
    repetidos: list[str] = []
    for mapper in Base.registry.mappers:
        clase = mapper.class_
        if "tenant_id" not in clase.__table__.columns:
            continue
        nombre = clase.__name__.lower()
        if nombre in modelos and modelos[nombre] is not clase:
            repetidos.append(f"{nombre}: {modelos[nombre].__module__} y {clase.__module__}")
        modelos[nombre] = clase
    assert not repetidos, (
        "Hay modelos con el mismo nombre de clase, y este gate los indexa por ese "
        "nombre: uno pisaría al otro y su ruta dejaría de probarse.\n  " + "\n  ".join(repetidos)
    )
    return modelos


def _rutas_con_id(app: Any) -> list[tuple[str, str, str]]:
    """(método, plantilla de ruta, nombre del parámetro) de cada ruta con un id."""
    esquema = app.openapi()
    encontradas: list[tuple[str, str, str]] = []
    for ruta, operaciones in esquema.get("paths", {}).items():
        parametros = re.findall(r"\{([a-zA-Z_][\w]*)\}", ruta)
        if len(parametros) != 1:
            # Con cero no hay nada que enumerar; con dos o más, la ruta es
            # anidada y el aislamiento lo decide el padre, que ya se prueba por
            # su propia ruta.
            continue
        for metodo in operaciones:
            if metodo.upper() in ("GET", "PATCH", "PUT", "DELETE", "POST"):
                encontradas.append((metodo.upper(), ruta, parametros[0]))
    return encontradas


def _crear_fila(db: Any, modelo: Any, tenant_id: UUID, _profundidad: int = 0) -> Any:
    """Inserta una fila mínima del modelo, rellenando lo obligatorio.

    Rellenar a ciegas las columnas no nulas es más robusto que mantener una
    factoría por modelo: una columna nueva obligatoria no rompe la prueba, y lo
    que se comprueba no depende del contenido de la fila.

    Dos cosas que hay que hacer bien o la prueba se cae por su propio peso:

    **Las claves ajenas obligatorias se crean antes**, recursivamente. Una
    oportunidad exige un pipeline, y un UUID inventado viola la restricción.

    **Los textos son únicos.** Media docena de modelos tienen restricciones de
    unicidad por tenant, y rellenar todos con `"x"` hace fallar la segunda fila.
    """
    import datetime as dt
    import decimal

    valores: dict[str, Any] = {"tenant_id": tenant_id}
    for columna in modelo.__table__.columns:
        if columna.name in valores or columna.nullable or columna.primary_key:
            continue
        if columna.default is not None or columna.server_default is not None:
            continue

        ajena = next(iter(columna.foreign_keys), None)
        if ajena is not None and _profundidad < 4:
            padre = _modelo_de_tabla(ajena.column.table.name)
            if padre is not None:
                valores[columna.name] = getattr(
                    _crear_fila(db, padre, tenant_id, _profundidad + 1),
                    ajena.column.name,
                )
                continue

        tipo = str(columna.type).upper()
        if "UUID" in tipo:
            valores[columna.name] = uuid4()
        elif "INT" in tipo:
            valores[columna.name] = 1
        elif "NUMERIC" in tipo or "DECIMAL" in tipo:
            valores[columna.name] = decimal.Decimal("1")
        elif "BOOL" in tipo:
            valores[columna.name] = False
        elif "JSON" in tipo:
            valores[columna.name] = {}
        elif "TIMESTAMP" in tipo or "DATE" in tipo:
            valores[columna.name] = dt.datetime.now(dt.timezone.utc)
        else:
            valores[columna.name] = uuid4().hex[:8]
    fila = modelo(**valores)
    db.add(fila)
    db.flush()
    return fila


def _modelo_de_tabla(nombre_tabla: str) -> Any:
    for mapper in Base.registry.mappers:
        if mapper.class_.__table__.name == nombre_tabla:
            return mapper.class_
    return None


@contextmanager
def _cliente(nombre: str) -> Iterator[tuple[Any, Any]]:
    """El servicio levantado **con su ciclo de vida**, no solo montado.

    El `with` importa: `TestClient` solo ejecuta el arranque de la aplicación si
    se usa como gestor de contexto, y en el arranque es donde el servicio instala
    sus garantías. La primera versión de esta prueba no lo hacía y probaba una
    aplicación a medio arrancar — lo que, dicho sea de paso, es exactamente cómo
    se encontró el fallo del guard: la prueba fallaba por el motivo equivocado y
    al buscar por qué apareció el de verdad.
    """
    from crmcore.service import crear_servicio

    modulo = __import__(f"services.{nombre}.api", fromlist=["ROUTERS"])
    app = crear_servicio(
        nombre=nombre,
        descripcion=f"{nombre} para el fuzzing entre tenants",
        routers=modulo.ROUTERS,
        necesita_bus=False,
    )
    with TestClient(app) as cliente:
        yield app, cliente


def _cabeceras(tenant_id: UUID) -> dict[str, str]:
    """Identidad firmada de un administrador del tenant dado.

    Con `*:*` a propósito: si se probara con permisos justos, un 403 por falta
    de permiso taparía un aislamiento roto y la prueba pasaría por el motivo
    equivocado.
    """
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )


def _cuerpo_minimo(metodo: str) -> dict[str, Any]:
    """Cuerpo vacío para las escrituras.

    Un 422 por cuerpo mal formado también vale como «no ha llegado al dato»,
    pero se manda `{}` para que la validación de esquema no tape el caso: lo que
    no puede pasar es un 200 o un 403.
    """
    return {} if metodo in ("PATCH", "PUT", "POST") else {}


@pytest.mark.db
@pytest.mark.parametrize("servicio", SERVICIOS)
def test_ninguna_ruta_deja_ver_un_registro_de_otro_tenant(
    servicio: str, db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    modelos = _modelos_por_nombre()

    sin_resolver: list[str] = []
    filtradas: list[str] = []
    probadas = 0

    with _cliente(servicio) as (app, cliente):
        for metodo, plantilla, parametro in _rutas_con_id(app):
            etiqueta = f"{metodo} {plantilla}"
            if etiqueta in EXENTAS:
                continue
            if parametro in PARAMETROS_NO_FILA:
                continue
            if not parametro.endswith("_id"):
                continue

            nombre_objeto = ALIAS_MODELO.get(parametro, parametro[: -len("_id")])
            modelo = modelos.get(nombre_objeto)
            if modelo is None:
                sin_resolver.append(f"{etiqueta} (parámetro «{parametro}»)")
                continue

            # La fila es del tenant A…
            fila = _crear_fila(db, modelo, tenant_id)
            db.commit()
            ruta = plantilla.replace(f"{{{parametro}}}", str(fila.id))

            # …y quien pregunta es el B.
            respuesta = cliente.request(
                metodo,
                ruta,
                headers=_cabeceras(otro_tenant_id),
                json=_cuerpo_minimo(metodo),
            )
            probadas += 1

            if respuesta.status_code in (200, 201, 204):
                filtradas.append(f"{etiqueta} → {respuesta.status_code} (VE EL REGISTRO AJENO)")
            elif respuesta.status_code == 403:
                filtradas.append(f"{etiqueta} → 403 (confirma que existe; debe ser 404)")

    assert not filtradas, "Rutas que filtran la existencia de un registro ajeno:\n  " + "\n  ".join(
        filtradas
    )
    assert not sin_resolver, (
        f"Rutas de «{servicio}» con identificador cuyo objeto no se ha podido resolver, "
        "así que NO se están probando:\n  "
        + "\n  ".join(sin_resolver)
        + "\n\nAñade el parámetro a PARAMETROS_NO_FILA con su motivo, o nombra el "
        "parámetro como el modelo (`cuenta_id` → `Cuenta`)."
    )
    assert probadas > 0, f"«{servicio}» no ha probado ninguna ruta: la suite no cubre nada"


@pytest.mark.db
def test_la_suite_cubre_una_cantidad_de_rutas_que_no_puede_bajar(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    """Un suelo, para que la cobertura no se desplome sin que nadie lo note.

    Sin este número, bastaría con que alguien renombrara un parámetro para que
    media suite dejara de probar y todo siguiera en verde. El número se sube
    cuando crece; bajarlo tiene que ser una decisión escrita en un commit.
    """
    total = 0
    for servicio in SERVICIOS:
        with _cliente(servicio) as (app, _):
            total += sum(
                1
                for _m, _r, p in _rutas_con_id(app)
                if p.endswith("_id") and p not in PARAMETROS_NO_FILA
            )
    assert total >= 40, f"Solo {total} rutas con identificador; antes había al menos 40"


@pytest.mark.db
def test_un_identificador_inventado_tambien_da_404(db: Any, tenant_id: UUID) -> None:
    """La otra mitad: «no existe» y «no es tuyo» tienen que ser indistinguibles
    desde fuera. Si un id inexistente diera 404 y uno ajeno 403, la diferencia
    sería la fuga."""
    with _cliente("party") as (_app, cliente):
        respuesta = cliente.get(f"/api/v1/accounts/{uuid4()}", headers=_cabeceras(tenant_id))
    assert respuesta.status_code == 404


@pytest.mark.db
def test_un_registro_propio_si_se_ve(db: Any, tenant_id: UUID) -> None:
    """El control de la suite. Sin esto, un servicio que devolviera 404 a todo
    —porque la ruta está rota— pasaría el fuzzing con matrícula de honor."""
    from services.party.modelos import Cuenta

    cuenta = _crear_fila(db, Cuenta, tenant_id)
    db.commit()
    with _cliente("party") as (_app, cliente):
        respuesta = cliente.get(f"/api/v1/accounts/{cuenta.id}", headers=_cabeceras(tenant_id))
    assert respuesta.status_code == 200, respuesta.text
