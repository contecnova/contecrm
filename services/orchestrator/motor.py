"""El motor: cómo se ejecuta un proceso, paso a paso y sin perder el hilo.

── Forma de una definición ───────────────────────────────────────────────────

    {
      "inicio": "crear_pedido",
      "pasos": {
        "crear_pedido": {
          "tipo": "servicio",
          "servicio": "sales", "operacion": "crear_pedido",
          "entrada": {"oportunidad_id": "@oportunidad_id"},
          "salida": "pedido",
          "compensacion": {"servicio": "sales", "operacion": "anular_pedido",
                           "entrada": {"pedido_id": "@pedido.id"}},
          "siguiente": "aprobar_si_grande"
        },
        "aprobar_si_grande": {
          "tipo": "decision",
          "condiciones": [
            {"si": {"atributo": "pedido.importe", "op": ">", "valor": 50000},
             "entonces": "aprobacion_director"}
          ],
          "si_no": "enviar_al_erp"
        },
        "aprobacion_director": {
          "tipo": "humano",
          "titulo": "Aprobar pedido de @pedido.importe €",
          "asignada_rol": "responsable_ventas",
          "opciones": ["aprobar", "rechazar"],
          "vence_en_horas": 48,
          "al_vencer": "escalar",
          "rutas": {"aprobar": "enviar_al_erp", "rechazar": "fin_rechazado"}
        },
        "enviar_al_erp": {"tipo": "servicio", "servicio": "integration",
                          "operacion": "enviar_pedido_erp",
                          "reintentos": 5, "siguiente": "fin_ok"},
        "fin_ok": {"tipo": "fin", "resultado": "completado"},
        "fin_rechazado": {"tipo": "fin", "resultado": "rechazado"}
      }
    }

Las referencias `@algo` se resuelven contra las variables de la instancia. Es
deliberadamente limitado —rutas con punto, sin expresiones ni llamadas— porque
una definición es **dato del tenant**: si admitiera expresiones arbitrarias,
publicar un proceso sería ejecutar código del cliente dentro del motor.

── Por qué el estado se guarda en cada paso ──────────────────────────────────

Porque es lo único que hace reanudable el proceso. Al terminar un paso se
escriben en la misma transacción: las variables nuevas, el historial de ese paso
y cuál es el siguiente. Si el proceso muere justo después, otro worker lee esa
fila y continúa exactamente ahí. Si muriera en mitad de un paso, el paso se
repite entero — y por eso **los pasos tienen que ser idempotentes**, lo que se
consigue pasando la clave de idempotencia de la instancia y el paso a la
operación invocada.

── Saga orquestada y compensación (CRM-00.03.02.03, .05) ─────────────────────

Cada paso puede declarar cómo se deshace. Al fallar definitivamente, el motor
recorre hacia atrás los pasos ya ejecutados y ejecuta sus compensaciones en
orden inverso. No es un rollback: es *rollback semántico*. Un pedido enviado al
ERP no «se desenvía», se anula — y esa anulación es una operación de negocio con
sus propias consecuencias, que es justo por lo que tiene que estar declarada
explícitamente y no inferirse.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger
from crmcore.obs import trazas
from sqlalchemy.orm import Session

from services.orchestrator.modelos import (
    DefinicionProceso,
    InstanciaProceso,
    PasoEjecutado,
    TareaHumana,
)

logger = get_logger(__name__)

TIPOS_PASO = frozenset(
    {
        "servicio",
        "decision",
        # `tabla` es una decisión que vive FUERA del proceso, en una tabla que
        # edita negocio (CRM-00.03.02.10). La diferencia con `decision` no es
        # técnica: una condición escrita en el proceso la cambia quien publica
        # el proceso, y la política de aprobaciones cambia cada trimestre sin
        # que el flujo cambie.
        "tabla",
        "humano",
        "espera",
        "evento",
        "subproceso",
        "paralelo",
        "fin",
    }
)

# Operadores de las condiciones. Lista cerrada por la misma razón que en ABAC:
# una definición es dato del tenant y no puede convertirse en código ejecutable.
OPERADORES: dict[str, Callable[[Any, Any], bool]] = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: _num(a) > _num(b),
    ">=": lambda a, b: _num(a) >= _num(b),
    "<": lambda a, b: _num(a) < _num(b),
    "<=": lambda a, b: _num(a) <= _num(b),
    "en": lambda a, b: a in (b or []),
    "contiene": lambda a, b: b in (a or []),
    "vacio": lambda a, _b: a in (None, "", [], {}),
    "no_vacio": lambda a, _b: a not in (None, "", [], {}),
}


def _num(valor: Any) -> float:
    """Convierte a número para comparar. Lo no convertible vale 0.

    Devolver 0 en vez de lanzar es lo correcto aquí: una comparación numérica
    contra un campo que llegó vacío debe dar falso, no detener un proceso que
    lleva tres días en marcha.
    """
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


# ── Resolución de referencias ─────────────────────────────────────────────


def resolver(valor: Any, variables: dict[str, Any]) -> Any:
    """Resuelve `@ruta.con.puntos` contra las variables. Recursivo."""
    if isinstance(valor, str) and valor.startswith("@"):
        actual: Any = variables
        for parte in valor[1:].split("."):
            if isinstance(actual, dict):
                actual = actual.get(parte)
            elif isinstance(actual, list) and parte.isdigit():
                indice = int(parte)
                actual = actual[indice] if indice < len(actual) else None
            else:
                actual = getattr(actual, parte, None)
            if actual is None:
                return None
        return actual
    if isinstance(valor, dict):
        return {k: resolver(v, variables) for k, v in valor.items()}
    if isinstance(valor, list):
        return [resolver(v, variables) for v in valor]
    return valor


def interpolar(texto: str, variables: dict[str, Any]) -> str:
    """Sustituye `@ruta` dentro de un texto. Para títulos de tarea y mensajes."""
    import re

    def _sust(m: "re.Match[str]") -> str:
        valor = resolver("@" + m.group(1), variables)
        return "" if valor is None else str(valor)

    return re.sub(r"@([a-zA-Z_][\w.]*)", _sust, texto)


# ── Validación de la definición ───────────────────────────────────────────


def validar_definicion(definicion: dict[str, Any]) -> list[str]:
    """Comprueba la definición antes de publicarla. Devuelve los problemas.

    Se valida al **publicar** y no al ejecutar. Un paso que apunta a otro
    inexistente descubierto en ejecución significa un proceso a medias en
    producción, con su compensación pendiente; descubierto al publicar, es un
    mensaje de error y nada más.
    """
    problemas: list[str] = []
    pasos = definicion.get("pasos") or {}
    inicio = definicion.get("inicio")

    if not pasos:
        return ["La definición no tiene pasos"]
    if not inicio:
        problemas.append("Falta el paso de inicio")
    elif inicio not in pasos:
        problemas.append(f"El paso de inicio «{inicio}» no existe")

    destinos_validos = set(pasos)
    for nombre, paso in pasos.items():
        tipo = paso.get("tipo")
        if tipo not in TIPOS_PASO:
            problemas.append(f"«{nombre}»: tipo desconocido «{tipo}»")
            continue

        for clave in ("siguiente", "si_no", "al_fallar"):
            destino = paso.get(clave)
            if destino and destino not in destinos_validos:
                problemas.append(f"«{nombre}».{clave} apunta a «{destino}», que no existe")

        for ruta in (paso.get("rutas") or {}).values():
            if ruta not in destinos_validos:
                problemas.append(f"«{nombre}» tiene una ruta a «{ruta}», que no existe")

        for cond in paso.get("condiciones") or []:
            destino = cond.get("entonces")
            if destino and destino not in destinos_validos:
                problemas.append(f"«{nombre}» decide ir a «{destino}», que no existe")
            si = cond.get("si") or {}
            op = si.get("op")
            if op and op not in OPERADORES:
                problemas.append(f"«{nombre}» usa el operador «{op}», que no existe")
            # Una condición sin atributo **se tomaba siempre**. Medido el
            # 26-10-2026: sin `si`, o con `si` y sin `atributo`, el motor
            # comparaba `None` con `None` y el `=` daba cierto, así que la
            # decisión se iba SIEMPRE por la primera rama — sin error, sin traza
            # y con el `si_no` que su autor escribió ahí mismo sin usarse nunca.
            #
            # Se rechaza al validar y no se adivina al ejecutar, que es la otra
            # mitad: `_cumple` devuelve falso ante una condición así, para que
            # las definiciones ya guardadas dejen de tomar la rama a ciegas.
            if not str(si.get("atributo") or "").strip():
                problemas.append(
                    f"«{nombre}» tiene una condición sin atributo: se tomaría "
                    "siempre, y el «si_no» de al lado no se usaría nunca"
                )

        if tipo == "servicio" and not paso.get("operacion"):
            problemas.append(f"«{nombre}» es de tipo servicio y no declara operación")
        if tipo == "tabla":
            if not paso.get("tabla"):
                problemas.append(f"«{nombre}» es un paso de tabla y no dice qué tabla")
            # Las rutas de un paso de tabla se eligen por el valor de una salida.
            # Sin decir cuál, el paso no sabría con qué comparar las rutas.
            if paso.get("rutas") and not paso.get("segun"):
                problemas.append(
                    f"«{nombre}» declara rutas y no dice por qué salida enrutar (`segun`)"
                )
        if tipo == "humano" and not (
            paso.get("asignada_a") or paso.get("asignada_rol") or paso.get("cola")
        ):
            # Una tarea humana sin dueño no la ve nadie: la bandeja enseña lo
            # asignado a la persona o a alguno de sus roles, así que una tarea
            # sin ninguna de las dos cosas existe en la base, detiene el
            # proceso y no aparece en ninguna pantalla. El proceso se queda
            # parado para siempre y nadie puede saber por qué.
            problemas.append(
                f"«{nombre}» es una tarea humana y no dice a quién le toca "
                "(`asignada_a`, `asignada_rol` o `cola`): nadie la vería y el "
                "proceso se quedaría parado"
            )
        if tipo == "humano" and not paso.get("rutas"):
            problemas.append(f"«{nombre}» es una tarea humana y no declara rutas de respuesta")
        if tipo == "fin" and paso.get("siguiente"):
            problemas.append(f"«{nombre}» es un paso final y aun así declara siguiente")

    # Pasos inalcanzables: no rompen nada, pero casi siempre son un error de
    # edición (un paso que se dejó de enlazar al reorganizar el flujo).
    alcanzables = _alcanzables(pasos, str(inicio))
    for huerfano in sorted(destinos_validos - alcanzables):
        problemas.append(f"«{huerfano}» no es alcanzable desde el inicio")

    # Y lo contrario, que es peor: pasos desde los que NO se puede llegar a un
    # final (CRM-00.03.05.03). Un paso inalcanzable es código muerto; uno sin
    # salida es una instancia que entra y no sale — se queda en curso para
    # siempre, consumiendo su temporizador y sin que nadie sepa por qué.
    #
    # Cubre los dos casos que se escriben solos al reorganizar un flujo: un
    # bucle que no tiene rama de salida, y una rama que se quedó sin enlazar a
    # ningún `fin`.
    sin_salida = sorted(
        nombre for nombre in alcanzables if nombre in pasos and not _llega_a_fin(pasos, nombre)
    )
    for atascado in sin_salida:
        problemas.append(f"desde «{atascado}» no se llega a ningún paso final")

    return problemas


def _llega_a_fin(pasos: dict[str, Any], desde: str) -> bool:
    """Si desde este paso se puede alcanzar algún paso de tipo `fin`.

    Se recorre hacia delante con los mismos enlaces que usa `_alcanzables`: si
    aparecieran enlaces nuevos y solo se añadieran allí, un bucle sin salida
    dejaría de detectarse justo cuando más falta hace.
    """
    for alcanzable in _alcanzables(pasos, desde):
        if (pasos.get(alcanzable) or {}).get("tipo") == "fin":
            return True
    return False


def _alcanzables(pasos: dict[str, Any], inicio: str) -> set[str]:
    vistos: set[str] = set()
    pila = [inicio]
    while pila:
        actual = pila.pop()
        if actual in vistos or actual not in pasos:
            continue
        vistos.add(actual)
        paso = pasos[actual]
        for clave in ("siguiente", "si_no", "al_fallar"):
            if paso.get(clave):
                pila.append(paso[clave])
        pila.extend((paso.get("rutas") or {}).values())
        pila.extend(c["entonces"] for c in paso.get("condiciones") or [] if c.get("entonces"))
        pila.extend(paso.get("ramas") or [])
    return vistos


# ── Ejecución ─────────────────────────────────────────────────────────────


def cumple_condicion(condicion: dict[str, Any], variables: dict[str, Any]) -> bool:
    """Si una condición de decisión se cumple. **Una sola implementación.**

    Estaba escrita dos veces —aquí y en el simulador de la API— y eso es
    exactamente lo que no puede estar duplicado: un simulador que no decide
    igual que el motor es peor que no tener simulador, porque enseña un camino
    que luego no se recorre. Al arreglar el caso de la condición sin atributo
    quedó a la vista, porque sólo se arregló una de las dos copias.
    """
    op = OPERADORES.get(str(condicion.get("op", "=")))
    if op is None:
        return False
    atributo = str(condicion.get("atributo") or "").strip()
    if not atributo:
        # Sin atributo no hay nada que comparar, y hasta el 26-10-2026 esto
        # devolvía CIERTO: `resolver("@", …)` da `None`, el valor por defecto
        # también, y `None == None` es cierto. Resultado: una decisión con la
        # condición mal escrita se iba siempre por la primera rama. Falso es lo
        # correcto porque el autor ya ha escrito a dónde ir cuando la condición
        # no se cumple — es el `si_no`.
        return False
    izquierda = resolver(f"@{atributo}", variables)
    derecha = resolver(condicion.get("valor"), variables)
    try:
        return op(izquierda, derecha)
    except TypeError:
        return False


class Motor:
    """Ejecuta instancias de proceso.

    `invocadores` es el mapa de cómo se llama a cada servicio. Se inyecta desde
    fuera para que el motor no dependa de ningún servicio concreto: en pruebas
    se pasan funciones, y en producción, clientes HTTP o publicaciones al bus.
    Esa inversión es lo que permite probar una saga completa, con su
    compensación, sin levantar nada.
    """

    def __init__(
        self,
        db: Session,
        *,
        invocadores: dict[str, Callable[..., dict[str, Any]]] | None = None,
        worker_id: str = "motor",
    ) -> None:
        self.db = db
        self.invocadores = invocadores or {}
        self.worker_id = worker_id

    # ── Arranque ─────────────────────────────────────────────────────────

    def _ejecuciones_del_periodo(self, tenant_id: UUID) -> int:
        """Procesos de primer nivel arrancados este mes por este tenant.

        Se cuentan las filas y no un contador: cada instancia ya deja la suya,
        así que la cuenta es verdad por construcción. Y sólo las de primer nivel,
        por lo mismo que sólo ésas consumen.
        """
        from crmcore.cuotas import inicio_del_periodo
        from sqlalchemy import func, select

        return int(
            self.db.execute(
                select(func.count())
                .select_from(InstanciaProceso)
                .where(
                    InstanciaProceso.tenant_id == tenant_id,
                    InstanciaProceso.padre_id.is_(None),
                    InstanciaProceso.created_at >= inicio_del_periodo(),
                )
            ).scalar_one()
        )

    def arrancar(
        self,
        *,
        tenant_id: UUID,
        clave: str,
        variables: dict[str, Any] | None = None,
        origen: tuple[str, str] | None = None,
        padre_id: UUID | None = None,
        profundidad: int = 0,
    ) -> InstanciaProceso:
        """Crea una instancia de la última versión publicada."""
        from crmcore.config import get_settings
        from sqlalchemy import select

        if profundidad > get_settings().proceso_max_profundidad:
            raise ErrorValidacion(
                "Se ha superado la profundidad máxima de subprocesos: casi "
                "siempre es un proceso que se llama a sí mismo",
                error_code="proceso.profundidad_excedida",
            )

        definicion = self.db.execute(
            select(DefinicionProceso)
            .where(
                DefinicionProceso.tenant_id == tenant_id,
                DefinicionProceso.clave == clave,
                DefinicionProceso.estado == "publicada",
            )
            .order_by(DefinicionProceso.version.desc())
            .limit(1)
        ).scalar_one_or_none()

        if definicion is None:
            from crmcore.errors import NoEncontrado

            raise NoEncontrado(
                f"No hay ninguna versión publicada del proceso «{clave}»",
                error_code="proceso.definicion_no_encontrada",
            )

        # LA CUOTA DE EJECUCIONES, aquí porque es la puerta única por la que
        # arranca un proceso: repartirla por los sitios que lo llaman garantiza
        # que al cuarto se olvide.
        #
        # **Sólo las de primer nivel.** Un subproceso es parte de la misma
        # ejecución, no otra: contarlo aparte haría que un proceso con diez
        # subprocesos gastara once, y el cliente vería agotarse su cuota al
        # triple de velocidad sin haber lanzado nada más. Y quien lo mire no
        # podría cuadrar el número con lo que ve en su pantalla.
        if profundidad == 0:
            from crmcore.cuotas import exigir

            exigir(
                self.db,
                tenant_id,
                clave="cuota_workflows_mes",
                metrica="workflows",
                contar=lambda: self._ejecuciones_del_periodo(tenant_id),
            )

        instancia = InstanciaProceso(
            tenant_id=tenant_id,
            definicion_id=definicion.id,
            clave=clave,
            version=definicion.version,
            estado="ejecutando",
            paso_actual=definicion.definicion.get("inicio"),
            variables=variables or {},
            origen_tipo=origen[0] if origen else None,
            origen_id=origen[1] if origen else None,
            padre_id=padre_id,
            profundidad=profundidad,
            # Despierta ya: el worker la recogerá en su siguiente vuelta. No se
            # ejecuta aquí mismo para que arrancar un proceso no alargue la
            # petición que lo pidió.
            despertar_at=datetime.now(timezone.utc),
        )
        self.db.add(instancia)
        self.db.flush()
        logger.info("proceso.arrancado", clave=clave, instancia=str(instancia.id))
        return instancia

    # ── Avance ───────────────────────────────────────────────────────────

    def avanzar(self, instancia: InstanciaProceso, *, max_pasos: int = 50) -> InstanciaProceso:
        """Ejecuta pasos hasta que la instancia termine, espere o agote el turno.

        `max_pasos` acota lo que hace un worker **en un turno**, no el total del
        proceso (eso lo limita `proceso_max_pasos`). Sirve para que una instancia
        con un bucle largo no monopolice al worker mientras las demás esperan.
        """
        from crmcore.config import get_settings

        s = get_settings()
        definicion = self.db.get(DefinicionProceso, instancia.definicion_id)
        if definicion is None:
            self._fallar(instancia, "La definición del proceso ha desaparecido")
            return instancia

        pasos = definicion.definicion.get("pasos") or {}
        ejecutados_en_turno = 0

        while instancia.estado == "ejecutando" and ejecutados_en_turno < max_pasos:
            if instancia.pasos_ejecutados >= s.proceso_max_pasos:
                self._fallar(
                    instancia,
                    f"Superado el máximo de {s.proceso_max_pasos} pasos: probable bucle",
                )
                break

            nombre = instancia.paso_actual
            paso = pasos.get(nombre or "")
            if paso is None:
                self._fallar(instancia, f"El paso «{nombre}» no existe en la definición")
                break

            inicio = time.perf_counter()
            try:
                # Un tramo por paso (CRM-00.06.01.03). Es lo que la traza de la
                # petición no puede dar: una orquestación que tarda dos días no
                # sucede dentro de la llamada que la arrancó, y es donde está
                # casi todo el tiempo que nadie se explica.
                with trazas.span(
                    f"proceso.{paso.get('tipo')}",
                    **{
                        "crm.proceso": definicion.clave,
                        "crm.instancia_id": str(instancia.id),
                        "crm.paso": str(nombre),
                        "crm.intento": instancia.pasos_ejecutados + 1,
                    },
                ):
                    siguiente = self._ejecutar_paso(instancia, str(nombre), paso)
            except _Espera as espera:
                # No es un error: el proceso se detiene a propósito, esperando
                # un temporizador, una persona o un evento.
                instancia.estado = espera.estado
                instancia.despertar_at = espera.despertar_at
                self._anotar(instancia, str(nombre), paso, "ok", inicio, salida=espera.datos)
                # Volcar antes de salir: la tarea humana que acaba de crearse
                # tiene que ser visible para quien consulte la bandeja, y la
                # sesión del motor no tiene autoflush.
                self.db.flush()
                break
            except Exception as exc:  # noqa: BLE001 — cualquier fallo de un paso
                self._anotar(instancia, str(nombre), paso, "fallido", inicio, error=str(exc))
                # El volcado va ANTES de decidir qué hacer con el fallo, y el
                # orden importa: `_tratar_fallo` cuenta los intentos previos con
                # una consulta, y sin volcar no vería el que se acaba de anotar.
                # Con la sesión en autoflush (el patrón habitual) esto pasaría
                # solo; aquí el autoflush está desactivado a propósito para que
                # nada llegue a la base sin que alguien lo haya decidido, así
                # que hay que ser explícito.
                self.db.flush()
                self._tratar_fallo(instancia, str(nombre), paso, pasos, exc)
                break

            self._anotar(instancia, str(nombre), paso, "ok", inicio)
            instancia.pasos_ejecutados += 1
            ejecutados_en_turno += 1
            # Se vuelca en cada paso, no al final del turno: es lo que hace
            # reanudable el proceso. Si el worker muere aquí, otro lo retoma
            # exactamente en el paso siguiente.
            self.db.flush()

            if siguiente is None:
                break
            instancia.paso_actual = siguiente

        return instancia

    def _ejecutar_paso(
        self, instancia: InstanciaProceso, nombre: str, paso: dict[str, Any]
    ) -> str | None:
        """Ejecuta un paso y devuelve el nombre del siguiente (o None si acaba)."""
        tipo = paso.get("tipo")

        if tipo == "fin":
            instancia.estado = "completada"
            instancia.finalizada_at = datetime.now(timezone.utc)
            instancia.variables = {
                **instancia.variables,
                "resultado": paso.get("resultado", "completado"),
            }
            return None

        if tipo == "servicio":
            return self._paso_servicio(instancia, nombre, paso)

        if tipo == "decision":
            for condicion in paso.get("condiciones") or []:
                if self._cumple(condicion.get("si") or {}, instancia.variables):
                    return condicion.get("entonces")
            return paso.get("si_no") or paso.get("siguiente")

        if tipo == "tabla":
            return self._paso_tabla(instancia, nombre, paso)

        if tipo == "espera":
            # Temporizadores y esperas (CRM-00.03.02.07). Mientras espera, la
            # instancia no consume nada: solo tiene una fecha de despertar que
            # el planificador consulta por índice.
            segundos = int(resolver(paso.get("segundos", 0), instancia.variables) or 0)
            hasta = resolver(paso.get("hasta"), instancia.variables)
            despertar = (
                datetime.fromisoformat(str(hasta))
                if hasta
                else datetime.now(timezone.utc) + timedelta(seconds=segundos)
            )
            raise _Espera("esperando", despertar, {"espera_hasta": despertar.isoformat()})

        if tipo == "humano":
            return self._paso_humano(instancia, nombre, paso)

        if tipo == "evento":
            # Espera a un evento externo. Sin plazo, un proceso podría quedarse
            # esperando algo que ya no va a llegar nunca, así que se exige uno.
            horas = int(paso.get("caduca_en_horas", 72))
            raise _Espera(
                "esperando",
                datetime.now(timezone.utc) + timedelta(hours=horas),
                {"esperando_evento": paso.get("evento")},
            )

        if tipo == "subproceso":
            sub = self.arrancar(
                tenant_id=instancia.tenant_id,
                clave=str(paso.get("proceso")),
                variables=resolver(paso.get("entrada") or {}, instancia.variables),
                padre_id=instancia.id,
                profundidad=instancia.profundidad + 1,
            )
            if paso.get("esperar", True):
                raise _Espera(
                    "esperando",
                    datetime.now(timezone.utc) + timedelta(minutes=1),
                    {"subproceso_id": str(sub.id)},
                )
            return paso.get("siguiente")

        raise ErrorValidacion(
            f"Tipo de paso no soportado: «{tipo}»", error_code="proceso.tipo_no_soportado"
        )

    def _paso_tabla(
        self, instancia: InstanciaProceso, nombre: str, paso: dict[str, Any]
    ) -> str | None:
        """Consulta una tabla de decisión y sigue por donde diga.

        Las salidas se vuelcan en las variables de la instancia bajo la clave
        que diga `guardar_en` (por defecto, el nombre del paso). Así el paso
        siguiente las usa como cualquier otra variable, y el historial de la
        instancia guarda **qué decidió la tabla y por qué**: sin eso, dentro de
        seis meses nadie podrá explicar por qué aquel expediente fue al director
        y no al responsable de zona, porque la tabla ya habrá cambiado.
        """
        from services.orchestrator.decision import decidir

        decision = decidir(
            self.db,
            instancia.tenant_id,
            str(paso.get("tabla")),
            instancia.variables,
        )
        destino = str(paso.get("guardar_en") or nombre)
        instancia.variables = {
            **instancia.variables,
            destino: decision.salidas,
            # La explicación va aparte y con prefijo: es para auditar, no para
            # que una condición posterior la lea por error como si fuera dato.
            f"_{destino}_explicacion": decision.a_dict(),
        }

        rutas = paso.get("rutas") or {}
        if rutas:
            segun = str(paso.get("segun"))
            valor = decision.salidas.get(segun)
            elegida = rutas.get(str(valor))
            if elegida:
                return elegida
            # Una salida sin ruta no se trata como «sigue recto»: casi siempre
            # es que alguien añadió un valor a la tabla y no la rama que le
            # corresponde, y seguir recto lo escondería.
            if paso.get("si_no"):
                return str(paso["si_no"])
            raise ErrorValidacion(
                f"«{nombre}»: la tabla decidió «{valor}» y no hay ruta para ese valor",
                error_code="proceso.tabla_sin_ruta",
                detalle={"salida": segun, "valor": valor, "rutas": sorted(rutas)},
            )
        return paso.get("siguiente")

    def _paso_servicio(
        self, instancia: InstanciaProceso, nombre: str, paso: dict[str, Any]
    ) -> str | None:
        """Invoca una operación de un servicio."""
        operacion = str(paso.get("operacion"))
        invocador = self.invocadores.get(operacion)
        if invocador is None:
            raise ErrorValidacion(
                f"No hay invocador registrado para «{operacion}»",
                error_code="proceso.operacion_desconocida",
            )

        entrada = resolver(paso.get("entrada") or {}, instancia.variables)
        # Clave de idempotencia derivada de la instancia y el paso: si el worker
        # muere después de invocar y antes de guardar, el reintento repite la
        # llamada y la operación destino la reconoce como la misma.
        salida = invocador(
            **entrada,
            _idempotencia=f"{instancia.id}:{nombre}:{instancia.pasos_ejecutados}",
            _tenant_id=instancia.tenant_id,
        )
        if paso.get("salida"):
            instancia.variables = {**instancia.variables, str(paso["salida"]): salida}
        return paso.get("siguiente")

    def _paso_humano(
        self, instancia: InstanciaProceso, nombre: str, paso: dict[str, Any]
    ) -> str | None:
        """Crea la tarea humana y detiene el proceso hasta que se responda."""
        horas = paso.get("vence_en_horas")
        vence = datetime.now(timezone.utc) + timedelta(hours=int(horas)) if horas else None
        asignada_a = resolver(paso.get("asignada_a"), instancia.variables)
        tarea = TareaHumana(
            tenant_id=instancia.tenant_id,
            instancia_id=instancia.id,
            paso=nombre,
            titulo=interpolar(str(paso.get("titulo", nombre)), instancia.variables),
            descripcion=interpolar(str(paso.get("descripcion", "")), instancia.variables),
            asignada_a=UUID(str(asignada_a)) if asignada_a else None,
            asignada_rol=paso.get("asignada_rol"),
            opciones=list((paso.get("rutas") or {}).keys()),
            vence_at=vence,
            datos=resolver(paso.get("datos") or {}, instancia.variables),
        )
        self.db.add(tarea)
        # Despierta al vencer la tarea, para poder escalarla o caducarla. Sin
        # plazo, se revisa una vez al día por si acaso.
        raise _Espera(
            "esperando_humano",
            vence or datetime.now(timezone.utc) + timedelta(days=1),
            {"tarea_pendiente": nombre},
        )

    def _cumple(self, condicion: dict[str, Any], variables: dict[str, Any]) -> bool:
        return cumple_condicion(condicion, variables)

    # ── Fallos y compensación ────────────────────────────────────────────

    def _tratar_fallo(
        self,
        instancia: InstanciaProceso,
        nombre: str,
        paso: dict[str, Any],
        pasos: dict[str, Any],
        exc: Exception,
    ) -> None:
        """Reintenta, desvía o compensa, según lo que declare el paso."""
        from sqlalchemy import func, select

        intentos_previos = (
            self.db.execute(
                select(func.count(PasoEjecutado.id)).where(
                    PasoEjecutado.instancia_id == instancia.id,
                    PasoEjecutado.paso == nombre,
                    PasoEjecutado.resultado == "fallido",
                )
            ).scalar_one()
            or 0
        )
        maximo = int(paso.get("reintentos", 0))

        # `intentos_previos` YA incluye el fallo que se acaba de anotar (se
        # volcó antes de llamar aquí), así que la comparación es estricta:
        # con `reintentos: 0` el primer fallo da 1 y no se reintenta, y con
        # `reintentos: 3` se reintenta tras el 1.º, 2.º y 3.º — cuatro intentos
        # en total, que es lo que cualquiera entiende por «tres reintentos».
        if intentos_previos < maximo + 1 and maximo > 0:
            # Backoff exponencial acotado a diez minutos: más allá, un proceso
            # de negocio esperando media hora entre reintentos es peor que uno
            # que falla y avisa.
            espera = min(2**intentos_previos * 5, 600)
            instancia.estado = "ejecutando"
            instancia.despertar_at = datetime.now(timezone.utc) + timedelta(seconds=espera)
            instancia.error = str(exc)[:1000]
            logger.warning(
                "proceso.reintento",
                instancia=str(instancia.id),
                paso=nombre,
                intento=intentos_previos + 1,
                espera_s=espera,
            )
            return

        if paso.get("al_fallar"):
            # Ruta de error declarada: el proceso la sigue sin compensar. Es
            # para los fallos que el negocio contempla («si el ERP rechaza,
            # manda a revisión manual»), que no son excepciones sino caminos.
            instancia.paso_actual = paso["al_fallar"]
            instancia.estado = "ejecutando"
            instancia.error = str(exc)[:1000]
            return

        instancia.error = str(exc)[:1000]
        self.compensar(instancia, pasos)

    def compensar(self, instancia: InstanciaProceso, pasos: dict[str, Any]) -> None:
        """Deshace en orden inverso los pasos ya ejecutados.

        No es un rollback de base de datos: es semántico. Un pedido enviado al
        ERP no se «desenvía», se anula, y esa anulación es una operación de
        negocio con sus propias consecuencias. Por eso cada compensación está
        declarada y no se infiere.
        """
        from sqlalchemy import select

        instancia.estado = "compensando"
        ejecutados = (
            self.db.execute(
                select(PasoEjecutado)
                .where(
                    PasoEjecutado.instancia_id == instancia.id,
                    PasoEjecutado.resultado == "ok",
                )
                .order_by(PasoEjecutado.created_at.desc())
            )
            .scalars()
            .all()
        )

        fallos_compensando: list[str] = []
        for ejecutado in ejecutados:
            compensacion = (pasos.get(ejecutado.paso) or {}).get("compensacion")
            if not compensacion:
                continue
            operacion = str(compensacion.get("operacion"))
            invocador = self.invocadores.get(operacion)
            if invocador is None:
                fallos_compensando.append(f"{ejecutado.paso}: sin invocador «{operacion}»")
                continue
            try:
                invocador(
                    **resolver(compensacion.get("entrada") or {}, instancia.variables),
                    _idempotencia=f"{instancia.id}:comp:{ejecutado.paso}",
                    _tenant_id=instancia.tenant_id,
                )
                ejecutado.resultado = "compensado"
            except Exception as exc:  # noqa: BLE001 — se sigue compensando el resto
                # Se anota y se continúa. Parar en la primera compensación
                # fallida dejaría los pasos anteriores sin deshacer, que es un
                # estado peor: más efectos vivos y menos rastro de cuáles.
                fallos_compensando.append(f"{ejecutado.paso}: {exc}")

        if fallos_compensando:
            instancia.estado = "fallida"
            instancia.error = (
                (instancia.error or "")
                + " | compensación incompleta: "
                + "; ".join(fallos_compensando)
            )[:2000]
            logger.error(
                "proceso.compensacion_incompleta",
                instancia=str(instancia.id),
                fallos=len(fallos_compensando),
            )
        else:
            instancia.estado = "compensada"
        instancia.finalizada_at = datetime.now(timezone.utc)

    def _fallar(self, instancia: InstanciaProceso, motivo: str) -> None:
        instancia.estado = "fallida"
        instancia.error = motivo[:1000]
        instancia.finalizada_at = datetime.now(timezone.utc)
        logger.error("proceso.fallido", instancia=str(instancia.id), motivo=motivo[:200])

    def _anotar(
        self,
        instancia: InstanciaProceso,
        nombre: str,
        paso: dict[str, Any],
        resultado: str,
        inicio: float,
        *,
        salida: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.db.add(
            PasoEjecutado(
                tenant_id=instancia.tenant_id,
                instancia_id=instancia.id,
                paso=nombre,
                tipo=str(paso.get("tipo", "")),
                resultado=resultado,
                entrada=resolver(paso.get("entrada") or {}, instancia.variables),
                salida=salida or {},
                error=error[:2000] if error else None,
                duracion_ms=int((time.perf_counter() - inicio) * 1000),
            )
        )

    # ── Respuesta a una tarea humana ─────────────────────────────────────

    def responder_tarea(
        self,
        tarea: TareaHumana,
        *,
        respuesta: str,
        usuario_id: UUID,
        comentario: str = "",
    ) -> InstanciaProceso:
        """Registra la respuesta y reanuda el proceso por la ruta que toque."""
        if tarea.estado != "pendiente":
            from crmcore.errors import Conflicto

            raise Conflicto(
                "Esa tarea ya está resuelta",
                error_code="tarea.ya_resuelta",
                detalle={"estado": tarea.estado},
            )
        if tarea.opciones and respuesta not in tarea.opciones:
            raise ErrorValidacion(
                f"Respuesta no válida. Opciones: {', '.join(tarea.opciones)}",
                error_code="tarea.respuesta_invalida",
            )

        tarea.estado = "completada"
        tarea.respuesta = respuesta
        tarea.comentario = comentario or None
        tarea.completada_at = datetime.now(timezone.utc)
        tarea.completada_por = usuario_id

        instancia = self.db.get(InstanciaProceso, tarea.instancia_id)
        if instancia is None:
            from crmcore.errors import NoEncontrado

            raise NoEncontrado(
                "La instancia del proceso no existe", error_code="proceso.no_encontrado"
            )

        definicion = self.db.get(DefinicionProceso, instancia.definicion_id)
        pasos = (definicion.definicion.get("pasos") or {}) if definicion else {}
        rutas = (pasos.get(tarea.paso) or {}).get("rutas") or {}

        instancia.variables = {
            **instancia.variables,
            f"{tarea.paso}_respuesta": respuesta,
            f"{tarea.paso}_comentario": comentario,
            f"{tarea.paso}_por": str(usuario_id),
        }
        instancia.paso_actual = rutas.get(respuesta)
        instancia.estado = "ejecutando" if instancia.paso_actual else "completada"
        instancia.despertar_at = datetime.now(timezone.utc)
        return instancia


class _Espera(Exception):
    """Señal interna: el proceso se detiene a propósito.

    Se usa una excepción y no un valor de retorno porque la espera puede surgir
    en cualquier nivel de `_ejecutar_paso` —incluida la creación de una tarea
    humana, tres llamadas dentro— y propagarla a mano por todos los retornos
    llenaría el código de comprobaciones que es fácil olvidar en una sola rama.
    """

    def __init__(self, estado: str, despertar_at: datetime, datos: dict[str, Any]) -> None:
        super().__init__(estado)
        self.estado = estado
        self.despertar_at = despertar_at
        self.datos = datos
