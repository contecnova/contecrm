/**
 * Identidad y seguridad: las preguntas que nadie podía contestar
 * (CRM-00.05.01.15, CRM-00.05.01.17, CRM-00.05.01.25, CRM-00.05.02.11,
 * CRM-07.03.02.06, CRM-00.05.01.14).
 *
 * Y, desde el 28-10-2026, **la primera de todas**: qué impide ahora mismo que
 * una empresa vea a otra (CRM-00.01.01.09, CRM-00.01.01.10, CRM-00.01.02.01,
 * CRM-00.01.02.02, CRM-00.01.02.03, CRM-00.01.02.04, CRM-00.01.02.05,
 * CRM-00.01.02.07). Las ocho estaban construidas y probadas, y a ninguna se
 * llegaba desde una pantalla: para saber si el aislamiento estaba de verdad
 * puesto en una instalación había que escribir un script y leer `pg_roles` a
 * mano. Se hizo, y lo que salió justifica la pantalla: 623 tablas con RLS,
 * FORCE y política —esa mitad, completa— y el servicio conectando con un rol
 * SUPERUSER, que se salta las políticas aunque estén en FORCE. De las tres
 * capas que el manual promete quedaba una.
 *
 * Por eso esta pregunta va **arriba del todo** y no al final: es la que decide
 * si todo lo demás significa algo. La respuesta se mide en cada carga; no hay
 * ningún visto bueno escrito a mano.
 *
 * El mismo panel mide ahora **con qué va cifrado el dato** (CRM-00.05.03.01,
 * CRM-00.05.03.02): si la conexión con la base lleva TLS —medido en la
 * conexión y no leído del ajuste, porque la cadena puede traer el suyo y
 * entonces el ajuste dice una cosa y la conexión hace otra— y si hay clave de
 * cifrado propia del tenant, que es lo que permite que revocarla deje
 * ilegible lo suyo y sólo lo suyo.
 *
 * Y el enmascaramiento por rol (CRM-00.05.03.03) es lo que ya enseñan las
 * excepciones de campo de más abajo: qué campo se ve en claro, cuál
 * enmascarado y cuál no se ve, y para quién.
 *
 * Y **si tu factor valdría para entrar sin contraseña**, junto a los factores
 * que tienes, que es donde se hace esa pregunta. La cuenta la hace el
 * servidor: él sabe cuál está atado al dominio. Antes había que pasarle
 * «¿resiste phishing?», que es justo lo que la pantalla no puede contestar
 * sin copiarse su tabla — y dos copias de esa tabla acabarían decidiendo
 * distinto si se puede quitar la contraseña.
 *
 * **No declara `CRM-00.05.01.23`**, aunque la enseñe: esa capacidad es entrar
 * sin contraseña y eso se hace en la pantalla de entrada, que ya la declara.
 * Aquí se contesta «¿podría?», que es la pregunta previa y no la capacidad.
 *
 * Y la tercera tanda, del mismo día: **quién ve qué, y por qué**
 * (CRM-00.05.02.02, CRM-00.05.02.03, CRM-00.05.02.05, CRM-00.05.02.08,
 * CRM-00.05.02.18, CRM-00.05.02.20, CRM-00.05.02.21). El explicador contestaba
 * «por qué puede» y no «qué decidiría cada capa»: ahora, con los mismos tres
 * datos y sin un segundo formulario, se ve el veredicto, **el rol y los
 * atributos por separado** —un «no puede» sin decir cuál de las dos lo impide
 * manda a cambiar el rol cuando lo que corta es una política— y el contexto
 * con el que se evaluó, que es lo único que permite reproducirlo.
 *
 * Y debajo, los campos que **no se comportan como dice su clasificación**. Se
 * podían declarar y no leer: la ruta que los crea justifica escribirlos con
 * que «una excepción que vive en la cabeza de quien la pidió es la que nadie
 * revisa al año siguiente», y sin lectura la excepción vivía igual de
 * escondida, sólo que en una tabla.
 *
 * Lo que esta pantalla **no** declara, aunque lo roce: `CRM-00.05.01.06` —MFA
 * obligatoria configurable por rol— porque aquí se ve si está puesta y no se
 * configura, y declarar lo que no se hace es justo lo que esta traza existe
 * para impedir.
 *
 * El módulo genérico «Identidad y acceso» ya lista lo que es una colección:
 * usuarios, roles, políticas, claves de API, sesiones, dispositivos y
 * proveedores. Lo que no puede listar es lo que **no es una tabla**, y resulta
 * que es justo lo que un administrador necesita saber:
 *
 *   · **quién no tiene segundo factor.** Un panel que diga «78 %» no sirve: el
 *     trabajo es hablar con los que faltan, así que lo que hace falta es la
 *     lista. Y separada por fuerza del factor, porque «tiene MFA» mete en el
 *     mismo saco una passkey y un SMS;
 *   · **qué certificado del proveedor de identidad caduca.** Un certificado de
 *     IdP que caduca no avisa: un sábado por la noche deja de validar toda
 *     aserción y el lunes no entra nadie de la empresa;
 *   · **quién tiene hoy permisos incompatibles.** Se calcula en vivo y no se
 *     guarda, porque una lista de conflictos vieja es peor que ninguna: se
 *     actúa sobre ella. Los que tienen excepción vigente salen igual, marcados;
 *   · **por qué esta persona puede (o no) hacer esto.** Sin el explicador, la
 *     respuesta se busca leyendo roles, políticas y reglas de compartición a la
 *     vez, y se contesta mal.
 *
 * Las cuatro son preguntas, no tablas, y por eso cada una se abre con su
 * respuesta —el número que importa— y debajo el detalle. Un listado de todo lo
 * que hay obliga a buscar el problema; esto lo pone delante.
 *
 * Nada de esto decide permisos: los pide, y el servidor contesta 403 a quien no
 * deba verlos. Lo que sí hace es no ofrecer lo que ya se sabe que va a dar 403.
 * Y desde el 29-10-2026, **cómo se entra en esta empresa**
 * (CRM-00.05.01.02, CRM-00.05.01.04, CRM-00.05.01.05, CRM-00.05.01.09,
 * CRM-00.05.01.11, CRM-00.05.01.12, CRM-00.05.01.13, CRM-00.05.01.16,
 * CRM-00.05.01.24). Nueve capacidades servidas y sin pantalla, y **cinco de
 * ellas ni siquiera salían por la API**: se escribían con un `PATCH` y el
 * listado devolvía el nombre, el tipo y los NOMBRES de las claves de
 * configuración, así que `forzar_sso` se veía como una palabra en una lista y
 * nunca su valor.
 *
 * Lo que eso dejaba sin revisar es lo que más importa: si se aceptan
 * aserciones que empiezan en el IdP —que sin petición nuestra se pueden
 * reenviar—, si el segundo factor se delega al proveedor, y si la contraseña
 * local está cortada y **quiénes** se lo saltan, que la capacidad exige que
 * sean nominales y queden escritas.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { ErrorApi, filas as filasDe, llamar, salvoCancelacion } from "@/lib/api";
import { puede, type Sesion } from "@/lib/sesion";

interface CapaDeAislamiento {
  clave: string;
  titulo: string;
  ok: boolean;
  cuantas: number | null;
  detalle: string;
  porque: string;
  medible_aqui?: boolean;
}

interface Garantias {
  esquema: string;
  rol: string;
  rol_se_salta_la_red: boolean;
  tablas_con_tenant: number;
  capas: CapaDeAislamiento[];
  todo_puesto: boolean;
  que_significa: string;
}

interface Excepcion {
  id: string;
  regla_codigo: string;
  usuario_id: string;
  motivo: string;
  caduca_at: string;
  vigente: boolean;
}

interface Descubrimiento {
  tiene_proveedor: boolean;
  nombre?: string;
  tipo?: string;
  contrasena_local_permitida?: boolean;
}

interface UsuarioMfa {
  usuario_id: string;
  email: string;
  nombre: string;
  roles: string[];
  ultimo_acceso_at: string | null;
  factor?: string;
  fuerza?: number;
}

interface Adopcion {
  total_usuarios: number;
  con_factor: number;
  sin_factor: number;
  adopcion_pct: number | null;
  medible: boolean;
  mfa_obligatoria: boolean;
  usuarios_sin_factor: UsuarioMfa[];
  canales_debiles_activos: string[];
  aviso: string;
}

interface Certificado {
  proveedor_id: string;
  proveedor: string;
  huella: string;
  caduca_at: string | null;
  dias_restantes: number | null;
  estado: "vigente" | "por_caducar" | "caducado" | "sin_fecha";
}

interface Violacion {
  usuario_id: string;
  regla: string;
  nombre: string;
  nivel: string;
  por_el_lado_a: string[];
  por_el_lado_b: string[];
  exento?: boolean;
}

/** `GET /factores/nivel`: con qué ha entrado esta sesión. */
interface Nivel {
  nivel: number;
  factores: { factor: string; at: string }[];
  factor_fuerte_at: string | null;
}

/** `GET /factores/plan-de-inscripcion`: qué falta para tenerlo en condiciones. */
interface Plan {
  activos: string[];
  pasos: { paso: string; porque: string }[];
  completo: boolean;
  porque: string;
}

interface Operacion {
  clave: string;
  descripcion: string;
}

/** `GET /factores/cambio-de-dispositivo`: qué camino hay al cambiar de móvil. */
interface Cambio {
  puede_solo: boolean;
  camino: string;
  aprobadores_necesarios: number;
  porque: string;
}

interface Passkey {
  id: string;
  nombre?: string;
}

export function Seguridad({ sesion }: { sesion: Sesion | null }) {
  const { t } = useTranslation();
  const [adopcion, setAdopcion] = useState<Adopcion | null>(null);
  const [certificados, setCertificados] = useState<Certificado[] | null>(null);
  const [sod, setSod] = useState<{
    violaciones: Violacion[];
    reglas: number;
  } | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    // Las tres a la vez: en serie, la pantalla tarda la suma y se lee como
    // lenta aunque cada una vaya rápida.
    Promise.all([
      llamar<Adopcion>("/api/v1/factores/adopcion", { signal: control.signal }),
      llamar<{ certificados: Certificado[] }>(
        "/api/v1/sso-gobierno/certificados",
        {
          signal: control.signal,
        },
      ),
      llamar<{ violaciones: Violacion[]; reglas: number }>(
        "/api/v1/segregacion/violaciones",
        {
          signal: control.signal,
        },
      ),
    ])
      .then(([a, c, s]) => {
        setAdopcion(a.datos);
        setCertificados(c.datos.certificados ?? []);
        setSod(s.datos);
      })
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);

  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!adopcion || !certificados || !sod) return <Cargando />;

  return (
    <div className="flex flex-col gap-6">
      <CabeceraPagina
        titulo={t("seguridad.titulo")}
        entradilla={t("seguridad.entradilla")}
        icono="shield_person"
      />

      {/* Arriba del todo porque es la que decide si lo demás significa algo:
          con un rol que se salta la RLS, contar tablas protegidas da verde
          sobre una red desarmada. */}
      <Aislamiento />
      <SegundoFactor datos={adopcion} />
      {/* Y lo de UNA persona, que es lo que no contesta el porcentaje: el
          administrador ve quién no tiene factor; quien entra necesita saber
          qué le falta a él, qué operaciones le van a pedir verificarse otra
          vez, y qué pasa el día que cambie de móvil — que es la llamada que
          más veces acaba en un desbloqueo manual, la puerta de atrás de toda
          la MFA. Las cuatro rutas estaban servidas y sin pantalla. */}
      {/* Cómo se entra en esta empresa, antes de lo que le falta a cada uno:
          si el SSO está forzado, con qué proveedor, si se aceptan aserciones
          que empiezan en el IdP, si el segundo factor se delega y quiénes se
          saltan la contraseña. Cinco de esos ajustes se escribían y no salían
          por la API. */}
      <ComoSeEntra />
      <MiSegundoFactor />
      <Certificados filas={certificados} />
      <Segregacion datos={sod} />
      {/* Y, justo debajo, por qué algunos de esos conflictos están
          permitidos: el informe de arriba los marca «con excepción» y hasta
          ahora no había forma de leer ni el motivo ni hasta cuándo. Una
          excepción que no se puede leer no es un control. */}
      <ExcepcionesAprobadas />
      {/* A qué proveedor le toca un correo. Es la primera pregunta cuando
          alguien «no puede entrar», y la que el propio usuario no sabe
          contestar: él sabe su correo, no si su empresa usa Entra ID o Ping. */}
      <AQuienLeToca />
      {/* Y los campos que no se comportan como dice su clasificación, justo
          al lado del explicador: son la respuesta a la mitad de los «pero yo
          esto lo veía». */}
      {puede(sesion, "role:read") ? <ExcepcionesDeCampo /> : null}
      {puede(sesion, "user:read") ? <Explicador /> : null}
    </div>
  );
}

/**
 * Qué impide, ahora mismo, que una empresa vea a otra.
 *
 * No es un panel de estado: es la respuesta a la pregunta que abre cualquier
 * auditoría. Cada capa dice **de dónde sale su número** y, si no está puesta,
 * qué falla exactamente. La que más importa no es la de arriba: es la del rol
 * de conexión, porque un SUPERUSER ignora las políticas aunque estén en FORCE
 * y entonces las demás líneas son verdes sobre nada.
 *
 * Lo que no se puede medir desde aquí —la suite que intenta entrar en lo
 * ajeno— sale dicho como lo que es: un gate que corre antes de empujar. Pintar
 * un visto bueno que nadie ha comprobado hoy sería peor que no pintar nada.
 */
function Aislamiento() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<Garantias | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  const cargar = useCallback(() => {
    const control = new AbortController();
    llamar<Garantias>("/api/v1/aislamiento/garantias", { signal: control.signal })
      .then((r) => setDatos(r.datos))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, []);
  useEffect(cargar, [cargar]);

  if (fallo) return <Fallo error={fallo} reintentar={cargar} />;
  if (!datos) return <Cargando />;

  return (
    <section className="card p-4">
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold">{t("seguridad.aislamiento")}</h2>
        <span
          role="status"
          className={
            datos.todo_puesto
              ? "text-sm text-success"
              : "text-sm font-semibold text-warning"
          }
          data-testid="aislamiento-veredicto"
        >
          {datos.que_significa}
        </span>
      </header>

      <ul className="divide-y divide-ink-dim/30">
        {datos.capas.map((capa) => (
          <li key={capa.clave} className="flex gap-3 py-2">
            <span
              aria-hidden="true"
              className={
                capa.ok ? "mt-1 text-success" : "mt-1 font-semibold text-warning"
              }
            >
              {capa.ok ? "✓" : "✗"}
            </span>
            <div className="min-w-0">
              <p className="font-medium">
                {capa.titulo}
                {/* El estado también en texto: un color no lo lee quien no
                    distingue el verde del rojo, y aquí el dato es el estado. */}
                <span className="sr-only">
                  {capa.ok ? t("seguridad.capaPuesta") : t("seguridad.capaNoPuesta")}
                </span>
                {capa.medible_aqui === false ? (
                  <span className="ml-2 text-xs text-ink-muted">
                    {t("seguridad.noSeMideAqui")}
                  </span>
                ) : null}
              </p>
              <p className="text-sm text-ink-muted">{capa.detalle}</p>
              <p className="text-xs text-ink-faint">{capa.porque}</p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

interface ProveedorIdp {
  id: string;
  nombre: string;
  tipo: string;
  activo: boolean;
  dominio_email: string | null;
  dominios: string[];
  jit_provisioning: boolean;
  permite_idp_initiated: boolean;
  acr_con_mfa: string[];
  forzar_sso: boolean;
  cuentas_de_rescate: string[];
}

interface Ajuste {
  valor: unknown;
  origen?: string;
  descripcion?: string;
}

/**
 * Cómo se entra en esta empresa.
 *
 * Nueve capacidades del bloque de autenticación estaban **servidas y sin
 * pantalla**, y cinco de ellas ni siquiera salían por la API: se escribían con
 * un `PATCH` y el listado devolvía el nombre, el tipo y los NOMBRES de las
 * claves de configuración. `forzar_sso` se veía como una palabra en una lista
 * y nunca su valor.
 *
 * Lo que eso dejaba sin poder revisar es justo lo que más importa:
 *
 * - **Si se aceptan aserciones que empiezan en el IdP** (CRM-00.05.01.11).
 *   Vienen apagadas de fábrica por un motivo: sin `InResponseTo` que atar a una
 *   petición nuestra, una aserción robada **se puede reenviar**. Encenderlo
 *   tiene que ser una decisión de alguien, y una decisión que no se ve no se
 *   revisa.
 * - **Si el segundo factor se delega al proveedor** (CRM-00.05.01.24): si hay
 *   valores de `acr`/`amr` aceptados, aquí ya no se pide. Está bien —pedirlo
 *   dos veces enseña a saltárselo— pero hay que saberlo.
 * - **Si entrar por contraseña está cortado y quiénes se lo saltan**
 *   (CRM-00.05.01.13). La capacidad exige que la excepción sea nominal y quede
 *   escrita; se enseñan **los correos**, porque «2 cuentas de rescate» no se
 *   puede revisar. Y el forzado va por dos sitios —el del tenant y el del
 *   proveedor— así que se enseñan los dos: mirar sólo uno da por abierta una
 *   puerta cerrada, o al revés.
 * - **Con qué protocolo habla cada proveedor y qué dominios atiende**
 *   (CRM-00.05.01.02, CRM-00.05.01.16), y **si da de alta solo a quien entra
 *   por primera vez** (CRM-00.05.01.04) — que es lo que hace que el alta sea
 *   cosa de sistemas y no del administrador del CRM.
 * - **Si el aprovisionamiento automático está encendido** (CRM-00.05.01.05):
 *   con SCIM apagado, una baja en el directorio no cierra nada aquí.
 * - **Qué condiciones de contexto se exigen** (CRM-00.05.01.09).
 * - **Y qué sesiones no se cerrarán en el proveedor al salir**
 *   (CRM-00.05.01.12): cerrar sólo aquí deja la del IdP viva, y volver a entrar
 *   no pide credenciales. Para quien lo hace, el botón de salir no ha hecho
 *   nada.
 */
function ComoSeEntra() {
  const { t } = useTranslation();
  const [proveedores, setProveedores] = useState<ProveedorIdp[] | null>(null);
  const [forzadoGlobal, setForzadoGlobal] = useState<Ajuste | null>(null);
  const [scim, setScim] = useState<{ activo: boolean; porque: string } | null>(
    null,
  );
  const [politicas, setPoliticas] = useState<number | null>(null);
  const [sinEnlace, setSinEnlace] = useState<number | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    const opciones = { signal: control.signal };
    llamar<unknown>("/api/v1/proveedores-identidad", opciones)
      .then((r) => setProveedores(filasDe<ProveedorIdp>(r.datos)))
      .catch(salvoCancelacion(setFallo));
    // Cada una con su fallo: que no se pueda leer el ajuste global no puede
    // dejar sin ver los proveedores.
    void llamar<Record<string, Ajuste>>("/api/v1/ajustes", opciones)
      .then((r) => setForzadoGlobal(r.datos?.sso_forzado ?? null))
      .catch(() => undefined);
    // **El 403 de SCIM es la respuesta, no un error.** «No está activo en esta
    // instalación» es exactamente lo que hay que enseñar: con SCIM apagado,
    // una baja en el directorio no cierra nada aquí.
    void llamar<unknown>("/api/v1/scim/v2/ServiceProviderConfig", opciones)
      .then(() => setScim({ activo: true, porque: "" }))
      .catch((e: unknown) =>
        setScim({
          activo: false,
          porque: e instanceof ErrorApi ? e.explicacion || e.titulo : "",
        }),
      );
    void llamar<unknown>("/api/v1/politicas-acceso", opciones)
      .then((r) => setPoliticas(filasDe<unknown>(r.datos).length))
      .catch(() => undefined);
    void llamar<unknown>("/api/v1/sesiones", opciones)
      .then((r) =>
        setSinEnlace(
          filasDe<{ enlazada_al_idp?: boolean }>(r.datos).filter(
            (s) => s.enlazada_al_idp === false,
          ).length,
        ),
      )
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  if (fallo) return <Fallo error={fallo} />;
  if (!proveedores) return <Cargando />;

  const forzadoDelTenant = forzadoGlobal?.valor === true;

  return (
    <section className="card mt-4 p-4">
      <h2 className="section-label mb-1">{t("seguridad.entrada.titulo")}</h2>
      <p className="mb-3 text-3xs text-ink-faint">
        {t("seguridad.entrada.ayuda")}
      </p>

      {/* El forzado del tenant, lo primero: manda sobre el de cada proveedor y
          mirar sólo el del proveedor da por abierta una puerta cerrada. */}
      <p className={forzadoDelTenant ? "text-2xs text-ink" : "text-2xs text-warning"}>
        {forzadoDelTenant
          ? t("seguridad.entrada.forzadoSi")
          : t("seguridad.entrada.forzadoNo")}
      </p>

      {proveedores.length === 0 ? (
        <Vacio
          titulo={t("seguridad.entrada.sinProveedor")}
          detalle={t("seguridad.entrada.sinProveedorPorque")}
          compacto
        />
      ) : (
        <ul className="mt-3 divide-y divide-ink-dim/30">
          {proveedores.map((p) => (
            <li key={p.id} className="py-2">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="text-sm text-ink">{p.nombre}</span>
                <span className="chip-dato">{p.tipo}</span>
                {!p.activo ? (
                  <span className="text-3xs text-ink-faint">
                    {t("seguridad.entrada.apagado")}
                  </span>
                ) : null}
                {(p.dominios.length ? p.dominios : [p.dominio_email ?? ""])
                  .filter(Boolean)
                  .map((d) => (
                    <span key={d} className="font-mono text-3xs text-ink-faint">
                      {d}
                    </span>
                  ))}
              </div>
              <div className="mt-1 flex flex-col gap-0.5 text-3xs">
                <span className="text-ink-muted">
                  {p.jit_provisioning
                    ? t("seguridad.entrada.jitSi")
                    : t("seguridad.entrada.jitNo")}
                </span>
                {/* En aviso cuando está ENCENDIDO, que es el caso que hay que
                    mirar: apagado es el estado seguro. */}
                <span
                  className={
                    p.permite_idp_initiated ? "text-warning" : "text-ink-muted"
                  }
                >
                  {p.permite_idp_initiated
                    ? t("seguridad.entrada.idpInitiadoSi")
                    : t("seguridad.entrada.idpInitiadoNo")}
                </span>
                {p.acr_con_mfa.length > 0 ? (
                  <span className="text-ink-muted">
                    {t("seguridad.entrada.mfaDelegada")}:{" "}
                    <span className="font-mono">{p.acr_con_mfa.join(" ")}</span>
                  </span>
                ) : (
                  <span className="text-ink-muted">
                    {t("seguridad.entrada.mfaAqui")}
                  </span>
                )}
                {p.forzar_sso ? (
                  <span className="text-ink-muted">
                    {t("seguridad.entrada.forzadoEnEste")}
                    {/* Los correos, no el recuento: una excepción que no se ve
                        deja de ser una excepción. */}
                    {p.cuentas_de_rescate.length > 0 ? (
                      <span className="text-warning">
                        {" · "}
                        {t("seguridad.entrada.rescate")}:{" "}
                        <span className="font-mono">
                          {p.cuentas_de_rescate.join(", ")}
                        </span>
                      </span>
                    ) : null}
                  </span>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex flex-col gap-1 text-3xs">
        {scim ? (
          <span className={scim.activo ? "text-ink-muted" : "text-warning"}>
            {scim.activo
              ? t("seguridad.entrada.scimSi")
              : `${t("seguridad.entrada.scimNo")} ${scim.porque}`}
          </span>
        ) : null}
        {politicas !== null ? (
          <span className="text-ink-muted">
            {t("seguridad.entrada.politicas", { cuantas: politicas })}
          </span>
        ) : null}
        {sinEnlace !== null && sinEnlace > 0 ? (
          <span className="text-warning">
            {t("seguridad.entrada.sinCierrePropagado", { cuantas: sinEnlace })}
          </span>
        ) : null}
      </div>
    </section>
  );
}

/**
 * Lo que le falta a QUIEN mira, no al conjunto.
 *
 * Un panel de adopción dice «78 %» y el trabajo que genera es hablar con los
 * que faltan. Esto contesta lo otro: con qué he entrado hoy, qué me falta para
 * tener el segundo factor en condiciones, qué operaciones me van a pedir
 * verificarme otra vez y qué camino hay si cambio de móvil.
 *
 * Lo último importa más de lo que parece: sin factor viejo ni respaldo, lo
 * único que demuestra quién es alguien es que otras personas respondan por
 * ella, y el desbloqueo manual es la puerta de atrás de toda la MFA. Decirlo
 * ANTES, en frío, es lo que evita descubrirlo en caliente.
 *
 * Esto es, y así consta desde el 29-10-2026, el **ciclo de vida del segundo
 * factor** (CRM-00.05.01.19) —inscripción guiada paso a paso con el porqué de
 * cada uno, cambio de dispositivo y desbloqueo asistido con doble aprobación—
 * y **qué operaciones piden reautenticarse** (CRM-00.05.01.18). Las dos
 * estaban aquí y el catálogo no lo sabía: se pedían al servidor, se pintaban
 * con sus palabras, y figuraban como capacidades sin pantalla. Declararlas no
 * cambia una línea de lo que se ve; cambia que el recuento diga la verdad.
 */
function MiSegundoFactor() {
  const { t } = useTranslation();
  const [nivel, setNivel] = useState<Nivel | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [sensibles, setSensibles] = useState<Operacion[] | null>(null);
  const [cambio, setCambio] = useState<Cambio | null>(null);
  const [passkeys, setPasskeys] = useState<Passkey[] | null>(null);
  const [sinContrasena, setSinContrasena] = useState<
    { factor: string; puede: boolean; porque: string }[]
  >([]);

  useEffect(() => {
    const control = new AbortController();
    const opciones = { signal: control.signal };
    // Cada una con su fallo: que no se pueda leer el plan no puede dejar sin
    // ver con qué se ha entrado.
    void llamar<Nivel>("/api/v1/factores/nivel", opciones)
      .then((r) => {
        setNivel(r.datos);
        // **Y si alguno de ellos valdría para entrar sin contraseña.** La
        // cuenta la hace el servidor, que es quien sabe qué factor está atado
        // al dominio; aquí sólo se le dicen los factores que esta persona
        // tiene. Antes había que pasarle «¿resiste phishing?», que es
        // justamente lo que la pantalla no puede saber sin copiarse su tabla.
        for (const f of r.datos.factores ?? []) {
          void llamar<{ puede: boolean; porque: string }>(
            `/api/v1/factores/vale-como-unico?factor=${encodeURIComponent(f.factor)}&tiene_respaldo=${
              (r.datos.factores ?? []).length > 1
            }`,
            opciones,
          )
            .then((v) =>
              setSinContrasena((previo) => [
                ...previo.filter((x) => x.factor !== f.factor),
                { factor: f.factor, ...v.datos },
              ]),
            )
            .catch(() => undefined);
        }
      })
      .catch(() => undefined);
    void llamar<Plan>("/api/v1/factores/plan-de-inscripcion", opciones)
      .then((r) => setPlan(r.datos))
      .catch(() => undefined);
    void llamar<{ operaciones: Operacion[] }>(
      "/api/v1/factores/operaciones-sensibles",
      opciones,
    )
      .then((r) => setSensibles(r.datos.operaciones ?? []))
      .catch(() => undefined);
    void llamar<Cambio>("/api/v1/factores/cambio-de-dispositivo", opciones)
      .then((r) => setCambio(r.datos))
      .catch(() => undefined);
    void llamar<Passkey[]>("/api/v1/auth/passkeys", opciones)
      .then((r) => setPasskeys(Array.isArray(r.datos) ? r.datos : []))
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  if (!nivel && !plan && !cambio) return null;

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">
        {t("seguridad.mio.titulo")}
      </h2>

      {plan ? (
        <p
          className={`text-2xs ${plan.completo ? "text-ink-muted" : "text-warning"}`}
        >
          {plan.porque}
        </p>
      ) : null}

      {/* **Si alguno de tus factores valdría para entrar sin contraseña**
          (CRM-00.05.01.23). Es la pregunta que se hace quien ya tiene passkey
          y se cansa de escribir la contraseña, y la respuesta no es «sí» a
          secas: hace falta que el factor esté atado al dominio —una web falsa
          no puede usarlo— y que haya una segunda vía, porque sin contraseña
          detrás, perder la llave deja a la persona fuera del todo.

          La cuenta la hace el servidor, que es quien sabe qué factor resiste
          phishing. Aquí sólo se le dicen los que esta persona tiene. */}
      {sinContrasena.length ? (
        <ul className="space-y-1" data-testid="sin-contrasena">
          {sinContrasena.map((f) => (
            <li key={f.factor} className="text-2xs">
              <span className={f.puede ? "text-success" : "text-ink-muted"}>
                {f.puede
                  ? t("seguridad.mio.valeSolo", { factor: f.factor })
                  : t("seguridad.mio.noValeSolo", { factor: f.factor })}
              </span>
              {/* El porqué siempre, también cuando la respuesta es que sí: sin
                  él, un «sí» se lee como permiso y un «no» como capricho. */}
              <span className="ml-1 text-ink-faint">{f.porque}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {/* Los pasos que faltan, con el porqué de cada uno: «inscribe un
          respaldo» sin decir que perder el móvil obliga a un desbloqueo
          manual se lee como una recomendación opcional. */}
      {plan?.pasos?.length ? (
        <ul className="space-y-1">
          {plan.pasos.map((paso) => (
            <li key={paso.paso} className="rounded-lg bg-paper-sunk px-3 py-2">
              <p className="text-2xs text-ink">
                {t(`seguridad.mio.${paso.paso}`, paso.paso)}
              </p>
              <p className="text-3xs text-ink-faint">{paso.porque}</p>
            </li>
          ))}
        </ul>
      ) : null}

      <p className="text-3xs text-ink-faint">
        {t("seguridad.mio.entradaDeHoy", {
          factores:
            (nivel?.factores ?? []).map((f) => f.factor).join(", ") || "—",
        })}
        {passkeys
          ? ` · ${t("seguridad.mio.passkeys", { cuantas: passkeys.length })}`
          : ""}
      </p>

      {/* Qué va a pedir verificarse otra vez. Saberlo antes evita la sorpresa
          en mitad de una operación que no se puede dejar a medias. */}
      {sensibles?.length ? (
        <p className="text-3xs text-ink-faint">
          {t("seguridad.mio.sensibles")}:{" "}
          {sensibles.map((o) => o.descripcion).join(" · ")}
        </p>
      ) : null}

      {cambio ? (
        <p className="text-3xs text-ink-faint">{cambio.porque}</p>
      ) : null}
    </section>
  );
}

/** Quién no tiene segundo factor. El trabajo es hablar con ellos. */
function SegundoFactor({ datos }: { datos: Adopcion }) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">
        {t("seguridad.mfa.titulo")}
      </h2>
      {/* El porcentaje va con el N al lado: un 78 % sobre nueve personas no es
          lo mismo que sobre novecientas, y sin el N se lee igual. */}
      <p className="text-2xs text-ink-muted">
        {datos.medible
          ? t("seguridad.mfa.resumen", {
              pct: datos.adopcion_pct,
              con: datos.con_factor,
              total: datos.total_usuarios,
            })
          : t("seguridad.mfa.sinUsuarios")}
      </p>
      {!datos.mfa_obligatoria ? (
        <p className="text-3xs text-warning">
          {t("seguridad.mfa.noObligatoria")}
        </p>
      ) : null}
      {datos.canales_debiles_activos.length > 0 ? (
        <p className="text-3xs text-warning">
          {t("seguridad.mfa.canalesDebiles", {
            canales: datos.canales_debiles_activos.join(", "),
          })}
        </p>
      ) : null}
      {datos.usuarios_sin_factor.length === 0 ? (
        <Vacio
          titulo={t("seguridad.mfa.todos")}
          detalle={t("seguridad.mfa.todosDetalle")}
        />
      ) : (
        <ul className="divide-y divide-ink-dim/30 overflow-hidden rounded-lg border border-ink-dim/40">
          {datos.usuarios_sin_factor.map((u) => (
            <li
              key={u.usuario_id}
              className="flex flex-wrap items-baseline gap-x-3 px-3 py-1.5"
            >
              <span className="min-w-0 flex-1 truncate text-2xs text-ink">
                {u.nombre}
              </span>
              <span className="truncate font-mono text-3xs text-ink-muted">
                {u.email}
              </span>
              <span className="text-3xs text-ink-faint">
                {u.roles.join(", ")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Qué certificado del IdP caduca, y cuándo. */
function Certificados({ filas }: { filas: Certificado[] }) {
  const { t } = useTranslation();
  // Primero los que ya caducaron, luego los que van a caducar: el orden es el
  // de la urgencia, no el del nombre del proveedor.
  const orden = {
    caducado: 0,
    por_caducar: 1,
    sin_fecha: 2,
    vigente: 3,
  } as const;
  const ordenadas = [...filas].sort(
    (a, b) => orden[a.estado] - orden[b.estado],
  );
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">
        {t("seguridad.certificados.titulo")}
      </h2>
      <p className="text-3xs text-ink-faint">
        {t("seguridad.certificados.porQue")}
      </p>
      {ordenadas.length === 0 ? (
        <Vacio
          titulo={t("seguridad.certificados.ninguno")}
          detalle={t("seguridad.certificados.ningunoDetalle")}
        />
      ) : (
        <ul className="divide-y divide-ink-dim/30 overflow-hidden rounded-lg border border-ink-dim/40">
          {ordenadas.map((c) => (
            <li
              key={`${c.proveedor_id}:${c.huella}`}
              className="flex flex-wrap items-baseline gap-x-3 px-3 py-1.5"
            >
              <span
                className={`badge ${
                  c.estado === "caducado"
                    ? "badge-danger"
                    : c.estado === "por_caducar"
                      ? "badge-warning"
                      : ""
                }`}
              >
                {t(`seguridad.certificados.estado.${c.estado}`)}
              </span>
              <span className="min-w-0 flex-1 truncate text-2xs text-ink">
                {c.proveedor}
              </span>
              <span className="truncate font-mono text-3xs text-ink-faint">
                {c.huella.slice(0, 16)}
              </span>
              <span className="font-mono text-3xs text-ink-muted">
                {c.dias_restantes === null
                  ? t("seguridad.certificados.sinFecha")
                  : t("seguridad.certificados.dias", {
                      dias: c.dias_restantes,
                    })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Quién tiene hoy permisos incompatibles. */
function Segregacion({
  datos,
}: {
  datos: { violaciones: Violacion[]; reglas: number };
}) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">
        {t("seguridad.sod.titulo")}
      </h2>
      <p className="text-3xs text-ink-faint">
        {t("seguridad.sod.porQue", { reglas: datos.reglas })}
      </p>
      {datos.violaciones.length === 0 ? (
        <Vacio
          titulo={t(
            datos.reglas === 0
              ? "seguridad.sod.sinReglas"
              : "seguridad.sod.ninguna",
          )}
          detalle={t(
            datos.reglas === 0
              ? "seguridad.sod.sinReglasDetalle"
              : "seguridad.sod.ningunaDetalle",
          )}
        />
      ) : (
        <ul className="divide-y divide-ink-dim/30 overflow-hidden rounded-lg border border-ink-dim/40">
          {datos.violaciones.map((v, i) => (
            <li key={`${v.usuario_id}:${v.regla}:${i}`} className="px-3 py-2">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="badge">{v.nivel}</span>
                <span className="min-w-0 flex-1 truncate text-2xs text-ink">
                  {v.nombre}
                </span>
                {/* La excepción no esconde el conflicto: lo marca. Esconderlo
                    haría que una excepción caducada pasara de «aprobado» a «no
                    existe» sin que nadie lo viera. */}
                {v.exento ? (
                  <span className="badge badge-warning">
                    {t("seguridad.sod.conExcepcion")}
                  </span>
                ) : null}
                <span className="font-mono text-3xs text-ink-faint">
                  {v.usuario_id.slice(0, 8)}
                </span>
              </div>
              <p className="mt-0.5 font-mono text-3xs text-ink-muted">
                {v.por_el_lado_a.join(", ")} ↔ {v.por_el_lado_b.join(", ")}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Por qué esta persona puede (o no) hacer esto. */
/**
 * Los campos que NO se comportan como dice su clasificación.
 *
 * La sensibilidad de un campo sale de su clasificación y eso cubre el caso
 * normal. Lo que se declara aparte es el que no: «el móvil del contacto lo ve
 * soporte en claro aunque sea un dato personal», «el margen lo tapamos también
 * para dirección».
 *
 * Se podían escribir y **no leer**. La propia ruta que las crea justifica
 * escribirlas con que «una excepción que vive en la cabeza de quien la pidió
 * es la que nadie revisa al año siguiente» — y sin lectura la excepción vivía
 * igual de escondida, sólo que en una tabla. Declarar que el margen lo tapa
 * también dirección y que nadie pueda comprobarlo después es lo que convierte
 * un control en papeleo.
 */
function ExcepcionesDeCampo() {
  const { t } = useTranslation();
  const [datos, setDatos] = useState<RespuestaCampos | null>(null);

  useEffect(() => {
    const control = new AbortController();
    void llamar<RespuestaCampos>("/api/v1/politicas-acceso/campos", {
      signal: control.signal,
    })
      .then((r) => setDatos(r.datos))
      .catch(() => undefined);
    return () => control.abort();
  }, []);

  if (!datos) return null;

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">
        {t("seguridad.campos.titulo")}
      </h2>
      <p className="text-3xs text-ink-faint">{datos.que_significa}</p>
      {datos.campos.length === 0 ? null : (
        <ul
          className="divide-y divide-ink-dim/30 overflow-hidden rounded-lg border border-ink-dim/40"
          data-testid="excepciones-de-campo"
        >
          {datos.campos.map((c) => (
            <li
              key={`${c.objeto}:${c.campo}:${c.rol}`}
              className="flex flex-wrap items-baseline gap-x-3 px-3 py-1.5 text-3xs"
            >
              <span className="font-mono text-ink">
                {c.objeto}.{c.campo}
              </span>
              <span
                className={
                  c.nivel === "oculto"
                    ? "text-warning"
                    : c.nivel === "enmascarado"
                      ? "text-ink-muted"
                      : "text-success"
                }
              >
                {c.nivel}
              </span>
              {/* El rol tal como está escrito, con `*` y todo: es lo que hay
                  que cambiar si se cambia, y traducirlo a «todos» esconde que
                  no hay ninguna excepción por rol debajo. */}
              <span className="text-ink-faint">
                {c.para_todos ? t("seguridad.campos.todosLosRoles") : c.rol}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** `GET /politicas-acceso/campos`. */
interface RespuestaCampos {
  campos: {
    objeto: string;
    campo: string;
    rol: string;
    nivel: string;
    para_todos: boolean;
  }[];
  cuantas: number;
  que_significa: string;
}

/** `POST /politicas-acceso/simular`: qué vería un usuario dado, con las dos
 *  capas por separado y el contexto con el que se evaluó. */
interface Simulacion {
  permitido: boolean;
  origen: string;
  rbac?: { concede: boolean; permiso?: string };
  abac?: { permitido: boolean; explicacion?: string };
  ambito?: {
    usuario?: { roles?: string[]; business_unit_id?: string | null };
    contexto?: { hora?: number; dia_semana?: number };
  };
}

function Explicador() {
  const { t } = useTranslation();
  const [usuario, setUsuario] = useState("");
  const [objeto, setObjeto] = useState("");
  const [accion, setAccion] = useState("read");
  const [salida, setSalida] = useState<unknown>(null);
  const [simulacion, setSimulacion] = useState<Simulacion | null>(null);
  const [fallo, setFallo] = useState<ErrorApi | null>(null);
  const [pidiendo, setPidiendo] = useState(false);

  async function preguntar() {
    setPidiendo(true);
    setFallo(null);
    try {
      // Las dos preguntas con los mismos tres datos, y por eso no hay un
      // segundo formulario: «¿por qué puede?» la contesta el explicador de
      // roles y «¿qué decidiría cada capa y con qué contexto?» la simulación
      // de políticas. Pedirlas por separado obligaría a teclear lo mismo dos
      // veces y a comparar dos respuestas a ojo, que es donde se concluye mal.
      const [r, s] = await Promise.all([
        llamar<unknown>("/api/v1/roles/explicar", {
          metodo: "POST",
          cuerpo: { usuario_id: usuario, objeto, accion, registro: {} },
        }),
        llamar<Simulacion>("/api/v1/politicas-acceso/simular", {
          metodo: "POST",
          cuerpo: { usuario_id: usuario, objeto, accion, registro: {} },
        }).catch(() => null),
      ]);
      setSalida(r.datos);
      setSimulacion(s ? s.datos : null);
    } catch (e: unknown) {
      if (e instanceof ErrorApi) setFallo(e);
    } finally {
      setPidiendo(false);
    }
  }

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">
        {t("seguridad.explicador.titulo")}
      </h2>
      <p className="text-3xs text-ink-faint">
        {t("seguridad.explicador.porQue")}
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-3xs text-ink-muted">
            {t("seguridad.explicador.usuario")}
          </span>
          <input
            value={usuario}
            onChange={(e) => setUsuario(e.target.value)}
            className="input-base font-mono"
            placeholder="uuid"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-3xs text-ink-muted">
            {t("seguridad.explicador.objeto")}
          </span>
          <input
            value={objeto}
            onChange={(e) => setObjeto(e.target.value)}
            className="input-base"
            placeholder="opportunity"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-3xs text-ink-muted">
            {t("seguridad.explicador.accion")}
          </span>
          <input
            value={accion}
            onChange={(e) => setAccion(e.target.value)}
            className="input-base"
          />
        </label>
        <button
          type="button"
          className="btn-primary"
          disabled={pidiendo || usuario.trim() === "" || objeto.trim() === ""}
          onClick={() => void preguntar()}
        >
          {t("seguridad.explicador.preguntar")}
        </button>
      </div>
      {fallo ? <Fallo error={fallo} /> : null}
      {/* La respuesta se anuncia: quien no ve la pantalla pulsa y no se entera
          de que ya está contestado. */}
      <div role="status" aria-live="polite">
        {/* **Las dos capas por separado, y el veredicto delante.** Un «no
            puede» sin decir cuál de las dos lo impide manda a cambiar el rol
            cuando lo que corta es una política de atributos, o al revés. Y el
            contexto —hora, día, unidad— se enseña porque una política que
            depende de él decide distinto a las nueve de la noche, y eso no se
            puede reproducir sin saber con qué contexto se evaluó. */}
        {simulacion ? (
          <div className="rounded-lg border border-ink-dim/40 p-3" data-testid="simulacion-acceso">
            <p
              className={
                simulacion.permitido
                  ? "text-sm font-medium text-success"
                  : "text-sm font-medium text-warning"
              }
            >
              {simulacion.permitido
                ? t("seguridad.simulador.permitido")
                : t("seguridad.simulador.denegado")}
              <span className="ml-2 text-3xs text-ink-faint">{simulacion.origen}</span>
            </p>
            <p className="mt-1 text-3xs text-ink-muted">
              {t("seguridad.simulador.rbac", {
                veredicto: simulacion.rbac?.concede
                  ? t("seguridad.simulador.concede")
                  : t("seguridad.simulador.niega"),
                permiso: simulacion.rbac?.permiso ?? "—",
              })}
            </p>
            <p className="text-3xs text-ink-muted">
              {t("seguridad.simulador.abac", {
                veredicto: simulacion.abac?.permitido
                  ? t("seguridad.simulador.concede")
                  : t("seguridad.simulador.niega"),
              })}
              {simulacion.abac?.explicacion ? ` — ${simulacion.abac.explicacion}` : ""}
            </p>
            {simulacion.ambito ? (
              <p className="mt-1 text-3xs text-ink-faint">
                {t("seguridad.simulador.contexto", {
                  roles: (simulacion.ambito.usuario?.roles ?? []).join(", ") || "—",
                  unidad: simulacion.ambito.usuario?.business_unit_id ?? "—",
                  hora: simulacion.ambito.contexto?.hora ?? "—",
                })}
              </p>
            ) : null}
          </div>
        ) : null}
        {salida ? (
          <pre className="overflow-x-auto rounded-lg border border-ink-dim/40 p-3 text-3xs text-ink">
            {JSON.stringify(salida, null, 2)}
          </pre>
        ) : null}
      </div>
    </section>
  );
}

/**
 * Los conflictos que alguien aprobó, con su motivo y su caducidad
 * (`CRM-07.03.02.06`).
 *
 * El informe de arriba marca «con excepción» los conflictos permitidos, y eso
 * está bien —esconderlos haría que una excepción caducada pasara de «aprobado»
 * a «no existe» sin que nadie lo viera—. Lo que faltaba es poder contestar la
 * pregunta siguiente, que es la que hace un auditor: **¿y éstos por qué están
 * permitidos?**
 *
 * El alta exige motivo escrito y caducidad. Si no se pueden leer, esos dos
 * requisitos son papeleo: la prueba se genera y se archiva donde nadie puede
 * recuperarla.
 *
 * Por defecto sólo las vigentes. Una lista con las de hace tres años obliga a
 * filtrar a mano justo cuando se está revisando.
 */
function ExcepcionesAprobadas() {
  const { t } = useTranslation();
  const [filas, setFilas] = useState<Excepcion[] | null>(null);
  const [caducadas, setCaducadas] = useState(false);
  const [fallo, setFallo] = useState<unknown>(null);

  useEffect(() => {
    const control = new AbortController();
    setFallo(null);
    llamar<Excepcion[]>(
      `/api/v1/segregacion/excepciones?incluir_caducadas=${caducadas}`,
      {
        signal: control.signal,
      },
    )
      .then((r) => setFilas(filas_(r.datos)))
      .catch(salvoCancelacion(setFallo));
    return () => control.abort();
  }, [caducadas]);

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">
        {t("seguridad.excepciones.titulo")}
      </h2>
      <p className="text-3xs text-ink-faint">
        {t("seguridad.excepciones.porQue")}
      </p>
      <label className="flex items-center gap-2 text-3xs text-ink-muted">
        <input
          type="checkbox"
          checked={caducadas}
          onChange={(e) => setCaducadas(e.target.checked)}
        />
        {t("seguridad.excepciones.verCaducadas")}
      </label>
      {fallo ? <Fallo error={fallo} /> : null}
      {filas === null ? null : filas.length === 0 ? (
        <Vacio
          titulo={t("seguridad.excepciones.ninguna")}
          detalle={t("seguridad.excepciones.ningunaDetalle")}
          compacto
        />
      ) : (
        <ul className="lista-acotada divide-y divide-ink-dim/30 overflow-hidden rounded-lg border border-ink-dim/40">
          {filas.map((e) => (
            <li key={e.id} className="px-3 py-2">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-mono text-2xs text-ink">
                  {e.regla_codigo}
                </span>
                <span className="font-mono text-3xs text-ink-faint">
                  {e.usuario_id.slice(0, 8)}
                </span>
                {/* Caducada se marca y no se esconde: una excepción vencida
                    sigue explicando por qué alguien tuvo ese permiso. */}
                <span
                  className={`badge ${e.vigente ? "badge-warning" : "badge-muted"}`}
                >
                  {e.vigente
                    ? t("seguridad.excepciones.hasta", {
                        fecha: e.caduca_at.slice(0, 10),
                      })
                    : t("seguridad.excepciones.caducada", {
                        fecha: e.caduca_at.slice(0, 10),
                      })}
                </span>
              </div>
              {/* El motivo, siempre: sin él la lista dice que hay excepciones
                  y no por qué, que es justo lo que hay que revisar. */}
              <p className="mt-0.5 text-3xs text-ink-muted">{e.motivo}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * A qué proveedor le toca este correo (`CRM-00.05.01.14`).
 *
 * «No puedo entrar» es la incidencia más común y la más cara de diagnosticar a
 * ciegas: puede ser que su dominio esté forzado a SSO, que no lo esté y se
 * espere contraseña, o que su subdominio herede de otro proveedor. El usuario
 * no puede contestarlo —él sabe su correo, no si su empresa usa Entra ID o
 * Ping— y quien atiende tampoco, si no puede mirarlo.
 *
 * El subdominio hereda del dominio padre y gana el más específico, así que
 * mirarlo «a ojo» en la lista de dominios se equivoca justo en los casos raros,
 * que son los que generan la incidencia.
 */
function AQuienLeToca() {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [quien, setQuien] = useState<Descubrimiento | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [mirando, setMirando] = useState(false);

  async function mirar() {
    if (!email.trim()) return;
    setMirando(true);
    setFallo(null);
    try {
      const r = await llamar<Descubrimiento>(
        `/api/v1/sso-gobierno/descubrir?email=${encodeURIComponent(email.trim())}`,
      );
      setQuien(r.datos);
    } catch (e: unknown) {
      setFallo(e);
    } finally {
      setMirando(false);
    }
  }

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold text-ink">
        {t("seguridad.aQuienLeToca.titulo")}
      </h2>
      <p className="text-3xs text-ink-faint">
        {t("seguridad.aQuienLeToca.porQue")}
      </p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void mirar();
        }}
      >
        <label className="flex min-w-0 flex-1 flex-col gap-1 text-3xs text-ink-muted">
          {t("seguridad.aQuienLeToca.correo")}
          <input
            type="email"
            className="input-base"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <button
          type="submit"
          className="btn-secondary"
          disabled={mirando || !email.trim()}
        >
          {mirando
            ? t("seguridad.aQuienLeToca.mirando")
            : t("seguridad.aQuienLeToca.mirar")}
        </button>
      </form>
      {fallo ? <Fallo error={fallo} /> : null}
      <div role="status" aria-live="polite">
        {quien ? (
          <p className="rounded-lg border border-ink-dim/40 p-3 text-2xs text-ink">
            {quien.tiene_proveedor
              ? t("seguridad.aQuienLeToca.entraPorSso", {
                  nombre: quien.nombre,
                  tipo: quien.tipo,
                })
              : t("seguridad.aQuienLeToca.entraPorContrasena")}
            {quien.tiene_proveedor &&
            quien.contrasena_local_permitida === false ? (
              <span className="mt-1 block text-3xs text-warning">
                {t("seguridad.aQuienLeToca.sinContrasenaLocal")}
              </span>
            ) : null}
          </p>
        ) : null}
      </div>
    </section>
  );
}

/** El servidor devuelve la lista tal cual; esto la deja en array pase lo que pase. */
function filas_(datos: unknown): Excepcion[] {
  return Array.isArray(datos) ? (datos as Excepcion[]) : [];
}
