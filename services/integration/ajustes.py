"""Ajustes propios del servicio de integración.

Nacen con la telefonía, la compensación externa y los avisos al chat
(CRM-04.02.01.05, CRM-03.02.03.04, CRM-06.01.01.03), que hasta el 09-11-2026
eran funciones puras: no llamaban a nadie, así que no tenían nada que ajustar.
Ahora llaman, y lo que deciden —qué operación de la conexión se invoca, cuánto
se espera, cuánto vive la ficha emergente— es configuración, no código.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from crmcore.config import Settings
from crmcore.runtime.keys import ClaveAjuste, registrar_claves
from crmcore.runtime.settings import registrar_ajustes_servicio
from pydantic import Field


class AjustesIntegration(Settings):
    """Configuración del servicio `integration`."""

    # ── Telefonía (CRM-04.02.01.05) ───────────────────────────────────────
    # Las operaciones que se piden a la conexión de telefonía. Son claves de
    # operaciones declaradas en la conexión: el proveedor es configuración.
    telefonia_op_originar: str = "originar_llamada"
    telefonia_op_transferir: str = "transferir_llamada"
    # Cuánto se espera a que la centralita conteste al originar o transferir.
    telefonia_espera_s: float = Field(15.0, ge=1.0, le=120.0)
    # Segundos que una llamada entrante sigue «sonando» para la ficha emergente
    # si la centralita no manda el colgado. Sin tope, una llamada cuyo final se
    # perdió se quedaría en la pantalla del agente para siempre.
    telefonia_ficha_emergente_s: int = Field(120, ge=10, le=3_600)
    # Cada cuántos segundos pregunta la pantalla si hay una llamada entrante.
    telefonia_sondeo_s: int = Field(5, ge=2, le=120)

    # ── Compensación externa (CRM-03.02.03.04) ───────────────────────────
    compensacion_op_enviar: str = "enviar_hechos"
    compensacion_op_calculo: str = "leer_calculo"
    # Diferencia por debajo de la cual el cálculo del motor y el de la casa
    # se dan por iguales (redondeos de céntimo).
    compensacion_tolerancia: float = Field(0.01, ge=0.0, le=1_000_000.0)
    compensacion_espera_s: float = Field(30.0, ge=1.0, le=300.0)

    # ── Avisos al chat (CRM-06.01.01.03) ──────────────────────────────────
    # El cuerpo que se manda al webhook entrante del canal. `{{texto}}` y
    # `{{enlace}}` se sustituyen. Por defecto, lo que aceptan los webhooks
    # entrantes de las plataformas habituales: un objeto con `text`.
    chat_plantilla_aviso: dict[str, Any] = Field(
        default_factory=lambda: {"text": "{{texto}} {{enlace}}"}
    )
    chat_espera_s: float = Field(10.0, ge=1.0, le=60.0)
    # La dirección pública del CRM, para que el aviso enlace al registro.
    chat_url_crm: str = ""

    # ── Referencias de la suite (CRM-06.01.03.08, .09, .12) ───────────────
    # La operación de la conexión del perfil de suite que dice si una nota, un
    # fichero o un hilo existe y si esta persona tiene acceso en el origen.
    suite_op_resolver_referencia: str = "resolver_referencia"

    # ── Señales de identidad hacia party (CRM-01.01.05.02) ────────────────
    # Cuánto se espera a party al mandar una señal, cuántas veces se reintenta
    # una que falla y cuántas manda el relevo por vuelta y tenant.
    senales_identidad_espera_s: float = Field(10.0, ge=1.0, le=120.0)
    senales_identidad_reintentos: int = Field(10, ge=1, le=1_000)
    senales_identidad_lote: int = Field(200, ge=1, le=10_000)

    # ── Número erróneo al cerrar una llamada ───────────────────────────────
    # El resultado comercial que dice que el número no es de esa persona, y el
    # estado que se escribe entonces en el teléfono de la ficha del contacto.
    telefonia_resultado_numero_erroneo: str = "numero_erroneo"
    telefonia_estado_telefono_erroneo: str = "erroneo"

    # ── Documentos desde la ficha del registro (CRM-06.01.01.06) ──────────
    # De dónde se leen los datos de cada tipo de registro, por HTTP y con la
    # identidad de quien genera. `{id}` es el del registro. `lineas`, si el
    # registro las tiene en otra ruta; `nombre`, el campo que lo nombra en el
    # fichero y en la carpeta del corpus. Un objeto nuevo se añade aquí, sin
    # tocar código. El presupuesto se lee por su ruta de documento, que es la
    # que NO trae el coste ni el margen.
    documento_fuentes: dict[str, Any] = Field(
        default_factory=lambda: {
            "oportunidad": {
                "ruta": "/api/v1/opportunities/{id}",
                "lineas": "/api/v1/opportunities/{id}/lineas",
                "nombre": "nombre",
            },
            "presupuesto": {"ruta": "/api/v1/presupuestos/{id}/documento", "nombre": "numero"},
            "contrato": {"ruta": "/api/v1/contratos/{id}", "nombre": "numero"},
            "pedido": {"ruta": "/api/v1/pedidos/{id}", "nombre": "numero"},
            "cuenta": {"ruta": "/api/v1/accounts/{id}", "nombre": "nombre"},
            "contacto": {
                "ruta": "/api/v1/contacts/{id}",
                "por_cuenta": "/api/v1/contacts?cuenta_id={id}&limite=1",
                "nombre": "nombre_completo",
            },
        }
    )
    # Cuánto se espera a cada servicio al leer el registro o guardar el PDF.
    documento_espera_s: float = Field(20.0, ge=1.0, le=120.0)
    # El papel y el margen del PDF. Letter para quien imprime en Estados Unidos.
    documento_pdf_papel: str = "A4"
    documento_pdf_margen_cm: float = Field(2.0, ge=0.5, le=5.0)
    # Los colores del PDF cuando el tenant no tiene marca configurada. Los de la
    # interfaz, para que el documento se parezca a la pantalla desde la que sale.
    documento_pdf_colores: dict[str, str] = Field(
        default_factory=lambda: {
            "acento": "#0176d3",
            "cabecera_tabla": "#014486",
            "texto": "#181818",
            "texto_suave": "#444444",
            "fila_alterna": "#f3f3f3",
            "fila_par": "#ffffff",
        }
    )
    # Qué campo de cada línea va en cada columna del PDF: el primero que la
    # línea traiga. Son nombres de campo, no textos; los títulos van en el
    # idioma de la plantilla.
    documento_pdf_columnas_lineas: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "descripcion": ["descripcion", "nombre", "sku"],
            "cantidad": ["cantidad"],
            "precio": ["precio", "precio_final", "precio_unitario"],
            "total": ["total", "importe"],
        }
    )
    # Los totales del registro que se ponen bajo las líneas, en este orden, si
    # el registro los trae.
    documento_pdf_totales: list[str] = Field(
        default_factory=lambda: ["subtotal", "descuento_total", "total"]
    )
    # Cómo se llama el fichero. `{plantilla}`, `{registro}` y `{fecha}`.
    documento_nombre_fichero: str = "{plantilla}-{registro}-{fecha}.pdf"
    # Si además del adjunto se archiva en el corpus documental cuando responde.
    documento_archivar_en_corpus: bool = True


registrar_claves(
    [
        ClaveAjuste(
            clave="telefonia_op_originar",
            tipo="str",
            descripcion="Operación de la conexión de telefonía que origina una llamada",
            campo_settings="telefonia_op_originar",
        ),
        ClaveAjuste(
            clave="telefonia_op_transferir",
            tipo="str",
            descripcion="Operación de la conexión de telefonía que transfiere una llamada",
            campo_settings="telefonia_op_transferir",
        ),
        ClaveAjuste(
            clave="telefonia_espera_s",
            tipo="float",
            descripcion="Segundos que se espera a la centralita al originar o transferir",
            minimo=1.0,
            maximo=120.0,
            campo_settings="telefonia_espera_s",
        ),
        ClaveAjuste(
            clave="telefonia_ficha_emergente_s",
            tipo="int",
            descripcion="Segundos que una llamada entrante sigue en la ficha emergente sin colgado",
            minimo=10,
            maximo=3_600,
            campo_settings="telefonia_ficha_emergente_s",
        ),
        ClaveAjuste(
            clave="telefonia_sondeo_s",
            tipo="int",
            descripcion="Cada cuántos segundos la pantalla pregunta si entra una llamada",
            minimo=2,
            maximo=120,
            campo_settings="telefonia_sondeo_s",
        ),
        ClaveAjuste(
            clave="compensacion_op_enviar",
            tipo="str",
            descripcion="Operación de la conexión del motor de compensación que recibe los hechos",
            campo_settings="compensacion_op_enviar",
        ),
        ClaveAjuste(
            clave="compensacion_op_calculo",
            tipo="str",
            descripcion="Operación de la conexión del motor de compensación que devuelve el cálculo",
            campo_settings="compensacion_op_calculo",
        ),
        ClaveAjuste(
            clave="compensacion_tolerancia",
            tipo="float",
            descripcion="Diferencia máxima entre el motor y la casa que se da por igual",
            minimo=0.0,
            maximo=1_000_000.0,
            campo_settings="compensacion_tolerancia",
        ),
        ClaveAjuste(
            clave="compensacion_espera_s",
            tipo="float",
            descripcion="Segundos que se espera al motor de compensación",
            minimo=1.0,
            maximo=300.0,
            campo_settings="compensacion_espera_s",
        ),
        ClaveAjuste(
            clave="chat_plantilla_aviso",
            tipo="json",
            descripcion="Cuerpo del aviso que se manda al webhook entrante de un canal de chat",
            campo_settings="chat_plantilla_aviso",
        ),
        ClaveAjuste(
            clave="chat_espera_s",
            tipo="float",
            descripcion="Segundos que se espera al webhook entrante del chat",
            minimo=1.0,
            maximo=60.0,
            campo_settings="chat_espera_s",
        ),
        ClaveAjuste(
            clave="suite_op_resolver_referencia",
            tipo="str",
            descripcion=(
                "Operación del perfil de suite que comprueba en el origen si una "
                "referencia existe y si quien la abre tiene acceso"
            ),
            campo_settings="suite_op_resolver_referencia",
        ),
        ClaveAjuste(
            clave="senales_identidad_espera_s",
            tipo="float",
            descripcion="Segundos que se espera a party al mandarle una señal de identidad",
            minimo=1.0,
            maximo=120.0,
            campo_settings="senales_identidad_espera_s",
        ),
        ClaveAjuste(
            clave="senales_identidad_reintentos",
            tipo="int",
            descripcion="Veces que se intenta mandar a party una señal de identidad que falla",
            minimo=1,
            maximo=1_000,
            campo_settings="senales_identidad_reintentos",
        ),
        ClaveAjuste(
            clave="senales_identidad_lote",
            tipo="int",
            descripcion="Señales de identidad que el relevo manda a party por vuelta y tenant",
            minimo=1,
            maximo=10_000,
            campo_settings="senales_identidad_lote",
        ),
        ClaveAjuste(
            clave="telefonia_resultado_numero_erroneo",
            tipo="str",
            descripcion="Resultado de la llamada que marca el teléfono de la ficha como erróneo",
            campo_settings="telefonia_resultado_numero_erroneo",
        ),
        ClaveAjuste(
            clave="telefonia_estado_telefono_erroneo",
            tipo="str",
            descripcion="Estado que se escribe en el teléfono del contacto cuando el número es erróneo",
            campo_settings="telefonia_estado_telefono_erroneo",
        ),
        ClaveAjuste(
            clave="documento_fuentes",
            tipo="json",
            descripcion=(
                "De qué ruta se leen los datos de cada tipo de registro al generar un "
                "documento desde su ficha (ruta, líneas y campo que lo nombra)"
            ),
            campo_settings="documento_fuentes",
        ),
        ClaveAjuste(
            clave="documento_espera_s",
            tipo="float",
            descripcion="Segundos que se espera a cada servicio al generar un documento",
            minimo=1.0,
            maximo=120.0,
            campo_settings="documento_espera_s",
        ),
        ClaveAjuste(
            clave="documento_pdf_papel",
            tipo="str",
            descripcion="Papel del PDF de los documentos generados (A4 o LETTER)",
            campo_settings="documento_pdf_papel",
        ),
        ClaveAjuste(
            clave="documento_pdf_margen_cm",
            tipo="float",
            descripcion="Margen del PDF de los documentos generados, en centímetros",
            minimo=0.5,
            maximo=5.0,
            campo_settings="documento_pdf_margen_cm",
        ),
        ClaveAjuste(
            clave="documento_pdf_colores",
            tipo="json",
            descripcion="Colores del PDF cuando el tenant no tiene marca configurada",
            campo_settings="documento_pdf_colores",
        ),
        ClaveAjuste(
            clave="documento_pdf_columnas_lineas",
            tipo="json",
            descripcion="Qué campo de cada línea va en cada columna del PDF (el primero presente)",
            campo_settings="documento_pdf_columnas_lineas",
        ),
        ClaveAjuste(
            clave="documento_pdf_totales",
            tipo="json",
            descripcion="Totales del registro que se ponen bajo las líneas del PDF, en orden",
            campo_settings="documento_pdf_totales",
        ),
        ClaveAjuste(
            clave="documento_nombre_fichero",
            tipo="str",
            descripcion="Nombre del PDF generado: {plantilla}, {registro} y {fecha}",
            campo_settings="documento_nombre_fichero",
        ),
        ClaveAjuste(
            clave="documento_archivar_en_corpus",
            tipo="bool",
            descripcion="Archivar también en el corpus documental el PDF generado, si responde",
            campo_settings="documento_archivar_en_corpus",
        ),
        ClaveAjuste(
            clave="chat_url_crm",
            tipo="str",
            descripcion="Dirección pública del CRM con la que se enlazan los avisos al chat",
            campo_settings="chat_url_crm",
        ),
    ]
)


@lru_cache(maxsize=1)
def ajustes() -> AjustesIntegration:
    return AjustesIntegration()


registrar_ajustes_servicio(ajustes)


def valor(clave: str, db: Any = None) -> Any:
    """El valor efectivo de un ajuste de integración, con su defecto de este servicio."""
    from crmcore.runtime.settings import efectivo

    return efectivo(clave, db, default=getattr(ajustes(), clave, None))
