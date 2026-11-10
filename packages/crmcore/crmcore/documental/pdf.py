# Origen: contecweb/app/services/reports/pdf.py @ 2026-11-10, que a su vez sale
# de contecflow PSA/app/services/report_pdf_service.py.
"""Chasis de PDF de la casa: documento, estilos, cabecera, tablas y pie.

Es **el mismo motor** con el que contecweb saca la cotización en PDF, traído y
no reescrito: la cabecera con la regla horizontal, la tabla con la cabecera
oscura y las filas alternas, el pie, y dos decisiones que se conservan tal cual.

**Si `reportlab` no está instalado, se falla en voz alta.** Devolver unos bytes
de relleno entrega un fichero que no abre, y el usuario ve un PDF corrupto en
lugar de un error. Un error se arregla; un PDF corrupto se convierte en «esta
aplicación no funciona».

**Las columnas se declaran, no se dibujan.** `tabla()` recibe columnas con su
alineación y su peso relativo y reparte el ancho útil: añadir una columna no
obliga a recalcular las demás.

Lo que cambia respecto al original, y por qué:

* **La marca y el papel llegan como parámetros**, no de una configuración
  global. En contecweb hay una marca por instalación; aquí cada tenant tiene la
  suya y cada plantilla puede llevar otra (un grupo con tres marcas manda
  ofertas con la que corresponda). Quien llama resuelve la marca —de la
  plantilla, del tenant o de los ajustes— y este módulo sólo pinta.
* **La fecha y los textos fijos también llegan hechos**: el idioma es el de la
  plantilla, no el del servidor, y la marca de tiempo de fuera permite que una
  prueba compare dos PDF.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

try:  # pragma: no cover - depende del entorno, no de la lógica
    from reportlab.lib import colors as _rl_colors
    from reportlab.lib.pagesizes import A4, LETTER, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    REPORTLAB_DISPONIBLE = True
except ImportError:  # pragma: no cover
    REPORTLAB_DISPONIBLE = False

AVISO_INSTALACION = (
    "Generar PDF necesita el paquete «reportlab», que no está instalado en este "
    "servicio. Se instala con requirements.txt"
)


@dataclass(frozen=True)
class Marca:
    """Cómo se ve el documento: nombre y colores.

    Los colores en hexadecimal (`#1F4E79`). Un valor vacío o mal escrito cae al
    del respaldo que se pase al construirla: un color roto no puede impedir que
    salga una oferta.
    """

    nombre: str
    acento: str
    cabecera_tabla: str
    texto: str
    texto_suave: str
    fila_alterna: str
    fila_par: str


@dataclass(frozen=True)
class Columna:
    """Una columna: su título, su peso relativo y cómo se alinea."""

    titulo: str
    peso: float = 1.0
    alinear: str = "LEFT"


def exigir_reportlab() -> None:
    """Falla en voz alta si no se puede generar el PDF.

    Nunca se devuelven bytes de relleno: un fichero que no abre se lee como «la
    aplicación está rota», mientras que un error dice exactamente qué falta.
    """
    if not REPORTLAB_DISPONIBLE:
        from crmcore.errors import NoDisponible

        raise NoDisponible(AVISO_INSTALACION, error_code="pdf.sin_motor")


class DocumentoPdf:
    """Un PDF en construcción. Se le añaden bloques y se cierra con `cerrar()`."""

    def __init__(
        self,
        *,
        marca: Marca,
        papel: str = "A4",
        margen_cm: float = 2.0,
        titulo: str = "",
        idioma: str = "es",
        horizontal: bool = False,
    ) -> None:
        exigir_reportlab()
        self._marca = marca
        self._buffer = io.BytesIO()
        tamano = LETTER if papel.strip().upper() == "LETTER" else A4
        if horizontal:
            tamano = landscape(tamano)
        self._ancho_util = tamano[0] - 2 * margen_cm * cm
        self._doc = SimpleDocTemplate(
            self._buffer,
            pagesize=tamano,
            leftMargin=margen_cm * cm,
            rightMargin=margen_cm * cm,
            topMargin=1.8 * cm,
            bottomMargin=1.6 * cm,
            title=titulo or marca.nombre,
            author=marca.nombre,
            lang=idioma,
        )
        self._estilos = _hoja_de_estilos(marca)
        self._historia: list[Any] = []

    def cabecera(self, titulo: str, subtitulo: str) -> DocumentoPdf:
        """El nombre de la marca, el título y el subtítulo, con la regla debajo."""
        if self._marca.nombre:
            self._historia.append(Paragraph(_escapar(self._marca.nombre), self._estilos["marca"]))
        self._historia.append(Paragraph(_escapar(titulo), self._estilos["titulo"]))
        if subtitulo:
            self._historia.append(Paragraph(_escapar(subtitulo), self._estilos["subtitulo"]))
        self._historia.append(
            HRFlowable(width="100%", thickness=1.5, color=_color(self._marca.acento), spaceAfter=10)
        )
        return self

    def seccion(self, titulo: str) -> DocumentoPdf:
        self._historia.append(Paragraph(_escapar(titulo), self._estilos["seccion"]))
        return self

    def texto(self, cuerpo: str) -> DocumentoPdf:
        """Texto corrido: cada línea en blanco separa un párrafo y cada salto se respeta.

        Es como se escribe una plantilla —en párrafos, con saltos de línea en el
        saludo y en la firma— y perder los saltos convierte «Atentamente,\\nAna»
        en una sola línea que nadie firmaría así.
        """
        for parrafo in cuerpo.replace("\r\n", "\n").split("\n\n"):
            if not parrafo.strip():
                continue
            html = "<br/>".join(_escapar(linea) for linea in parrafo.split("\n"))
            self._historia.append(Paragraph(html, self._estilos["cuerpo"]))
            self._historia.append(Spacer(1, 6))
        return self

    def datos(self, pares: list[tuple[str, str]]) -> DocumentoPdf:
        """Una rejilla de «etiqueta: valor»."""
        if not pares:
            return self
        filas = [
            [
                Paragraph(f"<b>{_escapar(k)}</b>", self._estilos["pequeno"]),
                Paragraph(_escapar(v), self._estilos["pequeno"]),
            ]
            for k, v in pares
        ]
        tabla = Table(filas, colWidths=[self._ancho_util * 0.32, self._ancho_util * 0.68])
        tabla.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.25, _color(self._marca.fila_alterna)),
                ]
            )
        )
        self._historia.append(tabla)
        self._historia.append(Spacer(1, 8))
        return self

    def tabla(self, columnas: list[Columna], filas: list[list[str]], *, vacia: str) -> DocumentoPdf:
        """Una tabla con la cabecera oscura y las filas alternas.

        Sin filas se escribe `vacia`: una tabla con cabecera y nada debajo se lee
        como un fallo, cuando el hecho es que no hay datos.
        """
        if not filas:
            self._historia.append(Paragraph(_escapar(vacia), self._estilos["nota"]))
            return self
        total = sum(c.peso for c in columnas) or 1.0
        anchos = [self._ancho_util * (c.peso / total) for c in columnas]
        cuerpo = [
            [Paragraph(f"<b>{_escapar(c.titulo)}</b>", self._estilos["th"]) for c in columnas]
        ]
        for fila in filas:
            cuerpo.append([Paragraph(_escapar(celda), self._estilos["td"]) for celda in fila])
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), _color(self._marca.cabecera_tabla)),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [_color(self._marca.fila_par), _color(self._marca.fila_alterna)],
            ),
            ("GRID", (0, 0), (-1, -1), 0.35, _rl_colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            # La cabecera se repite en cada página: una tabla partida en cinco
            # páginas sin cabecera son cuatro páginas de números sin nombre.
            ("REPEATROWS", (0, 0), (-1, 0)),
        ]
        for indice, columna in enumerate(columnas):
            if columna.alinear != "LEFT":
                estilo.append(("ALIGN", (indice, 0), (indice, -1), columna.alinear))
        tabla = Table(cuerpo, colWidths=anchos, repeatRows=1)
        tabla.setStyle(TableStyle(estilo))
        self._historia.append(tabla)
        self._historia.append(Spacer(1, 10))
        return self

    def cerrar(self, *, pie: str) -> bytes:
        self._historia.append(Spacer(1, 14))
        self._historia.append(
            HRFlowable(width="100%", thickness=0.5, color=_rl_colors.lightgrey, spaceAfter=4)
        )
        self._historia.append(Paragraph(_escapar(pie), self._estilos["nota"]))
        self._doc.build(self._historia)
        return self._buffer.getvalue()


def _color(hexadecimal: str) -> Any:
    try:
        return _rl_colors.HexColor(hexadecimal)
    except (ValueError, TypeError):
        # Un color mal escrito en la marca no puede impedir que salga el
        # documento; sale en gris y se ve que hay que corregirlo.
        return _rl_colors.grey


def _escapar(valor: str) -> str:
    """Escapa el texto antes de meterlo en un `Paragraph`.

    `Paragraph` interpreta marcado: una descripción con `<` o con `&` rompería
    el documento entero, y un nombre de cliente con etiquetas cambiaría la
    maquetación. Ninguno de los dos es un dato bajo nuestro control.
    """
    return str(valor).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _hoja_de_estilos(marca: Marca) -> dict[str, Any]:
    base = getSampleStyleSheet()
    return {
        "marca": ParagraphStyle(
            "CrmMarca",
            parent=base["Normal"],
            fontSize=9,
            fontName="Helvetica-Bold",
            textColor=_color(marca.acento),
            spaceAfter=4,
        ),
        "titulo": ParagraphStyle(
            "CrmTitulo",
            parent=base["Title"],
            fontSize=18,
            fontName="Helvetica-Bold",
            textColor=_color(marca.texto),
            alignment=0,
            spaceAfter=2,
            leading=22,
        ),
        "subtitulo": ParagraphStyle(
            "CrmSubtitulo",
            parent=base["Normal"],
            fontSize=9,
            textColor=_color(marca.texto_suave),
            spaceAfter=2,
        ),
        "seccion": ParagraphStyle(
            "CrmSeccion",
            parent=base["Normal"],
            fontSize=11,
            fontName="Helvetica-Bold",
            textColor=_color(marca.acento),
            spaceBefore=12,
            spaceAfter=5,
        ),
        "cuerpo": ParagraphStyle(
            "CrmCuerpo",
            parent=base["Normal"],
            fontSize=10,
            textColor=_color(marca.texto),
            leading=14,
        ),
        "pequeno": ParagraphStyle(
            "CrmPequeno",
            parent=base["Normal"],
            fontSize=8.5,
            textColor=_color(marca.texto),
            leading=11,
        ),
        "th": ParagraphStyle(
            "CrmTh", parent=base["Normal"], fontSize=8, textColor=_rl_colors.white, leading=10
        ),
        "td": ParagraphStyle(
            "CrmTd", parent=base["Normal"], fontSize=8, textColor=_color(marca.texto), leading=10
        ),
        "nota": ParagraphStyle(
            "CrmNota", parent=base["Normal"], fontSize=7.5, textColor=_color(marca.texto_suave)
        ),
    }


__all__ = [
    "AVISO_INSTALACION",
    "REPORTLAB_DISPONIBLE",
    "Columna",
    "DocumentoPdf",
    "Marca",
    "exigir_reportlab",
]
