/**
 * Qué enseña cada pantalla, y a qué sección del catálogo corresponde.
 *
 * Es la única lista escrita a mano del front, y está aquí a propósito: el gate
 * de cobertura (`test_catalogo_trazabilidad.py`) exige que **cada sección del
 * catálogo tenga pantalla declarada**, y esta es la declaración del lado del
 * código. Lo que no es a mano es el contenido de cada pantalla: las columnas
 * salen de lo que devuelve la API y los formularios del OpenAPI.
 *
 * El front estándar es con lo que se enseña la solución, así que una capacidad
 * que solo existe por API es una capacidad que nadie ve.
 */

export interface Modulo {
  /** Camino en la aplicación. */
  ruta: string;
  titulo: string;
  /** Sección del catálogo funcional que enseña. */
  seccion: string;
  /** Capacidad del catálogo que esta pantalla implementa. Es la traza. */
  capacidad: string;
  /** Grupo del menú. */
  grupo: string;
  /** Recursos que se pintan, en orden de pestañas. */
  recursos: Recurso[];
}

export interface Recurso {
  nombre: string;
  /** Ruta de la API que lista. Se usa tal cual. */
  listar: string;
  /** Ruta de la API que crea, si la hay. */
  crear?: string;
  /** Servicio dueño, para leer su contrato y generar el formulario. */
  servicio: string;
  /** Columnas preferidas. Las demás siguen estando, detrás. */
  columnas?: string[];
  /** Permiso que hace falta para verlo. Lo declara el servicio; aquí se lee. */
  permiso?: string;
  /**
   * Solo para administradores de plataforma, no de empresa.
   *
   * No es lo mismo que un permiso y por eso es un campo aparte: el
   * administrador de una empresa tiene `tenant:read` y aun así la API le
   * responde 403, porque listar tenants es de quien opera la plataforma. Sin
   * esta marca, a ese administrador se le enseñaba una pestaña que nunca podría
   * abrir y lo único que veía era un error.
   */
  solo_plataforma?: boolean;
  /**
   * El recurso no es un listado: es una búsqueda que **exige** un término.
   *
   * `/data-quality/accounts/duplicates` no devuelve «los duplicados»: compara
   * un nombre contra el maestro y dice a qué se parece. Pedido sin nombre
   * responde 422, y la pestaña salía con un error incomprensible. Declarándolo
   * aquí, la pantalla enseña un buscador y no pide nada hasta que hay algo que
   * buscar.
   */
  busqueda?: { parametro: string; etiqueta: string; minimo?: number };
  /**
   * Tipo de objeto para lo que cuelga del registro: adjuntos, comentarios y
   * documentos. Sin él no hay ficha, porque esas rutas lo llevan dentro.
   */
  objeto?: string;
}

export const MODULOS: Modulo[] = [
  // ── Módulo 0 · Plataforma ───────────────────────────────────────────────
  {
    ruta: "tenants",
    titulo: "Tenants y unidades",
    seccion: "0.1",
    capacidad: "CRM-07.04.03.01",
    grupo: "Plataforma",
    recursos: [
      {
        nombre: "Tenants",
        listar: "/api/v1/tenants",
        crear: "/api/v1/tenants",
        servicio: "tenancy",
        solo_plataforma: true,
        columnas: ["slug", "nombre", "estado", "plan_codigo"],
        permiso: "tenant:read",
      },
      { nombre: "Planes", listar: "/api/v1/planes", servicio: "tenancy" },
      { nombre: "Ajustes", listar: "/api/v1/ajustes", servicio: "tenancy" },
      { nombre: "Localización", listar: "/api/v1/localizacion", servicio: "tenancy" },
    ],
  },
  {
    ruta: "contrato",
    titulo: "Contrato de la API",
    seccion: "0.2",
    capacidad: "CRM-07.04.03.02",
    grupo: "Plataforma",
    recursos: [{ nombre: "Servicios", listar: "/api/v1/servicios", servicio: "gateway" }],
  },
  {
    ruta: "procesos",
    titulo: "Procesos y orquestación",
    seccion: "0.3",
    capacidad: "CRM-07.04.03.03",
    grupo: "Plataforma",
    recursos: [
      { nombre: "Definiciones", listar: "/api/v1/procesos/definiciones", servicio: "orchestrator" },
      { nombre: "Instancias", listar: "/api/v1/instancias", servicio: "orchestrator" },
      { nombre: "Tareas", listar: "/api/v1/tareas", servicio: "orchestrator" },
      { nombre: "Tablas de decisión", listar: "/api/v1/tablas-decision", servicio: "orchestrator" },
      { nombre: "Automatizaciones", listar: "/api/v1/automatizaciones", servicio: "automation" },
      { nombre: "Integraciones", listar: "/api/v1/integraciones/conexiones", servicio: "integration" },
      { nombre: "Ejecuciones", listar: "/api/v1/integraciones/ejecuciones", servicio: "integration" },
      { nombre: "Webhooks", listar: "/api/v1/webhooks", servicio: "eventing" },
      { nombre: "Trabajos de clientes", listar: "/api/v1/party/trabajos", servicio: "party" },
      { nombre: "Trabajos de ventas", listar: "/api/v1/sales/trabajos", servicio: "sales" },
      // El catálogo de conectores y lo instalado aquí, juntos: la pregunta real
      // es «¿qué tengo puesto y qué versión?», no «¿qué existe?».
      { nombre: "Catálogo de conectores", listar: "/api/v1/conectores", servicio: "integration" },
      { nombre: "Conectores instalados", listar: "/api/v1/conectores/instalados", servicio: "integration" },
      { nombre: "Canales de entrada", listar: "/api/v1/canales-entrada/sin-atribuir", servicio: "integration" },
      { nombre: "Agentes: uso", listar: "/api/v1/agentes-ia/uso", servicio: "integration" },
      { nombre: "Vistas federadas", listar: "/api/v1/federacion/vistas", servicio: "integration" },
      // El progreso de la migración, por delante de la lista de reglas: lo que
      // se pregunta cada semana es cuánto falta.
      { nombre: "Migración: progreso", listar: "/api/v1/convivencia/progreso", servicio: "integration" },
      { nombre: "Transportes", listar: "/api/v1/conectores/transportes", servicio: "integration" },
    ],
  },
  {
    ruta: "modelo",
    titulo: "Modelo de datos",
    seccion: "0.4",
    capacidad: "CRM-07.04.03.04",
    grupo: "Plataforma",
    recursos: [
      { nombre: "Objetos", listar: "/api/v1/metadata/objetos", servicio: "metadata" },
      { nombre: "Relaciones", listar: "/api/v1/metadata/relaciones", servicio: "metadata" },
      { nombre: "Tipos de relación", listar: "/api/v1/metadata/relaciones/tipos", servicio: "metadata" },
    ],
  },
  {
    ruta: "acceso",
    titulo: "Identidad y acceso",
    seccion: "0.5",
    capacidad: "CRM-07.04.03.05",
    grupo: "Plataforma",
    recursos: [
      { nombre: "Usuarios", listar: "/api/v1/usuarios", servicio: "identity", permiso: "user:read" },
      { nombre: "Roles", listar: "/api/v1/roles", servicio: "identity", permiso: "user:read" },
      {
        nombre: "Políticas de acceso",
        listar: "/api/v1/politicas-acceso",
        crear: "/api/v1/politicas-acceso/{nombre}",
        servicio: "identity",
        permiso: "user:read",
      },
      { nombre: "Claves de API", listar: "/api/v1/claves-api", servicio: "identity" },
      { nombre: "Sesiones", listar: "/api/v1/sesiones", servicio: "identity" },
      { nombre: "Proveedores de identidad", listar: "/api/v1/proveedores-identidad", servicio: "identity" },
    ],
  },
  {
    ruta: "operacion",
    titulo: "Operación",
    seccion: "0.6",
    capacidad: "CRM-07.04.03.06",
    grupo: "Plataforma",
    recursos: [
      { nombre: "Catálogo de eventos", listar: "/api/v1/eventos/catalogo", servicio: "eventing" },
      // La cola de fallidos delante del archivo: lo que hay que mirar cuando
      // algo va mal es lo que no salió, no lo que salió bien hace un mes.
      { nombre: "Cola de fallidos", listar: "/api/v1/eventos/fallidos", servicio: "eventing" },
      { nombre: "Archivo de eventos", listar: "/api/v1/eventos/archivo", servicio: "eventing" },
    ],
  },

  // ── Módulo 1 · Customer 360 ─────────────────────────────────────────────
  {
    ruta: "cuentas",
    titulo: "Cuentas y contactos",
    seccion: "1.1",
    capacidad: "CRM-07.04.03.07",
    grupo: "Clientes",
    recursos: [
      {
        nombre: "Cuentas",
        objeto: "cuenta",
        listar: "/api/v1/accounts",
        crear: "/api/v1/accounts",
        servicio: "party",
        columnas: ["nombre", "estado", "sector_codigo", "owner_id"],
        permiso: "account:read",
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
        nombre: "Duplicados",
        listar: "/api/v1/data-quality/accounts/duplicates",
        servicio: "party",
        busqueda: { parametro: "nombre", etiqueta: "Nombre de la cuenta", minimo: 2 },
      },
      {
        nombre: "Derechos del interesado",
        listar: "/api/v1/data-subject-requests",
        servicio: "party",
      },
      { nombre: "Papelera", listar: "/api/v1/party-admin/papelera", servicio: "party" },
    ],
  },
  {
    ruta: "actividades",
    titulo: "Actividades",
    seccion: "1.2",
    capacidad: "CRM-07.04.03.08",
    grupo: "Clientes",
    recursos: [
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
  },

  // ── Módulo 3 · Ventas ───────────────────────────────────────────────────
  {
    ruta: "oportunidades",
    titulo: "Pipeline",
    seccion: "3.1",
    capacidad: "CRM-07.04.03.13",
    grupo: "Ventas",
    recursos: [
      {
        nombre: "Oportunidades",
        objeto: "oportunidad",
        listar: "/api/v1/opportunities",
        crear: "/api/v1/opportunities",
        servicio: "sales",
        columnas: ["nombre", "etapa", "importe", "cierre_previsto"],
        permiso: "opportunity:read",
      },
      { nombre: "Pipelines", listar: "/api/v1/pipelines", servicio: "sales" },
      { nombre: "Motivos de pérdida", listar: "/api/v1/pipeline/motivos-perdida", servicio: "sales" },
    ],
  },
  {
    ruta: "leads",
    titulo: "Prospección",
    seccion: "3.3",
    capacidad: "CRM-07.04.03.15",
    grupo: "Ventas",
    recursos: [
      {
        nombre: "Leads",
        objeto: "lead",
        listar: "/api/v1/leads",
        crear: "/api/v1/leads",
        servicio: "sales",
        columnas: ["nombre", "empresa", "estado", "puntuacion"],
        permiso: "lead:read",
      },
      { nombre: "Enrutamiento", listar: "/api/v1/lead-routing/reglas", servicio: "sales" },
      { nombre: "Canales de captura", listar: "/api/v1/captura/canales", servicio: "sales" },
      { nombre: "Recepciones", listar: "/api/v1/captura/recepciones", servicio: "sales" },
      { nombre: "Motivos de descarte", listar: "/api/v1/leads/motivos-descarte", servicio: "sales" },
      { nombre: "Campañas de origen", listar: "/api/v1/origen/campanas", servicio: "sales" },
      { nombre: "Toques", listar: "/api/v1/origen/toques", servicio: "sales" },
    ],
  },

  {
    ruta: "prevision",
    titulo: "Previsión",
    seccion: "3.2",
    capacidad: "CRM-07.04.03.14",
    grupo: "Ventas",
    recursos: [
      {
        nombre: "Resumen del pipeline",
        listar: "/api/v1/pipeline/resumen",
        servicio: "sales",
        permiso: "opportunity:read",
      },
      // Las estancadas delante del resumen no: el resumen es lo que se mira
      // cada día y esto es lo que se mira cuando el resumen no cuadra.
      { nombre: "Estancadas", listar: "/api/v1/pipeline/estancadas", servicio: "sales" },
    ],
  },

  {
    ruta: "canal",
    titulo: "Canal indirecto",
    seccion: "3.4",
    capacidad: "CRM-07.04.03.16",
    grupo: "Ventas",
    recursos: [
      {
        nombre: "Partners",
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
        columnas: ["cliente", "estado", "importe_estimado", "protegido_hasta", "en_conflicto"],
        permiso: "partner:read",
      },
      { nombre: "Niveles", listar: "/api/v1/niveles-partner", servicio: "sales" },
      {
        nombre: "Certificaciones por caducar",
        listar: "/api/v1/partners/certificaciones/por-caducar",
        servicio: "sales",
      },
      {
        nombre: "Fondos de marketing",
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
        columnas: ["titulo", "estado", "solicitado", "aprobado", "justificado", "justificar_antes_de"],
      },
      // Las liquidaciones cuelgan del canal *y* de la retribución interna: es
      // el mismo motor, y enseñarlas dos veces daría dos listas del mismo dinero.
      {
        nombre: "Liquidaciones",
        listar: "/api/v1/liquidaciones",
        servicio: "sales",
        columnas: ["estado", "desde", "hasta", "total", "moneda", "pago_referencia"],
        permiso: "commission:read",
      },
      { nombre: "Planes de comisión", listar: "/api/v1/planes-comision", servicio: "sales" },
    ],
  },

  {
    ruta: "campo",
    titulo: "Servicio de campo",
    seccion: "4.4",
    capacidad: "CRM-07.04.03.20",
    grupo: "Servicio",
    recursos: [
      {
        nombre: "Órdenes de trabajo",
        listar: "/api/v1/ordenes-trabajo",
        crear: "/api/v1/ordenes-trabajo",
        servicio: "service",
        columnas: ["codigo", "titulo", "tipo", "estado", "prioridad", "cita_desde"],
        permiso: "case:read",
      },
      {
        nombre: "Activos instalados",
        listar: "/api/v1/activos",
        crear: "/api/v1/activos",
        servicio: "service",
        columnas: ["codigo", "nombre", "modelo", "numero_serie", "estado", "ubicacion"],
        permiso: "case:read",
      },
      { nombre: "Técnicos", listar: "/api/v1/tecnicos-campo", servicio: "service" },
      // El preventivo por delante de los repuestos: es lo que hay que mirar cada
      // semana, y los repuestos solo cuando falta uno.
      { nombre: "Planes preventivos", listar: "/api/v1/planes-preventivos", servicio: "service" },
      {
        nombre: "Vencimientos",
        listar: "/api/v1/planes-preventivos/vencimientos",
        servicio: "service",
      },
      { nombre: "Repuestos", listar: "/api/v1/repuestos", servicio: "service" },
      { nombre: "Reposición", listar: "/api/v1/repuestos/reposicion", servicio: "service" },
      {
        nombre: "Garantías por vencer",
        listar: "/api/v1/activos/garantias/por-vencer",
        servicio: "service",
      },
      { nombre: "Dispositivos", listar: "/api/v1/dispositivos", servicio: "integration" },
      {
        nombre: "Aparatos callados",
        listar: "/api/v1/dispositivos/silenciosos",
        servicio: "integration",
      },
    ],
  },
  {
    ruta: "postventa",
    titulo: "Postventa",
    seccion: "4.5",
    capacidad: "CRM-07.04.03.21",
    grupo: "Servicio",
    recursos: [
      {
        nombre: "Devoluciones",
        listar: "/api/v1/devoluciones",
        crear: "/api/v1/devoluciones",
        servicio: "service",
        columnas: ["codigo", "estado", "motivo", "fuera_de_plazo", "disposicion"],
        permiso: "case:read",
      },
      // Los expedientes ordenados por vencimiento, y los vencidos aparte: el
      // plazo legal no es una cola de trabajo, es una fecha que se pasa.
      {
        nombre: "Expedientes",
        listar: "/api/v1/expedientes",
        servicio: "service",
        columnas: ["codigo", "asunto", "estado", "via", "vence_at", "sin_acuse"],
      },
      { nombre: "Vencen pronto", listar: "/api/v1/expedientes/vencen", servicio: "service" },
      {
        nombre: "Problemas",
        listar: "/api/v1/problemas",
        servicio: "service",
        columnas: ["codigo", "titulo", "estado", "severidad", "error_conocido", "solo_apano"],
      },
      { nombre: "Correlación", listar: "/api/v1/problemas/correlacion", servicio: "service" },
    ],
  },

  // ── Módulo 5 · Analítica ────────────────────────────────────────────────
  {
    ruta: "explotacion",
    titulo: "Explotación",
    seccion: "5.1",
    capacidad: "CRM-07.04.03.22",
    grupo: "Analítica",
    recursos: [
      // La explotación la resuelve contecintelligence de forma frontless
      // (RT-4). Aquí se enseña el estado del enlace y lo que se ha consultado:
      // los informes se abren allí, con la identidad del usuario.
      { nombre: "Estado del enlace", listar: "/api/v1/analitica/estado", servicio: "analytics" },
      { nombre: "Consultas", listar: "/api/v1/analitica/consultas", servicio: "analytics" },
      {
        nombre: "Organizaciones",
        listar: "/api/v1/analitica/organizaciones",
        servicio: "analytics",
        solo_plataforma: true,
      },
      // El diccionario de métricas delante de las tablas: la pregunta que abre
      // la discusión es «¿qué quiere decir ingresos?», no «¿qué tablas hay?».
      { nombre: "Métricas", listar: "/api/v1/metricas", servicio: "analytics" },
      { nombre: "Frescura del almacén", listar: "/api/v1/almacen/frescura", servicio: "analytics" },
      { nombre: "Exportaciones", listar: "/api/v1/almacen/destinos", servicio: "analytics" },
      { nombre: "Despliegue de BI", listar: "/api/v1/analisis/despliegue", servicio: "analytics" },
    ],
  },

  // ── Módulo 7 · Gobierno ─────────────────────────────────────────────────
  {
    ruta: "gobierno",
    titulo: "Gobierno y cumplimiento",
    seccion: "7.3",
    capacidad: "CRM-07.04.03.28",
    grupo: "Gobierno",
    recursos: [
      {
        nombre: "Riesgos",
        listar: "/api/v1/grc/riesgos",
        servicio: "tenancy",
        columnas: ["codigo", "titulo", "inherente", "residual", "tratamiento", "estado"],
        permiso: "tenant:read",
      },
      {
        nombre: "Controles",
        listar: "/api/v1/grc/controles",
        servicio: "tenancy",
        columnas: ["codigo", "nombre", "tipo", "frecuencia", "activo"],
        permiso: "tenant:read",
      },
      { nombre: "Segregación", listar: "/api/v1/segregacion/reglas", servicio: "identity" },
      { nombre: "Retención", listar: "/api/v1/party/retencion/politicas", servicio: "party" },
      { nombre: "Bloqueos legales", listar: "/api/v1/party/retencion/bloqueos", servicio: "party" },
      { nombre: "Clases de dato", listar: "/api/v1/party/retencion/clases", servicio: "party" },
    ],
  },
  // ── Módulo 2 · Marketing ────────────────────────────────────────────────
  {
    ruta: "segmentos",
    titulo: "Segmentación",
    seccion: "2.1",
    capacidad: "CRM-07.04.03.09",
    grupo: "Marketing",
    recursos: [
      {
        nombre: "Segmentos",
        objeto: "segmento",
        listar: "/api/v1/segmentos",
        crear: "/api/v1/segmentos",
        servicio: "marketing",
        columnas: ["nombre", "tipo", "miembros", "calculado_at"],
        permiso: "segmento:read",
      },
      { nombre: "Supresiones", listar: "/api/v1/supresiones", servicio: "marketing" },
      { nombre: "Puntuación", listar: "/api/v1/puntuacion/modelos", servicio: "marketing" },
    ],
  },
  {
    ruta: "campanas",
    titulo: "Campañas",
    seccion: "2.2",
    capacidad: "CRM-07.04.03.10",
    grupo: "Marketing",
    recursos: [
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
      { nombre: "Presión de contacto", listar: "/api/v1/presion/reglas", servicio: "marketing" },
      { nombre: "Rebotes", listar: "/api/v1/rebotes", servicio: "marketing" },
    ],
  },

  // ── Módulo 4 · Servicio ─────────────────────────────────────────────────
  {
    ruta: "casos",
    titulo: "Casos",
    seccion: "4.1",
    capacidad: "CRM-07.04.03.17",
    grupo: "Servicio",
    recursos: [
      {
        nombre: "Casos",
        objeto: "caso",
        listar: "/api/v1/casos",
        crear: "/api/v1/casos",
        servicio: "service",
        columnas: ["codigo", "asunto", "estado", "prioridad"],
        permiso: "case:read",
      },
      { nombre: "Categorías", listar: "/api/v1/categorias-caso", servicio: "service" },
      { nombre: "SLA", listar: "/api/v1/sla", servicio: "service" },
      { nombre: "Colas", listar: "/api/v1/colas", servicio: "service" },
      { nombre: "Escalado", listar: "/api/v1/escalado/reglas", servicio: "service" },
      { nombre: "Entitlements", listar: "/api/v1/entitlements", servicio: "service" },
    ],
  },
  {
    ruta: "omnicanal",
    titulo: "Omnicanalidad",
    seccion: "4.2",
    capacidad: "CRM-07.04.03.18",
    grupo: "Servicio",
    recursos: [
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
      { nombre: "Macros", listar: "/api/v1/macros", servicio: "service" },
    ],
  },
  {
    ruta: "conocimiento",
    titulo: "Conocimiento",
    seccion: "4.3",
    capacidad: "CRM-07.04.03.19",
    grupo: "Servicio",
    recursos: [
      {
        nombre: "Artículos",
        objeto: "articulo",
        listar: "/api/v1/conocimiento/articulos",
        crear: "/api/v1/conocimiento/articulos",
        servicio: "service",
        columnas: ["titulo", "estado", "categoria"],
        permiso: "knowledge:read",
      },
      { nombre: "Portal", listar: "/api/v1/portal/accesos", servicio: "service" },
      { nombre: "Comunidad", listar: "/api/v1/comunidad/hilos", servicio: "service" },
    ],
  },
  {
    ruta: "canales",
    titulo: "Canales de ejecución",
    seccion: "2.3",
    capacidad: "CRM-07.04.03.11",
    grupo: "Marketing",
    recursos: [
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
  },
  {
    ruta: "contenido",
    titulo: "Contenido y gobierno",
    seccion: "2.4",
    capacidad: "CRM-07.04.03.12",
    grupo: "Marketing",
    recursos: [
      {
        nombre: "Plantillas",
        listar: "/api/v1/correo/plantillas",
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
      { nombre: "Supresiones", listar: "/api/v1/supresiones", servicio: "marketing" },
    ],
  },
];

export function moduloDe(ruta: string): Modulo | undefined {
  return MODULOS.find((m) => m.ruta === ruta);
}

export function porGrupo(): Map<string, Modulo[]> {
  const grupos = new Map<string, Modulo[]>();
  for (const modulo of MODULOS) {
    grupos.set(modulo.grupo, [...(grupos.get(modulo.grupo) ?? []), modulo]);
  }
  return grupos;
}
