"""Gates de arquitectura: invariantes que no se pueden dejar a la disciplina.

Son pruebas normales, no hooks, y eso es a propósito: corren con `pytest`, salen
en el resumen y no hacen falta dos mecanismos para lo mismo.

Cada una fija una invariante que, de romperse, no daría ningún síntoma inmediato
—y ese es justo el tipo de fallo que hay que atrapar con una prueba, no con una
revisión.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SERVICIOS_DIR = RAIZ / "services"
CORE_DIR = RAIZ / "packages" / "crmcore" / "crmcore"

SERVICIOS = sorted(
    p.name for p in SERVICIOS_DIR.iterdir() if p.is_dir() and not p.name.startswith("_")
)


def _modulos(directorio: Path) -> list[Path]:
    return [p for p in directorio.rglob("*.py") if "__pycache__" not in str(p)]


# ── Aislamiento entre servicios ───────────────────────────────────────────


def test_ningun_servicio_importa_modulos_de_otro() -> None:
    """Un servicio no puede importar código de otro servicio.

    Si pudiera, la separación sería decorativa: desplegar uno obligaría a
    desplegar el otro, y la «propiedad exclusiva de datos» se saltaría por la
    vía de importar sus modelos.

    La única excepción admitida es importar del **motor de procesos** los
    ayudantes de evaluación de condiciones (`services.orchestrator.motor`), que
    son lógica pura sin estado y que de otro modo estarían duplicados en tres
    sitios. Está aquí escrito para que sea una decisión y no un descuido.
    """
    excepciones = {
        ("automation", "orchestrator"),
        ("metadata", "orchestrator"),
        ("eventing", "orchestrator"),
    }
    infracciones: list[str] = []

    for servicio in SERVICIOS:
        for fichero in _modulos(SERVICIOS_DIR / servicio):
            arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
            for nodo in ast.walk(arbol):
                modulo = ""
                if isinstance(nodo, ast.ImportFrom) and nodo.module:
                    modulo = nodo.module
                elif isinstance(nodo, ast.Import):
                    modulo = nodo.names[0].name
                if not modulo.startswith("services."):
                    continue
                ajeno = modulo.split(".")[1]
                if ajeno == servicio or (servicio, ajeno) in excepciones:
                    continue
                infracciones.append(
                    f"{fichero.relative_to(RAIZ)} importa «{modulo}» (servicio «{ajeno}»)"
                )

    assert not infracciones, "Servicios acoplados:\n  " + "\n  ".join(infracciones)


def test_el_nucleo_no_importa_servicios() -> None:
    """`crmcore` no puede depender de ningún servicio.

    Es lo que mantiene la dirección de la dependencia: los servicios usan el
    núcleo, no al revés. Un solo import en sentido contrario convierte el
    núcleo en un monolito con otro nombre.
    """
    infracciones = [
        f"{f.relative_to(RAIZ)}: {linea.strip()}"
        for f in _modulos(CORE_DIR)
        for linea in f.read_text(encoding="utf-8").splitlines()
        if re.match(r"\s*(from|import)\s+services\.", linea)
    ]
    assert not infracciones, "El núcleo depende de servicios:\n  " + "\n  ".join(infracciones)


# ── Multi-tenancy ─────────────────────────────────────────────────────────

# Tablas que legítimamente NO llevan `tenant_id`, con su motivo. Añadir una a
# esta lista tiene que costar escribir por qué: cada excepción es un punto ciego
# para las dos redes de aislamiento (RLS y el guard ORM), que seleccionan las
# tablas por esa misma columna.
SIN_TENANT_JUSTIFICADAS: dict[str, str] = {
    "tenants": "ES el registro de tenants; filtrarla por sí misma impediría resolverlos",
    "usuarios": (
        "una persona puede pertenecer a varios tenants sin duplicar identidad; "
        "quien acota es `membresias`, y las consultas de usuarios unen por ella"
    ),
    "planes": "catálogo comercial común a todos los tenants",
    "alembic_version": "tabla de control de migraciones, no de negocio",
    "ajustes_runtime": (
        "guarda valores de CINCO ámbitos a la vez (global, tier, tenant, unidad "
        "de negocio y usuario), y los dos primeros no pertenecen a ningún "
        "tenant. Una columna `tenant_id` NOT NULL no podría representarlos, y "
        "una nullable rompería la garantía que este gate defiende. El "
        "aislamiento lo da la clave primaria (clave, ambito, ambito_id): una "
        "lectura SIEMPRE fija los dos últimos, y eso lo comprueba "
        "`test_los_ajustes_siempre_filtran_por_ambito`"
    ),
}


def test_toda_tabla_de_negocio_lleva_tenant_id() -> None:
    """Sin excepciones no justificadas (ver `crmcore.db.base`).

    Es la corrección deliberada de una limitación conocida de contecmind, donde
    58 de 107 modelos tienen `tenant_id` y el resto depende de filtros de
    propiedad. Funciona y está auditado, pero significa que las dos redes
    automáticas comparten punto ciego. Aquí la columna es obligatoria y esto lo
    comprueba.
    """
    import importlib

    for modulo in [
        "crmcore.audit.modelos",
        "crmcore.bus.modelos",
        "crmcore.http.idempotency",
        "crmcore.runtime.settings",
        *[f"services.{s}.modelos" for s in SERVICIOS],
    ]:
        try:
            importlib.import_module(modulo)
        except ModuleNotFoundError:
            continue

    from crmcore.db.base import Base

    sin_tenant: list[str] = []
    for mapper in Base.registry.mappers:
        tabla = mapper.local_table
        if tabla is None:
            continue
        nombre = tabla.name
        if nombre in SIN_TENANT_JUSTIFICADAS:
            continue
        if "tenant_id" not in tabla.columns:
            sin_tenant.append(f"{nombre} ({mapper.class_.__name__})")

    assert not sin_tenant, (
        "Tablas de negocio sin `tenant_id`:\n  "
        + "\n  ".join(sin_tenant)
        + "\n\nSi alguna es legítima, añádela a SIN_TENANT_JUSTIFICADAS con su motivo."
    )


def test_tenant_id_es_obligatorio_donde_existe() -> None:
    """`tenant_id` NOT NULL: una fila con tenant nulo sería visible desde todos.

    Las excepciones son las tablas de infraestructura del bus, donde hay eventos
    de plataforma sin tenant (el alta de un tenant, por ejemplo).
    """
    import importlib

    for modulo in [
        "crmcore.audit.modelos",
        "crmcore.bus.modelos",
        *[f"services.{s}.modelos" for s in SERVICIOS],
    ]:
        try:
            importlib.import_module(modulo)
        except ModuleNotFoundError:
            continue

    from crmcore.db.base import Base

    nullables_justificados = {
        "eventos_salientes",
        "eventos_entrantes",
        "eventos_fallidos",
        "feature_flags",
    }
    malos: list[str] = []
    for mapper in Base.registry.mappers:
        tabla = mapper.local_table
        if tabla is None or "tenant_id" not in tabla.columns:
            continue
        if tabla.name in nullables_justificados:
            continue
        if tabla.columns["tenant_id"].nullable:
            malos.append(tabla.name)

    assert not malos, f"Tablas con `tenant_id` nullable: {malos}"


# ── Contrato de API ───────────────────────────────────────────────────────


def test_toda_ruta_de_escritura_exige_permiso() -> None:
    """Ninguna ruta que escribe puede quedarse sin comprobación de permiso.

    Se comprueba sobre el ÁRBOL del código y no ejecutando la aplicación,
    porque lo que interesa es que el permiso esté declarado en la ruta
    (`dependencies=[Depends(exige_permiso(...))]`) y no escondido dentro de la
    función: una comprobación escondida no se puede auditar sin ejecutarla.
    """
    # Rutas de escritura que legítimamente no exigen permiso previo, con motivo.
    exentas = {
        "login": "es la ruta que otorga identidad; exigir permiso sería circular",
        "refrescar": "valida el token de refresco, que es su propia credencial",
        "logout": "cerrar la propia sesión solo exige tenerla",
        "iniciar_mfa": "el usuario configura su propio segundo factor",
        "activar_mfa": "ídem",
        "cerrar_sesion": "cierra una sesión propia; la comprobación va dentro",
        "responder": "la asignación de la tarea ES el permiso; se comprueba dentro",
        "delegar": "ídem: solo puede delegar quien la tiene asignada",
        "suplantar": "la comprobación es «ser personal de plataforma», dentro del servicio",
        "proxy_api": "el gateway reenvía; el permiso lo aplica el servicio destino",
        # El permiso depende de la OPERACIÓN que trae el cuerpo (crear,
        # actualizar, borrar), y una dependencia de ruta se resuelve antes de
        # leerlo. Declarar uno solo obligaría a exigir el más fuerte para todas,
        # y quien solo puede actualizar no podría actualizar en lote.
        # Que la comprobación exista y funcione no se queda sin probar: lo cubre
        # `test_sin_el_permiso_de_la_operacion_se_rechaza` en
        # `test_trabajos_y_masivo.py`, contra la API real montada.
        "masivo": "el permiso depende de la operación del cuerpo; se comprueba dentro",
        # Endpoint PÚBLICO de captura de leads (CRM-01.01.03.02): lo llama el
        # navegador de un desconocido desde la web del cliente, así que no hay
        # usuario que pueda tener un permiso. No es anónimo: lo autoriza la clave
        # del canal, y además tiene trampa para robots y tope por hora. Está
        # probado en `test_captura_leads.py`, incluido que un canal de otro
        # tenant no sirve.
        "recibir_lead": "público por diseño; lo autoriza la clave del canal, no un permiso",
    }

    # Los routers COMPARTIDOS del núcleo también escriben, y montarlos desde
    # varios servicios no los exime: al contrario, un agujero ahí sale
    # multiplicado por todos los servicios que los monten. Mirar solo
    # `services/*/api.py` era un punto ciego, y se descubrió al montar los de
    # adjuntos y comentarios: seis rutas de escritura sin permiso que el gate
    # daba por buenas.
    ficheros = [SERVICIOS_DIR / s / "api.py" for s in SERVICIOS]
    ficheros += sorted((RAIZ / "packages" / "crmcore" / "crmcore" / "http").glob("*_router.py"))

    sin_permiso: list[str] = []
    for fichero in ficheros:
        if not fichero.exists():
            continue
        etiqueta = f"{fichero.parent.name}/{fichero.name}"
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in nodo.decorator_list:
                if not isinstance(deco, ast.Call):
                    continue
                metodo = getattr(deco.func, "attr", "")
                if metodo not in ("post", "put", "patch", "delete", "api_route"):
                    continue
                texto = ast.unparse(deco)
                if "exige_permiso" in texto or nodo.name in exentas:
                    continue
                # `PlataformaDep` en los argumentos también es una comprobación
                # declarada, y más restrictiva que cualquier permiso.
                if "PlataformaDep" in ast.unparse(nodo.args):
                    continue
                sin_permiso.append(f"{etiqueta}::{nodo.name}")

    assert not sin_permiso, (
        "Rutas de escritura sin permiso declarado:\n  "
        + "\n  ".join(sin_permiso)
        + "\n\nSi alguna es legítima, añádela a `exentas` con su motivo."
    )


def test_los_errores_de_dominio_tienen_codigo_estable() -> None:
    """Todo `raise` de un error de dominio lleva `error_code`.

    Sin él, el cliente solo tiene el texto en castellano para distinguir un
    error de otro, y cualquier cambio de redacción le rompe la integración.
    """
    from crmcore.errors import CrmError

    nombres_error = {c.__name__ for c in [CrmError, *CrmError.__subclasses__()]} | {
        sc.__name__ for c in CrmError.__subclasses__() for sc in c.__subclasses__()
    }

    sin_codigo: list[str] = []
    for fichero in [*_modulos(SERVICIOS_DIR), *_modulos(CORE_DIR)]:
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Raise) or not isinstance(nodo.exc, ast.Call):
                continue
            nombre = getattr(nodo.exc.func, "id", "") or getattr(nodo.exc.func, "attr", "")
            if nombre not in nombres_error:
                continue
            if not any(kw.arg == "error_code" for kw in nodo.exc.keywords):
                sin_codigo.append(f"{fichero.relative_to(RAIZ)}:{nodo.lineno} {nombre}")

    assert not sin_codigo, "Errores de dominio sin `error_code`:\n  " + "\n  ".join(sin_codigo)


# ── Cero hardcodeado ──────────────────────────────────────────────────────


def test_no_hay_urls_ni_credenciales_escritas_en_el_codigo() -> None:
    """Nada de endpoints ni credenciales a fuego: van a configuración.

    Una URL escrita en el código solo se cambia redesplegando, y cada
    instalación es distinta.
    """
    # La URL tiene que parecer una URL REAL —con dominio y extensión— para que
    # no salten los patrones de validación (`^https://.+`) ni los mensajes de
    # error que citan el esquema («debe empezar por http:// o https://»). La
    # primera versión de este gate los marcaba, y un gate con falsos positivos
    # se acaba desactivando, que es peor que no tenerlo.
    patrones = [
        (
            re.compile(
                r"https?://(?!localhost|127\.0\.0\.1|example\.|contecrm\.dev|schemas?\.|www\.w3)"
                r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}"
            ),
            "URL externa",
        ),
        (
            re.compile(r"(password|contrasena|secret)\s*=\s*[\"'][^\"']{8,}[\"']", re.I),
            "credencial",
        ),
    ]
    hallazgos: list[str] = []
    for fichero in [*_modulos(SERVICIOS_DIR), *_modulos(CORE_DIR)]:
        for n, linea in enumerate(fichero.read_text(encoding="utf-8").splitlines(), 1):
            desnuda = linea.strip()
            # Los comentarios y las cadenas de documentación explican, no
            # ejecutan: una URL en un ejemplo del docstring es documentación.
            if desnuda.startswith(("#", '"', "'", "*")):
                continue
            for patron, que in patrones:
                if patron.search(linea):
                    hallazgos.append(f"{fichero.relative_to(RAIZ)}:{n} {que}: {desnuda[:80]}")
    assert not hallazgos, "Valores a fuego en el código:\n  " + "\n  ".join(hallazgos)


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_cada_servicio_usa_la_factoria(servicio: str) -> None:
    """Ningún servicio monta su FastAPI a mano.

    Si lo hiciera, se saltaría el contexto de tenant, los límites, el formato de
    errores y las métricas — y el fallo no se vería hasta que dos clientes se
    vieran los datos.
    """
    main = SERVICIOS_DIR / servicio / "main.py"
    if not main.exists():
        pytest.skip(f"«{servicio}» no tiene punto de entrada propio")
    fuente = main.read_text(encoding="utf-8")
    assert "crear_servicio(" in fuente, f"«{servicio}» no usa crmcore.service.crear_servicio"
    assert "FastAPI(" not in fuente, f"«{servicio}» instancia FastAPI directamente"


def test_los_ajustes_siempre_filtran_por_ambito() -> None:
    """`ajustes_runtime` no lleva `tenant_id`, así que su aislamiento depende de
    que toda lectura fije ámbito Y sujeto del ámbito.

    Esta prueba es la contrapartida de esa excepción: sin ella, la excepción
    sería una promesa. Comprueba que no queda ninguna consulta a la tabla que
    filtre solo por clave — que es como se leería la configuración de otro
    tenant sin enterarse.
    """
    fuente = (CORE_DIR / "runtime" / "settings.py").read_text(encoding="utf-8")
    arbol = ast.parse(fuente)

    consultas_sospechosas: list[str] = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        texto = ast.unparse(nodo)
        if "AjusteRuntime" not in texto or ".where(" not in texto:
            continue
        # Toda consulta sobre la tabla tiene que acotar por ámbito y por sujeto.
        if "AjusteRuntime.ambito" not in texto or "AjusteRuntime.ambito_id" not in texto:
            consultas_sospechosas.append(texto[:160])

    assert not consultas_sospechosas, (
        "Consultas a `ajustes_runtime` sin acotar ámbito y sujeto:\n  "
        + "\n  ".join(consultas_sospechosas)
    )


def test_toda_tabla_con_tenant_tiene_indice_por_tenant() -> None:
    """Cada tabla con `tenant_id` tiene un índice que empieza por esa columna.

    RLS añade `tenant_id = <actual>` a **toda** consulta, así que sin un índice
    que empiece por ahí cada lectura es un recorrido completo filtrado después
    —y con volumen, eso es la diferencia entre una lista instantánea y una que
    tarda segundos.

    El índice de una sola columna que creaba antes el mixin se quitó por
    redundante: había 14 ya cubiertos por un compuesto, y cada índice de más se
    paga en cada escritura. Este gate es lo que sustituye a aquel automatismo.
    """
    import importlib

    for modulo in [
        "crmcore.audit.modelos",
        "crmcore.bus.modelos",
        "crmcore.http.idempotency",
        "crmcore.runtime.settings",
        *[f"services.{s}.modelos" for s in SERVICIOS],
    ]:
        try:
            importlib.import_module(modulo)
        except ModuleNotFoundError:
            continue

    from crmcore.db.base import Base

    sin_indice: list[str] = []
    for tabla in Base.metadata.tables.values():
        if "tenant_id" not in tabla.columns:
            continue
        por_indice = any(
            list(i.columns) and list(i.columns)[0].name == "tenant_id" for i in tabla.indexes
        )
        # La clave primaria también sirve cuando incluye el tenant: la búsqueda
        # exacta por clave ya usa ese índice.
        por_pk = "tenant_id" in [c.name for c in tabla.primary_key.columns]
        if not (por_indice or por_pk):
            sin_indice.append(tabla.name)

    assert not sin_indice, (
        "Tablas con `tenant_id` sin índice que empiece por esa columna:\n  "
        + "\n  ".join(sin_indice)
    )


def test_no_hay_nombres_de_indice_duplicados() -> None:
    """Dos índices con el mismo nombre rompen la creación del esquema entero.

    Pasó al añadir el servicio de cuentas: un índice compuesto declarado a mano
    se llamaba igual que el que `index=True` genera en la columna, y el esquema
    no se podía crear —ni en pruebas ni en un despliegue nuevo—.
    """
    import importlib
    from collections import Counter

    for modulo in [
        "crmcore.audit.modelos",
        "crmcore.bus.modelos",
        "crmcore.http.idempotency",
        "crmcore.runtime.settings",
        *[f"services.{s}.modelos" for s in SERVICIOS],
    ]:
        try:
            importlib.import_module(modulo)
        except ModuleNotFoundError:
            continue

    from crmcore.db.base import Base

    nombres = [i.name for tabla in Base.metadata.tables.values() for i in tabla.indexes]
    repetidos = sorted({n for n, c in Counter(nombres).items() if c > 1})
    assert not repetidos, f"Nombres de índice repetidos: {repetidos}"


def test_ningun_cliente_http_crudo_fuera_del_guard() -> None:
    """Toda salida HTTP del servidor pasa por el guard de SSRF.

    Un `httpx.AsyncClient(...)` construido a mano en un camino que busca una URL
    del tenant es el agujero de vuelta, y no se ve en una revisión: la línea es
    idéntica a la correcta salvo por el nombre de la función.

    La excepción es el gateway, que reenvía a **nuestros propios** servicios por
    nombres de red internos —justo los que el guard bloquea— y cuya lista de
    destinos sale de la configuración del despliegue, no del tenant.
    """
    exentos = {
        "gateway/api.py": "reenvía a los servicios internos del propio despliegue",
    }

    crudos: list[str] = []
    for fichero in [
        *sorted(SERVICIOS_DIR.rglob("*.py")),
        *sorted((RAIZ / "packages" / "crmcore" / "crmcore").rglob("*.py")),
    ]:
        if "__pycache__" in str(fichero) or fichero.parent.name == "red":
            continue
        etiqueta = f"{fichero.parent.name}/{fichero.name}"
        if etiqueta in exentos:
            continue
        texto = fichero.read_text(encoding="utf-8")
        if "httpx.AsyncClient(" in texto or "httpx.Client(" in texto:
            crudos.append(etiqueta)

    assert not crudos, (
        "Clientes HTTP sin guard de SSRF:\n  "
        + "\n  ".join(crudos)
        + "\n\nUsa `crmcore.red.cliente_seguro` o `cliente_seguro_async`. Si el "
        "destino es un servicio interno del despliegue, añádelo a `exentos` con "
        "su motivo."
    )


def test_las_fichas_de_datos_personales_pasan_por_la_proyeccion() -> None:
    """Un endpoint que devuelve un registro con campos sensibles los proyecta.

    El permiso por objeto dice si alguien puede leer cuentas; la proyección dice
    qué columnas ve. Sin ella, dar lectura del maestro de clientes es darlo todo,
    y este gate existe porque la llamada es de una línea y se olvida.

    Se comprueba sobre los endpoints que devuelven un modelo con columnas
    declaradas sensibles: no sobre todos, porque un listado de etiquetas o un
    conteo no tienen nada que proyectar y exigírselo enseñaría a añadir la
    llamada sin pensar, que es como se acaba enmascarando lo que no toca.
    """
    # Endpoints que devuelven la ficha completa de un objeto con datos
    # personales. Se nombran porque son pocos y porque la lista, leída, dice
    # exactamente dónde sale dato sensible por la API.
    exigidos = {
        "party/api.py": {"obtener_cuenta", "obtener_contacto"},
    }

    faltan: list[str] = []
    for fichero_rel, funciones in exigidos.items():
        fichero = SERVICIOS_DIR / fichero_rel
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if nodo.name not in funciones:
                continue
            if "proyectar_para" not in ast.unparse(nodo):
                faltan.append(f"{fichero_rel}::{nodo.name}")

    assert not faltan, (
        "Endpoints que devuelven datos personales sin proyectarlos:\n  "
        + "\n  ".join(faltan)
        + "\n\nUsa `proyectar_para(principal, db, objeto=..., modelo=...)`."
    )


def test_todo_listado_de_objeto_sensible_proyecta_su_ordenacion() -> None:
    """Ordenar por un campo que no se puede ver lo reconstruye entero.

    Basta pedir la lista ascendente y descendente y comparar; con un filtro de
    rango, por búsqueda binaria, en una docena de peticiones. Así que todo
    listado de un objeto con columnas sensibles tiene que pasar `objeto` y
    `principal` a `aplicar_orden_y_cursor`, que es donde se recorta la lista de
    columnas ordenables al rol.

    Los argumentos son opcionales en la firma para no romper a quien ya llamaba;
    este gate es lo que impide que esa compatibilidad se convierta en la puerta
    de atrás.
    """
    # Listados sobre objetos que NO son datos de un tenant, con su motivo.
    exentos = {
        # `Tenant` es metadato de la plataforma: no tiene `tenant_id` ni columnas
        # clasificadas, y su listado ya exige ser personal de plataforma. Pedirle
        # una proyección por rol de tenant no significaría nada.
        "tenancy/api.py",
    }

    faltan: list[str] = []
    for fichero in sorted(SERVICIOS_DIR.rglob("api*.py")):
        if "__pycache__" in str(fichero):
            continue
        if f"{fichero.parent.name}/{fichero.name}" in exentos:
            continue
        texto = fichero.read_text(encoding="utf-8")
        if "aplicar_orden_y_cursor" not in texto:
            continue
        arbol = ast.parse(texto, str(fichero))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            nombre = getattr(nodo.func, "id", "") or getattr(nodo.func, "attr", "")
            if nombre != "aplicar_orden_y_cursor":
                continue
            claves = {k.arg for k in nodo.keywords}
            if not {"objeto", "principal"} <= claves:
                faltan.append(f"{fichero.parent.name}/{fichero.name}:{nodo.lineno}")

    assert not faltan, (
        "Listados que ordenan sin aplicar la proyección:\n  "
        + "\n  ".join(faltan)
        + "\n\nPasa `objeto=` y `principal=` a `aplicar_orden_y_cursor`."
    )


def test_toda_accion_de_automatizacion_tiene_ejecutor() -> None:
    """Una acción declarada sin ejecutor es peor que no declararla.

    La regla se guarda, se valida, se simula y al ejecutarse falla — o, como
    pasó aquí durante meses, no hace nada en silencio. `enviar_correo` estuvo en
    la lista sin que hubiera con qué enviar.
    """
    from services.automation.ejecutores import construir
    from services.automation.motor import ACCIONES

    class _UowFalsa:
        tenant_id = None

        def emitir(self, *_a: object, **_k: object) -> None:
            pass

    faltan = ACCIONES - set(construir(_UowFalsa()))
    assert not faltan, (
        f"Acciones declaradas sin ejecutor: {sorted(faltan)}. "
        "O se implementa el ejecutor, o se quita la acción de la lista."
    )


# Objetos de negocio sobre los que una política ABAC puede decidir. Son los que
# tienen ficha propia y dueño: sobre una línea de oportunidad o una dirección se
# decide a través de su padre, no por separado.
MODELOS_CON_POLITICA = {
    "Cuenta": "cuenta",
    "Contacto": "contacto",
    "Actividad": "actividad",
    "Lead": "lead",
    "Oportunidad": "oportunidad",
}


def test_todo_cargador_de_registro_pasa_por_el_punto_de_decision() -> None:
    """Quien carga un registro por su identificador evalúa las políticas.

    Este gate es la mitad que le faltaba al ABAC. El motor estaba entero y no lo
    llamaba nadie: las políticas se podían escribir y no decidían nada. Lo que
    impide que vuelva a pasar no es acordarse en cada endpoint —eso es
    exactamente lo que se olvida— sino que el cargador compartido lo haga y que
    esta prueba compruebe que ninguno se salta.

    Se buscan las funciones que hacen `db.get(<Modelo>, …)` sobre un objeto con
    política y responden 404 si no está: esas son las que devuelven un registro
    concreto a alguien. Cada una tiene que llamar a `exigir(...)`.

    Un cargador nuevo aparece en esta lista solo, sin que nadie actualice nada.
    """
    faltan: list[str] = []
    for fichero in sorted(SERVICIOS_DIR.glob("*/*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fuente = ast.unparse(nodo)
            carga = [
                modelo
                for modelo in MODELOS_CON_POLITICA
                if f"db.get({modelo}," in fuente or f"uow.db.get({modelo}," in fuente
            ]
            if not carga or "NoEncontrado(" not in fuente:
                continue
            if "exigir(" in fuente:
                continue
            rel = fichero.relative_to(SERVICIOS_DIR)
            faltan.append(f"{rel}::{nodo.name} (carga {', '.join(sorted(carga))})")

    assert not faltan, (
        "Cargadores de registro que no evalúan las políticas de acceso:\n  "
        + "\n  ".join(faltan)
        + "\n\nLlama a `crmcore.authz.decision.exigir(db, objeto=..., accion=..., "
        "registro=...)` antes de devolverlo, o delega en el cargador compartido "
        "que ya lo hace."
    )
