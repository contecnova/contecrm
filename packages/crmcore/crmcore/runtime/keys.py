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
        # Identidad
        _c(
            "mfa_obligatoria",
            "bool",
            "Exigir MFA a todos los usuarios del tenant",
            campo_settings="mfa_obligatoria",
            sensible=True,
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
        # Protección del dato
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
