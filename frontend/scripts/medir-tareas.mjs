/**
 * Mide las tareas más frecuentes de un CRM como las haría una persona.
 *
 *     ./setup.sh arrancar
 *     node frontend/scripts/medir-tareas.mjs            # las doce
 *     node frontend/scripts/medir-tareas.mjs T02 T05    # sólo esas
 *     MEDIR_JSON=/ruta/salida.json node frontend/scripts/medir-tareas.mjs
 *
 * **Por qué existe.** El rediseño se juzgaba a ojo: «se ve mejor», «está más
 * a mano». Eso no se puede comparar entre un bloque y el siguiente, ni contra
 * Salesforce. Esto sí: cada tarea empieza en la portada, recién entrado, y se
 * hace **por la interfaz** —botones y enlaces por su nombre accesible, como los
 * encuentra una persona o un lector de pantalla—, nunca llamando a la API ni
 * saltando a una dirección escrita a mano.
 *
 * **Qué cuenta, y cómo:**
 *
 * - **Clics**: cada pulsación sobre un botón, enlace, pestaña u opción. Entrar
 *   en un campo de texto para escribir **no** es un clic: va en «campos».
 * - **Teclas**: las que hacen algo (Intro para elegir, ⌘K). Escribir no cuenta.
 * - **Campos**: cuántos campos distintos hay que rellenar o elegir.
 * - **Pantallas**: cuántas direcciones distintas se recorren, la portada
 *   incluida. Cambiar de pestaña con `?r=` también cuenta: es otra lista.
 * - **Tiempo**: de la portada a la comprobación final, en segundos de reloj.
 *   Es el de la máquina, sin pensar: mide cuánto hace esperar el sistema.
 * - **Persona (est.)**: el tiempo de una persona según el modelo KLM (Card,
 *   Moran y Newell): 1,2 s por clic (apuntar y pulsar), 0,28 s por carácter o
 *   tecla y 1,35 s de pensar por cada campo y cada pantalla nueva. Es una
 *   **estimación**, y por eso va aparte del tiempo medido.
 * - **Errores**: respuestas 400, 404, 422 y 5xx de la API mientras dura la
 *   tarea, y excepciones de la página. 401, 403 y 409 no: son respuestas de
 *   negocio correctas (ver `barrido-pantallas.mjs`, que razona lo mismo).
 *
 * **Terminada quiere decir comprobada.** Cada tarea acaba leyendo por la API
 * lo que tenía que haber cambiado —el lead convertido, el caso cerrado, la
 * actividad colgando del registro—. Una tarea cuyos clics salen pero cuyo
 * efecto no está dice «NO» en la columna de terminada: medir los clics de algo
 * que no funciona no es medir.
 *
 * **Bloqueo** es lo que no se puede hacer desde la interfaz sin saber algo
 * que una persona no sabe —un identificador interno— o sin salir del producto.
 *
 * **Lo que crea, lo borra.** Corre contra la pila con datos de verdad, así que
 * todo lo que da de alta lleva «UX medida» en el nombre y se borra al final,
 * haya ido bien o mal. Las excepciones son rastro de auditoría que el producto
 * no deja borrar: la aprobación de la T12, que se crea sobre una oportunidad
 * de la propia medida, que sí se borra, y queda decidida; y el envío de la
 * respuesta de la T09, que queda en marketing con su estado —va a una
 * dirección de `example.com`, que no es de nadie—.
 */
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const APP = process.env.CRM_URL ?? "http://localhost:15173";
const EMPRESA = process.env.CRM_EMPRESA ?? "plataforma";
const USUARIO = process.env.CRM_USUARIO ?? "plataforma@contecrm.dev";
const CLAVE = process.env.CRM_CLAVE ?? "Plataforma2026.crm";
const SOLO = new Set(process.argv.slice(2).map((s) => s.toUpperCase()));
const MARCA = `UX medida ${Date.now().toString(36).slice(-5)}`;
// A quién se manda la respuesta de la T09: `example.com` está reservado y no
// es de nadie (RFC 2606), así que no le llega a ninguna persona.
const PARA_RESPUESTA = "uxmedida@example.com";
// Lo que una comprobación sabe de por qué no se cumplió, para decirlo.
let motivoDeLaComprobacion = "";

// KLM: operadores clásicos, en segundos.
const KLM = { clic: 1.2, caracter: 0.28, pensar: 1.35 };
const CUENTAN = (e) => e === 400 || e === 404 || e === 422 || e >= 500;

class Bloqueo extends Error {}

const navegador = await chromium.launch();
const ctx = await navegador.newContext({
  viewport: { width: 1440, height: 900 },
  locale: "es-ES",
});
const p = await ctx.newPage();

// ── Lo que pasa por la red, para saber cuándo ha terminado una acción ──────
let enVuelo = 0;
let ultimoMovimiento = Date.now();
let erroresTarea = [];
p.on("request", (r) => {
  if (r.url().includes("/api/")) {
    enVuelo++;
    ultimoMovimiento = Date.now();
  }
});
const fin = (r) => {
  if (r.url().includes("/api/")) {
    enVuelo = Math.max(0, enVuelo - 1);
    ultimoMovimiento = Date.now();
  }
};
p.on("requestfinished", fin);
p.on("requestfailed", fin);
p.on("response", (r) => {
  const u = r.url();
  if (process.env.MEDIR_DEPURAR && u.includes("/api/") && r.status() === 409)
    console.log("   409", r.request().method(), u.replace(APP, ""));
  if (u.includes("/api/") && CUENTAN(r.status()))
    erroresTarea.push(
      `${r.status()} ${r.request().method()} ${u.replace(APP, "").split("?")[0]}`,
    );
});
if (process.env.MEDIR_DEPURAR)
  p.on("response", (r) => {
    const u = r.url();
    if (
      r.request().method() !== "GET" &&
      u.includes("/api/v1/") &&
      !u.includes("/auth/")
    )
      console.log("   >", r.request().method(), u.replace(APP, ""), r.status());
  });
p.on("pageerror", (e) => erroresTarea.push(`JS ${String(e).slice(0, 120)}`));

/** Espera a que la pantalla deje de pedir cosas: 400 ms sin nada en vuelo. */
async function asentar(maximo = 12000) {
  const hasta = Date.now() + maximo;
  await p.waitForTimeout(120);
  while (Date.now() < hasta) {
    if (enVuelo === 0 && Date.now() - ultimoMovimiento > 400) return;
    await p.waitForTimeout(80);
  }
}

// ── Entrar ────────────────────────────────────────────────────────────────
await p.goto(APP, { waitUntil: "networkidle" });
await p.fill('input[autocomplete="organization"]', EMPRESA);
await p.fill('input[type="email"]', USUARIO);
await p.fill('input[autocomplete="current-password"]', CLAVE);
await p.click('button[type="submit"]:visible');
await p
  .waitForURL((u) => !/\/entrar/.test(u.pathname), { timeout: 30000 })
  .catch(() => {});
if (/entrar/.test(new URL(p.url()).pathname)) {
  console.error(
    `NO SE HA ENTRADO en ${APP} con ${USUARIO}: sin sesión no se mide nada.`,
  );
  process.exit(1);
}
await asentar();

/** La API con la sesión de la página: para preparar, comprobar y limpiar. */
async function api(metodo, ruta, cuerpo) {
  return p.evaluate(
    async ([m, r, c]) => {
      const tok =
        sessionStorage.getItem("crm.token") ||
        localStorage.getItem("crm.token") ||
        "";
      const res = await fetch(r, {
        method: m,
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(tok ? { Authorization: "Bearer " + tok } : {}),
        },
        body: c ? JSON.stringify(c) : undefined,
      });
      let d = null;
      try {
        d = await res.json();
      } catch {
        /* sin cuerpo */
      }
      return { s: res.status, d };
    },
    [metodo, ruta, cuerpo],
  );
}
const items = (d) => (Array.isArray(d) ? d : (d?.items ?? []));

// Lo que se crea, para borrarlo al final en orden inverso.
const creados = [];
const apuntar = (ruta) => ruta && creados.push(ruta);

// ── La persona ────────────────────────────────────────────────────────────
function persona() {
  const m = {
    clics: 0,
    teclas: 0,
    campos: new Set(),
    caracteres: 0,
    pantallas: new Set(),
  };
  const mirarPantalla = () => {
    const u = new URL(p.url());
    const r = u.searchParams.get("r");
    m.pantallas.add(u.pathname + (r ? `?r=${r}` : ""));
  };
  mirarPantalla();
  /** Un control visible por su papel y su nombre, como lo busca una persona. */
  const control = (nombre, { exacto = false, papel } = {}) => {
    const papeles = papel
      ? [papel]
      : ["button", "link", "tab", "menuitem", "option", "combobox"];
    let loc = null;
    for (const r of papeles) {
      const l = p.getByRole(r, { name: nombre, exact: exacto });
      loc = loc ? loc.or(l) : l;
    }
    return loc.locator("visible=true").first();
  };
  return {
    m,
    control,
    async clic(nombre, opciones) {
      const loc =
        typeof nombre === "string" || nombre instanceof RegExp
          ? control(nombre, opciones)
          : nombre;
      await loc.waitFor({ state: "visible", timeout: 10000 });
      await loc.click();
      m.clics++;
      await asentar();
      mirarPantalla();
    },
    async escribir(etiqueta, texto, { campo } = {}) {
      const loc =
        typeof etiqueta === "string" || etiqueta instanceof RegExp
          ? p
              .getByLabel(etiqueta, { exact: typeof etiqueta === "string" })
              .locator("visible=true")
              .first()
          : etiqueta;
      await loc.waitFor({ state: "visible", timeout: 10000 });
      await loc.fill(String(texto));
      m.campos.add(campo ?? String(etiqueta));
      m.caracteres += String(texto).length;
      await asentar(4000);
    },
    async elegir(etiqueta, valor) {
      const loc = p
        .getByLabel(etiqueta, { exact: true })
        .locator("visible=true")
        .first();
      await loc
        .selectOption({ label: valor })
        .catch(() => loc.selectOption(valor));
      m.campos.add(String(etiqueta));
      m.clics += 2; // abrir el desplegable y elegir
      await asentar(4000);
    },
    /** Un campo que apunta a otro registro: abrir, buscar y elegir. */
    async referencia(etiqueta, buscar, opcion) {
      await this.clic(
        p
          .getByRole("combobox", { name: etiqueta, exact: true })
          .locator("visible=true")
          .first(),
      );
      m.clics--; // lo cuenta el propio clic; abajo se suma como uno solo
      m.clics++;
      const buscador = p
        .getByRole("textbox", { name: /Buscar en la lista|Buscar/ })
        .locator("visible=true")
        .last();
      await buscador.fill(buscar);
      m.caracteres += buscar.length;
      await p.waitForTimeout(250);
      await p
        .getByRole("option", { name: opcion ?? buscar })
        .first()
        .click();
      m.clics++;
      m.campos.add(String(etiqueta));
      await asentar(4000);
    },
    /** El buscador de arriba: abrirlo, escribir y elegir con Intro. */
    /** `titulo`: cómo sale el registro en la lista, si no es lo que se teclea
     *  (un caso se busca por su código y se lista por su asunto). */
    async buscarYAbrir(texto, titulo = texto) {
      await this.clic("Buscar pantallas y módulos");
      const campo = p
        .getByPlaceholder(/Buscar una pantalla/)
        .locator("visible=true")
        .last();
      await this.escribir(campo, texto, { campo: "buscador" });
      // El resultado que se llama EXACTAMENTE así: una oportunidad «Suministro
      // — Componentes Delta» contiene el nombre del cliente y no es el cliente.
      await asentar();
      const rotulos = (
        await p
          .locator("#paleta-resultados button span.flex-1")
          .allTextContents()
      ).map((x) => x.trim());
      const cual = rotulos.findIndex((x) => x === titulo);
      if (cual < 0) throw new Error(`el buscador no encuentra «${texto}»`);
      // Intro si sale el primero; si delante hay otros, hay que ir a por él.
      if (cual === 0) await this.tecla("Enter");
      else await this.clic(p.locator("#paleta-resultados button").nth(cual));
    },
    async tecla(t) {
      await p.keyboard.press(t);
      m.teclas++;
      await asentar();
      mirarPantalla();
    },
    async esperar(texto, maximo = 10000) {
      await p
        .getByText(texto)
        .locator("visible=true")
        .first()
        .waitFor({ timeout: maximo });
    },
  };
}

// ── Preparación común ─────────────────────────────────────────────────────
// Un cliente de verdad para buscar y otro de la medida para colgarle cosas.
const cuentas = items((await api("GET", "/api/v1/accounts?limite=200")).d);
// Uno cuyo nombre no se repita: hay homónimos («… Pamplona, S.L.U.» dos veces)
// y con ellos la tarea mediría a cuál de los dos se llega, no cuánto cuesta.
const veces = (n) => cuentas.filter((c) => c.nombre === n).length;
const conocida = cuentas.find(
  (c) =>
    /^[A-ZÁÉÍÓÚ][^\d]{6,}$/.test(c.nombre ?? "") &&
    !/UX medida/.test(c.nombre) &&
    veces(c.nombre) === 1,
);
const cuentaMedida = (
  await api("POST", "/api/v1/accounts", { nombre: `${MARCA} Cliente` })
).d;
apuntar(`/api/v1/accounts/${cuentaMedida.id}`);

async function oportunidadDeMedida(sufijo) {
  const r = await api("POST", "/api/v1/opportunities", {
    nombre: `${MARCA} ${sufijo}`,
    cuenta_id: cuentaMedida.id,
    importe: 12000,
  });
  apuntar(`/api/v1/opportunities/${r.d.id}`);
  return r.d;
}
async function casoDeMedida(sufijo) {
  const asunto = `${MARCA} ${sufijo}`;
  const r = await api("POST", "/api/v1/casos", {
    asunto,
    cuenta_id: cuentaMedida.id,
  });
  apuntar(`/api/v1/casos/${r.d.id}`);
  // El alta no devuelve el asunto: se guarda el que se mandó, que es como
  // sale el caso en el buscador.
  return { ...r.d, asunto };
}
async function actividadesDe(objeto, id) {
  return items(
    (
      await api(
        "GET",
        `/api/v1/activities?objeto=${objeto}&objeto_id=${id}&limite=50`,
      )
    ).d,
  );
}

/**
 * Abrir un caso por su código, como lo busca un agente.
 *
 * Primero el buscador de arriba. Si no lo encuentra —medido el 10-11-2026: los
 * casos no estaban en el índice—, a la pestaña de casos y su buscador de lista.
 */
async function abrirCaso(h, caso) {
  try {
    await h.buscarYAbrir(caso.codigo, caso.asunto);
    return;
  } catch {
    await p.keyboard.press("Escape");
  }
  await h.clic("Casos", { papel: "link", exacto: true });
  await h.escribir("Buscar en esta lista", caso.codigo);
  await h.clic(p.getByRole("link", { name: new RegExp(caso.codigo) }).first());
}

// ── Las tareas ────────────────────────────────────────────────────────────
//
// Cada una: quién la hace, qué es, y el camino por la interfaz. `comprobar`
// lee por la API si el efecto está.
const TAREAS = [
  {
    id: "T01",
    rol: "Comercial",
    nombre: "Encontrar un cliente por nombre y abrir su ficha",
    async hacer(h) {
      await h.buscarYAbrir(conocida.nombre);
      return {};
    },
    async comprobar() {
      return p.url().includes(conocida.id);
    },
  },
  {
    id: "T02",
    rol: "Comercial",
    nombre:
      "Dar de alta un lead y convertirlo en cliente, contacto y oportunidad",
    async hacer(h) {
      const empresa = `${MARCA} Industrias`;
      await h.clic("Crear");
      await h.clic("Lead");
      await h.escribir("Nombre", "Laura");
      await h.escribir("Empresa", empresa);
      if (!(await p.getByLabel("Apellidos", { exact: true }).isVisible()))
        await h.clic(/Más campos/);
      // Apellido con la marca: el alta busca duplicados por nombre, y un
      // «Laura Medina» que se haya quedado de otra medida haría que ésta
      // midiera el aviso de duplicado y no el alta.
      await h.escribir("Apellidos", `Medina ${MARCA.slice(-5)}`);
      // Sin correo ni teléfono, a propósito: con cualquiera de los dos, el
      // contacto que nace al convertir se queda con señales de identidad y ya
      // no se puede borrar ni archivar (medido el 10-11-2026), y esta medida
      // corre contra datos de verdad y tiene que limpiar lo que crea.
      await h.clic("Guardar", { exacto: true });
      const lead = items((await api("GET", "/api/v1/leads?limite=20")).d).find(
        (l) => l.empresa === empresa,
      );
      if (lead) apuntar(`/api/v1/leads/${lead.id}`);
      // Si la pantalla no lleva a la ficha, hay que buscarlo en la lista.
      if (!/\/lead\//.test(p.url())) {
        await h.escribir("Buscar en esta lista", "Laura");
        await h.clic(p.getByRole("link", { name: "Laura" }).first());
      }
      // Convertir: el botón a la vista o el menú «Más».
      if (
        await h
          .control(/^Convertir/)
          .isVisible()
          .catch(() => false)
      ) {
        await h.clic(/^Convertir/);
      } else {
        await h.clic("Qué se puede hacer con esto");
        await h.clic(/Convertir el lead/);
      }
      // El formulario de antes pedía una cuenta YA EXISTENTE: el cliente nuevo
      // no estaba, y no había cómo crearlo desde aquí.
      if (
        await p
          .getByRole("combobox", { name: "Cuenta", exact: true })
          .isVisible()
          .catch(() => false)
      ) {
        throw new Bloqueo(
          "convertir pide una cuenta que ya exista: el cliente nuevo hay que darlo de alta antes, en otra pantalla, y el contacto aparte",
        );
      }
      await h.clic(
        p
          .getByRole("button", { name: /^Convertir/ })
          .locator("visible=true")
          .last(),
      );
      return { lead };
    },
    async comprobar({ lead }) {
      if (!lead) return false;
      const l = (await api("GET", `/api/v1/leads/${lead.id}`)).d;
      if (l?.cuenta_id) apuntar(`/api/v1/accounts/${l.cuenta_id}`);
      if (l?.contacto_id) apuntar(`/api/v1/contacts/${l.contacto_id}`);
      if (l?.oportunidad_id)
        apuntar(`/api/v1/opportunities/${l.oportunidad_id}`);
      return Boolean(l?.cuenta_id && l?.contacto_id && l?.oportunidad_id);
    },
  },
  {
    id: "T03",
    rol: "Comercial",
    nombre: "Crear una oportunidad para un cliente (importe y fecha de cierre)",
    async hacer(h) {
      await h.buscarYAbrir(`${MARCA} Cliente`);
      await h.clic("Nueva oportunidad");
      await h.escribir("Nombre", `${MARCA} Renovación`);
      if (
        !(await p
          .getByLabel("Importe", { exact: true })
          .isVisible()
          .catch(() => false))
      )
        await h.clic(/Más campos/);
      const cuenta = p.getByRole("combobox", { name: "Cuenta", exact: true });
      if (!(await cuenta.textContent()).includes(MARCA))
        await h.referencia("Cuenta", MARCA, `${MARCA} Cliente`);
      await h.escribir("Importe", "25000");
      await h.escribir("Fecha cierre", "2026-12-15");
      await h.clic("Guardar", { exacto: true });
      return {};
    },
    async comprobar() {
      const ops = items(
        (
          await api(
            "GET",
            `/api/v1/opportunities?cuenta_id=${cuentaMedida.id}&limite=50`,
          )
        ).d,
      );
      const op = ops.find((o) => o.nombre === `${MARCA} Renovación`);
      if (op) apuntar(`/api/v1/opportunities/${op.id}`);
      return Boolean(op && Number(op.importe) === 25000 && op.fecha_cierre);
    },
  },
  {
    id: "T04",
    rol: "Comercial",
    nombre: "Mover una oportunidad a la etapa siguiente",
    async preparar() {
      return { op: await oportunidadDeMedida("Ampliación") };
    },
    async hacer(h, { op }) {
      await h.buscarYAbrir(`${MARCA} Ampliación`);
      await h.clic("Análisis técnico", { exacto: true });
      return { op };
    },
    async comprobar({ op }) {
      const o = (await api("GET", `/api/v1/opportunities/${op.id}`)).d;
      return o?.etapa && o.etapa !== op.etapa;
    },
  },
  {
    id: "T05",
    rol: "Comercial",
    nombre: "Hacer un presupuesto de la oportunidad y enviarlo",
    async preparar() {
      return { op: await oportunidadDeMedida("Suministro") };
    },
    async hacer(h, { op }) {
      await h.buscarYAbrir(`${MARCA} Suministro`);
      if (
        await h
          .control(/Nueva oferta|Nuevo presupuesto/)
          .isVisible()
          .catch(() => false)
      ) {
        await h.clic(/Nueva oferta|Nuevo presupuesto/);
      } else {
        // Sin botón en la oportunidad: a la pestaña de ofertas del módulo.
        await h.clic("Oportunidades", { papel: "link", exacto: true });
        await h.clic("Qué se está mirando");
        await h.clic("Ofertas", { exacto: true });
        await h.clic("Nuevo", { exacto: true });
      }
      await h.clic("Añadir línea");
      await h.escribir("Descripción, línea 1", "Suministro anual");
      await h.escribir("Cantidad, línea 1", "2");
      await h.escribir("Precio unitario, línea 1", "1500");
      // Con el coste: sin él no hay margen, la política lo manda a aprobación
      // y lo que se mide ya no es enviar, es el circuito de aprobación.
      await h.escribir("Coste unitario, línea 1", "900");
      const oportunidad = p.getByRole("combobox", {
        name: "Oportunidad",
        exact: true,
      });
      if (!(await oportunidad.isVisible().catch(() => false)))
        await h.clic(/Más campos/);
      if (!((await oportunidad.textContent()) ?? "").includes(MARCA)) {
        await h.referencia("Oportunidad", "Suministro", `${MARCA} Suministro`);
        await h.referencia("Cuenta", MARCA, `${MARCA} Cliente`);
      }
      await h.clic("Guardar", { exacto: true });
      const pre = items(
        (
          await api(
            "GET",
            `/api/v1/presupuestos?oportunidad_id=${op.id}&limite=5`,
          )
        ).d,
      )[0];
      if (pre) apuntar(`/api/v1/presupuestos/${pre.id}`);
      if (!/\/presupuesto\//.test(p.url())) {
        if (!pre) throw new Bloqueo("el presupuesto no se ha creado");
        // La fila se reconoce por su número, pero el enlace es la primera
        // columna, sea la que sea.
        await h.clic(
          p
            .getByRole("row")
            .filter({ hasText: pre.numero })
            .getByRole("link")
            .first(),
        );
      }
      if (
        await h
          .control(/^Enviar|Mandar el presupuesto/)
          .isVisible()
          .catch(() => false)
      ) {
        await h.clic(/^Enviar|Mandar el presupuesto/);
        const confirmar = p
          .getByRole("button", { name: /Mandar el presupuesto|^Enviar/ })
          .locator("visible=true")
          .last();
        if (await confirmar.isVisible().catch(() => false))
          await h.clic(confirmar);
      } else {
        // Sin acción de enviar: queda el desplegable de estado, que lo marca
        // como enviado sin pasar por el control de descuentos.
        await h.clic(p.getByRole("button", { name: /Borrador/ }).first());
        await h.clic("Enviado", { exacto: true });
        const x = (await api("GET", `/api/v1/presupuestos/${pre.id}`)).d;
        if (x?.estado === "borrador") {
          throw new Bloqueo(
            "la ficha del presupuesto no tiene «Enviar»; el desplegable de estado ofrece «Enviado» y el servidor lo rechaza",
          );
        }
      }
      return { pre };
    },
    async comprobar({ pre }) {
      if (!pre) return false;
      const x = (await api("GET", `/api/v1/presupuestos/${pre.id}`)).d;
      return x?.estado === "enviado" || x?.estado === "en_aprobacion";
    },
  },
  {
    id: "T06",
    rol: "Comercial",
    nombre: "Registrar una llamada en un cliente",
    async hacer(h) {
      await h.buscarYAbrir(`${MARCA} Cliente`);
      await h.clic(/Llamada$/);
      await h.escribir("Qué ha pasado", "Llamada de seguimiento");
      await h.clic("Apuntar", { exacto: true });
      return {};
    },
    async comprobar() {
      const a = await actividadesDe("cuenta", cuentaMedida.id);
      a.forEach((x) => apuntar(`/api/v1/activities/${x.id}`));
      return a.some(
        (x) => x.tipo === "llamada" && x.asunto === "Llamada de seguimiento",
      );
    },
  },
  {
    id: "T07",
    rol: "Comercial",
    nombre: "Registrar una reunión en una oportunidad",
    async preparar() {
      return { op: await oportunidadDeMedida("Reunión") };
    },
    async hacer(h, { op }) {
      await h.buscarYAbrir(`${MARCA} Reunión`);
      const boton = h.control(/^Reunión$/, { papel: "button" });
      if (!(await boton.isVisible().catch(() => false))) {
        throw new Bloqueo(
          "la ficha de la oportunidad no deja anotar nada; el alta suelta de actividades pide el identificador interno de la oportunidad",
        );
      }
      await h.clic(boton);
      await h.escribir("Qué ha pasado", "Reunión de arranque");
      await h.clic("Apuntar", { exacto: true });
      return { op };
    },
    async comprobar({ op }) {
      const a = await actividadesDe("oportunidad", op.id);
      a.forEach((x) => apuntar(`/api/v1/activities/${x.id}`));
      return a.some((x) => x.tipo === "reunion");
    },
  },
  {
    id: "T08",
    rol: "Soporte",
    nombre: "Abrir un caso para un cliente, con prioridad",
    async hacer(h) {
      await h.buscarYAbrir(`${MARCA} Cliente`);
      if (
        await h
          .control("Nuevo caso")
          .isVisible()
          .catch(() => false)
      ) {
        await h.clic("Nuevo caso");
      } else {
        await h.clic("Crear");
        await h.clic("Caso de soporte");
      }
      await h.escribir("Asunto", `${MARCA} No arranca la línea 2`);
      if (
        !(await p
          .getByLabel("Prioridad", { exact: true })
          .isVisible()
          .catch(() => false))
      )
        await h.clic(/Más campos/);
      const cuenta = p.getByRole("combobox", { name: "Cuenta", exact: true });
      if (!((await cuenta.textContent()) ?? "").includes(MARCA))
        await h.referencia("Cuenta", MARCA, `${MARCA} Cliente`);
      // La prioridad es una lista de la empresa (vocabulario) desde el
      // 10-11-2026; antes era una caja de texto donde se tecleaba «alta».
      const prioridad = p
        .getByLabel("Prioridad", { exact: true })
        .locator("visible=true")
        .first();
      if ((await prioridad.evaluate((e) => e.tagName)) === "SELECT")
        await h.elegir("Prioridad", "Alta");
      else await h.escribir("Prioridad", "alta");
      await h.clic("Guardar", { exacto: true });
      return {};
    },
    async comprobar() {
      const c = items(
        (
          await api(
            "GET",
            `/api/v1/casos?cuenta_id=${cuentaMedida.id}&limite=50`,
          )
        ).d,
      ).find((x) => x.asunto === `${MARCA} No arranca la línea 2`);
      if (c) apuntar(`/api/v1/casos/${c.id}`);
      return Boolean(c && c.prioridad === "alta");
    },
  },
  {
    id: "T09",
    rol: "Soporte",
    nombre: "Responder un caso (anotar la respuesta al cliente)",
    async preparar() {
      return { caso: await casoDeMedida("Ruido en el motor") };
    },
    async hacer(h, { caso }) {
      await abrirCaso(h, caso);
      // Responder de verdad: el correo sale por el canal de la casa (desde el
      // 10-11-2026). Antes sólo se podía APUNTAR que se había contestado.
      const responder = h.control(/^Responder$/, { papel: "button" });
      if (await responder.isVisible().catch(() => false)) {
        await h.clic(responder);
        // El caso de la medida no tiene contacto: se escribe a quién. Una
        // dirección de `example.com`, que no es de nadie (RFC 2606).
        await h.escribir("Para", PARA_RESPUESTA);
        await h.escribir("Mensaje", "Cambiamos el rodamiento el jueves.");
        await h.clic("Enviar respuesta", { exacto: true });
        return { caso, mandada: true };
      }
      const boton = h.control(/^Correo$/, { papel: "button" });
      if (!(await boton.isVisible().catch(() => false))) {
        throw new Bloqueo(
          "la ficha del caso no tiene dónde escribir ni anotar la respuesta",
        );
      }
      await h.clic(boton);
      await h.escribir("Qué ha pasado", "Re: ruido en el motor");
      await h.escribir("Detalle", "Cambiamos el rodamiento el jueves.");
      await h.clic("Apuntar", { exacto: true });
      return { caso };
    },
    async comprobar({ caso, mandada }) {
      const a = await actividadesDe("caso", caso.id);
      a.forEach((x) => apuntar(`/api/v1/activities/${x.id}`));
      if (!a.some((x) => x.tipo === "email")) return false;
      if (!mandada) return true;
      // Mandada quiere decir que SALIÓ: el envío consta y está enviado.
      const envios =
        (
          await api(
            "GET",
            `/api/v1/envios-programados?origen=respuesta&origen_id=${caso.id}`,
          )
        ).d?.envios ?? [];
      const ultimo = envios.at(-1) ?? envios[0];
      if (ultimo?.estado !== "enviado") {
        motivoDeLaComprobacion = `la respuesta consta y no ha salido: ${ultimo?.motivo ?? "sin envío"}`;
        return false;
      }
      return true;
    },
  },
  {
    id: "T10",
    rol: "Soporte",
    nombre: "Cerrar un caso con su motivo",
    async preparar() {
      return { caso: await casoDeMedida("Etiqueta mal impresa") };
    },
    async hacer(h, { caso }) {
      await abrirCaso(h, caso);
      if (
        await h
          .control(/^Cerrar el caso/, { papel: "button" })
          .isVisible()
          .catch(() => false)
      ) {
        await h.clic(/^Cerrar el caso/, { papel: "button" });
      } else {
        await h.clic("Qué se puede hacer con esto");
        await h.clic(/Cerrar el caso con un motivo/);
      }
      // Las irreversibles piden confirmación antes del formulario.
      const sigue = h.control("Lo entiendo, sigue", { papel: "button" });
      if (await sigue.isVisible().catch(() => false)) await h.clic(sigue);
      const motivo = p
        .getByLabel(/Motivo/)
        .locator("visible=true")
        .first();
      if ((await motivo.evaluate((e) => e.tagName)) === "SELECT") {
        const opciones = await motivo.locator("option").allTextContents();
        await h.elegir(
          (await motivo.getAttribute("aria-label")) ?? "Motivo",
          opciones.find((o) => o.trim() && !/Elegir|—/.test(o)),
        );
      } else {
        await h.escribir(motivo, "resuelto", { campo: "motivo" });
      }
      await h.clic(
        p
          .getByRole("button", { name: /^Cerrar el caso/ })
          .locator("visible=true")
          .last(),
      );
      return { caso };
    },
    async comprobar({ caso }) {
      const c = (await api("GET", `/api/v1/casos/${caso.id}`)).d;
      return c?.estado === "cerrado";
    },
  },
  {
    id: "T11",
    rol: "Responsable",
    nombre: "Ver la previsión del trimestre en curso",
    async hacer(h) {
      const hoy = new Date().toISOString().slice(0, 10);
      const periodos = items(
        (await api("GET", "/api/v1/forecast/periodos?limite=50")).d,
      );
      const actual = periodos.find((x) => x.desde <= hoy && hoy <= x.hasta);
      if (!actual)
        throw new Bloqueo(
          "no hay un periodo de previsión abierto que contenga hoy",
        );
      const enPortada = p
        .getByRole("link", {
          name: new RegExp(`${actual.nombre}|${actual.clave}`),
        })
        .locator("visible=true")
        .first();
      if (await enPortada.isVisible().catch(() => false)) {
        await h.clic(enPortada);
      } else {
        await h.clic("Previsiones", { papel: "link", exacto: true });
        const fila = p
          .getByRole("row")
          .filter({ hasText: actual.clave })
          .getByRole("link")
          .first();
        if (!(await fila.isVisible().catch(() => false))) {
          // La pestaña de entrada no es la de los periodos: se cambia.
          await h.clic(
            p
              .locator("main button[aria-haspopup]")
              .filter({ hasText: /PREVISIONES/i })
              .first(),
          );
          await h.clic("Periodos", { exacto: true });
        }
        await h.clic(fila);
      }
      return { actual };
    },
    async comprobar({ actual }) {
      return p.url().includes(`/periodo/${actual.clave}`);
    },
  },
  {
    id: "T12",
    rol: "Responsable",
    nombre: "Aprobar algo pendiente",
    async preparar() {
      const op = await oportunidadDeMedida("Descuento");
      const yo = (await api("GET", "/api/v1/auth/me")).d;
      const r = await api("POST", "/api/v1/aprobaciones", {
        politica: "descuento_comercial",
        objeto: "oportunidad",
        objeto_id: op.id,
        titulo: `${MARCA} Descuento del 12 %`,
        etapas: [
          {
            nombre: "Dirección",
            origen: "usuario",
            usuarios: [yo.usuario?.id ?? yo.id],
            quorum: "cualquiera",
            permitir_autoaprobacion: true,
          },
        ],
        contexto: { descuento_pct: 12, importe: "12000" },
      });
      if (r.s >= 300)
        throw new Error(
          `no se ha podido preparar la aprobación: ${r.s} ${JSON.stringify(r.d).slice(0, 200)}`,
        );
      return { sol: r.d };
    },
    async hacer(h, { sol }) {
      const titulo = `${MARCA} Descuento del 12 %`;
      const enPortada = p.getByText(titulo).locator("visible=true").first();
      if (!(await enPortada.isVisible().catch(() => false))) {
        // Fuera de la portada: Configuración › Procesos › «Me toca decidir».
        await h.clic("Configuración", { papel: "link" });
        await h.clic("Procesos y orquestación", { papel: "link" });
        await h.clic(
          p
            .locator("main button[aria-haspopup]")
            .filter({ hasText: /PROCESOS/i })
            .first(),
        );
        await h.clic("Me toca decidir", { exacto: true });
        await h.clic(p.getByRole("link", { name: titulo }).first());
        await h.clic("Qué se puede hacer con esto");
        await h.clic(/Decidir sobre una aprobación/);
        await h.elegir("Decisión", "Aprobar");
        await h.clic(
          p
            .getByRole("button", { name: /Decidir sobre una aprobación/ })
            .locator("visible=true")
            .last(),
        );
      } else {
        const fila = p
          .locator("li, article, tr")
          .filter({ hasText: titulo })
          .first();
        await h.clic(fila.getByRole("button", { name: /^Aprobar/ }));
      }
      return { sol };
    },
    async comprobar({ sol }) {
      const id = sol.solicitud_id ?? sol.id;
      const x = (await api("GET", `/api/v1/aprobaciones/${id}`)).d;
      return x?.estado === "aprobada";
    },
  },
];

// ── Correr ────────────────────────────────────────────────────────────────
const resultados = [];
// Cada uno empieza en SU aplicación, la que tendría elegida: el producto la
// recuerda, y una tarea de soporte no puede heredar la de ventas de la anterior.
const APLICACION = {
  Comercial: "ventas",
  Responsable: "ventas",
  Soporte: "servicio",
};
for (const tarea of TAREAS) {
  if (SOLO.size && !SOLO.has(tarea.id)) continue;
  await p.goto(APP + "/", { waitUntil: "domcontentloaded" });
  await asentar();
  let datos = {};
  try {
    datos = tarea.preparar ? await tarea.preparar() : {};
  } catch (e) {
    resultados.push({
      id: tarea.id,
      rol: tarea.rol,
      tarea: tarea.nombre,
      estado: "NO",
      motivo: `preparación: ${String(e.message).slice(0, 160)}`,
      clics: 0,
      teclas: 0,
      campos: 0,
      pantallas: 0,
      segundos: 0,
      persona_s: 0,
      errores: [],
    });
    console.log(
      `${tarea.id} NO      — preparación: ${String(e.message).slice(0, 160)}`,
    );
    continue;
  }
  await p.evaluate(
    (a) => localStorage.setItem("contecrm.aplicacion", a),
    APLICACION[tarea.rol],
  );
  await p.goto(APP + "/", { waitUntil: "domcontentloaded" });
  await asentar();
  erroresTarea = [];
  const h = persona();
  const t0 = Date.now();
  let estado = "hecha";
  let motivo = "";
  let salida = datos;
  try {
    salida = { ...datos, ...(await tarea.hacer(h, datos)) };
    await asentar();
    motivoDeLaComprobacion = "";
    if (!(await tarea.comprobar(salida))) {
      estado = "NO";
      motivo =
        motivoDeLaComprobacion || "los clics salen pero el efecto no está";
      await p
        .screenshot({
          path: `${process.env.MEDIR_CAPTURAS ?? "/tmp"}/medir-${tarea.id}.png`,
        })
        .catch(() => {});
    }
  } catch (e) {
    if (e instanceof Bloqueo) {
      estado = "bloqueo";
      motivo = e.message;
    } else {
      estado = "NO";
      motivo = String(e.message ?? e)
        .split("\n")[0]
        .slice(0, 200);
    }
    if (tarea.comprobar) await tarea.comprobar(salida).catch(() => false);
    await p
      .screenshot({
        path: `${process.env.MEDIR_CAPTURAS ?? "/tmp"}/medir-${tarea.id}.png`,
      })
      .catch(() => {});
  }
  const segundos = (Date.now() - t0) / 1000;
  const m = h.m;
  const persona_s =
    m.clics * KLM.clic +
    (m.caracteres + m.teclas) * KLM.caracter +
    (m.campos.size + m.pantallas.size) * KLM.pensar;
  resultados.push({
    id: tarea.id,
    rol: tarea.rol,
    tarea: tarea.nombre,
    estado,
    motivo,
    clics: m.clics,
    teclas: m.teclas,
    campos: m.campos.size,
    pantallas: m.pantallas.size,
    segundos: Math.round(segundos * 10) / 10,
    persona_s: Math.round(persona_s),
    errores: [...new Set(erroresTarea)],
  });
  const r = resultados.at(-1);
  console.log(
    `${r.id} ${r.estado.padEnd(7)} clics ${String(r.clics).padStart(2)} · teclas ${r.teclas} · campos ${r.campos} · pantallas ${r.pantallas} · ${r.segundos} s · persona ≈${r.persona_s} s · errores ${r.errores.length}${r.motivo ? ` — ${r.motivo}` : ""}`,
  );
  for (const e of r.errores) console.log(`      ${e}`);
}

// ── Limpiar ───────────────────────────────────────────────────────────────
let borrados = 0;
const fallidos = [];
for (const ruta of [...new Set(creados)].reverse()) {
  let r = await api("DELETE", ruta);
  // Lo que ya tiene historia —un lead con su rastro de reparto— no se borra:
  // se archiva, que es lo que el propio producto ofrece en ese caso.
  if (r.s === 409) r = await api("POST", `${ruta}/archivar`, {});
  if (r.s < 300 || r.s === 404) borrados++;
  else fallidos.push(`${r.s} ${ruta}`);
}
// Lo que lleve la marca y se haya escapado del apunte —un alta que la
// pantalla hizo por su cuenta—, también.
for (const [lista, base] of [
  ["/api/v1/leads?limite=50", "/api/v1/leads/"],
  ["/api/v1/accounts?limite=200", "/api/v1/accounts/"],
  ["/api/v1/contacts?limite=200", "/api/v1/contacts/"],
]) {
  for (const x of items((await api("GET", lista)).d)) {
    if (
      /^UX medida /.test(x.nombre ?? "") ||
      /^UX medida /.test(x.empresa ?? "") ||
      /uxmedida@contecrm\.dev$/.test(x.email ?? "")
    ) {
      let r = await api("DELETE", base + x.id);
      if (r.s === 409) r = await api("POST", `${base}${x.id}/archivar`, {});
      if (r.s < 300 || r.s === 404) borrados++;
      else fallidos.push(`${r.s} ${base}${x.id}`);
    }
  }
}
console.log(
  `\nLimpieza: ${borrados} borrados${fallidos.length ? `, ${fallidos.length} sin borrar: ${fallidos.join(", ")}` : ""}.`,
);

const hechas = resultados.filter((r) => r.estado === "hecha").length;
console.log(
  `Medidas ${resultados.length} tareas: ${hechas} terminadas, ${resultados.length - hechas} no.`,
);
if (process.env.MEDIR_JSON)
  writeFileSync(
    process.env.MEDIR_JSON,
    JSON.stringify({ fecha: new Date().toISOString(), resultados }, null, 2),
  );
await navegador.close();
// Un recorrido que no midió nada no puede salir en verde.
process.exit(resultados.length === 0 ? 1 : 0);
