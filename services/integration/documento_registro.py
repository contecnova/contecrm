"""Generar un documento desde la ficha de un registro (CRM-06.01.01.06).

Medido el 10-11-2026: la generación desde plantilla funcionaba, pero los datos
había que escribirlos a mano en «Componer el documento» —`objeto` y
`objeto_id` sólo se anotaban—, salía texto y no PDF, y guardarlo dependía de
contecmind, que no arranca. Aquí se cierran las tres cosas:

**Los datos salen del registro.** Se leen por HTTP, con la identidad de quien
genera, del servicio que los tiene: el registro, su cuenta, su contacto, sus
líneas y cualquier otro registro al que apunte con un `<objeto>_id` que esté
declarado en `documento_fuentes`. Con la identidad de quien genera y no con la
de «la casa»: si esa persona no ve un campo en la ficha, tampoco lo ve el
documento, y lo que viene tapado se avisa en vez de escribirse como si fuera el
dato.

**La persona revisa y completa lo que falte, y se le dice qué falta.** Cada
marcador vuelve con su valor, de dónde salió y si falta. Lo escrito a mano gana
a lo leído, porque es lo último que alguien decidió.

**Sale en PDF y se guarda como adjunto del registro**, con el motor de PDF de la
casa y el almacenamiento de adjuntos, que no depende de contecmind. Si el corpus
responde se archiva además allí; si no, se dice por qué y no falla nada: el
documento ya está guardado.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorDependencia, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.logging import get_logger
from sqlalchemy.orm import Session

logger = get_logger(__name__)

# ── Puerto sustituible ────────────────────────────────────────────────────

_http: Callable[..., dict[str, Any]] | None = None


def _registrar_http(fn: Callable[..., dict[str, Any]] | None) -> None:
    """Sólo para las pruebas: sustituye las llamadas a otros servicios por un doble."""
    global _http
    _http = fn


def _ajuste(clave: str, db: Session | None) -> Any:
    from services.integration.ajustes import valor

    return valor(clave, db)


def _identidad(principal: Any) -> dict[str, Any]:
    from services.integration.api_telefonia import identidad_de

    return identidad_de(principal)


def _llamar(
    principal: Any,
    *,
    metodo: str,
    ruta: str,
    cuerpo: dict[str, Any] | None = None,
    fichero: tuple[str, bytes, str] | None = None,
    formulario: dict[str, str] | None = None,
    espera_s: float = 20.0,
) -> dict[str, Any]:
    """Llama a otro servicio con la identidad de quien genera. `{estado, datos}`.

    No lanza por un 4xx: quien llama decide si es un fallo (el registro) o un
    aviso (la cuenta que no se pudo leer). Sí lanza si no hay a quién llamar.
    """
    if _http is not None:
        return _http(
            metodo=metodo, ruta=ruta, cuerpo=cuerpo, fichero=fichero, formulario=formulario
        )
    if fichero is None:
        from urllib.parse import parse_qsl

        from crmcore.http.interno import invocar

        # La consulta va aparte: con ella pegada a la ruta, la tabla de
        # enrutado no encuentra dueño para «/contacts?cuenta_id=…».
        camino, _, consulta = ruta.partition("?")
        return invocar(
            metodo=metodo,
            ruta=camino,
            parametros=dict(parse_qsl(consulta)) or None,
            cuerpo=cuerpo,
            timeout_s=espera_s,
            **_identidad(principal),
        )

    import httpx
    from crmcore.http.interno import cabeceras_de, direccion_de
    from crmcore.rutas_de_api import servicio_de

    servicio = servicio_de(ruta.lstrip("/")) or ""
    base = direccion_de(servicio)
    if not base:
        raise ErrorDependencia(
            f"No hay dirección para «{ruta}»", error_code="documento.servicio_sin_direccion"
        )
    cabeceras = cabeceras_de(**_identidad(principal))
    try:
        r = httpx.request(
            metodo,
            f"{base}{ruta}",
            files={"fichero": fichero},
            data=formulario or {},
            headers=cabeceras,
            timeout=espera_s,
        )
    except httpx.HTTPError as exc:
        raise ErrorDependencia(
            f"El servicio «{servicio}» no responde", error_code="documento.servicio_no_responde"
        ) from exc
    try:
        datos: Any = r.json()
    except ValueError:
        datos = {"texto": r.text[:500]}
    return {"estado": r.status_code, "datos": datos}


def _motivo(r: dict[str, Any]) -> str:
    datos = r.get("datos")
    if isinstance(datos, dict):
        return str(datos.get("detail") or datos.get("mensaje") or datos.get("title") or "")
    return ""


# ── Reunir los datos del registro ─────────────────────────────────────────


def _fuentes(db: Session | None) -> dict[str, dict[str, Any]]:
    return dict(_ajuste("documento_fuentes", db) or {})


def objetos_admitidos(db: Session | None) -> list[str]:
    """Los tipos de registro desde los que se puede generar, según la configuración."""
    return sorted(_fuentes(db))


def reunir(db: Session | None, principal: Any, *, objeto: str, objeto_id: UUID) -> dict[str, Any]:
    """El registro y sus relacionados, leídos de quien los tiene.

    Devuelve `{"contexto": {...}, "avisos": [...]}`. El registro es obligatorio:
    si no se puede leer, se lanza con el motivo. Lo relacionado no: una cuenta
    que no se pudo leer es un aviso, porque la persona puede escribir a mano lo
    que falte — pero se dice, porque un documento con el hueco callado se manda
    igual que uno completo.
    """
    fuentes = _fuentes(db)
    if objeto not in fuentes:
        raise ErrorValidacion(
            f"No se generan documentos desde «{objeto}»",
            error_code="documento.objeto_no_admitido",
            detalle={"admitidos": sorted(fuentes)},
        )
    espera = float(_ajuste("documento_espera_s", db) or 20.0)
    avisos: list[str] = []

    def leer(tipo: str, ident: Any, *, clave: str = "ruta") -> Any:
        ruta = str((fuentes.get(tipo) or {}).get(clave) or "")
        if not ruta:
            return None
        principal_del_registro = tipo == objeto and clave == "ruta"
        try:
            r = _llamar(principal, metodo="GET", ruta=ruta.format(id=ident), espera_s=espera)
        except Exception as exc:  # noqa: BLE001 — lo relacionado es un aviso, no un fallo
            if principal_del_registro:
                raise
            avisos.append(f"{tipo}: no se ha podido leer ({str(exc)[:160]})")
            return None
        estado = int(r.get("estado") or 0)
        for campo in r.get("campos_tapados") or []:
            avisos.append(f"{tipo}.{campo}: viene tapado, no en claro")
        for campo in r.get("campos_no_entregados") or []:
            avisos.append(f"{tipo}.{campo}: no se entrega a quien genera")
        if estado >= 400:
            if principal_del_registro:
                motivo = _motivo(r) or f"HTTP {estado}"
                if estado == 404:
                    raise NoEncontrado(motivo, error_code="documento.registro_no_encontrado")
                if estado == 403:
                    raise Prohibido(motivo, error_code="documento.registro_prohibido")
                raise ErrorDependencia(
                    f"No se ha podido leer el registro: {motivo}",
                    error_code="documento.registro_ilegible",
                    detalle={"codigo_http": estado},
                )
            avisos.append(f"{tipo}: no se ha podido leer ({_motivo(r) or f'HTTP {estado}'})")
            return None
        return r.get("datos")

    registro = leer(objeto, objeto_id)
    if not isinstance(registro, dict):
        raise ErrorDependencia(
            "El registro no ha llegado como se esperaba", error_code="documento.registro_ilegible"
        )
    contexto: dict[str, Any] = {"registro": registro, objeto: registro}

    # Las líneas: de su ruta si la tienen, o del propio registro si las trae.
    lineas: Any = None
    if (fuentes.get(objeto) or {}).get("lineas"):
        lineas = leer(objeto, objeto_id, clave="lineas")
        if isinstance(lineas, dict):
            lineas = lineas.get("items")
    elif isinstance(registro.get("lineas"), list):
        lineas = registro.get("lineas")
    contexto["lineas"] = lineas if isinstance(lineas, list) else []

    # Los relacionados: todo `<tipo>_id` del registro cuyo tipo esté declarado.
    # Genérico a propósito: un contrato trae su presupuesto, un presupuesto su
    # oportunidad, y no hay que escribir cada pareja.
    for campo, valor in list(registro.items()):
        if not campo.endswith("_id") or not valor:
            continue
        tipo = campo[: -len("_id")]
        if tipo == objeto or tipo not in fuentes or tipo in contexto:
            continue
        datos = leer(tipo, valor)
        if isinstance(datos, dict):
            contexto[tipo] = datos

    # Sin contacto propio, el primero de la cuenta: «Estimado/a {{contacto}}»
    # es la primera línea de casi cualquier oferta.
    cuenta = registro if objeto == "cuenta" else contexto.get("cuenta")
    if "contacto" not in contexto and objeto != "contacto" and isinstance(cuenta, dict):
        if (fuentes.get("contacto") or {}).get("por_cuenta") and cuenta.get("id"):
            pagina = leer("contacto", cuenta["id"], clave="por_cuenta")
            items = pagina.get("items") if isinstance(pagina, dict) else pagina
            if isinstance(items, list) and items:
                contexto["contacto"] = items[0]
    if objeto == "cuenta":
        contexto["cuenta"] = registro

    contexto["hoy"] = date.today().isoformat()
    return {"contexto": contexto, "avisos": avisos}


# ── Resolver los marcadores ───────────────────────────────────────────────

_ISO_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_INSTANTE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
_DECIMAL = re.compile(r"^-?\d+\.\d+$")


def _leer(datos: Any, camino: str) -> tuple[Any, Any]:
    """`(valor, padre)` de `cuenta.nombre`. El padre sirve para la moneda hermana."""
    padre: Any = None
    actual: Any = datos
    for parte in camino.split("."):
        if not isinstance(actual, dict):
            return None, None
        padre, actual = actual, actual.get(parte)
    return actual, padre


def _nombre_de(registro: dict[str, Any], tipo: str, fuentes: dict[str, Any]) -> str:
    """Cómo se nombra un registro: el campo declarado, o el primero que tenga."""
    declarado = str((fuentes.get(tipo) or {}).get("nombre") or "")
    for campo in (declarado, "nombre_completo", "nombre", "titulo", "numero", "codigo"):
        if campo and registro.get(campo) not in (None, ""):
            return str(registro[campo])
    return ""


def _formatear(valor: Any, formato: str, padre: Any, loc: Any) -> str:
    if valor is None:
        return ""
    if formato == "texto":
        return str(valor)
    texto = str(valor)
    if formato in ("fecha", "auto") and (_ISO_FECHA.match(texto) or _ISO_INSTANTE.match(texto)):
        try:
            if _ISO_FECHA.match(texto):
                return loc.fecha(date.fromisoformat(texto))
            return loc.fecha(datetime.fromisoformat(texto.replace("Z", "+00:00")))
        except ValueError:
            return texto
    moneda = padre.get("moneda") if isinstance(padre, dict) else None
    es_numero = isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool)
    if formato == "importe" or (
        formato == "auto" and moneda and (es_numero or _DECIMAL.match(texto))
    ):
        try:
            return loc.importe(Decimal(texto), str(moneda or "") or None)
        except (InvalidOperation, ValueError):
            return texto
    if formato == "numero" or (formato == "auto" and _DECIMAL.match(texto)):
        try:
            return loc.numero(Decimal(texto))
        except (InvalidOperation, ValueError):
            return texto
    return texto


def resolver(
    plantilla: Any,
    contexto: dict[str, Any],
    *,
    a_mano: dict[str, Any],
    loc: Any,
    fuentes: dict[str, Any],
) -> list[dict[str, Any]]:
    """Cada marcador con su valor, de dónde sale y si falta.

    Por orden: lo escrito a mano; lo que diga el mapeo de la plantilla; el
    propio nombre del marcador en los datos (`{{cuenta.nombre}}`); y el
    marcador como campo del registro (`{{importe}}`). Un marcador que cae en un
    registro entero (`{{contacto}}`) toma su nombre.
    """
    from crmcore.documental.plantillas import marcadores

    mapeo = dict(getattr(plantilla, "mapeo", None) or {})
    salida: list[dict[str, Any]] = []
    for marcador in marcadores(plantilla.cuerpo):
        escrito = a_mano.get(marcador)
        if escrito not in (None, ""):
            salida.append(
                {"marcador": marcador, "valor": str(escrito), "origen": "a_mano", "campo": ""}
            )
            continue
        origen = mapeo.get(marcador)
        formato = "auto"
        if isinstance(origen, dict):
            campo = str(origen.get("campo") or "")
            formato = str(origen.get("formato") or "auto")
        elif isinstance(origen, str) and origen:
            campo = origen
        else:
            campo = marcador
        valor, padre = _leer(contexto, campo)
        if valor is None and not origen:
            valor, padre = _leer(contexto.get("registro") or {}, campo)
            if valor is not None:
                campo = f"registro.{campo}"
        if isinstance(valor, dict):
            tipo = campo.split(".")[-1]
            valor, padre = _nombre_de(valor, tipo, fuentes) or None, None
        if isinstance(valor, list):
            valor = None
        texto = _formatear(valor, formato, padre, loc)
        salida.append(
            {
                "marcador": marcador,
                "valor": texto,
                "origen": "registro" if texto else "falta",
                "campo": campo if texto else (campo if origen else ""),
            }
        )
    return salida


def _localizacion(db: Session | None, idioma: str) -> Any:
    """Las preferencias del tenant, con el idioma de la plantilla."""
    from crmcore.i18n import Localizacion
    from crmcore.i18n import resolver as resolver_loc

    base = resolver_loc(db)
    loc = Localizacion(idioma=idioma or base.idioma, moneda=base.moneda)
    loc.zona = base.zona
    loc.formato_fecha = base.formato_fecha
    return loc


def preparar(
    db: Session,
    principal: Any,
    *,
    clave: str,
    objeto: str,
    objeto_id: UUID,
    a_mano: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lo que saldría, sin generar nada: cada marcador con su valor y lo que falta."""
    from crmcore.documental.plantillas import RE_MARCADOR, vigente

    plantilla = vigente(db, principal.tenant_id, clave)
    objetos = list(plantilla.objetos or [])
    if objetos and objeto not in objetos:
        raise ErrorValidacion(
            f"La plantilla «{clave}» no es para «{objeto}»",
            error_code="documento.plantilla_de_otro_objeto",
            detalle={"objetos": objetos},
        )
    reunido = reunir(db, principal, objeto=objeto, objeto_id=objeto_id)
    contexto = reunido["contexto"]
    fuentes = _fuentes(db)
    loc = _localizacion(db, plantilla.idioma)
    resueltos = resolver(plantilla, contexto, a_mano=a_mano or {}, loc=loc, fuentes=fuentes)
    valores = {r["marcador"]: r["valor"] for r in resueltos if r["valor"]}
    previo = RE_MARCADOR.sub(lambda m: valores.get(m.group(1), m.group(0)), plantilla.cuerpo)
    faltan = [r["marcador"] for r in resueltos if not r["valor"]]
    return {
        "plantilla": {
            "clave": plantilla.clave,
            "version": plantilla.version,
            "nombre": plantilla.nombre,
            "tipo": plantilla.tipo,
            "idioma": plantilla.idioma,
            "marca": plantilla.marca,
        },
        "registro": {
            "objeto": objeto,
            "id": str(objeto_id),
            "nombre": _nombre_de(contexto["registro"], objeto, fuentes),
        },
        "marcadores": resueltos,
        "faltan": faltan,
        "se_puede_generar": not faltan,
        "avisos": reunido["avisos"],
        "texto": previo,
        "lineas": len(contexto.get("lineas") or []),
        "_contexto": contexto,
        "_plantilla": plantilla,
        "_loc": loc,
    }


# ── El PDF ────────────────────────────────────────────────────────────────

# Los textos fijos del PDF, en el idioma de la plantilla. Son pocos y estables;
# un idioma que no esté aquí sale en castellano y se ve.
TEXTOS_PDF: dict[str, dict[str, str]] = {
    "es": {
        "lineas": "Detalle",
        "descripcion": "Descripción",
        "cantidad": "Cantidad",
        "precio": "Precio",
        "total": "Total",
        "subtotal": "Subtotal",
        "descuento_total": "Descuento",
        "importe": "Importe",
        "sin_lineas": "Sin líneas.",
        "pie": "{plantilla} · versión {version} · generado el {fecha}",
    },
    "ca": {
        "lineas": "Detall",
        "descripcion": "Descripció",
        "cantidad": "Quantitat",
        "precio": "Preu",
        "total": "Total",
        "subtotal": "Subtotal",
        "descuento_total": "Descompte",
        "importe": "Import",
        "sin_lineas": "Sense línies.",
        "pie": "{plantilla} · versió {version} · generat el {fecha}",
    },
    "en": {
        "lineas": "Details",
        "descripcion": "Description",
        "cantidad": "Quantity",
        "precio": "Price",
        "total": "Total",
        "subtotal": "Subtotal",
        "descuento_total": "Discount",
        "importe": "Amount",
        "sin_lineas": "No lines.",
        "pie": "{plantilla} · version {version} · generated on {fecha}",
    },
    "fr": {
        "lineas": "Détail",
        "descripcion": "Description",
        "cantidad": "Quantité",
        "precio": "Prix",
        "total": "Total",
        "subtotal": "Sous-total",
        "descuento_total": "Remise",
        "importe": "Montant",
        "sin_lineas": "Aucune ligne.",
        "pie": "{plantilla} · version {version} · généré le {fecha}",
    },
    "de": {
        "lineas": "Positionen",
        "descripcion": "Beschreibung",
        "cantidad": "Menge",
        "precio": "Preis",
        "total": "Gesamt",
        "subtotal": "Zwischensumme",
        "descuento_total": "Rabatt",
        "importe": "Betrag",
        "sin_lineas": "Keine Positionen.",
        "pie": "{plantilla} · Version {version} · erstellt am {fecha}",
    },
    "pt": {
        "lineas": "Detalhe",
        "descripcion": "Descrição",
        "cantidad": "Quantidade",
        "precio": "Preço",
        "total": "Total",
        "subtotal": "Subtotal",
        "descuento_total": "Desconto",
        "importe": "Montante",
        "sin_lineas": "Sem linhas.",
        "pie": "{plantilla} · versão {version} · gerado em {fecha}",
    },
}


def _marca(db: Session | None, principal: Any, plantilla: Any, registro: dict[str, Any]) -> Any:
    """La marca del PDF: nombre de la plantilla, del registro o del tenant; colores
    del tenant si tiene marca activa, y si no los de los ajustes."""
    from crmcore.documental.pdf import Marca

    colores = dict(_ajuste("documento_pdf_colores", db) or {})
    nombre = str(plantilla.marca or registro.get("marca") or "")
    try:
        r = _llamar(principal, metodo="GET", ruta="/api/v1/marca", espera_s=5.0)
        aplicable = (
            (r.get("datos") or {}).get("aplicable") if int(r.get("estado") or 0) < 400 else {}
        )
    except Exception as exc:  # noqa: BLE001 — sin marca del tenant, la de los ajustes
        logger.info("documento.sin_marca_del_tenant", error=str(exc)[:200])
        aplicable = {}
    aplicable = aplicable or {}
    nombre = nombre or str(aplicable.get("nombre_producto") or "")
    acento = str(aplicable.get("color_principal") or "") or colores.get("acento", "#0176d3")
    return Marca(
        nombre=nombre,
        acento=acento,
        cabecera_tabla=str(aplicable.get("color_principal") or "")
        or colores.get("cabecera_tabla", acento),
        texto=str(aplicable.get("color_texto") or "") or colores.get("texto", "#181818"),
        texto_suave=colores.get("texto_suave", "#444444"),
        fila_alterna=colores.get("fila_alterna", "#f3f3f3"),
        fila_par=colores.get("fila_par", "#ffffff"),
    )


def componer_pdf(
    db: Session | None,
    *,
    plantilla: Any,
    texto: str,
    contexto: dict[str, Any],
    marca: Any,
    loc: Any,
    titulo_registro: str,
    ahora: datetime | None = None,
) -> bytes:
    """El PDF: cabecera con la marca, el texto compuesto, las líneas y el pie."""
    from crmcore.documental.pdf import Columna, DocumentoPdf

    textos = TEXTOS_PDF.get((plantilla.idioma or "es")[:2], TEXTOS_PDF["es"])
    momento = ahora or datetime.now(timezone.utc)
    doc = DocumentoPdf(
        marca=marca,
        papel=str(_ajuste("documento_pdf_papel", db) or "A4"),
        margen_cm=float(_ajuste("documento_pdf_margen_cm", db) or 2.0),
        titulo=plantilla.nombre,
        idioma=plantilla.idioma or "es",
    )
    doc.cabecera(
        plantilla.nombre, " · ".join(p for p in (titulo_registro, loc.fecha(momento)) if p)
    )
    doc.texto(texto)

    registro = contexto.get("registro") or {}
    lineas = contexto.get("lineas") or []
    if plantilla.con_lineas and lineas:
        columnas_cfg = dict(_ajuste("documento_pdf_columnas_lineas", db) or {})
        moneda = registro.get("moneda")
        columnas = []
        filas: list[list[str]] = [[] for _ in lineas]
        for col, candidatos in columnas_cfg.items():
            campo = next(
                (c for c in candidatos if any(isinstance(ln, dict) and c in ln for ln in lineas)),
                None,
            )
            if campo is None:
                continue
            es_dinero = col in ("precio", "total")
            columnas.append(
                Columna(
                    textos.get(col, col),
                    peso=4.0 if col == "descripcion" else 1.4,
                    alinear="LEFT" if col == "descripcion" else "RIGHT",
                )
            )
            for i, ln in enumerate(lineas):
                valor = ln.get(campo) if isinstance(ln, dict) else None
                filas[i].append(
                    _formatear(
                        valor,
                        "importe" if es_dinero and moneda else "auto",
                        # La moneda sólo a las columnas de dinero: con ella al
                        # lado, «auto» tomaba la cantidad por un importe.
                        {"moneda": moneda} if es_dinero else None,
                        loc,
                    )
                    or "—"
                )
        doc.seccion(textos["lineas"])
        doc.tabla(columnas, filas, vacia=textos["sin_lineas"])
        totales = [
            (textos.get(c, c), _formatear(registro.get(c), "auto", registro, loc))
            for c in list(_ajuste("documento_pdf_totales", db) or [])
            if registro.get(c) not in (None, "")
        ]
        doc.datos(totales)

    pie = textos["pie"].format(
        plantilla=f"{plantilla.nombre} ({plantilla.clave})",
        version=plantilla.version,
        fecha=loc.fecha_hora(momento),
    )
    return doc.cerrar(pie=pie)


def _nombre_fichero(db: Session | None, plantilla: Any, registro: str) -> str:
    patron = str(_ajuste("documento_nombre_fichero", db) or "{plantilla}-{registro}-{fecha}.pdf")
    try:
        nombre = patron.format(
            plantilla=plantilla.clave,
            registro=registro or "registro",
            fecha=date.today().isoformat(),
        )
    except (KeyError, IndexError, ValueError):
        nombre = f"{plantilla.clave}-{registro}.pdf"
    nombre = re.sub(r"[^\w.\- ]+", "-", nombre).strip(" -")[:180] or "documento.pdf"
    return nombre if nombre.lower().endswith(".pdf") else f"{nombre}.pdf"


# ── Generar, guardar y archivar ───────────────────────────────────────────


def _anidar(valores: dict[str, str]) -> dict[str, Any]:
    """`{"cliente.nombre": "x"}` → `{"cliente": {"nombre": "x"}}`, que es lo que lee el motor."""
    salida: dict[str, Any] = {}
    for camino, valor in valores.items():
        actual = salida
        partes = camino.split(".")
        for parte in partes[:-1]:
            siguiente = actual.get(parte)
            if not isinstance(siguiente, dict):
                siguiente = {}
                actual[parte] = siguiente
            actual = siguiente
        actual[partes[-1]] = valor
    return salida


def generar(
    db: Session,
    principal: Any,
    *,
    clave: str,
    objeto: str,
    objeto_id: UUID,
    a_mano: dict[str, Any] | None = None,
    permitir_incompleto: bool = False,
) -> dict[str, Any]:
    """Genera el PDF desde el registro, lo guarda como adjunto y lo archiva si se puede.

    El orden importa: primero se compone (y si falta algo se para, con la
    lista), después se guarda el adjunto —que es lo que no puede fallar en
    silencio— y al final se archiva en el corpus, que puede no estar.
    """
    from crmcore.documental import plantillas as pl

    prep = preparar(db, principal, clave=clave, objeto=objeto, objeto_id=objeto_id, a_mano=a_mano)
    plantilla = prep["_plantilla"]
    contexto = prep["_contexto"]
    loc = prep["_loc"]
    valores = {r["marcador"]: r["valor"] for r in prep["marcadores"] if r["valor"]}
    compuesto = pl.generar(
        db,
        tenant_id=principal.tenant_id,
        clave=clave,
        datos=_anidar(valores),
        objeto=objeto,
        objeto_id=objeto_id,
        por=principal.id,
        permitir_incompleto=permitir_incompleto,
    )
    nombre_registro = prep["registro"]["nombre"]
    pdf = componer_pdf(
        db,
        plantilla=plantilla,
        texto=compuesto["texto"],
        contexto=contexto,
        marca=_marca(db, principal, plantilla, contexto.get("registro") or {}),
        loc=loc,
        titulo_registro=nombre_registro,
    )
    fichero = _nombre_fichero(db, plantilla, nombre_registro)
    espera = float(_ajuste("documento_espera_s", db) or 20.0)

    # El adjunto lo guarda el servicio dueño del registro. Si no se puede, se
    # lanza y la constancia se deshace con la transacción: un «generado» sin
    # documento guardado diría que se mandó algo que no está en ninguna parte.
    subida = _llamar(
        principal,
        metodo="POST",
        ruta=f"/api/v1/adjuntos/{objeto}",
        fichero=(fichero, pdf, "application/pdf"),
        formulario={
            "objeto_id": str(objeto_id),
            "descripcion": f"{plantilla.nombre} · v{plantilla.version}",
        },
        espera_s=espera,
    )
    estado = int(subida.get("estado") or 0)
    if estado >= 400:
        raise ErrorDependencia(
            f"El PDF se ha generado pero no se ha podido guardar como adjunto: "
            f"{_motivo(subida) or f'HTTP {estado}'}",
            error_code="documento.adjunto_no_guardado",
            detalle={"codigo_http": estado},
        )
    adjunto = subida.get("datos") or {}
    adjunto_id = str(adjunto.get("id") or "")

    constancia = db.get(pl.DocumentoGenerado, UUID(compuesto["constancia_id"]))
    if constancia is not None:
        constancia.adjunto_id = UUID(adjunto_id) if adjunto_id else None
        constancia.formato = "pdf"

    archivo = _archivar(
        db,
        principal,
        objeto=objeto,
        objeto_id=objeto_id,
        adjunto_id=adjunto_id,
        titulo=fichero,
        rol=plantilla.tipo,
        etiqueta=nombre_registro,
        espera_s=espera,
    )
    if archivo["archivado"] and constancia is not None:
        constancia.documento_id = archivo["documento_id"]
    db.flush()

    logger.info(
        "documento.generado_desde_registro",
        plantilla=clave,
        version=plantilla.version,
        objeto=objeto,
        archivado=archivo["archivado"],
    )
    return {
        "plantilla": clave,
        "version": plantilla.version,
        "texto": compuesto["texto"],
        "incompleto": compuesto["incompleto"],
        "faltaban": compuesto["faltaban"],
        "aviso": compuesto["aviso"],
        "avisos": prep["avisos"],
        "adjunto": {
            "id": adjunto_id,
            "nombre": adjunto.get("nombre") or fichero,
            "objeto": objeto,
            "tamano": adjunto.get("tamano") or len(pdf),
            "descargar": f"/api/v1/adjuntos/{objeto}/{adjunto_id}/contenido",
        },
        "corpus": archivo,
    }


def _archivar(
    db: Session | None,
    principal: Any,
    *,
    objeto: str,
    objeto_id: UUID,
    adjunto_id: str,
    titulo: str,
    rol: str,
    etiqueta: str,
    espera_s: float,
) -> dict[str, Any]:
    """Lo archiva en el corpus si se puede. **Nunca lanza**: el documento ya está guardado."""
    if not _ajuste("documento_archivar_en_corpus", db):
        return {
            "archivado": False,
            "documento_id": "",
            "motivo": "Archivar en el corpus está desactivado en los ajustes",
        }
    try:
        r = _llamar(
            principal,
            metodo="POST",
            ruta=f"/api/v1/documentos/{objeto}/{objeto_id}/archivar-adjunto/{adjunto_id}",
            cuerpo={"titulo": titulo, "rol": rol, "etiqueta": etiqueta},
            espera_s=espera_s,
        )
    except Exception as exc:  # noqa: BLE001 — archivar es un extra, no puede romper lo guardado
        return {"archivado": False, "documento_id": "", "motivo": str(exc)[:300]}
    estado = int(r.get("estado") or 0)
    if estado >= 400:
        return {
            "archivado": False,
            "documento_id": "",
            "motivo": _motivo(r) or f"El corpus documental ha contestado {estado}",
        }
    datos = r.get("datos") or {}
    return {
        "archivado": True,
        "documento_id": str(datos.get("documento_id") or ""),
        "motivo": "",
    }


def plantillas_para(db: Session, tenant_id: UUID, objeto: str) -> list[dict[str, Any]]:
    """Las plantillas vigentes que sirven para este tipo de registro."""
    from crmcore.documental.plantillas import PlantillaDocumento, marcadores
    from sqlalchemy import select

    filas = (
        db.execute(
            select(PlantillaDocumento)
            .where(
                PlantillaDocumento.tenant_id == tenant_id,
                PlantillaDocumento.vigente.is_(True),
                PlantillaDocumento.deleted_at.is_(None),
            )
            .order_by(PlantillaDocumento.nombre)
        )
        .scalars()
        .all()
    )
    return [
        {
            "clave": f.clave,
            "nombre": f.nombre,
            "tipo": f.tipo,
            "idioma": f.idioma,
            "marca": f.marca,
            "version": f.version,
            "marcadores": marcadores(f.cuerpo),
            "mapeo": f.mapeo or {},
        }
        for f in filas
        if not f.objetos or objeto in f.objetos
    ]
