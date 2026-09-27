#!/usr/bin/env python3
"""Levanta los servicios de la casa de los que contecrm depende, y los enlaza.

contecrm no es autosuficiente por diseño: la explotación del dato la resuelve
**contecintelligence** (RT-4) y el corpus documental **contecmind** (RT-5). Las
dos son dependencias de despliegue, no extras, así que arrancar contecrm sin
ellas deja media aplicación con pantallas que no pueden funcionar.

    python scripts/vecinos.py levantar     # los arranca y los enlaza
    python scripts/vecinos.py estado       # dice si están y si se ven
    python scripts/vecinos.py parar

**Se usa el compose de cada vecino, no una copia suya aquí.** contecrm tenía en
su `docker-compose.yml` un contenedor `contecmind` de un solo servicio contra su
propio Postgres, y eso no ha funcionado nunca: contecmind necesita además Qdrant,
Redis y MinIO. Una descripción de la topología ajena escrita aquí se queda vieja
el día que el vecino añada una pieza, y nadie se entera hasta que arranca y falla
a medias.

**El enlace de red se rehace en cada arranque.** contecrm los llama por su nombre
(`CI_BASE_URL`, `DMS_BASE_URL`), así que sus contenedores tienen que estar en la
red de contecrm con ese alias. contecintelligence lo declara en su propio compose
—que es lo mejor—; contecmind no, así que se engancha desde aquí. Hacerlo a mano
una vez no vale: se pierde al recrear el contenedor y el enlace se cae con «Name
or service not known» sin que nadie haya tocado nada. Pasó.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"


def ok(msg: str) -> None:
    print(f"  {VERDE}✓{FIN} {msg}")


def malo(msg: str) -> None:
    print(f"  {ROJO}✗{FIN} {msg}")


def aviso(msg: str) -> None:
    print(f"  {AMARILLO}!{FIN} {msg}")


def info(msg: str) -> None:
    print(f"  {GRIS}·{FIN} {msg}")


@dataclass(frozen=True)
class Vecino:
    """Un servicio de la casa del que contecrm depende."""

    nombre: str
    # Dónde está su repositorio. Se puede apuntar a otro sitio sin tocar esto:
    # lo normal en una instalación es tenerlo en otra máquina o en otra ruta.
    variable_repo: str
    repo_por_defecto: str
    compose: str
    # El contenedor que sirve la API y el nombre con el que contecrm lo llama.
    contenedor: str
    alias: str
    puerto_interno: int
    # Una ruta suya que conteste 200 sin autenticarse, para saber que está vivo.
    sonda: str
    # El ajuste del `.env` de contecrm que tiene que apuntar aquí.
    ajuste_url: str
    ajuste_activo: str
    # Una ruta suya a la que el NAVEGADOR llama directamente desde una pantalla
    # del CRM, si la hay. Vacío = el CRM solo habla con él desde el servidor.
    sonda_navegador: str = ""
    # Su ruta de token de aplicación, si la tiene. Es lo que permite comprobar
    # que la CREDENCIAL sigue valiendo, no solo que el servicio conteste.
    ruta_token: str = ""
    # Los ajustes del `.env` con esa credencial.
    ajuste_cliente: str = ""
    ajuste_secreto: str = ""
    # El ajuste del `.env` con los alcances que le pedimos. Se comprueban contra
    # los que CONCEDE, que no son los mismos: el alta de la aplicación allí
    # decide cuáles tiene, y pedir uno que no tiene no falla al canjear —falla
    # al usarlo, con un 403 en la pantalla y días después.
    ajuste_alcances: str = ""
    perfiles: tuple[str, ...] = ()
    entorno: dict[str, str] = field(default_factory=dict)
    # Su fichero de entorno, relativo al repositorio, cuando NO está junto al
    # compose. Compose busca el `.env` en el directorio del compose, así que un
    # vecino que lo guarde en su raíz y tenga el compose en `deploy/compose/` se
    # levanta con los valores por defecto sin avisar — y los valores por defecto
    # son justo los que chocan con otro producto de la casa.
    env_file: str = ""
    # El nombre del proyecto de compose. Se DECLARA porque compose lo deduce del
    # directorio del compose, y un vecino con el suyo en `deploy/compose/` se
    # llamaría «compose»: `ps` no vería sus contenedores y un `up` crearía un
    # SEGUNDO juego al lado del que ya corre, con los mismos puertos. Vacío =
    # el nombre del vecino, que es lo que usa la casa.
    proyecto: str = ""
    # Lo que hay que hacer DESPUÉS de levantarlo, como `(servicio, orden)`. No
    # todo vecino arranca dejando su casa en orden, y eso no lo arregla contecrm
    # editando el compose ajeno: se hace aquí y se dice por qué.
    despues: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # Servicios que hay que reiniciar después, porque cachean algo del que se
    # acaba de recrear.
    reiniciar: tuple[str, ...] = ()

    def nombre_proyecto(self) -> str:
        return self.proyecto or self.nombre

    def ruta(self) -> Path:
        return Path(os.environ.get(self.variable_repo) or (RAIZ.parent / self.repo_por_defecto))

    def fichero_compose(self) -> Path:
        return self.ruta() / self.compose

    def url_interna(self) -> str:
        return f"http://{self.alias}:{self.puerto_interno}"


VECINOS: tuple[Vecino, ...] = (
    Vecino(
        nombre="contecintelligence",
        variable_repo="CONTECINTELLIGENCE_REPO",
        repo_por_defecto="contecintelligence",
        compose="deploy/compose/docker-compose.yml",
        env_file=".env",
        contenedor="contecintelligence-backend-1",
        alias="contecintelligence",
        puerto_interno=8000,
        sonda="/livez",
        ajuste_url="CI_BASE_URL",
        ajuste_activo="CI_ENABLED",
        # La pantalla de explotación del CRM llama a `/api/ask` desde el
        # navegador, con un token corto por usuario. O sea que el origen del
        # front tiene que estar permitido ALLÍ, y eso no se ve desde el servidor.
        sonda_navegador="/api/ask",
        ruta_token="/api/oauth/token",
        ajuste_cliente="CI_CLIENT_ID",
        ajuste_secreto="CI_CLIENT_SECRET",
        ajuste_alcances="CI_SCOPES",
        # Su compose se engancha a la red de contecrm y necesita saber cuál es.
        entorno={"CONTECRM_NETWORK": ""},
    ),
    Vecino(
        nombre="contecmind",
        variable_repo="CONTECMIND_REPO",
        repo_por_defecto="contecmind",
        compose="docker-compose.yml",
        contenedor="contecmind-api",
        alias="contecmind",
        puerto_interno=4000,
        sonda="/api/v1/openapi.json",
        ajuste_url="DMS_BASE_URL",
        ajuste_activo="DMS_ENABLED",
        ruta_token="/api/v1/oauth/token",
        ajuste_cliente="DMS_CLIENT_ID",
        ajuste_secreto="DMS_CLIENT_SECRET",
        ajuste_alcances="DMS_SCOPES",
        perfiles=("app",),
        # Su arranque NO aplica migraciones. Sin esto, la base se queda atrás y
        # las rutas nuevas dan 500 por tablas que no existen — que es un fallo
        # que parece del código y es del despliegue.
        despues=(("api", ("alembic", "upgrade", "head")),),
        # Su nginx resuelve la IP de la API al arrancar y la cachea: recrear la
        # API sin reiniciarlo da 502 con los dos contenedores «healthy», que es
        # de los diagnósticos que más tiempo comen.
        reiniciar=("web",),
    ),
)


def _compose(vecino: Vecino, *args: str) -> list[str]:
    """La orden base de compose para ese vecino, con su entorno y sus perfiles."""
    orden = [
        "docker",
        "compose",
        "-p",
        vecino.nombre_proyecto(),
        "-f",
        str(vecino.fichero_compose()),
    ]
    if vecino.env_file:
        orden += ["--env-file", str(vecino.ruta() / vecino.env_file)]
    for perfil in vecino.perfiles:
        orden += ["--profile", perfil]
    return orden + list(args)


def _correr(orden: list[str], *, cwd: Path | None = None, entorno: dict[str, str] | None = None):
    return subprocess.run(
        orden,
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, **(entorno or {})},
        timeout=1800,
    )


def red_de_contecrm() -> str | None:
    """La red donde viven los contenedores de contecrm. Se MIDE, no se supone.

    El nombre depende del nombre del proyecto de compose, que a su vez depende
    del directorio o de `COMPOSE_PROJECT_NAME`. Escribirlo aquí funcionaría en la
    máquina de quien lo escribió.
    """
    salida = _correr(["docker", "compose", "--profile", "app", "ps", "--format", "json"], cwd=RAIZ)
    contenedor = ""
    for linea in salida.stdout.splitlines():
        try:
            fila = json.loads(linea)
        except ValueError:
            continue
        if fila.get("Service") == "gateway":
            contenedor = str(fila.get("Name") or "")
            break
    if not contenedor:
        return None
    redes = _correr(
        [
            "docker",
            "inspect",
            contenedor,
            "--format",
            "{{range $k, $_ := .NetworkSettings.Networks}}{{$k}}{{end}}",
        ]
    )
    return (redes.stdout or "").strip() or None


def _enganchado(contenedor: str, red: str) -> bool:
    salida = _correr(
        ["docker", "inspect", contenedor, "--format", "{{json .NetworkSettings.Networks}}"]
    )
    try:
        return red in json.loads(salida.stdout or "{}")
    except ValueError:
        return False


def _enganchar(vecino: Vecino, red: str) -> None:
    """Mete el contenedor del vecino en la red de contecrm con su alias."""
    if _enganchado(vecino.contenedor, red):
        ok(f"{vecino.nombre}: ya está en la red de contecrm")
        return
    salida = _correr(
        ["docker", "network", "connect", "--alias", vecino.alias, red, vecino.contenedor]
    )
    if salida.returncode:
        malo(f"{vecino.nombre}: no se ha podido enganchar a la red — {salida.stderr.strip()[:200]}")
        return
    ok(f"{vecino.nombre}: enganchado a {red} como «{vecino.alias}»")


def _alcanzable(vecino: Vecino, red: str) -> bool:
    """¿Contesta desde DENTRO de la red de contecrm?

    Se comprueba desde dentro y no desde la máquina: lo que importa es si el
    gateway lo ve, y un puerto publicado en el host no dice nada de eso. Es
    justo la diferencia que hizo perder una tarde con contecintelligence.
    """
    salida = _correr(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            red,
            "curlimages/curl:8.11.1",
            "-fsS",
            "-m",
            "5",
            "-o",
            "/dev/null",
            f"{vecino.url_interna()}{vecino.sonda}",
        ]
    )
    return salida.returncode == 0


def _puertos_que_pide(vecino: Vecino, entorno: dict[str, str]):
    """Qué puertos del equipo va a reservar ese compose, resueltos por él mismo.

    Se le pregunta con `config`, que aplica su `.env`, sus valores por defecto y
    sus perfiles. Leer el YAML a mano daría los `${MINIO_PORT:-...}` sin
    resolver, que es justo lo que hay que resolver.
    """
    salida = _correr(
        _compose(vecino, "config", "--format", "json"),
        cwd=vecino.fichero_compose().parent,
        entorno=entorno,
    )
    if salida.returncode:
        return []
    try:
        cfg = json.loads(salida.stdout)
    except ValueError:
        return []
    pedidos: list[tuple[str, str, int]] = []
    for nombre, servicio in (cfg.get("services") or {}).items():
        for puerto in servicio.get("ports") or []:
            publicado = puerto.get("published")
            if publicado is None:
                continue
            pedidos.append((nombre, str(puerto.get("host_ip") or "0.0.0.0"), int(publicado)))
    return pedidos


def _publicados(puertos: str) -> set[int]:
    """Los puertos del equipo que ocupa un contenedor, según `docker ps`.

    Hay que entender los RANGOS —`127.0.0.1:9000-9001->9000-9001/tcp`— y no solo
    los sueltos. Sin ellos, el guardia de choques no veía el MinIO de contecweb,
    que es exactamente el que se llevó por delante media pila de un vecino: un
    guardia que no ve el caso que lo motivó es peor que no tenerlo, porque además
    tranquiliza.
    """
    salida: set[int] = set()
    for trozo in puertos.split(","):
        izquierda = trozo.split("->")[0].strip()
        if ":" not in izquierda:
            continue
        rango = izquierda.rsplit(":", 1)[-1]
        desde, _, hasta = rango.partition("-")
        try:
            primero = int(desde)
            ultimo = int(hasta) if hasta else primero
        except ValueError:
            continue
        # Un rango absurdo no puede colgar esto: se toma como uno solo.
        if ultimo < primero or ultimo - primero > 1000:
            ultimo = primero
        salida.update(range(primero, ultimo + 1))
    return salida


def _quien_tiene(puerto: int, contenedores_propios: set[str]) -> str:
    """Quién ocupa ese puerto, si lo ocupa alguien que no sea el vecino mismo."""
    salida = _correr(["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"])
    for linea in salida.stdout.splitlines():
        nombre, _, puertos = linea.partition("\t")
        if nombre in contenedores_propios:
            continue
        if puerto in _publicados(puertos):
            return nombre
    return ""


def _contenedores_de(vecino: Vecino) -> set[str]:
    salida = _correr(
        _compose(vecino, "ps", "-a", "--format", "{{.Name}}"),
        cwd=vecino.fichero_compose().parent,
    )
    return {n.strip() for n in salida.stdout.splitlines() if n.strip()}


def _puertos_libres(vecino: Vecino, entorno: dict[str, str]) -> list[str]:
    """Los choques de puerto, dichos ANTES de tocar nada.

    Existe porque no comprobarlo salió caro: al levantar contecmind, su MinIO
    pidió el 9000 y lo tenía el de contecweb. El `up` no falló limpio — dejó
    cinco contenedores del vecino PARADOS a medio recrear, o sea peor de como
    estaban. Un arranque que puede dejar el sistema peor tiene que mirar antes.
    """
    propios = _contenedores_de(vecino)
    choques: list[str] = []
    for servicio, _ip, puerto in _puertos_que_pide(vecino, entorno):
        dueno = _quien_tiene(puerto, propios)
        if dueno:
            choques.append(f"{servicio} pide el puerto {puerto} y lo tiene «{dueno}»")
    return choques


def levantar(vecinos: tuple[Vecino, ...]) -> int:
    if not shutil.which("docker"):
        malo("Docker no está disponible: los vecinos se levantan con Docker")
        return 1

    red = red_de_contecrm()
    if red is None:
        malo(
            "contecrm no está levantado, así que su red no existe todavía. "
            "Arranca contecrm primero: los vecinos se enganchan a SU red"
        )
        return 1
    info(f"Red de contecrm: {red}")

    fallos = 0
    for vecino in vecinos:
        print(f"\n{GRIS}── {vecino.nombre} {FIN}")
        compose = vecino.fichero_compose()
        if not compose.exists():
            aviso(
                f"No encuentro su compose en {compose}. Pon la ruta en "
                f"{vecino.variable_repo} si lo tienes en otro sitio"
            )
            # No es un fallo del arranque de contecrm: sin el vecino hay CRM,
            # lo que no hay es la capa que él resuelve. Se dice y se sigue.
            fallos += 1
            continue

        entorno = {k: (v or red) for k, v in vecino.entorno.items()}

        choques = _puertos_libres(vecino, entorno)
        if choques:
            malo(f"{vecino.nombre} no se levanta: hay puertos ocupados por otros")
            for choque in choques:
                info(choque)
            info(
                "En esta máquina conviven varias soluciones de la casa. Cambia el "
                "puerto en el `.env` de ese vecino, o para quien lo tiene. NO se "
                "levanta a medias a propósito: un `up` que choca deja parados los "
                "contenedores que ya iba a recrear, y eso es peor que no arrancar"
            )
            fallos += 1
            continue

        salida = _correr(_compose(vecino, "up", "-d"), cwd=compose.parent, entorno=entorno)
        if salida.returncode:
            malo(f"no ha levantado — {(salida.stderr or salida.stdout).strip()[-400:]}")
            fallos += 1
            continue
        ok("levantado")
        _enganchar(vecino, red)

        for servicio, orden_extra in vecino.despues:
            ejecutada = _correr(
                _compose(vecino, "exec", "-T", servicio, *orden_extra),
                cwd=compose.parent,
                entorno=entorno,
            )
            if ejecutada.returncode:
                malo(
                    f"{' '.join(orden_extra)} en «{servicio}» ha fallado — "
                    f"{(ejecutada.stderr or ejecutada.stdout).strip()[-300:]}"
                )
                fallos += 1
            else:
                ok(f"{' '.join(orden_extra)} aplicado en «{servicio}»")

        if vecino.reiniciar:
            _correr(
                _compose(vecino, "restart", *vecino.reiniciar),
                cwd=compose.parent,
                entorno=entorno,
            )
            ok(f"reiniciado: {', '.join(vecino.reiniciar)}")

        # Se espera a que conteste, no a que el contenedor exista: un contenedor
        # arriba con la aplicación todavía migrando no sirve para nada, y el
        # siguiente paso —comprobar las credenciales— fallaría por eso.
        for intento in range(60):
            if _alcanzable(vecino, red):
                ok(f"responde en {vecino.url_interna()}")
                break
            time.sleep(2)
            if intento == 29:
                info("sigue arrancando…")
        else:
            malo(
                f"no responde en {vecino.url_interna()} después de dos minutos. "
                f"Mira: docker compose -f {compose} logs {vecino.contenedor}"
            )
            fallos += 1
    return 1 if fallos else 0


def _origenes_del_front() -> list[str]:
    """Desde dónde llama el navegador a esta instalación."""
    from crmcore.config import get_settings

    crudos = get_settings().cors_origins or []
    if isinstance(crudos, str):
        crudos = [o.strip() for o in crudos.split(",")]
    return [o for o in crudos if o]


def _cors_permitido(vecino: Vecino, origen: str) -> bool | None:
    """¿Deja ese vecino que el navegador le llame desde el front del CRM?

    Se pregunta con un preflight de verdad contra el puerto PUBLICADO, no por la
    red interna: lo que se comprueba es lo que hace el navegador, y por la red
    interna el CORS no aparece por ninguna parte.

    Existe porque no se veía. La aplicación anfitriona de contecrm tenía
    registrado `localhost:5173` —el puerto estándar de Vite— y el front de esta
    instalación escucha en el 15173. Un dígito. El navegador cortaba la petición
    en el preflight y la pantalla decía «no se pudo responder», que manda a
    buscar el fallo al modelo, a la fuente o a los permisos: a cualquier sitio
    menos al que era.

    Devuelve `None` si no se ha podido comprobar, que no es lo mismo que «no».
    """
    from crmcore.config import get_settings

    url = str(getattr(get_settings(), vecino.ajuste_url.lower(), "") or "")
    publica = _url_publicada(vecino) or url
    if not publica or not vecino.sonda_navegador:
        return None
    try:
        import httpx

        respuesta = httpx.request(
            "OPTIONS",
            publica.rstrip("/") + vecino.sonda_navegador,
            headers={
                "Origin": origen,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
            timeout=10.0,
        )
    except Exception:  # noqa: BLE001 — no poder comprobarlo no es un fallo del CORS
        return None
    return respuesta.status_code < 400 and bool(
        respuesta.headers.get("access-control-allow-origin")
    )


def _url_publicada(vecino: Vecino) -> str:
    """Su dirección vista desde el EQUIPO, que es por donde llama el navegador."""
    salida = _correr(["docker", "port", vecino.contenedor, str(vecino.puerto_interno)])
    primera = (salida.stdout or "").strip().splitlines()
    if not primera:
        return ""
    destino = primera[0].strip()
    puerto = destino.rsplit(":", 1)[-1]
    return f"http://127.0.0.1:{puerto}" if puerto.isdigit() else ""


def _credencial_vale(vecino: Vecino) -> bool | None:
    """¿La credencial de aplicación del `.env` sigue valiendo ALLÍ?

    Que el vecino conteste no significa que nos conozca. Su base se puede
    restaurar, se puede perder un volumen, alguien puede revocar la aplicación —
    y entonces el servicio responde perfectamente y **todo** lo que pasa por él
    falla con «ha rechazado la credencial de aplicación», que parece un problema
    de red y no lo es.

    Pasó hoy: al perderse el volumen de contecintelligence desapareció la
    aplicación `contecrm` registrada allí, y el estado seguía diciendo que todo
    estaba bien mientras ningún informe se podía ejecutar.

    Devuelve `None` si no se ha podido comprobar, que no es lo mismo que «no».
    """
    from crmcore.config import get_settings

    s = get_settings()
    if not vecino.ruta_token:
        return None
    cliente = str(getattr(s, vecino.ajuste_cliente.lower(), "") or "")
    secreto = getattr(s, vecino.ajuste_secreto.lower(), "")
    secreto = secreto.get_secret_value() if hasattr(secreto, "get_secret_value") else str(secreto)
    if not cliente or not secreto:
        return False
    publica = _url_publicada(vecino) or str(getattr(s, vecino.ajuste_url.lower(), "") or "")
    if not publica:
        return None
    try:
        import httpx

        respuesta = httpx.post(
            publica.rstrip("/") + vecino.ruta_token,
            json={"client_id": cliente, "client_secret": secreto},
            timeout=15.0,
        )
    except Exception:  # noqa: BLE001 — no poder comprobarlo no es un «no vale»
        return None
    if respuesta.status_code >= 400:
        return False
    return _alcances_que_faltan(vecino, respuesta)


def _alcances_que_faltan(vecino: Vecino, respuesta: Any) -> bool | list[str]:
    """Lo que pedimos y NO nos conceden.

    Un canje que sale bien no quiere decir que podamos hacer lo que vamos a
    hacer: los alcances los fija el alta de la aplicación al otro lado, y pedir
    uno que no está concedido no falla aquí. Falla el día que alguien pulsa el
    botón, con un 403 que en la pantalla se lee como «no tienes permiso» — y no
    es de la persona, es de la aplicación.

    Devuelve `True` cuando está todo, o la lista de los que faltan.
    """
    from crmcore.config import get_settings

    if not vecino.ajuste_alcances:
        return True
    pedidos = list(getattr(get_settings(), vecino.ajuste_alcances.lower(), ()) or ())
    if not pedidos:
        return True
    try:
        datos = respuesta.json()
    except Exception:  # noqa: BLE001
        return True
    # `scope` separado por espacios es lo que dice OAuth2; se acepta también una
    # lista, que es como lo devuelve alguno de la casa. Si no viene ninguno de
    # los dos no se inventa un veredicto: se da por bueno.
    crudo = datos.get("scope", datos.get("scopes"))
    if crudo is None:
        return True
    concedidos = set(crudo.split()) if isinstance(crudo, str) else {str(x) for x in crudo}
    faltan = [a for a in pedidos if a not in concedidos]
    return faltan or True


def estado(vecinos: tuple[Vecino, ...]) -> int:
    red = red_de_contecrm()
    if red is None:
        aviso("contecrm no está levantado")
        return 1
    from crmcore.config import get_settings

    s = get_settings()
    peor = 0
    for vecino in vecinos:
        activo = bool(getattr(s, vecino.ajuste_activo.lower(), False))
        url = str(getattr(s, vecino.ajuste_url.lower(), "") or "")
        if not activo:
            aviso(f"{vecino.nombre}: apagado en la configuración ({vecino.ajuste_activo}=false)")
            peor = 1
            continue
        if not url:
            malo(f"{vecino.nombre}: encendido y sin dirección ({vecino.ajuste_url} vacío)")
            peor = 1
            continue
        if _alcanzable(vecino, red):
            ok(f"{vecino.nombre}: responde en {url}")
        else:
            malo(f"{vecino.nombre}: NO responde en {url}")
            peor = 1
            continue

        # Que conteste no basta: que nos CONOZCA. Una base restaurada o un
        # volumen perdido dejan al vecino sano y a nosotros sin aplicación
        # registrada, y eso se ve como un fallo de red que no lo es.
        credencial = _credencial_vale(vecino)
        if credencial is False:
            malo(
                f"{vecino.nombre}: responde pero RECHAZA nuestra credencial "
                f"({vecino.ajuste_cliente}). Hay que volver a dar de alta la "
                "aplicación allí y poner sus datos en el `.env`"
            )
            peor = 1
        elif isinstance(credencial, list):
            malo(
                f"{vecino.nombre}: acepta la credencial pero NO concede "
                f"{', '.join(credencial)}. Lo pide el `.env` en "
                f"{vecino.ajuste_alcances} y lo decide el alta de la aplicación "
                "allí: hay que ampliarla, o lo que dependa de ese alcance dará "
                "403 el día que alguien lo use"
            )
            peor = 1
        elif credencial:
            ok(f"{vecino.nombre}: acepta nuestra credencial y concede lo que le pedimos")

        # Y, si alguna pantalla le llama desde el navegador, que el origen del
        # front esté permitido allí. Responder bien al servidor y cortar al
        # navegador se ve igual desde fuera: la pantalla no funciona.
        for origen in _origenes_del_front():
            permitido = _cors_permitido(vecino, origen)
            if permitido is False:
                malo(
                    f"{vecino.nombre}: rechaza al navegador desde «{origen}». "
                    "La pantalla que le llama desde el front no puede funcionar"
                )
                peor = 1
            elif permitido:
                ok(f"{vecino.nombre}: acepta al navegador desde «{origen}»")
    return peor


def parar(vecinos: tuple[Vecino, ...]) -> int:
    for vecino in vecinos:
        compose = vecino.fichero_compose()
        if not compose.exists():
            continue
        _correr(_compose(vecino, "down"), cwd=compose.parent)
        ok(f"{vecino.nombre} parado")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("orden", choices=["levantar", "estado", "parar"])
    parser.add_argument("--solo", choices=[v.nombre for v in VECINOS])
    args = parser.parse_args()

    elegidos = tuple(v for v in VECINOS if not args.solo or v.nombre == args.solo)
    return {"levantar": levantar, "estado": estado, "parar": parar}[args.orden](elegidos)


if __name__ == "__main__":
    raise SystemExit(main())
