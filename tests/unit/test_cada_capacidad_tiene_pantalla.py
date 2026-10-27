"""De cada capacidad hecha se tiene que llegar a una pantalla (CRM-07.04.05.02).

El informe de cobertura que ya había mide **operaciones publicadas**: cuántas
rutas de la API tienen pantalla. Es útil y no contesta la pregunta que importa,
que es la del catálogo: **qué sabe hacer el CRM que ninguna pantalla enseña**.

La diferencia no es formal. Una pantalla genérica lista `/api/v1/webhooks` y con
eso cubre la operación; que además enseñe la cola de fallidos, el reenvío y el
catálogo de eventos —tres capacidades distintas del catálogo— no lo dice nadie.
Y al revés: hay capacidades enteras cuya única puerta es la API, y quien mira el
producto concluye que no están.

**El mecanismo es el mismo que el de las pruebas que citan por identificador**, y
por el mismo motivo: declarar obliga a mirar la pantalla. Una declaración se
escribe en un minuto; escribirla sin abrir la pantalla es tan posible aquí como
allí, y lo que lo hace caro es que la declaración **se enseña en el producto**
—la pantalla de cobertura la pinta—, así que una falsa la ve el primero que
entra.

El tope sólo baja. Cada bajada va en el mismo commit que la pantalla o la
declaración que la justifica, con una línea diciendo qué se miró.

NO cuentan los ficheros de prueba del front: una prueba no es una pantalla, y
contarlas haría que citar un identificador en un test «cubriera» la capacidad
sin que nadie la enseñe.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
FRONT = RAIZ / "frontend" / "src"
RE_ID = re.compile(r"CRM-\d\d\.\d\d\.\d\d\.\d\d")

# ── Histórico. Cada línea, el bloque que la bajó ──────────────────────────
#
#   26-10-2026  684 de 753  medido por primera vez. El informe de cobertura
#                            que habia mide operaciones publicadas; este mide
#                            CAPACIDADES, que es lo que se vende y lo que el
#                            catalogo enumera. Solo 69 tenian una pantalla que
#                            las nombrara, y 53 de esas 69 son las propias
#                            capacidades de front: o sea que de todo lo demas
#                            que sabe hacer el CRM, 16 capacidades estaban
#                            declaradas en alguna pantalla. Las de `docs`
#                            quedan fuera del recuento
#   26-10-2026  540 de 753  declarado lo que ya se ensena: los 24 modulos
#                            genericos declaran ahora la lista de capacidades
#                            de PRODUCTO que se ven en ellos —no solo cual de
#                            front es la pantalla— y siete pantallas a medida
#                            (portada, ficha de cliente, tablero de embudo,
#                            bandeja de aprobaciones, gobierno de la suite,
#                            estado y rendimiento) dicen lo suyo en su
#                            cabecera. La lista se PINTA en la pantalla, que es
#                            lo unico que hace caro declarar algo que no se
#                            ensena. 144 capacidades en un bloque, ninguna
#                            pantalla nueva: estaban todas construidas y no lo
#                            decia nadie
#   27-10-2026  510 de 753  el bloque de «la pantalla toca lo que dice que
#                            ensena»: cinco listados de aislamiento y
#                            residencia en Tenants, las aprobaciones del motor
#                            en Procesos, los encargos a proveedor con sus
#                            tres vistas derivadas y sus dos acciones de
#                            coleccion mas las plantillas de documento y la
#                            firma presencial en Operacion, los creditos de
#                            servicio y el cumplimiento de SLA en Casos, los
#                            recorridos en Campanas y los activos en
#                            Contenido. Y pantalla propia para la
#                            conversacion: responder, nota interna, cambio de
#                            canal y escalado a persona estaban publicados y
#                            probados sin un solo boton que los llamara, y la
#                            cola de la consola de agente enlazaba a una ruta
#                            que no existia
#   27-10-2026  505 de 753  pantalla de identidad y seguridad: las cuatro
#                            preguntas que el modulo generico no puede
#                            contestar porque no son tablas —quien no tiene
#                            segundo factor con la LISTA de los que faltan y
#                            no un porcentaje, que certificado del IdP caduca,
#                            quien tiene hoy permisos incompatibles y por que
#                            esta persona puede hacer esto—. Las cuatro tenian
#                            extremo publicado y ninguna tenia puerta
#   27-10-2026  494 de 753  gobierno de la IA. `/api/v1/ia` publica 71
#                            operaciones y la unica pantalla de inteligencia
#                            que habia ensena la salud de UNA cuenta: quien
#                            presta el servicio y en que region, que modelos
#                            hay con sus metricas y su deriva, que agentes
#                            estan sueltos con sus permisos y su presupuesto,
#                            que bloquearon las guardias y cuanto cuesta todo
#                            no tenian puerta. Lo que NO se ha fingido:
#                            transcripciones, variantes, voz y sugerencias de
#                            caso son extremos de analisis, no listados, y su
#                            sitio es dentro de la actividad o del caso
#   27-10-2026  458 de 753  dos cosas a la vez, y conviene no confundirlas.
#                            SIETE son pantalla de verdad: la consola de
#                            administracion declara lo que pinta y solo ella
#                            —claves de cifrado del cliente, flags, plantillas,
#                            calendarios, monedas, reglas de comparticion y
#                            buzones—, que se ve porque el servidor etiqueta
#                            esas operaciones como de administracion y la
#                            consola se construye de ahi.
#                            VEINTINUEVE salen del recuento porque su
#                            entregable NO es una pantalla: GraphQL, gRPC,
#                            idempotencia, ETag, paginacion por cursor,
#                            Problem Details, firma HMAC, entrega al menos una
#                            vez, CDC, ordenacion por agregado, BFF, SDK,
#                            mTLS, service mesh, outbox y las garantias del
#                            motor. Cada una con su motivo escrito en el
#                            catalogo, y hay una prueba que exige que el
#                            motivo sea una frase y no repita el enunciado:
#                            marcar es la salida barata y tiene que costar
#   27-10-2026  431 de 753  quince mas fuera del recuento con su motivo
#                            —telemetria, continuidad, rendimiento y los
#                            compromisos: los ejecuta y los vigila quien opera
#                            la plataforma, no hay palanca dentro del
#                            producto— y doce declaradas de verdad. Seis en
#                            Procesos: el disparador, las acciones y el
#                            momento de una automatizacion son campos de su
#                            propio registro, y la instancia lleva su espera y
#                            su proceso padre. Y seis en Cuentas, con arreglo
#                            de por medio: el modelo tenia diez columnas que
#                            el contrato NO devolvia —ABC, es_personal,
#                            frecuencia, horario, estado del correo y del
#                            telefono, canales y correo secundario—, asi que
#                            la pantalla no podia ensenarlas por mucho que
#                            existieran
#   27-10-2026  426 de 753  el mismo hallazgo de las columnas que no salen,
#                            llevado a actividades, leads y oportunidades: 29
#                            columnas mas que existian en la tabla y el
#                            esquema de lectura no devolvia. Una reunion
#                            llegaba a la pantalla SIN HORA —`inicio_at` y
#                            `fin_at` no salian—, un lead sin su campana ni
#                            sus UTM ni su primer toque, y una oportunidad sin
#                            el competidor que la gano, sin la nota de perdida
#                            y sin la probabilidad puesta a mano. Cinco
#                            capacidades declaradas con eso arreglado
#   27-10-2026  426 de 755  dos capacidades NUEVAS construidas, no
#                            declaradas: solo lectura por condicion y por
#                            procedencia, y la granularidad del campo de
#                            fecha. Las dos se configuran en el formulario del
#                            propio campo, en Modelo de datos, asi que el
#                            recuento no sube pese a que el catalogo tiene dos
#                            capacidades hechas mas
#   27-10-2026  415 de 778  pantalla de Plataforma y cumplimiento. Lo que la
#                            destapo fue medir el contrato publicado contra el
#                            front: 477 colecciones GET sin un solo boton, y
#                            170 de ellas la MISMA ruta repetida en los
#                            catorce servicios —papelera, rastro,
#                            cumplimiento, restauracion, volumen,
#                            tokenizacion—. Lo evidente, una pestana por
#                            servicio y familia, son setenta y ocho pestanas
#                            que dicen lo mismo. Con un selector de servicio
#                            arriba y cuatro preguntas debajo se cubren diez
#                            capacidades: el audit trail inmutable, la
#                            auditoria de cambios de configuracion y permisos,
#                            su volcado al SIEM, su consulta desde la propia
#                            plataforma, el DLP de exportaciones, el RAT, el
#                            informe de cumplimiento, la matriz de permisos y
#                            la restauracion selectiva
TOPE_SIN_PANTALLA = 415


def _es_pantalla(p: Path) -> bool:
    texto = str(p)
    return "/pruebas/" not in texto and ".test." not in texto


@functools.cache
def _ids_del_front() -> frozenset[str]:
    partes = [
        p.read_text(encoding="utf-8", errors="ignore")
        for p in FRONT.rglob("*.ts*")
        if _es_pantalla(p)
    ]
    return frozenset(RE_ID.findall("\n".join(partes)))


@functools.cache
def _capacidades_hechas() -> tuple[dict, ...]:
    catalogo = yaml.safe_load((RAIZ / "docs/catalogo/catalogo.yaml").read_text(encoding="utf-8"))
    return tuple(
        cap
        for modulo in catalogo["modulos"]
        for seccion in modulo["secciones"]
        for funcion in seccion["funciones"]
        for cap in funcion["capacidades"]
        # Las de `docs` quedan fuera: su entregable ES el documento, y una
        # pantalla que «enseñe el manual» ya existe —la ayuda en producto—,
        # así que exigirles declaración sería contar dos veces lo mismo.
        #
        # Y las que llevan `sin_pantalla_porque` en el catálogo: su entregable
        # no es una pantalla. La regla es estrecha a propósito —**no hay nada
        # que una persona pueda ver ni hacer**: un protocolo, una garantía del
        # servidor, una propiedad de la arquitectura— y el motivo va escrito
        # capacidad a capacidad, en el catálogo, que es donde se revisa. Si un
        # administrador podría querer ver su estado, es pantalla y se queda.
        if cap.get("estado") == "hecho"
        and cap.get("svc") != "docs"
        and not cap.get("sin_pantalla_porque")
    )


@functools.cache
def _excluidas() -> tuple[dict, ...]:
    catalogo = yaml.safe_load((RAIZ / "docs/catalogo/catalogo.yaml").read_text(encoding="utf-8"))
    return tuple(
        cap
        for modulo in catalogo["modulos"]
        for seccion in modulo["secciones"]
        for funcion in seccion["funciones"]
        for cap in funcion["capacidades"]
        if cap.get("sin_pantalla_porque")
    )


@functools.cache
def _sin_pantalla() -> tuple[str, ...]:
    vistas = _ids_del_front()
    return tuple(c["id"] for c in _capacidades_hechas() if c["id"] not in vistas)


def test_sacar_una_capacidad_del_recuento_cuesta_un_motivo() -> None:
    """La salida de emergencia, cerrada con llave.

    Marcar una capacidad como «no es pantalla» baja el tope sin construir nada,
    así que tiene que costar: el motivo va escrito, es largo —una frase, no una
    palabra— y **no puede ser el propio enunciado**, que sería no haber pensado
    nada. Sin esto, el camino barato para bajar el número es marcarlo todo.
    """
    flojos: list[str] = []
    for cap in _excluidas():
        motivo = str(cap.get("sin_pantalla_porque", ""))
        if len(motivo) < 60:
            flojos.append(f"{cap['id']}: el motivo tiene {len(motivo)} caracteres")
        elif motivo.strip().lower() in str(cap.get("t", "")).strip().lower():
            flojos.append(f"{cap['id']}: el motivo repite el enunciado")
    assert not flojos, "Motivos que no explican nada:\n  " + "\n  ".join(flojos)
    # Y que esto no esté midiendo el vacío.
    assert len(_excluidas()) >= 20, len(_excluidas())


def test_el_recorrido_mira_de_verdad() -> None:
    """Primero, que esto no esté midiendo el vacío.

    Si `FRONT` dejara de existir o el patrón dejara de casar, el recuento
    saldría cero y el gate pasaría en verde sin haber abierto un fichero. Ya
    pasó con el de las pruebas y por eso está escrito aquí también.
    """
    assert len(_capacidades_hechas()) > 700, len(_capacidades_hechas())
    assert len(_ids_del_front()) > 50, sorted(_ids_del_front())
    assert (FRONT / "lib" / "modulos.ts").exists()


def test_las_pruebas_del_front_no_cuentan() -> None:
    """Una prueba no es una pantalla.

    Se comprueba plantando el caso malo: hay identificadores que **sólo**
    aparecen en ficheros de prueba del front, y ninguno de ellos puede estar
    contado como «tiene pantalla».
    """
    solo_en_pruebas = set()
    for p in FRONT.rglob("*.ts*"):
        if _es_pantalla(p):
            continue
        solo_en_pruebas |= set(RE_ID.findall(p.read_text(encoding="utf-8", errors="ignore")))
    solo_en_pruebas -= _ids_del_front()
    assert solo_en_pruebas, "no hay ningún id que viva sólo en pruebas: el caso malo no se planta"
    assert not (solo_en_pruebas & set(_ids_del_front()))


def test_el_tope_de_capacidades_sin_pantalla_solo_baja() -> None:
    """Y que el tope no se quede atrás de la realidad.

    Las dos mitades: no puede subir —una capacidad que pierde su pantalla es
    una regresión— y no puede quedarse muy por encima, porque un tope con
    holgura deja entrar la siguiente sin que nadie se entere.
    """
    cuantas = len(_sin_pantalla())
    assert cuantas <= TOPE_SIN_PANTALLA, (
        f"Hay {cuantas} capacidades hechas que ninguna pantalla nombra, y el "
        f"tope medido eran {TOPE_SIN_PANTALLA}. Si has marcado algo «hecho», "
        f"declara en qué pantalla se ve:\n  " + "\n  ".join(sorted(_sin_pantalla())[:20])
    )
    assert cuantas >= TOPE_SIN_PANTALLA - 3, (
        f"Hay {cuantas} y el tope dice {TOPE_SIN_PANTALLA}: bájalo en este mismo "
        f"commit y di en el histórico qué pantalla lo justifica."
    )


@pytest.mark.parametrize("modulo", ["00", "07"])
def test_el_informe_reparte_por_modulo(modulo: str) -> None:
    """El total no sirve para repartir el trabajo: hace falta saber de qué
    módulo son. 703 es un número para un informe; «59 del módulo de
    multi-tenancy» es un número para una tarde."""
    del_modulo = [i for i in _sin_pantalla() if i.startswith(f"CRM-{modulo}.")]
    assert del_modulo or modulo == "07", f"módulo {modulo} sin huecos, revisa el tope"
