"""Qué hace `marketing` con los datos personales que guarda (CRM-07.03.01.04).

Es el servicio donde la base legal importa más y donde más se falsea: casi todo
lo de aquí se hace por **consentimiento**, y el consentimiento se prueba o no
existe. Por eso lo que se guarda de un consentimiento —cuándo, desde dónde, con
qué texto— es también dato personal, y también se declara.
"""

from __future__ import annotations

from crmcore.cumplimiento import Tratamiento, declarar

RESPONSABLE = "El cliente titular del tenant; el fabricante actúa como encargado"

declarar(
    Tratamiento(
        objeto="perfiles_marketing",
        finalidad="Segmentar y dirigir comunicaciones comerciales a quien las ha aceptado",
        base_legal="consentimiento",
        plazo="Hasta que se retire el consentimiento, y 3 años más solo para acreditar que existió",
        destinatarios=("Proveedor de envío de correo configurado por el cliente",),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="consentimientos_canal",
        # Se guarda la IP y el momento porque un consentimiento que no se puede
        # probar es un consentimiento que no existe delante de una autoridad.
        finalidad="Probar cuándo, desde dónde y con qué texto se dio o se retiró un consentimiento",
        base_legal="obligacion_legal",
        plazo="3 años desde la retirada, para poder acreditarlo",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="preferencias_contacto",
        finalidad="Respetar por qué canales quiere o no quiere ser contactada cada persona",
        base_legal="obligacion_legal",
        plazo="Indefinido mientras exista la dirección: olvidar una baja es volver a escribir a quien pidió no recibir nada",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="supresiones",
        # La lista de supresión tiene que sobrevivir al borrado de todo lo demás:
        # si se borra, la siguiente importación vuelve a escribir a quien se dio
        # de baja. Es el caso en que conservar protege más que suprimir.
        finalidad="No volver a enviar comunicaciones a quien se ha dado de baja",
        base_legal="obligacion_legal",
        plazo="Indefinido: es lo único que garantiza que la baja se respete",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="rebotes",
        finalidad="Dejar de escribir a direcciones que no existen y proteger la reputación de envío",
        base_legal="interes_legitimo",
        plazo="24 meses",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="confirmaciones_optin",
        # Se guarda la IP de quien pide el alta y la de quien confirma porque son
        # dos momentos distintos, y la diferencia entre ellos es lo que prueba
        # que confirmó quien recibió el correo y no quien rellenó el formulario.
        finalidad="Probar que la persona confirmó su alta, y que fue ella",
        base_legal="obligacion_legal",
        plazo="3 años desde la baja, para poder acreditar que el alta fue válida",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="consentimientos_cookies",
        finalidad="Probar qué aceptó cada visitante, sobre qué versión del aviso y cuándo",
        base_legal="obligacion_legal",
        plazo="2 años desde la decisión, que es lo que suele durar el propio consentimiento",
        responsable=RESPONSABLE,
    )
)
