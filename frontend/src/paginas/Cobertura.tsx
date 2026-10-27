/**
 * Qué del sistema enseña la interfaz, y qué no
 * (CRM-07.04.05.01, CRM-07.04.05.02).
 *
 * El informe normal es el de cobertura: cuántas operaciones publicadas tienen
 * pantalla. El que **nadie hace** es el de vuelta, y es el que importa aquí:
 * **qué sabe hacer el CRM que ninguna pantalla enseña**. Esa es la lista de
 * potencia escondida en la API — capacidades construidas, probadas y
 * documentadas que quien mira el producto concluye que no están.
 *
 * Se calcula en vivo cruzando la superficie con los módulos declarados. Un
 * informe guardado se queda viejo en cuanto alguien añade una ruta, y un
 * informe de cobertura viejo es peor que ninguno porque se decide sobre él.
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo } from "@/componentes/Estados";
import { MODULOS } from "@/lib/modulos";
import { recursosDe } from "@/lib/recursos";
import { todasLasEntradas } from "@/lib/navegacion";
import { cargarSuperficie, recursoDe, type Superficie } from "@/lib/superficie";
import { CabeceraPagina } from "@/componentes/Pagina";
import { salvoCancelacion } from "@/lib/api";

export function Cobertura() {
  const { t } = useTranslation();
  const [superficie, setSuperficie] = useState<Superficie | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    cargarSuperficie(control.signal).then(setSuperficie).catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  const informe = useMemo(() => (superficie ? calcular(superficie) : null), [superficie]);

  if (fallo) return <Fallo error={fallo} />;
  if (!informe) return <Cargando />;

  return (
    <>
      <CabeceraPagina
        titulo={t("cobertura.titulo")}
        entradilla={t("cobertura.intro")}
        icono="fact_check"
      />

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Dato titulo={t("cobertura.publicadas")} valor={informe.publicadas} />
        <Dato titulo={t("cobertura.conPantalla")} valor={informe.conPantalla} />
        <Dato titulo={t("cobertura.deMaquina")} valor={informe.deMaquina} />
        <Dato
          titulo={t("cobertura.sinPantalla")}
          valor={informe.operacionesSinPantalla}
          alerta={informe.operacionesSinPantalla > 0}
        />
      </div>
      <p className="mt-2 text-3xs text-ink-faint">
        {t("cobertura.enRecursos", { cuantos: informe.sinPantalla.length })}
      </p>

      <h2 className="mt-8 text-2xs font-medium uppercase tracking-wide text-ink-faint">
        {t("cobertura.escondido")}
      </h2>
      <p className="mt-1 text-2xs text-ink-faint">{t("cobertura.escondidoIntro")}</p>
      {informe.sinPantalla.length === 0 ? (
        <p className="mt-3 text-2xs text-success">{t("cobertura.todoEnsenado")}</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-1">
          {informe.sinPantalla.map((r) => (
            <li
              key={r.recurso}
              className="rounded-lg border border-ink-dim/30 bg-paper px-3 py-2 text-2xs"
            >
              <span className="font-mono text-ink">{r.recurso}</span>
              <span className="ml-2 text-ink-faint">
                {r.servicios.join(", ")} · {r.operaciones} {t("cobertura.operaciones")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function Dato({ titulo, valor, alerta }: { titulo: string; valor: number; alerta?: boolean }) {
  return (
    <div className="rounded-xl border border-ink-dim/60 bg-paper p-4">
      <p className="text-2xs text-ink-faint">{titulo}</p>
      <p className={`mt-1 text-lg ${alerta ? "text-warning" : "text-ink"}`}>{valor}</p>
    </div>
  );
}

export interface Informe {
  publicadas: number;
  conPantalla: number;
  /** Operaciones que no enseña ninguna pantalla. Antes se enseñaba el número
   *  de RECURSOS junto a dos cifras de operaciones, y no cuadraba con nada:
   *  «1404 publicadas · 814 con pantalla · 85 sin pantalla». */
  operacionesSinPantalla: number;
  /** Lo que es maquinaria y nunca va a tener pantalla, contado aparte. */
  deMaquina: number;
  sinPantalla: { recurso: string; servicios: string[]; operaciones: number }[];
}

/**
 * Lo que no lleva pantalla porque no es para una persona.
 *
 * Contarlo como carencia infla el número y, peor, esconde las carencias de
 * verdad debajo de sesenta y cinco comprobaciones de salud. Cada entrada va
 * con su motivo: sin motivo, esta lista se convierte en el sitio donde se
 * esconde lo que no apetece hacer.
 */
/**
 * Lo que se enseña **dentro de la ficha de cada registro**, no en un módulo.
 *
 * Los adjuntos, los comentarios y los documentos de una cuenta no tienen
 * pantalla propia ni deben tenerla: se ven donde se usan, colgando del
 * registro. El informe los contaba como carencia porque solo miraba módulos.
 */
const EN_LA_FICHA: Record<string, string> = {
  adjuntos: "Cuelgan de cada registro, en su ficha",
  comentarios: "Cuelgan de cada registro, en su ficha",
  documentos: "Cuelgan de cada registro, en su ficha",
};

const DE_MAQUINA: Record<string, string> = {
  estado: "Salud y arranque de cada servicio: lo consulta el orquestador",
  metrics: "Métricas para Prometheus",
  docs: "La documentación interactiva de cada servicio",
  "openapi.json": "El contrato en crudo; su pantalla es «Contrato de la API»",
  auth: "Entrar, refrescar y salir: su pantalla es la de acceso",
  scim: "Aprovisionamiento automático desde el proveedor de identidad",
  interno: "Llamadas firmadas entre servicios, nunca desde fuera",
  sso: "La vuelta del proveedor de identidad: la trae el navegador, no se pulsa",
  telefonia: "Las llama la centralita al entrar o transferir una llamada",
  "sincronizacion-campo": "El volcado del móvil cuando recupera cobertura",
  servicio: "Entrada de mensajes por webhook, desde el canal de fuera",
  contactos: "Alias en español del alta masiva; se lanza desde el listado",
  cuentas: "Alias en español del alta masiva; se lanza desde el listado",
  oportunidades: "Alias en español del alta masiva; se lanza desde el listado",
};

export function calcular(superficie: Superficie): Informe {
  // Los recursos que alguna pantalla enseña salen de las rutas declaradas en
  // los módulos, no de una lista aparte: una lista aparte se queda vieja en
  // cuanto alguien añade una pestaña.
  const enseñados = new Set<string>();
  for (const modulo of MODULOS) {
    for (const recurso of recursosDe(modulo.ruta)) enseñados.add(recursoDe(recurso.listar));
  }
  // Y las pantallas escritas a mano, que declaran lo que enseñan. Sin esto, el
  // informe contaba «sin pantalla» proveedores, cuadros de mando, inteligencia
  // o la suite —que tienen pantalla propia desde hace tiempo— y la lista de
  // carencias era en buena parte inventada.
  for (const entrada of todasLasEntradas()) {
    for (const recurso of entrada.recursos ?? []) enseñados.add(recurso);
  }
  for (const recurso of Object.keys(EN_LA_FICHA)) enseñados.add(recurso);
  // La consola de administración enseña TODO lo marcado como administración,
  // porque se construye de la propia superficie.
  for (const operacion of superficie.operaciones) {
    if (operacion.administracion) enseñados.add(recursoDe(operacion.ruta));
  }

  const porRecurso = new Map<string, { servicios: Set<string>; operaciones: number }>();
  for (const operacion of superficie.operaciones) {
    const recurso = recursoDe(operacion.ruta);
    if (!recurso) continue;
    const dato = porRecurso.get(recurso) ?? { servicios: new Set<string>(), operaciones: 0 };
    dato.servicios.add(operacion.servicio);
    dato.operaciones += 1;
    porRecurso.set(recurso, dato);
  }

  const deMaquina = [...porRecurso.entries()]
    .filter(([recurso]) => recurso in DE_MAQUINA)
    .reduce((n, [, d]) => n + d.operaciones, 0);

  const sinPantalla = [...porRecurso.entries()]
    .filter(([recurso]) => !enseñados.has(recurso) && !(recurso in DE_MAQUINA))
    .map(([recurso, dato]) => ({
      recurso,
      servicios: [...dato.servicios].sort(),
      operaciones: dato.operaciones,
    }))
    .sort((a, b) => b.operaciones - a.operaciones);

  const operacionesSinPantalla = sinPantalla.reduce((n, r) => n + r.operaciones, 0);
  return {
    publicadas: superficie.total,
    conPantalla: superficie.total - operacionesSinPantalla - deMaquina,
    operacionesSinPantalla,
    deMaquina,
    sinPantalla,
  };
}
