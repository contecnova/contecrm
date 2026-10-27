#!/usr/bin/env python3
"""Los gates locales. Este repositorio no tiene CI (CRM-07.02.01.05).

Todo lo que en otro repositorio comprobaría un servidor al abrir un pull
request, aquí lo comprueba la máquina de quien desarrolla, antes de que el
cambio salga de ella.

    python scripts/preflight.py            # tier `fast`: segundos
    python scripts/preflight.py --tests    # lo que corre el push (~37 s)
    python scripts/preflight.py --todo     # TODO, con las dos suites (~130 s)

OBLIGATORIO ANTES DEL PUSH QUE CIERRA UN BLOQUE: `--todo`, entero y en primer
plano. El push ya no corre las dos suites —eran 92 de los 129 segundos que
costaba— y eso significa que **la red que queda la pone quien empuja, no la
máquina**. Si esto se salta, se ha cambiado seguridad por tiempo y el proyecto
ha empeorado.
    python scripts/preflight.py --todo     # además, lo lento

Esa apuesta tiene una consecuencia que conviene tener presente: **los gates solo
protegen si están instalados**. En otra solución de la casa se encontró que
`.git/hooks/` solo tenía los `.sample`, o sea que ninguno había corrido nunca —y
en ese hueco entraron 218 cadenas sin traducir y un test de política de
seguridad que llevaba tiempo en rojo sin que nadie lo supiera.

Instalación, **obligatoria**:

    pre-commit install
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PY = sys.executable


@dataclass(frozen=True, slots=True)
class Gate:
    nombre: str
    comando: list[str]
    tier: str
    garantiza: str
    # Un gate opcional avisa y no bloquea cuando falta su herramienta. Es lo que
    # permite que la suite corra en una máquina sin Docker sin volverse
    # impasable —y por tanto sin que nadie acabe empujando con `--no-verify`.
    opcional: bool = False
    # Un gate EXCLUSIVO no puede correr a la vez que otro exclusivo: levanta un
    # Postgres embebido, y dos a la vez se cuelgan esperándose. Los demás sí
    # corren en paralelo entre ellos y con el exclusivo de turno.
    exclusivo: bool = False
    # Qué tiene que haber cambiado para que este gate aporte algo. Vacío = mira
    # siempre.
    #
    # **Sólo se aplica al nivel del push**, y existe porque un push que tarda
    # tres minutos deja de correrse. El 11-10-2026 costaba 2 min 47 s —la nota
    # de abajo decía 37 s— y 117 de ellos eran el recorrido de aislamiento, que
    # construye las catorce aplicaciones aunque el commit sólo toque un manual.
    #
    # Lo que NO es esto: quitar comprobaciones. El nivel completo las corre
    # todas, siempre, y es el que cierra cada bloque. Lo que cambia es que un
    # commit que no toca el front no espere a que el front compile.
    #
    # Y lo omitido SE DICE, con lo que no cambió: un gate que no corre en
    # silencio da una falsa sensación de cobertura, que es peor que no tenerlo.
    toca: tuple[str, ...] = ()
    # Si este gate está parametrizado por servicio y se le puede pasar un `-k`
    # con los que cambiaron. Ver `_acotar_a_los_servicios_que_cambiaron`: sólo
    # se acota cuando no hay NADA fuera de `services/<x>/`.
    por_servicio: bool = False


GATES: list[Gate] = [
    Gate(
        "entorno",
        [PY, "scripts/check_environment.py", "--quiet"],
        "fast",
        "el árbol instalado cumple requirements*.txt",
    ),
    Gate(
        "ruff",
        [PY, "-m", "ruff", "check", "."],
        "fast",
        "estilo y errores estáticos de Python",
    ),
    Gate(
        "formato",
        [PY, "-m", "ruff", "format", "--check", "."],
        "fast",
        "formato uniforme",
    ),
    Gate(
        "env-example",
        [PY, "scripts/gen_env_example.py", "--check"],
        "fast",
        ".env.example refleja los Settings reales",
    ),
    Gate(
        "catalogo",
        [PY, "scripts/gen_catalogo_md.py", "--check"],
        "fast",
        "la matriz de trazabilidad está regenerada desde el catálogo",
    ),
    Gate(
        "hoja-estado",
        [PY, "scripts/gen_hoja_estado.py", "--check"],
        "fast",
        "la hoja web de estado refleja el catálogo y el manual",
    ),
    Gate(
        "procesos",
        [PY, "scripts/gen_procesos.py", "--check"],
        "todo",
        "el documento de procesos dice lo que el código hace de verdad",
    ),
    # En el nivel de push —`tests`— y no en el completo, a propósito: lo que protege es
    # que no desaparezca una operación publicada, y eso hay que cazarlo en el
    # push que la borra — no en el pase completo de dentro de veinte commits,
    # cuando ya está en producción y el cliente de otro lleva días con un 404.
    #
    # Y no basta con que la prueba exista en `tests/unit`: la selección del
    # push corre las pruebas de lo que cambia, y una ruta borrada en `party` no
    # arrastra un fichero que no se llama «de party».
    Gate(
        "contrato-sellado",
        [PY, "scripts/sellar_contrato.py"],
        "tests",
        "no ha desaparecido ninguna operación publicada (compatibilidad hacia atrás)",
    ),
    Gate(
        "arquitectura",
        [PY, "-m", "pytest", "tests/unit/test_contratos_arquitectura.py", "-q", "--no-header"],
        "fast",
        "servicios desacoplados, tenant_id obligatorio, permisos declarados",
    ),
    Gate(
        "atributos",
        [PY, "scripts/comprobar_atributos.py"],
        "tests",
        "nadie lee un campo que no existe (lo que en ejecución es un 500)",
        # No aporta nada si no cambió el código: recorre el front contra los esquemas de los catorce servicios.
        toca=("services/", "packages/", "frontend/src/"),
    ),
    Gate(
        "acciones",
        [
            PY,
            "-m",
            "pytest",
            "tests/unit/test_acciones_alcanzables.py",
            "tests/unit/test_rutas_del_front.py",
            "tests/unit/test_catalogo_eventos.py",
            "-q",
            "--no-header",
        ],
        "tests",
        "lo que la API deja hacer se alcanza desde el front, y lo que emite se puede recibir",
        # No aporta nada si no cambió el código: cruza lo que la API ofrece con lo que el front alcanza.
        toca=("services/", "packages/", "frontend/src/"),
    ),
    Gate(
        "trazabilidad",
        [PY, "-m", "pytest", "tests/unit/test_catalogo_trazabilidad.py", "-q", "--no-header"],
        "fast",
        "nada se declara hecho sin cita en el código y en el manual",
    ),
    Gate(
        "manuales",
        [PY, "-m", "pytest", "tests/unit/test_manuales.py", "-q", "--no-header"],
        "fast",
        "los dos manuales cubren todo y no describen lo que ya no existe",
    ),
    Gate(
        "pantallas",
        [
            PY,
            "-m",
            "pytest",
            "tests/unit/test_cada_capacidad_tiene_pantalla.py",
            "tests/unit/test_la_pantalla_toca_lo_que_dice_que_ensena.py",
            "-q",
            "--no-header",
        ],
        "fast",
        "de cada capacidad hecha se llega a una pantalla, y el menu no miente",
    ),
    Gate(
        "contrato-headless",
        [PY, "-m", "pytest", "tests/unit/test_headless_contract.py", "-q", "--no-header"],
        "fast",
        "todo servicio publica su contrato y toda ruta está documentada",
        # No aporta nada si no cambió el código: construye los catorce contratos OpenAPI.
        toca=("services/", "packages/"),
    ),
    Gate(
        "pruebas-sin-bd",
        [PY, "-m", "pytest", "-m", "not db", "-q", "--no-header"],
        "suite",
        "todo lo que no necesita infraestructura",
    ),
    Gate(
        "aislamiento",
        [PY, "-m", "pytest", "-m", "db and despliegue", "-q", "--no-header"],
        # EN EL PUSH, y no con las demás. Lo que sale del push es lo que puede
        # esperar a la verificación del bloque; **una fuga de datos de un
        # cliente a otro no puede esperar a nada**.
        #
        # Se eligen POR MARCA y no por una lista de ficheros. Esto era un
        # `--ignore` con siete rutas, y tenía dos defectos: se queda atrás en
        # cuanto alguien añade una prueba de aislamiento nueva —que entraría en
        # el saco lento sin que nadie lo note— y obliga a contar las pruebas de
        # los dos lados para saber que no se ha perdido ninguna. La marca viaja
        # con la prueba y la pone quien la escribe, que es quien sabe si lo que
        # comprueba puede esperar al lunes.
        #
        # El criterio para sacar algo del push NO es cuánto tarda: es qué caza.
        #
        # Y NO SE PARTE EN VARIOS GATES. Se propuso dos veces —recorre los trece
        # servicios en serie— y las dos se descartó, la segunda con el motivo que
        # no caduca: los gates que tocan base son `exclusivo` porque cada uno
        # levanta su propio Postgres embebido, y ya hay un cerrojo que los turna.
        # Partir éste en cuatro daría cuatro gates haciendo la misma cola **más
        # cuatro arranques de Postgres en vez de uno**: perdería.
        #
        # Lo que habría que reabrir el día que apriete **no es «repartir gates»**:
        # es **«xdist con esquema por trabajador»**, que paraleliza DENTRO del
        # gate. Hoy ni `pytest-xdist` está instalado ni el `conftest` contempla
        # trabajadores, así que es trabajo de verdad y su beneficio está sin
        # medir. Queda escrito aquí para que nadie repita la hora que costó
        # averiguarlo.
        "tests",
        "ninguna ruta deja ver lo de otro tenant, y ninguna deja de responder",
        exclusivo=True,
        # No aporta nada si no cambió el código: construye las catorce
        # aplicaciones y recorre sus rutas; 117 s de los 167 que costaba el push.
        toca=("services/", "packages/"),
        # Y se puede acotar a los servicios que cambiaron, porque está
        # parametrizado por servicio. Sólo cuando TODO lo que cambió vive dentro
        # de `services/<x>/`: un cambio en `packages/` toca a los catorce y
        # acotarlo sería dejar trece sin mirar.
        por_servicio=True,
    ),
    Gate(
        "pruebas-con-bd",
        [PY, "-m", "pytest", "-m", "db and not despliegue", "-q", "--no-header"],
        "suite",
        "motor de procesos, persistencia y todo lo demás que necesita base",
        exclusivo=True,
    ),
    Gate(
        "migraciones",
        [PY, "scripts/migraciones_locales.py", "comprobar"],
        "tests",
        "ningún modelo cambiado se ha quedado sin su migración",
        exclusivo=True,
        # No aporta nada si no cambió el código: levanta un Postgres y aplica todas las migraciones desde cero.
        toca=("services/", "packages/", "alembic/"),
    ),
    Gate(
        "front",
        ["npm", "--prefix", "frontend", "run", "verificar"],
        "tests",
        "el front oficial tipa, cumple sus reglas, pasa sus pruebas y construye",
        # Opcional porque no toda máquina que toca el backend tiene Node
        # instalado, y negarse a correr el preflight por eso convertiría el
        # ciclo rápido en una instalación obligatoria. Si Node está, el gate
        # corre y falla como cualquier otro.
        opcional=True,
        # No aporta nada si no cambió el código: compila el front entero.
        toca=("frontend/",),
    ),
    Gate(
        "pantallas",
        ["npm", "--prefix", "frontend", "run", "pantallas"],
        "suite",
        "las pantallas del front montan, no dejan la aplicación en blanco y caben",
        # En el nivel `suite` —el de `--todo`— y no en el del push: arranca un
        # navegador y
        # construye la aplicación, así que son ~25 s. En el ciclo rápido sería
        # el coste, y el coste nunca pueden ser los guardianes.
        #
        # Opcional por lo mismo que el gate del front: una máquina sin Node no
        # puede correrlo, y negarse por eso convertiría el preflight en una
        # instalación obligatoria.
        opcional=True,
        # EXCLUSIVO, y no por el Postgres: abre navegadores de verdad y los
        # cronometra. Compitiendo con los otros cinco gates, una pantalla tarda
        # en montar más de lo que se le espera y sale como rota. Medido:
        # «Marketing» pasó 3 de 3 corriendo sola y falló dentro del preflight.
        #
        # Un gate que falla según lo ocupada que esté la máquina es peor que no
        # tenerlo: enseña a desconfiar del rojo, y entonces el rojo de verdad
        # tampoco se mira.
        exclusivo=True,
    ),
    Gate(
        "docs",
        [PY, "-m", "mkdocs", "build", "--strict", "--quiet"],
        "todo",
        "el manual construye y sus enlaces resuelven",
        opcional=True,
    ),
]


# Lo que puede tardar el preflight ENTERO, en segundos.
#
# No es una preferencia: es la condición para que exista. Un preflight que pasa
# de tres minutos deja de correrse —se pospone «para luego», y luego se empuja
# sin él— y un gate que no se corre no garantiza nada, con lo que el coste se
# paga entero y el beneficio no llega.
#
# Cuando esto falla, lo que se arregla es el gate lento, no la comprobación. La
# primera vez que se midió, 195 de los 200 segundos de las pruebas con base de
# datos se iban en crear y tirar un esquema de 98 tablas **por prueba**; pasar a
# aislar por transacción lo dejó en 11 segundos sin quitar ni una prueba.
#
# Se mide el RELOJ DE PARED, no la suma de los gates. Antes se sumaba, y eso
# medía trabajo hecho en vez de tiempo esperado: con los gates corriendo en
# paralelo, sumar decía tres minutos y medio donde quien lo lanzaba esperaba
# minuto y medio. Lo que hace que un preflight deje de correrse es lo que se
# tarda en volver al teclado.
#
# Y el presupuesto de CPU, que es lo que MEJOR dice si el preflight ha engordado.
# El reloj de pared mide lo que espera quien lo lanza —y por eso se sigue
# enseñando—, pero **no distingue un gate que ha engordado de una máquina
# ocupada**: medido el 05-10-2026, el mismo gate de aislamiento tardó 59 s y
# 382 s en la misma hora, con el mismo trabajo de CPU, porque en esta máquina
# estaban corriendo a la vez el `tsc` de contecmind, dos `vitest` de contecpos y
# el indexador de Spotlight. Fallar ahí es fallar por el vecino, y eso enseña a
# ignorar el rojo — que es la forma de perder el guardián entero.
#
# **El CPU aguanta mucho mejor, pero no es inmune, y aquí ponía que sí.** Hasta
# el 07-10-2026 esta nota decía «si la máquina está cargada, no sube», y eso era
# lo que justificaba fallar por CPU. Medido ese día, el mismo commit y el mismo
# nivel «push»:
#
#     carga  7  →  146 s de CPU   (78 s de reloj)
#     carga 61  →  252 s de CPU  (243 s de reloj)
#
# Un 1,7× sin haber añadido una línea. Con contención suben los cambios de
# contexto y se pierde la caché, y ese trabajo también se contabiliza. Así que
# el rojo sigue yendo por CPU —es la mejor señal que hay— pero **no se falla
# cuando la máquina está por encima de sus núcleos**: se dice el número, se dice
# la carga y se pide repetirlo con la máquina libre. Fallar ahí seguiría siendo
# fallar por el vecino, sólo que con otra unidad.
#
# Y UNO POR NIVEL, porque son tres cosas distintas y un solo número las trata
# igual. Con el número único en 300 s pasaban las dos cosas malas a la vez:
#
#   · el nivel rápido gasta 22 s y tenía 300 de margen, o sea el guardián del
#     crecimiento dormido justo en el nivel que más se corre;
#   · el nivel completo gasta 354 s y por tanto **no podía salir en verde
#     nunca**, con lo que `_apuntar_pase_completo` era inalcanzable: el apunte
#     de «aquí pasó la batería entera» no se escribía ni pasando los 20 gates.
#     El aviso de «van N commits sin un pase completo» no bajaba de N, y eso
#     enseña a ignorarlo, que es como se pierde el apunte entero.
#
# Medido el 06-10-2026 en esta máquina y con la máquina libre, CPU / reloj:
#     rápido   22 s / 14 s   (tres pases, idénticos)
#     push    139 s / 72 s
#     completo 354 s / 216 s
#
# El margen es de ~1,4×: lo justo para que no salte por el ruido de una
# ejecución y lo bastante apretado para que saltar signifique que alguien ha
# añadido trabajo. Si salta, se arregla el gate lento; no se sube el número.
PRESUPUESTOS: dict[str, tuple[float, float]] = {
    # nivel: (reloj de referencia, tope de CPU)
    "rapido": (35.0, 40.0),
    "push": (120.0, 200.0),
    "completo": (330.0, 500.0),
}


def _presupuesto(tiers: set[str]) -> tuple[str, float, float]:
    """Qué nivel es éste y qué se le permite."""
    if "suite" in tiers:
        return "completo", *PRESUPUESTOS["completo"]
    if "tests" in tiers:
        return "push", *PRESUPUESTOS["push"]
    return "rapido", *PRESUPUESTOS["rapido"]


# Lo que cuesta de memoria el gate más gordo, medido: los que recorren los trece
# servicios construyen las trece aplicaciones FastAPI y se quedan en medio giga.
COSTE_POR_GATE_MB = 500


def _memoria_disponible_mb() -> int | None:
    """Memoria que se puede usar sin empezar a paginar, o `None` si no se sabe."""
    try:
        if sys.platform == "linux":
            for linea in Path("/proc/meminfo").read_text().splitlines():
                if linea.startswith("MemAvailable:"):
                    return int(linea.split()[1]) // 1024
            return None
        if sys.platform == "darwin":
            salida = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10).stdout
            pagina = 4096
            paginas: dict[str, int] = {}
            for linea in salida.splitlines():
                if "page size of" in linea:
                    pagina = int(linea.split("page size of")[1].split()[0])
                elif ":" in linea:
                    clave, _, valor = linea.partition(":")
                    paginas[clave.strip()] = int(valor.strip().rstrip("."))
            # Libre más inactiva: la inactiva se puede reclamar sin paginar.
            libres = paginas.get("Pages free", 0) + paginas.get("Pages inactive", 0)
            return libres * pagina // (1024 * 1024)
    except Exception:  # noqa: BLE001 — no saberlo no puede impedir el preflight
        return None
    return None


def _paralelos() -> int:
    """Cuántos gates a la vez, limitado por lo que de verdad escasea.

    **La memoria, no los núcleos.** Con seis a la vez cada gate pasó de 14 s a
    112 s: no era la CPU —diez núcleos y el trabajo es de uno cada uno— era que
    Docker se lleva la mitad de la RAM de esta máquina y seis procesos de medio
    giga la metían a paginar. Un preflight que pagina tarda más en paralelo que
    en serie, que es lo contrario de lo que se buscaba.

    Se mide en vez de fijarse: la misma cifra no vale para una máquina con la
    pila levantada y otra sin ella, y un número escrito aquí sería el de la
    máquina de quien lo escribió.
    """
    por_cpu = max(2, min(6, (os.cpu_count() or 4) - 1))
    disponible = _memoria_disponible_mb()
    if disponible is None:
        return por_cpu
    # Se deja un gate de margen para el resto del sistema.
    por_memoria = max(1, disponible // COSTE_POR_GATE_MB - 1)
    return max(1, min(por_cpu, por_memoria))


PARALELOS = _paralelos()


def _carga() -> float:
    """Cuánta cola ha tenido esta máquina, mirando las TRES medias.

    Se enseña cuando el reloj se dispara y el CPU no: sin ella, «ha tardado el
    doble» no dice si el problema es el preflight o la máquina, y esa es
    justamente la diferencia que hay que poder ver de un vistazo.

    **La del minuto no vale sola, y aquí era la única que se miraba.** Se
    consulta al TERMINAR, y un nivel completo dura diez minutos: la del minuto
    describe el último tramo, no el pase. Medido el 07-10-2026 a las 03:06, un
    `--todo` con los veinte gates en verde y todos sus tiempos inflados 3× —
    señal de contención— salió marcado como rojo de presupuesto porque al acabar
    la del minuto había bajado de 10, mientras la de quince seguía en 19.
    Se toma la mayor de las tres, que es la que cubre el pase entero.
    """
    try:
        return max(os.getloadavg())
    except (OSError, AttributeError):  # pragma: no cover — sistemas sin carga
        return 0.0


def _cambios_del_push() -> list[str] | None:
    """Qué ficheros lleva este push respecto de lo ya publicado.

    `None` significa **no se sabe**, y entonces no se omite nada: sin rama
    remota, en un repositorio recién clonado o si `git` falla, el comportamiento
    seguro es correrlo todo. Una optimización que se equivoca callando es peor
    que no tenerla.
    """
    for referencia in ("@{upstream}", "origin/main"):
        try:
            r = subprocess.run(
                ["git", "diff", "--name-only", f"{referencia}...HEAD"],
                cwd=RAIZ,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:  # noqa: BLE001 — sin git se corre todo
            return None
        if r.returncode == 0:
            # Y lo que está sin confirmar: alguien puede estar corriendo el
            # preflight antes de commitear, y lo que tiene delante cuenta.
            sucio = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=RAIZ,
                capture_output=True,
                text=True,
                timeout=15,
            )
            ficheros = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
            ficheros += [ln[3:].strip() for ln in sucio.stdout.splitlines() if len(ln) > 3]
            return ficheros
    return None


def _aporta_algo(gate: Gate, cambios: list[str] | None) -> bool:
    """Si este gate puede decir algo distinto con lo que ha cambiado.

    Sin `toca` declarado, siempre. Sin saber qué cambió, también: ver arriba.
    """
    if not gate.toca or cambios is None:
        return True
    return any(f.startswith(prefijo) for f in cambios for prefijo in gate.toca)


def _acotar_a_los_servicios_que_cambiaron(gate: Gate, cambios: list[str] | None) -> Gate:
    """Añade un `-k` con los servicios tocados, si se puede acotar sin riesgo.

    **Sólo cuando TODO lo que cambió vive dentro de `services/<x>/`.** Un cambio
    en `packages/` es del núcleo y lo heredan los catorce: acotarlo dejaría trece
    sin mirar, y esto comprueba que ninguna ruta deja ver lo de otro cliente —
    de lo que no se puede dejar trece sin mirar.

    Ante cualquier duda se devuelve el gate tal cual. Una optimización que se
    equivoca callando es peor que no tenerla.
    """
    if not gate.por_servicio or not cambios:
        return gate

    # Lo que no es código no cuenta para decidir: un manual o una prueba no
    # cambian qué servicios hay que recorrer.
    codigo = [f for f in cambios if f.startswith(("services/", "packages/"))]
    if not codigo or any(f.startswith("packages/") for f in codigo):
        return gate

    servicios = {f.split("/")[1] for f in codigo if len(f.split("/")) > 2}
    # Sin servicios identificables —un fichero suelto en `services/`— no se
    # acota: no se sabe de quién es.
    if not servicios or len(servicios) > 6:
        return gate

    expresion = " or ".join(sorted(servicios))
    return replace(gate, comando=[*gate.comando, "-k", expresion])


def _correr(gate: Gate) -> tuple[bool, float, str]:
    inicio = time.perf_counter()
    try:
        proceso = subprocess.run(
            gate.comando, cwd=RAIZ, capture_output=True, text=True, timeout=1800
        )
    except FileNotFoundError:
        return (gate.opcional, time.perf_counter() - inicio, "herramienta no instalada")
    except subprocess.TimeoutExpired:
        return (False, time.perf_counter() - inicio, "tiempo agotado (30 min)")
    salida = (proceso.stdout + proceso.stderr).strip()
    return (proceso.returncode == 0, time.perf_counter() - inicio, salida)


# ── Constancia de qué nivel corrió (y de lo que no corrió) ────────────────
#
# El tercer nivel —la suite entera antes del push que cierra un bloque— se
# apoya en que alguien se acuerde. Eso no es una garantía: es exactamente el
# `make` voluntario que en otro repositorio de la casa dejó seis pruebas en
# rojo durante semanas sin que nadie se enterara. Un gancho o corre en cada
# push —y entonces no puede llevar las suites— o depende de la memoria de
# quien empuja.
#
# No se puede obligar hacia atrás. Lo que sí se puede es **impedir que se
# mienta**: aquí queda apuntado cuándo pasó el nivel completo por última vez, y
# el nivel del push dice cuántos commits llevas sin él. Quita la coartada.
#
# El apunte NO se versiona, a propósito: es constancia de lo que corrió EN ESTA
# MÁQUINA. Un clon recién hecho dice «nunca», que es la verdad.
APUNTE = RAIZ / ".verificacion-bloque"

# A partir de aquí se dice en rojo. Diez commits es más de un día de trabajo:
# suficiente para que la suite lleve sin correr lo bastante como para que algo
# se haya roto sin que nadie lo sepa.
COMMITS_PARA_GRITAR = 10


def _commit_actual() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=RAIZ, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _apuntar_pase_completo() -> None:
    try:
        APUNTE.write_text(
            json.dumps(
                {"commit": _commit_actual(), "cuando": datetime.now(timezone.utc).isoformat()},
                indent=2,
            )
            + "\n"
        )
    except Exception:  # noqa: BLE001 — no poder apuntarlo no puede tumbar el preflight
        return


def _commits_desde_el_ultimo_pase() -> tuple[int, str] | None:
    """Cuántos commits van sin un pase completo, y cuándo fue. `None` = nunca."""
    try:
        apunte = json.loads(APUNTE.read_text())
        r = subprocess.run(
            ["git", "rev-list", "--count", f"{apunte['commit']}..HEAD"],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            return None  # el commit apuntado ya no existe: rebase, o rama nueva
        return int(r.stdout.strip() or 0), str(apunte.get("cuando", ""))[:16].replace("T", " ")
    except Exception:  # noqa: BLE001
        return None


def _decir_que_falta_por_correr(completo: bool) -> None:
    if completo:
        _apuntar_pase_completo()
        print("Apuntado: el nivel completo ha pasado aquí.")
        return

    desde = _commits_desde_el_ultimo_pase()
    if desde is None:
        print(
            "\nAQUÍ NO CONSTA NINGÚN PASE DEL NIVEL COMPLETO.\n"
            "Las dos suites no las ha corrido nadie en esta máquina."
        )
    elif desde[0] == 0:
        print("\nEl nivel completo pasó en este mismo commit.")
    else:
        aviso = "AVISO: " if desde[0] >= COMMITS_PARA_GRITAR else ""
        print(f"\n{aviso}Van {desde[0]} commit(s) sin un pase del nivel completo")
        print(f"(el último, {desde[1]}).")
    print(
        "Antes del push que cierra el bloque: «python scripts/preflight.py --todo», "
        "entero y en primer plano."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tests", action="store_true", help="incluye la suite")
    parser.add_argument("--todo", action="store_true", help="incluye lo lento")
    parser.add_argument("--solo", default="", help="un gate por su nombre")
    args = parser.parse_args()

    tiers = {"fast"}
    if args.tests or args.todo:
        tiers.add("tests")
    if args.todo:
        tiers.add("todo")
        # LAS DOS SUITES SOLO AQUÍ. Son 92 s de los 129 que costaba el push
        # —27 s sin base de datos y 65 s con ella, medidos— y sacarlas lo deja
        # en unos 37. No se han tocado por dentro ni se ha quitado una sola
        # comprobación: han cambiado de momento.
        #
        # LO QUE ESTO EXIGE A CAMBIO, y no es opcional: **antes del push que
        # cierra un bloque hay que correr `--todo`, entero y en primer plano**.
        # Si eso no se hace, se ha cambiado seguridad por tiempo y el proyecto
        # ha empeorado. No hay aquí nada que lo obligue: lo obliga quien empuja.
        tiers.add("suite")

    seleccionados = [
        g for g in GATES if (g.nombre == args.solo) or (not args.solo and g.tier in tiers)
    ]

    # ── Lo que toca lo que ha cambiado, y SÓLO en el nivel del push ──────
    #
    # El nivel completo los corre todos siempre: es el que cierra cada bloque y
    # el que tiene que poder decir «pasó entero». El rápido no tiene gates caros
    # que recortar. El del push sí, y es el que se corre veinte veces al día:
    # el 11-10-2026 costaba 2 min 47 s con la máquina a media carga, de los que
    # 117 s eran el recorrido de aislamiento — que construye las catorce
    # aplicaciones aunque el commit sólo toque un manual.
    #
    # Un push de tres minutos deja de correrse, y entonces se empuja con
    # `--no-verify`, que es como se pierde la red entera. Esto no quita ninguna
    # comprobación: cambia cuándo.
    fuera_de_alcance: list[Gate] = []
    if "tests" in tiers and "suite" not in tiers and not args.solo:
        cambios = _cambios_del_push()
        if cambios is not None:
            dentro = [g for g in seleccionados if _aporta_algo(g, cambios)]
            fuera_de_alcance = [g for g in seleccionados if g not in dentro]
            seleccionados = [_acotar_a_los_servicios_que_cambiaron(g, cambios) for g in dentro]
    if not seleccionados:
        print(f"No hay ningún gate llamado «{args.solo}»", file=sys.stderr)
        return 2

    fallos: list[tuple[Gate, str]] = []
    omitidos: list[str] = []
    print(f"preflight — {len(seleccionados)} gates\n")

    # Los exclusivos se turnan entre ellos; el resto va en paralelo. El cerrojo
    # es lo único que los separa: sin él, dos Postgres embebidos a la vez se
    # quedan esperándose y el preflight no termina nunca.
    turno = threading.Lock()

    def _ejecutar(gate: Gate) -> tuple[bool, float, str]:
        if not gate.exclusivo:
            return _correr(gate)
        with turno:
            return _correr(gate)

    import resource

    reloj = time.perf_counter()
    antes = resource.getrusage(resource.RUSAGE_CHILDREN)
    with ThreadPoolExecutor(max_workers=PARALELOS) as pool:
        resultados = list(pool.map(_ejecutar, seleccionados))
    total = time.perf_counter() - reloj
    despues = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (despues.ru_utime - antes.ru_utime) + (despues.ru_stime - antes.ru_stime)

    # Se imprime en el orden en que están declarados, no en el que terminaron:
    # el informe tiene que ser el mismo dos veces seguidas para poder compararlo.
    for gate, (ok, duracion, salida) in zip(seleccionados, resultados, strict=True):
        if ok and "no instalada" in salida:
            omitidos.append(gate.nombre)
            print(f"  ~ {gate.nombre:22} omitido ({salida})")
            continue
        marca = "✓" if ok else "✗"
        print(f"  {marca} {gate.nombre:22} {duracion:5.1f}s  {gate.garantiza}")
        if not ok:
            fallos.append((gate, salida))

    if fuera_de_alcance:
        # Se dice cuáles y POR QUÉ. Un gate que no corre en silencio da una
        # falsa sensación de cobertura, que es peor que no tener el gate — y el
        # nivel completo los corre todos, así que esto es «ahora no», no «nunca».
        nombres = ", ".join(g.nombre for g in fuera_de_alcance)
        print(f"\nFuera de alcance de este push ({nombres}): no cambió lo que miran.")
        print("El nivel completo los corre igual: «python scripts/preflight.py --todo».")

    if omitidos:
        # Se dice qué NO se ha comprobado. Un gate omitido en silencio da una
        # falsa sensación de cobertura, que es peor que no tener el gate.
        print(f"\nNo comprobado: {', '.join(omitidos)}")

    if fallos:
        print(f"\n{len(fallos)} gate(s) en rojo:\n")
        for gate, salida in fallos:
            print(f"── {gate.nombre} " + "─" * (60 - len(gate.nombre)))
            print(salida[-3000:] or "(sin salida)")
            print()
        return 1

    carga = _carga()
    nivel, presupuesto_reloj, presupuesto_cpu = _presupuesto(tiers)
    # Por encima de sus núcleos la máquina está peleándose consigo misma, y el
    # CPU medido deja de ser el trabajo del preflight: ver la nota de los
    # presupuestos, con los pases que lo miden. `_carga()` mira las tres medias
    # —no sólo la del minuto— porque un nivel completo dura diez.
    apretada = carga > (os.cpu_count() or 4)
    if cpu > presupuesto_cpu and apretada:
        print(
            f"\nTodo en verde. {cpu:.0f}s de CPU, más de los "
            f"{presupuesto_cpu:.0f}s del nivel «{nivel}», pero la máquina está a "
            f"una carga de {carga:.0f} con {os.cpu_count()} núcleos.\n"
            "Con contención el CPU medido sube sin que nadie haya añadido "
            "trabajo —1,7× medido el 07-10-2026—, así que esto NO cuenta como "
            "pase ni como rojo.\nRepítelo con la máquina libre antes de "
            "creértelo en cualquiera de los dos sentidos."
        )
        return 0
    if cpu > presupuesto_cpu:
        print(
            f"\nTodo en verde, PERO el nivel «{nivel}» gasta {cpu:.0f}s de CPU "
            f"y su presupuesto son {presupuesto_cpu:.0f}s "
            f"(reloj: {total:.0f}s).\n\n"
            "Un preflight que pasa de tres minutos deja de correrse, y un gate "
            "que no se corre no garantiza nada — con lo que el coste se paga\n"
            "entero y el beneficio no llega. Los tiempos de arriba dicen dónde "
            "se va: se arregla el gate lento, no se quita la comprobación."
        )
        return 1

    if total > presupuesto_reloj:
        # Lento de reloj pero no de trabajo: la máquina está ocupada. Se dice y
        # NO se falla. Fallar aquí es fallar por lo que esté compilando otra
        # ventana, y un rojo que no depende de lo que uno ha hecho se ignora a
        # la segunda vez.
        print(
            f"\nTodo en verde. {total:.0f}s de reloj —más de los {presupuesto_reloj:.0f}s "
            f"de referencia— pero solo {cpu:.0f}s de CPU"
            + (f", con la máquina a una carga de {carga:.0f}" if carga else "")
            + ".\nNo ha engordado el preflight: está compartiendo máquina. El "
            "presupuesto que decide es el de CPU."
        )
        return 0

    print(
        f"\nTodo en verde. {total:.0f}s de reloj y {cpu:.0f}s de CPU de los "
        f"{presupuesto_cpu:.0f}s del nivel «{nivel}», con hasta {PARALELOS} gates a la vez."
    )
    # Y QUÉ NIVEL FUE ÉSTE. Un push con el subconjunto no puede constar como
    # batería completa: si no se dice, «todo en verde» se lee igual en los dos
    # casos y ahí es donde se afloja la red sin que nadie lo decida.
    _decir_que_falta_por_correr(completo="suite" in tiers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
