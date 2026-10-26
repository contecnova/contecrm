"""Desde una capacidad se puede llegar al código; a una prueba, no siempre.

El gate del catálogo exige que toda capacidad `hecho` esté **citada** por su ID
y **documentada** en un manual. Eso convierte el catálogo en trazabilidad de
verdad… hasta el código. De ahí a una prueba no hay camino: la cita vale esté
donde esté, y en 227 de 752 casos no hay ninguna prueba que nombre el ID.

**Esto NO dice que esas 227 estén sin probar, y es importante no leerlo así.**
Comprobadas a mano dos al azar: el aislamiento estanco por partner
(`CRM-03.04.01.03`) y el opt-out de entrenamiento (`CRM-05.02.02.09`) tienen
pruebas de sobra — lo que no tienen es el identificador escrito en ellas. Lo que
falta es el último tramo de la cadena, no la red.

Lo que cuesta: en una auditoría la pregunta no es «¿está probado?» sino
«enséñame la prueba de ESTO». Sin el ID en la prueba hay que saberse el código
para contestar, y quien audita no se lo sabe — así que la respuesta acaba siendo
«confía en nosotros».

Por eso esto es un TOPE y no una exigencia: reescribir doscientos ficheros de prueba de
golpe sería un commit que nadie puede revisar, y la mitad de las citas saldrían
puestas a ojo. Lo que no puede es crecer: una capacidad nueva nace con su prueba
citada, y las viejas se van citando cuando se las toque.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]

# Cuántas capacidades `hecho` no las nombra ninguna prueba. Sólo puede BAJAR.
#
#   11-10-2026  227 de 752  medición inicial — MAL: este fichero se contaba a
#                            sí mismo, así que el tope nacía con dos de hueco
#   11-10-2026  228 de 752  MAL otra vez: ese 228 lo saqué sumando tres a la
#                            medición anterior en vez de volver a medir
#   11-10-2026  227 de 752  medido, ejecutando el recorrido
#   26-10-2026  224 de 752  auditada la familia de entornos y despliegue
#                            (CRM-07.02.01): las tres que no citaba ninguna
#                            prueba —entornos separados, configuracion como
#                            codigo y gates de calidad— ya la tienen, y
#                            mirandolas salio un agujero de verdad: la
#                            referencia de Git se escribia y no se leia
#   26-10-2026  215 de 752  auditado el chat interno (CRM-06.02.02), las nueve
#                            capacidades recorridas por HTTP. Ocho estaban; la
#                            papelera NO EXISTIA —ni ruta de borrado, ni de
#                            recuperacion, ni retencion declarada en identity—
#                            y estaba contada como hecha
#   26-10-2026  208 de 752  auditada la familia de GRC (CRM-07.03.02), las diez
#                            capacidades recorridas por HTTP. La primera familia
#                            que sale entera SIN un hallazgo, y conviene que
#                            conste: una auditoria que siempre encuentra algo
#                            deja de significar nada
#   26-10-2026  199 de 752  auditada la familia de autorizacion
#                            (CRM-00.05.02): las nueve sin citar, mas la
#                            jerarquia replicada. Nada roto. Lo que se fija es
#                            la propiedad que justifica el subsistema entero:
#                            que el listado y la ficha digan LO MISMO, por dos
#                            caminos distintos —SQL y Python—
#   26-10-2026  191 de 752  auditado el motor de procesos (CRM-00.03.02). DOS
#                            hallazgos: una condicion sin atributo se tomaba
#                            SIEMPRE —el motor comparaba None con None y el «=»
#                            daba cierto—, y el enlace de un subproceso con su
#                            padre estaba en la fila y no salia por la API
#   26-10-2026  185 de 752  auditados los webhooks y el catalogo de eventos
#                            (CRM-00.02.02). Nada roto; lo que se fija es cada
#                            forma de fallar EN SILENCIO: el tipo mal escrito,
#                            la firma sin instante, el reenvio de algo viejo, el
#                            endpoint caido que sigue recibiendo y el replay sin
#                            tope
#   26-10-2026  179 de 752  auditada la firma electronica (CRM-06.01.02).
#                            HALLAZGO GORDO: `enviar` marcaba el sobre como
#                            enviado y NO llamaba al proveedor — el cliente no
#                            recibia nada y el CRM decia que estaba mandado
#   26-10-2026  160 de 752  los 19 modulos de la consola, recorridos abriendo
#                            sus 110 pestanas contra el servicio dueno. Todas
#                            contestan; el barrido queda porque lo caro es la
#                            pestana que se rompe el dia que alguien cambia un
#                            permiso, no mantener quince segundos de prueba
#   26-10-2026  153 de 752  cinco pantallas de operacion, pintadas con el
#                            contrato real. DOS hallazgos pequenos: el puesto
#                            decia cuantas conexiones estaban sin medir y no
#                            CUALES, y rendimiento decia que el sistema estaba
#                            bajo presion sin decir de quien ni quien no habia
#                            contestado
#   26-10-2026  150 de 752  tres pantallas de servicio, pintadas con el
#                            contrato real: la consola de agente, conocimiento
#                            e inteligencia
#   26-10-2026  146 de 752  lo que el cliente hace y lo que NO decide
#                            (CRM-07.04.02): clave de idempotencia, If-Match,
#                            la sesion en cookie, el Problem Details con su
#                            explicacion, los comodines de permiso entendidos
#                            igual que en el servidor y la CSP sin eval
#   26-10-2026  145 de 752  la localizacion del tenant (CRM-07.04.01.05).
#                            HALLAZGO: la ruta que la resuelve existia y el
#                            front no la leia — «es-ES» a mano en 16 sitios de
#                            5 ficheros, y los formateadores construidos al
#                            importar, o sea imposibles de cambiar
#   26-10-2026  144 de 752  la marca por tenant (CRM-07.04.01.04). HALLAZGO
#                            del mismo tipo que la localizacion: el servidor la
#                            guarda y la ruta solo devolvia el DIAGNOSTICO, asi
#                            que el front sacaba nombre, color y logotipo de
#                            config.json —que es del despliegue— y dos tenants
#                            de la misma instalacion compartian marca
#   26-10-2026  139 de 752  autenticacion (CRM-00.05.01): volver a entrar, las
#                            credenciales de maquina, las sesiones, el segundo
#                            factor y la federacion. Nada roto
#   26-10-2026  134 de 752  los contratos de API (CRM-00.02.01). Con sello del
#                            contrato publicado —2.396 operaciones— para que
#                            la compatibilidad hacia atras no se rompa en
#                            silencio: no se rompe con un error, se rompe y se
#                            entera el cliente de otro el dia del despliegue
#   26-10-2026  129 de 752  la automatizacion low-code (CRM-00.03.03).
#                            HALLAZGO: las variables finales se metian dentro
#                            de `decisiones`, que es una LISTA, asi que toda
#                            regla que SI cumplia sus condiciones reventaba con
#                            «list object is not a mapping»
#   26-10-2026  125 de 752  integracion y conectividad (CRM-00.03.04), cuatro
#                            de cinco. La quinta —funciones de transformacion y
#                            validacion en el mapeo— NO ESTA: el mapeo copia
#                            valores por ruta y nada mas. Queda avisado y sin
#                            construir, que es funcionalidad nueva
#   26-10-2026  121 de 752  configuracion y metadatos por tenant
#                            (CRM-00.01.04): la jerarquia de ajustes, el
#                            modelo extensible, los feature flags y los
#                            secretos. Nada roto. Lo que se fija aqui es que
#                            `ui_densidad` —una de las cinco claves que llegan
#                            al usuario— recorre la escalera entera, que quitar
#                            el de arriba destapa el de abajo en vez de dejar
#                            un hueco, y que el proposito segmenta de verdad el
#                            almacen de secretos: la clave de las integraciones
#                            no abre los campos de cliente
#   26-10-2026  111 de 752  el aislamiento entre empresas y la puerta por la
#                            que se entra (CRM-00.01.01, CRM-00.01.02,
#                            CRM-00.02.04) mas la propiedad de datos por
#                            servicio, que ya la fijaba el gate de
#                            arquitectura y ahora la cita. Nada roto. Lo mas
#                            util que se fija: que las cabeceras de identidad
#                            que llegan de FUERA no pasan al servicio de
#                            detras —el gateway pone las suyas firmadas— y que
#                            una pista de tenant que contradice al token se
#                            rechaza, que es la via mas barata que existe para
#                            saltarse el aislamiento. QUEDA UN HUECO: los pools
#                            de computo dedicados (CRM-00.01.01.06) se
#                            declaran, se guardan y nadie los lee. Sin prueba
#                            que lo cite, a proposito, y avisado en su nota
TOPE_SIN_PRUEBA_QUE_LAS_NOMBRE = 111


@functools.cache
def _capacidades_hechas() -> tuple[dict, ...]:
    catalogo = yaml.safe_load((RAIZ / "docs/catalogo/catalogo.yaml").read_text(encoding="utf-8"))
    return tuple(
        cap
        for modulo in catalogo["modulos"]
        for seccion in modulo["secciones"]
        for funcion in seccion["funciones"]
        for cap in funcion["capacidades"]
        # Las de `docs` quedan fuera: su entregable ES el documento, y el propio
        # gate del catálogo ya las exime de tener código que citar.
        if cap.get("estado") == "hecho" and cap.get("svc") != "docs"
    )


@functools.cache
def _texto_de_las_pruebas() -> str:
    # ESTE FICHERO NO CUENTA. Su prosa nombra identificadores para explicar el
    # hallazgo, y contarlos haría que citarlos aquí «arreglara» capacidades sin
    # haber escrito una sola prueba: un guardián mirando su propio reflejo. Ya
    # pasó al medirlo —el número salía 225 en vez de 227— y por eso el tope
    # nacía con dos de hueco, que es exactamente lo que un tope no puede tener.
    trozos = [
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (RAIZ / "tests").rglob("*.py")
        if "__pycache__" not in str(p) and p.name != Path(__file__).name
    ]
    # Las del front cuentan: una capacidad de interfaz se prueba allí.
    trozos += [
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (RAIZ / "frontend" / "src").rglob("*.test.*")
    ]
    return "\n".join(trozos)


@functools.cache
def _sin_prueba_que_las_nombre() -> tuple[str, ...]:
    texto = _texto_de_las_pruebas()
    return tuple(c["id"] for c in _capacidades_hechas() if c["id"] not in texto)


def test_el_recorrido_mira_de_verdad() -> None:
    """Un recorrido que no lee las pruebas daría «ninguna citada», que es el
    mismo rojo que no citar ninguna — y uno que no lea el catálogo daría cero,
    que es el verde de no haber mirado."""
    assert len(_capacidades_hechas()) >= 700
    assert len(_texto_de_las_pruebas()) > 1_000_000
    # Y una que evidentemente está citada, para saber que el corpus se lee.
    assert "CRM-00.04.01.03" not in _sin_prueba_que_las_nombre()


def test_la_distancia_entre_el_catalogo_y_las_pruebas_no_crece() -> None:
    """Una capacidad nueva nace con su prueba citada. Las viejas se van citando
    cuando se las toque — no de golpe, que sería un commit irrevisable."""
    cuantas = len(_sin_prueba_que_las_nombre())
    assert cuantas <= TOPE_SIN_PRUEBA_QUE_LAS_NOMBRE, (
        f"Han subido a {cuantas} las capacidades `hecho` que no nombra ninguna "
        f"prueba; el tope medido eran {TOPE_SIN_PRUEBA_QUE_LAS_NOMBRE}. Si has "
        "declarado una capacidad hecha, cita su identificador en la prueba que "
        "lo demuestra."
    )


def test_el_tope_no_se_queda_alto_cuando_se_arregla() -> None:
    """Un tope que no baja deja sitio para que entre una nueva cada vez que se
    arregla otra, y entonces el número miente sin que nadie lo note."""
    cuantas = len(_sin_prueba_que_las_nombre())
    assert cuantas >= TOPE_SIN_PRUEBA_QUE_LAS_NOMBRE - 3, (
        f"Van {cuantas} y el tope dice {TOPE_SIN_PRUEBA_QUE_LAS_NOMBRE}: baja el "
        "tope en el mismo commit en que se arreglan, o el margen se lo come la "
        "siguiente que entre sin citar."
    )


def test_lo_declarado_hecho_sigue_citado_en_alguna_parte() -> None:
    """La comprobación que ya existía, repetida aquí a propósito: este tope sólo
    tiene sentido mientras la cita en el código siga siendo obligatoria. Si
    alguien aflojara aquélla, éste pasaría a medir la distancia a una cadena que
    ya está rota por el otro extremo."""
    gate = (RAIZ / "tests/unit/test_catalogo_trazabilidad.py").read_text(encoding="utf-8")
    assert "def test_lo_declarado_hecho_esta_citado_en_el_codigo" in gate
    assert "def test_lo_declarado_hecho_esta_documentado" in gate
