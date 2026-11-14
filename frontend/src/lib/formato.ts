/**
 * Cómo se escribe un valor para que lo lea una persona.
 *
 * Esto existe porque la tabla genérica volcaba los valores compuestos en JSON:
 * una celda con `{"procesos":true,"webhooks":true,"ia_gen…` recortada a la
 * mitad. Es información verdadera y es **inutilizable**: nadie lee un objeto
 * JSON de un vistazo, y recortado ni siquiera se puede leer entero.
 *
 * Lo mismo con los números —`19440000.00` no se lee, `19.440.000 €` sí— y con
 * las fechas en ISO, que son para máquinas.
 */

/**
 * La localización del tenant, **resuelta por el servidor** (CRM-07.04.01.05).
 *
 * Estaba escrita a mano: `"es-ES"` en dieciséis sitios de cinco ficheros, y
 * los formateadores creados como constantes de módulo — o sea que no podían
 * cambiar ni aunque alguien quisiera, porque se construyen al importar.
 *
 * Mientras tanto `GET /api/v1/localizacion` existe, resuelve la jerarquía
 * global → tier → tenant → unidad → usuario y devuelve **ejemplos como
 * contrato**, para que un cliente pueda comprobar que formatea igual que el
 * servidor sin reimplementar la jerarquía. Nadie lo leía. Un tenant en
 * Portugal o en México veía sus números escritos como en España.
 *
 * Aquí se guarda lo que diga el servidor y se reconstruyen los formateadores.
 * El castellano es el **respaldo hasta que llegue la respuesta**, no un valor
 * guardado: guardarlo al arrancar es como el ajuste del servidor se queda sin
 * usar para siempre.
 */
let LOCALE = "es-ES";
let NUMERO = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 2 });
let DINERO = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 });
/**
 * El año va ENTERO, no en dos cifras.
 *
 * `dateStyle: "short"` da «7/12/16» en castellano, y eso en un CRM es un
 * problema de verdad: la fecha de vencimiento de una actividad salía así y no
 * hay forma de saber si es 2016 o 2116 —ni, para quien venga de otro formato,
 * si el 7 es el día o el mes—. Un contrato que vence «el 3/4/25» se ha
 * discutido en más de una empresa.
 *
 * Se piden los campos a mano en vez de `dateStyle` porque `short` es lo único
 * que trae hora sin traerse también el día de la semana, y el año de cuatro
 * cifras no es negociable.
 */
const CAMPOS_FECHA = {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
} as const;
const CAMPOS_HORA = { hour: "2-digit", minute: "2-digit" } as const;
let FECHA = new Intl.DateTimeFormat(LOCALE, CAMPOS_FECHA);
let FECHA_HORA = new Intl.DateTimeFormat(LOCALE, {
  ...CAMPOS_FECHA,
  ...CAMPOS_HORA,
});
const MONEDAS = new Map<string, Intl.NumberFormat>();

/** La localización que se está usando ahora mismo. */
export function localizacion(): string {
  return LOCALE;
}

/**
 * El idioma de la voz: el de los TEXTOS, no el de la localización del tenant
 * (auditoría 13-11-2026, UX-31; la misma decisión que el `lang` del documento
 * en UX-15).
 *
 * Usaba `localizacion()`, y en un tenant `pt-PT` el navegador leía en voz alta
 * con fonética portuguesa respuestas escritas en castellano —los textos sólo
 * existen en los idiomas de `IDIOMAS`, hoy `es`— y esperaba oír portugués de
 * quien pregunta a una interfaz en castellano. La localización sí aporta algo
 * cuando es del MISMO idioma: la variante (`es-MX` frente a `es-ES`) afina el
 * reconocimiento; si es de otro, no dice nada de cómo habla quien está
 * delante y se descarta.
 */
export function idiomaDeVoz(idioma: string, locale: string): string {
  const base = idioma.split("-")[0] || "es";
  return locale.split("-")[0] === base ? locale : base;
}

/**
 * Fija la localización del tenant. La llama el arranque con lo que responde
 * `GET /api/v1/localizacion`.
 *
 * Una localización que `Intl` no conoce **no deja los números sin pintar**: se
 * queda la anterior. Un formateador que revienta vacía la pantalla entera, y
 * el precio de equivocarse en un código de idioma no puede ser ese.
 */
export function fijarLocalizacion(locale: string): void {
  const limpio = (locale || "").trim();
  if (!limpio || limpio === LOCALE) return;
  try {
    const numero = new Intl.NumberFormat(limpio, { maximumFractionDigits: 2 });
    const dinero = new Intl.NumberFormat(limpio, { maximumFractionDigits: 0 });
    const fecha = new Intl.DateTimeFormat(limpio, CAMPOS_FECHA);
    const fechaHora = new Intl.DateTimeFormat(limpio, {
      ...CAMPOS_FECHA,
      ...CAMPOS_HORA,
    });
    LOCALE = limpio;
    NUMERO = numero;
    DINERO = dinero;
    FECHA = fecha;
    FECHA_HORA = fechaHora;
    // El `lang` del documento **no** viaja con ella (auditoría 13-11-2026,
    // UX-15). Lo hacía, y un tenant en Portugal acababa con `lang="pt-PT"`
    // sobre textos que sólo existen en castellano: el lector de pantalla leía
    // «Guardar» con fonética portuguesa y el corrector del navegador marcaba
    // en rojo cada palabra. `lang` dice en qué idioma ESTÁ ESCRITO lo que se
    // ve, y eso lo decide i18n (`i18n/index.ts`); la localización del tenant
    // sólo decide cómo se escriben números, fechas e importes, que van por
    // `Intl` con ella dentro.
    // Las monedas ya construidas llevaban la localización vieja dentro.
    MONEDAS.clear();
  } catch {
    // Se queda la que había.
  }
}

const ISO_FECHA = /^\d{4}-\d{2}-\d{2}$/;
const ISO_MOMENTO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
export const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Nombres de campo que se leen como importes: se escriben sin decimales. */
const PARECE_IMPORTE =
  /(importe|facturacion|precio|coste|margen|total|saldo|cuota)/i;

/**
 * Prefijos técnicos que no aportan nada al leerlo.
 *
 * `quota_registros` se lee «Registros»: la columna ya se llama «Cuotas», y
 * repetir «quota» en cada etiqueta gasta espacio y no dice nada. Es una regla,
 * no una tabla de traducciones, para que no se quede corta al primer campo
 * nuevo.
 */
const PREFIJOS_TECNICOS = /^(quota|cuota|flag|attr|meta|config|param)_/;

/**
 * Las columnas que tiene TODA tabla, escritas como se leen.
 *
 * `created_at`, `updated_by`, `deleted_origen`… son del armazón, no del
 * negocio, y salían en inglés en la ficha de cualquier registro: «Created at»,
 * «Updated by», «Created origen». Es un conjunto cerrado —tres momentos por
 * tres aspectos— así que una tabla no se queda corta: no las inventa nadie,
 * las pone el modelo base.
 */
const DE_SISTEMA: Record<string, string> = {
  // Convive con `tamano` en la misma lista, y quitarle el `_at` dejaba las
  // dos columnas llamadas «Tamaño» — una con el número y otra con una fecha.
  // Visto en la pantalla de Segmentos el 03-11-2026. Es la excepción que la
  // regla de abajo ya preveía, puesta donde se pone: aquí, con su nombre.
  tamano_at: "Calculado",
  created_at: "Creado",
  updated_at: "Modificado",
  deleted_at: "Borrado",
  created_by: "Creado por",
  updated_by: "Modificado por",
  deleted_by: "Borrado por",
  created_origen: "Creado desde",
  updated_origen: "Modificado desde",
  deleted_origen: "Borrado desde",
};

/**
 * El sufijo `_at` marca «cuándo pasó» y no se lee.
 *
 * «Vence at», «Inicio at», «Completada at», «Recordar at»: lo escribe el
 * modelo para distinguir la marca de tiempo del campo, y quitarlo deja
 * exactamente lo que se quiere decir —«Vence», «Inicio», «Completada»—. El
 * dato que hay debajo ya es una fecha, así que no se pierde nada.
 *
 * **Lo que se pierde cuando colisiona** se arregla en `DE_SISTEMA`, no aquí:
 * `tamano` y `tamano_at` acababan los dos como «Tamaño», y en la lista de
 * Segmentos salían dos columnas con el mismo rótulo, una con el número y otra
 * con una fecha. Se vio mirando la pantalla el 03-11-2026 — llevaba
 * documentado como «un caso en 106 columnas» y dado por aceptable, y de
 * aceptable no tenía nada: dos columnas que se llaman igual obligan a leer
 * los datos para saber cuál es cuál.
 *
 * Que no vuelva a pasar lo vigila `ninguna_lista_repite_un_rotulo`, que mira
 * las columnas declaradas de los 25 módulos y no una sola lista.
 */
const MARCA_DE_TIEMPO = /_at$/;

/**
 * Palabras castellanas que un nombre de columna no puede llevar acentuadas.
 *
 * Una columna se llama `direccion`, `telefono`, `tamano`: el identificador no
 * admite tildes ni eñes. Hasta el 01-11-2026 eso salía tal cual a la pantalla
 * —«Direccion», «Tamano», «Dias medios de pago», «Sector codigo»— en los
 * rótulos de las listas, en el selector de columnas, en los avisos de calidad
 * del dato y en las métricas de la ficha. Un producto que escribe mal el
 * castellano en la primera pantalla no parece terminado, y no lo está.
 *
 * Esto NO es una tabla de campos: es de **palabras**, así que sirve igual para
 * `direccion`, `direccion_fiscal` y `email_direccion` sin tocar nada. Y lo
 * regular —`-cion` y `-sion`, que son 56 de las palabras de este producto— no
 * está aquí, está en una regla: una tabla que repite lo que una regla ya
 * resuelve se queda corta a la primera palabra nueva.
 *
 * Las de aquí son las irregulares, sacadas del vocabulario **real**: los
 * nombres de campo de los 13 contratos y las 106 columnas declaradas, no de
 * una lista imaginada.
 */
const CON_TILDE: Record<string, string> = {
  anadir: "añadir",
  engana: "engaña",
  telefonia: "telefonía",
  conservacion: "conservación",
  comprobacion: "comprobación",
  anonimo: "anónimo",
  mayusculas: "mayúsculas",
  inscripcion: "inscripción",
  ningun: "ningún",
  validas: "válidas",
  garantias: "garantías",
  compensacion: "compensación",
  grabacion: "grabación",
  erroneo: "erróneo",
  entro: "entró",
  imagenes: "imágenes",
  significacion: "significación",
  tardio: "tardío",
  decidio: "decidió",
  acerto: "acertó",
  atribucion: "atribución",
  basica: "básica",
  vinculo: "vínculo",
  adopcion: "adopción",
  eliminacion: "eliminación",
  maxima: "máxima",
  mayoria: "mayoría",
  leccion: "lección",
  hariamos: "haríamos",
  movio: "movió",
  multiple: "múltiple",
  tenian: "tenían",
  busqueda: "búsqueda",
  transicion: "transición",
  correlacion: "correlación",
  instantanea: "instantánea",
  instantaneas: "instantáneas",
  cuantas: "cuántas",
  leidas: "leídas",
  programacion: "programación",
  notificacion: "notificación",
  // `mencion_neutra` es uno de los tipos de lo que se recoge en redes, y el
  // humanizador lo pintaba «Mencion neutra». El producto escribe «menciones»
  // con tilde en todas partes menos ahí.
  mencion: "mención",
  menciones: "menciones",
  dia: "día",
  dias: "días",
  ano: "año",
  anos: "años",
  mas: "más",
  pais: "país",
  tamano: "tamaño",
  codigo: "código",
  titulo: "título",
  numero: "número",
  telefono: "teléfono",
  campeon: "campeón",
  categoria: "categoría",
  metrica: "métrica",
  metricas: "métricas",
  region: "región",
  metodo: "método",
  ambito: "ámbito",
  limite: "límite",
  minimo: "mínimo",
  minima: "mínima",
  maximo: "máximo",
  exposicion: "exposición",
  variacion: "variación",
  ultimo: "último",
  ultima: "última",
  // Las de los bloques de compras, sandboxes y extensiones (05-11-2026), que
  // salían sin tilde en sus columnas y en los resultados de sus acciones.
  ultimas: "últimas",
  senales: "señales",
  calculos: "cálculos",
  canonico: "canónico",
  canonica: "canónica",
  extraidos: "extraídos",
  desvio: "desvío",
  evaluacion: "evaluación",
  formacion: "formación",
  membresia: "membresía",
  peticion: "petición",
  resumenes: "resúmenes",
  vacios: "vacíos",
  proximo: "próximo",
  proxima: "próxima",
  analisis: "análisis",
  sintesis: "síntesis",
  // El sandbox de API y el archivo de histórico (09-11-2026).
  sinteticos: "sintéticos",
  antiguedad: "antigüedad",
  practica: "práctica",
  politica: "política",
  articulo: "artículo",
  credito: "crédito",
  deposito: "depósito",
  trafico: "tráfico",
  vehiculo: "vehículo",
  publico: "público",
  unico: "único",
  basico: "básico",
  tecnico: "técnico",
  fisico: "físico",
  logico: "lógico",
  historico: "histórico",
  economico: "económico",
  numerico: "numérico",
  geografico: "geográfico",
  electronico: "electrónico",
  automatico: "automático",
  telefonico: "telefónico",
  // ── Medido el 03-11-2026 ────────────────────────────────────────────
  //
  // Se vio en la pantalla de duplicados: «Forma juridica distinta». De ahí se
  // midió la familia entera en vez de arreglar la palabra: se sacaron del
  // contrato vivo **las 1.586 claves que el producto puede enseñar**
  // —propiedades y valores de enum de los trece servicios—, se humanizaron y
  // se cruzaron con cómo escribe el producto cada palabra en sus propios
  // textos. Salieron 62; éstas son las inequívocas.
  //
  // **Diez se quedan fuera a propósito**, porque sin tilde también son
  // correctas y ponérsela estropearía más de lo que arregla:
  //   · `cambio`   — `fecha_cierre_en_cambio` es el sustantivo, no «cambió»
  //   · `como`     — `actua_como_id` es «actúa como»
  //   · `este`     — `solo_este_tenant` es el demostrativo
  //   · `paso`     — un paso de un proceso, no «pasó»
  //   · `intento`  — el sustantivo
  //   · `solo`     — la RAE le quitó la tilde en 2010
  //   · `cual`, `cuando`, `cuantos`, `quien` — como etiqueta serían
  //     interrogativos, pero `humanizar` también pinta VALORES y ahí no lo
  //     son. Sin saber cuál de los dos es, se deja como está.
  accion: "acción",
  afectaria: "afectaría",
  alli: "allí",
  anade: "añade",
  anadidos: "añadidos",
  analitica: "analítica",
  aprobaria: "aprobaría",
  aqui: "aquí",
  asercion: "aserción",
  auditoria: "auditoría",
  automatizacion: "automatización",
  autenticacion: "autenticación",
  autonomo: "autónomo",
  buzon: "buzón",
  cabria: "cabría",
  caduco: "caducó",
  caida: "caída",
  cambiarian: "cambiarían",
  comision: "comisión",
  comparticion: "compartición",
  condicion: "condición",
  configuracion: "configuración",
  conversion: "conversión",
  correccion: "corrección",
  creditos: "créditos",
  cumplio: "cumplió",
  debiles: "débiles",
  deflexion: "deflexión",
  delegacion: "delegación",
  detras: "detrás",
  digitos: "dígitos",
  diseno: "diseño",
  division: "división",
  eleccion: "elección",
  escribio: "escribió",
  existia: "existía",
  explicito: "explícito",
  extraccion: "extracción",
  fusion: "fusión",
  generacion: "generación",
  generico: "genérico",
  grafico: "gráfico",
  habia: "había",
  habria: "habría",
  integracion: "integración",
  leido: "leído",
  libreria: "librería",
  limites: "límites",
  liquidacion: "liquidación",
  medicion: "medición",
  metodologia: "metodología",
  modulos: "módulos",
  nucleo: "núcleo",
  numeros: "números",
  pagina: "página",
  parametro: "parámetro",
  pestana: "pestaña",
  politicas: "políticas",
  prediccion: "predicción",
  prevision: "previsión",
  produccion: "producción",
  reclamacion: "reclamación",
  respondio: "respondió",
  reutilizacion: "reutilización",
  reversion: "reversión",
  saldrian: "saldrían",
  seccion: "sección",
  senal: "señal",
  sesion: "sesión",
  suplantacion: "suplantación",
  tecnicos: "técnicos",
  ultimos: "últimos",
  vencio: "venció",
  actualizacion: "actualización",
  anfitrion: "anfitrión",
  automatica: "automática",
  cache: "caché",
  categorias: "categorías",
  cluster: "clúster",
  codigos: "códigos",
  comparacion: "comparación",
  composicion: "composición",
  confirmacion: "confirmación",
  creacion: "creación",
  declaracion: "declaración",
  devolucion: "devolución",
  duracion: "duración",
  exportacion: "exportación",
  expresion: "expresión",
  extension: "extensión",
  formula: "fórmula",
  interaccion: "interacción",
  limitacion: "limitación",
  millon: "millón",
  modificacion: "modificación",
  movil: "móvil",
  obligacion: "obligación",
  ocurrio: "ocurrió",
  ordenes: "órdenes",
  paginas: "páginas",
  parametros: "parámetros",
  patron: "patrón",
  preproduccion: "preproducción",
  prohibe: "prohíbe",
  proteccion: "protección",
  raiz: "raíz",
  rectificacion: "rectificación",
  recuperacion: "recuperación",
  relacion: "relación",
  renovacion: "renovación",
  reparacion: "reparación",
  replica: "réplica",
  replicas: "réplicas",
  sincronizacion: "sincronización",
  transcripcion: "transcripción",
  vacio: "vacío",
  validacion: "validación",
  atras: "atrás",
  catalogo: "catálogo",
  migracion: "migración",
  antelacion: "antelación",
  aprobacion: "aprobación",
  asignacion: "asignación",
  actua: "actúa",
  campana: "campaña",
  campanas: "campañas",
  clasificacion: "clasificación",
  conexion: "conexión",
  contrasena: "contraseña",
  conversacion: "conversación",
  decision: "decisión",
  definicion: "definición",
  descripcion: "descripción",
  despues: "después",
  dinamico: "dinámico",
  direccion: "dirección",
  dueno: "dueño",
  duenos: "dueños",
  ejecucion: "ejecución",
  envio: "envío",
  envios: "envíos",
  excepcion: "excepción",
  exclusion: "exclusión",
  facturacion: "facturación",
  funcion: "función",
  garantia: "garantía",
  identificacion: "identificación",
  incumplio: "incumplió",
  indice: "índice",
  instalacion: "instalación",
  interes: "interés",
  jerarquia: "jerarquía",
  juridica: "jurídica",
  juridico: "jurídico",
  legitimo: "legítimo",
  linea: "línea",
  lineas: "líneas",
  maquina: "máquina",
  modulo: "módulo",
  operacion: "operación",
  organizacion: "organización",
  porque: "porqué",
  proposito: "propósito",
  propension: "propensión",
  leidos: "leídos",
  puntuacion: "puntuación",
  resolucion: "resolución",
  reunion: "reunión",
  revision: "revisión",
  solucion: "solución",
  supresion: "supresión",
  suscripcion: "suscripción",
  unica: "única",
  util: "útil",
  valida: "válida",
  valido: "válido",
  version: "versión",
  // Inglés que se ha colado en un nombre de columna. Sólo lo que de verdad
  // está: `owner_id` salía «Owner id» en los avisos de calidad de cada ficha.
  owner: "responsable",
};

/** Siglas: se escriben enteras en mayúsculas, no «Nps» ni «Iva». */
const SIGLAS = new Set([
  "id",
  "iva",
  "nps",
  "roi",
  "kpi",
  "sla",
  "slo",
  "api",
  "url",
  "uri",
  "crm",
  "erp",
  "bi",
  "ia",
  "sql",
  "csv",
  "pdf",
  "http",
  "https",
  "dns",
  "ip",
  "sso",
  "mfa",
  "rgpd",
  "cif",
  "nif",
  "iban",
  "sepa",
  "utc",
]);

/**
 * Una palabra suelta de un nombre de campo, escrita en castellano.
 *
 * El orden importa: primero la regla regular, que no envejece, y sólo después
 * la tabla.
 */
function enCastellano(palabra: string): string {
  if (SIGLAS.has(palabra)) return palabra.toUpperCase();
  // `-cion` → `-ción`, `-sion` → `-sión`. Una regla, no 56 entradas:
  // «facturacion», «puntuacion», «direccion», «conversion»… y las que vengan.
  if (/[cs]ion$/.test(palabra)) return palabra.slice(0, -3) + "ión";
  if (/[cs]iones$/.test(palabra)) return palabra.slice(0, -5) + "iones";
  return CON_TILDE[palabra] ?? palabra;
}

/**
 * El resumen de una operación, listo para ser el rótulo de un botón.
 *
 * Los resúmenes del contrato llevan a veces el código de la capacidad que los
 * respalda —«Comprobar un contenido antes de mandarlo (CRM-02.04.01.03)»—. Ahí
 * está bien: quien integra lo lee en el OpenAPI y la trazabilidad lo cita. En
 * un botón no: a quien comprueba un contenido, `CRM-02.04.01.03` no le dice
 * nada y le ocupa media mitad del rótulo.
 *
 * Se quita aquí y no en los servicios por eso mismo: el código tiene que
 * seguir en el contrato. **Medido el 04-11-2026: 43 de 2.452 resúmenes lo
 * llevan**, y se vieron al salir por primera vez como botones.
 *
 * Admite el código solo y la lista —«(CRM-00.01.05.01, .02)»—, que es como se
 * escriben los que respaldan más de una.
 */
export function comoRotulo(resumen: string | null | undefined): string {
  return String(resumen ?? "")
    .replace(/\s*\(\s*CRM-[\d.]+(?:\s*,\s*(?:CRM-)?[\d.]+)*\s*\)/g, "")
    .trim();
}

/**
 * El nombre del campo, escrito como se lee: `sector_codigo` → «Sector código».
 *
 * Sirve también para los **valores**: `esperando_cliente` → «Esperando
 * cliente». Son el mismo problema —un identificador enseñado a una persona— y
 * arreglarlo en un sitio los arregla en los veinte que la llaman.
 */
export function humanizar(campo: string | null | undefined): string {
  // Un rótulo no puede tumbar una pantalla. Pasó: la ficha de una
  // oportunidad reventaba entera porque un campo venía `undefined` y aquí
  // se llamaba a `.replace` sobre él. Lo que falta se queda en blanco.
  if (!campo) return "";
  // Por guion bajo **y por espacio**: unas veces llega el nombre crudo
  // (`sector_codigo`) y otras el `title` del contrato, que Pydantic genera en
  // inglés-Title-Case («Tenant Id», «Desde Moneda»). Partiendo sólo por guion,
  // ese segundo caso entraba entero como una palabra y no se arreglaba nada.
  const delSistema = DE_SISTEMA[campo];
  if (delSistema) return delSistema;
  const palabras = campo
    .replace(PREFIJOS_TECNICOS, "")
    .replace(MARCA_DE_TIEMPO, "")
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((p) => enCastellano(p.toLowerCase()));
  if (palabras.length === 0) return "";
  const primera = palabras[0]!;
  // Una sigla no se «capitaliza»: ya está entera en mayúsculas.
  const inicio =
    primera === primera.toUpperCase()
      ? primera
      : primera.charAt(0).toUpperCase() + primera.slice(1);
  return [inicio, ...palabras.slice(1)].join(" ");
}

/**
 * El texto de una opción de lista: `descuento_tardio` → «Descuento tardío».
 *
 * No es `humanizar`, que es para nombres de campo: aquél quita prefijos
 * técnicos y pasa todo a minúsculas, y una opción como `EUR` o `B2B` salía
 * «Eur». Las siglas se quedan como vienen.
 */
export function rotuloDeOpcion(valor: string): string {
  if (!valor || valor === valor.toUpperCase()) return valor;
  // «opportunity:write» es un permiso, código: ponerle mayúscula y quitarle el
  // guion bajo lo convierte en otro texto que nadie encuentra en un rol.
  if (valor.includes(":")) return valor;
  const palabras = valor
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((p) => enCastellano(p.toLowerCase()));
  const primera = palabras[0] ?? "";
  return [
    primera.charAt(0).toUpperCase() + primera.slice(1),
    ...palabras.slice(1),
  ].join(" ");
}

/** ¿Hay algo que enseñar? Una lista vacía y un objeto vacío no lo son. */
export function tieneDato(valor: unknown): boolean {
  if (valor === null || valor === undefined || valor === "") return false;
  if (Array.isArray(valor)) return valor.length > 0;
  if (typeof valor === "object") return Object.keys(valor as object).length > 0;
  return true;
}

/**
 * Las opciones de lista cerrada que han declarado los contratos cargados, por
 * nombre de campo. Las rellena `contratoDe` al cargar cada contrato.
 *
 * Con esto, «abierta» en el campo `estado` sale «Abierta» porque el servidor
 * dice que es una opción, no porque la pantalla lo suponga: una palabra suelta
 * en minúscula puede ser también un nombre o un identificador.
 */
const OPCIONES_DE_CAMPO = new Map<string, Set<string>>();

export function registrarOpciones(nuevas: Map<string, Set<string>>): void {
  for (const [campo, valores] of nuevas) {
    const hay = OPCIONES_DE_CAMPO.get(campo) ?? new Set<string>();
    for (const v of valores) hay.add(v);
    OPCIONES_DE_CAMPO.set(campo, hay);
  }
}

/** Un código de opción: `descuento_tardio`, `en_curso`. */
const CODIGO_DE_OPCION = /^[a-z][a-z0-9]*(_[a-z0-9]+)+$/;

/** Un número, una fecha o un texto, escritos en castellano. */

export function escalar(valor: unknown, campo = "", moneda = ""): string {
  // **Sin dato es una raya, nunca la palabra «null».** `String(null)` da
  // «null», y eso llegaba a la pantalla a través de `trozos`: la pestaña
  // «Detalles» de un caso enseñaba «Motivo: null», «Padre: null»,
  // «Contacto ID: null». Quien lo lee no sabe si es un hueco o un valor que
  // alguien escribió. Medido el 02-11-2026.
  if (valor === null || valor === undefined) return "—";
  if (typeof valor === "boolean") return valor ? "sí" : "no";
  // Un importe con la moneda del registro sale CON su símbolo. Sin ella no se
  // inventa ninguna: una cifra con el símbolo equivocado es peor que una
  // cifra sin símbolo. **Medido el 02-11-2026**: la ficha de una oportunidad
  // decía «Importe 117.693» arriba y «117.693 €» tres centímetros más abajo,
  // el mismo dato con dos formatos en la misma pantalla.
  const comoDinero = (n: number) =>
    PARECE_IMPORTE.test(campo)
      ? moneda
        ? importe(n, moneda)
        : DINERO.format(n)
      : NUMERO.format(n);
  if (typeof valor === "number") return comoDinero(valor);
  // Una lista, separada como se escribe —«Precio, Descuento tardío»— y no
  // como la pinta `String()`: «precio,descuento_tardio».
  if (Array.isArray(valor)) {
    if (!valor.length) return "—";
    // Si todos son códigos —`competidor`, `decisor_en_contra`—, se escriben
    // todos como texto: tratar sólo los que llevan guion bajo dejaba
    // «competidor, Decisor en contra» en la misma línea.
    const codigos = valor.every(
      (v) => typeof v === "string" && /^[a-z0-9_]+$/.test(v),
    );
    return valor
      .map((v) =>
        codigos ? rotuloDeOpcion(String(v)) : escalar(v, campo, moneda),
      )
      .join(", ");
  }
  const texto = String(valor);
  // Una opción que el contrato declara para este campo se escribe como texto.
  if (campo && OPCIONES_DE_CAMPO.get(campo)?.has(texto))
    return rotuloDeOpcion(texto);
  // Un código de opción —`descuento_tardio`, `en_curso`— se lee como texto.
  // Sólo con guion bajo: una palabra suelta puede ser un nombre o un
  // identificador corto, y cambiarle la mayúscula lo falsearía.
  if (CODIGO_DE_OPCION.test(texto)) return rotuloDeOpcion(texto);
  // Los decimales llegan como cadena desde la API (`Numeric` en JSON es texto
  // para no perder precisión), así que hay que reconocerlos aquí.
  if (/^-?\d+(\.\d+)?$/.test(texto) && texto.length < 18) {
    return comoDinero(Number(texto));
  }
  if (ISO_MOMENTO.test(texto)) {
    const d = new Date(texto);
    if (!Number.isNaN(d.getTime())) return FECHA_HORA.format(d);
  }
  if (ISO_FECHA.test(texto)) {
    const d = new Date(`${texto}T00:00:00`);
    if (!Number.isNaN(d.getTime())) return FECHA.format(d);
  }
  return texto;
}

/**
 * Una fecha escrita como aquí se escribe.
 *
 * Existe porque diez pantallas llamaban a `new Date(x).toLocaleDateString()`
 * **sin localización**, y entonces manda la del navegador: una oferta válida
 * hasta el 26 de noviembre salía como «Válido hasta el 11/26/2026» en una
 * pantalla en castellano. La localización de este producto no es la del
 * navegador: la resuelve el servidor por tenant, unidad y usuario
 * (`GET /api/v1/localizacion`), y es la que llevan `FECHA` y `FECHA_HORA`.
 *
 * Un valor vacío o ilegible devuelve una raya, no «Invalid Date».
 */
export function fecha(valor: unknown): string {
  if (!tieneDato(valor)) return "—";
  const d = valor instanceof Date ? valor : new Date(String(valor));
  return Number.isNaN(d.getTime()) ? "—" : FECHA.format(d);
}

/** Una fecha con su hora, igual que `fecha` pero cuando la hora importa. */
export function fechaHora(valor: unknown): string {
  if (!tieneDato(valor)) return "—";
  const d = valor instanceof Date ? valor : new Date(String(valor));
  return Number.isNaN(d.getTime()) ? "—" : FECHA_HORA.format(d);
}

export interface Trozo {
  texto: string;
  /** Un interruptor apagado se pinta distinto de uno encendido. */
  apagado?: boolean;
}

/**
 * Un valor compuesto, convertido en trozos legibles.
 *
 * Un objeto de interruptores —`{"procesos":true,"ia_generativa":false}`— se lee
 * como lo que es: qué está encendido y qué no. Un objeto de cifras —las
 * cuotas— como pares «nombre: cifra». Y una lista, como sus elementos.
 */
export function trozos(valor: unknown, campo = ""): Trozo[] {
  if (Array.isArray(valor)) {
    return valor.map((v) => ({
      texto:
        v !== null && typeof v === "object"
          ? trozos(v)
              .map((t) => t.texto)
              .join(" · ")
          : escalar(v, campo),
    }));
  }
  if (valor !== null && typeof valor === "object") {
    return Object.entries(valor as Record<string, unknown>).map(([k, v]) => {
      if (typeof v === "boolean") return { texto: humanizar(k), apagado: !v };
      if (v !== null && typeof v === "object") {
        return { texto: `${humanizar(k)}: ${trozos(v).length}` };
      }
      return { texto: `${humanizar(k)}: ${escalar(v, k)}` };
    });
  }
  return [{ texto: escalar(valor, campo) }];
}

/**
 * Una cifra sin unidad, con los separadores de la empresa. Para sumar una
 * columna que no se sabe si es dinero: «48 €» sumando horas de plazo dice algo
 * que no es.
 */
export function cifra(valor: unknown): string {
  const numero = Number(valor ?? 0);
  if (Number.isNaN(numero)) return String(valor ?? "");
  return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 2 }).format(
    numero,
  );
}

/**
 * Un importe con su moneda, como se escribe en español: «217.788 €».
 *
 * `217788.00 EUR` no es un importe: es el dato en crudo. El símbolo va detrás
 * y separado, que es la convención de aquí, y lo pone `Intl` para que una
 * instalación en otra moneda no tenga que tocar nada.
 */
export function importe(valor: unknown, moneda = "EUR"): string {
  const numero = Number(valor ?? 0);
  if (Number.isNaN(numero)) return String(valor ?? "");
  let formato = MONEDAS.get(moneda);
  if (!formato) {
    try {
      formato = new Intl.NumberFormat(LOCALE, {
        style: "currency",
        currency: moneda,
        maximumFractionDigits: 0,
      });
    } catch {
      // Una moneda que `Intl` no conoce no puede dejar la cifra sin pintar.
      formato = DINERO;
    }
    MONEDAS.set(moneda, formato);
  }
  return formato.format(numero);
}

/**
 * Un precio unitario, con sus céntimos cuando los tiene.
 *
 * `importe` redondea a euros enteros, que es lo que pide un total. Un precio
 * unitario no: «100 × 14 €» al lado de «1420 €» era un arnés de 14,20 €
 * (visto el 10-11-2026), y la cuenta no salía.
 */
export function importeUnitario(valor: unknown, moneda = "EUR"): string {
  const numero = Number(valor ?? 0);
  if (Number.isNaN(numero)) return String(valor ?? "");
  if (Number.isInteger(numero)) return importe(numero, moneda);
  try {
    return new Intl.NumberFormat(LOCALE, {
      style: "currency",
      currency: moneda,
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    }).format(numero);
  } catch {
    return NUMERO.format(numero);
  }
}

/**
 * Campos que identifican al registro para la máquina, no para quien mira.
 *
 * `cuenta_id = 01a0cd8c-880c-7f85-96bc-0f01dce176a2` no es información: es el
 * dato en crudo. Ocupan la mitad de una ficha y no dicen nada, así que no se
 * enseñan de entrada — pero siguen estando a un clic, porque quien abre una
 * incidencia de soporte los necesita enteros.
 */
export function esIdentificadorTecnico(campo: string): boolean {
  return campo === "id" || campo === "version" || /(^|_)id$/.test(campo);
}

/**
 * Cómo se llama este registro para una persona.
 *
 * Se busca el primer campo con el que alguien lo reconocería. Sin esto, la
 * ficha de una oportunidad se titulaba con su UUID: el propio registro no decía
 * cuál era.
 */
const CAMPOS_DE_NOMBRE = [
  // El completo antes que el nombre: quien trae los dos es una persona, y su
  // `nombre` es sólo el de pila. El selector de contactos ofrecía «Paco»,
  // «Ana», «Silvia»… y dos Silvias que no había forma de distinguir.
  "nombre_completo",
  "nombre",
  "asunto",
  "titulo",
  "razon_social",
  "clave",
  "codigo",
  "email",
  "slug",
] as const;

/**
 * De QUÉ campo salió el nombre, no sólo cuál es.
 *
 * Hace falta para no enseñarlo dos veces. La tarjeta de un caso se titulaba
 * «Discrepancia en el albarán — Componentes Delta» y justo debajo repetía
 * «Asunto: Discrepancia en el albarán — Componentes Del…», recortado: el mismo
 * texto dos veces, la segunda peor, gastando una de las cinco líneas útiles.
 * Pasaba porque quien montaba la tarjeta excluía el campo `"nombre"` escrito a
 * mano, y un caso no tiene `nombre`: se titula por `asunto`. Igual con
 * `titulo`, `razon_social`, `clave`, `codigo`, `email`, `slug` y
 * `nombre_completo` — ocho de los nueve campos de la lista.
 */
export function campoDelNombre(fila: Record<string, unknown>): string {
  for (const clave of CAMPOS_DE_NOMBRE) {
    const valor = fila[clave];
    if (typeof valor === "string" && valor.trim()) return clave;
  }
  return "";
}

export function nombreDelRegistro(fila: Record<string, unknown>): string {
  const clave = campoDelNombre(fila);
  return clave ? String(fila[clave]) : "";
}
