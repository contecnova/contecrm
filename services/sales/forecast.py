"""Previsión de ventas: categorías, jerarquía, ajustes, instantáneas,
*waterfall*, multi-moneda, desglose y cierre de periodo
(CRM-03.02.01.01 a .09, CRM-03.01.01.13).

La previsión es el entregable que más se mira y el que peor envejece. Todo lo
que hay aquí sale de una misma idea: **un número de previsión solo vale si se
puede explicar**. Un total sin desglose no se discute, se cree o no se cree; y
uno que cambia cada vez que se consulta no se puede ni comparar consigo mismo.

De ahí las cuatro decisiones que gobiernan el módulo:

* **Las categorías son datos.** «Pipeline, best case, commit, cerrado» es lo
  habitual, pero hay quien mete «upside» en medio y quien lo llama todo de otra
  manera. Con la lista escrita en el código, cada organización es una versión del
  producto. Lo que sí es del sistema es el *significado* —si cuenta como
  compromiso y si es terminal—, y va en dos banderas explícitas y no deducido del
  nombre, que se rompería en cuanto alguien lo traduzca.
* **Los ajustes del manager son un registro, no una hoja aparte.** Ajustan
  siempre, porque saben cosas que no están en el CRM. El problema nunca fue que
  ajusten: es que después nadie sabe quién quitó doscientos mil euros ni por qué.
* **Las fotos se guardan enteras.** El *waterfall* no se puede reconstruir desde
  el estado de hoy, y hacerlo desde el historial de cambios es caro y frágil.
  Guardar unas cuantas filas por periodo es ridículo comparado con no poder
  explicar por qué se cayó el trimestre.
* **El cambio de moneda es el del día, no el de hoy.** Convertirlo todo al cambio
  actual hace que el histórico de ventas se mueva solo y que dos informes del
  mismo trimestre den números distintos según cuándo se sacaron.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.datos.cambio import convertir
from crmcore.datos.estados import con_significado
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy
from crmcore.logging import get_logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.sales.modelos import (
    AjusteForecast,
    CambioPrevision,
    CategoriaForecast,
    InstantaneaForecast,
    LineaInstantanea,
    LineaOportunidad,
    Oportunidad,
    PeriodoForecast,
)

logger = get_logger(__name__)

CERO = Decimal("0.00")

# Categorías de serie. Se **siembran** en el tenant la primera vez, no se usan
# en duro: sembrar deja que el cliente las renombre, reordene y amplíe; usarlas
# en duro le obliga a vivir con nuestras palabras.
CATEGORIAS_DE_SERIE = (
    {"clave": "pipeline", "nombre": "Pipeline", "orden": 10, "por_defecto": True},
    {"clave": "best_case", "nombre": "Best case", "orden": 20},
    {"clave": "commit", "nombre": "Commit", "orden": 30, "cuenta_como_compromiso": True},
    {
        "clave": "cerrado",
        "nombre": "Cerrado",
        "orden": 40,
        "cuenta_como_compromiso": True,
        "terminal": True,
    },
)


# ── Categorías (CRM-03.02.01.01) ──────────────────────────────────────────


def sembrar_categorias(db: Session, tenant_id: UUID) -> list[CategoriaForecast]:
    """Crea las categorías de serie si el tenant no tiene ninguna."""
    existentes = (
        db.execute(select(CategoriaForecast).where(CategoriaForecast.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    if existentes:
        return list(existentes)
    creadas = []
    for datos in CATEGORIAS_DE_SERIE:
        fila = CategoriaForecast(tenant_id=tenant_id, **datos)
        db.add(fila)
        creadas.append(fila)
    db.flush()
    return creadas


def categorias(db: Session, tenant_id: UUID) -> list[CategoriaForecast]:
    return list(
        db.execute(
            select(CategoriaForecast)
            .where(CategoriaForecast.tenant_id == tenant_id)
            .order_by(CategoriaForecast.orden, CategoriaForecast.clave)
        )
        .scalars()
        .all()
    )


def categoria_por_defecto(db: Session, tenant_id: UUID) -> CategoriaForecast | None:
    todas = categorias(db, tenant_id)
    for fila in todas:
        if fila.por_defecto:
            return fila
    return todas[0] if todas else None


def clasificar(db: Session, oportunidad: Oportunidad, clave: str) -> Oportunidad:
    """Pone la oportunidad en una categoría de previsión.

    Se comprueba que la categoría exista en el tenant. Aceptar cualquier texto
    haría que una errata creara una categoría fantasma que no sale en ningún
    informe y cuyo importe desaparece del total sin que nadie lo eche en falta —
    el peor tipo de error de datos, el que resta en silencio.
    """
    validas = {c.clave for c in categorias(db, oportunidad.tenant_id)}
    if clave not in validas:
        raise ErrorValidacion(
            f"«{clave}» no es una categoría de previsión de este tenant.",
            error_code="forecast.categoria_desconocida",
            detalle={"validas": sorted(validas)},
        )
    oportunidad.categoria_forecast = clave
    return oportunidad


# ── Periodos y su cierre (CRM-03.02.01.09) ────────────────────────────────


def periodo(db: Session, tenant_id: UUID, clave: str) -> PeriodoForecast:
    fila = db.execute(
        select(PeriodoForecast).where(
            PeriodoForecast.tenant_id == tenant_id, PeriodoForecast.clave == clave
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            f"No hay un periodo de previsión «{clave}»", error_code="forecast.periodo_desconocido"
        )
    return fila


def abrir_periodo(
    db: Session, tenant_id: UUID, *, clave: str, desde: date, hasta: date, nombre: str = ""
) -> PeriodoForecast:
    if hasta < desde:
        raise ErrorValidacion(
            "El periodo termina antes de empezar", error_code="forecast.periodo_invalido"
        )
    existente = db.execute(
        select(PeriodoForecast).where(
            PeriodoForecast.tenant_id == tenant_id, PeriodoForecast.clave == clave
        )
    ).scalar_one_or_none()
    if existente is not None:
        raise Conflicto("Ese periodo ya existe", error_code="forecast.periodo_duplicado")
    fila = PeriodoForecast(
        tenant_id=tenant_id, clave=clave, nombre=nombre or clave, desde=desde, hasta=hasta
    )
    db.add(fila)
    db.flush()
    return fila


def cerrar_periodo(
    db: Session, tenant_id: UUID, clave: str, *, por: UUID | None = None
) -> dict[str, Any]:
    """Cierra el periodo y deja una foto final.

    Cerrar es lo que hace que el número signifique algo: mientras está abierto,
    el commit del trimestre cambia cada vez que alguien toca una oportunidad, y
    comparar dos informes de fechas distintas es comparar dos cosas que no son la
    misma. La foto se toma **dentro** del cierre y no se deja para después: un
    cierre sin foto es un número que ya no se puede reconstruir.
    """
    fila = periodo(db, tenant_id, clave)
    if fila.cerrado_at is not None:
        raise Conflicto("Ese periodo ya está cerrado", error_code="forecast.periodo_cerrado")

    foto = tomar_instantanea(db, tenant_id, clave, etiqueta="cierre de periodo", por=por)
    fila.cerrado_at = datetime.now(timezone.utc)
    fila.cerrado_por = por
    registrar(
        db,
        accion="forecast.periodo_cerrado",
        objeto="periodo_forecast",
        objeto_id=fila.id,
        datos={"periodo": clave, "instantanea": str(foto.id), "totales": foto.totales},
        tenant_id=tenant_id,
    )
    return {"periodo": clave, "instantanea_id": str(foto.id), "totales": foto.totales}


def reabrir_periodo(
    db: Session, tenant_id: UUID, clave: str, *, motivo: str, por: UUID | None = None
) -> PeriodoForecast:
    """Reabrir es un acto explícito, motivado y contado.

    Si fuera gratis, «cerrado» dejaría de significar nada: el número volvería a
    moverse y la comparación entre periodos perdería su base. El contador de
    reaperturas está para que se vea cuántas veces ha pasado, que es la señal de
    que el proceso de cierre no se está respetando.
    """
    if not (motivo or "").strip():
        raise ErrorValidacion(
            "Reabrir un periodo cerrado exige un motivo escrito.",
            error_code="forecast.reapertura_sin_motivo",
        )
    fila = periodo(db, tenant_id, clave)
    if fila.cerrado_at is None:
        raise Conflicto("Ese periodo no está cerrado", error_code="forecast.periodo_abierto")
    fila.cerrado_at = None
    fila.cerrado_por = None
    fila.reaperturas += 1
    fila.motivo_reapertura = motivo
    registrar(
        db,
        accion="forecast.periodo_reabierto",
        objeto="periodo_forecast",
        objeto_id=fila.id,
        datos={
            "periodo": clave,
            "motivo": motivo,
            "reaperturas": fila.reaperturas,
            "por": str(por),
        },
        tenant_id=tenant_id,
    )
    return fila


def exigir_periodo_abierto(db: Session, tenant_id: UUID, en_fecha: date | None) -> None:
    """Impide tocar una oportunidad cuyo cierre cae en un periodo cerrado.

    Sin esto, cerrar el periodo sería un gesto decorativo: el número queda
    fotografiado pero las oportunidades siguen moviéndose, y al trimestre
    siguiente nadie entiende por qué la foto no cuadra con el detalle.
    """
    if en_fecha is None:
        return
    cerrado = db.execute(
        select(PeriodoForecast).where(
            PeriodoForecast.tenant_id == tenant_id,
            PeriodoForecast.desde <= en_fecha,
            PeriodoForecast.hasta >= en_fecha,
            PeriodoForecast.cerrado_at.isnot(None),
        )
    ).scalar_one_or_none()
    if cerrado is not None:
        raise Conflicto(
            f"El periodo «{cerrado.clave}» está cerrado: su previsión ya está en un "
            "informe que alguien ha mirado.",
            error_code="forecast.periodo_cerrado",
            detalle={"periodo": cerrado.clave},
        )


# ── El cálculo (CRM-03.02.01.01, .02, .07, .08) ───────────────────────────


@dataclass(slots=True)
class Total:
    importe: Decimal = CERO
    ponderado: Decimal = CERO
    oportunidades: int = 0


@dataclass(slots=True)
class Previsión:
    periodo: str
    moneda: str
    por_categoria: dict[str, Total] = field(default_factory=dict)
    compromiso: Decimal = CERO
    total: Decimal = CERO
    ponderado: Decimal = CERO
    oportunidades: int = 0
    # Lo que NO se ha podido convertir. Se saca aparte en vez de contarlo como
    # cero: un total al que le faltan importes en silencio es peor que uno que
    # avisa, porque nadie lo cuestiona.
    sin_tipo_de_cambio: list[str] = field(default_factory=list)


def _cerradas_sin_ganar(db: Session) -> frozenset[str]:
    """Los estados de las oportunidades que ya no suman a la previsión.

    Una oportunidad perdida o cancelada no es ingreso del periodo, por mucho que
    su fecha de cierre caiga dentro y su categoría siga diciendo «commit»:
    `_cerrar` baja la probabilidad a cero, pero no toca la categoría —que es la
    opinión del comercial y se conserva tal cual por si se reabre—, así que el
    total y el compromiso la seguían sumando (auditoría FUN-B-1, 13-11-2026).

    Las **ganadas sí siguen**: son justo lo que el periodo ha ingresado, y
    quitarlas haría que la previsión bajara cada vez que se gana algo.

    Por significado y no por nombre, con la máquina de la empresa: una que llame
    «Desierta» a su cancelada, o que añada otro estado que signifique «perdido»,
    sale igual. Es la misma frontera que usa el *waterfall* para separar lo
    perdido del resto.
    """
    return con_significado("oportunidad", "perdido", db) | con_significado(
        "oportunidad", "cancelado", db
    )


def _moneda_funcional(db: Session) -> str:
    from crmcore.runtime import settings as rt

    return str(rt.efectivo("moneda_funcional", db) or "EUR")


def _importe_funcional(
    db: Session, oportunidad: Oportunidad, moneda: str, fallidas: list[str]
) -> Decimal:
    """El importe en la moneda del informe, con el cambio **del día de cierre**.

    Y no el de hoy: una oportunidad cerrada en marzo tiene que seguir valiendo lo
    que valía en marzo. Con el cambio de hoy, el histórico de ventas se mueve
    solo y el mismo trimestre da números distintos según cuándo se consulte.
    """
    if (oportunidad.moneda or moneda) == moneda:
        return oportunidad.importe or CERO
    try:
        return convertir(
            db,
            tenant_id=oportunidad.tenant_id,
            importe=oportunidad.importe or CERO,
            desde=oportunidad.moneda,
            hasta=moneda,
            en_fecha=oportunidad.fecha_cierre or hoy(db),
        )
    except NoEncontrado:
        fallidas.append(str(oportunidad.id))
        return CERO


def calcular(
    db: Session,
    tenant_id: UUID,
    *,
    periodo_clave: str,
    owners: list[UUID] | None = None,
    moneda: str | None = None,
) -> Previsión:
    """La previsión del periodo, por categoría.

    `owners` acota a un comercial o a los de un equipo. La jerarquía se resuelve
    **fuera** (ver `previsión_por_jerarquía`): `sales` no conoce el organigrama
    —vive en `identity`— y montarlo aquí sería leer el esquema de otro servicio.

    Suma lo abierto y lo ganado; lo perdido y lo cancelado no (ver
    `_cerradas_sin_ganar`).
    """
    per = periodo(db, tenant_id, periodo_clave)
    moneda = (moneda or _moneda_funcional(db)).upper()

    consulta = select(Oportunidad).where(
        Oportunidad.tenant_id == tenant_id,
        Oportunidad.fecha_cierre >= per.desde,
        Oportunidad.fecha_cierre <= per.hasta,
        Oportunidad.deleted_at.is_(None),
        Oportunidad.estado.not_in(_cerradas_sin_ganar(db)),
    )
    if owners:
        consulta = consulta.where(Oportunidad.owner_id.in_(owners))

    por_clave = {c.clave: c for c in categorias(db, tenant_id)}
    defecto = categoria_por_defecto(db, tenant_id)
    salida = Previsión(periodo=periodo_clave, moneda=moneda)
    fallidas: list[str] = []

    for oportunidad in db.execute(consulta).scalars():
        clave = oportunidad.categoria_forecast or (defecto.clave if defecto else "pipeline")
        total = salida.por_categoria.setdefault(clave, Total())
        importe = _importe_funcional(db, oportunidad, moneda, fallidas)
        ponderado = (importe * Decimal(oportunidad.probabilidad or 0) / Decimal(100)).quantize(
            Decimal("0.01")
        )

        total.importe += importe
        total.ponderado += ponderado
        total.oportunidades += 1
        salida.total += importe
        salida.ponderado += ponderado
        salida.oportunidades += 1
        categoria = por_clave.get(clave)
        if categoria is not None and categoria.cuenta_como_compromiso:
            salida.compromiso += importe

    salida.sin_tipo_de_cambio = fallidas
    return salida


def a_dict(previsión: Previsión) -> dict[str, Any]:
    return {
        "periodo": previsión.periodo,
        "moneda": previsión.moneda,
        "total": str(previsión.total),
        "ponderado": str(previsión.ponderado),
        "compromiso": str(previsión.compromiso),
        "oportunidades": previsión.oportunidades,
        "por_categoria": {
            clave: {
                "importe": str(t.importe),
                "ponderado": str(t.ponderado),
                "oportunidades": t.oportunidades,
            }
            for clave, t in sorted(previsión.por_categoria.items())
        },
        "sin_tipo_de_cambio": previsión.sin_tipo_de_cambio,
        # Se dice en la respuesta, no solo en un campo que nadie mira: un total
        # con importes perdidos tiene que llevar el aviso pegado al número.
        "aviso": (
            f"{len(previsión.sin_tipo_de_cambio)} oportunidades no se han podido "
            f"convertir a {previsión.moneda} y NO están sumadas"
            if previsión.sin_tipo_de_cambio
            else ""
        ),
    }


def previsión_por_jerarquía(
    db: Session,
    tenant_id: UUID,
    *,
    periodo_clave: str,
    jerarquía: dict[str, list[UUID]],
    moneda: str | None = None,
) -> dict[str, Any]:
    """Previsión por nivel: comercial, equipo, región, compañía
    (CRM-03.02.01.02).

    `jerarquía` llega ya resuelta —`{"nodo": [owner_ids]}`— porque el organigrama
    vive en `identity` y ningún servicio lee el esquema de otro. Pasarla resuelta
    tiene además la ventaja de que la misma función sirve para agrupar por
    territorio, por canal o por lo que el cliente use, sin tocar nada.

    El total de la compañía se calcula **aparte** y no sumando los nodos: una
    oportunidad cuyo dueño no esté en ninguna rama —alguien recién incorporado,
    o un registro huérfano tras una baja— desaparecería de la suma sin que nadie
    lo notara, y el agujero se descubre al final del trimestre.
    """
    nodos = {
        nombre: a_dict(
            calcular(db, tenant_id, periodo_clave=periodo_clave, owners=owners, moneda=moneda)
        )
        for nombre, owners in jerarquía.items()
    }
    global_ = calcular(db, tenant_id, periodo_clave=periodo_clave, moneda=moneda)
    suma_nodos = sum(Decimal(n["total"]) for n in nodos.values()) if nodos else CERO
    return {
        "periodo": periodo_clave,
        "nodos": nodos,
        "compañía": a_dict(global_),
        "sin_asignar": str(global_.total - suma_nodos),
        # Si la resta no es cero hay oportunidades fuera del organigrama. No es
        # un error, pero tiene que verse: es el agujero que explica por qué la
        # suma de los equipos no cuadra con el total.
        "cuadra": global_.total == suma_nodos,
    }


def previsión_por_organigrama(
    db: Session,
    tenant_id: UUID,
    *,
    periodo_clave: str,
    fuente: str = "territorios",
    moneda: str | None = None,
) -> dict[str, Any]:
    """La previsión por jerarquía con el organigrama **resuelto aquí**
    (CRM-03.02.01.02).

    `previsión_por_jerarquía` pide los nodos ya resueltos —qué comerciales hay
    en cada uno—, y nadie los tenía: la pantalla habría tenido que pedir
    identificadores a mano. Pero `sales` sí tiene las dos formas en que una
    empresa agrupa a sus comerciales, sin leer el esquema de nadie:

    * `territorios`: el mapa de territorios de ventas, que es suyo. Un
      territorio sin hijos es un **equipo**; uno con hijos, una **región**.
    * `mando`: la jerarquía de mando que `identity` publica por evento y este
      servicio replica (`crmcore.authz.jerarquia`). Quien tiene a otros a su
      cargo es jefe de **equipo**; quien tiene jefes a su cargo, de **región**.

    Cada nodo suma lo de **todos** los comerciales que cuelgan de él, y el total
    de la compañía se calcula aparte: lo que no cuelga de ninguna rama sale
    como «fuera del organigrama» con su importe y sus dueños, que es el agujero
    que explica por qué las ramas no suman el total.
    """
    from crmcore.authz.jerarquia import MandoReplicado, frescura

    from services.sales.territorios import MiembroTerritorio, Territorio

    if fuente not in ("territorios", "mando"):
        raise ErrorValidacion(
            f"No se sabe agrupar por «{fuente}»",
            error_code="forecast.fuente_desconocida",
            detalle={"validas": ["territorios", "mando"]},
        )

    hijos: dict[str, list[str]] = {}
    datos_nodo: dict[str, dict[str, Any]] = {}
    miembros: dict[str, set[UUID]] = {}
    aviso = ""

    if fuente == "territorios":
        territorios = (
            db.execute(
                select(Territorio).where(
                    Territorio.tenant_id == tenant_id,
                    Territorio.deleted_at.is_(None),
                    Territorio.activo.is_(True),
                )
            )
            .scalars()
            .all()
        )
        ids = {str(t.id) for t in territorios}
        for t in territorios:
            clave = str(t.id)
            datos_nodo[clave] = {"id": clave, "nombre": t.nombre, "usuario_id": None}
            padre = str(t.padre_id) if t.padre_id and str(t.padre_id) in ids else ""
            hijos.setdefault(padre, []).append(clave)
            # El responsable del territorio cuenta como suyo: es el dueño del
            # trozo de mercado, y un mapa que lo dejara fuera sacaría sus
            # ventas del árbol en cuanto no estuviera además como miembro.
            miembros[clave] = {t.responsable_id} if t.responsable_id else set()
        for m in db.execute(
            select(MiembroTerritorio).where(MiembroTerritorio.tenant_id == tenant_id)
        ).scalars():
            if str(m.territorio_id) in miembros:
                miembros[str(m.territorio_id)].add(m.usuario_id)
        if not territorios:
            aviso = "No hay territorios activos: el desglose sale por comercial."
    else:
        filas = (
            db.execute(select(MandoReplicado).where(MandoReplicado.tenant_id == tenant_id))
            .scalars()
            .all()
        )
        personas = {str(f.usuario_id) for f in filas}
        for f in filas:
            clave = str(f.usuario_id)
            datos_nodo[clave] = {"id": clave, "nombre": "", "usuario_id": clave}
            superior = str(f.superior_id) if f.superior_id else ""
            if superior and superior not in personas:
                # El jefe no consta en la réplica: se le pone igual, como raíz,
                # para no perder la rama entera.
                personas.add(superior)
                datos_nodo[superior] = {"id": superior, "nombre": "", "usuario_id": superior}
                hijos.setdefault("", []).append(superior)
                miembros[superior] = {UUID(superior)}
            hijos.setdefault(superior, []).append(clave)
            miembros[clave] = {f.usuario_id}
        estado = frescura(db, tenant_id)
        if estado.get("vacia"):
            aviso = str(estado.get("que_significa") or "")

    # Lo de cada nodo es lo suyo más lo de todo lo que cuelga, sin ciclos.
    def bajo(clave: str, vistos: frozenset[str] = frozenset()) -> set[UUID]:
        if clave in vistos:
            return set()
        todos = set(miembros.get(clave, set()))
        for hijo in hijos.get(clave, []):
            todos |= bajo(hijo, vistos | {clave})
        return todos

    # Los dueños con oportunidades en el periodo, para la rama «por comercial» y
    # para saber quién queda fuera. Con el mismo filtro que `calcular`: quien
    # solo tiene perdidas no tiene nada en la previsión, y sacarlo «fuera del
    # organigrama» con un cero sería un agujero que no existe.
    per = periodo(db, tenant_id, periodo_clave)
    con_ventas = {
        o
        for o in db.execute(
            select(Oportunidad.owner_id)
            .where(
                Oportunidad.tenant_id == tenant_id,
                Oportunidad.fecha_cierre >= per.desde,
                Oportunidad.fecha_cierre <= per.hasta,
                Oportunidad.deleted_at.is_(None),
                Oportunidad.estado.not_in(_cerradas_sin_ganar(db)),
                Oportunidad.owner_id.is_not(None),
            )
            .distinct()
        ).scalars()
    }

    def resumen(owners: set[UUID]) -> dict[str, Any]:
        if not owners:
            vacio = a_dict(Previsión(periodo=periodo_clave, moneda=(moneda or "").upper()))
            return {k: vacio[k] for k in ("total", "ponderado", "compromiso", "oportunidades")}
        calculado = a_dict(
            calcular(
                db, tenant_id, periodo_clave=periodo_clave, owners=sorted(owners), moneda=moneda
            )
        )
        return {k: calculado[k] for k in ("total", "ponderado", "compromiso", "oportunidades")}

    def montar(clave: str, profundidad: int, vistos: frozenset[str]) -> dict[str, Any]:
        sub = [
            montar(h, profundidad + 1, vistos | {clave})
            for h in hijos.get(clave, [])
            if h not in vistos
        ]
        if fuente == "territorios":
            # Los comerciales del territorio van debajo, como hojas.
            sub += [
                {
                    "id": f"{clave}:{u}",
                    "nombre": "",
                    "usuario_id": str(u),
                    "nivel": "comercial",
                    **resumen({u}),
                    "hijos": [],
                }
                for u in sorted(miembros.get(clave, set()), key=str)
            ]
        altura = 1 + max((_altura(n) for n in sub), default=-1)
        if fuente == "territorios":
            # Un territorio es como poco un equipo, aunque hoy no tenga a nadie.
            altura = max(altura, 1)
        nivel = (
            "comercial"
            if altura == 0
            else "equipo"
            if altura == 1
            else "region"
            if altura == 2
            else "direccion"
        )
        return {**datos_nodo[clave], "nivel": nivel, **resumen(bajo(clave)), "hijos": sub}

    raices = [montar(c, 0, frozenset()) for c in hijos.get("", [])]
    en_el_organigrama: set[UUID] = set()
    for c in hijos.get("", []):
        en_el_organigrama |= bajo(c)

    global_ = calcular(db, tenant_id, periodo_clave=periodo_clave, moneda=moneda)
    fuera = sorted(con_ventas - en_el_organigrama, key=str)
    dentro_total = Decimal(resumen(en_el_organigrama)["total"]) if en_el_organigrama else CERO
    de_fuera = [{"usuario_id": str(u), **resumen({u})} for u in fuera]
    # Lo que no es de nadie: oportunidades sin dueño. Sin esta línea, la lista
    # de «fuera» no sumaba el agujero y parecía que faltaba dinero.
    sin_dueno = global_.total - dentro_total - sum((Decimal(f["total"]) for f in de_fuera), CERO)
    return {
        "periodo": periodo_clave,
        "fuente": fuente,
        "moneda": global_.moneda,
        "compania": a_dict(global_),
        "nodos": raices,
        "fuera_del_organigrama": de_fuera,
        "sin_dueno": str(sin_dueno),
        "sin_asignar": str(global_.total - dentro_total),
        "cuadra": global_.total == dentro_total,
        "aviso": aviso,
    }


def _altura(nodo: dict[str, Any]) -> int:
    return 1 + max((_altura(h) for h in nodo.get("hijos", [])), default=-1)


def desglose(
    db: Session,
    tenant_id: UUID,
    *,
    periodo_clave: str,
    por: str = "familia",
    moneda: str | None = None,
) -> dict[str, Any]:
    """Previsión por producto, familia o tipo de ingreso (CRM-03.02.01.08).

    Se calcula sobre las **líneas** y no sobre la cabecera, que es lo único que
    permite que una oportunidad con software y servicios cuente en las dos
    familias por su parte correspondiente. Repartir la cabecera a ojo daría un
    desglose que suma bien y reparte mal, que es peor que no tenerlo.
    """
    campos = {
        "familia": LineaOportunidad.familia,
        "tipo_ingreso": LineaOportunidad.tipo_ingreso,
        "producto": LineaOportunidad.producto_id,
    }
    if por not in campos:
        raise ErrorValidacion(
            f"No se puede desglosar por «{por}».",
            error_code="forecast.desglose_no_soportado",
            detalle={"validos": sorted(campos)},
        )

    per = periodo(db, tenant_id, periodo_clave)
    moneda = (moneda or _moneda_funcional(db)).upper()
    columna = campos[por]

    filas = db.execute(
        select(
            columna,
            Oportunidad.moneda,
            Oportunidad.fecha_cierre,
            Oportunidad.probabilidad,
            func.sum(LineaOportunidad.total),
            func.count(),
        )
        .join(Oportunidad, Oportunidad.id == LineaOportunidad.oportunidad_id)
        .where(
            Oportunidad.tenant_id == tenant_id,
            Oportunidad.fecha_cierre >= per.desde,
            Oportunidad.fecha_cierre <= per.hasta,
            Oportunidad.deleted_at.is_(None),
            # Lo mismo que suma `calcular`: si no, el desglose de una previsión
            # no cuadra con ella.
            Oportunidad.estado.not_in(_cerradas_sin_ganar(db)),
        )
        .group_by(columna, Oportunidad.moneda, Oportunidad.fecha_cierre, Oportunidad.probabilidad)
    ).all()

    agrupado: dict[str, dict[str, Any]] = {}
    sin_cambio = 0
    for valor, moneda_op, fecha, probabilidad, suma, cuantas in filas:
        clave = str(valor) if valor is not None else "(sin asignar)"
        entrada = agrupado.setdefault(clave, {"importe": CERO, "ponderado": CERO, "lineas": 0})
        importe = Decimal(suma or 0)
        if (moneda_op or moneda) != moneda:
            try:
                importe = convertir(
                    db,
                    tenant_id=tenant_id,
                    importe=importe,
                    desde=moneda_op,
                    hasta=moneda,
                    en_fecha=fecha or hoy(db),
                )
            except NoEncontrado:
                sin_cambio += 1
                continue
        entrada["importe"] += importe
        entrada["ponderado"] += (importe * Decimal(probabilidad or 0) / Decimal(100)).quantize(
            Decimal("0.01")
        )
        entrada["lineas"] += int(cuantas)

    return {
        "periodo": periodo_clave,
        "por": por,
        "moneda": moneda,
        "grupos": {
            clave: {
                "importe": str(v["importe"]),
                "ponderado": str(v["ponderado"]),
                "lineas": v["lineas"],
            }
            for clave, v in sorted(agrupado.items())
        },
        "grupos_sin_tipo_de_cambio": sin_cambio,
    }


# ── Ajustes del responsable (CRM-03.02.01.03) ─────────────────────────────


def ajustar(
    db: Session,
    tenant_id: UUID,
    *,
    periodo_clave: str,
    categoria: str,
    importe_ajustado: Decimal,
    importe_bruto: Decimal,
    motivo: str,
    ambito: str = "usuario",
    ambito_id: UUID | None = None,
    por: UUID | None = None,
    moneda: str = "EUR",
) -> AjusteForecast:
    """Registra el ajuste de un responsable sobre el número calculado.

    El motivo es **obligatorio**. Un ajuste sin motivo es exactamente el problema
    que esto viene a resolver: el número cambia, nadie sabe por qué, y al
    trimestre siguiente la discusión empieza de cero.

    Se guarda el bruto junto al ajustado porque sin él no se puede medir si los
    ajustes de alguien acertaron, que es la única forma de saber si conviene
    hacerle caso la próxima vez.
    """
    if not (motivo or "").strip():
        raise ErrorValidacion(
            "Un ajuste de previsión exige un motivo escrito.",
            error_code="forecast.ajuste_sin_motivo",
        )
    per = periodo(db, tenant_id, periodo_clave)
    if per.cerrado_at is not None:
        raise Conflicto(
            "El periodo está cerrado: su número ya está en un informe.",
            error_code="forecast.periodo_cerrado",
        )

    fila = db.execute(
        select(AjusteForecast).where(
            AjusteForecast.tenant_id == tenant_id,
            AjusteForecast.periodo == periodo_clave,
            AjusteForecast.ambito == ambito,
            AjusteForecast.ambito_id == ambito_id,
            AjusteForecast.categoria == categoria,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = AjusteForecast(
            tenant_id=tenant_id,
            periodo=periodo_clave,
            ambito=ambito,
            ambito_id=ambito_id,
            categoria=categoria,
        )
        db.add(fila)

    fila.importe_bruto = importe_bruto
    fila.importe_ajustado = importe_ajustado
    fila.moneda = moneda
    fila.motivo = motivo
    fila.por = por
    db.flush()

    registrar(
        db,
        accion="forecast.ajustado",
        objeto="ajuste_forecast",
        objeto_id=fila.id,
        datos={
            "periodo": periodo_clave,
            "ambito": ambito,
            "categoria": categoria,
            "bruto": str(importe_bruto),
            "ajustado": str(importe_ajustado),
            "delta": str(importe_ajustado - importe_bruto),
            "motivo": motivo,
        },
        tenant_id=tenant_id,
    )
    return fila


def ajustes_de(db: Session, tenant_id: UUID, periodo_clave: str) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(AjusteForecast)
            .where(AjusteForecast.tenant_id == tenant_id, AjusteForecast.periodo == periodo_clave)
            .order_by(AjusteForecast.ambito, AjusteForecast.categoria)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "ambito": f.ambito,
            "ambito_id": str(f.ambito_id) if f.ambito_id else None,
            "categoria": f.categoria,
            "bruto": str(f.importe_bruto),
            "ajustado": str(f.importe_ajustado),
            "delta": str(f.importe_ajustado - f.importe_bruto),
            "motivo": f.motivo,
            "por": str(f.por) if f.por else None,
            "at": f.updated_at.isoformat() if f.updated_at else None,
        }
        for f in filas
    ]


def acierto_de_los_ajustes(db: Session, tenant_id: UUID, periodo_clave: str) -> dict[str, Any]:
    """Si los ajustes acercaron o alejaron del número real.

    Es la pregunta que nadie se hace y que decide si los ajustes sirven. Se
    compara contra lo **cerrado ganado** del periodo, y si no hay nada cerrado se
    dice que no es medible en vez de devolver un cero que parecería un acierto
    perfecto.
    """
    per = periodo(db, tenant_id, periodo_clave)
    real = Decimal(
        db.execute(
            select(func.coalesce(func.sum(Oportunidad.importe), 0)).where(
                Oportunidad.tenant_id == tenant_id,
                # Lo GANADO, se llame como se llame en esta empresa.
                Oportunidad.estado.in_(con_significado("oportunidad", "ganado", db)),
                Oportunidad.fecha_cierre >= per.desde,
                Oportunidad.fecha_cierre <= per.hasta,
            )
        ).scalar_one()
        or 0
    )
    filas = ajustes_de(db, tenant_id, periodo_clave)
    if not filas or real == 0:
        return {"medible": False, "motivo": "no hay ajustes o no hay nada cerrado todavía"}

    bruto = sum(Decimal(f["bruto"]) for f in filas)
    ajustado = sum(Decimal(f["ajustado"]) for f in filas)
    return {
        "medible": True,
        "real": str(real),
        "bruto": str(bruto),
        "ajustado": str(ajustado),
        "error_sin_ajuste": str(abs(bruto - real)),
        "error_con_ajuste": str(abs(ajustado - real)),
        "el_ajuste_acerto": abs(ajustado - real) < abs(bruto - real),
    }


# ── Instantáneas y waterfall (CRM-03.02.01.04, .05) ───────────────────────


def tomar_instantanea(
    db: Session,
    tenant_id: UUID,
    periodo_clave: str,
    *,
    etiqueta: str = "",
    por: UUID | None = None,
    moneda: str | None = None,
) -> InstantaneaForecast:
    """Congela el estado de la previsión del periodo."""
    per = periodo(db, tenant_id, periodo_clave)
    moneda = (moneda or _moneda_funcional(db)).upper()

    foto = InstantaneaForecast(
        tenant_id=tenant_id,
        periodo=periodo_clave,
        etiqueta=etiqueta or hoy(db).isoformat(),
        tomada_por=por,
        moneda=moneda,
    )
    db.add(foto)
    db.flush()

    defecto = categoria_por_defecto(db, tenant_id)
    totales: dict[str, str] = {}
    cuantas = 0
    fallidas: list[str] = []
    fuera = _cerradas_sin_ganar(db)

    for oportunidad in db.execute(
        select(Oportunidad).where(
            Oportunidad.tenant_id == tenant_id,
            Oportunidad.fecha_cierre >= per.desde,
            Oportunidad.fecha_cierre <= per.hasta,
            Oportunidad.deleted_at.is_(None),
        )
    ).scalars():
        clave = oportunidad.categoria_forecast or (defecto.clave if defecto else "pipeline")
        no_suma = oportunidad.estado in fuera
        # La que no suma tampoco avisa de que le falta el cambio: el aviso es de
        # importes que faltan en el total, y esta no iba a estar.
        funcional = _importe_funcional(db, oportunidad, moneda, [] if no_suma else fallidas)
        db.add(
            LineaInstantanea(
                tenant_id=tenant_id,
                instantanea_id=foto.id,
                oportunidad_id=oportunidad.id,
                nombre=oportunidad.nombre[:300],
                categoria=clave,
                etapa_id=oportunidad.etapa_id,
                owner_id=oportunidad.owner_id,
                importe=oportunidad.importe or CERO,
                importe_funcional=funcional,
                moneda=oportunidad.moneda,
                probabilidad=oportunidad.probabilidad or 0,
                fecha_cierre=oportunidad.fecha_cierre,
                estado=oportunidad.estado,
            )
        )
        # La línea de una perdida se guarda —el *waterfall* la necesita para
        # contarla como «perdida» y no como «salida»—, pero no suma: los
        # totales de la foto tienen que ser los de `calcular` en ese momento.
        if no_suma:
            continue
        totales[clave] = str(Decimal(totales.get(clave, "0")) + funcional)
        cuantas += 1

    foto.totales = totales
    foto.oportunidades = cuantas
    if fallidas:
        # La foto lo dice: una instantánea con importes a cero por falta de
        # cambio parecería una caída del pipeline en el waterfall siguiente.
        foto.totales["_sin_tipo_de_cambio"] = str(len(fallidas))
    db.flush()
    return foto


def instantaneas(db: Session, tenant_id: UUID, periodo_clave: str) -> list[InstantaneaForecast]:
    return list(
        db.execute(
            select(InstantaneaForecast)
            .where(
                InstantaneaForecast.tenant_id == tenant_id,
                InstantaneaForecast.periodo == periodo_clave,
            )
            .order_by(InstantaneaForecast.tomada_at)
        )
        .scalars()
        .all()
    )


def waterfall(db: Session, tenant_id: UUID, desde_id: UUID, hasta_id: UUID) -> dict[str, Any]:
    """Qué ha cambiado entre dos fotos, descompuesto (CRM-03.02.01.05).

    La diferencia entre dos totales no explica nada: «hemos bajado 300.000» no
    dice si es porque se ha perdido una operación grande, porque tres se han ido
    al trimestre siguiente o porque han bajado los importes. Las cinco causas se
    separan porque cada una lleva a una conversación distinta, y mezclarlas es
    exactamente lo que hace que la reunión de previsión no sirva.
    """
    foto_a = db.get(InstantaneaForecast, desde_id)
    foto_b = db.get(InstantaneaForecast, hasta_id)
    if foto_a is None or foto_b is None:
        raise NoEncontrado("Instantánea no encontrada", error_code="forecast.instantanea_no_existe")
    if foto_a.tenant_id != tenant_id or foto_b.tenant_id != tenant_id:
        raise NoEncontrado("Instantánea no encontrada", error_code="forecast.instantanea_no_existe")
    if foto_a.moneda != foto_b.moneda:
        # Restar euros de dólares daría un waterfall precioso y falso.
        raise ErrorValidacion(
            "Las dos instantáneas están en monedas distintas y no se pueden comparar.",
            error_code="forecast.monedas_distintas",
            detalle={"desde": foto_a.moneda, "hasta": foto_b.moneda},
        )

    def _lineas(foto: InstantaneaForecast) -> dict[UUID, LineaInstantanea]:
        filas = (
            db.execute(select(LineaInstantanea).where(LineaInstantanea.instantanea_id == foto.id))
            .scalars()
            .all()
        )
        return {f.oportunidad_id: f for f in filas}

    antes, despues = _lineas(foto_a), _lineas(foto_b)

    entradas: list[dict[str, Any]] = []
    salidas: list[dict[str, Any]] = []
    ganadas: list[dict[str, Any]] = []
    perdidas: list[dict[str, Any]] = []
    deslizadas: list[dict[str, Any]] = []
    variacion: list[dict[str, Any]] = []

    ganado = con_significado("oportunidad", "ganado", db)
    cerrado_sin_ganar = _cerradas_sin_ganar(db)

    for op_id, fila in despues.items():
        previa = antes.get(op_id)
        # Entra lo que pasa a sumar: lo nuevo en la foto y lo que se reabre. Lo
        # que aparece ya perdido no ha entrado en ningún total, y contarlo como
        # entrada inflaría el pipeline nuevo con dinero que no está.
        nueva_que_suma = previa is None and fila.estado not in cerrado_sin_ganar
        reabierta = (
            previa is not None
            and previa.estado in cerrado_sin_ganar
            and fila.estado not in cerrado_sin_ganar
        )
        if nueva_que_suma or reabierta:
            entradas.append(
                {
                    "oportunidad_id": str(op_id),
                    "nombre": fila.nombre,
                    "importe": str(fila.importe_funcional),
                }
            )
        if previa is None or reabierta:
            continue
        if previa.estado in cerrado_sin_ganar and fila.estado in cerrado_sin_ganar:
            # Perdida en las dos fotos: no estaba en ningún total, así que lo que
            # le pase a su importe o a su fecha no explica ninguna variación.
            continue
        if fila.estado in ganado and previa.estado not in ganado:
            ganadas.append(
                {
                    "oportunidad_id": str(op_id),
                    "nombre": fila.nombre,
                    "importe": str(fila.importe_funcional),
                }
            )
        elif fila.estado in cerrado_sin_ganar and previa.estado not in cerrado_sin_ganar:
            perdidas.append(
                {
                    "oportunidad_id": str(op_id),
                    "nombre": fila.nombre,
                    "importe": str(previa.importe_funcional),
                }
            )
            # Sale entera por «perdidas», con lo que valía en la foto anterior;
            # contarle además el cambio de importe restaría dos veces.
            continue
        if fila.fecha_cierre != previa.fecha_cierre and fila.fecha_cierre and previa.fecha_cierre:
            deslizadas.append(
                {
                    "oportunidad_id": str(op_id),
                    "nombre": fila.nombre,
                    "dias": (fila.fecha_cierre - previa.fecha_cierre).days,
                    "importe": str(fila.importe_funcional),
                }
            )
        if fila.importe_funcional != previa.importe_funcional:
            variacion.append(
                {
                    "oportunidad_id": str(op_id),
                    "nombre": fila.nombre,
                    "delta": str(fila.importe_funcional - previa.importe_funcional),
                }
            )

    for op_id, previa in antes.items():
        # La que ya estaba perdida no estaba en el total: que deje la foto no
        # resta nada.
        if op_id not in despues and previa.estado not in cerrado_sin_ganar:
            # Salir de la foto no es lo mismo que perderse: puede haberse ido a
            # otro trimestre o haberla borrado alguien. Mezclarlo con «perdida»
            # inflaría la tasa de pérdida y llevaría a revisar un problema que no
            # existe.
            salidas.append(
                {
                    "oportunidad_id": str(op_id),
                    "nombre": previa.nombre,
                    "importe": str(previa.importe_funcional),
                }
            )

    def _suma(filas: list[dict[str, Any]], campo: str = "importe") -> str:
        return str(sum(Decimal(f[campo]) for f in filas) if filas else CERO)

    total_a = sum(Decimal(v) for k, v in (foto_a.totales or {}).items() if not k.startswith("_"))
    total_b = sum(Decimal(v) for k, v in (foto_b.totales or {}).items() if not k.startswith("_"))

    return {
        "desde": {"id": str(foto_a.id), "etiqueta": foto_a.etiqueta, "total": str(total_a)},
        "hasta": {"id": str(foto_b.id), "etiqueta": foto_b.etiqueta, "total": str(total_b)},
        "moneda": foto_a.moneda,
        "variacion_total": str(total_b - total_a),
        "entradas": {"cuantas": len(entradas), "importe": _suma(entradas), "detalle": entradas},
        "salidas": {"cuantas": len(salidas), "importe": _suma(salidas), "detalle": salidas},
        "ganadas": {"cuantas": len(ganadas), "importe": _suma(ganadas), "detalle": ganadas},
        "perdidas": {"cuantas": len(perdidas), "importe": _suma(perdidas), "detalle": perdidas},
        "deslizadas": {"cuantas": len(deslizadas), "detalle": deslizadas},
        "variacion_de_importe": {
            "cuantas": len(variacion),
            "delta": _suma(variacion, "delta"),
            "detalle": variacion,
        },
    }


# ── Deslizamiento (CRM-03.01.01.13) ───────────────────────────────────────


def anotar_cambio_de_prevision(
    db: Session,
    oportunidad: Oportunidad,
    *,
    importe_antes: Decimal | None,
    fecha_antes: date | None,
    motivo: str = "",
) -> list[CambioPrevision]:
    """Deja constancia de un cambio de importe o de fecha de cierre.

    Se llama desde la actualización de la oportunidad y no desde quien la llame:
    un historial que dependa de que alguien se acuerde tiene huecos justo donde
    importa, y el hueco típico es el cambio de fecha sin cambio de etapa — que es
    precisamente el deslizamiento que explica el trimestre.
    """
    apuntes: list[CambioPrevision] = []

    if importe_antes is not None and oportunidad.importe != importe_antes:
        apuntes.append(
            CambioPrevision(
                tenant_id=oportunidad.tenant_id,
                oportunidad_id=oportunidad.id,
                campo="importe",
                valor_anterior=str(importe_antes),
                valor_nuevo=str(oportunidad.importe),
                delta_importe=(oportunidad.importe or CERO) - importe_antes,
                motivo=motivo or None,
                por=oportunidad.updated_by,
            )
        )

    if fecha_antes != oportunidad.fecha_cierre:
        dias = None
        if fecha_antes and oportunidad.fecha_cierre:
            dias = (oportunidad.fecha_cierre - fecha_antes).days
        apuntes.append(
            CambioPrevision(
                tenant_id=oportunidad.tenant_id,
                oportunidad_id=oportunidad.id,
                campo="fecha_cierre",
                valor_anterior=fecha_antes.isoformat() if fecha_antes else None,
                valor_nuevo=(
                    oportunidad.fecha_cierre.isoformat() if oportunidad.fecha_cierre else None
                ),
                dias_deslizados=dias,
                motivo=motivo or None,
                por=oportunidad.updated_by,
            )
        )

    for apunte in apuntes:
        db.add(apunte)
    return apuntes


def deslizamiento(db: Session, tenant_id: UUID, periodo_clave: str) -> dict[str, Any]:
    """Cuánto se ha movido el periodo y quién lo ha movido.

    Se saca **el número de veces**, no solo los días: una oportunidad empujada
    cuatro veces dos semanas cada una no es lo mismo que otra movida dos meses de
    golpe, aunque el total coincida. La primera es un problema de calificación y
    la segunda, de un cliente que cambió de plan.
    """
    per = periodo(db, tenant_id, periodo_clave)
    filas = db.execute(
        select(
            CambioPrevision.oportunidad_id,
            Oportunidad.nombre,
            func.count(),
            func.sum(CambioPrevision.dias_deslizados),
        )
        .join(Oportunidad, Oportunidad.id == CambioPrevision.oportunidad_id)
        .where(
            CambioPrevision.tenant_id == tenant_id,
            CambioPrevision.campo == "fecha_cierre",
            CambioPrevision.dias_deslizados.isnot(None),
            Oportunidad.fecha_cierre >= per.desde,
            Oportunidad.fecha_cierre <= per.hasta,
        )
        .group_by(CambioPrevision.oportunidad_id, Oportunidad.nombre)
    ).all()

    # Con su nombre: la pantalla lo pinta y salía «—» delante de «52 días, 2
    # veces», sin decir qué venta es la que no existe (visto el 10-11-2026).
    detalle = [
        {
            "oportunidad_id": str(op),
            "nombre": nombre,
            "veces": int(veces),
            "dias_netos": int(dias or 0),
        }
        for op, nombre, veces, dias in filas
    ]
    empujadas = [d for d in detalle if d["dias_netos"] > 0]
    return {
        "periodo": periodo_clave,
        "oportunidades_con_cambio_de_fecha": len(detalle),
        "empujadas": len(empujadas),
        "dias_empujados": sum(d["dias_netos"] for d in empujadas),
        # Empujada más de una vez: es la señal de que nunca iba a cerrar en este
        # trimestre y de que el problema está antes, en la calificación.
        "empujadas_mas_de_una_vez": len([d for d in empujadas if d["veces"] > 1]),
        "detalle": sorted(detalle, key=lambda d: -d["dias_netos"]),
    }


def historial_de(db: Session, tenant_id: UUID, oportunidad_id: UUID) -> list[dict[str, Any]]:
    """Cambios de importe y fecha de una oportunidad.

    Se comprueba primero que la oportunidad sea de este tenant. Devolver una
    lista vacía para una ajena parece inofensivo y no lo es: un 200 confirma que
    ese identificador existe en algún sitio, y con eso se puede recorrer la
    instalación entera averiguando qué registros hay. Lo cazó el gate de fuzzing
    entre tenants.
    """
    ajena = db.execute(
        select(Oportunidad.id).where(
            Oportunidad.id == oportunidad_id, Oportunidad.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if ajena is None:
        raise NoEncontrado(
            "Oportunidad no encontrada", error_code="sales.oportunidad_no_encontrada"
        )

    filas = (
        db.execute(
            select(CambioPrevision)
            .where(
                CambioPrevision.tenant_id == tenant_id,
                CambioPrevision.oportunidad_id == oportunidad_id,
            )
            .order_by(CambioPrevision.created_at)
        )
        .scalars()
        .all()
    )
    return [
        {
            "campo": f.campo,
            "anterior": f.valor_anterior,
            "nuevo": f.valor_nuevo,
            "dias_deslizados": f.dias_deslizados,
            "delta_importe": str(f.delta_importe) if f.delta_importe is not None else None,
            "motivo": f.motivo,
            "at": f.created_at.isoformat(),
        }
        for f in filas
    ]


def _sin_usar(*_a: Any) -> None:  # pragma: no cover
    """Mantiene el import de `UnidadDeTrabajo` para las anotaciones."""
    _ = UnidadDeTrabajo
