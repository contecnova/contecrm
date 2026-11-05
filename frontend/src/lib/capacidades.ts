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
  // El gobierno de la IA: quién la presta y en qué región, con qué modelo y a
  // qué coste; qué modelos hay y con qué métricas y deriva; qué agentes están
  // sueltos, con sus permisos, su presupuesto y su punto de control humano; y
  // qué bloquearon las guardias. La trazabilidad por registro
  // (CRM-05.02.02.08) NO está declarada: su extremo cuelga de un registro y su
  // sitio es la ficha, que todavía no lo pinta.
  "ia": [
    // Sacar los datos de un contacto de un texto, y aceptarlos o rechazarlos uno a uno.
    "CRM-05.02.02.05",
    "CRM-05.02.01.04",
    "CRM-05.02.01.05",
    "CRM-05.02.01.07",
    "CRM-05.02.02.07",
    "CRM-05.02.02.09",
    "CRM-05.02.02.10",
    "CRM-05.02.03.01",
    "CRM-05.02.03.02",
    "CRM-05.02.03.03",
    "CRM-05.02.03.04",
    // Verificadas pulsando el 05-11-2026: «Predicciones» lleva «Forecast predictivo
    // al lado del humano» y la columna «Factores» que explica cada puntuación;
    // «Modelos» da de alta la versión entrenada con lo del tenant; y en «Agentes
    // autónomos» se declaran los agentes concretos —calificar leads, contestar
    // soporte— porque son configuración, con sus herramientas y su punto de parada.
    "CRM-03.02.01.06",
    "CRM-05.02.01.01",
    "CRM-05.02.01.06",
    "CRM-05.02.03.06",
    // Las exposiciones MCP: qué agente se expone, con «Publicar una herramienta».
    // Verificado pulsando el 05-11-2026.
    "CRM-00.03.04.11",
    // Proveedores de IA con su región y si el modelo es propio: es donde se
    // decide que el dato no salga. Verificado pulsando el 05-11-2026.
    "CRM-00.01.05.04",
  ],

  // El alta por API y el autoservicio (`POST /tenants`), el cambio de estado
  // —suspender, reactivar, congelar en solo lectura—, las unidades de
  // negocio, los ajustes jerárquicos, el catálogo de planes y capacidades,
  // la localización del tenant y su consumo contra el límite. Todo cuelga de
  // la ficha del tenant, que se abre porque la fila lleva `objeto`.
  "tenants": [
    // Sandboxes: se crean, se copian anonimizados y se apagan desde su ficha.
    "CRM-07.02.01.02",
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
    // La salida de un cliente: la ficha del tenant ofrece «Exportar los datos del
    // tenant» y «Destruir los datos del tenant y emitir el certificado».
    // Verificado pulsando el 05-11-2026.
    "CRM-00.01.03.05",
    "CRM-08.02.01.05",
    // Calendarios laborales con su país y «Añadir un festivo» en la ficha; la pausa
    // del reloj no tiene pantalla propia porque ocurre sola al pasar el caso a un
    // estado de espera, y se acumula en el caso. Y los tipos de cambio con fecha, que
    // son los que usa la previsión en otra moneda. Verificado pulsando el 05-11-2026.
    "CRM-04.01.02.04",
    "CRM-03.02.01.07",
    // Las migraciones entre regiones: su ficha abre la ventana de solo lectura,
    // verifica la integridad, cierra o revierte. Verificado pulsando el 05-11-2026.
    "CRM-00.01.03.09",
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
    // El código del tenant: «Extensiones» (alta, versiones que no se pisan,
    // probar, activar y volver atrás, ejecuciones y cómo va), «Endpoints
    // propios» y «Firmantes de confianza» para las de terceros.
    "CRM-00.04.02.01",
    "CRM-00.04.02.04",
    "CRM-00.04.02.05",
    "CRM-00.04.02.06",
    "CRM-00.04.02.07",
    // La automatización, en los campos de su propio registro: cuándo se
    // dispara y sobre qué campos vigilados (.02), qué hace —lista cerrada de
    // nueve acciones, ninguna que ejecute código (.03)— y si corre al momento,
    // al confirmar la transacción o a una hora (.05).
    "CRM-00.03.03.02",
    "CRM-00.03.03.03",
    "CRM-00.03.03.05",
    // Y la instancia de un proceso, en los suyos: cuándo despierta de una
    // espera (.07) y de qué proceso padre cuelga (.08).
    "CRM-00.03.02.07",
    "CRM-00.03.02.08",
    // La definición lleva su versión y su estado —borrador, publicado,
    // archivado—, y la instancia termina con la versión con la que empezó.
    "CRM-00.03.05.05",
    // Comprobadas a mano el 05-11-2026, pulsándolas en esta pantalla:
    // las condiciones y los campos vigilados de una automatización (.03.04);
    // «Llevar una automatización de pruebas a producción», que pide desde,
    // hacia y probada en seco (.03.08); «Instalar una plantilla de
    // automatizaciones por industria» (.03.09); «Copiar una plantilla de
    // flujo para modificarla» (.05.15); «Qué pasaría con lo que está en vuelo
    // al publicar otra versión» (.02.13); y el campo «Automática» de una
    // aprobación (.05.11). Las tres de plantillas y migración no se
    // alcanzaban hasta hoy: la regla de acciones excluía las de dos tramos.
    "CRM-00.03.03.04",
    "CRM-00.03.03.08",
    "CRM-00.03.03.09",
    "CRM-00.03.05.15",
    "CRM-00.03.02.13",
    "CRM-00.03.05.11",
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
    // Las sagas, con compensar hacia atrás el paso que falló: el order-to-cash
    // corre como una de ellas. Verificado pulsando el 05-11-2026.
    "CRM-03.03.02.12",
    // El catálogo de conectores nativos con «Instalar un conector en este tenant»;
    // los canales de entrada sin pantalla —correo, SMS, voz, chatbot— con su
    // «Registrar una interacción llegada por un canal»; y las vistas federadas, que
    // componen datos del ERP sin copiarlos. Verificado pulsando el 05-11-2026.
    "CRM-00.03.04.01",
    "CRM-00.02.03.09",
    "CRM-01.01.05.04",
  ],
  // Los objetos propios del tenant y el grafo de relaciones con sus tipos.
  "modelo": [
    // El código legible que la gente dice por teléfono: su patrón, su relleno,
    // cuándo reinicia y qué saldría el siguiente.
    "CRM-00.04.01.11",
    // Las dos puertas nuevas del campo, que se configuran en su propio
    // formulario: cuándo deja de poderse editar —condiciones sobre el
    // registro— y quién puede escribirlo —las procedencias—. Vacío en las
    // procedencias significa «cualquiera».
    "CRM-00.04.03.13",
    // Y con qué precisión se conoce una fecha: día, mes o trimestre. Se
    // declara entre las restricciones del campo, como el mínimo, el máximo o
    // los decimales, porque es una restricción de su tipo.
    "CRM-00.04.01.12",
    "CRM-00.04.01.01",
    "CRM-00.04.01.03",
    // Los vocabularios de negocio: cada lista dice si sigue con los valores de
    // fábrica o ya es de la empresa. Verificado pulsando el 05-11-2026.
    "CRM-07.01.01.03",
    // Los objetos propios del tenant, que extienden su modelo sin tocar el de
    // los demás. Verificado pulsando el 05-11-2026.
    "CRM-00.01.04.03",
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
    // Usuarios con su ficha, las licencias encima de la lista y «Dar de baja a un
    // usuario», que pregunta a quién pasan sus registros. La ficha no abría hasta
    // el 05-11-2026: le faltaba su GET. Verificado pulsando después.
    "CRM-07.01.01.02",
    // «Dar acceso temporal a alguien de fuera», en la lista de usuarios, con
    // motivo y caducidad obligatorios. Verificado pulsando el 05-11-2026.
    "CRM-06.02.01.06",
    // El portal del integrador: cada clave de API tiene en su fila «Qué ha hecho
    // esta clave este mes» —sus llamadas, lo que queda de cuota y los últimos
    // errores separados por culpa— y «Cambiar la cuota mensual». Las llamadas
    // las apunta el gateway. Verificado el 05-11-2026 con una clave real: tres
    // llamadas, el 404 y el 403 contados como del integrador.
    "CRM-00.02.04.06",
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
    // Proveedores de servicio con «Regla de elección de proveedor» y «A qué
    // proveedor iría este encargo»; y los buzones conectados, que registran solos lo
    // que llega por correo. Verificado pulsando el 05-11-2026.
    "CRM-00.04.05.07",
    "CRM-01.02.01.04",
  ],
  // La ficha de cuenta y la de contacto con sus canales, las relaciones entre
  // cuentas, las direcciones e identificadores fiscales con su
  // reverificación, las visitas, el mapa de personas e influencia, la cola de
  // calidad del dato con sus duplicados y su fusión, los derechos del
  // interesado y la papelera con restauración en cascada.
  "cuentas": [
    // La IA desde la ficha: resumir la cuenta y redactar un correo a un contacto.
    "CRM-01.01.05.05",
    "CRM-05.02.02.01",
    "CRM-05.02.02.02",
    // La segmentación completa de la cuenta, que es la que se vende: sector
    // con su esquema (CNAE/SIC/NAICS), tamaño, facturación, tier, ABC y ciclo
    // de vida. Llegaban cuatro de las seis: la clasificación ABC y «es una
    // persona» estaban en la tabla y no salían por la API.
    "CRM-01.01.01.07",
    "CRM-01.01.01.09",
    // La ficha de contacto con sus canales —correo principal y secundario,
    // teléfono, móvil y los canales alternativos declarados—, y sus cuatro
    // preferencias: canal, frecuencia máxima, idioma y horario. Las dos
    // últimas tampoco salían.
    "CRM-01.01.02.01",
    "CRM-01.01.02.05",
    // La puntuación de completitud de cada registro, con la lista de lo que
    // falta: no un número suelto, sino qué hay que rellenar.
    "CRM-01.01.04.05",
    // Y si el correo y el teléfono están verificados o sólo escritos. Un
    // correo sin verificar que se lee como bueno es una campaña que rebota
    // entera.
    "CRM-01.01.04.10",
    "CRM-01.01.01.01",
    "CRM-01.01.01.04",
    "CRM-01.01.01.05",
    "CRM-01.01.01.06",
    "CRM-01.01.01.13",
    "CRM-01.01.02.03",
    "CRM-01.01.02.04",
    "CRM-01.01.02.06",
    "CRM-01.01.04.08",
    "CRM-00.06.02.04",
    // Los derechos del interesado, verificados pulsando el 05-11-2026: la lista
    // va por vencimiento con los días restantes, y la ficha de cada solicitud
    // ofrece acceso, rectificación, supresión con bloqueos legales, portabilidad,
    // oposición y «Bloquear el tratamiento sin borrar nada».
    "CRM-02.04.02.04",
    "CRM-02.04.02.05",
    "CRM-07.03.01.03",
    // Las visitas: «Registrar la llegada» con latitud, longitud y si fue fuera de
    // sitio. Verificado pulsando el 05-11-2026.
    "CRM-01.02.01.08",
  ],
  // El proveedor como cuenta con rol, su homologación por categoría y la
  // documentación obligatoria con vigencia que avisa de lo que caduca.
  "proveedores": [
    "CRM-09.01.01.01",
    "CRM-09.01.01.02",
    "CRM-09.01.01.03",
    // Compras al proveedor, verificado pulsando el 05-11-2026 sobre lo
    // sembrado: peticiones de oferta con quién no ha contestado, la comparación
    // con la homologación y los papeles de cada uno, la fecha que se puede
    // prometer, el reparto, la capacidad con lo comprometido, el rappel con lo
    // comprado, el contrato con lo adjudicado sin entregar y el alcance; y en
    // la ficha del proveedor, la evaluación con sus entregas y la baja con lo
    // comprometido. Las calculadoras de antes —que pedían teclear los hechos—
    // quedan ocultas en la pantalla y siguen en la API.
    "CRM-09.02.01.04",
    "CRM-09.02.01.05",
    "CRM-09.02.01.06",
    "CRM-09.02.01.07",
    "CRM-09.02.01.08",
    "CRM-09.02.01.09",
    "CRM-09.01.01.04",
    "CRM-09.01.01.05",
    "CRM-09.01.01.07",
    "CRM-09.01.01.09",
    "CRM-09.01.01.10",
  ],
  // El modelo común de actividad —tareas, eventos, llamadas, notas y
  // visitas—, sus plantillas y secuencias por tipo de proceso, y las
  // recurrencias con su reprogramación.
  "actividades": [
    "CRM-01.02.01.01",
    "CRM-01.02.01.02",
    "CRM-01.02.01.07",
    "CRM-01.02.01.09",
    // Las actividades cuelgan de cualquier objeto: la lista enseña de cuál, y
    // la ficha delega, programa el recordatorio y la completa. Verificado pulsando el 05-11-2026.
    "CRM-01.02.01.03",
  ],
  // La oportunidad con su pipeline y sus etapas, los presupuestos con
  // versiones y vigencia, el motor de precios, los pedidos y su traspaso al
  // ERP, los contratos con su renovación, las suscripciones, el catálogo de
  // producto, las metodologías de venta, la cola priorizada del comercial y
  // la papelera.
  "oportunidades": [
    // «Qué hacer ahora con esta oportunidad», con las señales del negocio.
    "CRM-03.01.02.04",
    // La probabilidad de la etapa y la puesta a mano, las dos a la vez: saber
    // cuál manda es lo que separa una previsión creída de una inventada.
    // `probabilidad_manual` estaba en la tabla y no salía por la API.
    "CRM-03.01.01.04",
    // Por qué se perdió, con el motivo normalizado —que agrupa—, la nota
    // —que explica— y contra quién: sin el competidor, el informe dice
    // «precio» cincuenta veces y no dice contra quién. Las dos últimas
    // tampoco salían.
    "CRM-03.01.01.09",
    // Y que una oportunidad cerrada se bloquea, con el recuento de cuántas
    // veces se ha reabierto.
    "CRM-03.01.01.14",
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
    // «Registrar una revisión estructurada de la oportunidad», con el aviso de
    // cuántas revisiones tienen resultado antes de sacar conclusiones. Verificado pulsando el 05-11-2026.
    "CRM-03.01.02.06",
    // El coste del proveedor, de punta a punta, verificado el 05-11-2026: la
    // tarifa de coste se da de alta en «Listas de precio» con su sentido y su
    // proveedor; la oportunidad copia precio y coste del catálogo y enseña su
    // margen —con las líneas sin coste dichas—; y la oferta congela el coste y
    // avisa si hoy es otro, sin reescribirse.
    "CRM-09.02.01.01",
    "CRM-09.02.01.02",
    "CRM-09.02.01.03",
  ],
  // El lead con su ciclo de vida, la captura multicanal con sus canales y
  // recepciones, el enrutamiento por reglas, los motivos de descarte
  // normalizados, la trazabilidad de origen con sus campañas y toques, y las
  // cadencias con sus plantillas de correo.
  "leads": [
    // El motivo de descarte normalizado con su nota y su fecha de reciclaje:
    // el motivo agrupa —«precio»— y la nota dice cuál era el precio del otro.
    // La nota estaba en la tabla y no salía por la API.
    "CRM-01.01.03.05",
    // Y el SLA de primera respuesta: cuándo vencía, cuándo se contestó de
    // verdad y si se incumplió. Un lead que lleva tres semanas sin tocar no
    // se distingue de uno de ayer si esto no se ve.
    "CRM-01.01.03.07",
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
  // Las lecciones aprendidas: el expediente de cada cierre comparado con las
  // ganadas del mismo embudo, el post-mortem firmado y lo que se repite.
  "lecciones": [
    "CRM-03.01.01.15",
  ],
  "prevision": [
    // El cierre del objetivo de un periodo, con su historial de reaperturas.
    "CRM-03.02.02.08",
    "CRM-03.01.01.12",
    "CRM-03.02.01.01",
    "CRM-03.02.01.09",
    "CRM-03.02.02.01",
    "CRM-03.02.02.04",
    "CRM-03.02.02.06",
    // El ingreso previsto por periodo —cuándo entra el dinero, no cuándo se
    // firma— y los territorios con sus asignaciones, que deciden la visibilidad.
    // Verificado pulsando el 05-11-2026.
    "CRM-03.01.01.07",
    "CRM-00.05.02.07",
  ],
  // El registro de partners con sus niveles y certificaciones, el portal de
  // partner con el registro de oportunidades, los fondos de marketing con sus
  // solicitudes y liquidaciones, y los planes de comisión.
  "canal": [
    "CRM-03.02.03.01",
    "CRM-03.04.01.01",
    "CRM-03.04.01.02",
    "CRM-03.04.01.04",
    // El canal: el portal del partner acotado por el compartimento del token, el
    // acuerdo de precio de canal y si un precio lo puede dar solo, el rendimiento
    // del canal y el plan de negocio conjunto en la ficha del partner.
    // Verificado pulsando el 05-11-2026.
    "CRM-03.04.01.03",
    "CRM-03.04.01.05",
    "CRM-03.04.01.06",
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
  // y listas negras, y los modelos de puntuación. Y, desde la ficha de un
  // segmento y la de la puntuación de un lead, lo que antes sólo tenía API:
  // dinámico o congelado, el tamaño con su fecha y sus supresiones, el
  // solapamiento contra otro segmento, los dos ejes del score por separado con
  // su desglose, el decaimiento y los umbrales que disparan MQL y SQL.
  "segmentos": [
    "CRM-02.01.01.01",
    "CRM-02.01.01.02",
    "CRM-02.01.01.03",
    "CRM-02.01.01.04",
    "CRM-02.01.01.06",
    "CRM-02.01.01.07",
    "CRM-02.01.02.01",
    "CRM-02.01.02.03",
    "CRM-02.01.02.04",
    "CRM-02.01.02.05",
    "CRM-02.01.02.06",
    // La biblioteca de activos con su vigencia («Si este activo se puede usar
    // para esto y hoy») y su flujo de aprobación por pasos, también para campañas.
    // Verificado pulsando el 05-11-2026.
    "CRM-02.04.01.01",
    "CRM-02.04.01.02",
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
    // El calendario de campañas, que avisa de solapamientos por audiencia y canal
    // y no sólo por fechas. Verificado pulsando el 05-11-2026.
    "CRM-02.02.01.03",
  ],
  // El caso con su taxonomía y su ciclo, las colas con su asignación, las
  // reglas de escalado, los SLA con sus relojes, los entitlements, los
  // agentes disponibles con su capacidad, las encuestas de satisfacción y la
  // papelera.
  "casos": [
    // Casos resueltos y artículos parecidos, por significado, con su cita.
    "CRM-04.03.01.04",
    // Resumir el caso y sugerir respuesta con los artículos en que se apoya.
    "CRM-04.02.02.05",
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
    // En la conversación: resumirla, qué quiere el cliente y traducirle.
    "CRM-04.02.02.06",
    "CRM-04.02.02.07",
    "CRM-05.02.02.06",
    "CRM-04.02.02.04",
  ],
  // Los artículos con sus versiones y su flujo de aprobación, los accesos al
  // portal de autoservicio y los hilos de la comunidad.
  "conocimiento": [
    // Preguntar a la base de conocimiento: contesta sólo con los artículos, citándolos.
    "CRM-05.02.02.03",
    "CRM-04.03.01.01",
    "CRM-04.03.02.01",
    "CRM-04.03.02.04",
    // Los accesos al portal: identidades de fuera, aparte de las de empleados,
    // con su nivel y sus secciones, y la ficha que las quita o abre un caso en
    // su nombre. Verificado pulsando el 05-11-2026.
    "CRM-00.05.01.10",
    "CRM-04.03.02.05",
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
