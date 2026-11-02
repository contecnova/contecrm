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
    // El `lang` del documento viaja con ella. `index.html` lo trae fijo en
    // «es» y un tenant en Portugal o en México se quedaba con esa marca aunque
    // sus números y sus fechas ya salieran bien.
    //
    // Lo que arregla y lo que no: con esto Firefox pinta el `<input
    // type="date">` en el formato del tenant, y los lectores de pantalla leen
    // el idioma correcto. **Chrome no**: para ese control usa la localización
    // del propio navegador y no mira `lang`, así que quien lo tenga en inglés
    // verá ahí `mm/dd/yyyy` por mucho que la pantalla esté en castellano. Eso
    // no se puede arreglar desde aquí.
    if (typeof document !== "undefined") document.documentElement.lang = limpio;
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
 * **Lo que sí se pierde, y se dice:** en la única lista donde conviven
 * `tamano` y `tamano_at` los dos rótulos pasan a ser «Tamaño». Es un caso en
 * 106 columnas declaradas, y el remedio —dejar «Tamano at» en todas las
 * demás— cuesta más de lo que arregla.
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
  maximo: "máximo",
  ultimo: "último",
  ultima: "última",
  proximo: "próximo",
  proxima: "próxima",
  analisis: "análisis",
  sintesis: "síntesis",
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

/** ¿Hay algo que enseñar? Una lista vacía y un objeto vacío no lo son. */
export function tieneDato(valor: unknown): boolean {
  if (valor === null || valor === undefined || valor === "") return false;
  if (Array.isArray(valor)) return valor.length > 0;
  if (typeof valor === "object") return Object.keys(valor as object).length > 0;
  return true;
}

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
  const texto = String(valor);
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
  "nombre",
  "nombre_completo",
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
