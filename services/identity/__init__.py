"""Servicio de identidad: usuarios, roles, sesiones, credenciales y federación.

Separado de `tenancy` a propósito. Un tenant es una organización; un usuario es
una persona. Que sean servicios distintos permite lo que casi todo CRM
empresarial acaba necesitando y pocos soportan: que **una misma persona opere en
varios tenants** —consultoras, grupos, partners— sin duplicar su identidad ni
sus credenciales.

La pertenencia vive en `Membresia`, que es la tabla que une a las dos: un
usuario tiene una membresía por cada tenant al que pertenece, con sus roles en
ese tenant. Sus roles en uno no dicen nada de sus roles en otro.
"""
