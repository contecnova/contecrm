"""La página de estado que publica cada servicio (CRM-00.06.01.06).

Se monta sola en `crear_servicio`, como la salud y la superficie. Si dependiera
de que cada servicio se acuerde, faltaría en alguno —precisamente en el que
menos se mira— y la página del cliente tendría un agujero sin decirlo.

Cada servicio publica **lo suyo**. El gateway junta las páginas de todos y
devuelve una sola, que es lo que ve el cliente: `GET /api/v1/estado`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from crmcore.http.deps import AutenticadoDep, DbDep, PlataformaDep


class SoloLectura(BaseModel):
    activo: bool
    motivo: str = Field(
        "",
        description=(
            "Qué está pasando, en una frase que se le pueda enseñar al usuario. "
            "Obligatorio al entrar: sin él, quien no puede guardar cree que su "
            "cambio tenía algo malo y lo reintenta cambiándolo"
        ),
    )


def crear_router_estado(servicio: str) -> APIRouter:
    router = APIRouter(prefix="/estado", tags=["estado del servicio"])

    @router.get(
        "",
        summary=f"Estado de «{servicio}» para este tenant",
        description=(
            "Los componentes de **este servicio** para el tenant que pregunta, "
            "calculados en vivo. La página completa —con la de todos los "
            "servicios— la sirve el gateway en la misma ruta.\n\n"
            "Se calcula en vivo a propósito: una página de estado cacheada "
            "enseña «todo bien» mientras el cliente mira una pantalla que no "
            "carga, y eso destruye más confianza que no tener página."
        ),
    )
    def estado(db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.datos.estado import calcular

        return {"servicio": servicio, **calcular(db, principal.tenant_id)}

    @router.get(
        "/consumo",
        summary=f"Cuánta cuota lleva gastada este tenant en «{servicio}»",
        description=(
            "Lo que **este módulo** cuenta para este tenant. La suma de todos "
            "los módulos la compone el gateway en la misma ruta.\n\n"
            "Va por módulo porque las cuotas van por módulo: cada servicio "
            "guarda lo suyo en su esquema y cuenta lo suyo, y así el número que "
            "se enseña se puede cuadrar con lo que el cliente ve en su pantalla."
        ),
    )
    def consumo(db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.consumo import medido_aqui

        return {"servicio": servicio, "metricas": medido_aqui(db, principal.tenant_id)}

    @router.get(
        "/contratos",
        summary=f"Contratos de evento que «{servicio}» consume y cumple",
        description=(
            "Contract testing interno dirigido por el consumidor "
            "(CRM-00.03.01.03): qué campos de qué eventos necesita este "
            "servicio, qué promesas no se sostienen y —lo que más cuesta "
            "encontrar en otros sitios— qué parte del contrato se ha visto "
            "cumplirse de verdad y cuál solo está escrita.\n\n"
            "La cobertura se cuenta sobre emisiones observadas, no sobre "
            "campos declarados: un 100 % de campos declarados sin una sola "
            "emisión observada sería un informe que dice que todo va bien sin "
            "haber mirado."
        ),
    )
    def contratos_de_evento(principal: AutenticadoDep) -> Any:
        from crmcore import contratos

        return {"servicio": servicio, **contratos.informe()}

    @router.get(
        "/slo",
        summary=f"Presupuesto de error de «{servicio}» para este tenant",
        description=(
            "SLO y error budget (CRM-00.06.01.04): cuántas peticiones de este "
            "tenant ha servido este servicio en el periodo, cuántas fallaron y "
            "cuántas llegaron tarde, y cuánto margen queda antes de incumplir "
            "lo prometido.\n\n"
            "El tier se pasa como parámetro porque **este servicio no lo sabe**: "
            "el plan contratado vive en `tenancy` y ningún servicio lee el "
            "esquema de otro. Quien compone la vista completa —el gateway— lo "
            "resuelve una vez y se lo dice a todos. Sin tier se responde con el "
            "estándar, que es lo que se promete por defecto.\n\n"
            "Sin tráfico se responde «no medible» en vez de 100 %: un servicio "
            "que nadie ha usado no ha demostrado nada."
        ),
    )
    async def slo_del_servicio(principal: AutenticadoDep, tier: str = "estandar") -> Any:
        from crmcore.config import get_settings
        from crmcore.obs import slo

        objetivo = slo.objetivo_de(servicio, tier)
        consumo = await slo.consumo_de(servicio, principal.tenant_id, tier=objetivo.tier)
        return slo.presupuesto(objetivo, consumo, dias_del_periodo=get_settings().slo_dias_periodo)

    @router.get(
        "/ui-referencia",
        summary="Si este servicio necesita la interfaz de referencia",
        description=(
            "«La UI es opcional» (CRM-00.02.03.02) es de esas frases que se "
            "erosionan solas: alguien monta un estático, otro deja una "
            "redirección a `/app`, y al año la API headless necesita su front.\n\n"
            "Esto lo **mide** sobre la aplicación montada de verdad y dice qué "
            "ata el servicio a una interfaz concreta, si es que hay algo. "
            "Corre también como gate del preflight, que es donde se para antes "
            "de que llegue a un despliegue."
        ),
    )
    def ui_de_referencia(request: Request, principal: AutenticadoDep) -> Any:
        from crmcore.config import get_settings
        from crmcore.http.ui_opcional import comprobar_independencia, estado_de_la_ui

        s = get_settings()
        return {
            "servicio": servicio,
            **comprobar_independencia(request.app, origenes_cors=list(s.origenes_cors or [])),
            "la_interfaz": estado_de_la_ui(settings=s),
        }

    @router.get(
        "/presion",
        summary="Cuánta presión tiene este servicio y qué se está aplazando",
        description=(
            "El mecanismo de degradación controlada (CRM-08.01.01.06) decide qué "
            "pasa cuando el sistema está saturado —lo crítico pasa siempre, lo "
            "diferible espera—, y esto enseña **por qué** en un momento dado.\n\n"
            "Sirve para contestar la pregunta de un incidente («¿por qué mi "
            "informe no sale?») sin leer el código, y para ver si la presión que "
            "se está midiendo se parece a lo que la gente está notando."
        ),
    )
    def presion_del_servicio(principal: AutenticadoDep) -> Any:
        from crmcore import resiliencia
        from crmcore.obs.presion import que_se_esta_aplazando

        return {
            "servicio": servicio,
            **que_se_esta_aplazando(resiliencia.presion()),
            # El modo solo lectura sale AQUÍ y no en otra ruta: durante un
            # incidente, quien mira la página de estado es quien tiene que
            # enterarse de que no se puede guardar, y mandarle a otro sitio es
            # pedirle que lo adivine.
            "solo_lectura": resiliencia.estado(),
        }

    # ── Lo que hace falta ANTES de desplegar o de escalar ─────────────────
    #
    # Nueve decisiones de observabilidad estaban escritas, probadas y sin que las
    # alcanzara ninguna ruta. Son las que se consultan cuando algo va mal o
    # cuando hay que crecer, y entonces nadie se pone a leer código.

    @router.get(
        "/consultas-degradadas",
        summary="Qué consultas se han vuelto lentas respecto a su propia base",
        description=(
            "Comparadas **consigo mismas**, no con un umbral: una consulta que "
            "siempre tardó 800 ms no es un problema nuevo, y una que pasó de 20 a "
            "90 sí lo es aunque siga por debajo de cualquier umbral. Un umbral "
            "fijo caza las lentas de siempre y se pierde las que se acaban de "
            "torcer, que son las que tienen arreglo."
        ),
    )
    def consultas_degradadas(
        principal: AutenticadoDep,
        minimo_veces: int = 20,
        factor: float = 2.0,
    ) -> Any:
        from crmcore.obs.consultas import degradadas

        return {"consultas": degradadas(minimo_veces=minimo_veces, factor=factor)}

    @router.post(
        "/solo-lectura",
        summary="Entrar o salir del modo solo lectura (plataforma)",
        description=(
            "**Lo aplica la unidad de trabajo**, que es por donde pasan todas las "
            "escrituras. Hasta el 05-10-2026 esto no existía en el sistema: se "
            "podía entrar en modo degradado y las escrituras seguían pasando, "
            "porque la comprobación estaba escrita, probada y sin que la llamara "
            "nadie. El modo existía en la página de estado y no existía.\n\n"
            "El motivo es obligatorio al entrar, y no es cortesía: sin él el "
            "usuario cree que su cambio tenía algo malo y lo reintenta "
            "cambiándolo, que es cómo se pierde trabajo durante una incidencia.\n\n"
            "Es de **plataforma**: afecta a todos los tenants de este proceso, "
            "así que no lo decide nadie desde dentro de uno."
        ),
    )
    def solo_lectura(datos: SoloLectura, principal: PlataformaDep) -> Any:
        from crmcore import resiliencia

        if datos.activo:
            resiliencia.entrar_en_solo_lectura(datos.motivo)
        else:
            resiliencia.salir_de_solo_lectura()
        return {"servicio": servicio, **resiliencia.estado()}

    return router
