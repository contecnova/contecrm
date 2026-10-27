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
import { VISIBILIDAD } from "@/lib/visibilidad";
import { rutaPermitida } from "@/lib/superficie";

export interface Modulo {
  /** Camino en la aplicación. */
  ruta: string;
  titulo: string;
  /** Sección del catálogo funcional que enseña. */
  seccion: string;
  /** Capacidad del catálogo que esta pantalla implementa. Es la traza. */
  capacidad: string;
  // Las DEMÁS capacidades del catálogo que esta pantalla enseña viven en
  // `capacidades.ts`, no aquí: este fichero lo importa el marco y viaja en el
  // módulo de entrada, y esa lista sólo la pinta la cabecera de un módulo.
  /** Grupo del menú. */
  grupo: string;
  // Las pestañas viven en `recursos.ts` y se piden cuando hacen falta: ese
  // fichero son 42 kB comprimidos que sólo necesitan cinco pantallas, y
  // ninguna se abre al entrar. Lo mínimo para decidir si este módulo se
  // enseña en el menú está en `visibilidad.ts`, derivado de aquél.
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
   * El recurso es un informe de un PERIODO: exige `desde` y `hasta`.
   *
   * Es el hermano de `busqueda` para los informes —cumplimiento de SLA,
   * cumplimiento por proveedor— y hacía falta porque `busqueda` admite un solo
   * parámetro. Sin esto, la pestaña se abría y la API contestaba 422 nada más
   * entrar: una pantalla con su rótulo y un error para alguien.
   *
   * **No se inventa un periodo por defecto.** Un informe que se abre con «los
   * últimos noventa días» sin que nadie lo pida se lee como si fuera el dato,
   * y el número que se copia a un correo es de un periodo que no eligió nadie.
   * Como en `busqueda`: no se pide nada hasta que hay rango.
   */
  periodo?: boolean;
  /**
   * La misma colección existe en VARIOS servicios, cada uno con lo suyo.
   *
   * Las políticas de retención, los trabajos de fondo, los vocabularios de
   * negocio y la búsqueda por objeto los publica cada servicio en su propio
   * prefijo —`/api/v1/:servicio/retencion/politicas`— porque cada uno guarda
   * los suyos en su esquema. Eso es correcto por dentro, y por fuera creaba un
   * problema que no se veía: la pestaña apuntaba a **uno** de ellos y se
   * llamaba «Retención», así que quien la abría creía estar viendo todas las
   * políticas del sistema cuando veía las de clientes. Las de identidad y las
   * de ventas no tenían pantalla.
   *
   * Con esto, `listar` lleva `:servicio` y la pantalla pone un selector con
   * estos nombres. Una pestaña, todos los servicios, y ninguno escondido.
   *
   * La alternativa era una pestaña por servicio —«Retención (clientes)»,
   * «Retención (ventas)»…— y son tres pestañas que dicen lo mismo en un menú
   * donde ya hay veinte.
   */
  por_servicio?: string[];
  /**
   * Medidas que acompañan a este listado: un objeto, no una lista.
   *
   * De las colecciones publicadas sin pantalla, **96 de 157 son esto**: un
   * `GET` que devuelve un objeto con cuatro cifras y una frase que explica qué
   * significan —«el presupuesto de IA gastado este mes», «cuánto se lleva
   * consumido de lo contratado», «si los avisos de anomalía sirven de algo»—.
   * No son listados y por eso no cabían como pestaña, y hacerle una pantalla a
   * cada una serían noventa y seis pantallas de un párrafo.
   *
   * Se pintan arriba del listado al que pertenecen, que es donde se preguntan:
   * el gasto del mes, encima del consumo; la calidad de los borradores, encima
   * de los borradores. Lo que se enseña sale del propio objeto —las cifras y
   * su explicación—, así que una medida nueva no pide código.
   *
   * Cada una con su fallo: que no se pueda leer una medida no puede dejar sin
   * ver el listado, que es a lo que se venía.
   */
  resumen?: string[];
  /**
   * Tipo de objeto para lo que cuelga del registro: adjuntos, comentarios y
   * documentos. Sin él no hay ficha, porque esas rutas lo llevan dentro.
   */
  objeto?: string;
  /**
   * Esta fila habla de un registro que vive en otro sitio.
   *
   * Un listado derivado —«documentos que vencen», «certificaciones por
   * caducar»— no tiene ficha propia, y sin esto sus filas no llevan a ninguna
   * parte: se ve el problema y no hay forma de ir a arreglarlo. Con esto, la
   * fila abre el registro del que habla, que es donde están sus acciones.
   */
  abre?: { modulo: string; objeto: string; campo: string };
  /**
   * Acciones que actúan sobre la COLECCIÓN entera, no sobre una fila.
   *
   * Las de fila salen solas del contrato —la superficie las declara colgando
   * del identificador— pero «cargar el almacén» o «recalcular» no cuelgan de
   * ningún registro: son hermanas del listado, no hijas. No hay forma de
   * deducirlas de la ruta sin acertar por casualidad, así que se declaran.
   *
   * Sin esto, `POST /almacen/cargar` existía en la API y no había ningún botón
   * en ninguna pantalla que lo llamara: la tabla de frescura decía «nunca
   * cargada» y no ofrecía cargarla.
   */
  acciones?: Array<{
    ruta: string;
    nombre: string;
    /** Frase corta bajo el botón. Para lo que no se adivina por el rótulo. */
    detalle?: string;
    permiso?: string;
  }>;
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
{
    ruta: "tenants",
    titulo: "Tenants y unidades",
    seccion: "0.1",
    capacidad: "CRM-07.04.03.01",
    grupo: "Plataforma",
  },
{
    ruta: "contrato",
    titulo: "Contrato de la API",
    seccion: "0.2",
    capacidad: "CRM-07.04.03.02",
    grupo: "Plataforma",
  },
{
    ruta: "procesos",
    titulo: "Procesos y orquestación",
    seccion: "0.3",
    capacidad: "CRM-07.04.03.03",
    grupo: "Plataforma",
  },
{
    ruta: "modelo",
    titulo: "Modelo de datos",
    seccion: "0.4",
    capacidad: "CRM-07.04.03.04",
    grupo: "Plataforma",
  },
{
    ruta: "acceso",
    titulo: "Identidad y acceso",
    seccion: "0.5",
    capacidad: "CRM-07.04.03.05",
    grupo: "Plataforma",
  },
{
    ruta: "operacion",
    titulo: "Operación",
    seccion: "0.6",
    capacidad: "CRM-07.04.03.06",
    grupo: "Plataforma",
  },
{
    ruta: "cuentas",
    titulo: "Cuentas y contactos",
    seccion: "1.1",
    capacidad: "CRM-07.04.03.07",
    grupo: "Clientes",
  },
{
    ruta: "proveedores",
    titulo: "Proveedores",
    seccion: "9.1",
    capacidad: "CRM-07.04.03.31",
    grupo: "Clientes",
  },
{
    ruta: "actividades",
    titulo: "Actividades",
    seccion: "1.2",
    capacidad: "CRM-07.04.03.08",
    grupo: "Clientes",
  },
{
    ruta: "oportunidades",
    // «Oportunidades» y no «Pipeline»: el tablero donde se arrastran de etapa
    // tiene su propia entrada en el menú, y dos sitios distintos con el mismo
    // nombre obligan a entrar en los dos para saber cuál es cuál.
    titulo: "Oportunidades",
    seccion: "3.1",
    capacidad: "CRM-07.04.03.13",
    grupo: "Ventas",
  },
{
    ruta: "leads",
    titulo: "Prospección",
    seccion: "3.3",
    capacidad: "CRM-07.04.03.15",
    grupo: "Ventas",
  },
{
    ruta: "prevision",
    titulo: "Previsión",
    seccion: "3.2",
    capacidad: "CRM-07.04.03.14",
    grupo: "Ventas",
  },
{
    ruta: "canal",
    titulo: "Canal indirecto",
    seccion: "3.4",
    capacidad: "CRM-07.04.03.16",
    grupo: "Ventas",
  },
{
    ruta: "campo",
    titulo: "Servicio de campo",
    seccion: "4.4",
    capacidad: "CRM-07.04.03.20",
    grupo: "Servicio",
  },
{
    ruta: "postventa",
    titulo: "Postventa",
    seccion: "4.5",
    capacidad: "CRM-07.04.03.21",
    grupo: "Servicio",
  },
{
    // El gobierno de la IA, que no tenía ninguna puerta: `/api/v1/ia` publica
    // 71 operaciones y la única pantalla de inteligencia que había enseña la
    // salud de UNA cuenta. Lo que falta no es eso: es quién puede llamar a
    // qué modelo, cuánto está costando, qué bloquearon las guardias y qué
    // agentes hay sueltos.
    //
    // Aquí van las COLECCIONES, que es lo que un módulo genérico enseña bien.
    // Lo que no está y no se finge: transcripciones, variantes, voz y
    // sugerencias de caso son extremos de análisis (`POST` que devuelven un
    // cálculo), no listados; su sitio es dentro de la actividad, del caso o de
    // la campaña, no una pestaña que pida un JSON.
    ruta: "ia",
    titulo: "Gobierno de la IA",
    seccion: "5.2",
    capacidad: "CRM-07.04.03.23",
    grupo: "Analítica",
  },
{
    ruta: "explotacion",
    titulo: "Explotación",
    seccion: "5.1",
    capacidad: "CRM-07.04.03.22",
    grupo: "Analítica",
  },
{
    ruta: "gobierno",
    titulo: "Gobierno y cumplimiento",
    seccion: "7.3",
    capacidad: "CRM-07.04.03.28",
    grupo: "Gobierno",
  },
{
    ruta: "segmentos",
    titulo: "Segmentación",
    seccion: "2.1",
    capacidad: "CRM-07.04.03.09",
    grupo: "Marketing",
  },
{
    ruta: "campanas",
    titulo: "Campañas",
    seccion: "2.2",
    capacidad: "CRM-07.04.03.10",
    grupo: "Marketing",
  },
{
    ruta: "casos",
    titulo: "Casos",
    seccion: "4.1",
    capacidad: "CRM-07.04.03.17",
    grupo: "Servicio",
  },
{
    ruta: "omnicanal",
    titulo: "Omnicanalidad",
    seccion: "4.2",
    capacidad: "CRM-07.04.03.18",
    grupo: "Servicio",
  },
{
    ruta: "conocimiento",
    titulo: "Conocimiento",
    seccion: "4.3",
    capacidad: "CRM-07.04.03.19",
    grupo: "Servicio",
  },
{
    ruta: "canales",
    titulo: "Canales de ejecución",
    seccion: "2.3",
    capacidad: "CRM-07.04.03.11",
    grupo: "Marketing",
  },
{
    ruta: "contenido",
    titulo: "Contenido y gobierno",
    seccion: "2.4",
    capacidad: "CRM-07.04.03.12",
    grupo: "Marketing",
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
  return recurso.listar
    .replace(/^\/api\/v1\//, "")
    .replace(/\?.*$/, "")
    .replace(/\//g, "-");
}

/**
 * Qué recurso del módulo abre esta ficha.
 *
 * Antes la ficha usaba siempre `recursos[0]`, así que en un módulo con varias
 * pestañas solo se podía abrir la primera: al pinchar una fila de la segunda se
 * pedía el registro contra la ruta de la primera y salía un 404. Por eso solo
 * tenían ficha los módulos que declaraban `objeto` en su primer recurso.
 */
// `recursoDe` vive en `recursos.ts`, con la tabla: necesita las pestañas y
// este fichero no las trae.

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
  recurso: {
    listar: string;
    permiso?: string;
    solo_plataforma?: boolean;
    por_servicio?: string[];
  },
  permitidas?: Set<string>,
): boolean {
  if (recurso.solo_plataforma && !sesion?.es_admin_plataforma) return false;
  if (!puede(sesion, recurso.permiso)) return false;
  // Una colección que vive en varios servicios se enseña si se puede ver en
  // ALGUNO: la plantilla `/api/v1/:servicio/…` no casa con ninguna ruta de
  // las que publica el servidor, así que sin esto la pestaña quedaba escondida
  // para todo el mundo — y es la que acaba de dejar de mentir.
  if (recurso.por_servicio?.length && recurso.listar.includes(":servicio")) {
    if (!permitidas || permitidas.size === 0) return true;
    return recurso.por_servicio.some((s) =>
      rutaPermitida(permitidas, recurso.listar.replace(":servicio", s)),
    );
  }
  // Lo que de verdad manda es lo que el servidor dice que exige esa ruta. El
  // campo `permiso` de aquí solo lo declaran unos pocos recursos, así que por
  // sí solo no filtra nada: sin la superficie, a un agente de soporte se le
  // seguían enseñando los veintitrés módulos.
  if (permitidas && permitidas.size > 0)
    return rutaPermitida(permitidas, recurso.listar);
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
/**
 * El grupo de menú al que pertenece un módulo, por su ruta.
 *
 * Lo necesita la navegación para saber a qué **ámbito** —Trabajar o
 * Administrar— pertenece `/m/<ruta>`. Se expone como función y no importando
 * `MODULOS` desde allí a propósito: ese fichero lo carga el marco entero y
 * esta tabla pesa.
 */
export function grupoDelModulo(ruta: string): string | undefined {
  return MODULOS.find((m) => m.ruta === ruta)?.grupo;
}

export function porGrupoVisible(
  sesion: Sesion | null,
  permitidas?: Set<string>,
): Map<string, Modulo[]> {
  const grupos = new Map<string, Modulo[]>();
  for (const modulo of MODULOS) {
    // Con el RESUMEN y no con la tabla entera: esto corre al pintar el menú,
    // antes de que nadie abra nada, y traerse las pestañas completas para
    // decidir qué módulos se enseñan costaba 42 kB comprimidos de apertura.
    const pestanas = VISIBILIDAD[modulo.ruta] ?? [];
    const visible = pestanas.some((p) =>
      recursoVisible(sesion, { listar: p.r, permiso: p.p, solo_plataforma: p.sp }, permitidas),
    );
    if (!visible) continue;
    grupos.set(modulo.grupo, [...(grupos.get(modulo.grupo) ?? []), modulo]);
  }
  return grupos;
}
