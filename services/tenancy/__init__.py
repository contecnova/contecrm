"""Servicio de tenancy: ciclo de vida del tenant, configuración, planes y cuotas.

Es el servicio del que dependen todos los demás, y por eso es el primero que se
escribió. Responde a cuatro preguntas que ningún otro servicio puede responder
por su cuenta:

  * **¿Existe este tenant y está operativo?** Un tenant suspendido o congelado
    tiene que dejar de operar en TODOS los servicios a la vez.
  * **¿Qué puede usar?** El plan decide qué capacidades están activas
    (CRM-00.01.04.05), y eso no puede vivir repartido por ocho servicios.
  * **¿Cuánto lleva consumido?** Las cuotas y su medición (CRM-00.01.06).
  * **¿Cómo está configurado?** La jerarquía de ajustes global → tier → tenant →
    unidad de negocio → usuario.

Lo que **no** hace: autenticar. Eso es de `identity`. Un tenant es una
organización cliente; un usuario pertenece a uno. Separarlos permite que un
mismo usuario opere en varios tenants (consultoras, grupos empresariales) sin
duplicar su identidad.
"""
