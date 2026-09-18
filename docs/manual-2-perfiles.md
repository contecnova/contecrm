# Manual II — Qué puede hacer cada perfil

Escrito para quien va a **usar** o **administrar** el sistema, no para quien lo
programa. Cada apartado dice qué puede hacer ese perfil, qué no, y dónde está lo
que necesita.

> **Nota importante sobre las pantallas.** contecrm es *headless*: hoy todo se
> hace por API, y la interfaz de usuario llega en la fase 1. Este manual
> describe **capacidades**, no botones. Cuando diga «puede», significa que hay
> una llamada de API que lo hace y que el permiso correspondiente la autoriza.

---

## Usuario del CRM

El perfil de partida. Con el rol `usuario` puede:

- Consultar cuentas, contactos y actividad.
- Crear y gestionar **su propia** actividad y sus notas.
- Ver su bandeja de tareas y responder las que le tocan.
- Configurar su **doble factor** y ver sus sesiones abiertas, cerrando la que no
  reconozca.

No puede cambiar la configuración del tenant ni ver datos de otros tenants —eso
no es una cuestión de permisos, sino de que el sistema no se los devuelve.

## Comercial

Hereda todo lo del usuario y añade la gestión de su cartera: cuentas, contactos,
leads, oportunidades y presupuestos.

Lo que le afecta y conviene que sepa:

- Si su organización activa la política **«solo las propias»**, podrá ver las
  oportunidades del equipo pero solo modificar aquellas de las que es
  propietario. Cuando algo se le deniegue, el sistema le dice **qué política lo
  impide**, no un «sin permiso» a secas.
- Un descuento por encima del umbral configurado no se aplica solo: **abre una
  tarea de aprobación** a quien corresponda y la oportunidad queda esperando.

## Responsable de ventas

Hereda del comercial y añade:

- **Previsión** sobre su equipo, con visibilidad ascendente: ve los registros de
  todo su árbol, no solo de quien le reporta directamente.
- **Aprobaciones**: las tareas asignadas a su rol le llegan a la bandeja, con su
  plazo. Si no las atiende antes del vencimiento, se **escalan**.
- Puede **delegar** una tarea concreta sin ceder su rol.

## Agente de soporte

- Casos, con su cola, su prioridad y sus relojes de SLA.
- Base de conocimiento, en lectura.
- Consulta de los derechos de servicio del cliente.

## Administrador del tenant

Es quien configura el CRM para su organización. Puede:

**Usuarios y permisos**
: Dar de alta y de baja, asignar roles, crear roles propios con los permisos que
  quiera combinar. Puede además **preguntar por qué** un usuario ve o no ve algo
  concreto, y obtiene la respuesta con el permiso y la política que deciden.

**Modelo de datos**
: Crear objetos y campos propios, con sus validaciones y su clasificación de
  sensibilidad. Nada de esto afecta a otros clientes de la instalación.

**Procesos y automatizaciones**
: Publicar procesos de negocio, simularlos antes con datos de ejemplo, y crear
  reglas «cuando ocurre X, si Y, entonces Z». Toda regla nace **desactivada**:
  se prueba en seco y luego se activa.

**Integraciones**
: Declarar conexiones con sistemas externos y sus operaciones, sin escribir
  código. Puede probar la conectividad antes de que falle un proceso real.

**Configuración**
: Los ajustes editables en caliente (topes, plazos, políticas de sesión, MFA
  obligatoria…), viendo **de qué ámbito sale** cada valor efectivo —lo que
  evita la confusión de «he guardado esto y no se aplica», que casi siempre es
  un ámbito más específico sobrescribiendo.

**Auditoría**
: Consultar quién hizo qué, con el valor anterior y el nuevo, y **por qué vía**:
  a mano, por API, por una automatización o por el orquestador.

Lo que **no** puede: dar de alta otros tenants, ni ver nada fuera del suyo.

## Integrador / desarrollador externo

Trabaja contra la API con una **clave de máquina**, no con un usuario.

- La clave tiene **ámbitos**: una de solo lectura no escribe aunque el rol
  asociado pueda.
- Puede caducar y admite lista de IP.
- El secreto se enseña **una sola vez**. Si se pierde, se genera otra: poder
  recuperarlo significaría que está guardado en claro.
- Se suscribe a **webhooks** con filtro por tipo y por contenido, verifica la
  firma de cada entrega y, si su sistema estuvo caído, puede pedir un **replay**
  de la ventana que se perdió.
- El catálogo de eventos y su especificación AsyncAPI están publicados en la
  propia API.

## Personal de la plataforma (proveedor)

- Alta, suspensión y baja de tenants.
- **Suplantación** de un usuario para dar soporte. Exige **motivo escrito**,
  caduca en minutos y **queda auditada en el tenant del cliente**, con quién
  suplantó a quién y por qué. El cliente puede consultarlo.
- Operación: estado de los servicios, cola de eventos fallidos, reenvíos.

No puede leer datos de un tenant sin dejar rastro. Esa es la garantía, y está
comprobada por pruebas, no prometida.
