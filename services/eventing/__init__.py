"""Servicio de eventos salientes: webhooks, catálogo y reproceso.

Es la cara pública del bus. Dentro, los servicios se hablan por NATS; fuera, un
integrador no va a conectarse a nuestro bus — quiere un HTTP POST en su
endpoint, firmado, con reintentos y con forma de poder recuperar lo que se
perdió mientras su sistema estaba caído.

Tres cosas que distinguen unos webhooks utilizables de unos que solo existen:

  * **Firma y anti-replay** (CRM-00.02.02.02): el receptor puede comprobar que
    el mensaje viene de nosotros y que no es uno antiguo reenviado.
  * **Cola de fallidos con reenvío** (CRM-00.02.02.03): lo que no se pudo
    entregar no se pierde ni se reintenta para siempre; se aparta y se puede
    reenviar cuando el receptor vuelva.
  * **Replay desde un punto en el tiempo** (CRM-00.02.02.09): «se me cayó el
    sistema el martes, mándame otra vez lo de ese día» tiene respuesta.
"""
