"""Servicios de contecrm, delimitados por capacidad de negocio (CRM-00.03.01.01).

Cada carpeta es un servicio desplegable por su cuenta, con su propio esquema de
base de datos, su propio rol de conexión y su propia cadena de migraciones
(CRM-00.03.01.02, CRM-00.03.01.06). Ninguno importa código de otro —lo comprueba
`tests/unit/test_contratos_arquitectura.py`— y entre ellos se hablan por el bus,
no por HTTP, para que una caída no se propague.

    gateway        única puerta de entrada: tenant, identidad, límites, enrutado
    tenancy        ciclo de vida del tenant, configuración, planes, cuotas
    identity       usuarios, roles, sesiones, credenciales, federación
    metadata       objetos y campos del tenant, validaciones, layouts
    orchestrator   motor de procesos duradero, sagas, tareas humanas
    automation     reglas declarativas «cuando X, si Y, entonces Z»
    integration    conectores declarativos con sistemas externos
    eventing       webhooks, catálogo de eventos, replay y cola de fallidos

Los de negocio —party, sales, service, marketing, analytics, intelligence—
llegan en las fases 1 a 5 y siguen esta misma forma.
"""
