/**
 * Lo mínimo para decidir qué módulos enseña el menú. **Generado.**
 *
 *     node scripts/gen-visibilidad.mjs
 *
 * De cada pestaña, lo justo: de dónde lista (`r`), qué permiso exige (`p`),
 * de qué servicio sale (`s`) y si es sólo de quien opera la plataforma
 * (`sp`). Nada más — el resto de la tabla son 42 kB comprimidos que no hacen
 * falta para pintar un menú.
 *
 * NO se edita a mano: sale de `recursos.ts`, que es la fuente. Dos listas a
 * mano acaban diciendo cosas distintas y entonces no se sabe cuál manda.
 */

export interface PestanaVisible {
  /** De dónde lista. Se compara con lo que el servidor dice que permite. */
  r: string;
  /** El tipo de registro de la pestaña, si lo declara. */
  o?: string;
  /** El permiso que declara el recurso, si declara alguno. */
  p?: string;
  /**
   * De qué servicio sale.
   *
   * Decide si esta pestaña se puede esconder: la superficie se agrega de diez
   * servicios y el que no contesta aporta cero operaciones. Sin saber de quién
   * es cada pestaña, un servicio lento al arrancar borra del menú todo lo suyo
   * y no hay forma de distinguirlo de «no te toca».
   */
  s?: string;
  /** Sólo para quien opera la plataforma. */
  sp?: boolean;
}

export const VISIBILIDAD: Record<string, PestanaVisible[]> = {
  "tenants": [
    {
      "r": "/api/v1/compromisos",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/tenants",
      "p": "tenant:read",
      "o": "tenant",
      "sp": true,
      "s": "tenancy"
    },
    {
      "r": "/api/v1/ciclo-vida/perfiles",
      "p": "tenant:read",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/calendarios",
      "p": "tenant:read",
      "o": "calendario_laboral",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/plantillas",
      "p": "tenant:read",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/monedas/cambios",
      "p": "tenant:read",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/localizacion",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/aislamiento",
      "p": "tenant:read",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/aislamiento/migraciones",
      "p": "tenant:read",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/residencia",
      "p": "tenant:read",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/residencia/subprocesadores",
      "p": "tenant:read",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/residencia/transferencias",
      "p": "tenant:read",
      "s": "tenancy"
    }
  ],
  "contrato": [],
  "procesos": [
    {
      "r": "/api/v1/procesos/definiciones",
      "s": "orchestrator"
    },
    {
      "r": "/api/v1/instancias",
      "o": "instancia",
      "s": "orchestrator"
    },
    {
      "r": "/api/v1/tablas-decision",
      "s": "orchestrator"
    },
    {
      "r": "/api/v1/automatizaciones",
      "s": "automation"
    },
    {
      "r": "/api/v1/integraciones/conexiones",
      "o": "conexion",
      "s": "integration"
    },
    {
      "r": "/api/v1/integraciones/ejecuciones",
      "s": "integration"
    },
    {
      "r": "/api/v1/party/trabajos",
      "o": "trabajo",
      "s": "party"
    },
    {
      "r": "/api/v1/conectores",
      "s": "integration"
    },
    {
      "r": "/api/v1/conectores/instalados",
      "s": "integration"
    },
    {
      "r": "/api/v1/canales-entrada",
      "p": "integracion:read",
      "o": "canal_entrada",
      "s": "integration"
    },
    {
      "r": "/api/v1/canales-entrada/interacciones",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/canales-entrada/sin-atribuir",
      "s": "integration"
    },
    {
      "r": "/api/v1/agentes-ia/uso",
      "s": "integration"
    },
    {
      "r": "/api/v1/federacion/vistas",
      "s": "integration"
    },
    {
      "r": "/api/v1/convivencia",
      "p": "integracion:read",
      "o": "regla_convivencia",
      "s": "integration"
    },
    {
      "r": "/api/v1/convivencia/progreso",
      "s": "integration"
    },
    {
      "r": "/api/v1/sagas",
      "p": "proceso:read",
      "o": "saga",
      "s": "orchestrator"
    },
    {
      "r": "/api/v1/integraciones/programacion",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/integraciones/registros-recibidos",
      "p": "integracion:read",
      "o": "registro_recibido",
      "s": "integration"
    },
    {
      "r": "/api/v1/conectores/transportes",
      "s": "integration"
    },
    {
      "r": "/api/v1/aprobaciones",
      "p": "aprobacion:read",
      "s": "orchestrator"
    },
    {
      "r": "/api/v1/aprobaciones/delegaciones",
      "p": "aprobacion:read",
      "s": "orchestrator"
    },
    {
      "r": "/api/v1/aprobaciones/enlaces",
      "p": "aprobacion:read",
      "s": "orchestrator"
    }
  ],
  "modelo": [
    {
      "r": "/api/v1/metadata/objetos",
      "o": "objeto",
      "s": "metadata"
    },
    {
      "r": "/api/v1/metadata/relaciones",
      "s": "metadata"
    },
    {
      "r": "/api/v1/metadata/relaciones/tipos",
      "s": "metadata"
    },
    {
      "r": "/api/v1/sales/vocabularios",
      "p": "metadata:read",
      "s": "sales"
    },
    {
      "r": "/api/v1/party/buscar/objetos",
      "p": "metadata:read",
      "s": "party"
    },
    {
      "r": "/api/v1/metadata/modulos",
      "p": "metadata:read",
      "o": "modulo",
      "s": "metadata"
    },
    {
      "r": "/api/v1/entornos",
      "p": "metadata:read",
      "o": "entorno",
      "s": "metadata"
    },
    {
      "r": "/api/v1/sales/numeracion",
      "p": "metadata:read",
      "s": "sales"
    }
  ],
  "acceso": [
    {
      "r": "/api/v1/seguimientos",
      "s": "identity"
    },
    {
      "r": "/api/v1/dispositivos-confianza",
      "s": "identity"
    },
    {
      "r": "/api/v1/usuarios",
      "p": "user:read",
      "o": "usuario",
      "s": "identity"
    },
    {
      "r": "/api/v1/roles",
      "p": "user:read",
      "s": "identity"
    },
    {
      "r": "/api/v1/politicas-acceso",
      "p": "user:read",
      "s": "identity"
    },
    {
      "r": "/api/v1/claves-api",
      "s": "identity"
    },
    {
      "r": "/api/v1/notificaciones/preferencias",
      "p": "user:read",
      "o": "notificacion",
      "s": "identity"
    },
    {
      "r": "/api/v1/sharing-rules",
      "p": "sharing:read",
      "s": "identity"
    },
    {
      "r": "/api/v1/proveedores-identidad",
      "s": "identity"
    }
  ],
  "operacion": [
    {
      "r": "/api/v1/modelo-canonico/objetos",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/sincronizacion/conflictos",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/proveedores-servicio",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/canales-chat",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/eventos/catalogo",
      "s": "eventing"
    },
    {
      "r": "/api/v1/eventos/fallidos",
      "s": "eventing"
    },
    {
      "r": "/api/v1/eventos/archivo",
      "s": "eventing"
    },
    {
      "r": "/api/v1/encargos",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/encargos/entregados-sin-prueba",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/encargos/coste-real",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/encargos/cumplimiento",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/encargos/estados-sin-mapear",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/plantillas-documento",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/suites/perfiles",
      "p": "integracion:read",
      "o": "perfil_suite",
      "s": "integration"
    },
    {
      "r": "/api/v1/buzones",
      "p": "integracion:read",
      "o": "buzon",
      "s": "integration"
    },
    {
      "r": "/api/v1/suites/consentimiento",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/firma/sobres",
      "p": "integracion:read",
      "o": "sobre_firma",
      "s": "integration"
    },
    {
      "r": "/api/v1/firma/proveedores",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/firma-presencial",
      "p": "firma:read",
      "s": "integration"
    }
  ],
  "cuentas": [
    {
      "r": "/api/v1/accounts",
      "p": "account:read",
      "o": "cuenta",
      "s": "party"
    },
    {
      "r": "/api/v1/planes-cuenta",
      "p": "party:read",
      "o": "plan_cuenta",
      "s": "party"
    },
    {
      "r": "/api/v1/planes-cuenta/financiero",
      "p": "party:read",
      "s": "party"
    },
    {
      "r": "/api/v1/cambios-de-empresa",
      "p": "party:read",
      "o": "cambio_de_empresa",
      "s": "party"
    },
    {
      "r": "/api/v1/contacts",
      "p": "contact:read",
      "o": "contacto",
      "s": "party"
    },
    {
      "r": "/api/v1/calidad-dato/cola",
      "p": "account:read",
      "s": "party"
    },
    {
      "r": "/api/v1/visitas",
      "p": "account:read",
      "s": "party"
    },
    {
      "r": "/api/v1/mapa-personas",
      "p": "contact:read",
      "s": "party"
    },
    {
      "r": "/api/v1/data-subject-requests",
      "o": "solicitud_derechos",
      "s": "party"
    },
    {
      "r": "/api/v1/party/papelera",
      "o": "entrada_papelera",
      "s": "party"
    }
  ],
  "proveedores": [
    {
      "r": "/api/v1/proveedores",
      "p": "party:read",
      "o": "proveedor",
      "s": "party"
    },
    {
      "r": "/api/v1/proveedores/documentos/vencen",
      "p": "party:read",
      "o": "proveedor",
      "s": "party"
    }
  ],
  "actividades": [
    {
      "r": "/api/v1/plantillas-actividad",
      "p": "activity:read",
      "s": "party"
    },
    {
      "r": "/api/v1/recurrencias",
      "p": "activity:read",
      "s": "party"
    },
    {
      "r": "/api/v1/activities",
      "p": "activity:read",
      "o": "actividad",
      "s": "party"
    }
  ],
  "oportunidades": [
    {
      "r": "/api/v1/presupuestos",
      "p": "quote:read",
      "o": "presupuesto",
      "s": "sales"
    },
    {
      "r": "/api/v1/planes-conjuntos",
      "p": "sales:read",
      "o": "plan_conjunto",
      "s": "sales"
    },
    {
      "r": "/api/v1/pedidos",
      "p": "order:read",
      "o": "pedido",
      "s": "sales"
    },
    {
      "r": "/api/v1/contratos",
      "p": "contract:read",
      "o": "contrato",
      "s": "sales"
    },
    {
      "r": "/api/v1/suscripciones",
      "p": "contract:read",
      "s": "sales"
    },
    {
      "r": "/api/v1/productos",
      "p": "producto:read",
      "o": "producto",
      "s": "sales"
    },
    {
      "r": "/api/v1/listas-precio",
      "p": "producto:read",
      "s": "sales"
    },
    {
      "r": "/api/v1/metodologias",
      "s": "sales"
    },
    {
      "r": "/api/v1/sales/papelera",
      "o": "entrada_papelera",
      "s": "sales"
    },
    {
      "r": "/api/v1/opportunities",
      "p": "opportunity:read",
      "o": "oportunidad",
      "s": "sales"
    },
    {
      "r": "/api/v1/pipelines",
      "o": "pipeline",
      "s": "sales"
    },
    {
      "r": "/api/v1/sales/vocabularios/motivos_perdida",
      "s": "sales"
    }
  ],
  "leads": [
    {
      "r": "/api/v1/plantillas-correo",
      "s": "sales"
    },
    {
      "r": "/api/v1/leads",
      "p": "lead:read",
      "o": "lead",
      "s": "sales"
    },
    {
      "r": "/api/v1/lead-routing/reglas",
      "s": "sales"
    },
    {
      "r": "/api/v1/captura/canales",
      "s": "sales"
    },
    {
      "r": "/api/v1/captura/recepciones",
      "s": "sales"
    },
    {
      "r": "/api/v1/sales/vocabularios/motivos_descarte",
      "s": "sales"
    },
    {
      "r": "/api/v1/origen/campanas",
      "s": "sales"
    }
  ],
  "prevision": [
    {
      "r": "/api/v1/territorios",
      "o": "territorio",
      "s": "sales"
    },
    {
      "r": "/api/v1/forecast/categorias",
      "p": "forecast:read",
      "s": "sales"
    },
    {
      "r": "/api/v1/forecast/periodos",
      "p": "forecast:read",
      "o": "periodo",
      "s": "sales"
    },
    {
      "r": "/api/v1/cuotas",
      "p": "forecast:read",
      "s": "sales"
    },
    {
      "r": "/api/v1/cuotas/consecucion",
      "p": "forecast:read",
      "s": "sales"
    },
    {
      "r": "/api/v1/ingresos/previsto",
      "p": "forecast:read",
      "s": "sales"
    },
    {
      "r": "/api/v1/pipeline/resumen",
      "p": "opportunity:read",
      "s": "sales"
    },
    {
      "r": "/api/v1/pipeline/estancadas",
      "s": "sales"
    },
    {
      "r": "/api/v1/cuotas/congelaciones",
      "p": "forecast:read",
      "s": "sales"
    }
  ],
  "canal": [
    {
      "r": "/api/v1/portal-partner/mis-registros",
      "p": "partner:read",
      "s": "sales"
    },
    {
      "r": "/api/v1/partners",
      "p": "partner:read",
      "o": "partner",
      "s": "sales"
    },
    {
      "r": "/api/v1/registros-oportunidad",
      "p": "partner:read",
      "s": "sales"
    },
    {
      "r": "/api/v1/niveles-partner",
      "o": "nivel",
      "s": "sales"
    },
    {
      "r": "/api/v1/partners/certificaciones/por-caducar",
      "s": "sales"
    },
    {
      "r": "/api/v1/fondos-mdf",
      "p": "campaign:read",
      "o": "fondo",
      "s": "marketing"
    },
    {
      "r": "/api/v1/solicitudes-mdf",
      "s": "marketing"
    },
    {
      "r": "/api/v1/liquidaciones",
      "p": "commission:read",
      "s": "sales"
    },
    {
      "r": "/api/v1/planes-comision",
      "s": "sales"
    }
  ],
  "campo": [
    {
      "r": "/api/v1/ordenes-trabajo",
      "p": "case:read",
      "s": "service"
    },
    {
      "r": "/api/v1/activos",
      "p": "case:read",
      "o": "activo",
      "s": "service"
    },
    {
      "r": "/api/v1/tecnicos-campo",
      "o": "tecnico",
      "s": "service"
    },
    {
      "r": "/api/v1/planes-preventivos",
      "o": "plan_preventivo",
      "s": "service"
    },
    {
      "r": "/api/v1/planes-preventivos/vencimientos",
      "s": "service"
    },
    {
      "r": "/api/v1/repuestos/reposicion",
      "s": "service"
    },
    {
      "r": "/api/v1/repuestos/movimientos",
      "s": "service"
    },
    {
      "r": "/api/v1/activos/garantias/por-vencer",
      "s": "service"
    },
    {
      "r": "/api/v1/dispositivos",
      "s": "integration"
    },
    {
      "r": "/api/v1/dispositivos/silenciosos",
      "s": "integration"
    }
  ],
  "postventa": [
    {
      "r": "/api/v1/devoluciones",
      "p": "case:read",
      "o": "devolucion",
      "s": "service"
    },
    {
      "r": "/api/v1/expedientes",
      "s": "service"
    },
    {
      "r": "/api/v1/expedientes/vencen",
      "s": "service"
    },
    {
      "r": "/api/v1/problemas",
      "s": "service"
    },
    {
      "r": "/api/v1/problemas/correlacion",
      "s": "service"
    }
  ],
  "ia": [
    {
      "r": "/api/v1/ia/proveedores",
      "p": "ia:administrar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/modelos",
      "p": "ia:administrar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/conversacion/resumenes",
      "p": "ia:usar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/modelos/deriva",
      "p": "ia:administrar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/agentes-autonomos",
      "p": "ia:administrar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/anomalias",
      "p": "ia:usar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/guardias",
      "p": "ia:administrar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/plantillas",
      "p": "ia:administrar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/guardias/bloqueos",
      "p": "ia:administrar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/uso",
      "p": "ia:administrar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/uso/por-dia",
      "p": "ia:administrar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/salud",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/prediccion",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/extraidos",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/ia/salud/riesgo",
      "p": "ia:usar",
      "s": "intelligence"
    },
    {
      "r": "/api/v1/agentes-ia/exposiciones",
      "p": "integracion:read",
      "s": "integration"
    }
  ],
  "explotacion": [
    {
      "r": "/api/v1/analitica/estado",
      "s": "analytics"
    },
    {
      "r": "/api/v1/analitica/consultas",
      "s": "analytics"
    },
    {
      "r": "/api/v1/analitica/organizaciones",
      "sp": true,
      "s": "analytics"
    },
    {
      "r": "/api/v1/metricas",
      "o": "metrica",
      "s": "analytics"
    },
    {
      "r": "/api/v1/almacen/tablas",
      "p": "informe:read",
      "o": "tabla_analitica",
      "s": "analytics"
    },
    {
      "r": "/api/v1/almacen/federadas",
      "p": "informe:read",
      "s": "analytics"
    },
    {
      "r": "/api/v1/federacion/embebidos",
      "p": "integracion:read",
      "s": "integration"
    },
    {
      "r": "/api/v1/cuadros-mando/embebidos",
      "p": "informe:read",
      "o": "enlace_embebido",
      "s": "analytics"
    },
    {
      "r": "/api/v1/informes/programaciones",
      "p": "informe:read",
      "s": "analytics"
    },
    {
      "r": "/api/v1/informes/ejecuciones",
      "p": "informe:read",
      "s": "analytics"
    },
    {
      "r": "/api/v1/almacen/frescura",
      "s": "analytics"
    },
    {
      "r": "/api/v1/almacen/destinos",
      "s": "analytics"
    },
    {
      "r": "/api/v1/analisis/despliegue",
      "s": "analytics"
    }
  ],
  "gobierno": [
    {
      "r": "/api/v1/grc/riesgos",
      "p": "tenant:read",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/grc/controles",
      "p": "tenant:read",
      "s": "tenancy"
    },
    {
      "r": "/api/v1/segregacion/reglas",
      "s": "identity"
    },
    {
      "r": "/api/v1/party/retencion/politicas",
      "s": "party"
    },
    {
      "r": "/api/v1/party/retencion/bloqueos",
      "s": "party"
    },
    {
      "r": "/api/v1/party/retencion/clases",
      "s": "party"
    }
  ],
  "segmentos": [
    {
      "r": "/api/v1/segmentos",
      "p": "segmento:read",
      "o": "segmento",
      "s": "marketing"
    },
    {
      "r": "/api/v1/puntuacion/modelos",
      "s": "marketing"
    },
    {
      "r": "/api/v1/activos-marketing/aprobacion",
      "p": "marketing:read",
      "o": "activo_marketing",
      "s": "marketing"
    },
    {
      "r": "/api/v1/activos-marketing",
      "p": "marketing:read",
      "s": "marketing"
    }
  ],
  "campanas": [
    {
      "r": "/api/v1/marketing/papelera",
      "o": "entrada_papelera",
      "s": "marketing"
    },
    {
      "r": "/api/v1/campanas/calendario",
      "p": "campaign:read",
      "s": "marketing"
    },
    {
      "r": "/api/v1/campanas",
      "p": "campana:read",
      "o": "campana",
      "s": "marketing"
    },
    {
      "r": "/api/v1/presion/reglas",
      "s": "marketing"
    },
    {
      "r": "/api/v1/rebotes",
      "s": "marketing"
    },
    {
      "r": "/api/v1/recorridos",
      "p": "campana:read",
      "s": "marketing"
    }
  ],
  "casos": [
    {
      "r": "/api/v1/encuestas/resumen",
      "p": "case:read",
      "s": "service"
    },
    {
      "r": "/api/v1/encuestas",
      "o": "encuesta",
      "s": "service"
    },
    {
      "r": "/api/v1/agentes/disponibles",
      "s": "service"
    },
    {
      "r": "/api/v1/service/papelera",
      "o": "entrada_papelera",
      "s": "service"
    },
    {
      "r": "/api/v1/casos",
      "p": "case:read",
      "o": "caso",
      "s": "service"
    },
    {
      "r": "/api/v1/categorias-caso",
      "o": "categoria",
      "s": "service"
    },
    {
      "r": "/api/v1/sla/cumplimiento",
      "p": "case:read",
      "s": "service"
    },
    {
      "r": "/api/v1/sla",
      "s": "service"
    },
    {
      "r": "/api/v1/escalado/reglas",
      "s": "service"
    },
    {
      "r": "/api/v1/entitlements",
      "s": "service"
    },
    {
      "r": "/api/v1/creditos-servicio",
      "p": "case:read",
      "s": "service"
    },
    {
      "r": "/api/v1/creditos-servicio/cumplimiento",
      "p": "case:read",
      "s": "service"
    }
  ],
  "omnicanal": [
    {
      "r": "/api/v1/canales-servicio",
      "p": "case:read",
      "s": "service"
    },
    {
      "r": "/api/v1/macros",
      "o": "macro",
      "s": "service"
    }
  ],
  "conocimiento": [
    {
      "r": "/api/v1/conocimiento/articulos",
      "p": "knowledge:read",
      "o": "articulo",
      "s": "service"
    },
    {
      "r": "/api/v1/portal/accesos",
      "s": "service"
    },
    {
      "r": "/api/v1/comunidad/hilos",
      "s": "service"
    }
  ],
  "canales": [
    {
      "r": "/api/v1/canales-marketing",
      "p": "campana:read",
      "s": "marketing"
    },
    {
      "r": "/api/v1/landings",
      "s": "marketing"
    },
    {
      "r": "/api/v1/dominios-envio",
      "s": "marketing"
    }
  ],
  "contenido": [
    {
      "r": "/api/v1/reglas-contenido",
      "s": "marketing"
    },
    {
      "r": "/api/v1/optin/renovaciones",
      "s": "marketing"
    },
    {
      "r": "/api/v1/correo/plantillas",
      "p": "campana:read",
      "s": "marketing"
    },
    {
      "r": "/api/v1/correo/bloques",
      "s": "marketing"
    },
    {
      "r": "/api/v1/preferencias/categorias",
      "s": "marketing"
    },
    {
      "r": "/api/v1/supresiones",
      "s": "marketing"
    }
  ]
};
