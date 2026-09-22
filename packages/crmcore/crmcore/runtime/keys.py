"""Catálogo de ajustes editables en caliente (CRM-00.01.04.01).

Un ajuste de `Settings` se lee del entorno y solo cambia redesplegando. Los que
están declarados aquí, además, se pueden cambiar desde la consola de
administración y tienen efecto **sin reiniciar**, con la jerarquía:

    global → tier → tenant → unidad de negocio → usuario

Cada nivel sobrescribe al anterior; lo que ningún nivel fije, se resuelve al
valor de `.env`. Esa cadena es lo que permite que un despliegue tenga un tope
por defecto, un plan lo suba para los clientes grandes, un cliente concreto lo
ajuste y un usuario tenga su preferencia — sin una sola rama en el código.

**Qué entra aquí y qué no.** Entra lo que una instalación quiera afinar en
marcha: topes, plazos, umbrales, interruptores de funcionalidad. No entra nada
de arranque (puerto, URL de la base, tamaño del pool) porque cambiarlo en
caliente no haría nada y daría la falsa impresión de que sí: el pool se crea una
vez al arrancar, y un ajuste que se guarda pero no se aplica es peor que uno que
no se puede tocar.

Cada clave declara tipo y rango, y el gate `docs-coverage` exige que toda clave
tenga consumidor real en el código y una línea en el manual. Un ajuste que nadie
lee es ruido en la consola; uno sin documentar es una palanca sin etiqueta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Ambito = Literal["global", "tier", "tenant", "bu", "usuario"]


@dataclass(frozen=True, slots=True)
class ClaveAjuste:
    """Declaración de un ajuste editable."""

    clave: str
    tipo: Literal["bool", "int", "float", "str", "json"]
    descripcion: str
    # Ámbito más bajo en el que tiene sentido fijarlo. Un tope de cuota por
    # usuario no significa nada; una preferencia de idioma sí.
    minimo_ambito: Ambito = "tenant"
    minimo: float | None = None
    maximo: float | None = None
    # Valores admitidos cuando es una enumeración.
    opciones: tuple[str, ...] = ()
    # Campo de `Settings` del que sale el valor por defecto. Es lo que ata el
    # ajuste en caliente a su default de entorno: sin esto, habría dos fuentes
    # de verdad para el mismo número.
    campo_settings: str = ""
    # `True` cuando cambiarlo tiene consecuencias de seguridad o de coste. La
    # consola lo pide con confirmación y la auditoría lo marca.
    sensible: bool = False


def _c(*args: Any, **kwargs: Any) -> ClaveAjuste:
    return ClaveAjuste(*args, **kwargs)


# ── Catálogo ──────────────────────────────────────────────────────────────
CLAVES: dict[str, ClaveAjuste] = {
    c.clave: c
    for c in (
        # SSO (CRM-00.05.01.01, .02)
        _c(
            "oidc_cache_ttl_s",
            "int",
            "Segundos que se cachean el descubrimiento y las claves del proveedor",
            minimo=10,
            maximo=86_400,
            campo_settings="oidc_cache_ttl_s",
        ),
        _c(
            "sso_estado_ttl_s",
            "int",
            "Segundos que vive un inicio de sesión a medias",
            minimo=60,
            maximo=3_600,
            campo_settings="sso_estado_ttl_s",
            sensible=True,
        ),
        # Máquinas de estado (CRM-00.04.01.07)
        _c(
            "transiciones_prohibidas",
            "json",
            "Transiciones que este tenant quita de las que el producto admite",
            campo_settings="transiciones_prohibidas",
            sensible=True,
        ),
        # Búsqueda (CRM-00.01.01.09)
        _c(
            "busqueda_idioma",
            "str",
            "Idioma con el que se derivan las palabras al buscar",
            campo_settings="busqueda_idioma",
        ),
        _c(
            "busqueda_max_resultados",
            "int",
            "Resultados devueltos por consulta",
            minimo=1,
            maximo=200,
            campo_settings="busqueda_max_resultados",
        ),
        # Salidas de red (CRM-00.01.01.08, webhooks, conector)
        _c(
            "url_guard_hosts_permitidos",
            "str",
            "Hosts internos admitidos para salidas del servidor, separados por comas",
            campo_settings="url_guard_hosts_permitidos",
            minimo_ambito="global",
            sensible=True,
        ),
        # Colaboración (CRM-06.02.01.01)
        _c(
            "comentario_max_caracteres",
            "int",
            "Longitud máxima de un comentario",
            minimo=100,
            maximo=1_000_000,
            campo_settings="comentario_max_caracteres",
        ),
        _c(
            "comentario_max_menciones",
            "int",
            "Menciones permitidas en un solo comentario",
            minimo=1,
            maximo=500,
            campo_settings="comentario_max_menciones",
        ),
        # Adjuntos y almacenamiento (CRM-06.01.01.05)
        _c(
            "adjunto_max_mb",
            "int",
            "Tamaño máximo por fichero adjunto, en MB",
            minimo=1,
            maximo=5_000,
            campo_settings="adjunto_max_mb",
        ),
        _c(
            "adjunto_extensiones",
            "json",
            "Extensiones admitidas (lista blanca)",
            campo_settings="adjunto_extensiones",
            sensible=True,
        ),
        _c(
            "adjunto_deduplicar",
            "bool",
            "Guardar una sola copia de dos ficheros idénticos",
            campo_settings="adjunto_deduplicar",
        ),
        _c(
            "adjunto_max_versiones",
            "int",
            "Versiones que se conservan de un documento (0 = todas)",
            minimo=0,
            maximo=1_000,
            campo_settings="adjunto_max_versiones",
        ),
        _c(
            "adjunto_enlace_ttl_s",
            "int",
            "Segundos que vive un enlace de descarga firmado",
            minimo=30,
            maximo=86_400,
            campo_settings="adjunto_enlace_ttl_s",
            sensible=True,
        ),
        _c(
            "adjunto_exigir_analisis",
            "bool",
            "No entregar un adjunto que no haya pasado el antivirus",
            campo_settings="adjunto_exigir_analisis",
            sensible=True,
        ),
        _c(
            "adjunto_analizador_url",
            "str",
            "URL del analizador antivirus (vacío = sin análisis)",
            campo_settings="adjunto_analizador_url",
            sensible=True,
        ),
        # Límites y cuotas
        _c(
            "rate_limit_por_tenant",
            "int",
            "Peticiones por ventana y tenant",
            minimo=0,
            maximo=10_000_000,
            campo_settings="rate_limit_por_tenant",
            sensible=True,
        ),
        _c(
            "rate_limit_por_usuario",
            "int",
            "Peticiones por ventana y usuario",
            minimo=0,
            maximo=1_000_000,
            campo_settings="rate_limit_por_usuario",
        ),
        _c(
            "quota_api_calls_por_minuto",
            "int",
            "Llamadas a la API por minuto",
            minimo=0,
            campo_settings="quota_api_calls_por_minuto",
            sensible=True,
        ),
        _c(
            "quota_registros",
            "int",
            "Máximo de registros del tenant (0 = sin límite)",
            minimo=0,
            campo_settings="quota_registros",
            sensible=True,
        ),
        _c(
            "quota_almacenamiento_mb",
            "int",
            "Almacenamiento máximo en MB (0 = sin límite)",
            minimo=0,
            campo_settings="quota_almacenamiento_mb",
            sensible=True,
        ),
        _c(
            "quota_correos_por_dia",
            "int",
            "Correos salientes por día (0 = sin límite)",
            minimo=0,
            campo_settings="quota_correos_por_dia",
        ),
        _c(
            "quota_workflows_concurrentes",
            "int",
            "Procesos simultáneos por tenant",
            minimo=0,
            campo_settings="quota_workflows_concurrentes",
        ),
        _c(
            "quota_tokens_ia_por_dia",
            "int",
            "Tokens de IA por día (0 = sin límite)",
            minimo=0,
            campo_settings="quota_tokens_ia_por_dia",
            sensible=True,
        ),
        _c(
            "quota_aviso_pct",
            "int",
            "Porcentaje de consumo que dispara el aviso",
            minimo=1,
            maximo=100,
            campo_settings="quota_aviso_pct",
        ),
        # Paginación y operaciones masivas
        _c(
            "page_max_size",
            "int",
            "Tamaño máximo de página",
            minimo=1,
            maximo=10_000,
            campo_settings="page_max_size",
        ),
        _c(
            "bulk_max_items",
            "int",
            "Elementos máximos en una operación masiva",
            minimo=1,
            maximo=100_000,
            campo_settings="bulk_max_items",
        ),
        _c(
            "trabajo_max_items",
            "int",
            "Elementos máximos en una operación masiva diferida",
            minimo=1,
            maximo=5_000_000,
            campo_settings="trabajo_max_items",
        ),
        _c(
            "trabajo_tanda",
            "int",
            "Elementos que procesa un trabajo entre commit y commit",
            minimo=1,
            maximo=10_000,
            campo_settings="trabajo_tanda",
        ),
        _c(
            "trabajo_retencion_h",
            "int",
            "Horas que se conserva un trabajo terminado antes de borrarlo",
            minimo=1,
            maximo=8_760,
            campo_settings="trabajo_retencion_h",
        ),
        _c(
            "campo_velocidad_media_kmh",
            "int",
            "Velocidad media para estimar el viaje entre visitas de campo",
            minimo=5,
            maximo=130,
            campo_settings="campo_velocidad_media_kmh",
        ),
        _c(
            "garantia_preaviso_dias",
            "int",
            "Antelación con la que se avisa de una garantía de activo que vence",
            minimo=1,
            maximo=730,
            campo_settings="garantia_preaviso_dias",
        ),
        _c(
            "caso_reapertura_dias",
            "int",
            "Días durante los que un caso cerrado se puede reabrir (0 = sin límite)",
            minimo=0,
            maximo=3650,
            campo_settings="caso_reapertura_dias",
        ),
        # Identidad
        _c(
            "mfa_obligatoria",
            "bool",
            "Exigir MFA a todos los usuarios del tenant",
            campo_settings="mfa_obligatoria",
            sensible=True,
        ),
        # Segundo factor y gobierno del SSO (CRM-00.05.01.13 .. .25). Todos
        # editables en caliente: el día que hay que apagar el SMS porque el
        # proveedor está caído, o forzar el SSO tras un incidente, esperar a un
        # despliegue es esperar de más.
        _c(
            "otp_sms_enabled",
            "bool",
            "Segundo factor por SMS. Es el factor más débil: se intercepta con un cambio de SIM",
            campo_settings="otp_sms_enabled",
            sensible=True,
        ),
        _c(
            "otp_email_enabled",
            "bool",
            "Segundo factor por correo",
            campo_settings="otp_email_enabled",
            sensible=True,
        ),
        _c(
            "otp_digitos",
            "int",
            "Dígitos del código de un solo uso",
            minimo=4,
            maximo=10,
            campo_settings="otp_digitos",
        ),
        _c(
            "otp_validez_segundos",
            "int",
            "Cuánto vive un código de un solo uso",
            minimo=30,
            maximo=1800,
            campo_settings="otp_validez_segundos",
        ),
        _c(
            "otp_max_intentos",
            "int",
            "Intentos antes de invalidar el código",
            minimo=1,
            maximo=20,
            campo_settings="otp_max_intentos",
        ),
        _c(
            "otp_reenvio_segundos",
            "int",
            "Espera mínima entre reenvíos de código",
            minimo=10,
            maximo=900,
            campo_settings="otp_reenvio_segundos",
        ),
        _c(
            "stepup_validez_minutos",
            "int",
            "Cuánto vale el segundo factor antes de volver a pedirlo para una operación sensible",
            minimo=1,
            maximo=480,
            campo_settings="stepup_validez_minutos",
            sensible=True,
        ),
        _c(
            "dispositivo_confianza_dias",
            "int",
            "Días que se recuerda un equipo antes de volver a pedir el factor (0 = desactivado)",
            minimo=0,
            maximo=365,
            campo_settings="dispositivo_confianza_dias",
            sensible=True,
        ),
        _c(
            "sso_forzado",
            "bool",
            "Obligar a entrar por el proveedor de identidad, sin contraseña local",
            campo_settings="sso_forzado",
            sensible=True,
        ),
        _c(
            "delegar_mfa_al_idp",
            "bool",
            "Aceptar el segundo factor que ya ha exigido el IdP, si declara cuáles valen",
            campo_settings="delegar_mfa_al_idp",
            sensible=True,
        ),
        _c(
            "idp_aviso_caducidad_dias",
            "int",
            "Días de aviso antes de que caduque un certificado de firma del IdP",
            minimo=1,
            maximo=365,
            campo_settings="idp_aviso_caducidad_dias",
        ),
        _c(
            "sesiones_max_por_usuario",
            "int",
            "Sesiones simultáneas (0 = sin límite)",
            minimo=0,
            maximo=1000,
            campo_settings="sesiones_max_por_usuario",
        ),
        _c(
            "sesion_inactividad_minutos",
            "int",
            "Cierre de sesión por inactividad",
            minimo=5,
            maximo=10_080,
            campo_settings="sesion_inactividad_minutos",
        ),
        _c(
            "login_max_intentos",
            "int",
            "Intentos fallidos antes de bloquear",
            minimo=1,
            maximo=100,
            campo_settings="login_max_intentos",
            sensible=True,
        ),
        _c(
            "suplantacion_enabled",
            "bool",
            "Permitir que soporte suplante a un usuario",
            campo_settings="suplantacion_enabled",
            sensible=True,
        ),
        _c(
            "suplantacion_max_minutos",
            "int",
            "Duración máxima de una suplantación",
            minimo=5,
            maximo=1440,
            campo_settings="suplantacion_max_minutos",
        ),
        # Eventos y webhooks
        _c(
            "webhooks_enabled",
            "bool",
            "Entregar eventos a los webhooks del tenant",
            campo_settings="webhooks_enabled",
        ),
        _c(
            "webhook_max_intentos",
            "int",
            "Reintentos antes de la cola de fallidos",
            minimo=1,
            maximo=50,
            campo_settings="webhook_max_intentos",
        ),
        _c(
            "webhook_timeout_s",
            "float",
            "Espera máxima de un webhook",
            minimo=0.5,
            maximo=120.0,
            campo_settings="webhook_timeout_s",
        ),
        # Procesos y automatizaciones
        _c(
            "proceso_max_pasos",
            "int",
            "Pasos máximos de una instancia de proceso",
            minimo=1,
            maximo=1_000_000,
            campo_settings="proceso_max_pasos",
        ),
        _c(
            "proceso_max_duracion_h",
            "int",
            "Duración máxima de un proceso, en horas",
            minimo=1,
            maximo=8760,
            campo_settings="proceso_max_duracion_h",
        ),
        _c(
            "automatizacion_max_cascada",
            "int",
            "Automatizaciones encadenadas antes de cortar la cascada",
            minimo=1,
            maximo=100,
            campo_settings="automatizacion_max_cascada",
            sensible=True,
        ),
        # Papelera (CRM-00.06.02.04)
        _c(
            "papelera_dias_retencion",
            "int",
            "Días que un registro borrado se conserva antes de poder purgarse",
            minimo=1,
            maximo=3650,
            campo_settings="papelera_dias_retencion",
            sensible=True,
        ),
        # Protección del dato
        _c(
            "politica_sensibilidad",
            "json",
            "Qué nivel de sensibilidad ve cada rol, en claro o enmascarado",
            campo_settings="politica_sensibilidad",
            sensible=True,
        ),
        _c(
            "masking_enabled",
            "bool",
            "Enmascarar datos sensibles según el rol",
            campo_settings="masking_enabled",
            sensible=True,
        ),
        _c(
            "dlp_export_filas_aviso",
            "int",
            "Filas a partir de las que se audita la exportación",
            minimo=1,
            campo_settings="dlp_export_filas_aviso",
        ),
        _c(
            "dlp_export_filas_bloqueo",
            "int",
            "Filas a partir de las que se bloquea la exportación (0 = no bloquear)",
            minimo=0,
            campo_settings="dlp_export_filas_bloqueo",
            sensible=True,
        ),
        _c(
            "audit_retencion_dias",
            "int",
            "Días que se conserva la traza de auditoría",
            minimo=30,
            maximo=36_500,
            campo_settings="audit_retencion_dias",
            sensible=True,
        ),
        # Canales de notificación (CRM-06.02.01.02). Son JSON porque describen
        # un canal entero —URL, método, cabeceras, plantilla— y partirlo en
        # cinco claves obligaría a mantener cinco jerarquías coherentes entre sí.
        _c(
            "canal_correo",
            "json",
            "Servidor y remitente de correo de este tenant (vacío = el del despliegue)",
            campo_settings="",
            sensible=True,
        ),
        _c(
            "canal_sms",
            "json",
            "Endpoint HTTP del proveedor de SMS: url, metodo, cabeceras y cuerpo",
            campo_settings="",
            sensible=True,
        ),
        _c(
            "canal_push",
            "json",
            "Endpoint HTTP del proveedor de push: url, metodo, cabeceras y cuerpo",
            campo_settings="",
            sensible=True,
        ),
        # Verificadores externos (CRM-01.01.01.05, .06 y CRM-01.01.04.10). Uno
        # por tipo de dato, y opcionalmente uno por país para lo que cambia de
        # país a país —el registro fiscal— sin repetir lo que no cambia.
        #
        # No hay código de ningún proveedor: aquí se declara a dónde llamar y de
        # qué parte de la respuesta sale el veredicto.
        _c(
            "verificador_fiscal",
            "json",
            "Registro oficial de identificadores fiscales",
            sensible=True,
        ),
        _c("verificador_fiscal_es", "json", "Registro fiscal específico de España", sensible=True),
        _c("verificador_direccion", "json", "Geocodificador de direcciones", sensible=True),
        _c("verificador_correo", "json", "Validador de direcciones de correo", sensible=True),
        _c("verificador_telefono", "json", "Validador de números de teléfono", sensible=True),
        # Localización, con preferencia por usuario
        _c(
            "idioma",
            "str",
            "Idioma por defecto de la interfaz y los correos",
            minimo_ambito="usuario",
            opciones=("es", "en", "ca", "fr", "pt", "de"),
        ),
        _c(
            "zona_horaria",
            "str",
            "Zona horaria para fechas y calendarios laborales",
            minimo_ambito="usuario",
        ),
        _c(
            "moneda_funcional",
            "str",
            "Moneda en la que se consolidan los importes",
            minimo_ambito="tenant",
        ),
        _c(
            "formato_fecha",
            "str",
            "Formato de fecha en interfaces y documentos",
            minimo_ambito="usuario",
            opciones=("dd/mm/aaaa", "mm/dd/aaaa", "aaaa-mm-dd"),
        ),
        _c(
            "primer_dia_semana",
            "int",
            "Primer día de la semana (0 = lunes)",
            minimo=0,
            maximo=6,
            minimo_ambito="usuario",
        ),
        # Registro de tratamiento (CRM-07.03.01.04). Una sola clave JSON y no
        # cuatro por cada objeto: con veinticinco objetos serían cien palancas en
        # la consola, y una consola con cien palancas es una consola que nadie
        # toca. Dentro va {objeto: {finalidad, base_legal, plazo, responsable}},
        # y lo que no se ponga se queda con lo que declara el producto.
        _c(
            "rat_ajustes",
            "json",
            "Finalidad, base legal, plazo y responsable propios de este tenant, por objeto",
        ),
    )
}


def registrar_claves(nuevas: list[ClaveAjuste]) -> None:
    """Añade ajustes propios de un servicio al catálogo en caliente.

    Los ajustes transversales viven en este módulo; los de un dominio concreto
    —los umbrales de deduplicación, por ejemplo— los declara su servicio y los
    registra al importarse. Sin esta vía, o se mete todo aquí (y el núcleo acaba
    sabiendo de cuentas y oportunidades) o el servicio se inventa su propio
    mecanismo de configuración, que es peor: dos sitios donde mirar cuando algo
    no se aplica.

    Rechaza redefinir una clave existente con otro tipo: dos servicios que usen
    el mismo nombre para cosas distintas producirían un valor que significa una
    cosa al escribirlo y otra al leerlo.
    """
    for clave in nuevas:
        previa = CLAVES.get(clave.clave)
        if previa is not None and previa.tipo != clave.tipo:
            raise ValueError(
                f"El ajuste «{clave.clave}» ya está declarado con tipo "
                f"«{previa.tipo}» y se intenta registrar como «{clave.tipo}»"
            )
        CLAVES[clave.clave] = clave


def validar(clave: str, valor: Any) -> Any:
    """Valida y convierte un valor contra la declaración de su clave.

    Se valida al ESCRIBIR, no al leer. Si un valor inválido entrara en la tabla,
    reventaría mucho después, en la petición de un usuario que no tiene nada que
    ver con quien lo configuró — y el mensaje de error no diría qué ajuste fue.
    """
    from crmcore.errors import ErrorValidacion

    decl = CLAVES.get(clave)
    if decl is None:
        raise ErrorValidacion(
            f"El ajuste «{clave}» no existe",
            error_code="ajustes.clave_desconocida",
        )

    try:
        if decl.tipo == "bool":
            convertido: Any = (
                valor
                if isinstance(valor, bool)
                else str(valor).lower() in ("1", "true", "sí", "si")
            )
        elif decl.tipo == "int":
            convertido = int(valor)
        elif decl.tipo == "float":
            convertido = float(valor)
        elif decl.tipo == "str":
            convertido = str(valor)
        else:
            convertido = valor
    except (TypeError, ValueError):
        raise ErrorValidacion(
            f"El ajuste «{clave}» espera un valor de tipo {decl.tipo}",
            error_code="ajustes.tipo_invalido",
            detalle={"tipo_esperado": decl.tipo, "recibido": str(valor)[:80]},
        )

    if (
        decl.minimo is not None
        and isinstance(convertido, (int, float))
        and convertido < decl.minimo
    ):
        raise ErrorValidacion(
            f"El ajuste «{clave}» no puede ser menor que {decl.minimo}",
            error_code="ajustes.fuera_de_rango",
            detalle={"minimo": decl.minimo, "maximo": decl.maximo},
        )
    if (
        decl.maximo is not None
        and isinstance(convertido, (int, float))
        and convertido > decl.maximo
    ):
        raise ErrorValidacion(
            f"El ajuste «{clave}» no puede ser mayor que {decl.maximo}",
            error_code="ajustes.fuera_de_rango",
            detalle={"minimo": decl.minimo, "maximo": decl.maximo},
        )
    if decl.opciones and str(convertido) not in decl.opciones:
        raise ErrorValidacion(
            f"El ajuste «{clave}» admite: {', '.join(decl.opciones)}",
            error_code="ajustes.opcion_invalida",
            detalle={"opciones": list(decl.opciones)},
        )
    return convertido


ORDEN_AMBITOS: tuple[Ambito, ...] = ("global", "tier", "tenant", "bu", "usuario")


def ambito_permitido(clave: str, ambito: Ambito) -> bool:
    """Si una clave se puede fijar en ese ámbito.

    Un ajuste declarado con `minimo_ambito="tenant"` se puede fijar en tenant,
    global o tier, pero no por usuario: dejar que cada usuario se ponga su propio
    tope de cuota sería un agujero, no una preferencia.
    """
    decl = CLAVES.get(clave)
    if decl is None:
        return False
    return ORDEN_AMBITOS.index(ambito) <= ORDEN_AMBITOS.index(decl.minimo_ambito)
