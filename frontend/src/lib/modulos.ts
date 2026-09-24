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

import { puede, type Sesion } from "@/lib/sesion";
import { rutaPermitida } from "@/lib/superficie";

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
  /**
   * Icono con el que se rotula la pestaña, **en vez del nombre**.
   *
   * Para lo que se repite en todos los módulos y cuyo contexto ya está claro:
   * dentro de Campañas, «Papelera de marketing» no dice nada que «Papelera» no
   * diga, y «Papelera» no dice nada que no diga el icono. El nombre sigue
   * estando, como etiqueta accesible y como título de la pantalla.
   */
  icono?: string;
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
      { nombre: "Compromisos", listar: "/api/v1/compromisos", servicio: "tenancy" },
      {
        nombre: "Tenants",
        // Con `objeto` para que cada fila se abra: suspender, reactivar,
        // exportar y ver el consumo cuelgan del tenant, y a un registro que no
        // se abre no se llega. Y `plan_codigo` no existe: el campo es `plan`,
        // así que esa columna salía siempre vacía.
        objeto: "tenant",
        listar: "/api/v1/tenants",
        crear: "/api/v1/tenants",
        servicio: "tenancy",
        solo_plataforma: true,
        columnas: ["slug", "nombre", "estado", "plan", "region", "idioma"],
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
      { nombre: "Seguimientos", listar: "/api/v1/seguimientos", servicio: "identity" },
      {
        nombre: "Dispositivos de confianza",
        listar: "/api/v1/dispositivos-confianza",
        servicio: "identity",
      },
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
      {
        // La COLA, no el buscador. El buscador sigue existiendo y hace falta
        // —avisa mientras se escribe un alta—, pero como pantalla solo protege
        // lo que entra desde hoy: obliga a sospechar de una ficha concreta y a
        // teclear su nombre. Los duplicados no llegan de uno en uno, llegan de
        // golpe con una importación, y de los que ya están dentro esa pantalla
        // no decía nada.
        nombre: "Duplicados",
        listar: "/api/v1/data-quality/accounts/duplicates/cola",
        servicio: "party",
        columnas: ["probabilidad", "a_nombre", "b_nombre", "senales", "concluyente"],
        permiso: "account:read",
      },
      {
        nombre: "Derechos del interesado",
        objeto: "solicitud_derechos",
        listar: "/api/v1/data-subject-requests",
        crear: "/api/v1/data-subject-requests",
        servicio: "party",
        columnas: ["tipo", "email_solicitante", "estado", "vence_at", "dias_restantes"],
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
        columnas: ["etiqueta", "objeto", "borrado_at", "dias_para_purga", "en_cascada"],
      },
    ],
  },
  // ── Proveedores ─────────────────────────────────────────────────────────
  //
  // Un módulo y no una pantalla escrita a mano. Lo era, y por eso no se podía
  // hacer nada: enseñaba la lista, y dar de alta, abrir uno o cambiarle algo
  // exigía saber que **un proveedor es una cuenta con rol** —irse a cuentas,
  // crearla allí y volver—. Como módulo hereda lo mismo que clientes: alta,
  // ficha, edición, borrado, adjuntos, comentarios, documentos y actividad.
  {
    ruta: "proveedores",
    titulo: "Proveedores",
    seccion: "9.1",
    capacidad: "CRM-07.04.03.31",
    grupo: "Clientes",
    recursos: [
      {
        nombre: "Proveedores",
        objeto: "proveedor",
        listar: "/api/v1/proveedores",
        servicio: "party",
        columnas: ["nombre", "estado", "sector_codigo", "telefono", "email", "owner_id"],
        permiso: "party:read",
      },
      {
        nombre: "Documentos que vencen",
        listar: "/api/v1/proveedores/documentos/vencen",
        servicio: "party",
        permiso: "party:read",
      },
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
  },

  // ── Módulo 3 · Ventas ───────────────────────────────────────────────────
  {
    ruta: "oportunidades",
    // «Oportunidades» y no «Pipeline»: el tablero donde se arrastran de etapa
    // tiene su propia entrada en el menú, y dos sitios distintos con el mismo
    // nombre obligan a entrar en los dos para saber cuál es cuál.
    titulo: "Oportunidades",
    seccion: "3.1",
    capacidad: "CRM-07.04.03.13",
    grupo: "Ventas",
    recursos: [
      {
        nombre: "Ofertas",
        listar: "/api/v1/presupuestos",
        servicio: "sales",
        permiso: "quote:read",
        columnas: ["codigo", "estado", "total", "moneda", "valido_hasta"],
      },
      {
        nombre: "Pedidos",
        listar: "/api/v1/pedidos",
        servicio: "sales",
        permiso: "order:read",
      },
      {
        nombre: "Contratos",
        listar: "/api/v1/contratos",
        servicio: "sales",
        permiso: "contract:read",
      },
      {
        nombre: "Suscripciones",
        listar: "/api/v1/suscripciones",
        servicio: "sales",
        permiso: "contract:read",
      },
      {
        nombre: "Productos",
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
      { nombre: "Metodologías", listar: "/api/v1/metodologias", servicio: "sales" },
      { nombre: "Mi cola", listar: "/api/v1/mi-cola", servicio: "sales" },
      {
        nombre: "Papelera",
        icono: "delete",
        objeto: "entrada_papelera",
        listar: "/api/v1/sales/papelera",
        servicio: "sales",
        columnas: ["etiqueta", "objeto", "borrado_at", "dias_para_purga", "en_cascada"],
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
  },
  {
    ruta: "leads",
    titulo: "Prospección",
    seccion: "3.3",
    capacidad: "CRM-07.04.03.15",
    grupo: "Ventas",
    recursos: [
      { nombre: "Cadencias", listar: "/api/v1/cadencias", servicio: "sales" },
      {
        nombre: "Plantillas de correo",
        listar: "/api/v1/plantillas-correo",
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
      { nombre: "Enrutamiento", listar: "/api/v1/lead-routing/reglas", servicio: "sales" },
      { nombre: "Canales de captura", listar: "/api/v1/captura/canales", servicio: "sales" },
      { nombre: "Recepciones", listar: "/api/v1/captura/recepciones", servicio: "sales" },
      {
        nombre: "Motivos de descarte",
        listar: "/api/v1/sales/vocabularios/motivos_descarte",
        servicio: "sales",
        columnas: ["etiqueta", "valor", "orden", "activo", "de_fabrica"],
      },
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
      { nombre: "Territorios", listar: "/api/v1/territorios", servicio: "sales" },
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
        nombre: "Portal del partner",
        listar: "/api/v1/portal-partner/mis-registros",
        servicio: "sales",
        permiso: "partner:read",
      },
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
        columnas: ["clave", "nombre", "objeto", "tamano", "tamano_at"],
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
        nombre: "Papelera",
        icono: "delete",
        objeto: "entrada_papelera",
        listar: "/api/v1/marketing/papelera",
        servicio: "marketing",
        columnas: ["etiqueta", "objeto", "borrado_at", "dias_para_purga", "en_cascada"],
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
      { nombre: "Encuestas", listar: "/api/v1/encuestas", servicio: "service" },
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
        columnas: ["etiqueta", "objeto", "borrado_at", "dias_para_purga", "en_cascada"],
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
        columnas: ["clave", "estado", "audiencia", "idioma", "vistas"],
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
      { nombre: "Reglas de contenido", listar: "/api/v1/reglas-contenido", servicio: "marketing" },
      { nombre: "Cookies", listar: "/api/v1/cookies", servicio: "marketing" },
      {
        nombre: "Renovación de consentimiento",
        listar: "/api/v1/optin/renovaciones",
        servicio: "marketing",
      },
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

/**
 * Con qué nombre viaja un recurso en la dirección de su ficha.
 *
 * El `objeto` declarado manda cuando lo hay, porque además de identificar la
 * pestaña nombra el tipo en las rutas de lo que cuelga del registro
 * (`/adjuntos/{tipo}/…`) y ahí «cuenta» no es intercambiable por «cuentas».
 * Para el resto se deriva de la ruta que lista, y se deriva **entera**: dos
 * pestañas del mismo módulo pueden acabar en el mismo segmento
 * —`/procesos/definiciones` y `/definiciones`— y con el último tramo la ficha
 * habría abierto la equivocada.
 */
export function objetoDe(recurso: Recurso): string {
  if (recurso.objeto) return recurso.objeto;
  return recurso.listar.replace(/^\/api\/v1\//, "").replace(/\?.*$/, "").replace(/\//g, "-");
}

/**
 * Qué recurso del módulo abre esta ficha.
 *
 * Antes la ficha usaba siempre `recursos[0]`, así que en un módulo con varias
 * pestañas solo se podía abrir la primera: al pinchar una fila de la segunda se
 * pedía el registro contra la ruta de la primera y salía un 404. Por eso solo
 * tenían ficha los módulos que declaraban `objeto` en su primer recurso.
 */
export function recursoDe(modulo: Modulo, objeto: string): Recurso | undefined {
  return modulo.recursos.find((r) => objetoDe(r) === objeto) ?? modulo.recursos[0];
}

export function porGrupo(): Map<string, Modulo[]> {
  const grupos = new Map<string, Modulo[]>();
  for (const modulo of MODULOS) {
    grupos.set(modulo.grupo, [...(grupos.get(modulo.grupo) ?? []), modulo]);
  }
  return grupos;
}

/**
 * ¿Puede esta persona ver algo de este recurso?
 *
 * Dos condiciones distintas: el permiso y el ámbito. Un administrador de
 * empresa **tiene** `tenant:read` y aun así no puede listar tenants, porque eso
 * es de quien opera la plataforma. Si solo se mirara el permiso, seguiría
 * viendo esa pestaña.
 */
export function recursoVisible(
  sesion: Sesion | null,
  recurso: Recurso,
  permitidas?: Set<string>,
): boolean {
  if (recurso.solo_plataforma && !sesion?.es_admin_plataforma) return false;
  if (!puede(sesion, recurso.permiso)) return false;
  // Lo que de verdad manda es lo que el servidor dice que exige esa ruta. El
  // campo `permiso` de aquí solo lo declaran unos pocos recursos, así que por
  // sí solo no filtra nada: sin la superficie, a un agente de soporte se le
  // seguían enseñando los veintitrés módulos.
  if (permitidas && permitidas.size > 0) return rutaPermitida(permitidas, recurso.listar);
  return true;
}

/**
 * Los módulos que esta persona puede abrir, agrupados.
 *
 * Un módulo del que no se puede ver **ningún** recurso no sale en el menú. No
 * es una cuestión estética: ofrecer lo que no se puede hacer obliga a probarlo
 * para descubrirlo, y lo que se descubre es un error. Es lo que hacen las
 * herramientas del mercado —una pestaña sin acceso no se enseña— y es lo que
 * aquí no se hacía.
 *
 * La decisión se toma con lo que el servidor dice que puede esta sesión, no con
 * una lista escrita en el front: si el servidor cambia de opinión, el menú
 * cambia con él.
 */
export function porGrupoVisible(
  sesion: Sesion | null,
  permitidas?: Set<string>,
): Map<string, Modulo[]> {
  const grupos = new Map<string, Modulo[]>();
  for (const modulo of MODULOS) {
    if (!modulo.recursos.some((r) => recursoVisible(sesion, r, permitidas))) continue;
    grupos.set(modulo.grupo, [...(grupos.get(modulo.grupo) ?? []), modulo]);
  }
  return grupos;
}
