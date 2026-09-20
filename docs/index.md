# contecrm — Documentación

CRM empresarial **headless**, con **orquestación de servicios** y **multi-tenant**
desde la primera línea.

> **Dónde vive el manual:** aquí. El `README.md` de la raíz es solo el índice que
> apunta a este sitio. Se sirve con `mkdocs serve`.

## Mapa rápido

- **Arrancarlo en cinco minutos** → *[Manual I](manual-1-empezar.md)*
- **Qué puede hacer cada perfil** → *[Manual II](manual-2-perfiles.md)*
- **Qué sabe hacer el sistema**, capacidad por capacidad → *[Manual III](manual-3-funcionalidades.md)*
- **Configurarlo y operarlo** → *[Manual IV](manual-4-configuracion.md)*
- **Cómo está construido y por qué** → *[Manual V](manual-5-arquitectura.md)*
- **Los 122 ajustes, uno a uno** → *[Manual VI](manual-6-referencia-ajustes.md)*
- **Contribuir** → *[Gates locales](QUALITY_GATES.md)*. **Empieza por ahí**: este
  proyecto no tiene CI por decisión, y los gates solo protegen si los instalas.

## Las tres restricciones que ordenan todo

| | Qué significa | Cómo se comprueba |
|---|---|---|
| **Frontless** | Toda capacidad existe primero como servicio con contrato. La interfaz es un consumidor más, sin privilegios | `tests/unit/test_headless_contract.py` |
| **Orquestación** | Los procesos son composiciones explícitas y observables, no lógica enterrada en controladores | `tests/unit/test_contratos_arquitectura.py` |
| **Multi-tenant** | Cada capacidad es *tenant-aware* por defecto: datos, configuración, cuotas, claves y observabilidad | `tests/integration/test_rls_aislamiento.py` |

No son declaraciones: cada una tiene un gate que falla si se rompe.

## Estado

El alcance está en un [catálogo funcional](catalogo/catalogo.yaml) de **560
capacidades** con identificador estable, del que salen el manual, la matriz de
trazabilidad y el gate que impide declarar hecho lo que no lo está.

- **[Resumen por módulo, criticidad y fase](catalogo/resumen.md)**
- **[Estado de las 560 capacidades](catalogo/estado.md)**
- **[Qué se reutiliza de las otras soluciones de la casa](REUTILIZACION.md)**

Las fases 0 (plataforma) y 1 (núcleo de datos de cliente y ventas básica) son
las que están en marcha. Lo que está a medias se dice
con nombre y apellidos al final del [Manual III](manual-3-funcionalidades.md).

## Servicios

| Servicio | De qué responde |
|---|---|
| `gateway` | Única puerta: tenant, identidad, límites, enrutado |
| `tenancy` | Ciclo de vida del tenant, configuración, planes, cuotas |
| `identity` | Usuarios, roles, sesiones, credenciales, federación |
| `metadata` | Objetos y campos del tenant, validaciones, layouts |
| `orchestrator` | Motor de procesos duradero, sagas, tareas humanas |
| `automation` | Reglas «cuando X, si Y, entonces Z» |
| `integration` | Conectores declarativos con sistemas externos |
| `eventing` | Webhooks, catálogo de eventos, replay, cola de fallidos |
| `party` | Cuentas, contactos, actividades, calidad del dato y consentimientos |
| `sales` | Leads, pipelines y oportunidades |

## Estado del proyecto

La hoja de estado (`docs/hoja-estado.html`) enseña las 560 capacidades con su
estado real, filtrables por fase, servicio, criticidad y texto, y dice de cada
capacidad «en curso» qué hay y qué falta.

Se **genera** desde el catálogo y desde este manual —`python
scripts/gen_hoja_estado.py`— y un gate del preflight falla si se queda
desfasada. Editarla a mano no serviría de nada: la siguiente regeneración la
pisaría, y esa es precisamente la garantía de que dice la verdad.
