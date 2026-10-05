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
    leidos = 0

    for servicio in SERVICIOS:
        for fichero in _modulos(SERVICIOS_DIR / servicio):
            leidos += 1
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

    # Y que de verdad se haya leído el árbol: si `_modulos` dejara de encontrar
    # ficheros, esto pasaría en verde sin haber abierto ninguno.
    assert leidos > 200, f"Solo se han leído {leidos} módulos de servicio; son cientos"
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
    "plantillas_flujo": (
        "catálogo de procesos de ejemplo DE LA INSTALACIÓN, como `perfiles_industria`. "
        "Se CLONAN a cada tenant y el clon sí es suyo: si la plantilla llevara "
        "tenant_id, cada uno tendría que escribir la suya y la biblioteca no "
        "serviría para nada"
    ),
    "perfiles_industria": (
        "catálogo de preconfiguraciones DE LA INSTALACIÓN, como `modulos_publicados` "
        "y por el mismo motivo: un perfil de industria lo escribe quien opera la "
        "plataforma y lo aplican muchos tenants. Lo que sí es por tenant es "
        "`aplicaciones_perfil`, que sí lleva tenant_id y guarda qué se le aplicó a "
        "cada uno y qué se saltó"
    ),
    "modulos_publicados": (
        "catálogo de módulos verticales DE LA INSTALACIÓN, no de cada tenant. "
        "Quién puede publicar un módulo es una decisión de quien opera la "
        "plataforma: dejar que cada tenant publique el suyo convertiría el "
        "catálogo en una vía para ejecutar configuración ajena en casa de otro. "
        "Lo que sí es por tenant es `modulos_instalados`, que sí lleva tenant_id"
    ),
    "manifiestos_conector": (
        "catálogo de conectores DE LA INSTALACIÓN, no de cada tenant, por el "
        "mismo motivo que `modulos_publicados`: publicar un manifiesto es "
        "declarar a qué sistemas externos se puede llamar y con qué mapeo, y "
        "dejar que cada tenant publique el suyo lo convertiría en una vía para "
        "ejecutar configuración ajena en casa de otro. Lo que sí es por tenant "
        "es `instalaciones_conector`, que lleva tenant_id y es lo único que "
        "decide qué conector usa cada cliente"
    ),
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
        # Recuperar el acceso: quien las llama **no ha entrado**, que es todo el
        # problema. Lo que autoriza es el enlace de un solo uso, hasheado y con
        # caducidad, y lo que impide abusar de ellas es que la respuesta sea la
        # misma exista o no el correo. Probado en `test_restablecer_contrasena.py`.
        "pedir_restablecer": "la pide quien no puede entrar; autoriza el enlace, no un permiso",
        "confirmar_restablecer": "ídem: la credencial es el token del enlace",
        # Entrar con passkey es entrar: exigir permiso sería tan circular como
        # exigirlo en `login`. Lo que autoriza es la firma del dispositivo.
        "empezar_passkey": "es parte de la entrada; exigir permiso sería circular",
        "entrar_con_passkey": "ídem: lo que autoriza es la firma de la llave",
        # Y registrar o quitar una llave propia solo exige tener sesión: son
        # `AutenticadoDep` y la comprobación de que la llave es suya va dentro.
        "empezar_registro_passkey": "el usuario registra su propia llave",
        "confirmar_registro_passkey": "ídem",
        "quitar_passkey": "quita una llave propia; que sea suya se comprueba dentro",
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
        # Las dos puertas del cuadro incrustado. Exigir sesión del CRM era
        # justamente el fallo: obligaba a repartir credenciales de empleado
        # entre los usuarios de la aplicación que incrusta el cuadro.
        "abrir_embebido": "la autoriza el secreto del enlace; exigir permiso sería circular",
        # ── Lo que apareció al dejar de mirar solo `api.py` ────────────────
        # El gate recorría `services/*/api.py` y los routers del núcleo, y los
        # servicios tienen DIECINUEVE ficheros de rutas más (`api_sso.py`,
        # `api_cuadros.py`, `api_factores.py`…). Medido el 05-10-2026: 26 rutas
        # de escritura fuera del alcance del gate. Ninguna resultó ser un
        # agujero —están abajo con su motivo, y se comprobó una a una— pero eso
        # no se sabía, y es lo que hace falta que no vuelva a pasar: un gate que
        # mira la cuarta parte de los ficheros da la misma luz verde que uno que
        # los mira todos.
        #
        # Entrar es entrar: estas rutas son las que reparten identidad, y
        # exigirles permiso sería tan circular como exigírselo a `login`.
        "iniciar": "arranca el SSO; a ella se llega sin credencial, es donde se consigue",
        "callback_oidc": "la vuelta del proveedor de identidad; lo que autoriza es el código",
        "acs_saml": "la vuelta del proveedor SAML; lo que autoriza es la aserción firmada",
        "sesion_portal": "el cliente canjea su enlace por su sesión; no tiene otra cosa",
        # Lo que autoriza no es un permiso sino una credencial que viaja en el
        # cuerpo, y se comprueba dentro.
        "entrada": "público por diseño; lo autoriza el secreto del canal, como «recibir_lead»",
        "entrar": "el token del enlace de portal ES la autorización; se comprueba dentro",
        "canjear": "el token del partner ES la autorización; se comprueba dentro",
        "datos_embebido": "la autoriza el ticket que emite «abrir_embebido»; no lleva permisos",
        # Sobre uno mismo. La identidad de quien llama ES la autorización: pedir
        # un permiso para que alguien gestione su propio segundo factor o cierre
        # su propia sesión deja a quien no lo tenga sin poder protegerse.
        "pedir_codigo": "sobre el propio segundo factor; la identidad es la autorización",
        "comprobar_codigo": "sobre el propio segundo factor; la identidad es la autorización",
        "revocar_dispositivo": "uno revoca sus dispositivos de confianza, no los de otro",
        "revocar_todos": "uno revoca sus dispositivos de confianza, no los de otro",
        "salir": "uno cierra su sesión; exigir permiso dejaría a alguien sin poder salir",
        "cierre_unico": "uno cierra su sesión también en el proveedor de identidad",
        "conceder": "lo concede el dueño del buzón y solo él; un permiso no lo sustituye",
        "revocar": "uno revoca el acceso a sus propios recursos",
        "valorar": "uno vota un artículo como uno mismo",
        "pedir_enlace": "la pide quien atiende, y lo que da es un enlace, no acceso",
        # No escriben, aunque el método sea POST.
        "previsualizar": "no escribe: pinta una plantilla con los datos que trae quien pregunta",
        "resolver_perfil": "no escribe: resuelve un perfil declarado con los ajustes del cuerpo",
    }

    # Los routers COMPARTIDOS del núcleo también escriben, y montarlos desde
    # varios servicios no los exime: al contrario, un agujero ahí sale
    # multiplicado por todos los servicios que los monten. Mirar solo
    # `services/*/api.py` era un punto ciego, y se descubrió al montar los de
    # adjuntos y comentarios: seis rutas de escritura sin permiso que el gate
    # daba por buenas.
    # TODOS los ficheros de rutas de cada servicio, no solo `api.py`: mirar uno
    # de los veinte y dar el verde es exactamente lo que este gate existe para
    # impedir.
    ficheros = [f for s in SERVICIOS for f in sorted((SERVICIOS_DIR / s).glob("api*.py"))]
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
                # `exige_firma_interna` también es una guarda DECLARADA en la
                # ruta, y más cerrada que cualquier permiso: no la pasa un
                # usuario, la pasa otro servicio de la casa con el secreto
                # compartido. Se reconoce aquí en vez de ir apuntando cada ruta
                # interna en `exentas`, porque una lista de nombres se queda
                # vieja y esto no: la guarda está en el código o no está.
                if "exige_firma_interna" in texto:
                    continue
                # `PlataformaDep` en los argumentos también es una comprobación
                # declarada, y más restrictiva que cualquier permiso. `PortalDep`
                # y `TicketDep` son del mismo tipo: una identidad declarada que
                # NO es la de un empleado y que no puede llegar a estas rutas sin
                # haber canjeado antes su credencial. Se reconocen por estructura
                # y no por nombre de función, por lo mismo que `exige_firma_interna`.
                argumentos = ast.unparse(nodo.args)
                if any(d in argumentos for d in ("PlataformaDep", "PortalDep", "TicketDep")):
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


# ── Mapa de datos personales (CRM-07.03.01.04) ────────────────────────────

# Columnas que **parecen** dato personal por el nombre y no lo son, con el
# motivo. Va aquí y no en un comentario del modelo porque la excepción tiene que
# costar algo: escribir una línea con su razón es barato, y es exactamente lo que
# hace que nadie añada una a la ligera.
#
# El listado inverso —lo que sí es personal— no se escribe en ningún sitio: sale
# del modelo. Una lista de campos personales mantenida a mano se queda corta al
# primer campo nuevo, y ese campo no existiría para el RAT hasta que alguien se
# acordara. Nadie se acuerda.
COLUMNAS_QUE_NO_SON_PERSONALES = {
    "adaptadores_canonicos.direccion": "sentido del mapeo (entrante/saliente), no una dirección postal",
    "adaptadores_canonicos.direccion_por_campo": "sentido del mapeo campo a campo",
    "mensajes.direccion": "sentido del mensaje (entrante/saliente)",
    "interacciones_entrantes.direccion": "sentido de la interacción",
    "canales_servicio.direccion_propia": "el buzón de la EMPRESA, no de una persona",
    "dominios_envio.ip_dedicada": "IP de infraestructura de envío, no de un visitante",
    "proveedores_identidad.dominio_email": "un dominio corporativo, no la dirección de nadie",
    "exportaciones_tenant.manifiesto": "el nombre contiene «nif» por casualidad",
    "marca_tenants.pie_correo": (
        "es el pie que el CLIENTE pone en sus correos —su razón social, su "
        "dirección fiscal—, no datos de una persona: es justo lo contrario, la "
        "identificación de quien manda"
    ),
    "modulos_publicados.manifiesto": "el nombre contiene «nif» por casualidad",
    "modulos_instalados.manifiesto": "el nombre contiene «nif» por casualidad",
    "instalaciones_conector.manifiesto_id": "el nombre contiene «nif» por casualidad",
}

# Lo que dispara la comprobación. No pretende encontrar todo el dato personal
# —un campo llamado `notas` puede llevar media vida de alguien— sino cerrar el
# camino por el que se cuela sin querer: los campos de contacto e identificación,
# que son los que se añaden a diario.
NOMBRES_DE_DATO_PERSONAL = re.compile(
    r"(correo|email|telefono|movil|apellid|nif|cif|iban|direccion|codigo_postal"
    r"|fecha_nacimiento|(^|_)ip($|_))"
)


def test_toda_columna_que_parece_personal_declara_su_sensibilidad() -> None:
    """El mapa de datos personales sale del modelo, así que el modelo tiene que
    decir la verdad.

    Sin este gate, el RAT es correcto el día que se escribe y mentira un mes
    después: alguien añade un `email_facturacion`, nadie lo marca, y el registro
    que se le enseña a un auditor dice que ese dato no existe. La diferencia
    entre un RAT útil y una hoja de cálculo vieja es exactamente esta
    comprobación.
    """
    from crmcore.db.base import Base

    sin_declarar: list[str] = []
    for mapper in Base.registry.mappers:
        tabla = getattr(mapper.class_, "__table__", None)
        if tabla is None:
            continue
        for columna in tabla.columns:
            if not NOMBRES_DE_DATO_PERSONAL.search(columna.name):
                continue
            if (columna.info or {}).get("sensibilidad"):
                continue
            clave = f"{tabla.name}.{columna.name}"
            if clave in COLUMNAS_QUE_NO_SON_PERSONALES:
                continue
            sin_declarar.append(clave)

    assert not sin_declarar, (
        "Columnas que parecen dato personal y no declaran su sensibilidad:\n  "
        + "\n  ".join(sorted(sin_declarar))
        + '\n\nAñade `info={"sensibilidad": "personal"}` —o `"especial"` si es '
        "del artículo 9— al `mapped_column`, o justifícala en "
        "`COLUMNAS_QUE_NO_SON_PERSONALES` diciendo por qué no lo es."
    )


def test_las_justificaciones_de_no_personal_siguen_existiendo() -> None:
    """Una excepción sobre una columna que ya no existe es una excepción que
    nadie ha revisado, y la siguiente que se añada se colará detrás de ella."""
    from crmcore.db.base import Base

    reales = {
        f"{t.name}.{c.name}"
        for m in Base.registry.mappers
        if (t := getattr(m.class_, "__table__", None)) is not None
        for c in t.columns
    }
    sobran = sorted(set(COLUMNAS_QUE_NO_SON_PERSONALES) - reales)
    assert not sobran, (
        "Justificaciones de «no es dato personal» sobre columnas que ya no "
        "existen:\n  " + "\n  ".join(sobran) + "\n\nQuítalas."
    )


def test_todo_objeto_con_datos_personales_declara_su_tratamiento() -> None:
    """Un objeto con datos personales y sin actividad declarada es un hueco en el
    RAT, y un RAT con huecos no lo mira nadie dos veces.

    Marcar la sensibilidad de un campo y no decir para qué se trata deja el
    registro a medias: el auditor ve que el dato existe y no ve por qué. Las dos
    mitades van juntas o no sirven.
    """
    import importlib
    import pathlib

    from crmcore.cumplimiento import registro_de_tratamiento
    from crmcore.db.base import Base

    # Se cargan y se recargan las declaraciones aquí mismo. Depender de que otro
    # fichero las haya dejado puestas convierte este gate en algo que pasa o
    # falla según el orden de la suite, y un gate así acaba desactivado.
    raiz = pathlib.Path(__file__).resolve().parents[2] / "services"
    for servicio in sorted(d.name for d in raiz.iterdir() if d.is_dir()):
        if (raiz / servicio / "modelos.py").exists():
            importlib.import_module(f"services.{servicio}.modelos")
        if (raiz / servicio / "tratamientos.py").exists():
            importlib.reload(importlib.import_module(f"services.{servicio}.tratamientos"))

    modelos = {
        t.name: m.class_
        for m in Base.registry.mappers
        if (t := getattr(m.class_, "__table__", None)) is not None
    }
    rat = registro_de_tratamiento(modelos)

    assert not rat["objetos_sin_tratamiento_declarado"], (
        "Objetos con datos personales y sin actividad de tratamiento declarada:\n  "
        + "\n  ".join(rat["objetos_sin_tratamiento_declarado"])
        + "\n\nDeclárala en el `tratamientos.py` del servicio: finalidad, base "
        "legal y plazo. Son decisiones, no datos técnicos, y por eso no se "
        "pueden deducir del modelo."
    )
    assert not rat["tratamientos_sobre_objetos_sin_datos_personales"], (
        "Tratamientos declarados sobre objetos que ya no tienen datos "
        "personales:\n  "
        + "\n  ".join(rat["tratamientos_sobre_objetos_sin_datos_personales"])
        + "\n\nSuele significar que el objeto cambió y el RAT no."
    )
