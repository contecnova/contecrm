"""El correo como lo va a recibir alguien de verdad (CRM-02.03.01.02,
CRM-02.03.01.06, CRM-02.03.01.07).

Hasta el 09-11-2026 había tres medias capacidades:

* **la personalización** sustituía tokens con datos que se tecleaban en la
  pantalla —no con los del contacto— y las «recomendaciones» no existían;
* **la previsualización** no tenía pantalla (`/componer` devolvía los bloques en
  JSON) y el «spam score» era una lista de seis palabras;
* **la separación transaccional/promocional** sólo informaba de dos dominios:
  nada salía de verdad por ninguno de ellos.

Aquí las tres de una vez, porque son la misma cosa vista desde tres sitios: el
correo montado con los datos reales de una persona, por dónde sale y con qué
probabilidad acaba en basura.

**Los datos salen de su dueño.** El contacto y su cuenta los guarda `party`; las
oportunidades y el catálogo, `sales`. Se preguntan por HTTP con la identidad de
quien mira, y si no contestan **se dice**, en vez de componer con huecos.

**Las recomendaciones salen del historial, no de una lista fija.** Las familias
de producto que la cuenta ya tiene en sus oportunidades deciden qué productos de
esas familias, que todavía no tiene, se le recomiendan; y los contenidos de la
biblioteca etiquetados con esas familias. Sin historial no se recomienda nada y
se dice por qué: recomendar «lo más vendido» a quien no conocemos es publicidad,
no recomendación.

**El spam se puntúa con reglas que se pueden leer.** Cada regla dice qué ha
visto y cuánto suma; los pesos y el umbral son ajustes. Un número sin
explicación lo ignora todo el mundo; una lista de «esto te resta» se arregla.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from crmcore.errors import NoDisponible
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = get_logger(__name__)


def _ajuste(clave: str, db: Session | None) -> Any:
    from services.marketing.ajustes import valor

    return valor(clave, db)


def clase_de(plantilla_clase: str) -> str:
    """Promocional o transaccional. Todo lo que no es promocional —«operativa»,
    «aviso», «factura»— es transaccional: el riesgo está en confundirlo al revés."""
    return (
        "promocional"
        if str(plantilla_clase or "") in ("promocional", "marketing")
        else ("transaccional")
    )


# ── Por dónde sale cada clase (CRM-02.03.01.07) ───────────────────────────


def _dominio_de(direccion: str) -> str:
    return direccion.rsplit("@", 1)[-1].strip().lower() if "@" in direccion else ""


def salida(db: Session, tenant_id: UUID, clase: str) -> dict[str, Any]:
    """Dominio, remitente y flujo por los que sale una clase de correo.

    El dominio es el ajuste de la clase; si no está, el dominio de envío dado de
    alta con ese uso. El flujo —el servidor SMTP— es el propio de la clase; si no,
    el del canal de correo del tenant, y si no, el del despliegue. **Y se dice
    cuál es**, porque «sale por el mismo sitio» es justo lo que hay que ver.
    """
    from crmcore.runtime import settings as rt

    from services.marketing.canales import DominioEnvio

    usos = ("promocional", "marketing") if clase == "promocional" else ("transaccional",)
    dominio = str(_ajuste(f"dominio_{clase}", db) or "").strip().lower()
    fila = None
    if not dominio:
        fila = db.execute(
            select(DominioEnvio)
            .where(
                DominioEnvio.tenant_id == tenant_id,
                DominioEnvio.uso.in_(usos),
                DominioEnvio.deleted_at.is_(None),
            )
            .order_by(DominioEnvio.created_at)
            .limit(1)
        ).scalar_one_or_none()
        dominio = fila.dominio.lower() if fila else ""
    else:
        fila = db.execute(
            select(DominioEnvio).where(
                DominioEnvio.tenant_id == tenant_id, DominioEnvio.dominio == dominio
            )
        ).scalar_one_or_none()

    remitente = str(_ajuste(f"remitente_{clase}", db) or "").strip()
    propio = dict(_ajuste(f"correo_flujo_{clase}", db) or {})
    del_tenant = dict(rt.efectivo("canal_correo", db, default={}) or {})
    flujo = propio or del_tenant
    origen_flujo = "propio" if propio else ("tenant" if del_tenant else "despliegue")
    from crmcore.config import get_settings

    s = get_settings()
    host = str(flujo.get("host") or s.smtp_host or "")
    if not remitente:
        remitente = str(flujo.get("remitente") or "")

    problemas: list[str] = []
    if not dominio:
        problemas.append(f"No hay dominio de envío para lo {clase}.")
    if not remitente:
        problemas.append(f"No hay remitente para lo {clase}.")
    elif dominio and _dominio_de(remitente) != dominio:
        problemas.append(
            f"El remitente «{remitente}» no es del dominio «{dominio}»: saldría por el "
            "dominio equivocado y compartiría su reputación."
        )
    if not host:
        problemas.append("No hay servidor de salida configurado.")
    return {
        "clase": clase,
        "dominio": dominio or None,
        "remitente": remitente or None,
        "remitente_nombre": str(flujo.get("remitente_nombre") or ""),
        "flujo": {
            "origen": origen_flujo,
            "host": host or None,
            "puerto": flujo.get("puerto") or s.smtp_puerto,
            "tls": str(flujo.get("tls") or s.smtp_tls),
        },
        "autenticacion": (
            {
                "spf": fila.spf,
                "dkim": fila.dkim,
                "dmarc": fila.dmarc,
                "bimi": fila.bimi,
            }
            if fila is not None
            else None
        ),
        "puede_salir": not problemas,
        "problemas": problemas,
        "_config": {**flujo, "remitente": remitente},
    }


def separacion(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Las dos clases juntas y si de verdad van por sitios distintos."""
    pro = salida(db, tenant_id, "promocional")
    tra = salida(db, tenant_id, "transaccional")
    mismo_dominio = bool(pro["dominio"]) and pro["dominio"] == tra["dominio"]
    mismo_flujo = (pro["flujo"]["host"], pro["flujo"]["origen"]) == (
        tra["flujo"]["host"],
        tra["flujo"]["origen"],
    ) and pro["flujo"]["origen"] != "propio"
    separados = bool(pro["dominio"] and tra["dominio"]) and not mismo_dominio
    for d in (pro, tra):
        d.pop("_config", None)
    return {
        "promocional": pro,
        "transaccional": tra,
        "separados": separados,
        "mismo_flujo": mismo_flujo,
        "aviso": (
            ""
            if separados and not mismo_flujo
            else (
                "Comparten dominio: una campaña con quejas hundirá la entrega de las " "facturas."
                if not separados
                else "Dominios distintos, pero el mismo servidor de salida: la reputación "
                "de la IP se comparte. Declara un flujo propio para cada clase."
            )
        ),
    }


# ── Los datos reales (CRM-02.03.01.02) ────────────────────────────────────


def _invocar(**kw: Any) -> dict[str, Any]:
    from crmcore.http.interno import invocar

    return invocar(**kw)


def _get(
    invocar: Any,
    ruta: str,
    *,
    tenant_id: UUID,
    principal_id: Any,
    permisos: list[str],
    parametros: dict[str, Any] | None = None,
) -> Any:
    r = invocar(
        metodo="GET",
        ruta=ruta,
        parametros=parametros,
        tenant_id=tenant_id,
        principal_id=principal_id,
        permisos=permisos,
        timeout_s=10.0,
    )
    if r.get("estado") == 404:
        return None
    if not r.get("ok"):
        raise NoDisponible(
            f"«{ruta}» ha contestado {r.get('estado')}", error_code="vista.origen_no_contesta"
        )
    return r.get("datos")


def _filas(datos: Any) -> list[dict[str, Any]]:
    if isinstance(datos, list):
        return [d for d in datos if isinstance(d, dict)]
    if isinstance(datos, dict):
        for k in ("datos", "elementos", "filas", "items"):
            if isinstance(datos.get(k), list):
                return [d for d in datos[k] if isinstance(d, dict)]
    return []


def recomendar(
    db: Session,
    tenant_id: UUID,
    *,
    cuenta_id: UUID | None,
    principal_id: Any,
    invocar: Any = None,
) -> dict[str, Any]:
    """Qué productos y qué contenidos recomendar a esta cuenta, por su historial."""
    from services.marketing.activos import Activo

    llamar = invocar or _invocar
    maximo = int(_ajuste("recomendaciones_maximo", db) or 3)
    vacio = {"productos": [], "contenidos": [], "familias": []}
    if cuenta_id is None:
        return {**vacio, "porque": "No tiene cuenta: no hay historial del que recomendar."}

    oportunidades = _filas(
        _get(
            llamar,
            "/api/v1/opportunities",
            parametros={"cuenta_id": str(cuenta_id), "estado": "", "limite": 50},
            tenant_id=tenant_id,
            principal_id=principal_id,
            permisos=["opportunity:read"],
        )
    )
    tiene: set[str] = set()
    for op in oportunidades[:20]:
        for linea in _filas(
            _get(
                llamar,
                f"/api/v1/opportunities/{op.get('id')}/lineas",
                tenant_id=tenant_id,
                principal_id=principal_id,
                permisos=["opportunity:read"],
            )
        ):
            if linea.get("producto_id"):
                tiene.add(str(linea["producto_id"]))
    if not tiene:
        return {
            **vacio,
            "porque": (
                f"La cuenta tiene {len(oportunidades)} oportunidades y ninguna línea con "
                "producto: sin historial no se recomienda nada. Recomendar «lo más "
                "vendido» a quien no conocemos es publicidad, no recomendación."
            ),
        }
    catalogo = _filas(
        _get(
            llamar,
            "/api/v1/productos",
            parametros={"limite": 1000},
            tenant_id=tenant_id,
            principal_id=principal_id,
            permisos=["producto:read"],
        )
    )
    por_id = {str(p.get("id")): p for p in catalogo}
    familias = sorted(
        {str(por_id[i].get("familia")) for i in tiene if por_id.get(i, {}).get("familia")}
    )
    productos = [
        {
            "id": str(p.get("id")),
            "nombre": p.get("nombre"),
            "sku": p.get("sku"),
            "familia": p.get("familia"),
            "porque": f"Es de la familia «{p.get('familia')}», que ya tiene, y este no lo tiene.",
        }
        for p in catalogo
        if str(p.get("familia") or "") in familias and str(p.get("id")) not in tiene
    ][:maximo]
    contenidos = []
    if familias:
        for a in db.execute(
            select(Activo).where(Activo.tenant_id == tenant_id, Activo.deleted_at.is_(None))
        ).scalars():
            etiquetas = {str(e).lower() for e in (a.etiquetas or [])}
            comunes = [f for f in familias if f.lower() in etiquetas]
            if comunes and "correo" in [str(u) for u in (a.usos_permitidos or [])]:
                contenidos.append(
                    {
                        "id": str(a.id),
                        "nombre": a.nombre,
                        "referencia": a.referencia,
                        "porque": f"Habla de «{comunes[0]}», que es de lo que tiene.",
                    }
                )
            if len(contenidos) >= maximo:
                break
    return {
        "productos": productos,
        "contenidos": contenidos,
        "familias": familias,
        "porque": (
            f"Sale de {len(tiene)} productos en sus oportunidades, de las familias "
            + ", ".join(familias)
            + "."
        ),
    }


def datos_de(
    db: Session,
    tenant_id: UUID,
    *,
    contacto_id: UUID,
    principal_id: Any,
    invocar: Any = None,
) -> dict[str, Any]:
    """Los datos con los que se rellena el correo de esta persona, de su dueño."""
    llamar = invocar or _invocar
    contacto = _get(
        llamar,
        f"/api/v1/contacts/{contacto_id}",
        tenant_id=tenant_id,
        principal_id=principal_id,
        permisos=["contact:read"],
    )
    if not isinstance(contacto, dict):
        raise NoDisponible("Ese contacto no existe", error_code="vista.contacto_no_existe")
    cuentas = _filas(
        _get(
            llamar,
            f"/api/v1/contacts/{contacto_id}/cuentas",
            tenant_id=tenant_id,
            principal_id=principal_id,
            permisos=["contact:read"],
        )
    )
    cuenta: dict[str, Any] = {}
    cuenta_id = None
    if cuentas:
        vinculo = cuentas[0]
        cuenta_id = vinculo.get("cuenta_id") or vinculo.get("id")
        datos_cuenta = _get(
            llamar,
            f"/api/v1/accounts/{cuenta_id}",
            tenant_id=tenant_id,
            principal_id=principal_id,
            permisos=["account:read"],
        )
        cuenta = datos_cuenta if isinstance(datos_cuenta, dict) else {}
    recomendaciones = recomendar(
        db,
        tenant_id,
        cuenta_id=UUID(str(cuenta_id)) if cuenta_id else None,
        principal_id=principal_id,
        invocar=llamar,
    )
    ficha_contacto = {
        k: contacto.get(k)
        for k in (
            "nombre",
            "apellidos",
            "nombre_completo",
            "cargo",
            "email",
            "telefono",
            "idioma",
            "tratamiento",
        )
    }
    ficha_cuenta = {k: cuenta.get(k) for k in ("nombre", "sector", "pais", "ciudad", "web")}
    datos: dict[str, Any] = {
        "contacto": ficha_contacto,
        "cuenta": ficha_cuenta,
        **{k: v for k, v in ficha_contacto.items() if v not in (None, "")},
        "empresa": ficha_cuenta.get("nombre"),
        "recomendaciones": recomendaciones,
    }
    for i, p in enumerate(recomendaciones["productos"], start=1):
        datos[f"recomendacion_{i}"] = p
    url_baja = str(_ajuste("correo_url_baja", db) or "")
    if url_baja and contacto.get("email"):
        datos["url_baja"] = url_baja.replace("{email}", str(contacto["email"]))
    return datos


# ── Montar el HTML ────────────────────────────────────────────────────────


def _rellenar(texto: Any, datos: dict[str, Any], sin_dato: set[str]) -> str:
    from services.marketing.canales import personalizar

    r = personalizar(str(texto or ""), datos)
    sin_dato.update(r["sin_dato"])
    return html.escape(r["texto"])


def _bloque_html(
    bloque: dict[str, Any], datos: dict[str, Any], sin_dato: set[str], *, imagenes: bool
) -> str:
    tipo = str(bloque.get("tipo") or "")
    c = dict(bloque.get("contenido") or {})

    def img(src: Any, alt: Any, alto: Any = None) -> str:
        alt_txt = _rellenar(alt, datos, sin_dato)
        if not imagenes:
            return f'<div class="sin-imagen">[{alt_txt or "imagen"}]</div>'
        estilo = f' style="height:{int(alto)}px"' if alto else ""
        return f'<img src="{html.escape(str(src or ""))}" alt="{alt_txt}"{estilo}>'

    if tipo == "cabecera":
        return f'<div class="cabecera">{img(c.get("logo"), c.get("alt") or "logo", c.get("alto"))}</div>'
    if tipo == "imagen":
        return f'<div class="imagen">{img(c.get("url") or c.get("src"), c.get("alt"))}</div>'
    if tipo == "boton":
        enlace = _rellenar(c.get("enlace") or c.get("url"), datos, sin_dato)
        return f'<p class="boton"><a href="{enlace}">{_rellenar(c.get("texto"), datos, sin_dato)}</a></p>'
    if tipo == "separador":
        return "<hr>"
    if tipo == "pie":
        baja = _rellenar(c.get("enlace_baja"), datos, sin_dato)
        enlace = f' · <a href="{baja}">Darse de baja</a>' if baja else ""
        return f'<p class="pie">{_rellenar(c.get("texto"), datos, sin_dato)}{enlace}</p>'
    if tipo == "recomendaciones" or (tipo in ("contenido", "columnas") and c.get("muestra")):
        recs = (datos.get("recomendaciones") or {}).get("productos") or []
        if not recs:
            return ""
        celdas = "".join(
            f'<td class="rec"><strong>{html.escape(str(r.get("nombre") or ""))}</strong>'
            f'<br><small>{html.escape(str(r.get("sku") or ""))}</small></td>'
            for r in recs
        )
        return f'<table class="recomendaciones"><tr>{celdas}</tr></table>'
    texto = c.get("html") or c.get("texto") or ""
    return f"<p>{_rellenar(texto, datos, sin_dato)}</p>"


def montar(
    composicion: dict[str, Any],
    datos: dict[str, Any],
    *,
    ancho: int = 600,
    imagenes: bool = True,
    oscuro: bool = False,
) -> dict[str, Any]:
    sin_dato: set[str] = set()
    asunto_html = _rellenar(composicion.get("asunto"), datos, sin_dato)
    cuerpo = "".join(
        _bloque_html(b, datos, sin_dato, imagenes=imagenes)
        for b in composicion.get("bloques") or []
    )
    fondo, tinta = ("#1e1e1e", "#e8e8e8") if oscuro else ("#ffffff", "#1a1a1a")  # noqa: S105
    documento = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>body{{margin:0;background:{fondo};color:{tinta};font-family:Arial,sans-serif}}"
        f".marco{{max-width:{int(ancho)}px;margin:0 auto;padding:16px}}"
        "img{max-width:100%}.sin-imagen{border:1px dashed #999;padding:8px;color:#777}"
        ".boton a{display:inline-block;padding:10px 16px;border-radius:6px;background:#2563eb;"
        "color:#fff;text-decoration:none}.pie{font-size:12px;color:#888}"
        ".recomendaciones{width:100%}.rec{padding:6px;border:1px solid #ccc}</style></head>"
        f"<body><div class='marco'>{cuerpo}</div></body></html>"
    )
    return {
        "asunto": html.unescape(asunto_html),
        "html": documento,
        "cuerpo": cuerpo,
        "sin_dato": sorted(sin_dato),
    }


def texto_plano(cuerpo_html: str) -> str:
    # Sin el `<style>`: si no, la parte de texto del correo empieza por el CSS.
    sin_estilo = re.sub(r"<style[^>]*>.*?</style>", " ", cuerpo_html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", sin_estilo))).strip()


# ── Spam (CRM-02.03.01.06) ────────────────────────────────────────────────

RE_ENLACE = re.compile(r'<a\s[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
RE_IMG = re.compile(r"<img\s[^>]*>", re.I)
RE_IP = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def puntuar_spam(
    db: Session,
    *,
    asunto: str,
    cuerpo_html: str,
    clase: str,
    salida_clase: dict[str, Any],
    sin_dato: list[str],
) -> dict[str, Any]:
    """Puntúa el correo con reglas explicadas. Más puntos, más cerca de la basura."""
    pesos = {str(k): float(v) for k, v in dict(_ajuste("spam_pesos", db) or {}).items()}
    umbral = float(_ajuste("spam_umbral", db) or 5)
    palabras = [str(p).lower() for p in (_ajuste("spam_palabras", db) or [])]
    acortadores = [str(a).lower() for a in (_ajuste("spam_acortadores", db) or [])]
    maximo_enlaces = int(_ajuste("spam_maximo_enlaces", db) or 15)

    reglas: list[dict[str, Any]] = []

    def suma(clave: str, grupo: str, porque: str, veces: int = 1) -> None:
        puntos = round(pesos.get(clave, 0.0) * veces, 2)
        if puntos:
            reglas.append({"regla": clave, "grupo": grupo, "puntos": puntos, "porque": porque})

    # Estructura.
    if not asunto.strip():
        suma("asunto_vacio", "estructura", "El asunto está vacío.")
    letras = [c for c in asunto if c.isalpha()]
    if len(letras) >= 8 and sum(c.isupper() for c in letras) / len(letras) > 0.6:
        suma("asunto_mayusculas", "estructura", "El asunto va casi entero en mayúsculas.")
    if asunto.count("!") >= 2:
        suma("asunto_exclamaciones", "estructura", "Varios signos de exclamación en el asunto.")
    texto = texto_plano(cuerpo_html)
    todo = f"{asunto} {texto}".lower()
    vistas = [p for p in palabras if p and p in todo]
    if vistas:
        suma(
            "palabras_gatillo",
            "estructura",
            "Palabras que los filtros marcan: " + ", ".join(f"«{v}»" for v in vistas) + ".",
            veces=len(vistas),
        )
    if sin_dato:
        suma(
            "tokens_sin_rellenar",
            "estructura",
            "Campos sin dato que saldrían vacíos: " + ", ".join(sin_dato) + ".",
        )
    # Proporción texto/imagen.
    imagenes = RE_IMG.findall(cuerpo_html)
    if not texto:
        suma("sin_texto", "texto_imagen", "No hay texto: un correo que es sólo imagen va a basura.")
    elif imagenes and len(texto) / len(imagenes) < 200:
        suma(
            "poco_texto_por_imagen",
            "texto_imagen",
            f"{len(texto)} caracteres de texto para {len(imagenes)} imágenes: hace falta más texto.",
        )
    sin_alt = [i for i in imagenes if 'alt=""' in i or "alt=" not in i]
    if sin_alt:
        suma(
            "imagen_sin_alt",
            "texto_imagen",
            f"{len(sin_alt)} imágenes sin texto alternativo.",
            veces=len(sin_alt),
        )
    # Enlaces.
    enlaces = RE_ENLACE.findall(cuerpo_html)
    if len(enlaces) > maximo_enlaces:
        suma("muchos_enlaces", "enlaces", f"{len(enlaces)} enlaces: parece un folleto.")
    hay_baja = False
    for href, etiqueta in enlaces:
        destino = urlparse(html.unescape(href))
        host = (destino.hostname or "").lower()
        if "baja" in texto_plano(etiqueta).lower():
            hay_baja = bool(href)
        if host and RE_IP.match(host):
            suma("enlace_a_ip", "enlaces", f"Un enlace va a una IP ({host}) y no a un dominio.")
        if host and any(host == a or host.endswith("." + a) for a in acortadores):
            suma("acortador", "enlaces", f"Un enlace usa el acortador {host}: esconde el destino.")
        visible = texto_plano(etiqueta)
        visto = urlparse(visible if "://" in visible else "")
        if visto.hostname and host and visto.hostname.lower() != host:
            suma(
                "enlace_engana",
                "enlaces",
                f"El texto dice «{visto.hostname}» y el enlace lleva a «{host}».",
            )
        if destino.scheme == "http":
            suma("enlace_sin_https", "enlaces", f"El enlace a {host or href} no va por https.")
    if clase == "promocional" and not hay_baja:
        suma(
            "promocional_sin_baja",
            "cabeceras",
            "Es promocional y no lleva enlace de baja: los proveedores lo exigen.",
        )
    # Autenticación del dominio.
    auth = salida_clase.get("autenticacion")
    if not salida_clase.get("dominio"):
        suma("sin_dominio", "autenticacion", f"No hay dominio de envío para lo {clase}.")
    elif auth is None:
        suma(
            "sin_spf",
            "autenticacion",
            f"«{salida_clase['dominio']}» no está dado de alta: no se sabe si tiene SPF.",
        )
    else:
        if not auth.get("spf"):
            suma("sin_spf", "autenticacion", "El dominio no publica SPF.")
        if not auth.get("dkim"):
            suma("sin_dkim", "autenticacion", "El dominio no firma con DKIM.")
        if not auth.get("dmarc"):
            suma("sin_dmarc", "autenticacion", "El dominio no publica DMARC.")
        elif auth.get("dmarc") == "none":
            suma("dmarc_none", "autenticacion", "DMARC está en «none»: detecta pero no protege.")
    remitente = str(salida_clase.get("remitente") or "")
    if (
        remitente
        and salida_clase.get("dominio")
        and _dominio_de(remitente) != salida_clase["dominio"]
    ):
        suma(
            "remitente_otro_dominio",
            "autenticacion",
            f"El remitente «{remitente}» no es del dominio de la clase.",
        )

    total = round(sum(r["puntos"] for r in reglas), 2)
    return {
        "puntos": total,
        "umbral": umbral,
        "veredicto": "basura" if total >= umbral else ("dudoso" if total >= umbral / 2 else "bien"),
        "reglas": sorted(reglas, key=lambda r: -r["puntos"]),
        "texto_caracteres": len(texto),
        "imagenes": len(imagenes),
        "enlaces": len(enlaces),
    }


def vista_previa(
    db: Session,
    tenant_id: UUID,
    *,
    plantilla: str,
    idioma: str,
    contacto_id: UUID | None,
    principal_id: Any,
    invocar: Any = None,
) -> dict[str, Any]:
    """El correo montado con los datos de un contacto real, en cada cliente."""
    from services.marketing.correo import componer

    composicion = componer(db, tenant_id, plantilla, idioma=idioma)
    clase = clase_de(composicion.get("clase") or "")
    datos: dict[str, Any] = {}
    aviso_datos = ""
    if contacto_id is not None:
        try:
            datos = datos_de(
                db, tenant_id, contacto_id=contacto_id, principal_id=principal_id, invocar=invocar
            )
        except NoDisponible as exc:
            aviso_datos = str(exc.mensaje)
    else:
        aviso_datos = "Sin contacto elegido: los campos salen vacíos."
    clientes = []
    for cli in list(_ajuste("vista_previa_clientes", db) or []):
        m = montar(
            composicion,
            datos,
            ancho=int(cli.get("ancho") or 600),
            imagenes=bool(cli.get("imagenes", True)),
            oscuro=bool(cli.get("oscuro", False)),
        )
        clientes.append(
            {
                "clave": cli.get("clave"),
                "nombre": cli.get("nombre"),
                "ancho": int(cli.get("ancho") or 600),
                "html": m["html"],
            }
        )
    base = montar(composicion, datos)
    salida_clase = salida(db, tenant_id, clase)
    spam = puntuar_spam(
        db,
        asunto=base["asunto"],
        cuerpo_html=base["cuerpo"],
        clase=clase,
        salida_clase=salida_clase,
        sin_dato=base["sin_dato"],
    )
    salida_clase.pop("_config", None)
    return {
        "plantilla": composicion.get("plantilla"),
        "clase": clase,
        "asunto": base["asunto"],
        "sin_dato": base["sin_dato"],
        "bloques_que_faltan": composicion.get("bloques_que_faltan") or [],
        "anadidos_por_obligacion": composicion.get("anadidos_por_obligacion") or [],
        "datos": {k: datos.get(k) for k in ("contacto", "cuenta")},
        "recomendaciones": datos.get("recomendaciones")
        or {"productos": [], "contenidos": [], "porque": aviso_datos},
        "aviso_datos": aviso_datos,
        "clientes": clientes,
        "spam": spam,
        "salida": salida_clase,
    }
