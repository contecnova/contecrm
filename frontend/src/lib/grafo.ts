/**
 * El proceso como grafo y como código, intercambiables (CRM-00.03.05.02).
 *
 * La definición **es** el JSON: pasos, enlaces y nada más. El gráfico no es otra
 * cosa que se mantenga en paralelo —eso son dos verdades que divergen al tercer
 * cambio— sino una lectura de ese mismo JSON.
 *
 * Lo único que el lienzo añade es **dónde está cada caja**, y va dentro de la
 * propia definición bajo `grafico.posiciones`. Es información de presentación y
 * el motor la ignora; guardarla aparte obligaría a sincronizar dos documentos
 * y, el día que se desincronizaran, el diagrama enseñaría un proceso que no es
 * el que se ejecuta.
 *
 * **Una definición escrita a mano, sin posiciones, tiene que abrirse bien.** Si
 * no, «intercambiables» sería falso: se podría ir del gráfico al código pero no
 * al revés. Por eso, cuando faltan posiciones, se calculan por capas.
 */

export interface Paso {
  tipo?: string;
  siguiente?: string;
  si_no?: string;
  al_fallar?: string;
  rutas?: Record<string, string>;
  condiciones?: { entonces?: string }[];
  ramas?: string[];
  [clave: string]: unknown;
}

export interface Definicion {
  inicio?: string;
  pasos?: Record<string, Paso>;
  grafico?: { posiciones?: Record<string, { x: number; y: number }> };
  [clave: string]: unknown;
}

export interface Nodo {
  nombre: string;
  tipo: string;
  x: number;
  y: number;
  esInicio: boolean;
}

export interface Arista {
  desde: string;
  hasta: string;
  /** Qué enlace es: `siguiente`, `si_no`, el nombre de una ruta… */
  etiqueta: string;
}

/** Separación entre cajas, en píxeles. Fijo y no configurable: no es una preferencia. */
export const ANCHO = 190;
export const ALTO = 90;

/**
 * Todas las salidas de un paso, con su etiqueta.
 *
 * Es la MISMA lista de enlaces que usa el validador del servidor para saber qué
 * es alcanzable. Si aquí faltara una, el diagrama enseñaría un proceso con menos
 * caminos de los que tiene — y el que falta sería justo el que nadie revisa.
 */
export function salidas(paso: Paso): { hasta: string; etiqueta: string }[] {
  const fuera: { hasta: string; etiqueta: string }[] = [];
  for (const clave of ["siguiente", "si_no", "al_fallar"] as const) {
    const destino = paso[clave];
    if (typeof destino === "string" && destino) fuera.push({ hasta: destino, etiqueta: clave });
  }
  for (const [etiqueta, destino] of Object.entries(paso.rutas ?? {})) {
    if (destino) fuera.push({ hasta: destino, etiqueta });
  }
  for (const condicion of paso.condiciones ?? []) {
    if (condicion.entonces) fuera.push({ hasta: condicion.entonces, etiqueta: "si" });
  }
  for (const rama of paso.ramas ?? []) fuera.push({ hasta: rama, etiqueta: "rama" });
  return fuera;
}

export function aristas(definicion: Definicion): Arista[] {
  const fuera: Arista[] = [];
  for (const [nombre, paso] of Object.entries(definicion.pasos ?? {})) {
    for (const salida of salidas(paso)) {
      fuera.push({ desde: nombre, hasta: salida.hasta, etiqueta: salida.etiqueta });
    }
  }
  return fuera;
}

/**
 * Coloca los pasos: los guardados donde estaban, el resto por capas.
 *
 * Se respeta la posición guardada de cada paso por separado, no del diagrama
 * entero: así añadir un paso nuevo a un proceso ya colocado no reordena todo lo
 * demás, que es lo que hace que nadie vuelva a tocar el diagrama.
 */
export function colocar(definicion: Definicion): Nodo[] {
  const pasos = definicion.pasos ?? {};
  const guardadas = definicion.grafico?.posiciones ?? {};
  const capas = porCapas(definicion);

  const enCapa = new Map<number, number>();
  return Object.entries(pasos).map(([nombre, paso]) => {
    const guardada = guardadas[nombre];
    if (guardada) {
      return {
        nombre,
        tipo: String(paso.tipo ?? "?"),
        x: guardada.x,
        y: guardada.y,
        esInicio: nombre === definicion.inicio,
      };
    }
    const capa = capas.get(nombre) ?? 0;
    const indice = enCapa.get(capa) ?? 0;
    enCapa.set(capa, indice + 1);
    return {
      nombre,
      tipo: String(paso.tipo ?? "?"),
      x: 40 + capa * ANCHO,
      y: 40 + indice * ALTO,
      esInicio: nombre === definicion.inicio,
    };
  });
}

/**
 * Profundidad de cada paso desde el inicio.
 *
 * Un recorrido en anchura, y por capas y no por orden de aparición porque un
 * diagrama en el que las flechas van hacia atrás no se lee. Los pasos
 * inalcanzables —que el servidor marca como problema— se colocan igual, en la
 * primera capa: esconderlos haría imposible arreglarlos desde el propio editor.
 */
export function porCapas(definicion: Definicion): Map<string, number> {
  const pasos = definicion.pasos ?? {};
  const capas = new Map<string, number>();
  const cola: [string, number][] = definicion.inicio ? [[definicion.inicio, 0]] : [];

  while (cola.length > 0) {
    const [nombre, capa] = cola.shift()!;
    if (capas.has(nombre) || !pasos[nombre]) continue;
    capas.set(nombre, capa);
    for (const salida of salidas(pasos[nombre]!)) cola.push([salida.hasta, capa + 1]);
  }
  return capas;
}

/** Guarda las posiciones DENTRO de la definición, sin tocar nada más. */
export function conPosiciones(definicion: Definicion, nodos: Nodo[]): Definicion {
  return {
    ...definicion,
    grafico: {
      ...definicion.grafico,
      posiciones: Object.fromEntries(nodos.map((n) => [n.nombre, { x: n.x, y: n.y }])),
    },
  };
}
