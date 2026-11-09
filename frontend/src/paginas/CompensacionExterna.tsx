/**
 * El motor externo de compensación: lo que se manda, lo que vuelve y lo que no
 * cuadra con la casa (CRM-03.02.03.04).
 *
 * Hasta el 09-11-2026 `/compensacion/*` componía y conciliaba listas tecleadas
 * y no mandaba nada a ningún motor. Aquí se conecta el motor sobre una
 * conexión de Integraciones, se recogen las ventas ganadas del periodo, se dan
 * de alta cobros, devoluciones y anulaciones, se manda lo pendiente —el hecho,
 * nunca la comisión—, se trae lo calculado y se pone al lado de lo que calcula
 * la casa en sus liquidaciones, con cada diferencia a la vista.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Cargando, Error as Fallo, Vacio } from "@/componentes/Estados";
import { CabeceraPagina } from "@/componentes/Pagina";
import { Casilla, Rejilla } from "@/componentes/Rejilla";
import { llamar } from "@/lib/api";
import { listar } from "@/lib/listados";

const HECHOS = [
  "cierre",
  "anulacion",
  "modificacion_importe",
  "cobro",
  "devolucion",
] as const;

interface Motor {
  conectado: boolean;
  porque?: string;
  conexion_id?: string;
  nombre?: string;
  operaciones?: Record<string, boolean>;
  falta?: string[];
}

interface Hecho {
  id: string;
  tipo: string;
  referencia: string;
  fecha: string;
  importe: string;
  moneda: string;
  estado: string;
  error: string | null;
  comision_motor: string | null;
  comision_casa: string | null;
  diferencia: string | null;
  provisional: boolean;
  periodo: string;
  enviado?: { datos?: { nombre?: string; motivo?: string } };
}

interface Diferencia {
  referencia: string;
  diferencia: string | null;
  porque: string;
}

function primeroDeMes(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

function hoy(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function CompensacionExterna() {
  const { t } = useTranslation();
  const [motor, setMotor] = useState<Motor | null>(null);
  const [hechos, setHechos] = useState<Hecho[] | null>(null);
  const [conexiones, setConexiones] = useState<
    { id: string; nombre: string }[]
  >([]);
  const [conexion, setConexion] = useState("");
  const [desde, setDesde] = useState(primeroDeMes());
  const [hasta, setHasta] = useState(hoy());
  const [resultado, setResultado] = useState("");
  const [diferencias, setDiferencias] = useState<Diferencia[] | null>(null);
  const [fallo, setFallo] = useState<unknown>(null);
  const [manual, setManual] = useState({
    tipo: "cobro",
    referencia: "",
    fecha: hoy(),
    importe: "",
    motivo: "",
  });

  const cargar = useCallback(() => {
    llamar<Motor>("/api/v1/compensacion/motor")
      .then((r) => {
        setMotor(r.datos);
        if (r.datos.conexion_id) setConexion(r.datos.conexion_id);
      })
      .catch((e) => setFallo(e));
    llamar<{ hechos: Hecho[] }>("/api/v1/compensacion/envios")
      .then((r) => setHechos(r.datos.hechos ?? []))
      .catch(() => setHechos([]));
  }, []);
  useEffect(cargar, [cargar]);
  useEffect(() => {
    void listar<{ id: string; nombre: string }>(
      "/api/v1/integraciones/conexiones",
    )
      .then(setConexiones)
      .catch(() => setConexiones([]));
  }, []);

  async function hacer(
    ruta: string,
    cuerpo: unknown,
    decir: (d: Record<string, unknown>) => string,
  ) {
    setFallo(null);
    setResultado("");
    try {
      const r = await llamar<Record<string, unknown>>(ruta, {
        metodo: ruta.endsWith("/motor") ? "PUT" : "POST",
        cuerpo,
      });
      setResultado(decir(r.datos));
      if (Array.isArray(r.datos.diferencias))
        setDiferencias(r.datos.diferencias as Diferencia[]);
      cargar();
    } catch (e) {
      setFallo(e);
    }
  }

  function alta(e: FormEvent) {
    e.preventDefault();
    void hacer(
      "/api/v1/compensacion/envios/manual",
      { ...manual, importe: manual.importe || "0" },
      (d) => t(`compensacionExterna.que.${String(d.que)}`),
    );
  }

  if (fallo && !motor) return <Fallo error={fallo} reintentar={cargar} />;
  if (!motor) return <Cargando />;
  const periodo = { desde, hasta };

  return (
    <div>
      <CabeceraPagina
        titulo={t("compensacionExterna.titulo")}
        entradilla={t("compensacionExterna.entradilla")}
        icono="payments"
      />

      <section className="card mb-4 p-4">
        <h2 className="section-label">{t("compensacionExterna.motor")}</h2>
        <p role="status" className="mt-1 text-dato text-ink">
          {motor.conectado
            ? t("compensacionExterna.conectado", { nombre: motor.nombre })
            : motor.porque}
        </p>
        {motor.operaciones ? (
          <ul className="mt-2 flex flex-wrap gap-1">
            {Object.entries(motor.operaciones).map(([k, v]) => (
              <li
                key={k}
                className={`chip-dato ${v ? "chip-dato--si" : "chip-dato--mal"}`}
              >
                {k}:{" "}
                {v
                  ? t("compensacionExterna.declarada")
                  : t("compensacionExterna.falta")}
              </li>
            ))}
          </ul>
        ) : null}
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("compensacionExterna.conexion")}
            <select
              className="input-base"
              value={conexion}
              onChange={(e) => setConexion(e.target.value)}
            >
              <option value="">{t("compensacionExterna.elige")}</option>
              {conexiones.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn-secondary"
            disabled={!conexion}
            onClick={() =>
              void hacer(
                "/api/v1/compensacion/motor",
                { conexion_id: conexion },
                () => t("compensacionExterna.motorGuardado"),
              )
            }
          >
            {t("compensacionExterna.usarComoMotor")}
          </button>
        </div>
      </section>

      <section className="card mb-4 p-4">
        <h2 className="section-label">{t("compensacionExterna.periodo")}</h2>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("compensacionExterna.desde")}
            <input
              type="date"
              className="input-base"
              value={desde}
              onChange={(e) => setDesde(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("compensacionExterna.hasta")}
            <input
              type="date"
              className="input-base"
              value={hasta}
              onChange={(e) => setHasta(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn-secondary"
            onClick={() =>
              void hacer("/api/v1/compensacion/envios/recoger", periodo, (d) =>
                t("compensacionExterna.recogidas", {
                  nuevas: d.nuevo,
                  ya: d.ya_estaba,
                  cambios: d.cambio_tras_enviar,
                }),
              )
            }
          >
            {t("compensacionExterna.recoger")}
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() =>
              void hacer("/api/v1/compensacion/envios/enviar", undefined, (d) =>
                t("compensacionExterna.enviados", {
                  n: d.enviados,
                  calculados: d.calculados,
                  errores: d.errores,
                }),
              )
            }
          >
            {t("compensacionExterna.enviar")}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() =>
              void hacer("/api/v1/compensacion/envios/calculo", periodo, (d) =>
                String(d.que_significa ?? ""),
              )
            }
          >
            {t("compensacionExterna.traer")}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() =>
              void hacer(
                "/api/v1/compensacion/envios/conciliar",
                periodo,
                (d) =>
                  t("compensacionExterna.conciliado", {
                    cuadran: d.cuadran,
                    hechos: d.hechos,
                    liquidaciones: d.liquidaciones_de_la_casa,
                  }),
              )
            }
          >
            {t("compensacionExterna.conciliar")}
          </button>
        </div>
        {resultado ? (
          <p role="status" className="mt-3 text-dato text-ink">
            {resultado}
          </p>
        ) : null}
        {fallo ? <Fallo error={fallo} /> : null}
        {diferencias && diferencias.length > 0 ? (
          <ul className="lista-acotada mt-2 grid gap-1">
            {diferencias.map((d) => (
              <li key={d.referencia} className="text-rotulo text-danger">
                {d.referencia}: {d.porque}
                {d.diferencia ? ` (${d.diferencia})` : ""}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="card mb-4 p-4">
        <h2 className="section-label">{t("compensacionExterna.manual")}</h2>
        <form
          className="mt-2 grid gap-3 md:grid-cols-3"
          onSubmit={(e) => alta(e)}
        >
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("compensacionExterna.tipo")}
            <select
              className="input-base"
              value={manual.tipo}
              onChange={(e) => setManual({ ...manual, tipo: e.target.value })}
            >
              {HECHOS.map((h) => (
                <option key={h} value={h}>
                  {t(`compensacionExterna.hechos.${h}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("compensacionExterna.referencia")}
            <input
              className="input-base"
              required
              value={manual.referencia}
              onChange={(e) =>
                setManual({ ...manual, referencia: e.target.value })
              }
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("compensacionExterna.fecha")}
            <input
              type="date"
              className="input-base"
              required
              value={manual.fecha}
              onChange={(e) => setManual({ ...manual, fecha: e.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted">
            {t("compensacionExterna.importe")}
            <input
              className="input-base"
              inputMode="decimal"
              required
              value={manual.importe}
              onChange={(e) =>
                setManual({ ...manual, importe: e.target.value })
              }
            />
          </label>
          <label className="flex flex-col gap-1 text-rotulo text-ink-muted md:col-span-2">
            {t("compensacionExterna.motivo")}
            <input
              className="input-base"
              value={manual.motivo}
              onChange={(e) => setManual({ ...manual, motivo: e.target.value })}
            />
          </label>
          <div className="md:col-span-3">
            <button type="submit" className="btn-secondary">
              {t("compensacionExterna.darDeAlta")}
            </button>
          </div>
        </form>
      </section>

      <section className="card mb-4 p-4">
        <h2 className="section-label">{t("compensacionExterna.hechosTit")}</h2>
        {!hechos ? <Cargando /> : null}
        {hechos && hechos.length === 0 ? (
          <Vacio titulo={t("compensacionExterna.sinHechos")} compacto />
        ) : null}
        {hechos && hechos.length > 0 ? (
          <Rejilla
            titulo={t("compensacionExterna.hechosTit")}
            cabeceras={[
              t("compensacionExterna.fecha"),
              t("compensacionExterna.tipo"),
              t("compensacionExterna.referencia"),
              t("compensacionExterna.importe"),
              t("compensacionExterna.estado"),
              t("compensacionExterna.delMotor"),
              t("compensacionExterna.deLaCasa"),
              t("compensacionExterna.diferencia"),
            ]}
          >
            {hechos.map((h) => (
              <tr key={h.id}>
                <Casilla enUnaLinea>{h.fecha}</Casilla>
                <Casilla>{t(`compensacionExterna.hechos.${h.tipo}`)}</Casilla>
                <Casilla>
                  {h.enviado?.datos?.nombre ?? h.referencia}
                  {h.enviado?.datos?.motivo ? (
                    <span className="block text-rotulo text-ink-muted">
                      {h.enviado.datos.motivo}
                    </span>
                  ) : null}
                </Casilla>
                <Casilla enUnaLinea>
                  {h.importe} {h.moneda}
                </Casilla>
                <Casilla>
                  {t(`compensacionExterna.estados.${h.estado}`)}
                  {h.error ? (
                    <span className="block text-rotulo text-danger">
                      {h.error}
                    </span>
                  ) : null}
                </Casilla>
                <Casilla enUnaLinea>
                  {h.comision_motor ?? ""}
                  {h.comision_motor && h.provisional ? (
                    <span className="block text-rotulo text-ink-muted">
                      {t("compensacionExterna.provisional")}
                    </span>
                  ) : null}
                </Casilla>
                <Casilla enUnaLinea>{h.comision_casa ?? ""}</Casilla>
                <Casilla enUnaLinea>
                  {h.diferencia !== null && Number(h.diferencia) !== 0 ? (
                    <span className="text-danger">{h.diferencia}</span>
                  ) : (
                    (h.diferencia ?? "")
                  )}
                </Casilla>
              </tr>
            ))}
          </Rejilla>
        ) : null}
      </section>
    </div>
  );
}
