"""Auditoría de configuración y metadatos por tenant (CRM-00.01.04).

Cuatro capacidades sin ninguna prueba que las nombre. Lo que tienen en común es
que fallan **a favor del valor equivocado**, y eso no se ve: el sistema hace
algo razonable, sólo que no es lo que la empresa configuró.

  · **la jerarquía** (CRM-00.01.04.01): global → tier → tenant → unidad →
    usuario. Lo más cercano gana, y si no gana, la empresa cambia su ajuste y
    no le cambia a nadie;
  · **el modelo extensible** (CRM-00.01.04.03): lo que un tenant añade no lo
    ve otro — y lo que uno quita tampoco le desaparece al de al lado;
  · **los feature flags** (CRM-00.01.04.04): usuario, tenant y porcentaje, y el
    porcentaje por **hash** y no al azar, porque si fuera aleatorio a la misma
    persona le aparecería y desaparecería la funcionalidad entre dos
    peticiones;
  · y **los secretos por tenant** (CRM-00.01.04.08): guardados cifrados y no
    legibles desde una copia de la tabla.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


# ── CRM-00.01.04.04 · Feature flags ───────────────────────────────────────


@pytest.fixture
def flags(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> Any:
    from services.tenancy.modelos import FeatureFlag

    return FeatureFlag


def test_lo_mas_cercano_gana_crm_00_01_04_04(
    db: Any, tenant_id: UUID, flags: Any, contexto_tenant: UUID
) -> None:
    """Usuario sobre tenant, y tenant sobre global. Si no fuera así, apagarle
    una funcionalidad a una persona concreta sería imposible sin apagársela a
    toda la empresa."""
    from services.tenancy.servicio import flag_activo

    quien = uuid4()
    db.add(flags(clave="nueva", activo=True))  # global: encendida
    db.add(flags(clave="nueva", tenant_id=tenant_id, activo=False))  # esta empresa: apagada
    db.flush()
    assert flag_activo(db, "nueva", tenant_id=tenant_id) is False

    db.add(flags(clave="nueva", user_id=quien, activo=True))  # esta persona: encendida
    db.flush()
    assert flag_activo(db, "nueva", tenant_id=tenant_id, user_id=quien) is True


def test_una_bandera_que_no_existe_esta_apagada_crm_00_01_04_04(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**Apagada por defecto**, no encendida: una funcionalidad a medias que se
    enciende sola porque nadie declaró la bandera es cómo se estrena algo sin
    querer."""
    from services.tenancy.servicio import flag_activo

    assert flag_activo(db, "no-declarada", tenant_id=tenant_id) is False


def test_el_porcentaje_reparte_por_hash_y_no_al_azar_crm_00_01_04_04(
    db: Any, tenant_id: UUID, flags: Any, contexto_tenant: UUID
) -> None:
    """**Si fuera aleatorio, a la misma persona le aparecería y desaparecería
    la funcionalidad entre dos peticiones**, que es la peor forma de probar
    algo: nadie sabría si el fallo que ve es de la versión nueva o de la vieja.

    Aquí se pregunta diez veces por la misma persona y tiene que contestar lo
    mismo las diez.
    """
    from services.tenancy.servicio import flag_activo

    db.add(flags(clave="a-medias", activo=False, porcentaje=50))
    db.flush()

    quien = uuid4()
    respuestas = {flag_activo(db, "a-medias", user_id=quien) for _ in range(10)}
    assert len(respuestas) == 1, f"la misma persona recibe respuestas distintas: {respuestas}"


def test_el_porcentaje_reparte_de_verdad_crm_00_01_04_04(
    db: Any, tenant_id: UUID, flags: Any, contexto_tenant: UUID
) -> None:
    """Y reparte: con el 50 %, unos sí y otros no. Un reparto estable que
    conteste siempre lo mismo a todos también es «estable», y no despliega
    nada."""
    from services.tenancy.servicio import flag_activo

    db.add(flags(clave="mitad", activo=False, porcentaje=50))
    db.flush()

    personas = [uuid4() for _ in range(60)]
    encendidas = sum(1 for p in personas if flag_activo(db, "mitad", user_id=p))
    assert 0 < encendidas < 60, f"con el 50 % le toca a {encendidas} de 60"


def test_cero_y_cien_son_lo_que_parecen_crm_00_01_04_04(
    db: Any, tenant_id: UUID, flags: Any, contexto_tenant: UUID
) -> None:
    """Los dos extremos, porque son los que se usan para apagar y para
    terminar de desplegar, y un fallo ahí deja a alguien fuera para siempre o
    estrena para todos antes de tiempo."""
    from services.tenancy.servicio import flag_activo

    db.add(flags(clave="nadie", activo=False, porcentaje=0))
    db.add(flags(clave="todos", activo=False, porcentaje=100))
    db.flush()

    personas = [uuid4() for _ in range(20)]
    assert not any(flag_activo(db, "nadie", user_id=p) for p in personas)
    assert all(flag_activo(db, "todos", user_id=p) for p in personas)


# ── CRM-00.01.04.01 · La jerarquía de ajustes ─────────────────────────────

# `ui_densidad` es de las cinco claves que llegan hasta el usuario: las otras
# 85 se quedan en el tenant. Se usa esta a propósito, porque es la única forma
# de recorrer la escalera entera —global, tenant, usuario— con una clave de
# verdad y no con una inventada para la prueba.
CLAVE = "ui_densidad"


def test_el_ajuste_mas_cercano_gana_crm_00_01_04_01(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Global → tier → tenant → unidad → usuario. **Si lo más cercano no ganara,
    la empresa cambiaría su ajuste y no le cambiaría a nadie** — y nadie sabría
    por qué: el valor nuevo está guardado, se ve en la pantalla de Admin, y la
    aplicación sigue haciendo lo de antes.
    """
    from crmcore.runtime import settings as rt
    from crmcore.tenancy.context import con_contexto

    quien = uuid4()
    assert rt.efectivo(CLAVE, db) == "compacta", "el ajuste no parte del .env"

    rt.fijar(db, CLAVE, "comoda", ambito="global")
    db.flush()
    assert rt.efectivo(CLAVE, db) == "comoda", "lo global no llega"

    rt.fijar(db, CLAVE, "compacta", ambito="tenant", ambito_id=str(tenant_id))
    db.flush()
    assert rt.efectivo(CLAVE, db) == "compacta", "el del tenant no gana al global"

    with con_contexto(tenant_id=tenant_id, user_id=quien):
        rt.fijar(db, CLAVE, "comoda", ambito="usuario", ambito_id=str(quien))
        db.flush()
        assert rt.efectivo(CLAVE, db) == "comoda", "el de la persona no gana al del tenant"

    # Y al de al lado no le ha cambiado nada: un ajuste personal que se cuela en
    # el ámbito del tenant le cambia la pantalla a toda la empresa.
    with con_contexto(tenant_id=tenant_id, user_id=uuid4()):
        assert rt.efectivo(CLAVE, db) == "compacta"


def test_quitar_el_de_arriba_destapa_el_de_abajo_crm_00_01_04_01(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La escalera tiene que funcionar también hacia atrás: quitar el ajuste del
    tenant devuelve el global, no deja un hueco. **Un ajuste quitado que se
    queda en `None` apaga la funcionalidad en vez de devolverla al valor de la
    casa**, que es lo contrario de lo que espera quien pulsa «restablecer»."""
    from crmcore.runtime import settings as rt

    rt.fijar(db, CLAVE, "comoda", ambito="global")
    rt.fijar(db, CLAVE, "compacta", ambito="tenant", ambito_id=str(tenant_id))
    db.flush()
    assert rt.efectivo(CLAVE, db) == "compacta"

    rt.quitar(db, CLAVE, ambito="tenant", ambito_id=str(tenant_id))
    db.flush()
    assert rt.efectivo(CLAVE, db) == "comoda", "quitar el del tenant deja un hueco"

    rt.quitar(db, CLAVE, ambito="global")
    db.flush()
    assert rt.efectivo(CLAVE, db) == "compacta", "quitarlo todo no vuelve al .env"


def test_un_ajuste_no_se_fija_por_debajo_de_su_ambito_crm_00_01_04_01(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El tamaño máximo de un adjunto es del tenant, no de cada persona. **Si
    cada clave se pudiera fijar en cualquier ámbito, el límite que protege el
    almacenamiento lo levantaría cualquiera para sí mismo** — y la pantalla de
    Admin seguiría enseñando el límite de la empresa.

    Se rechaza, y el mensaje dice cuál es su ámbito más específico: un «no» sin
    decir qué sí se puede deja al operador probando.
    """
    from crmcore.errors import ErrorValidacion
    from crmcore.runtime import settings as rt

    with pytest.raises(ErrorValidacion) as fallo:
        rt.fijar(db, "adjunto_max_mb", 999, ambito="usuario", ambito_id=str(uuid4()))
    assert "tenant" in str(fallo.value), str(fallo.value)


def test_sin_sesion_se_contesta_con_el_del_fichero_crm_00_01_04_01() -> None:
    """Se puede preguntar desde donde no hay sesión —un middleware, el
    arranque— sin abrir una conexión sólo para leer un número. Lo que no puede
    es fallar: **un ajuste que revienta sin base de datos tumba el arranque**,
    y el error que se ve no habla de ajustes."""
    from crmcore.runtime import settings as rt

    assert rt.efectivo(CLAVE) == "compacta"


def test_un_ajuste_que_no_existe_no_se_inventa_crm_00_01_04_01() -> None:
    """Devolver un valor plausible para una clave que nadie declaró es cómo un
    error de escritura se convierte en una configuración silenciosa: la clave
    mal escrita contesta algo, nadie ve un fallo, y el ajuste de verdad lleva
    meses sin aplicarse."""
    from crmcore.runtime import settings as rt

    assert rt.efectivo("no-declarado-en-ninguna-parte") is None


# ── CRM-00.01.04.03 · El modelo extensible por tenant ─────────────────────


def _objeto_con_campo(db: Any, tenant: UUID, campo: str) -> Any:
    """Un objeto propio con un campo, para un tenant. Devuelve el objeto."""
    from services.metadata.modelos import CampoDefinido, ObjetoDefinido

    objeto = ObjetoDefinido(
        tenant_id=tenant,
        nombre="proyecto_obra",
        etiqueta="Proyecto de obra",
        origen="propio",
    )
    db.add(objeto)
    db.flush()
    db.add(
        CampoDefinido(
            tenant_id=tenant,
            objeto_id=objeto.id,
            nombre=campo,
            etiqueta=campo,
            tipo="numero",
        )
    )
    db.flush()
    return objeto


def test_lo_que_anade_un_tenant_no_lo_ve_otro_crm_00_01_04_03(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Dos empresas pueden llamar igual a su objeto propio y ponerle campos
    distintos. **Un campo que se cuela de un tenant al de al lado no es un fallo
    de pantalla: es una columna del modelo de datos de un cliente apareciendo en
    el formulario de otro**, con su etiqueta y con lo que signifique.
    """
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    from services.metadata.api import _objeto
    from services.metadata.modelos import CampoDefinido

    _objeto_con_campo(db, tenant_id, "metros_cuadrados")
    with con_contexto(tenant_id=otro_tenant_id):
        _objeto_con_campo(db, otro_tenant_id, "toneladas")

    def campos_de(tenant: UUID) -> set[str]:
        objeto = _objeto(db, tenant, "proyecto_obra")
        filas = (
            db.execute(select(CampoDefinido).where(CampoDefinido.objeto_id == objeto.id))
            .scalars()
            .all()
        )
        return {c.nombre for c in filas}

    assert campos_de(tenant_id) == {"metros_cuadrados"}
    assert campos_de(otro_tenant_id) == {"toneladas"}


def test_retirar_un_campo_no_se_lo_quita_al_de_al_lado_crm_00_01_04_03(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La otra mitad, y la que no se mira: aislar lo que se **añade** es fácil;
    lo que se rompe es retirar. Y además se deprecia en vez de borrarse — un
    campo que desaparece de golpe rompe a quien aún lo manda, y lo rompe en
    silencio, con un 400 que su integración no sabe leer.
    """
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    from services.metadata.modelos import CampoDefinido

    _objeto_con_campo(db, tenant_id, "comun")
    with con_contexto(tenant_id=otro_tenant_id):
        _objeto_con_campo(db, otro_tenant_id, "comun")

    mio = db.execute(
        select(CampoDefinido).where(
            CampoDefinido.tenant_id == tenant_id, CampoDefinido.nombre == "comun"
        )
    ).scalar_one()
    mio.deprecado = True
    mio.solo_lectura = True
    db.flush()

    suyo = db.execute(
        select(CampoDefinido).where(
            CampoDefinido.tenant_id == otro_tenant_id, CampoDefinido.nombre == "comun"
        )
    ).scalar_one()
    assert suyo.deprecado is False, "retirar un campo se lo ha retirado al vecino"
    # Y el mío sigue ahí, legible: deprecado no es borrado.
    assert mio.activo is True


# ── CRM-00.01.04.08 · Secretos y claves por tenant ────────────────────────


def test_un_secreto_no_queda_legible_crm_00_01_04_08(db: Any) -> None:
    """Quien lea la tabla —una copia de seguridad, un volcado de soporte, una
    réplica de lectura— no puede sacar de ahí la credencial con la que entrar
    en el sistema de un cliente."""
    from crmcore.security.cifrado import PREFIJO, cifrar, descifrar

    guardado = cifrar("clave-del-erp-del-cliente", proposito="integracion", db=db)
    assert guardado.startswith(PREFIJO), guardado[:20]
    assert "clave-del-erp" not in guardado
    assert descifrar(guardado, proposito="integracion", db=db) == "clave-del-erp-del-cliente"


def test_el_mismo_secreto_dos_veces_no_se_guarda_igual_crm_00_01_04_08(db: Any) -> None:
    """**Dos filas idénticas delatan que la contraseña es la misma** sin
    descifrar nada: quien tenga la tabla sabe qué clientes comparten credencial,
    y cuál de ellos cambió la suya y cuál no. El nonce por valor es lo que lo
    impide, y por eso se guarda con el valor y no al lado."""
    from crmcore.security.cifrado import cifrar

    uno = cifrar("misma-contrasena", proposito="integracion", db=db)
    otro = cifrar("misma-contrasena", proposito="integracion", db=db)
    assert uno != otro


def test_el_almacen_esta_segmentado_por_proposito_crm_00_01_04_08(db: Any) -> None:
    """«Vault segmentado» no es una palabra: es que **la clave que cifra las
    credenciales de integración no abre los campos de cliente**. Si fuera una
    sola, comprometer el subsistema más expuesto daría acceso a todo lo demás.
    """
    from crmcore.errors import ErrorInterno
    from crmcore.security.cifrado import cifrar, descifrar

    guardado = cifrar("clave-del-erp", proposito="integracion", db=db)
    with pytest.raises(ErrorInterno):
        descifrar(guardado, proposito="campo_cliente", db=db)


def test_un_secreto_alterado_falla_en_vez_de_abrir_otra_cosa_crm_00_01_04_08(db: Any) -> None:
    """GCM y no CBC porque **autentica**. Sin autenticación, quien pueda
    escribir en la tabla cambia un valor cifrado por otro y el sistema se
    conecta a donde le digan: no falla, hace algo distinto. Eso no se ve en
    ningún registro."""
    import base64

    from crmcore.errors import ErrorInterno
    from crmcore.security.cifrado import PREFIJO, cifrar, descifrar

    guardado = cifrar("clave-del-erp", proposito="integracion", db=db)
    crudo = bytearray(base64.b64decode(guardado[len(PREFIJO) :]))
    crudo[-1] ^= 0x01  # un bit del texto cifrado
    alterado = PREFIJO + base64.b64encode(bytes(crudo)).decode()

    with pytest.raises(ErrorInterno):
        descifrar(alterado, proposito="integracion", db=db)


def test_un_almacen_que_no_existe_corta_el_arranque_crm_00_01_04_08(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SECRETOS_BACKEND=vault` guardaba los secretos en la base igual. No es un
    ajuste decorativo: **es una creencia falsa sobre dónde están los secretos
    del cliente**, que es de las pocas cosas que hay que saber con certeza. Se
    corta al arrancar y no se cae a la base avisando en el log — el aviso lo lee
    quien mira el log, y quien escribió «vault» seguiría creyendo lo que creía.
    """
    from crmcore.config import get_settings
    from crmcore.errors import ErrorValidacion
    from crmcore.security.cifrado import comprobar_backend_de_secretos

    comprobar_backend_de_secretos()  # con lo configurado, pasa

    s = get_settings()
    monkeypatch.setattr(s, "secretos_backend", "vault", raising=False)
    with pytest.raises(ErrorValidacion) as fallo:
        comprobar_backend_de_secretos()
    assert "vault" in str(fallo.value)
