/**
 * Qué capacidades del catálogo enseña cada pantalla genérica (CRM-07.04.05.05).
 *
 * Vive **fuera** de `modulos.ts` por una razón medida: `modulos.ts` lo importa
 * el marco —la barra, la paleta, las acciones— así que viaja en el módulo de
 * entrada, el que el navegador descarga antes de pintar nada. Esta lista no la
 * necesita el marco: sólo la pinta la cabecera de un módulo, dentro de un
 * desplegable cerrado. Son 180 identificadores hoy y crecen en cada bloque;
 * medido, media kilobyte comprimido que nadie necesita para ver su menú.
 *
 * `Modulo.tsx` la carga cuando ya está abierto el módulo. Si la carga falla,
 * la cabecera se queda sin la lista y la pantalla funciona igual: es una
 * declaración de trazabilidad, no contenido.
 *
 * Declarar aquí es la mitad barata; la cara es que **se pinta en el producto**,
 * así que una declaración falsa la ve el primero que entra.
 */

export const CAPACIDADES_POR_MODULO: Record<string, readonly string[]> = {
  // El alta por API y el autoservicio (`POST /tenants`), el cambio de estado
  // —suspender, reactivar, congelar en solo lectura—, las unidades de
  // negocio, los ajustes jerárquicos, el catálogo de planes y capacidades,
  // la localización del tenant y su consumo contra el límite. Todo cuelga de
  // la ficha del tenant, que se abre porque la fila lleva `objeto`.
  "tenants": [
    "CRM-00.01.03.01",
    "CRM-00.01.03.04",
    "CRM-00.01.03.08",
    "CRM-00.01.04.01",
    "CRM-00.01.04.05",
    "CRM-00.01.04.07",
    "CRM-00.01.06.06",
    "CRM-00.01.01.01",
    "CRM-00.01.01.02",
    "CRM-00.01.01.03",
    "CRM-00.01.01.04",
    "CRM-00.01.01.05",
    "CRM-00.01.05.01",
    "CRM-00.01.05.02",
    "CRM-00.01.05.03",
  ],
  // La superficie publicada entera —cada operación con su método, su ruta y
  // el permiso que exige— y la salud de cada servicio enrutado, que es el
  // catálogo interno con su dueño y su estado.
  "contrato": [
    "CRM-00.02.01.01",
    "CRM-00.02.01.04",
    "CRM-00.03.01.04",
  ],
  // El lienzo de procesos y sus instancias, la bandeja de tareas humanas, las
  // tablas de decisión, las automatizaciones, los webhooks, las conexiones
  // con su prueba y su rotación, el monitor de ejecuciones, el registro de
  // conectores instalables, los trabajos largos y el progreso de convivencia
  // con el CRM heredado.
  "procesos": [
    "CRM-00.02.01.12",
    "CRM-00.02.02.01",
    "CRM-00.03.01.07",
    "CRM-00.03.02.02",
    "CRM-00.03.02.09",
    "CRM-00.03.02.10",
    "CRM-00.03.02.11",
    "CRM-00.03.03.01",
    "CRM-00.03.04.02",
    "CRM-00.03.04.05",
    "CRM-00.03.04.06",
    "CRM-00.03.04.10",
    "CRM-00.03.05.09",
    "CRM-00.03.05.10",
  ],
  // Los objetos propios del tenant y el grafo de relaciones con sus tipos.
  "modelo": [
    "CRM-00.04.01.01",
    "CRM-00.04.01.03",
  ],
  // Proveedores de identidad por tenant, credenciales de máquina con ámbito y
  // caducidad, sesiones revocables, dispositivos de confianza, roles y las
  // políticas de acceso editables desde aquí.
  "acceso": [
    "CRM-00.05.01.03",
    "CRM-00.05.01.07",
    "CRM-00.05.01.08",
    "CRM-00.05.01.20",
    "CRM-00.05.02.01",
    "CRM-00.05.02.17",
  ],
  // El modelo canónico de intercambio, los conflictos de sincronización, el
  // catálogo de eventos publicado, la cola de fallidos con su reenvío y el
  // archivo desde el que se reproduce lo histórico.
  "operacion": [
    "CRM-00.02.02.03",
    "CRM-00.02.02.07",
    "CRM-00.02.02.09",
    "CRM-00.03.04.07",
    "CRM-00.03.04.08",
    "CRM-00.03.04.09",
    "CRM-00.04.05.01",
    "CRM-00.04.05.02",
    "CRM-00.04.05.04",
    "CRM-00.04.05.05",
    "CRM-00.04.05.08",
    "CRM-00.04.05.09",
    "CRM-00.04.05.10",
    "CRM-06.01.01.06",
    "CRM-06.01.02.09",
    "CRM-06.01.02.13",
    "CRM-06.01.02.14",
  ],
  // La ficha de cuenta y la de contacto con sus canales, las relaciones entre
  // cuentas, las direcciones e identificadores fiscales con su
  // reverificación, las visitas, el mapa de personas e influencia, la cola de
  // calidad del dato con sus duplicados y su fusión, los derechos del
  // interesado y la papelera con restauración en cascada.
  "cuentas": [
    "CRM-01.01.01.01",
    "CRM-01.01.01.04",
    "CRM-01.01.01.05",
    "CRM-01.01.01.06",
    "CRM-01.01.01.13",
    "CRM-01.01.02.03",
    "CRM-01.01.02.04",
    "CRM-01.01.02.06",
    "CRM-01.01.04.01",
    "CRM-01.01.04.03",
    "CRM-01.01.04.08",
    "CRM-00.06.02.04",
  ],
  // El proveedor como cuenta con rol, su homologación por categoría y la
  // documentación obligatoria con vigencia que avisa de lo que caduca.
  "proveedores": [
    "CRM-09.01.01.01",
    "CRM-09.01.01.02",
    "CRM-09.01.01.03",
  ],
  // El modelo común de actividad —tareas, eventos, llamadas, notas y
  // visitas—, sus plantillas y secuencias por tipo de proceso, y las
  // recurrencias con su reprogramación.
  "actividades": [
    "CRM-01.02.01.01",
    "CRM-01.02.01.02",
    "CRM-01.02.01.07",
    "CRM-01.02.01.09",
  ],
  // La oportunidad con su pipeline y sus etapas, los presupuestos con
  // versiones y vigencia, el motor de precios, los pedidos y su traspaso al
  // ERP, los contratos con su renovación, las suscripciones, el catálogo de
  // producto, las metodologías de venta, la cola priorizada del comercial y
  // la papelera.
  "oportunidades": [
    "CRM-03.01.01.01",
    "CRM-03.01.01.02",
    "CRM-03.01.01.03",
    "CRM-03.01.02.01",
    "CRM-03.03.01.02",
    "CRM-03.03.02.01",
    "CRM-03.03.02.03",
    "CRM-03.03.02.08",
    "CRM-03.03.02.09",
    "CRM-03.03.02.11",
  ],
  // El lead con su ciclo de vida, la captura multicanal con sus canales y
  // recepciones, el enrutamiento por reglas, los motivos de descarte
  // normalizados, la trazabilidad de origen con sus campañas y toques, y las
  // cadencias con sus plantillas de correo.
  "leads": [
    "CRM-01.01.03.01",
    "CRM-01.01.03.02",
    "CRM-01.01.03.04",
    "CRM-01.01.03.06",
    "CRM-03.03.01.01",
    "CRM-03.03.01.03",
  ],
  // Los territorios con su jerarquía, las categorías y periodos de forecast
  // con su cierre, las cuotas y su consecución, el ingreso previsto y el
  // resumen del pipeline con las oportunidades estancadas.
  "prevision": [
    "CRM-03.01.01.12",
    "CRM-03.02.01.01",
    "CRM-03.02.01.09",
    "CRM-03.02.02.01",
    "CRM-03.02.02.04",
    "CRM-03.02.02.06",
  ],
  // El registro de partners con sus niveles y certificaciones, el portal de
  // partner con el registro de oportunidades, los fondos de marketing con sus
  // solicitudes y liquidaciones, y los planes de comisión.
  "canal": [
    "CRM-03.02.03.01",
    "CRM-03.04.01.01",
    "CRM-03.04.01.02",
    "CRM-03.04.01.04",
  ],
  // Las órdenes de trabajo, los activos instalados con sus garantías, los
  // técnicos, los planes preventivos con sus vencimientos, los repuestos y su
  // reposición, y los dispositivos con su telemetría.
  "campo": [
    "CRM-04.04.01.01",
    "CRM-04.04.01.04",
    "CRM-04.04.01.05",
    "CRM-04.04.02.01",
    "CRM-04.04.02.03",
    "CRM-04.04.02.05",
  ],
  // Las devoluciones con su autorización y disposición, los expedientes con
  // sus plazos legales y los problemas con su correlación de casos.
  "postventa": [
    "CRM-04.01.01.11",
    "CRM-04.05.01.01",
    "CRM-04.05.01.03",
  ],
  // El estado del enlace con contecintelligence, las consultas con su
  // auditoría, la correspondencia entre tenant y organización, las métricas
  // certificadas, la frescura del almacén analítico y sus destinos de
  // exportación.
  "explotacion": [
    "CRM-05.01.03.01",
    "CRM-05.01.03.02",
    "CRM-05.01.03.03",
    "CRM-05.01.04.02",
    "CRM-05.01.04.07",
    "CRM-05.01.04.12",
  ],
  // El registro de riesgos y el catálogo de controles, las reglas de
  // segregación de funciones, las políticas de retención con sus bloqueos
  // legales y las clases de dato con su sensibilidad.
  "gobierno": [
    "CRM-07.03.01.01",
    "CRM-07.03.01.05",
    "CRM-07.03.01.06",
    "CRM-07.03.02.01",
    "CRM-07.03.02.02",
    "CRM-07.03.02.06",
  ],
  // El constructor de segmentos con sus condiciones anidadas, las supresiones
  // y listas negras, y los modelos de puntuación.
  "segmentos": [
    "CRM-02.01.01.01",
    "CRM-02.01.01.02",
    "CRM-02.01.01.06",
    "CRM-02.01.02.01",
  ],
  // La jerarquía de campañas con su presupuesto, las reglas de presión y
  // frecuencia de contacto, los rebotes duros y blandos, y la papelera.
  "campanas": [
    "CRM-02.02.01.01",
    "CRM-02.02.02.06",
    "CRM-02.03.01.04",
    "CRM-02.02.02.02",
    "CRM-02.02.02.03",
    "CRM-02.02.02.07",
    "CRM-02.02.02.08",
  ],
  // El caso con su taxonomía y su ciclo, las colas con su asignación, las
  // reglas de escalado, los SLA con sus relojes, los entitlements, los
  // agentes disponibles con su capacidad, las encuestas de satisfacción y la
  // papelera.
  "casos": [
    "CRM-04.01.01.01",
    "CRM-04.01.01.02",
    "CRM-04.01.01.05",
    "CRM-04.01.01.07",
    "CRM-04.01.01.12",
    "CRM-04.01.02.01",
    "CRM-04.01.02.02",
    "CRM-04.01.02.03",
    "CRM-04.02.02.03",
    "CRM-04.01.02.07",
    "CRM-04.01.02.08",
  ],
  // Los canales de servicio y las macros con sus acciones compuestas.
  "omnicanal": [
    "CRM-04.02.02.04",
  ],
  // Los artículos con sus versiones y su flujo de aprobación, los accesos al
  // portal de autoservicio y los hilos de la comunidad.
  "conocimiento": [
    "CRM-04.03.01.01",
    "CRM-04.03.02.01",
    "CRM-04.03.02.04",
  ],
  // Los canales de marketing, las landings y formularios alojados, y los
  // dominios de envío con su entregabilidad.
  "canales": [
    "CRM-02.03.01.03",
    "CRM-02.03.02.06",
  ],
  // Las reglas de contenido por marca, país e idioma, el consentimiento de
  // cookies, la renovación del opt-in, las plantillas de correo con sus
  // bloques reutilizables, las categorías del centro de preferencias y las
  // supresiones.
  "contenido": [
    "CRM-02.03.01.01",
    "CRM-02.03.01.05",
    "CRM-02.04.01.03",
    "CRM-02.04.02.02",
    "CRM-07.03.01.08",
  ],
};
