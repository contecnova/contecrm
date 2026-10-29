/**
 * Lo mínimo para decidir qué módulos enseña el menú. **Generado.**
 *
 *     node scripts/gen-visibilidad.mjs
 *
 * De cada pestaña, tres cosas: de dónde lista (`r`), qué permiso exige (`p`)
 * y si es sólo de quien opera la plataforma (`sp`). Nada más — el resto de la
 * tabla son 42 kB comprimidos que no hacen falta para pintar un menú.
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
  /** Sólo para quien opera la plataforma. */
  sp?: boolean;
}

export const VISIBILIDAD: Record<string, PestanaVisible[]> = {
  "tenants": [
    {
      "r": "/api/v1/compromisos"
    },
    {
      "r": "/api/v1/tenants",
      "p": "tenant:read",
      "o": "tenant",
      "sp": true
    },
    {
      "r": "/api/v1/ciclo-vida/perfiles",
      "p": "tenant:read"
    },
    {
      "r": "/api/v1/calendarios",
      "p": "tenant:read",
      "o": "calendario_laboral"
    },
    {
      "r": "/api/v1/plantillas",
      "p": "tenant:read"
    },
    {
      "r": "/api/v1/monedas/cambios",
      "p": "tenant:read"
    },
    {
      "r": "/api/v1/localizacion"
    },
    {
      "r": "/api/v1/aislamiento",
      "p": "tenant:read"
    },
    {
      "r": "/api/v1/aislamiento/migraciones",
      "p": "tenant:read"
    },
    {
      "r": "/api/v1/residencia",
      "p": "tenant:read"
    },
    {
      "r": "/api/v1/residencia/subprocesadores",
      "p": "tenant:read"
    },
    {
      "r": "/api/v1/residencia/transferencias",
      "p": "tenant:read"
    }
  ],
  "contrato": [],
  "procesos": [
    {
      "r": "/api/v1/procesos/definiciones"
    },
    {
      "r": "/api/v1/instancias",
      "o": "instancia"
    },
    {
      "r": "/api/v1/tablas-decision"
    },
    {
      "r": "/api/v1/automatizaciones"
    },
    {
      "r": "/api/v1/integraciones/conexiones",
      "o": "conexion"
    },
    {
      "r": "/api/v1/integraciones/ejecuciones"
    },
    {
      "r": "/api/v1/party/trabajos",
      "o": "trabajo"
    },
    {
      "r": "/api/v1/conectores"
    },
    {
      "r": "/api/v1/conectores/instalados"
    },
    {
      "r": "/api/v1/canales-entrada",
      "p": "integracion:read",
      "o": "canal_entrada"
    },
    {
      "r": "/api/v1/canales-entrada/interacciones",
      "p": "integracion:read",
      "o": "canal_entrada"
    },
    {
      "r": "/api/v1/canales-entrada/sin-atribuir"
    },
    {
      "r": "/api/v1/agentes-ia/uso"
    },
    {
      "r": "/api/v1/federacion/vistas"
    },
    {
      "r": "/api/v1/convivencia",
      "p": "integracion:read",
      "o": "regla_convivencia"
    },
    {
      "r": "/api/v1/convivencia/progreso"
    },
    {
      "r": "/api/v1/sagas",
      "p": "proceso:read",
      "o": "saga"
    },
    {
      "r": "/api/v1/integraciones/programacion",
      "p": "integracion:read",
      "o": "registro_recibido"
    },
    {
      "r": "/api/v1/integraciones/registros-recibidos",
      "p": "integracion:read",
      "o": "registro_recibido"
    },
    {
      "r": "/api/v1/conectores/transportes"
    },
    {
      "r": "/api/v1/aprobaciones",
      "p": "aprobacion:read"
    }
  ],
  "modelo": [
    {
      "r": "/api/v1/metadata/objetos",
      "o": "objeto"
    },
    {
      "r": "/api/v1/metadata/relaciones"
    },
    {
      "r": "/api/v1/metadata/relaciones/tipos"
    },
    {
      "r": "/api/v1/sales/vocabularios",
      "p": "metadata:read"
    },
    {
      "r": "/api/v1/party/buscar/objetos",
      "p": "metadata:read"
    },
    {
      "r": "/api/v1/metadata/modulos",
      "p": "metadata:read",
      "o": "modulo"
    },
    {
      "r": "/api/v1/entornos",
      "p": "metadata:read",
      "o": "entorno"
    },
    {
      "r": "/api/v1/sales/numeracion",
      "p": "metadata:read"
    }
  ],
  "acceso": [
    {
      "r": "/api/v1/seguimientos"
    },
    {
      "r": "/api/v1/dispositivos-confianza"
    },
    {
      "r": "/api/v1/usuarios",
      "p": "user:read",
      "o": "usuario"
    },
    {
      "r": "/api/v1/roles",
      "p": "user:read"
    },
    {
      "r": "/api/v1/politicas-acceso",
      "p": "user:read"
    },
    {
      "r": "/api/v1/claves-api"
    },
    {
      "r": "/api/v1/notificaciones/preferencias",
      "p": "user:read",
      "o": "notificacion"
    },
    {
      "r": "/api/v1/sharing-rules",
      "p": "sharing:read"
    },
    {
      "r": "/api/v1/proveedores-identidad"
    }
  ],
  "operacion": [
    {
      "r": "/api/v1/modelo-canonico/objetos",
      "p": "integracion:read"
    },
    {
      "r": "/api/v1/sincronizacion/conflictos",
      "p": "integracion:read"
    },
    {
      "r": "/api/v1/proveedores-servicio",
      "p": "integracion:read"
    },
    {
      "r": "/api/v1/canales-chat",
      "p": "integracion:read"
    },
    {
      "r": "/api/v1/eventos/catalogo"
    },
    {
      "r": "/api/v1/eventos/fallidos"
    },
    {
      "r": "/api/v1/eventos/archivo"
    },
    {
      "r": "/api/v1/encargos",
      "p": "integracion:read"
    },
    {
      "r": "/api/v1/encargos/entregados-sin-prueba",
      "p": "integracion:read"
    },
    {
      "r": "/api/v1/encargos/cumplimiento",
      "p": "integracion:read"
    },
    {
      "r": "/api/v1/encargos/estados-sin-mapear",
      "p": "integracion:read"
    },
    {
      "r": "/api/v1/plantillas-documento",
      "p": "integracion:read"
    },
    {
      "r": "/api/v1/suites/perfiles",
      "p": "integracion:read",
      "o": "perfil_suite"
    },
    {
      "r": "/api/v1/buzones",
      "p": "integracion:read",
      "o": "buzon"
    },
    {
      "r": "/api/v1/suites/consentimiento",
      "p": "integracion:read"
    },
    {
      "r": "/api/v1/firma/sobres",
      "p": "integracion:read",
      "o": "sobre_firma"
    },
    {
      "r": "/api/v1/firma/proveedores",
      "p": "integracion:read"
    },
    {
      "r": "/api/v1/firma-presencial",
      "p": "firma:read"
    }
  ],
  "cuentas": [
    {
      "r": "/api/v1/accounts",
      "p": "account:read",
      "o": "cuenta"
    },
    {
      "r": "/api/v1/planes-cuenta",
      "p": "party:read",
      "o": "plan_cuenta"
    },
    {
      "r": "/api/v1/planes-cuenta/financiero",
      "p": "party:read",
      "o": "plan_cuenta"
    },
    {
      "r": "/api/v1/cambios-de-empresa",
      "p": "party:read",
      "o": "cambio_de_empresa"
    },
    {
      "r": "/api/v1/contacts",
      "p": "contact:read",
      "o": "contacto"
    },
    {
      "r": "/api/v1/calidad-dato/cola",
      "p": "account:read"
    },
    {
      "r": "/api/v1/visitas",
      "p": "account:read"
    },
    {
      "r": "/api/v1/mapa-personas",
      "p": "contact:read"
    },
    {
      "r": "/api/v1/data-subject-requests",
      "o": "solicitud_derechos"
    },
    {
      "r": "/api/v1/party/papelera",
      "o": "entrada_papelera"
    }
  ],
  "proveedores": [
    {
      "r": "/api/v1/proveedores",
      "p": "party:read",
      "o": "proveedor"
    },
    {
      "r": "/api/v1/proveedores/documentos/vencen",
      "p": "party:read",
      "o": "proveedor"
    }
  ],
  "actividades": [
    {
      "r": "/api/v1/plantillas-actividad",
      "p": "activity:read"
    },
    {
      "r": "/api/v1/recurrencias",
      "p": "activity:read"
    },
    {
      "r": "/api/v1/activities",
      "p": "activity:read",
      "o": "actividad"
    }
  ],
  "oportunidades": [
    {
      "r": "/api/v1/presupuestos",
      "p": "quote:read",
      "o": "presupuesto"
    },
    {
      "r": "/api/v1/planes-conjuntos",
      "p": "sales:read",
      "o": "plan_conjunto"
    },
    {
      "r": "/api/v1/pedidos",
      "p": "order:read",
      "o": "pedido"
    },
    {
      "r": "/api/v1/contratos",
      "p": "contract:read",
      "o": "contrato"
    },
    {
      "r": "/api/v1/suscripciones",
      "p": "contract:read"
    },
    {
      "r": "/api/v1/productos",
      "p": "producto:read",
      "o": "producto"
    },
    {
      "r": "/api/v1/listas-precio",
      "p": "producto:read"
    },
    {
      "r": "/api/v1/metodologias"
    },
    {
      "r": "/api/v1/sales/papelera",
      "o": "entrada_papelera"
    },
    {
      "r": "/api/v1/opportunities",
      "p": "opportunity:read",
      "o": "oportunidad"
    },
    {
      "r": "/api/v1/pipelines",
      "o": "pipeline"
    },
    {
      "r": "/api/v1/sales/vocabularios/motivos_perdida"
    }
  ],
  "leads": [
    {
      "r": "/api/v1/plantillas-correo"
    },
    {
      "r": "/api/v1/leads",
      "p": "lead:read",
      "o": "lead"
    },
    {
      "r": "/api/v1/lead-routing/reglas"
    },
    {
      "r": "/api/v1/captura/canales"
    },
    {
      "r": "/api/v1/captura/recepciones"
    },
    {
      "r": "/api/v1/sales/vocabularios/motivos_descarte"
    },
    {
      "r": "/api/v1/origen/campanas"
    }
  ],
  "prevision": [
    {
      "r": "/api/v1/territorios",
      "o": "territorio"
    },
    {
      "r": "/api/v1/forecast/categorias",
      "p": "forecast:read"
    },
    {
      "r": "/api/v1/forecast/periodos",
      "p": "forecast:read"
    },
    {
      "r": "/api/v1/cuotas",
      "p": "forecast:read"
    },
    {
      "r": "/api/v1/cuotas/consecucion",
      "p": "forecast:read"
    },
    {
      "r": "/api/v1/ingresos/previsto",
      "p": "forecast:read"
    },
    {
      "r": "/api/v1/pipeline/resumen",
      "p": "opportunity:read"
    },
    {
      "r": "/api/v1/pipeline/estancadas"
    },
    {
      "r": "/api/v1/cuotas/congelaciones",
      "p": "forecast:read"
    }
  ],
  "canal": [
    {
      "r": "/api/v1/portal-partner/mis-registros",
      "p": "partner:read"
    },
    {
      "r": "/api/v1/partners",
      "p": "partner:read",
      "o": "partner"
    },
    {
      "r": "/api/v1/registros-oportunidad",
      "p": "partner:read"
    },
    {
      "r": "/api/v1/niveles-partner",
      "o": "nivel"
    },
    {
      "r": "/api/v1/partners/certificaciones/por-caducar"
    },
    {
      "r": "/api/v1/fondos-mdf",
      "p": "campaign:read",
      "o": "fondo"
    },
    {
      "r": "/api/v1/solicitudes-mdf"
    },
    {
      "r": "/api/v1/liquidaciones",
      "p": "commission:read"
    },
    {
      "r": "/api/v1/planes-comision"
    }
  ],
  "campo": [
    {
      "r": "/api/v1/ordenes-trabajo",
      "p": "case:read"
    },
    {
      "r": "/api/v1/activos",
      "p": "case:read",
      "o": "activo"
    },
    {
      "r": "/api/v1/tecnicos-campo",
      "o": "tecnico"
    },
    {
      "r": "/api/v1/planes-preventivos",
      "o": "plan_preventivo"
    },
    {
      "r": "/api/v1/planes-preventivos/vencimientos"
    },
    {
      "r": "/api/v1/repuestos/reposicion"
    },
    {
      "r": "/api/v1/repuestos/movimientos"
    },
    {
      "r": "/api/v1/activos/garantias/por-vencer"
    },
    {
      "r": "/api/v1/dispositivos"
    },
    {
      "r": "/api/v1/dispositivos/silenciosos"
    }
  ],
  "postventa": [
    {
      "r": "/api/v1/devoluciones",
      "p": "case:read",
      "o": "devolucion"
    },
    {
      "r": "/api/v1/expedientes"
    },
    {
      "r": "/api/v1/expedientes/vencen"
    },
    {
      "r": "/api/v1/problemas"
    },
    {
      "r": "/api/v1/problemas/correlacion"
    }
  ],
  "ia": [
    {
      "r": "/api/v1/ia/proveedores",
      "p": "ia:administrar"
    },
    {
      "r": "/api/v1/ia/modelos",
      "p": "ia:administrar"
    },
    {
      "r": "/api/v1/ia/conversacion/resumenes",
      "p": "ia:usar"
    },
    {
      "r": "/api/v1/ia/modelos/deriva",
      "p": "ia:administrar"
    },
    {
      "r": "/api/v1/ia/agentes-autonomos",
      "p": "ia:administrar"
    },
    {
      "r": "/api/v1/ia/anomalias",
      "p": "ia:usar"
    },
    {
      "r": "/api/v1/ia/guardias",
      "p": "ia:administrar"
    },
    {
      "r": "/api/v1/ia/plantillas",
      "p": "ia:administrar"
    },
    {
      "r": "/api/v1/ia/guardias/bloqueos",
      "p": "ia:administrar"
    },
    {
      "r": "/api/v1/ia/uso",
      "p": "ia:administrar"
    },
    {
      "r": "/api/v1/ia/uso/por-dia",
      "p": "ia:administrar"
    },
    {
      "r": "/api/v1/ia/salud"
    },
    {
      "r": "/api/v1/ia/prediccion"
    },
    {
      "r": "/api/v1/ia/extraidos"
    },
    {
      "r": "/api/v1/ia/salud/riesgo",
      "p": "ia:usar"
    },
    {
      "r": "/api/v1/agentes-ia/exposiciones",
      "p": "integracion:read"
    }
  ],
  "explotacion": [
    {
      "r": "/api/v1/analitica/estado"
    },
    {
      "r": "/api/v1/analitica/consultas"
    },
    {
      "r": "/api/v1/analitica/organizaciones",
      "sp": true
    },
    {
      "r": "/api/v1/metricas",
      "o": "metrica"
    },
    {
      "r": "/api/v1/almacen/tablas",
      "p": "informe:read",
      "o": "tabla_analitica"
    },
    {
      "r": "/api/v1/almacen/federadas",
      "p": "informe:read",
      "o": "tabla_analitica"
    },
    {
      "r": "/api/v1/cuadros-mando/embebidos",
      "p": "informe:read",
      "o": "enlace_embebido"
    },
    {
      "r": "/api/v1/informes/programaciones",
      "p": "informe:read"
    },
    {
      "r": "/api/v1/informes/ejecuciones",
      "p": "informe:read"
    },
    {
      "r": "/api/v1/almacen/frescura"
    },
    {
      "r": "/api/v1/almacen/destinos"
    },
    {
      "r": "/api/v1/analisis/despliegue"
    }
  ],
  "gobierno": [
    {
      "r": "/api/v1/grc/riesgos",
      "p": "tenant:read"
    },
    {
      "r": "/api/v1/grc/controles",
      "p": "tenant:read"
    },
    {
      "r": "/api/v1/segregacion/reglas"
    },
    {
      "r": "/api/v1/party/retencion/politicas"
    },
    {
      "r": "/api/v1/party/retencion/bloqueos"
    },
    {
      "r": "/api/v1/party/retencion/clases"
    }
  ],
  "segmentos": [
    {
      "r": "/api/v1/segmentos",
      "p": "segmento:read",
      "o": "segmento"
    },
    {
      "r": "/api/v1/supresiones"
    },
    {
      "r": "/api/v1/puntuacion/modelos"
    },
    {
      "r": "/api/v1/activos-marketing/aprobacion",
      "p": "marketing:read",
      "o": "activo_marketing"
    },
    {
      "r": "/api/v1/activos-marketing",
      "p": "marketing:read"
    }
  ],
  "campanas": [
    {
      "r": "/api/v1/marketing/papelera",
      "o": "entrada_papelera"
    },
    {
      "r": "/api/v1/campanas/calendario",
      "p": "campaign:read"
    },
    {
      "r": "/api/v1/campanas",
      "p": "campana:read",
      "o": "campana"
    },
    {
      "r": "/api/v1/presion/reglas"
    },
    {
      "r": "/api/v1/rebotes"
    },
    {
      "r": "/api/v1/recorridos",
      "p": "campana:read"
    }
  ],
  "casos": [
    {
      "r": "/api/v1/encuestas/resumen",
      "p": "case:read"
    },
    {
      "r": "/api/v1/encuestas",
      "o": "encuesta"
    },
    {
      "r": "/api/v1/agentes/disponibles"
    },
    {
      "r": "/api/v1/service/papelera",
      "o": "entrada_papelera"
    },
    {
      "r": "/api/v1/casos",
      "p": "case:read",
      "o": "caso"
    },
    {
      "r": "/api/v1/categorias-caso",
      "o": "categoria"
    },
    {
      "r": "/api/v1/sla/cumplimiento",
      "p": "case:read"
    },
    {
      "r": "/api/v1/sla"
    },
    {
      "r": "/api/v1/escalado/reglas"
    },
    {
      "r": "/api/v1/entitlements"
    },
    {
      "r": "/api/v1/creditos-servicio",
      "p": "case:read"
    },
    {
      "r": "/api/v1/creditos-servicio/cumplimiento",
      "p": "case:read"
    }
  ],
  "omnicanal": [
    {
      "r": "/api/v1/canales-servicio",
      "p": "case:read"
    },
    {
      "r": "/api/v1/macros",
      "o": "macro"
    }
  ],
  "conocimiento": [
    {
      "r": "/api/v1/conocimiento/articulos",
      "p": "knowledge:read",
      "o": "articulo"
    },
    {
      "r": "/api/v1/portal/accesos"
    },
    {
      "r": "/api/v1/comunidad/hilos"
    }
  ],
  "canales": [
    {
      "r": "/api/v1/canales-marketing",
      "p": "campana:read"
    },
    {
      "r": "/api/v1/landings"
    },
    {
      "r": "/api/v1/dominios-envio"
    }
  ],
  "contenido": [
    {
      "r": "/api/v1/reglas-contenido"
    },
    {
      "r": "/api/v1/optin/renovaciones"
    },
    {
      "r": "/api/v1/correo/plantillas",
      "p": "campana:read"
    },
    {
      "r": "/api/v1/correo/bloques"
    },
    {
      "r": "/api/v1/preferencias/categorias"
    },
    {
      "r": "/api/v1/supresiones"
    }
  ]
};
