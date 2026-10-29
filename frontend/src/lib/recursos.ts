/**
 * Qué pestañas tiene cada módulo, y de dónde sale cada una (CRM-07.04.04.05).
 *
 * **Vive aparte de `modulos.ts` por una razón medida, no por orden.** Ese otro
 * fichero lo importa el marco entero —la barra lateral, la de arriba, la
 * paleta— así que viaja en el módulo de entrada: lo que el navegador descarga
 * **antes de pintar nada**. Esta tabla sólo la necesitan la pantalla de
 * módulo, la ficha, la de cliente, la paleta y las referencias, y ninguna se
 * abre al entrar.
 *
 * Medido sobre el paquete construido: la tabla son 4,7 kB comprimidos, y
 * sacarla deja la apertura en 115,3 kB en vez de 130,4 —un 11,6 % menos—
 * porque además permite diferir las tres pantallas que la arrastraban.
 *
 * Lo que SÍ necesita el marco —qué permisos exige cada pestaña, para no
 * enseñar un módulo que nadie puede abrir— vive en `modulos.ts` como un
 * resumen **derivado de aquí**, no copiado a mano: lo genera un script y hay
 * un gate que lo comprueba. Dos listas escritas a mano acaban diciendo cosas
 * distintas, y entonces no se sabe cuál manda.
 */

import type { Modulo, Recurso } from "@/lib/modulos";
import { objetoDe } from "@/lib/modulos";

export const RECURSOS_POR_MODULO: Record<string, Recurso[]> = {
  "tenants": [
      {
        nombre: "Compromisos",
        listar: "/api/v1/compromisos",
        servicio: "tenancy",
      },
      {
        nombre: "Tenants",
        // Con `objeto` para que cada fila se abra: suspender, reactivar,
        // exportar y ver el consumo cuelgan del tenant, y a un registro que no
        // se abre no se llega. Y `plan_codigo` no existe: el campo es `plan`,
        // así que esa columna salía siempre vacía.
        objeto: "tenant",
        listar: "/api/v1/tenants",
        // El estado de la clave de cifrado propia del tenant: si está revocada, lo
        // cifrado con ella no se lee, y eso es irreversible.
        resumen: ["/api/v1/claves-cifrado"],
        crear: "/api/v1/tenants",
        servicio: "tenancy",
        solo_plataforma: true,
        columnas: ["slug", "nombre", "estado", "plan", "region", "idioma"],
        permiso: "tenant:read",
      },
      // Los calendarios laborales y los festivos: de ellos salen los plazos de
      // los SLA, así que un festivo que falta mueve la fecha de resolución de
      // todos los casos de ese día. Se publicaban y no se veían.
      // Los perfiles de industria: lo que deja puesto un alta según el sector.
      // Se declaran y nadie los veía, así que elegir uno al dar de alta un
      // cliente era elegir a ciegas.
      {
        nombre: "Perfiles de industria",
        listar: "/api/v1/ciclo-vida/perfiles",
        servicio: "tenancy",
        permiso: "tenant:read",
      },
      {
        nombre: "Calendarios laborales",
        // Con `objeto` para que la fila abra: los festivos y el cálculo de
        // vencimiento cuelgan del calendario.
        objeto: "calendario_laboral",
        listar: "/api/v1/calendarios",
        crear: "/api/v1/calendarios",
        servicio: "tenancy",
        permiso: "tenant:read",
      },
      {
        nombre: "Plantillas del cliente",
        listar: "/api/v1/plantillas",
        crear: "/api/v1/plantillas",
        servicio: "tenancy",
        permiso: "tenant:read",
      },
      { nombre: "Planes", listar: "/api/v1/planes", servicio: "tenancy" },
      { nombre: "Ajustes", listar: "/api/v1/ajustes", servicio: "tenancy" },
      {
        // El histórico de tipos de cambio. Sin él, un importe convertido no se
        // puede explicar: «salió a 1,07» es verificable, «salió al cambio» no.
        nombre: "Tipos de cambio",
        listar: "/api/v1/monedas/cambios",
        servicio: "tenancy",
        permiso: "tenant:read",
      },
      {
        nombre: "Localización",
        listar: "/api/v1/localizacion",
        servicio: "tenancy",
      },
      // El modelo de aislamiento del tenant y las migraciones entre modelos
      // (CRM-00.01.01.01 a .05): qué tenant está en pool, en esquema propio o
      // en instancia dedicada, y la migración de uno a otro con su ventana, su
      // verificación y su vuelta atrás. Hasta hoy esto solo existía por API.
      {
        nombre: "Aislamiento",
        listar: "/api/v1/aislamiento",
      // Los tenants cuyo aislamiento no ha contrastado nadie. No es que estén mal:
        // es que no se sabe, y contarlos con los comprobados es el verde falso.
      resumen: ["/api/v1/aislamiento/sin-comprobar"],
        servicio: "tenancy",
        permiso: "tenant:read",
      },
      {
        nombre: "Migraciones de aislamiento",
        listar: "/api/v1/aislamiento/migraciones",
        servicio: "tenancy",
        permiso: "tenant:read",
      },
      // Dónde viven los datos de cada tenant, quién los trata por cuenta
      // nuestra y qué transferencias internacionales hay declaradas
      // (CRM-00.01.05.01 a .03). Es lo que se enseña en una auditoría, y hasta
      // hoy había que pedirlo por API.
      {
        nombre: "Residencia",
        listar: "/api/v1/residencia",
        servicio: "tenancy",
        permiso: "tenant:read",
      },
      {
        nombre: "Subprocesadores",
        listar: "/api/v1/residencia/subprocesadores",
        servicio: "tenancy",
        permiso: "tenant:read",
      },
      {
        nombre: "Transferencias internacionales",
        listar: "/api/v1/residencia/transferencias",
        servicio: "tenancy",
        permiso: "tenant:read",
      },
    ],
  "contrato": [
      { nombre: "Servicios", listar: "/api/v1/servicios", servicio: "gateway" },
    ],
  "procesos": [
      {
        nombre: "Definiciones",
        listar: "/api/v1/procesos/definiciones",
        servicio: "orchestrator",
      },
      {
        nombre: "Instancias",
        objeto: "instancia",
        listar: "/api/v1/instancias",
        servicio: "orchestrator",
      },
      { nombre: "Tareas", listar: "/api/v1/tareas", servicio: "orchestrator" },
      {
        nombre: "Tablas de decisión",
        listar: "/api/v1/tablas-decision",
        servicio: "orchestrator",
      },
      {
        nombre: "Automatizaciones",
        listar: "/api/v1/automatizaciones",
        servicio: "automation",
      },
      {
        nombre: "Integraciones",
        objeto: "conexion",
        listar: "/api/v1/integraciones/conexiones",
        servicio: "integration",
      },
      {
        nombre: "Ejecuciones",
        listar: "/api/v1/integraciones/ejecuciones",
        servicio: "integration",
      },
      { nombre: "Webhooks", listar: "/api/v1/webhooks", servicio: "eventing" },
      // Eran dos pestañas —«de clientes» y «de ventas»— para lo mismo, y los
      // trabajos de analítica y de inteligencia no salían en ninguna. Una
      // pestaña con selector: lo mismo, todos los servicios, y una entrada
      // menos en un menú que ya tiene veinte.
      {
        nombre: "Trabajos de fondo",
        objeto: "trabajo",
        listar: "/api/v1/:servicio/trabajos",
        por_servicio: ["party", "sales", "analytics", "intelligence"],
        servicio: "party",
      },
      // El catálogo de conectores y lo instalado aquí, juntos: la pregunta real
      // es «¿qué tengo puesto y qué versión?», no «¿qué existe?».
      {
        nombre: "Catálogo de conectores",
        listar: "/api/v1/conectores",
        servicio: "integration",
      },
      {
        nombre: "Conectores instalados",
        listar: "/api/v1/conectores/instalados",
        servicio: "integration",
      },
      // La lista de canales, delante de los que no se han sabido atribuir: lo
      // primero que se pregunta es cuáles hay, no cuáles fallaron.
      {
        nombre: "Canales de entrada",
        objeto: "canal_entrada",
        listar: "/api/v1/canales-entrada",
        crear: "/api/v1/canales-entrada",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        // Lo que ha entrado por cada canal. Sin esto, un canal configurado y
        // mudo se ve igual que uno que trabaja.
        nombre: "Interacciones por canal",
        objeto: "canal_entrada",
        listar: "/api/v1/canales-entrada/interacciones",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Entradas sin atribuir",
        listar: "/api/v1/canales-entrada/sin-atribuir",
        servicio: "integration",
      },
      {
        nombre: "Agentes: uso",
        listar: "/api/v1/agentes-ia/uso",
        servicio: "integration",
      },
      {
        nombre: "Vistas federadas",
        listar: "/api/v1/federacion/vistas",
        servicio: "integration",
      },
      // El progreso de la migración, por delante de la lista de reglas: lo que
      // se pregunta cada semana es cuánto falta.
      // Y las reglas que gobiernan ese progreso: se veía cuánto falta y no qué
      // regla decide a quién le toca, que es lo que hay que cambiar para que
      // avance.
      {
        nombre: "Migración: reglas",
        objeto: "regla_convivencia",
        listar: "/api/v1/convivencia",
        crear: "/api/v1/convivencia",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Migración: progreso",
        listar: "/api/v1/convivencia/progreso",
        servicio: "integration",
      },
      // Las sagas: lo que cruza servicios y hay que poder deshacer. Se
      // publicaban desde el primer día y no salían en ninguna pantalla, así que
      // una compensación a medias no la veía nadie.
      {
        nombre: "Sagas",
        objeto: "saga",
        listar: "/api/v1/sagas",
        crear: "/api/v1/sagas",
        servicio: "orchestrator",
        permiso: "proceso:read",
      },
      // Lo que corre solo y lo que ha llegado. Son las dos preguntas de quien
      // mantiene una integración —«¿se está ejecutando?» y «¿está entrando
      // algo?»— y ninguna tenía pantalla.
      {
        nombre: "Ejecuciones programadas",
        objeto: "registro_recibido",
        listar: "/api/v1/integraciones/programacion",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Registros recibidos",
        objeto: "registro_recibido",
        listar: "/api/v1/integraciones/registros-recibidos",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Transportes",
        listar: "/api/v1/conectores/transportes",
        servicio: "integration",
      },
      // Las aprobaciones del motor de flujos (CRM-00.03.05): la lista entera,
      // no solo la bandeja de quien entra. «Aprobaciones» en la navegación
      // llevaba a la bandeja documental, que es otra cosa: estas son las del
      // proceso, con su delegación, su plazo y su decisión por enlace firmado.
      {
        nombre: "Aprobaciones",
        listar: "/api/v1/aprobaciones",
        // Lo que me toca decidir A MÍ, encima de todas las aprobaciones: la
        // lista entera dice qué hay parado y la bandeja, qué está parado por mí.
        resumen: ["/api/v1/aprobaciones/bandeja"],
        servicio: "orchestrator",
        permiso: "aprobacion:read",
        acciones: [
          {
            ruta: "/api/v1/aprobaciones/revisar-plazos",
            nombre: "Revisar plazos",
            detalle: "Avisa a los que van tarde y escala a los que ya se pasaron",
            permiso: "aprobacion:write",
          },
        ],
      },
      // **Quién decide por quién, y hasta cuándo** (CRM-00.03.05.08). Se podía
      // delegar la firma y no leerlo: «¿quién tiene hoy la de dirección?» es
      // la pregunta de cualquier revisión de poderes, y una delegación puesta
      // para agosto sigue viva en marzo sin que nadie lo note. Las caducadas
      // salen marcadas y no escondidas: una que acaba de vencer explica por
      // qué algo que antes salía solo ahora se queda parado.
      {
        nombre: "Delegaciones de firma",
        listar: "/api/v1/aprobaciones/delegaciones",
        servicio: "orchestrator",
        permiso: "aprobacion:read",
      },
      // Los enlaces que permiten decidir SIN entrar al CRM
      // (CRM-00.03.05.12): una credencial con patas. No se devuelve el token
      // —en la base sólo está su hash, y ése es el punto— sino a quién
      // representa, cuándo caduca y si ya se usó.
      {
        nombre: "Enlaces de decisión",
        listar: "/api/v1/aprobaciones/enlaces",
        servicio: "orchestrator",
        permiso: "aprobacion:read",
      },
    ],
  "modelo": [
      {
        nombre: "Objetos",
        // Con `objeto` para que la fila abra. Sin esto, el modelo de datos se
        // podía listar y nada más: los campos, las validaciones, los tipos de
        // registro, los límites y la trazabilidad del esquema no se alcanzaban
        // desde ninguna pantalla, aunque la API los publique entera.
        objeto: "objeto",
        listar: "/api/v1/metadata/objetos",
        // El mapa de relaciones del tenant, encima de los objetos: la lista dice
        // cuáles hay y el mapa cómo se enganchan, que es lo que se mira antes de
        // tocar una relación.
        resumen: ["/api/v1/metadata/relaciones/grafo"],
        servicio: "metadata",
        columnas: ["nombre", "etiqueta", "origen", "activo"],
      },
      {
        nombre: "Relaciones",
        listar: "/api/v1/metadata/relaciones",
        servicio: "metadata",
      },
      {
        nombre: "Tipos de relación",
        listar: "/api/v1/metadata/relaciones/tipos",
        servicio: "metadata",
      },
      // Qué vocabularios de negocio hay. Los valores de uno suelto ya se veían
      // —«Motivos de descarte»—, pero cuáles existen no: para saberlo había que
      // probar su ruta.
      //
      // Sólo `sales`, y no los tres que decía el contrato publicado: el router
      // se monta en el servicio que DECLARA alguno, y declararlos sólo los
      // declara ventas. El contrato anunciaba también los de `service` y
      // `tenancy` porque se construyen los catorce en el mismo proceso y el
      // registro era global; pedidas al servicio de verdad daban 404.
      {
        nombre: "Vocabularios de negocio",
        listar: "/api/v1/sales/vocabularios",
        servicio: "sales",
        permiso: "metadata:read",
      },
      // Qué objetos admite la búsqueda de cada servicio. Sin esto, la única
      // forma de saber si algo es buscable era buscarlo y ver si salía.
      {
        nombre: "Objetos buscables",
        listar: "/api/v1/:servicio/buscar/objetos",
        por_servicio: ["party", "sales"],
        servicio: "party",
        permiso: "metadata:read",
      },
      // Qué módulos del producto tiene puestos este cliente y cuáles hay para
      // instalar. Con `objeto` para que la fila abra: de un módulo cuelgan si
      // lo instalado es lo que se publicó y qué parte se usa de verdad, y a un
      // registro que no se abre no se llega.
      {
        nombre: "Módulos instalados",
        objeto: "modulo",
        resumen: ["/api/v1/metadata/modulos/catalogo"],
        listar: "/api/v1/metadata/modulos",
        servicio: "metadata",
        permiso: "metadata:read",
      },
      // Los entornos declarados. La pantalla de ALM los tenía escritos a mano
      // en un desplegable mientras el servidor los publicaba: un entorno nuevo
      // no aparecía hasta que alguien editara el front.
      {
        nombre: "Entornos",
        objeto: "entorno",
        listar: "/api/v1/entornos",
        servicio: "metadata",
        permiso: "metadata:read",
      },
      // Cómo se numera cada objeto: el patrón, el relleno, cuándo reinicia y
      // —lo que de verdad se viene a mirar— qué código saldría el siguiente.
      {
        nombre: "Numeración de negocio",
        // Los tres servicios que numeran objetos de negocio, no sólo ventas:
        // el código legible es del objeto y el objeto vive en su servicio, así
        // que `party` y `service` llevan el suyo y no se veían.
        listar: "/api/v1/:servicio/numeracion",
        por_servicio: ["sales", "party", "service"],
        servicio: "sales",
        permiso: "metadata:read",
      },
    ],
  "acceso": [
      {
        nombre: "Seguimientos",
        listar: "/api/v1/seguimientos",
        servicio: "identity",
      },
      {
        nombre: "Dispositivos de confianza",
        listar: "/api/v1/dispositivos-confianza",
        servicio: "identity",
      },
      {
        // Con `objeto` para que las referencias a personas —quién anotó esto,
        // de quién es esta cuota— se resuelvan a un buscador con nombres en vez
        // de dejar un identificador a la vista.
        nombre: "Usuarios",
        objeto: "usuario",
        listar: "/api/v1/usuarios",
      // Lo que se consume de licencias, encima de la lista: dar de alta a alguien
        // sin saber si quedan licencias es cómo se descubre el tope al revés.
      resumen: ["/api/v1/usuarios/licencias"],
        servicio: "identity",
        permiso: "user:read",
      },
      {
        nombre: "Roles",
        listar: "/api/v1/roles",
        servicio: "identity",
        permiso: "user:read",
      },
      {
        nombre: "Políticas de acceso",
        listar: "/api/v1/politicas-acceso",
        crear: "/api/v1/politicas-acceso/{nombre}",
        servicio: "identity",
        permiso: "user:read",
      },
      {
        nombre: "Claves de API",
        listar: "/api/v1/claves-api",
        servicio: "identity",
      },
      { nombre: "Sesiones", listar: "/api/v1/sesiones", servicio: "identity" },
      // A quién se le avisa de qué y por dónde. Los canales de entrega y cuántos
      // llegaron, se abrieron o rebotaron van encima: una preferencia sin saber
      // si el canal entrega es una casilla que no hace nada.
      {
        nombre: "Avisos y preferencias",
        objeto: "notificacion",
        resumen: [
          "/api/v1/notificaciones/canales",
          "/api/v1/notificaciones/entregas/estadisticas",
        ],
        listar: "/api/v1/notificaciones/preferencias",
        servicio: "identity",
        permiso: "user:read",
      },
      // Quién ve lo de quién por regla, no por jerarquía. Se publicaba y no
      // salía en ninguna parte: una regla de compartición que nadie ve es un
      // acceso concedido que nadie audita.
      {
        nombre: "Reglas de compartición",
        listar: "/api/v1/sharing-rules",
        crear: "/api/v1/sharing-rules",
        servicio: "identity",
        permiso: "sharing:read",
      },
      {
        nombre: "Proveedores de identidad",
        listar: "/api/v1/proveedores-identidad",
      // Qué perfiles hay declarados y qué comparte de verdad cada proveedor con la
        // suite: lo segundo es lo que se pregunta cuando alguien no aparece.
      resumen: ["/api/v1/proveedores-identidad/perfiles", "/api/v1/proveedores-identidad/suite"],
        servicio: "identity",
      },
    ],
  "operacion": [
      {
        nombre: "Modelo canónico",
        listar: "/api/v1/modelo-canonico/objetos",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Conflictos de sincronización",
        listar: "/api/v1/sincronizacion/conflictos",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Proveedores de servicio",
        listar: "/api/v1/proveedores-servicio",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Canales de chat",
        listar: "/api/v1/canales-chat",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Catálogo de eventos",
        listar: "/api/v1/eventos/catalogo",
        servicio: "eventing",
      },
      // La cola de fallidos delante del archivo: lo que hay que mirar cuando
      // algo va mal es lo que no salió, no lo que salió bien hace un mes.
      {
        nombre: "Cola de fallidos",
        listar: "/api/v1/eventos/fallidos",
        servicio: "eventing",
      },
      {
        nombre: "Archivo de eventos",
        listar: "/api/v1/eventos/archivo",
        servicio: "eventing",
      },
      // El encargo a un proveedor externo y su rastro (CRM-00.04.05): qué se
      // le pidió, por dónde va, qué incidencias lleva y qué documentos ha
      // devuelto. Doce operaciones publicadas y ninguna pantalla hasta hoy.
      {
        nombre: "Encargos a proveedor",
        listar: "/api/v1/encargos",
        servicio: "integration",
        permiso: "integracion:read",
        acciones: [
          {
            ruta: "/api/v1/encargos/revisar-silencios",
            nombre: "Revisar silencios",
            detalle: "Marca como mudo el encargo del que el proveedor no dice nada dentro de su plazo",
            permiso: "integracion:write",
          },
          {
            ruta: "/api/v1/encargos/conciliar",
            nombre: "Conciliar lo facturado",
            detalle: "Lo que el proveedor factura contra lo que consta entregado",
            permiso: "integracion:write",
          },
        ],
      },
      // Las tres vistas que convierten el encargo en algo operable: lo
      // entregado sin prueba, el cumplimiento por proveedor y los estados que
      // el proveedor manda y nadie ha mapeado todavía. Son hermanas del
      // listado, no hijas de un registro, así que se declaran.
      {
        nombre: "Encargos: entregados sin prueba",
        listar: "/api/v1/encargos/entregados-sin-prueba",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Encargos: cumplimiento por proveedor",
        listar: "/api/v1/encargos/cumplimiento",
        periodo: true,
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Encargos: estados sin mapear",
        listar: "/api/v1/encargos/estados-sin-mapear",
        servicio: "integration",
        permiso: "integracion:read",
      },
      // Las plantillas con las que se generan los documentos y la firma hecha
      // delante del cliente. Viven aquí, con la integración, porque es de ahí
      // de donde salen y hacia donde van.
      {
        nombre: "Plantillas de documento",
        listar: "/api/v1/plantillas-documento",
        servicio: "integration",
        permiso: "integracion:read",
      },
      // Los perfiles de suite y el consentimiento de cada usuario: el primero
      // es la declaración de qué sabe hacer un proveedor —endpoints, campos,
      // incremento y límites, como configuración y no como código—, y el
      // segundo es con qué permiso se conectó cada buzón. Los dos se listaban
      // por API y no salían en ninguna parte.
      {
        nombre: "Perfiles de suite",
        objeto: "perfil_suite",
        listar: "/api/v1/suites/perfiles",
        crear: "/api/v1/suites/perfiles",
        servicio: "integration",
        permiso: "integracion:read",
      },
      // Y los buzones de verdad: qué correo y qué calendario de quién está
      // conectado, con su estado. El consentimiento dice qué se autorizó; esto,
      // qué está entrando.
      {
        nombre: "Buzones conectados",
        objeto: "buzon",
        listar: "/api/v1/buzones",
      // Cómo va la sincronización y, sobre todo, qué NO está entrando: un buzón
        // conectado que lleva días sin traer nada se lee como que no hay correo.
      resumen: ["/api/v1/buzones/panel"],
        crear: "/api/v1/buzones",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Consentimiento de suite",
        listar: "/api/v1/suites/consentimiento",
        crear: "/api/v1/suites/consentimiento",
        servicio: "integration",
        permiso: "integracion:read",
      },
      // La firma electrónica entera estaba publicada y sin una sola pestaña:
      // los sobres, sus firmantes, sus recordatorios, su cancelación y su
      // evidencia legal. Con `objeto` la fila abre, y las acciones sobre un
      // sobre —mandarlo, recordar, cancelar, archivar el firmado— las resuelve
      // sola la ficha desde la superficie.
      {
        nombre: "Sobres de firma",
        objeto: "sobre_firma",
        listar: "/api/v1/firma/sobres",
        crear: "/api/v1/firma/sobres",
        servicio: "integration",
        columnas: ["referencia", "asunto", "estado", "nivel", "proveedor"],
        permiso: "integracion:read",
      },
      {
        nombre: "Proveedores de firma",
        listar: "/api/v1/firma/proveedores",
        crear: "/api/v1/firma/proveedores",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        nombre: "Firma presencial",
        listar: "/api/v1/firma-presencial",
        servicio: "integration",
        permiso: "firma:read",
      },
    ],
  "cuentas": [
      // **El plan de cada cuenta grande** (CRM-01.01.01.11): a dónde se quiere
      // llegar y qué falta. Se podía escribir y no leer, que es como se
      // escribe uno en la reunión de enero y nadie lo mira hasta la de enero
      // siguiente. Los objetivos y los riesgos van contados aparte: un plan
      // con cinco objetivos y ningún riesgo es optimista, y uno al revés es
      // una cuenta en problemas.
      {
        nombre: "Planes de cuenta",
        listar: "/api/v1/planes-cuenta",
        servicio: "party",
        permiso: "party:read",
      },
      // **El estado financiero replicado** (CRM-01.01.01.12), con la
      // antigüedad del dato delante: bloquear una oferta con una foto del ERP
      // de hace tres semanas es casi peor que no bloquear, porque el comercial
      // deja de creerse el bloqueo y entonces ya no sirve ninguno.
      {
        nombre: "Estado financiero",
        listar: "/api/v1/planes-cuenta/financiero",
        servicio: "party",
        permiso: "party:read",
      },
      // **Quién parece que ha cambiado de empresa** (CRM-01.01.02.07). Es la
      // mejor oportunidad que hay —conoce el producto y acaba de llegar a un
      // sitio donde no está— y el agujero de datos más común. Con su indicio,
      // porque no es lo mismo que rebote su correo que que alguien lo haya
      // visto en otra empresa: lo que se hace después es distinto.
      {
        nombre: "Cambios de empresa",
        listar: "/api/v1/cambios-de-empresa",
        servicio: "party",
        permiso: "party:read",
      },
      // Cuentas primero: es el módulo «Cuentas y contactos» y abría por la cola
      // de excepciones de calidad, así que lo primero al entrar en clientes era
      // una lista de problemas.
      {
        nombre: "Cuentas",
        objeto: "cuenta",
        listar: "/api/v1/accounts",
        crear: "/api/v1/accounts",
        servicio: "party",
        columnas: ["nombre", "estado", "sector_codigo", "owner_id"],
        permiso: "account:read",
      },
      // El plan de cuenta: a qué se ha comprometido el equipo con este cliente
      // este año. Se publicaba entero —plan, financiero, hitos— y no se llegaba
      // desde ninguna pantalla.
      {
        nombre: "Planes de cuenta",
        objeto: "plan_cuenta",
        listar: "/api/v1/planes-cuenta",
        crear: "/api/v1/planes-cuenta",
        servicio: "party",
        permiso: "party:read",
      },
      // Quién ha cambiado de empresa. Es calidad del dato y es una oportunidad:
      // un contacto que se va a otra cuenta se lleva la relación.
      {
        // El estado financiero de la cuenta, que es de donde sale si se le
        // puede vender más: un plan de cuenta sin eso es una lista de deseos.
        nombre: "Estado financiero",
        objeto: "plan_cuenta",
        listar: "/api/v1/planes-cuenta/financiero",
        servicio: "party",
        permiso: "party:read",
      },
      {
        nombre: "Cambios de empresa",
        objeto: "cambio_de_empresa",
        listar: "/api/v1/cambios-de-empresa",
        crear: "/api/v1/cambios-de-empresa",
        servicio: "party",
        permiso: "party:read",
      },
      {
        nombre: "Contactos",
        objeto: "contacto",
        listar: "/api/v1/contacts",
        crear: "/api/v1/contacts",
        servicio: "party",
        columnas: ["nombre_completo", "email", "telefono"],
        permiso: "contact:read",
      },
      {
        nombre: "Calidad del dato",
        listar: "/api/v1/calidad-dato/cola",
        // La salud del dato encima de la cola: la cola dice qué hay que tocar hoy;
        // la salud, si la cola está creciendo. Y qué reglas producen ruido en vez
        // de trabajo, que es lo que explica una cola que no baja. Con los pares
        // que parecen la misma persona y cuándo toca volver a preguntar fuera.
        resumen: ["/api/v1/calidad-dato/salud", "/api/v1/calidad-dato/metricas", "/api/v1/calidad-dato/reglas-sospechosas", "/api/v1/calidad-dato/uniones-propuestas", "/api/v1/calidad-dato/enriquecimiento/caducidad"],
        servicio: "party",
        permiso: "account:read",
      },
      {
        nombre: "Visitas",
        listar: "/api/v1/visitas",
        servicio: "party",
        permiso: "account:read",
      },
      {
        nombre: "Mapa de personas",
        listar: "/api/v1/mapa-personas",
        servicio: "party",
        permiso: "contact:read",
      },
      // LA COLA DE DUPLICADOS NO ES UNA PESTAÑA, y es una decisión, no un
      // olvido. Estuvo aquí hasta el 28-10-2026 y enseñaba exactamente la
      // misma colección que la pantalla «Duplicados por resolver», pero sin
      // poder decidir ninguna: quien entraba por aquí veía dieciocho parejas,
      // no podía hacer nada con ellas y **no sabía que existía el otro sitio**.
      //
      // No eran dos vistas del mismo dato: era la misma vista, una capada. La
      // misma colección en dos sitios sólo se sostiene cuando cada uno
      // contesta una pregunta distinta —la ficha enseña los casos DE ESA
      // CUENTA, el tablero enseña las oportunidades COMO EMBUDO—, y aquí no
      // la había.
      {
        nombre: "Derechos del interesado",
        objeto: "solicitud_derechos",
        listar: "/api/v1/data-subject-requests",
        crear: "/api/v1/data-subject-requests",
        servicio: "party",
        columnas: [
          "tipo",
          "email_solicitante",
          "estado",
          "vence_at",
          "dias_restantes",
        ],
      },
      {
        nombre: "Papelera",
        icono: "delete",
        // Con `objeto` para que cada fila se pueda abrir: «Restaurar» cuelga de
        // la entrada, y a una entrada que no se abre no se llega desde ninguna
        // pantalla. Estaba la acción y no había forma de usarla.
        objeto: "entrada_papelera",
        // La del router compartido, la misma forma que las demás: `party-admin`
        // tiene la suya de antes y dos caminos para lo mismo obligan a saber
        // cuál mira cada pantalla.
        listar: "/api/v1/party/papelera",
        servicio: "party",
        columnas: [
          "etiqueta",
          "objeto",
          "borrado_at",
          "dias_para_purga",
          "en_cascada",
        ],
      },
    ],
  "proveedores": [
      {
        nombre: "Proveedores",
        objeto: "proveedor",
        listar: "/api/v1/proveedores",
        servicio: "party",
        columnas: [
          "nombre",
          "estado",
          "sector_codigo",
          "telefono",
          "email",
          "owner_id",
        ],
        permiso: "party:read",
      },
      {
        nombre: "Documentos que vencen",
        listar: "/api/v1/proveedores/documentos/vencen",
        servicio: "party",
        // Cada fila es un documento de un proveedor, así que abre **al
        // proveedor**: es donde se sube el renovado. Sin esto la pantalla
        // enseñaba el problema y no había por dónde ir a arreglarlo.
        abre: {
          modulo: "proveedores",
          objeto: "proveedor",
          campo: "cuenta_id",
        },
        columnas: ["estado", "proveedor", "documento", "valido_hasta", "dias"],
        permiso: "party:read",
      },
    ],
  "actividades": [
      {
        nombre: "Plantillas",
        listar: "/api/v1/plantillas-actividad",
        servicio: "party",
        permiso: "activity:read",
      },
      {
        nombre: "Recurrencias",
        listar: "/api/v1/recurrencias",
        servicio: "party",
        permiso: "activity:read",
      },
      {
        nombre: "Actividades",
        objeto: "actividad",
        listar: "/api/v1/activities",
        crear: "/api/v1/activities",
        servicio: "party",
        columnas: ["asunto", "tipo", "estado", "vence_at"],
        permiso: "activity:read",
      },
    ],
  "oportunidades": [
      {
        nombre: "Ofertas",
        objeto: "presupuesto",
        listar: "/api/v1/presupuestos",
        servicio: "sales",
        permiso: "quote:read",
        columnas: ["codigo", "estado", "total", "moneda", "valido_hasta"],
      },
      // El plan conjunto: lo acordado CON el cliente, con su calibración. Es
      // del mismo ciclo que la oferta y el pedido, y se publicaba sin pestaña.
      {
        nombre: "Planes conjuntos",
        objeto: "plan_conjunto",
        listar: "/api/v1/planes-conjuntos",
      // Cuánto se parece lo que se dice en las revisiones a lo que luego pasa, y
        // qué lleva demasiado sin revisarse: un plan conjunto que nadie revisa es
        // un documento, no un acuerdo.
      resumen: ["/api/v1/planes-conjuntos/calibracion", "/api/v1/planes-conjuntos/sin-revisar"],
        crear: "/api/v1/planes-conjuntos",
        servicio: "sales",
        permiso: "sales:read",
      },
      {
        nombre: "Pedidos",
        objeto: "pedido",
        listar: "/api/v1/pedidos",
      // Los pedidos de los que el ERP no ha dicho nada: no salen como un estado
        // del pedido, salen de comparar, y sin esto no los ve nadie.
      resumen: ["/api/v1/pedidos/conciliacion-erp"],
        servicio: "sales",
        permiso: "order:read",
      },
      {
        nombre: "Contratos",
        objeto: "contrato",
        listar: "/api/v1/contratos",
        servicio: "sales",
        permiso: "contract:read",
      },
      {
        nombre: "Suscripciones",
        listar: "/api/v1/suscripciones",
      // MRR y ARR encima de las suscripciones: es la cifra por la que se mira esta
        // lista, y calcularla a mano desde las filas es cómo salen dos números.
      resumen: ["/api/v1/suscripciones/recurrente"],
        servicio: "sales",
        permiso: "contract:read",
      },
      {
        nombre: "Productos",
        objeto: "producto",
        listar: "/api/v1/productos",
        servicio: "sales",
        permiso: "producto:read",
      },
      {
        nombre: "Listas de precio",
        listar: "/api/v1/listas-precio",
        servicio: "sales",
        permiso: "producto:read",
      },
      {
        nombre: "Metodologías",
        listar: "/api/v1/metodologias",
        servicio: "sales",
      },
      { nombre: "Mi cola", listar: "/api/v1/mi-cola", servicio: "sales" },
      {
        nombre: "Papelera",
        icono: "delete",
        objeto: "entrada_papelera",
        listar: "/api/v1/sales/papelera",
        servicio: "sales",
        columnas: [
          "etiqueta",
          "objeto",
          "borrado_at",
          "dias_para_purga",
          "en_cascada",
        ],
      },
      {
        nombre: "Oportunidades",
        objeto: "oportunidad",
        listar: "/api/v1/opportunities",
        crear: "/api/v1/opportunities",
        servicio: "sales",
        columnas: ["nombre", "etapa", "importe", "fecha_cierre", "estado"],
        permiso: "opportunity:read",
      },
      // «Procesos de venta» y no «Pipelines»: esto es la CONFIGURACIÓN de las
      // etapas, no el tablero donde se mueven las oportunidades. Llamar a las
      // dos cosas «pipeline» hace que quien busca el tablero acabe en una tabla
      // de definiciones y concluya que el tablero ya no está.
      {
        nombre: "Procesos de venta",
        objeto: "pipeline",
        listar: "/api/v1/pipelines",
        servicio: "sales",
        columnas: ["nombre", "descripcion", "activo", "por_defecto"],
      },
      {
        // Al vocabulario y no a `/pipeline/motivos-perdida`: esa ruta solo los
        // enseña. La empresa decide los suyos, y esta pestaña es donde lo hace.
        nombre: "Motivos de pérdida",
        listar: "/api/v1/sales/vocabularios/motivos_perdida",
        servicio: "sales",
        columnas: ["etiqueta", "valor", "orden", "activo", "de_fabrica"],
      },
    ],
  "leads": [
      { nombre: "Cadencias", listar: "/api/v1/cadencias", servicio: "sales" },
      {
        nombre: "Plantillas de correo",
        listar: "/api/v1/plantillas-correo",
      // Qué plantillas funcionan, encima de las plantillas: la lista las ordena
        // por nombre y la pregunta es cuál usar.
      resumen: ["/api/v1/plantillas-correo/rendimiento"],
        servicio: "sales",
      },
      {
        nombre: "Leads",
        objeto: "lead",
        listar: "/api/v1/leads",
        crear: "/api/v1/leads",
        servicio: "sales",
        columnas: ["nombre", "empresa", "estado", "puntuacion"],
        permiso: "lead:read",
      },
      {
        nombre: "Enrutamiento",
        // Qué estrategias de reparto hay, encima de las reglas que las usan:
        // sin ellas, escribir una regla es adivinar qué valores admite.
        resumen: ["/api/v1/lead-routing/estrategias"],
        listar: "/api/v1/lead-routing/reglas",
        servicio: "sales",
      },
      {
        nombre: "Canales de captura",
        listar: "/api/v1/captura/canales",
        servicio: "sales",
      },
      {
        nombre: "Recepciones",
        listar: "/api/v1/captura/recepciones",
        servicio: "sales",
      },
      {
        nombre: "Motivos de descarte",
        listar: "/api/v1/sales/vocabularios/motivos_descarte",
        servicio: "sales",
        columnas: ["etiqueta", "valor", "orden", "activo", "de_fabrica"],
      },
      {
        nombre: "Campañas de origen",
        listar: "/api/v1/origen/campanas",
        servicio: "sales",
      },
      { nombre: "Toques", listar: "/api/v1/origen/toques", servicio: "sales" },
    ],
  "prevision": [
      {
        nombre: "Territorios",
        objeto: "territorio",
        listar: "/api/v1/territorios",
        servicio: "sales",
      },
      // El módulo enseñaba el resumen del pipeline y llamaba a eso «Previsión».
      // Las categorías, los periodos y las cuotas —que es con lo que se hace
      // una previsión— no tenían pantalla ninguna.
      {
        nombre: "Categorías",
        listar: "/api/v1/forecast/categorias",
        servicio: "sales",
        permiso: "forecast:read",
      },
      {
        nombre: "Periodos",
        listar: "/api/v1/forecast/periodos",
        servicio: "sales",
        permiso: "forecast:read",
      },
      {
        nombre: "Cuotas",
        listar: "/api/v1/cuotas",
        servicio: "sales",
        permiso: "forecast:read",
      },
      {
        nombre: "Consecución",
        listar: "/api/v1/cuotas/consecucion",
        servicio: "sales",
        permiso: "forecast:read",
      },
      {
        nombre: "Ingreso previsto",
        listar: "/api/v1/ingresos/previsto",
        servicio: "sales",
        permiso: "forecast:read",
      },
      {
        nombre: "Resumen del pipeline",
        listar: "/api/v1/pipeline/resumen",
        servicio: "sales",
        permiso: "opportunity:read",
      },
      // Las estancadas delante del resumen no: el resumen es lo que se mira
      // cada día y esto es lo que se mira cuando el resumen no cuadra.
      {
        nombre: "Estancadas",
        listar: "/api/v1/pipeline/estancadas",
        servicio: "sales",
      },
      // Qué periodos tienen el objetivo cerrado, con quién lo cerró, cuándo y
      // por qué —y los que se reabrieron, con su motivo—. Es el historial, no
      // un interruptor: reabrir a mitad de año es legítimo y tiene que
      // quedar rastro.
      {
        nombre: "Objetivos congelados",
        listar: "/api/v1/cuotas/congelaciones",
        servicio: "sales",
        permiso: "forecast:read",
      },
    ],
  "canal": [
      {
        nombre: "Portal del partner",
        listar: "/api/v1/portal-partner/mis-registros",
        servicio: "sales",
        permiso: "partner:read",
      },
      {
        nombre: "Partners",
        objeto: "partner",
        listar: "/api/v1/partners",
        crear: "/api/v1/partners",
        servicio: "sales",
        columnas: ["clave", "nombre", "tipo", "canal", "estado"],
        permiso: "partner:read",
      },
      // Los registros delante de los niveles: es lo que se mira todos los días,
      // y es donde aparece el conflicto entre dos partners, que es lo que hay
      // que decidir hoy y no la semana que viene.
      {
        nombre: "Registros de oportunidad",
        listar: "/api/v1/registros-oportunidad",
        servicio: "sales",
        columnas: [
          "cliente",
          "estado",
          "importe_estimado",
          "protegido_hasta",
          "en_conflicto",
        ],
        permiso: "partner:read",
      },
      {
        nombre: "Niveles",
        objeto: "nivel",
        listar: "/api/v1/niveles-partner",
        servicio: "sales",
      },
      {
        nombre: "Certificaciones por caducar",
        listar: "/api/v1/partners/certificaciones/por-caducar",
        servicio: "sales",
      },
      {
        nombre: "Fondos de marketing",
        objeto: "fondo",
        listar: "/api/v1/fondos-mdf",
        crear: "/api/v1/fondos-mdf",
        servicio: "marketing",
        columnas: ["nombre", "desde", "hasta", "asignado", "moneda", "cerrado"],
        permiso: "campaign:read",
      },
      {
        nombre: "Solicitudes de fondos",
        listar: "/api/v1/solicitudes-mdf",
        servicio: "marketing",
        columnas: [
          "titulo",
          "estado",
          "solicitado",
          "aprobado",
          "justificado",
          "justificar_antes_de",
        ],
      },
      // Las liquidaciones cuelgan del canal *y* de la retribución interna: es
      // el mismo motor, y enseñarlas dos veces daría dos listas del mismo dinero.
      {
        nombre: "Liquidaciones",
        listar: "/api/v1/liquidaciones",
        servicio: "sales",
        columnas: [
          "estado",
          "desde",
          "hasta",
          "total",
          "moneda",
          "pago_referencia",
        ],
        permiso: "commission:read",
      },
      {
        nombre: "Planes de comisión",
        listar: "/api/v1/planes-comision",
        servicio: "sales",
      },
    ],
  "campo": [
      {
        nombre: "Órdenes de trabajo",
        listar: "/api/v1/ordenes-trabajo",
        crear: "/api/v1/ordenes-trabajo",
        servicio: "service",
        columnas: [
          "codigo",
          "titulo",
          "tipo",
          "estado",
          "prioridad",
          "cita_desde",
        ],
        permiso: "case:read",
      },
      {
        nombre: "Activos instalados",
        objeto: "activo",
        listar: "/api/v1/activos",
        crear: "/api/v1/activos",
        servicio: "service",
        columnas: [
          "codigo",
          "nombre",
          "modelo",
          "numero_serie",
          "estado",
          "ubicacion",
        ],
        permiso: "case:read",
      },
      {
        nombre: "Técnicos",
        objeto: "tecnico",
        listar: "/api/v1/tecnicos-campo",
        servicio: "service",
      },
      // El preventivo por delante de los repuestos: es lo que hay que mirar cada
      // semana, y los repuestos solo cuando falta uno.
      {
        nombre: "Planes preventivos",
        objeto: "plan_preventivo",
        listar: "/api/v1/planes-preventivos",
        servicio: "service",
      },
      {
        nombre: "Vencimientos",
        listar: "/api/v1/planes-preventivos/vencimientos",
        servicio: "service",
      },
      { nombre: "Repuestos", listar: "/api/v1/repuestos", servicio: "service" },
      {
        nombre: "Reposición",
        listar: "/api/v1/repuestos/reposicion",
        servicio: "service",
      },
      // Cada entrada y salida del almacén móvil, con su porqué. Se escribía y
      // **no lo leía nadie**: un almacén sin histórico no se puede cuadrar, y
      // cuando falta una pieza la pregunta es quién se la llevó y cuándo.
      {
        nombre: "Movimientos de almacén",
        listar: "/api/v1/repuestos/movimientos",
        servicio: "service",
        columnas: ["tipo", "cantidad", "motivo", "dejo_negativo", "cuando"],
      },
      {
        nombre: "Garantías por vencer",
        listar: "/api/v1/activos/garantias/por-vencer",
        servicio: "service",
      },
      {
        nombre: "Dispositivos",
        listar: "/api/v1/dispositivos",
        servicio: "integration",
      },
      {
        nombre: "Aparatos callados",
        listar: "/api/v1/dispositivos/silenciosos",
        servicio: "integration",
      },
    ],
  "postventa": [
      {
        nombre: "Devoluciones",
        objeto: "devolucion",
        listar: "/api/v1/devoluciones",
        crear: "/api/v1/devoluciones",
        servicio: "service",
        columnas: [
          "codigo",
          "estado",
          "motivo",
          "fuera_de_plazo",
          "disposicion",
        ],
        permiso: "case:read",
      },
      // Los expedientes ordenados por vencimiento, y los vencidos aparte: el
      // plazo legal no es una cola de trabajo, es una fecha que se pasa.
      {
        nombre: "Expedientes",
        listar: "/api/v1/expedientes",
        servicio: "service",
        columnas: [
          "codigo",
          "asunto",
          "estado",
          "via",
          "vence_at",
          "sin_acuse",
        ],
      },
      {
        nombre: "Vencen pronto",
        listar: "/api/v1/expedientes/vencen",
        servicio: "service",
      },
      {
        nombre: "Problemas",
        listar: "/api/v1/problemas",
        servicio: "service",
        columnas: [
          "codigo",
          "titulo",
          "estado",
          "severidad",
          "error_conocido",
          "solo_apano",
        ],
      },
      {
        nombre: "Correlación",
        listar: "/api/v1/problemas/correlacion",
        servicio: "service",
      },
    ],
  "ia": [
      // Quién presta el servicio, con qué modelo y a qué coste. Es la primera
      // pregunta de cualquiera que firme una factura de IA.
      {
        nombre: "Proveedores de IA",
        listar: "/api/v1/ia/proveedores",
        servicio: "intelligence",
        permiso: "ia:administrar",
      },
      {
        nombre: "Modelos",
        listar: "/api/v1/ia/modelos",
        servicio: "intelligence",
        permiso: "ia:administrar",
      },
      // Cómo ha ido acertando cada modelo con el tiempo. Las mediciones se
      // anotaban desde el primer día y **no las leía nadie**: había ruta para
      // escribir una y ninguna para verlas, así que se medía la deriva y no se
      // miraba — que es lo contrario de para lo que se mide.
      // Los resúmenes propuestos de una conversación, con lo que quedó
      // pendiente. Se escribían y **no los leía nadie**: se generaban, se
      // pagaban al proveedor de IA y se quedaban en una tabla sin puerta.
      {
        nombre: "Resúmenes de conversación",
        listar: "/api/v1/ia/conversacion/resumenes",
        servicio: "intelligence",
        columnas: ["momento", "parcial", "mensajes_usados", "mensajes_totales", "estado"],
        permiso: "ia:usar",
      },
      {
        nombre: "Deriva de los modelos",
        listar: "/api/v1/ia/modelos/deriva",
        servicio: "intelligence",
        columnas: ["metrica", "valor", "referencia", "caida", "muestras", "hasta"],
        permiso: "ia:administrar",
      },
      // Un agente autónomo que nadie ve es un proceso con permisos corriendo
      // solo. Aquí se ve cuáles hay, y desde la ficha se apagan.
      {
        nombre: "Agentes autónomos",
        listar: "/api/v1/ia/agentes-autonomos",
        servicio: "intelligence",
        permiso: "ia:administrar",
        acciones: [
          {
            ruta: "/api/v1/ia/agentes-autonomos/herramientas-desde-contrato",
            nombre: "Herramientas desde el contrato",
            detalle: "Las saca de las propias operaciones publicadas, en vez de escribirlas a mano",
            permiso: "ia:administrar",
          },
        ],
      },
      {
        nombre: "Anomalías",
        // Si los avisos sirven de algo, encima de los avisos. Un detector que
        // nadie confirma nunca es un detector que se acaba ignorando.
        resumen: ["/api/v1/ia/anomalias/utilidad"],
        listar: "/api/v1/ia/anomalias",
        servicio: "intelligence",
        permiso: "ia:usar",
      },
      // **Qué dice cada guardarraíl**, no sólo cuántas veces ha saltado
      // (CRM-05.02.02.07). Se podían declarar y no leer: se veía que algo
      // había cortado mil peticiones y no qué sensibilidades deja pasar, qué
      // patrones tapa ni si corta la petición o sólo enmascara el dato — que
      // no es lo mismo. Sin ninguna regla NO se dice «todo bien»: se dice que
      // manda el comportamiento por defecto, que es que lo personal y lo
      // especial no salen.
      {
        nombre: "Guardarraíles",
        listar: "/api/v1/ia/guardias",
        servicio: "intelligence",
        permiso: "ia:administrar",
      },
      // Con qué texto se le pide al modelo, en su versión vigente. La
      // plantilla ES la instrucción: cuando una respuesta empieza a salir mal,
      // la primera pregunta es qué se le está pidiendo exactamente, y hasta
      // hoy había que mirarlo en la base de datos.
      {
        nombre: "Plantillas del modelo",
        listar: "/api/v1/ia/plantillas",
        servicio: "intelligence",
        permiso: "ia:administrar",
      },
      // Lo que las guardias NO dejaron pasar. Una guardia sin registro es una
      // promesa: nadie sabe si ha actuado nunca.
      {
        nombre: "Bloqueos de las guardias",
        listar: "/api/v1/ia/guardias/bloqueos",
        servicio: "intelligence",
        permiso: "ia:administrar",
      },
      // Las dos caras del gasto: el total con su tasa de descarte —cuánto de
      // lo que se paga se tira— y la curva por día, que es donde se ve el
      // salto del martes que nadie pidió.
      {
        nombre: "Consumo y coste",
        // Con el presupuesto del mes encima: el coste acumulado no dice si
        // queda margen, y «queda margen» es la decisión.
        resumen: ["/api/v1/ia/presupuesto", "/api/v1/ia/eleccion"],
        listar: "/api/v1/ia/uso",
        servicio: "intelligence",
        permiso: "ia:administrar",
      },
      {
        nombre: "Uso por día",
        listar: "/api/v1/ia/uso/por-dia",
        servicio: "intelligence",
        permiso: "ia:administrar",
      },
      // Cuentas que el modelo marca en riesgo, que es la lista sobre la que se
      // trabaja; la salud de una cuenta suelta ya se ve en su pantalla.
      {
        // La salud de TODAS las cuentas, no sólo las que están en riesgo: la
        // lista de riesgo dice a quién llamar hoy y ésta si el modelo está
        // midiendo algo. Con la calidad de lo que propone encima.
        nombre: "Salud de cuentas",
        resumen: ["/api/v1/ia/calidad"],
        listar: "/api/v1/ia/salud",
        servicio: "intelligence",
      },
      {
        nombre: "Predicciones",
        listar: "/api/v1/ia/prediccion",
        servicio: "intelligence",
      },
      {
        // Lo que la extracción ha sacado de documentos y correos, con sus
        // conflictos: un campo extraído que choca con lo que hay guardado es
        // una decisión de alguien, no un dato que se pisa solo.
        nombre: "Campos extraídos",
        resumen: ["/api/v1/ia/extraidos"],
        listar: "/api/v1/ia/extraidos",
        servicio: "intelligence",
      },
      {
        nombre: "Cuentas en riesgo",
        listar: "/api/v1/ia/salud/riesgo",
        servicio: "intelligence",
        permiso: "ia:usar",
      },
      // Herramientas que exponemos a agentes de fuera por MCP. Vive en
      // integración y se gobierna aquí: lo que se decide es a qué puede llegar
      // un agente que no es nuestro.
      {
        nombre: "Exposiciones MCP",
        listar: "/api/v1/agentes-ia/exposiciones",
        servicio: "integration",
        permiso: "integracion:read",
      },
    ],
  "explotacion": [
      // La explotación la resuelve contecintelligence de forma frontless
      // (RT-4). Aquí se enseña el estado del enlace y lo que se ha consultado:
      // los informes se abren allí, con la identidad del usuario.
      {
        nombre: "Estado del enlace",
        listar: "/api/v1/analitica/estado",
        servicio: "analytics",
      },
      {
        nombre: "Consultas",
        listar: "/api/v1/analitica/consultas",
        servicio: "analytics",
      },
      {
        nombre: "Organizaciones",
        listar: "/api/v1/analitica/organizaciones",
        servicio: "analytics",
        solo_plataforma: true,
      },
      // El diccionario de métricas delante de las tablas: la pregunta que abre
      // la discusión es «¿qué quiere decir ingresos?», no «¿qué tablas hay?».
      {
        nombre: "Métricas",
        listar: "/api/v1/metricas",
        // Con alta y con ficha. La API tenía definir, certificar, versionar y
        // plan desde el principio, y el front solo listaba: se veía el
        // diccionario y no se podía tocar nada. La ficha sale de que exista un
        // `GET /metricas/{clave}`, que es lo que faltaba al otro lado.
        crear: "/api/v1/metricas",
        objeto: "metrica",
        servicio: "analytics",
        columnas: ["clave", "nombre", "estado", "objeto", "agregacion", "unidad"],
      },
      // Qué hay en el almacén y de dónde sale. La frescura decía si estaba al
      // día sin decir de QUÉ, así que el almacén se miraba por su síntoma.
      {
        nombre: "Tablas del almacén",
        objeto: "tabla_analitica",
        listar: "/api/v1/almacen/tablas",
        // Qué se puede explotar de este tenant y cómo se describe el CRM para poder
        // preguntarle: es lo que decide si una pregunta en lenguaje natural tiene
        // alguna posibilidad de contestarse.
        resumen: ["/api/v1/analitica/modelo-semantico", "/api/v1/explotacion/descripcion"],
        servicio: "analytics",
        permiso: "informe:read",
      },
      {
        // Lo que se consulta sin copiarlo: una fuente federada que falla no
        // deja un hueco en una tabla, deja un informe en error.
        nombre: "Fuentes federadas",
        objeto: "tabla_analitica",
        listar: "/api/v1/almacen/federadas",
        servicio: "analytics",
        permiso: "informe:read",
      },
      // **Dónde puede vivir el CRM embebido** (CRM-05.01.02.06). Se podía
      // declarar y no leer, y es un control de seguridad: la lista de orígenes
      // es lo que impide que cualquier página incruste el CRM y le pida datos
      // con la sesión de quien la abra. Un origen que alguien puso para una
      // prueba hace año y medio sigue valiendo y nadie lo sabe. Los orígenes
      // se nombran, no se cuentan: lo que se revisa es si alguno sobra.
      {
        nombre: "Sitios donde se embebe",
        listar: "/api/v1/federacion/embebidos",
        servicio: "integration",
        permiso: "integracion:read",
      },
      {
        // admite: un enlace embebido es una ventana al dato desde fuera, y
        // quién tiene una abierta es justo lo que hay que poder mirar.
        nombre: "Cuadros incrustados",
        objeto: "enlace_embebido",
        resumen: ["/api/v1/cuadros-mando/componentes"],
        listar: "/api/v1/cuadros-mando/embebidos",
        servicio: "analytics",
        permiso: "informe:read",
      },
      // Qué informe sale solo, cuándo y **a quién** (CRM-05.01.01.06). Se
      // podía programar un envío y no leer ninguna de esas cuatro cosas: ni
      // quién lo recibe, ni si uno que ya no mira nadie se sigue mandando
      // todas las semanas. Un envío semanal a una lista que nadie revisó en
      // dos años es la forma más habitual de que un dato salga de donde debía
      // quedarse.
      {
        nombre: "Informes programados",
        listar: "/api/v1/informes/programaciones",
        servicio: "analytics",
        permiso: "informe:read",
      },
      {
        // Cada vez que se corrió un informe, con lo que costó. La tabla es
        // append-only y **no la leía nadie**: se escribía en cada ejecución y
        // ninguna ruta la devolvía, así que el coste se guardaba y no se podía
        // mirar. El peor caso va al lado de la media, porque la media esconde
        // justo el informe que tarda dos minutos una vez al día.
        nombre: "Ejecuciones de informe",
        listar: "/api/v1/informes/ejecuciones",
        servicio: "analytics",
        columnas: ["origen", "filas", "duracion_ms", "truncado", "ok", "cuando"],
        permiso: "informe:read",
      },
      {
        nombre: "Frescura del almacén",
        listar: "/api/v1/almacen/frescura",
        servicio: "analytics",
        acciones: [
          {
            ruta: "/api/v1/almacen/cargar",
            nombre: "Cargar ahora",
            detalle:
              "Trae las filas de cada tabla declarada. Hasta que alguien lo hace, el almacén está vacío y los informes no tienen de dónde leer.",
            permiso: "informe:write",
          },
        ],
      },
      {
        nombre: "Exportaciones",
        listar: "/api/v1/almacen/destinos",
        servicio: "analytics",
      },
      {
        nombre: "Despliegue de BI",
        listar: "/api/v1/analisis/despliegue",
        servicio: "analytics",
      },
    ],
  "gobierno": [
      {
        nombre: "Riesgos",
        listar: "/api/v1/grc/riesgos",
        // El panel de GRC encima de los riesgos: lo que no cuadra HOY, ordenado
        // por lo que urge, y qué del producto tiene control y qué no. Un
        // registro de riesgos sin eso es un inventario que nadie recorre.
        resumen: ["/api/v1/grc/panel", "/api/v1/grc/pendiente", "/api/v1/grc/cobertura"],
        servicio: "tenancy",
        columnas: [
          "codigo",
          "titulo",
          "inherente",
          "residual",
          "tratamiento",
          "estado",
        ],
        permiso: "tenant:read",
      },
      {
        nombre: "Controles",
        listar: "/api/v1/grc/controles",
        // Del marco normativo a las capacidades que lo sostienen: un control sin
        // saber a qué marco responde es trabajo que nadie sabe por qué se hace.
        resumen: ["/api/v1/grc/marcos"],
        servicio: "tenancy",
        columnas: ["codigo", "nombre", "tipo", "frecuencia", "activo"],
        permiso: "tenant:read",
      },
      {
        nombre: "Segregación",
        listar: "/api/v1/segregacion/reglas",
      // Las excepciones aprobadas, con la regla al lado: una regla de segregación
        // sin ver sus excepciones dice lo contrario de lo que pasa de verdad.
      resumen: ["/api/v1/segregacion/excepciones"],
        servicio: "identity",
      },
      // Las tres apuntaban a `party` y se llamaban «Retención», «Bloqueos
      // legales» y «Clases de dato»: quien las abría creía ver las de todo el
      // sistema y veía las de clientes. Las de identidad y las de ventas no
      // tenían pantalla. Cada servicio guarda las suyas en su esquema, así que
      // la pestaña lleva selector en vez de apuntar a una.
      {
        nombre: "Retención",
        listar: "/api/v1/:servicio/retencion/politicas",
        por_servicio: ["party", "identity", "sales"],
        servicio: "party",
      },
      {
        nombre: "Bloqueos legales",
        listar: "/api/v1/:servicio/retencion/bloqueos",
        por_servicio: ["party", "identity", "sales"],
        servicio: "party",
      },
      {
        nombre: "Clases de dato",
        listar: "/api/v1/:servicio/retencion/clases",
        por_servicio: ["party", "identity", "sales"],
        servicio: "party",
      },
    ],
  "segmentos": [
      {
        nombre: "Segmentos",
        objeto: "segmento",
        listar: "/api/v1/segmentos",
        crear: "/api/v1/segmentos",
        servicio: "marketing",
        columnas: ["clave", "nombre", "objeto", "tamano", "tamano_at"],
        permiso: "segmento:read",
      },
      {
        nombre: "Supresiones",
        listar: "/api/v1/supresiones",
        servicio: "marketing",
      },
      {
        nombre: "Puntuación",
        listar: "/api/v1/puntuacion/modelos",
      // Cuántos leads llevan una versión vieja del modelo: activar una versión
        // nueva no repuntúa lo anterior, y eso no se ve en la lista de modelos.
      resumen: ["/api/v1/puntuacion/pendientes"],
        servicio: "marketing",
      },
      // Los activos de marketing con su revisión y su aprobación: qué se
      // puede usar, desde cuándo y hasta cuándo.
      // Quién tiene que aprobar qué, antes de publicarlo. La lista de activos
      // dice lo que hay; ésta, lo que está parado esperando a alguien.
      {
        nombre: "Aprobaciones de activos",
        objeto: "activo_marketing",
        listar: "/api/v1/activos-marketing/aprobacion",
        servicio: "marketing",
        permiso: "marketing:read",
      },
      {
        nombre: "Activos de marketing",
        listar: "/api/v1/activos-marketing",
        // Qué hay que mirar antes de que dé un problema: un activo caducado que
        // sigue publicado no avisa solo.
        resumen: ["/api/v1/activos-marketing/revision"],
        servicio: "marketing",
        permiso: "marketing:read",
      },
    ],
  "campanas": [
      {
        nombre: "Papelera",
        icono: "delete",
        objeto: "entrada_papelera",
        listar: "/api/v1/marketing/papelera",
        servicio: "marketing",
        columnas: [
          "etiqueta",
          "objeto",
          "borrado_at",
          "dias_para_purga",
          "en_cascada",
        ],
      },
      // Qué hay en marcha y qué se solapa. Dos campañas al mismo público la
      // misma semana no dan error: dan una tasa de baja que nadie explica.
      {
        nombre: "Calendario de campañas",
        listar: "/api/v1/campanas/calendario",
        periodo: true,
        servicio: "marketing",
        permiso: "campaign:read",
      },
      {
        nombre: "Campañas",
        objeto: "campana",
        listar: "/api/v1/campanas",
        crear: "/api/v1/campanas",
        servicio: "marketing",
        columnas: ["nombre", "estado", "canal", "desde", "hasta"],
        permiso: "campana:read",
      },
      // La atribución NO se lista: se consulta por lead (`/atribucion/leads/{id}`).
      // Ponerla aquí como lista sería inventar un endpoint que no existe, y el
      // gate del front lo caza — que es para lo que está.
      {
        nombre: "Presión de contacto",
        listar: "/api/v1/presion/reglas",
      // A cuánta gente se ha escrito y cuántas veces, encima de las reglas que lo
        // limitan: una regla de presión sin la presión medida es una promesa.
      resumen: ["/api/v1/presion"],
        servicio: "marketing",
      },
      {
        nombre: "Rebotes",
        // Las tasas con su umbral al lado: una lista de rebotes no dice si se
        // está cerca de que el proveedor corte el envío, y eso es lo que decide.
        resumen: ["/api/v1/rebotes/salud"],
        listar: "/api/v1/rebotes",
        servicio: "marketing",
      },
      // El recorrido automatizado (CRM-02.02.02): sus nodos, sus inscritos,
      // su embudo y su publicación. Catorce operaciones sin pantalla.
      {
        nombre: "Recorridos",
        listar: "/api/v1/recorridos",
        servicio: "marketing",
        permiso: "campana:read",
      },
    ],
  "casos": [
      // CSAT, CES y NPS del periodo, juntos: mirarlos por separado es cómo se
      // acaba citando el que mejor sale.
      {
        nombre: "Satisfacción del periodo",
        listar: "/api/v1/encuestas/resumen",
        periodo: true,
        servicio: "service",
        permiso: "case:read",
      },
      {
        nombre: "Encuestas",
        objeto: "encuesta",
        listar: "/api/v1/encuestas",
        servicio: "service",
      },
      {
        nombre: "Agentes disponibles",
        listar: "/api/v1/agentes/disponibles",
        servicio: "service",
      },
      {
        nombre: "Papelera",
        icono: "delete",
        objeto: "entrada_papelera",
        listar: "/api/v1/service/papelera",
        servicio: "service",
        columnas: [
          "etiqueta",
          "objeto",
          "borrado_at",
          "dias_para_purga",
          "en_cascada",
        ],
      },
      {
        nombre: "Casos",
        objeto: "caso",
        listar: "/api/v1/casos",
        crear: "/api/v1/casos",
        servicio: "service",
        columnas: ["codigo", "asunto", "estado", "prioridad"],
        permiso: "case:read",
      },
      {
        nombre: "Categorías",
        objeto: "categoria",
        listar: "/api/v1/categorias-caso",
        servicio: "service",
      },
      // El cumplimiento del periodo: los acuerdos dicen a qué nos
      // comprometimos y esto si se cumplió. Sin rango no se pide nada — un
      // informe que se abre con «los últimos noventa días» da un número de un
      // periodo que no eligió nadie.
      {
        nombre: "Cumplimiento del periodo",
        listar: "/api/v1/sla/cumplimiento",
        periodo: true,
        servicio: "service",
        permiso: "case:read",
      },
      {
        nombre: "SLA",
        // Los casos que van a incumplir si nadie hace nada, encima de los
        // acuerdos: el acuerdo se lee una vez; lo que está a punto de romperse,
        // hoy.
        resumen: ["/api/v1/sla/en-riesgo"],
        listar: "/api/v1/sla",
        servicio: "service",
      },
      { nombre: "Colas", listar: "/api/v1/colas", servicio: "service" },
      {
        nombre: "Escalado",
        listar: "/api/v1/escalado/reglas",
        servicio: "service",
      },
      {
        nombre: "Entitlements",
        listar: "/api/v1/entitlements",
        servicio: "service",
      },
      // Lo que se le debe al cliente cuando el SLA se incumple
      // (CRM-04.01.02): el crédito calculado, quién lo aprueba y cómo quedó.
      {
        nombre: "Créditos de servicio",
        listar: "/api/v1/creditos-servicio",
        servicio: "service",
        permiso: "case:read",
      },
      {
        nombre: "Cumplimiento de SLA",
        listar: "/api/v1/creditos-servicio/cumplimiento",
        periodo: true,
        servicio: "service",
        permiso: "case:read",
      },
    ],
  "omnicanal": [
      // Las conversaciones no tienen listado general a propósito: se trabajan
      // desde la consola de agente, que las da junto a los casos en una sola
      // cola. Una lista aparte reintroduciría la bandeja por canal que la
      // omnicanalidad viene a quitar.
      {
        nombre: "Canales",
        listar: "/api/v1/canales-servicio",
        crear: "/api/v1/canales-servicio",
        servicio: "service",
        columnas: ["nombre", "tipo", "activo"],
        permiso: "case:read",
      },
      {
        nombre: "Macros",
        objeto: "macro",
        listar: "/api/v1/macros",
        servicio: "service",
      },
      // La conversación como registro, con su historial, su transferencia y
      // su escalado a persona. El canal ya se veía; la conversación no.
    ],
  "conocimiento": [
      {
        nombre: "Artículos",
        objeto: "articulo",
        listar: "/api/v1/conocimiento/articulos",
        // Qué artículos sirven, cuáles estorban y cuáles no usa nadie. Un gestor de
        // conocimiento sin esto crece hasta que nadie encuentra nada.
        resumen: ["/api/v1/conocimiento/eficacia", "/api/v1/conocimiento"],
        crear: "/api/v1/conocimiento/articulos",
        servicio: "service",
        columnas: ["clave", "estado", "audiencia", "idioma", "vistas"],
        permiso: "knowledge:read",
      },
      {
        nombre: "Portal",
        listar: "/api/v1/portal/accesos",
        servicio: "service",
      },
      {
        nombre: "Comunidad",
        listar: "/api/v1/comunidad/hilos",
        servicio: "service",
      },
    ],
  "canales": [
      {
        nombre: "Canales",
        listar: "/api/v1/canales-marketing",
        crear: "/api/v1/canales-marketing",
        servicio: "marketing",
        columnas: ["clave", "nombre", "tipo", "activo"],
        permiso: "campana:read",
      },
      {
        nombre: "Landings",
        listar: "/api/v1/landings",
        crear: "/api/v1/landings",
        servicio: "marketing",
        columnas: ["clave", "titulo", "visitas", "envios"],
      },
      {
        nombre: "Dominios de envío",
        listar: "/api/v1/dominios-envio",
        crear: "/api/v1/dominios-envio",
        servicio: "marketing",
        columnas: ["dominio", "uso", "spf", "dkim", "dmarc"],
      },
    ],
  "contenido": [
      {
        nombre: "Reglas de contenido",
        listar: "/api/v1/reglas-contenido",
        servicio: "marketing",
      },
      { nombre: "Cookies", listar: "/api/v1/cookies", servicio: "marketing" },
      {
        nombre: "Renovación de consentimiento",
        listar: "/api/v1/optin/renovaciones",
        servicio: "marketing",
      },
      {
        nombre: "Plantillas",
        listar: "/api/v1/correo/plantillas",
        // Por qué dominio sale cada clase de correo. Mandar una campaña desde el
        // dominio de las facturas quema la reputación del que cobra.
        resumen: ["/api/v1/correo/remitente"],
        crear: "/api/v1/correo/plantillas",
        servicio: "marketing",
        columnas: ["clave", "nombre", "clase", "categoria", "idioma"],
        permiso: "campana:read",
      },
      {
        nombre: "Bloques",
        listar: "/api/v1/correo/bloques",
        crear: "/api/v1/correo/bloques",
        servicio: "marketing",
        columnas: ["clave", "nombre", "tipo"],
      },
      {
        nombre: "Categorías de preferencia",
        listar: "/api/v1/preferencias/categorias",
        crear: "/api/v1/preferencias/categorias",
        servicio: "marketing",
        columnas: ["clave", "nombre", "obligatoria"],
      },
      {
        nombre: "Supresiones",
        listar: "/api/v1/supresiones",
        servicio: "marketing",
      },
    ],
};

/** Las pestañas de un módulo, o ninguna si no es suyo. */
export function recursosDe(ruta: string): Recurso[] {
  return RECURSOS_POR_MODULO[ruta] ?? [];
}

/**
 * Qué recurso del módulo abre esta ficha.
 *
 * Antes la ficha usaba siempre `recursos[0]`, así que en un módulo con varias
 * pestañas sólo se podía abrir la primera: al pinchar una fila de la segunda
 * se pedía el registro contra la ruta de la primera y salía un 404. Por eso
 * sólo tenían ficha los módulos que declaraban `objeto` en su primer recurso.
 */
export function recursoDe(modulo: Modulo, objeto: string): Recurso | undefined {
  const pestanas = recursosDe(modulo.ruta);
  return pestanas.find((r) => objetoDe(r) === objeto) ?? pestanas[0];
}
