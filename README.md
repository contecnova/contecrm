# contecrm

CRM empresarial **headless**, con **orquestación de servicios** y
**multi-tenant** desde la primera línea.

```bash
./setup.sh instalar     # una vez
./setup.sh arrancar     # ocho servicios en pie en segundos
./setup.sh demo         # un tenant de demostración
```

→ <http://localhost:8080/api/v1/docs>

---

## Qué es esto

Un CRM construido sobre tres restricciones que no se negocian, y que están
comprobadas por pruebas en lugar de declaradas:

| | Qué significa | Gate que lo sostiene |
|---|---|---|
| **Frontless** | Toda capacidad existe primero como servicio con contrato. La interfaz es un consumidor más, sin privilegios ni lógica propia | `tests/unit/test_headless_contract.py` |
| **Orquestación** | Los procesos de negocio son composiciones explícitas y observables, no lógica enterrada en controladores o *triggers* | `tests/unit/test_contratos_arquitectura.py` |
| **Multi-tenant** | Cada capacidad es *tenant-aware* por defecto: datos, configuración, metadatos, cuotas, claves y observabilidad | `tests/integration/test_rls_aislamiento.py` |

El alcance vive en un [catálogo funcional](docs/catalogo/catalogo.yaml) de **527
capacidades** con identificador estable. Del catálogo salen el manual, la matriz
de trazabilidad y un gate que **impide declarar hecho lo que no lo está**: una
capacidad solo pasa a «hecho» si se cita por su ID en el código y está explicada
en un manual escrito a mano.

**Estado hoy**: 86 capacidades hechas, 15 en curso, 426 pendientes — la fase 0
(la plataforma) es la que está en marcha. El detalle, en
[el estado del catálogo](docs/catalogo/estado.md), y lo que está a medias se
dice con nombre y apellidos al final del
[Manual III](docs/manual-3-funcionalidades.md).

## Los servicios

```
              ┌──────────────┐
  cliente ───▶│   gateway    │  tenant · identidad · límites · rutas
              └──────┬───────┘
     ┌──────────┬────┴─────┬──────────┬──────────┐
     ▼          ▼          ▼          ▼          ▼
  tenancy   identity   metadata  orchestrator  automation  integration  eventing
     └──────────┴──────────┴──────────┴──────────┘
                           │
                 Postgres (un esquema y un rol por servicio)
                 NATS JetStream (un subject por tenant)
```

Cada servicio tiene **su esquema, su rol de base de datos sin permisos sobre los
demás y su propia cadena de migraciones**. La propiedad exclusiva de datos no es
una norma en un documento: es una imposibilidad a nivel de permisos.

## Documentación

El manual completo está en [`docs/`](docs/index.md) y se sirve con
`mkdocs serve`:

| | Para quién |
|---|---|
| [I — Empezar](docs/manual-1-empezar.md) | Quien acaba de clonar el repositorio |
| [II — Perfiles](docs/manual-2-perfiles.md) | Quien va a usar o administrar el CRM |
| [III — Referencia funcional](docs/manual-3-funcionalidades.md) | Quien necesita saber qué hace, capacidad por capacidad |
| [IV — Configuración y operación](docs/manual-4-configuracion.md) | Quien lo despliega y lo mantiene |
| [V — Arquitectura](docs/manual-5-arquitectura.md) | Quien va a tocar el código o a evaluarlo |
| [VI — Ajustes](docs/manual-6-referencia-ajustes.md) | Los 122 ajustes, generados del código |
| [Gates locales](docs/QUALITY_GATES.md) | **Quien va a contribuir: empieza por aquí** |

## Desarrollo

Este repositorio **no tiene CI, por decisión de proyecto**. Lo que en otro
repositorio comprobaría un servidor, aquí lo comprueban hooks de git:

```bash
pre-commit install          # obligatorio: los gates solo protegen si están puestos
./setup.sh gates            # los rápidos
./setup.sh gates --tests    # + la suite entera
```

Las pruebas que necesitan base de datos usan un **Postgres embebido** que viene
en un wheel: no hace falta Docker ni permisos de administrador, y por eso el gate
de *pre-push* puede correr en cualquier máquina —que es lo que evita que alguien
acabe empujando con `--no-verify`.

## Reutilización

`contecrm` no parte de cero: [`docs/REUTILIZACION.md`](docs/REUTILIZACION.md)
inventaría, con rutas y líneas medidas, qué está ya resuelto en `contecmind`,
`contecweb`, `contecflow-PSA` y `contecpos`, y qué se porta de cada uno. La regla
de la casa: **antes de escribir un módulo nuevo se busca en las otras cuatro
soluciones; si existe, se porta y se mejora**.
