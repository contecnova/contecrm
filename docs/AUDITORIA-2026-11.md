# Auditoría del 13-11-2026: qué se encontró y qué se arregló

Revisión completa del repositorio: seguridad, código muerto y valores fijos,
usabilidad, diseño, funcionalidad y presencia en pantalla de cada capacidad.
Cada hallazgo se midió (herramienta, prueba o lectura del código con su línea),
y cada arreglo lleva su commit y cómo se verificó. El seguimiento vivo, con los
pendientes, está en la página de saneamiento que acompaña a esta auditoría; este
documento es el registro que se queda en el repositorio.

**Cómo leer las columnas.** *Verificación* dice lo que se ejecutó de verdad.
«Solo lectura» quiere decir que no hay prueba que pase por ese camino: se dice
para que nadie lo dé por probado.

## Seguridad

| ID | Qué pasaba | Qué se hizo | Commit | Verificación |
|---|---|---|---|---|
| SEC-1 | `POST /auth/restablecer` devolvía el token: con un correo y el slug se tomaba cualquier cuenta. Además el evento no se volcaba y ningún correo podía salir | El enlace va solo por correo (evento interno → aviso de identidad, urgente); solo a miembros activos del tenant | `34f863f` | 35 pruebas de restablecer + 115 de gates |
| SEC-2 | El ticket del cuadro incrustado valía como sesión del creador en todo el CRM | Puerta propia `admite_cuadro_embebido`; lista blanca de tipos de JWT; rutas dedicadas en el gateway | `5c76d79`, `522d63c` | 10 pruebas de puertas + gate de permisos |
| SEC-3 | `CAMBIAME` de `.env.example` no se rechazaba en producción | Se recorren todos los ajustes (también los de cada servicio); claves maestras ≥ 32 caracteres | `84a43c8` | 14 pruebas |
| SEC-4 | Cambiar el TOTP o añadir passkeys no pedía reverificación | `cambio_mfa` si la cuenta ya tiene factor fuerte | `90cf1e7` | 10 pruebas (5 fallan con el código anterior) |
| SEC-5 | El portal de partner devolvía el token del enlace | Respuesta fija; enlace por evento interno y correo a no usuarios (`identity/correo_externo.py`) | `90cf1e7` | Pruebas con BD del portal de partner |
| SEC-6 | El alta autoservicio devolvía el token de confirmación | Igual que SEC-5 (`tenant.alta_solicitada`) | `90cf1e7` | Prueba con BD del alta |
| SEC-7 | `/portal/enlace` exigía sesión de empleado (el cliente recibía 401) y devolvía el token | Ruta pública con tenant, respuesta fija, enlace solo por correo; validez por ajuste | `01f75c8` | 5 pruebas de portal + gate + vitest 6/6 |
| SEC-8 | La IP salía del primer valor de `X-Forwarded-For` (lo escribe el cliente); `TRUSTED_PROXIES` sin uso | `crmcore.http.ip_cliente`: último salto no confiable, solo tras un proxy declarado | `16bcba7` | 6 pruebas |
| SEC-12 | El compose fijaba `ENV: dev` | `ENV: ${ENV:-dev}`; su `SECRET_KEY` por defecto es un marcador inseguro | `db7fccf` | 10 pruebas; `docker compose config` |
| SEC-13 | Login y enlaces sin tope propio por IP; el tiempo del login delataba qué correos existen | Topes en el gateway (`ENTRAR_INTENTOS_POR_IP`); el hash se verifica siempre | `5ba49b2` | 6 pruebas |
| SEC-19 | Los webhooks y el empuje entregaban eventos internos (enlaces de restablecer y de aprobación) | Solo salen eventos públicos del catálogo | `fe39633` | 28 pruebas de webhooks |
| HARD-1 | `aceptar_host_desconocido` del SFTP valía en producción | Rechazado en producción | `f7cdd6a` | 2 pruebas |
| FUN-A-3 | La rotación del refresco no detectaba la reutilización y la revocación se deshacía | Refresco anterior guardado, margen de gracia para pestañas, revocación confirmada, `FOR UPDATE` | `6d10816` | 4 pruebas |
| FUN-A-13 | La caché de claves de API ignoraba la IP | Caché por (secreto, IP) | `9ef0fe7` | Prueba con transporte simulado |
| FUN-A-15 | El contador de intentos de login se pisaba en paralelo | `UPDATE … + 1 RETURNING` en una sentencia | `9ef0fe7` | Prueba con objeto desfasado |
| DEP-1 | 33 CVE en 5 paquetes Python y 3 en el extra de trazas | Versiones corregidas; `pyopenssl` fijada | `3414e6e` | `pip-audit`: 0 vulnerabilidades |

## Funcionalidad

| ID | Qué pasaba | Qué se hizo | Commit | Verificación |
|---|---|---|---|---|
| FUN-A-4 | Los reintentos de webhooks no encontraban el evento | El sobre sale del archivo de eventing | `fe39633` | Reintento real en prueba |
| FUN-A-5 | Nadie escribía el archivo de eventos: replay siempre 0 | Se archiva cada evento público; purga diaria (`EVENTOS_ARCHIVO_RETENCION_DIAS`) | `fe39633` | 28 pruebas de webhooks |
| FUN-A-6 | Una tarea humana vencida paraba el proceso para siempre | Escalar de verdad, `si_vence` o fallo explicado | `c850e0f` | 7 pruebas |
| FUN-A-7 | Una aprobación automática sin importe se aprobaba sola | Comparación numérica con un lado vacío = falsa | `2939201` | 60 pruebas sin BD + nodos con BD |
| FUN-A-8 | Una petición idempotente cancelada dejaba la clave «en curso» 24 h | Se libera como fallo ante excepción o cancelación | `0dca4e7` | 2 nuevas + 2 existentes |
| FUN-A-10 | Dos réplicas reintentaban la misma entrega | Reserva por plazo en la misma transacción del bloqueo | `aa7443d` | 2 pruebas |
| FUN-A-14 | El tope del alta contaba la IP del gateway | Tope en el gateway; tenancy usa la IP común | `5ba49b2` | Pruebas de SEC-13 |
| FUN-A-16 | Dos aprobadores a la vez se pisaban | `responder_tarea` relee con `FOR UPDATE` | `1985e70` | 3 pruebas |
| FUN-A-17 | Un fallo transitorio de BD dejaba la instancia «fallida» | Se distingue y se reintenta | `c632dd2` | 1 prueba |
| FUN-B-1 | La previsión sumaba lo perdido y lo cancelado | Excluido en cálculo, organigrama, desglose, foto y waterfall | `42e1ac4` | 6 pruebas con BD |
| FUN-B-2 | El SLA no contaba los vencidos abiertos | Cuenta lo vencido; respeta la pausa | `17348a1` | 3 pruebas con BD |
| FUN-B-3 | Aceptar dos veces un presupuesto daba dos pedidos | `FOR UPDATE` + 409 + restricción única | `2939201` | Pruebas con BD |
| FUN-B-4 / B-5 | El reenvío al ERP se descartaba; un rechazo tardío pisaba un pedido confirmado | Clave por intento; respuestas fuera de turno ignoradas y auditadas | `2939201` | Pruebas con BD |
| FUN-B-6 | Liquidaciones de comisión duplicadas (la comprobación comparaba `= NULL`) | `IS NULL`, solapamientos, `FOR UPDATE`, índice único parcial | `1d806ae` | 6 pruebas con BD |
| FUN-B-7 | Operaciones de comisión sin validar → 500 | Modelo `Operacion` tipado → 422 | `47cce4e` | Prueba de modelo |
| FUN-B-8 | El acelerador saltaba con la consecución redondeada | Compara sin redondear | `47cce4e` | 1 prueba con BD |
| FUN-B-10 | Cambiar la cantidad no recalculaba el importe | Se recalcula (o se exige) | `ae6bade` | 1 prueba con BD |
| FUN-B-11 | Repetir el calendario de ingresos lo duplicaba | Reemplaza el de la oportunidad y tipo | `ae6bade` | 1 prueba con BD |
| FUN-B-14 | Líneas de presupuesto sin límites | Límites como en `CrearLinea` | `ae6bade` | Prueba de modelo |
| FUN-B-15 | Se fusionaba dentro de una cuenta ya absorbida | `party.superviviente_fusionada` | `3b574fe` | 2 pruebas |
| FUN-B-19 | Los huecos de agenda se construían en UTC | Zona del tenant, salida en UTC | `f997584` | 4 pruebas |
| FUN-B-20 | Rutas `async` bloqueaban el bucle con trabajo síncrono | `asyncio.to_thread` | `4f71dfe` | `probar` e `invocar` por su ruta real; `recibir_lead` y `orden_chat` solo lectura |
| FUN-B-27 | La bandeja de casos no respetaba la pausa | Misma regla que el informe | `50b88c1` | 10 pruebas |

## Pantallas, usabilidad y diseño

| ID | Qué pasaba | Qué se hizo | Commit | Verificación |
|---|---|---|---|---|
| UX-8 | Enlaces a `/contactos/:id` y `/cuentas/:id`, que no son rutas | `fichaDeObjeto` | `d49cad9` | Prueba que falla con el fallo plantado |
| UX-5 | Borrados sin confirmación en 6-7 pantallas | `ConfirmarBorrado` con aviso propio; «deshacer» al dejar de seguir | `d49cad9` | vitest |
| UX-2 / UX-3 | Texto sobre el acento por debajo de 4,5:1 en oscuro | Token `--on-accent` (3,56 → 5,16:1) | `d49cad9` | `contraste.mjs` |
| UX-4 | Anillo de foco a 1,77:1 | Opaco, ≥ 4,63:1 | `d49cad9` | `contraste.mjs` |
| UX-25 | `npm run verificar` se rompía en Windows (CRLF) | Normaliza al leer | `f226976` | `--comprobar`: 239 pestañas, exit 0 |
| UX-26 | `contraste.mjs` no medía texto sobre rellenos | Mide acento, foco y tinta a mano | `d49cad9` | Falla con los valores antiguos |
| UX-1 | 123 fallos de red tragados sin avisar (93 sin comentario): «no se pudo consultar» se veía como «no hay datos» | `useCargasSecundarias` + `FalloCompacto` con reintento; quedan 36, todos legítimos y comentados | ver abajo | vitest 310/311 (la que falla es una prueba que falla a veces bajo carga; sola pasa) |
| UX-9 | Listas cortadas a 200 sin avisar (27 `limite=200` a mano) | `useListaPaginada` con «Cargar más», `AvisoDeRecorte`, directorio de personas por cursor; quedan 3 justificados | ver abajo | vitest; rutas sin cursor anotadas como pendientes de backend |
| COB-1 | No había pantalla para dar de alta o quitar passkeys | `MisPasskeys` en Seguridad | `57be6a3` | vitest 8/8 |
| COB-12 / 13 | Los enlaces de partner y de alta no llevaban a ninguna pantalla | `/portal-partner` y `?alta=` | `57be6a3` | vitest 9/9 |

## Documentación y herramientas

| ID | Qué pasaba | Qué se hizo | Commit | Verificación |
|---|---|---|---|---|
| DOC-1 | README con cifras de otra época | 14 servicios, 788 / 785 / 3 | `2b0271e` | Medido en `setup.sh` y `estado.md` |
| AN-21 | Una prueba con BD tardaba 10-11 min | Modo persistente `CONTECRM_PRUEBAS_PG` | `1486e86` | 277 s en frío → 109 s; 2 pruebas en 77 s |
| — | `docs/procesos.md` estaba desfasado del código | Regenerado | `17a2dad` | `gen_procesos.py` |

## Lo que la auditoría no llegó a cubrir

Está en la página de seguimiento como «Análisis pendiente» (AN-1 a AN-20):
pruebas con varias réplicas, autorización fina ruta a ruta, SCIM, vinculación
de cuentas SSO, inyección de prompts, revisión funcional de analytics,
marketing, integration, tenancy y el resto del núcleo, prueba visual y de
accesibilidad en navegador y rendimiento del frontend.
