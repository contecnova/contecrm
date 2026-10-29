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
#   27-10-2026  413 de 778  segundo grupo de paneles en la misma pantalla,
#                            con la misma medida detras: de las 426 rutas que
#                            seguian sin puerta, 52 eran otras cinco
#                            preguntas repetidas en los catorce servicios
#                            —cuanto se perderia ahora (RPO real), si la
#                            retencion llega hasta donde se pide, que
#                            particiones faltan por crear y si hay boveda para
#                            tokenizar—. Dos capacidades mas declaradas:
#                            recuperacion a un punto en el tiempo por tenant y
#                            tokenizacion de datos de pago. Medido con la
#                            sonda corregida —la primera mezclaba total por
#                            ocurrencias con pendientes por rutas unicas y su
#                            numero no se podia comparar con nada—: 426 -> 374
#   27-10-2026  412 de 778  el boton de exportar un listado. Estaba TODO hecho
#                            menos el boton: el servidor publica
#                            `{coleccion}/exportar` en setenta colecciones, con
#                            los filtros de la URL, las columnas propias del
#                            tenant, la misma proyeccion por rol que el
#                            listado, la marca de origen y el paso de
#                            reverificacion; y el manual de usuario lo describe
#                            entero desde hace meses. Cero botones. Con uno
#                            —leido de la superficie, no de una lista— ganan
#                            puerta 54 colecciones. Y se cerro de paso el
#                            hueco que quedaba: en `csv` el recorte no se
#                            decia en ninguna parte, asi que el fichero salia
#                            cortado EN SILENCIO
#   27-10-2026  404 de 778  la pantalla de un objeto del modelo de datos. La
#                            familia entera —campos, validaciones, tipos de
#                            registro, limites del esquema, trazabilidad de
#                            quien puso cada campo— estaba publicada y sin
#                            puerta: el modulo listaba los objetos y ahi se
#                            acababa, porque la fila no abria. Y no bastaba
#                            con marcarla abrible: las rutas hijas se dirigen
#                            por NOMBRE y la ficha generica pasa el
#                            identificador, asi que cada panel habria salido
#                            en 404 —peor que no tenerlo—. La pantalla abre
#                            por identificador, lee el nombre y con el pide lo
#                            demas. Ocho capacidades
#   27-10-2026  401 de 778  la firma electronica. Veintidos rutas publicadas y
#                            cero pestanas: los sobres, sus firmantes, sus
#                            recordatorios, su cancelacion y su evidencia
#                            legal. Con `objeto` en el listado, las acciones
#                            sobre un sobre las resuelve sola la ficha desde
#                            la superficie, asi que el bloque es una pestana y
#                            una pantalla: la de «pendiente de firma», que
#                            contesta la pregunta de quien cierra un trimestre
#                            —que contratos estan parados y por quien— y que
#                            el servidor sabia responder desde el primer dia
#   28-10-2026  397 de 778  la pantalla de «preguntar al sistema». El agente
#                            autonomo estaba entero por debajo —plan,
#                            aprobacion por riesgo, tope, presupuesto y
#                            reversion paso a paso— y lo unico que se veia de
#                            el era una fila en un listado de administracion
#                            con un boton de apagar. Ahora se le escribe lo
#                            que se necesita, se lee el plan ANTES de que pase
#                            nada, se autoriza paso a paso y se deshace. Eso
#                            es lo que enseña `CRM-05.02.03.05` —la actuacion
#                            y su reversion—, que hasta hoy no la enseñaba
#                            ninguna. De las cuatro que baja el tope, UNA es
#                            esta: las otras tres ya estaban declaradas y el
#                            tope se habia quedado alto. Medido antes de
#                            tocar nada: 398
#   28-10-2026  395 de 778  las dos preguntas que se hacen cuando la suite de
#                            productividad falla, y que el servidor contestaba
#                            desde el primer dia sin que hubiera donde
#                            hacerlas: «esto no conecta, que falta
#                            exactamente» —que es lo que evita que una
#                            implantacion se atasque una semana probandolo
#                            todo y acabe pidiendo permisos de administrador
#                            global «para descartar»— y «si lo desconecto, que
#                            me llevo y que se queda», que nadie se atreve a
#                            hacer sin saberlo. Las 29 operaciones de la suite
#                            son casi todas POST —calculadoras, no listados—,
#                            asi que lo que falta ahi no son pestanas: son las
#                            preguntas concretas que alguien se hace
#   28-10-2026  394 de 778  «no puedo entrar: por donde le toca» —a que
#                            proveedor le toca un correo, que el usuario no
#                            sabe contestar porque el sabe su correo, no si su
#                            empresa usa Entra ID o Ping—. Y de paso, sin
#                            bajar el tope porque ya estaba declarada, las
#                            excepciones de segregacion con su motivo y su
#                            caducidad: el informe marcaba «con excepcion» y
#                            no habia forma de leer POR QUE estaban
#                            permitidas, que es la pregunta siguiente de
#                            cualquier auditor
#   28-10-2026  392 de 778  las dos de configurar el modelo sin sorpresas:
#                            «que pasaria si publicas esto» —a cuantos
#                            registros afecta y cuantos se quedarian sin
#                            rellenar, con la diferencia entre «no se ha
#                            podido contar» y «no afecta a nadie», que se
#                            pintaban igual y significan lo contrario— y
#                            llevarse la configuracion a otro entorno, que se
#                            exporta, se SIMULA y solo despues se aplica. Sin
#                            ellas, promover un cambio era rehacerlo a mano en
#                            el otro entorno, que es como los dos entornos
#                            dejan de parecerse
#   28-10-2026  391 de 778  el registro de llamadas al proveedor de firma. No
#                            era una pantalla que faltara: era un AGUJERO. La
#                            tabla se escribia en cada llamada —la capacidad
#                            dice «para conciliar la factura»— y NINGUNA ruta
#                            la devolvia, asi que no se podia leer. Ahora hay
#                            ruta y panel, con el gasto sumado —conciliar una
#                            factura con doscientos importes en pantalla es
#                            volver a sumarlos a mano— y las fallidas aparte
#                            con el suyo, porque un proveedor que cobra por
#                            intento hace que el importe y los sobres no
#                            cuadren
#   28-10-2026  383 de 778  «que impide que una empresa vea a otra», arriba del
#                            todo en Seguridad. Las ocho estaban construidas y
#                            probadas, y a ninguna se llegaba desde una
#                            pantalla: para saber si el aislamiento estaba de
#                            verdad puesto en una instalacion habia que
#                            escribir un script y leer `pg_roles` a mano. Se
#                            hizo, y lo que salio justifica la pantalla: 623
#                            tablas con RLS, FORCE y politica —esa mitad,
#                            completa— y el servicio conectando con un rol
#                            SUPERUSER, que se salta las politicas aunque esten
#                            en FORCE. De las tres capas que el manual promete
#                            quedaba una. Ahora se mide en cada carga, cada
#                            capa dice de donde sale su numero, y lo que no se
#                            puede medir en vivo —el fuzzing entre tenants, que
#                            es una suite— sale dicho como gate en vez de como
#                            visto bueno
#   28-10-2026  375 de 778  la suite por su DECLARACION y no solo por sus
#                            consecuencias. La consola enseñaba cuantas altas
#                            hubo y cuantas estan en cuarentena —el resultado—
#                            y no de que sale: con que direccion esta declarada
#                            cada herramienta, que rol de aqui es que rol de
#                            alli, que areas comparte el cliente y si el
#                            proveedor de identidad es uno para las tres. Un
#                            mapeo de roles que no se puede mirar no se puede
#                            revisar, y es justo donde se cuela que alguien
#                            entre de administrador en el gestor documental por
#                            ser comercial aqui. El panel tenia el mapeo y no
#                            lo mandaba. Y dos mas de leer-antes-de-hacer: QUE
#                            se aplicaria en cada herramienta —un «32 cambios»
#                            no se puede aprobar— y el certificado de cierre
#                            con sus palabras. NO se declara CRM-00.01.07.02
#                            —alta en cascada—: se ve lo aplicado y lo que se
#                            aplicaria, pero el alta se dispara por API
#   28-10-2026  368 de 778  «quien ve que, y por que», en Seguridad. El
#                            explicador contestaba «por que puede» y no «que
#                            decidiria cada capa»: ahora, con los MISMOS tres
#                            datos y sin un segundo formulario, se ve el
#                            veredicto, el rol y los atributos POR SEPARADO —un
#                            «no puede» sin decir cual de las dos lo impide
#                            manda a cambiar el rol cuando lo que corta es una
#                            politica— y el contexto con el que se evaluo, que
#                            es lo unico que permite reproducirlo. Y debajo,
#                            los campos que no se comportan como dice su
#                            clasificacion: SE PODIAN ESCRIBIR Y NO LEER, y la
#                            propia ruta que los crea justifica escribirlos con
#                            que «una excepcion que vive en la cabeza de quien
#                            la pidio es la que nadie revisa al año siguiente»
#   28-10-2026  365 de 778  la ficha de un modulo vertical instalado: su
#                            manifiesto —que estaba guardado ENTERO y la ficha
#                            devolvia cuatro campos—, su espacio de nombres,
#                            de que depende, su huella, si sigue siendo el que
#                            se instalo y que parte se usa de verdad. Siete.
#                            Y un arreglo de ESTA MISMA PRUEBA que va en
#                            sentido contrario: los parrafos de «lo que esta
#                            pantalla NO declara» contaban como declaracion,
#                            asi que escribir «esta pantalla NO ensena CRM-X»
#                            cerraba CRM-X. Ocho capacidades constaban con
#                            pantalla por ese motivo y por ningun otro, en
#                            cinco pantallas, cuatro de ellas de antes de hoy.
#                            La honestidad del texto volvia deshonesta la
#                            cuenta. Arreglado, vuelven a contarse: 7 cerradas
#                            menos 4 que reaparecen
#   28-10-2026  360 de 778  con que se firma, debajo de lo que esta parado:
#                            los proveedores con sus niveles eIDAS y sus
#                            formas de identificar al firmante, las reglas que
#                            deciden cual sale para cada documento y con que
#                            nivel minimo, y las plantillas con su plazo. Las
#                            dos ultimas SE PODIAN ESCRIBIR Y NO LEER, igual
#                            que las excepciones de campo: una regla decide
#                            con que proveedor y con que nivel sale un
#                            contrato, y «¿por que esto se firmo con un clic?»
#                            habia que contestarlo mirando la base de datos.
#                            Las reglas salen POR PRIORIDAD y no por nombre,
#                            que es como se aplican, y las apagadas se ven:
#                            una regla apagada es lo que explica que algo
#                            dejara de pasar
#   28-10-2026  355 de 778  la explotacion delegada. Cuatro las HACIA YA y no
#                            las declaraba —canjea la credencial por un token
#                            del usuario, registra el CRM como fuente, guarda y
#                            publica preguntas y explica la degradacion
#                            diciendo que SIGUE funcionando— y la quinta no
#                            existia en el front: preguntar sobre el registro
#                            que se esta mirando, desde su ficha. Esa se hace
#                            delante del dato, que es donde se le ocurre a
#                            alguien, y ENSEÑA EL FILTRO con el que se
#                            contesto: un numero que parece de toda la empresa
#                            y es de una cuenta no cuadra con nada en la
#                            reunion siguiente, y para cuando se descubre ya se
#                            ha dicho en voz alta
#   28-10-2026  354 de 778  los informes programados. Se podia programar un
#                            envio y no leer ninguna de sus cuatro cosas: ni
#                            quien lo recibe, ni cuando, ni en que formato, ni
#                            si uno que ya no mira nadie se sigue mandando
#                            todas las semanas. Los destinatarios se cuentan Y
#                            se nombran, porque la pregunta real es «¿a quien
#                            le esta llegando esto?» y un numero no la
#                            contesta. De paso se quito un aviso de
#                            «programaciones huerfanas» que yo mismo habia
#                            inventado: la clave ajena borra en cascada y el
#                            informe no tiene borrado blando, asi que no pueden
#                            existir — y queda prueba de ESO, para el dia en
#                            que alguien pase el informe a borrado blando
#   29-10-2026  353 de 778  donde puede vivir el CRM embebido. Se podia
#                            declarar y no leer, Y ES UN CONTROL DE SEGURIDAD:
#                            la lista de origenes es lo que impide que
#                            cualquier pagina lo incruste y le pida datos con
#                            la sesion de quien la abra. Un origen que alguien
#                            puso para una prueba hace año y medio sigue
#                            valiendo y nadie lo sabe. Los origenes se NOMBRAN
#                            y no se cuentan —lo que se revisa es si alguno
#                            sobra, y un «3 origenes» no deja revisar nada— y
#                            se dice que bloques puede pedir cada anfitrion,
#                            que es la otra mitad del control
#   29-10-2026  351 de 778  quien decide por quien, y con que enlaces. Dos
#                            puertas sin vuelta mas: se podia delegar la firma
#                            y no leerlo —«¿quien tiene hoy la de direccion?»
#                            es la pregunta de cualquier revision de poderes, y
#                            una delegacion puesta para agosto sigue viva en
#                            marzo— y se emitian enlaces que permiten aprobar
#                            SIN entrar al CRM sin forma de contarlos. El token
#                            no sale: en la base solo esta su hash, y ese es el
#                            punto. De paso, la prueba que las pide POR LA RUTA
#                            cazo que `GET /{aprobacion_id}` iba delante y se
#                            tragaba «delegaciones» con un 422 de UUID: llamando
#                            a la funcion eso no se ve
TOPE_SIN_PANTALLA = 351


def _es_pantalla(p: Path) -> bool:
    texto = str(p)
    return "/pruebas/" not in texto and ".test." not in texto


# Los párrafos en los que una pantalla dice lo que **no** enseña. Existen
# porque declarar lo que no se hace es justo lo que esta prueba impide, y son
# buena prosa — pero el identificador que nombran estaba contando como
# declarado. Es decir: escribir «esta pantalla NO enseña CRM-X» cerraba
# CRM-X. La honestidad del texto volvía deshonesta la cuenta.
#
# Medido el 28-10-2026: **ocho capacidades** constaban con pantalla por este
# motivo y por ningún otro, en cinco pantallas. Cuatro venían de antes.
RE_NO_DECLARA = re.compile(
    r"(?:\*\*no\*\* declara|no declara, aunque lo roce|NO declara)(?:.|\n)*?(?=\n \*\n|\n \*/)",
    re.IGNORECASE,
)


@functools.cache
def _ids_del_front() -> frozenset[str]:
    """Los identificadores que una pantalla dice enseñar.

    Se quitan antes los párrafos de «lo que esta pantalla **no** declara»: lo
    que nombran es precisamente lo que NO tiene pantalla, y contarlo al revés
    convierte el aviso en el atajo. Quien escribe esa prosa está siendo
    cuidadoso; la cuenta tiene que premiarlo, no aprovecharse.
    """
    partes = []
    for p in FRONT.rglob("*.ts*"):
        if not _es_pantalla(p):
            continue
        partes.append(RE_NO_DECLARA.sub(" ", p.read_text(encoding="utf-8", errors="ignore")))
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
