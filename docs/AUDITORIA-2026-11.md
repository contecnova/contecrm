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
| SEC-20 | `/mfa/iniciar` sobrescribía el secreto y los códigos de recuperación activos antes de confirmar el nuevo | Secreto y códigos pendientes; solo se promueven al activar con un código válido | `ca653d8` | 1 prueba (un código malo no deja a nadie fuera) |
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
| FUN-A-11 | Consulta y commit del relevo del outbox, aviso de empuje y guardado de idempotencia síncronos dentro de código async | `asyncio.to_thread` para lo bloqueante; publicar sigue siendo async | `cabe976` | Prueba nueva del relevo contra BD (no había ninguna) + idempotencia y eventing, 6/6 |
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
| FUN-B-22 | La llamada fallida al proveedor de firma y su evidencia se perdían con el rollback | Se escriben en su propia transacción, confirmada antes de relanzar | `068bfdf` | Prueba: se escriben en una sesión distinta de la de la petición (el arnés comparte transacción y no permite reproducir el rollback real) |

## Pantallas, usabilidad y diseño

| ID | Qué pasaba | Qué se hizo | Commit | Verificación |
|---|---|---|---|---|
| UX-8 | Enlaces a `/contactos/:id` y `/cuentas/:id`, que no son rutas | `fichaDeObjeto` | `d49cad9` | Prueba que falla con el fallo plantado |
| UX-5 | Borrados sin confirmación en 6-7 pantallas | `ConfirmarBorrado` con aviso propio; «deshacer» al dejar de seguir | `d49cad9` | vitest |
| UX-2 / UX-3 | Texto sobre el acento por debajo de 4,5:1 en oscuro | Token `--on-accent` (3,56 → 5,16:1) | `d49cad9` | `contraste.mjs` |
| UX-4 | Anillo de foco a 1,77:1 | Opaco, ≥ 4,63:1 | `d49cad9` | `contraste.mjs` |
| UX-25 | `npm run verificar` se rompía en Windows (CRLF) | Normaliza al leer | `f226976` | `--comprobar`: 239 pestañas, exit 0 |
| UX-26 | `contraste.mjs` no medía texto sobre rellenos | Mide acento, foco y tinta a mano | `d49cad9` | Falla con los valores antiguos |
| UX-1 | 123 fallos de red tragados sin avisar (93 sin comentario): «no se pudo consultar» se veía como «no hay datos» | `useCargasSecundarias` + `FalloCompacto` con reintento; quedan 36, todos legítimos y comentados | `79a6a40` | vitest 310/311 (la que falla es una prueba que falla a veces bajo carga; sola pasa) |
| UX-9 | Listas cortadas a 200 sin avisar (27 `limite=200` a mano) | `useListaPaginada` con «Cargar más», `AvisoDeRecorte`, directorio de personas por cursor; quedan 3 justificados | `79a6a40` | vitest; rutas sin cursor anotadas como pendientes de backend |
| COB-1 | No había pantalla para dar de alta o quitar passkeys | `MisPasskeys` en Seguridad | `57be6a3` | vitest 8/8 |
| COB-12 / 13 | Los enlaces de partner y de alta no llevaban a ninguna pantalla | `/portal-partner` y `?alta=` | `57be6a3` | vitest 9/9 |

## Documentación y herramientas

| ID | Qué pasaba | Qué se hizo | Commit | Verificación |
|---|---|---|---|---|
| DOC-1 | README con cifras de otra época | 14 servicios, 788 / 785 / 3 | `2b0271e` | Medido en `setup.sh` y `estado.md` |
| AN-21 | Una prueba con BD tardaba 10-11 min | Modo persistente `CONTECRM_PRUEBAS_PG` | `1486e86` | 277 s en frío → 109 s; 2 pruebas en 77 s |
| GATE-3 | La prueba del almacén de secretos fallaba sin `ENCRYPTION_KEY` en el entorno | La prueba fija su propia clave | `865ae0b` | El nodo pasa, 1/1 |
| — | `docs/procesos.md` estaba desfasado del código | Regenerado | `17a2dad` | `gen_procesos.py` |
| SEC-9 | El guard de SSRF admitía los hosts de los servicios internos (`RUTAS_SERVICIOS`, CI, DMS) para CUALQUIER URL, también las de webhooks y conectores que escribe un tenant; y no bloqueaba 100.64.0.0/10 (CGNAT, metadatos de Alibaba Cloud) | Los hosts internos solo se admiten con `cliente_seguro(internos=True)`, que llevan únicamente las 13 llamadas a servicios de la casa (analytics→CI, documental→DMS, clave de lectura→identity, salud→CRM); se bloquea toda IP no global | `024a198` | `test_los_servicios_de_la_casa_solo_para_quien_los_pide` + `test_las_ip_internas_se_bloquean[100.100.100.200]` + 4 nodos del guard, pasan |
| SEC-10 | La RLS fallaba abierta: con `app.current_tenant` vacío o sin fijar, la política dejaba ver y escribir las filas de TODOS los tenants, así que cualquier conexión que llegara sin tenant (script, conexión cruda, camino que se saltara `nueva_sesion`) cruzaba el aislamiento | El sistema se declara con `*` (`crmcore.db.rls.GUC_SISTEMA`), que solo ponen las sesiones abiertas con `sistema=True`, `alembic/env.py` y los scripts de diagnóstico y respaldo; vacío no ve nada. Misma condición en `rls.py` y `deploy/sql/rls.sql`. **Una base ya desplegada tiene que volver a pasar `scripts/aplicar_rls.py`** | `a5dcd8c` | Nodo `test_sin_tenant_no_se_ve_nada_y_el_sistema_se_declara` (vacío → 0 filas, `*` → todas) + 2 de aislamiento y alta de tenant con el rol sin privilegios |
| SEC-11 | Ningún JWT llevaba `iss` ni `aud` y los cuatro tipos (sesión, componente, portal, ticket de cuadro) se firmaban con la `SECRET_KEY` cruda: solo el campo `tipo` los separaba (raíz de SEC-2). Cinco `jwt.encode` y cuatro `jwt.decode` repartidos | Un solo módulo, `crmcore.tokens` (`emitir`/`verificar`): clave derivada por tipo (HMAC de `SECRET_KEY` con la audiencia), `aud`=`contecrm:<tipo>`, `iss`=`contecrm`, `exp` obligatorio. Lo usan identity, embebido, portal, cuadros y `deps`. Los tokens emitidos antes dejan de valer al desplegar (vida de minutos: se renuevan entrando) | `bff2128` | 4 pruebas nuevas en `test_cada_token_lleva_su_clave_y_su_audiencia.py` + 18 nodos de componente, portal, cookie y cuadro, pasan |
| UX-7 | Las confirmaciones en línea no movían el foco: con teclado o lector de pantalla, la pregunta aparecía sin que nadie la oyera | Hook `lib/foco.ts` (`useFocoDeConfirmacion`): al abrir, foco en el botón seguro; al cerrar, vuelve a donde estaba solo si se perdió. Lo usan la fusión de `Duplicados` y la acción irreversible de `Acciones` | `843cf3b` | tsc 0 · eslint 0 en 20 ficheros · vitest 17/17 nuevos y tocados + 51/51 de las páginas cambiadas · contraste 54 pares |
| UX-10 | Varias pantallas enseñaban «vacío» mientras cargaban | `null` (cargando) separado de `[]` (vacío) en Canales, CanalesDeEntrada, CicloDeVidaDelCliente y Territorios | `843cf3b` | tsc 0 · eslint 0 en 20 ficheros · vitest 17/17 nuevos y tocados + 51/51 de las páginas cambiadas · contraste 54 pares; prueba de Canales: cargando y luego vacío |
| UX-11 | Páginas que cargan sin indicador, medidas una a una | Asistente (dos secciones devolvían `null` y tragaban errores: ahora cargando + fallo con reintento), Procesos (versiones y plantillas: un fallo decía «biblioteca vacía» y ofrecía cargar las de serie), Prospeccion, TransferirPropiedad (`useDirectorio`, desplegables deshabilitados mientras cargan), Alm (estado ocupado en «Ver desvío»). Coste y Alm solo cargan al pulsar: no necesitan más | `843cf3b` | tsc 0 · eslint 0 en 20 ficheros · vitest 17/17 nuevos y tocados + 51/51 de las páginas cambiadas · contraste 54 pares |
| UX-15 | `lang` del documento seguía la localización del tenant: un tenant `pt-PT` marcaba como portugués un texto en español y el lector de pantalla lo pronunciaba mal | `lang` sigue al idioma resuelto de i18n (al iniciar y en `languageChanged`); las fechas siguen al tenant. La prueba que afirmaba lo contrario se corrige. `docs/ACCESIBILIDAD.md` 3.1.1 al día | `843cf3b` | tsc 0 · eslint 0 en 20 ficheros · vitest 17/17 nuevos y tocados + 51/51 de las páginas cambiadas · contraste 54 pares |
| COB-3 | Activar o volver a una versión de modelo de IA no tenía pantalla | Columna «Acción» en `ModelosPredictivos` (solo con permiso de operar): «Activar» / «Volver a esta», con `alertdialog` que compara la métrica actual con la nueva y avisa si no pasa el mínimo; el aviso del servidor se anuncia en `role=status`. Usa `POST /ia/modelos/{tipo}/versiones/{version}/activar` | `843cf3b` | tsc 0 · eslint 0 en 20 ficheros · vitest 17/17 nuevos y tocados + 51/51 de las páginas cambiadas · contraste 54 pares; 3 pruebas: pregunta antes, cancelar no envía, sin permiso no hay columna |
| GATE-2 | El gate de almacenamiento del navegador fallaba en Windows | No estaba desfasado: `str(relative_to)` daba `lib	ema.ts` y no casaba con la lista. Ahora `.as_posix()` y además exige que cada fichero de la lista exista | `843cf3b` | Nodo `test_el_front_no_guarda_datos_de_negocio_en_el_navegador`: fallaba con las 9 rutas con barra invertida, ahora pasa |
| TEST-1 | La prueba de reintento de la suite fallaba a ratos | Espera la fila con `findByText` y consulta `getByRole` una vez (rol y nombre se siguen comprobando). Medido: 107 ms por `getByRole` frente a 10 ms por `getByText`; el sondeo agotaba el segundo con carga | `843cf3b` | `suite.test.tsx` pasa |
| FUN-A-18 | El worker de procesos no comprobaba que seguía siendo dueño de la instancia: si un avance duraba más que el alquiler de la toma (`WORKER_BLOQUEO_MIN`), otra réplica la volvía a tomar y las dos ejecutaban los mismos pasos (correos o llamadas externas repetidos) | La instancia se relee con `FOR UPDATE` durante todo el avance (el motor no confirma a mitad) y, si `tomada_por` ya no es este worker, se suelta sin tocarla. La toma del otro usa `skip_locked` y la salta | pendiente | Nodo `test_una_instancia_que_ya_tiene_otro_worker_no_se_avanza` (doble de sesión: pide FOR UPDATE, no avanza, deshace). El camino normal contra Postgres real no tiene prueba: verificado por lectura |

## Lo que la auditoría no llegó a cubrir

Está en la página de seguimiento como «Análisis pendiente» (AN-1 a AN-20):
pruebas con varias réplicas, autorización fina ruta a ruta, SCIM, vinculación
de cuentas SSO, inyección de prompts, revisión funcional de analytics,
marketing, integration, tenancy y el resto del núcleo, prueba visual y de
accesibilidad en navegador y rendimiento del frontend.
