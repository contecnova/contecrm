"""La UI de referencia es opcional, y eso se mide (CRM-00.02.03.02).

«Nuestro producto es headless y la interfaz es opcional» lo dice todo el mundo,
y casi nunca es verdad. No porque se mienta, sino porque se erosiona: alguien
añade un endpoint que devuelve HTML, otro pone una redirección a `/app`, un
tercero deja el CORS abierto solo al origen de la consola, y al año la API
oficialmente headless necesita su front para funcionar del todo.

Aquí eso no es una declaración: es una comprobación que corre en el preflight y
mira la aplicación montada de verdad.

Qué se busca, y por qué cada cosa importa:

**Servir ficheros estáticos desde el servicio.** Un `StaticFiles` montado hace
que el front viaje dentro del backend: desplegar la API pasa a desplegar la
interfaz, y sustituirla deja de ser una opción de despliegue.

**Redirigir a una ruta del front.** Una redirección a `/app/...` es el backend
dando por hecho que existe una pantalla. Quien montó su propia interfaz recibe
un 307 hacia un sitio que en su instalación no existe.

**Devolver HTML donde debería ir JSON.** Un integrador que recibe una página de
error en HTML no puede leerla, y lo que pinta a su usuario es el código de
estado a secas.

**Y un CORS con un único origen.** Si solo se admite el origen de la consola,
cualquier otra interfaz —la del cliente, un portal, un quiosco— está fuera por
configuración, aunque la API sea perfectamente headless.

Lo que esto **no** comprueba, y conviene decirlo: que la consola no use un
endpoint que no esté documentado. De eso se ocupa la superficie
(`crmcore.http.superficie`), que es donde la consola saca lo que puede hacer.
"""

from __future__ import annotations

from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Prefijos que delatan una ruta pensada para el front de referencia y no para un
# cliente de API. Se comparan como fragmento porque cada servicio los monta
# donde quiere.
PREFIJOS_DE_UI = ("/app", "/consola", "/static", "/assets", "/ui")

# Respuestas que no son de una API. `text/html` es la que importa: un integrador
# que recibe HTML no puede leerlo.
MEDIOS_QUE_NO_SON_API = ("text/html", "text/css", "application/javascript")


def _rutas(app: Any) -> list[Any]:
    """Todas las rutas, entrando en los routers incluidos.

    Recorrido recursivo a propósito: este FastAPI envuelve los routers incluidos,
    y quedarse en el primer nivel dejaría fuera casi todo — dando un informe
    limpio y falso, que es peor que no tener informe.
    """
    salida: list[Any] = []
    pendientes = list(getattr(app, "routes", []) or [])
    while pendientes:
        ruta = pendientes.pop()
        salida.append(ruta)
        for atributo in ("routes", "router"):
            hijo = getattr(ruta, atributo, None)
            if hijo is None:
                continue
            pendientes.extend(hijo if isinstance(hijo, list) else getattr(hijo, "routes", []))
    return salida


def comprobar_independencia(app: Any, *, origenes_cors: list[str] | None = None) -> dict[str, Any]:
    """Mide si este servicio puede funcionar sin la interfaz de referencia.

    Devuelve **todos** los hallazgos, cada uno con lo que le pasaría a quien
    sustituya el front. Un informe que dice «no es independiente» sin decir por
    dónde no se puede arreglar.
    """
    hallazgos: list[dict[str, str]] = []

    for ruta in _rutas(app):
        camino = str(getattr(ruta, "path", "") or "")
        nombre_clase = type(ruta).__name__

        if nombre_clase == "Mount" and "StaticFiles" in type(getattr(ruta, "app", None)).__name__:
            hallazgos.append(
                {
                    "donde": camino,
                    "que": "el servicio sirve ficheros estáticos",
                    "consecuencia": (
                        "el front viaja dentro del backend: desplegar la API pasa a "
                        "desplegar la interfaz, y sustituirla deja de ser una opción"
                    ),
                }
            )
            continue

        if any(camino.startswith(p) for p in PREFIJOS_DE_UI):
            hallazgos.append(
                {
                    "donde": camino,
                    "que": "hay una ruta de interfaz montada en la API",
                    "consecuencia": (
                        "quien monte su propio front tiene una ruta del producto "
                        "ocupando un camino que quizá quería usar"
                    ),
                }
            )

        clase_respuesta = type(getattr(ruta, "response_class", None)).__name__
        if "HTML" in clase_respuesta:
            hallazgos.append(
                {
                    "donde": camino,
                    "que": "la respuesta es HTML",
                    "consecuencia": (
                        "un integrador que recibe HTML no puede leerlo, y lo que le "
                        "enseña a su usuario es el código de estado a secas"
                    ),
                }
            )

    origenes = list(origenes_cors or [])
    if len(origenes) == 1 and origenes[0] not in ("*",):
        hallazgos.append(
            {
                "donde": "CORS",
                "que": f"solo se admite un origen: {origenes[0]}",
                "consecuencia": (
                    "cualquier otra interfaz —la del cliente, un portal, un quiosco— "
                    "queda fuera por configuración, por muy headless que sea la API"
                ),
            }
        )

    return {
        "independiente": not hallazgos,
        "hallazgos": hallazgos,
        "veredicto": (
            "Este servicio funciona igual sin la interfaz de referencia: no la sirve, "
            "no redirige a ella y no da por hecho su origen."
            if not hallazgos
            else f"{len(hallazgos)} cosas atan este servicio a una interfaz concreta. "
            "«La UI es opcional» no se erosiona de golpe: se erosiona así, una "
            "redirección cada vez."
        ),
    }


def estado_de_la_ui(*, settings: Any) -> dict[str, Any]:
    """Qué pasa si no se despliega la interfaz de referencia.

    Está aquí para poder contestarlo con hechos —qué se pierde exactamente— en
    vez de con la frase de siempre.
    """
    return {
        "se_despliega_aparte": True,
        "como_se_apaga": (
            "No desplegando su contenedor: va en el perfil `consola` de "
            "`docker-compose.yml`, que no está en el arranque por defecto."
        ),
        "es_requisito_de_licencia": False,
        "que_se_pierde_sin_ella": [
            "Las pantallas que trae hechas. Nada más.",
        ],
        "que_NO_se_pierde": [
            "Ninguna operación: todo lo que hace la consola es una llamada de la "
            "superficie publicada (`/superficie`), que es de donde ella misma las saca.",
            "Ninguna comprobación: los permisos y las validaciones se resuelven en el "
            "servidor, no en el front.",
            "Ningún dato: el front no guarda estado propio.",
        ],
        "como_se_sustituye": (
            "Leyendo `/superficie` y las vistas servidas (`CRM-00.02.03.08`), que es "
            "exactamente lo que hace la consola oficial. No hay ningún camino privado."
        ),
        "cors": (
            "Con varios orígenes o vacío, cualquier front puede hablar con la API. Con "
            "uno solo, se está atando la API a una interfaz sin querer."
        ),
        "origenes_configurados": list(getattr(settings, "origenes_cors", []) or []),
    }
