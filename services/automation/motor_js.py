"""El motor que ejecuta el código del tenant (CRM-00.04.02.01).

JavaScript, en QuickJS compilado a WebAssembly (WASI) por su propio proyecto
—quickjs-ng—, y ejecutado por wasmtime. Se eligió así, y no un intérprete de
JavaScript enlazado en el proceso, porque es la pieza que aísla código ajeno:

- **No hay nada fuera.** El módulo no recibe ficheros —ningún directorio
  abierto—, ni variables de entorno, ni red: WASI sin enchufes. Lo único que
  entra es la entrada por la entrada estándar, y lo único que sale es lo que
  escribe en la salida. Y `std` y `os` se le quitan antes de que corra su código.
- **Los topes los pone el motor**, no el código: combustible (instrucciones de
  WebAssembly), memoria (lo que puede crecer la memoria lineal) y reloj. Una
  función que se pasa no «avisa»: se corta, y se dice por cuál.
- **Y el motor se comprueba.** Su huella está fijada en
  `motor_js.lock.json`; si el fichero no cuadra, no se ejecuta nada. Un motor
  cambiado es justo lo que no puede ejecutar código ajeno.

El reloj necesita un detalle: wasmtime corta por «épocas» del motor, y el motor
es uno para todas las ejecuciones. Si cada ejecución avanzara la época al
pasarse de tiempo, cortaría también a las demás que estuvieran corriendo. Por
eso hay UN reloj que la avanza cada `EXTENSIONES_RELOJ_MS`, y cada ejecución pide que la
corten pasadas sus N épocas.

La función del tenant es `function main(entrada) { ... }`, y puede ser `async`.
Lo que devuelve es su resultado; `console.log` se apunta aparte, hasta
`EXTENSIONES_LOGS_MAX` líneas.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crmcore.errors import ErrorInterno
from crmcore.logging import get_logger

logger = get_logger(__name__)

CANDADO = Path(__file__).with_name("motor_js.lock.json")

_cargado: tuple[Any, Any] | None = None
_cerrojo = threading.Lock()
_reloj: threading.Thread | None = None


@dataclass(frozen=True)
class Limites:
    tiempo_ms: int
    memoria_mb: int
    combustible: int
    entrada_kb: int
    salida_kb: int
    logs_max: int

    @classmethod
    def de_ajustes(cls) -> Limites:
        from crmcore.config import get_settings

        s = get_settings()
        return cls(
            tiempo_ms=s.extensiones_tiempo_ms,
            memoria_mb=s.extensiones_memoria_mb,
            combustible=s.extensiones_combustible,
            entrada_kb=s.extensiones_entrada_kb,
            salida_kb=s.extensiones_salida_kb,
            logs_max=s.extensiones_logs_max,
        )


def candado() -> dict[str, str]:
    return dict(json.loads(CANDADO.read_text()))


def ruta_del_motor() -> Path:
    from crmcore.config import get_settings

    ajustada = get_settings().extensiones_motor_ruta
    if ajustada:
        return Path(ajustada)
    return Path(__file__).resolve().parents[2] / "var" / "motor" / candado()["fichero"]


def estado_del_motor() -> dict[str, Any]:
    """Si el motor está y cuadra, sin cargarlo. Lo enseña la ficha del servicio."""
    fijado = candado()
    ruta = ruta_del_motor()
    if not ruta.exists():
        return {
            "listo": False,
            "version": fijado["version"],
            "porque": f"No está el motor en {ruta}: hay que traerlo con "
            "`python scripts/traer_motor_js.py`.",
        }
    huella = hashlib.sha256(ruta.read_bytes()).hexdigest()
    if huella != fijado["sha256"]:
        return {
            "listo": False,
            "version": fijado["version"],
            "porque": "La huella del motor no coincide con la fijada: no se ejecuta "
            "nada con un motor cambiado.",
        }
    return {"listo": True, "version": fijado["version"], "huella": huella}


def _cargar() -> tuple[Any, Any]:
    """El motor de wasmtime y el módulo compilado, una vez por proceso."""
    global _cargado
    if _cargado is not None:
        return _cargado
    with _cerrojo:
        if _cargado is not None:
            return _cargado
        estado = estado_del_motor()
        if not estado["listo"]:
            raise ErrorInterno(
                f"El motor de las extensiones no está disponible. {estado['porque']}",
                error_code="extension.motor_no_disponible",
            )
        from wasmtime import Config, Engine, Module

        configuracion = Config()
        configuracion.consume_fuel = True
        configuracion.epoch_interruption = True
        motor = Engine(configuracion)
        modulo = Module.from_file(motor, str(ruta_del_motor()))
        _cargado = (motor, modulo)
        _arrancar_reloj(motor)
        return _cargado


def _tick_s() -> float:
    """Cada cuánto avanza la época: la resolución del corte por reloj
    (`EXTENSIONES_RELOJ_MS`). Con 10 ms, un tope de 2 s corta entre 2,00 y 2,01."""
    from crmcore.config import get_settings

    return get_settings().extensiones_reloj_ms / 1000


def _arrancar_reloj(motor: Any) -> None:
    global _reloj
    tick = _tick_s()

    def _latir() -> None:
        while True:
            time.sleep(tick)
            motor.increment_epoch()

    _reloj = threading.Thread(target=_latir, name="reloj-extensiones", daemon=True)
    _reloj.start()


# Lo que rodea al código del tenant. Le quita `std` y `os` —la salida y la
# entrada las usa sólo esto—, recoge `console.*` aparte y escribe UNA línea con
# el resultado. Si `main` es asíncrona, se espera.
_ENVOLTORIO = """
const __std = std;
const __entrada = JSON.parse(__std.in.readAsString());
const __logs = [];
const __max = %(logs_max)d;
const __texto = (a) => a.map((x) => (typeof x === "string" ? x : JSON.stringify(x))).join(" ");
const __apuntar = (nivel) => (...a) => {
  if (__logs.length < __max) __logs.push({ nivel, texto: __texto(a).slice(0, 2000) });
};
globalThis.console = { log: __apuntar("info"), info: __apuntar("info"),
  warn: __apuntar("aviso"), error: __apuntar("error") };
delete globalThis.std;
delete globalThis.os;
const __fin = (r) => { r.logs = __logs; __std.out.puts(JSON.stringify(r)); __std.out.flush(); };
const __fallo = (e) => __fin({ ok: false,
  error: String((e && e.message) || e), pila: String((e && e.stack) || "") });
try {
  const __main = (function () {
%(codigo)s
;
    return typeof main === "function" ? main : undefined;
  })();
  if (!__main) throw new Error("El código no define function main(entrada)");
  const __r = __main(__entrada);
  if (__r && typeof __r.then === "function") {
    __r.then((v) => __fin({ ok: true, resultado: v === undefined ? null : v }), __fallo);
  } else {
    __fin({ ok: true, resultado: __r === undefined ? null : __r });
  }
} catch (e) { __fallo(e); }
"""


# Las líneas del envoltorio que van antes del código del tenant: un error de
# sintaxis llega con la línea del conjunto («<cmdline>:19»), y quien escribió la
# función tiene que ver la suya.
_DESFASE = _ENVOLTORIO.split("%(codigo)s")[0].count("\n")


def _sus_lineas(texto: str) -> str:
    import re

    return re.sub(
        r"<cmdline>:(\d+)(?::(\d+))?",
        lambda m: f"línea {max(1, int(m.group(1)) - _DESFASE)}"
        + (f", columna {m.group(2)}" if m.group(2) else ""),
        texto,
    )


def ejecutar(codigo: str, entrada: Any, limites: Limites | None = None) -> dict[str, Any]:
    """Ejecuta `main(entrada)` y devuelve qué pasó. No lanza por culpa del código.

    Devuelve `ok`, `resultado`, `logs`, `ms`, `combustible` gastado y, si se
    cortó, `cortada_por` (`tiempo`, `cpu` o `memoria`). Un fallo del código del
    tenant es un resultado, no una excepción: lo que se lanza es sólo lo que es
    nuestro —el motor que no está—.
    """
    from wasmtime import Linker, Store, Trap, TrapCode, WasiConfig, WasmtimeError

    limites = limites or Limites.de_ajustes()
    entrada_json = json.dumps(entrada, ensure_ascii=False, default=str)
    if len(entrada_json.encode()) > limites.entrada_kb * 1024:
        return {
            "ok": False,
            "error": f"La entrada pasa de {limites.entrada_kb} KB.",
            "logs": [],
            "ms": 0,
            "combustible": 0,
            "cortada_por": "entrada",
        }
    motor, modulo = _cargar()
    almacen = Store(motor)
    almacen.set_fuel(limites.combustible)
    almacen.set_limits(memory_size=limites.memoria_mb * 1024 * 1024)
    almacen.set_epoch_deadline(max(1, int(limites.tiempo_ms / 1000 / _tick_s())))

    carpeta = tempfile.mkdtemp(prefix="ext-")
    try:
        f_entrada = os.path.join(carpeta, "entrada")
        f_salida = os.path.join(carpeta, "salida")
        f_errores = os.path.join(carpeta, "errores")
        Path(f_entrada).write_text(entrada_json)
        wasi = WasiConfig()
        # Ni directorios abiertos, ni entorno, ni red: lo que no se le da no lo
        # tiene. El código va como argumento del intérprete.
        wasi.argv = [
            "qjs",
            "--std",
            "-e",
            _ENVOLTORIO % {"codigo": codigo, "logs_max": limites.logs_max},
        ]
        wasi.stdin_file = f_entrada
        wasi.stdout_file = f_salida
        wasi.stderr_file = f_errores
        almacen.set_wasi(wasi)
        enlazador = Linker(motor)
        enlazador.define_wasi()

        inicio = time.perf_counter()
        cortada_por: str | None = None
        error_motor = ""
        try:
            instancia = enlazador.instantiate(almacen, modulo)
            instancia.exports(almacen)["_start"](almacen)
        except Trap as trampa:
            codigo_trampa = getattr(trampa, "trap_code", None)
            if codigo_trampa == TrapCode.INTERRUPT:
                cortada_por = "tiempo"
            elif codigo_trampa == TrapCode.OUT_OF_FUEL:
                cortada_por = "cpu"
            else:
                error_motor = str(trampa).splitlines()[0]
        except WasmtimeError as exc:
            # La salida del intérprete con código distinto de cero llega así.
            error_motor = str(exc).splitlines()[0]
        ms = int((time.perf_counter() - inicio) * 1000)
        gastado = limites.combustible - almacen.get_fuel()

        salida_bytes = Path(f_salida).stat().st_size if os.path.exists(f_salida) else 0
        errores = (
            Path(f_errores).read_text(errors="replace")[:4000] if os.path.exists(f_errores) else ""
        )
        if salida_bytes > limites.salida_kb * 1024:
            return {
                "ok": False,
                "error": f"El resultado pasa de {limites.salida_kb} KB.",
                "logs": [],
                "ms": ms,
                "combustible": gastado,
                "cortada_por": "salida",
            }
        lineas = (
            Path(f_salida).read_text(errors="replace").strip().splitlines() if salida_bytes else []
        )
        final: dict[str, Any] = {}
        if lineas:
            try:
                final = json.loads(lineas[-1])
            except ValueError:
                final = {}
        if "out of memory" in (errores + str(final.get("error") or "")).lower():
            cortada_por = "memoria"
        if cortada_por:
            mensajes = {
                "tiempo": f"Se ha cortado a los {limites.tiempo_ms} ms.",
                "cpu": "Se ha cortado al gastar su combustible: demasiadas instrucciones.",
                "memoria": f"Se ha cortado al pasar de {limites.memoria_mb} MB de memoria.",
            }
            return {
                "ok": False,
                "error": mensajes[cortada_por],
                "logs": final.get("logs") or [],
                "ms": ms,
                "combustible": gastado,
                "cortada_por": cortada_por,
            }
        if not final:
            return {
                "ok": False,
                "error": _sus_lineas(errores.strip() or error_motor or "No ha devuelto nada.")[
                    :2000
                ],
                "logs": [],
                "ms": ms,
                "combustible": gastado,
                "cortada_por": None,
            }
        return {
            "ok": bool(final.get("ok")),
            "resultado": final.get("resultado"),
            "error": _sus_lineas(final.get("error") or ""),
            "pila": _sus_lineas(final.get("pila") or ""),
            "logs": final.get("logs") or [],
            "ms": ms,
            "combustible": gastado,
            "cortada_por": None,
        }
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)
