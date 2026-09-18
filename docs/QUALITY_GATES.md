# Gates locales — lo que este repositorio usa en lugar de CI

Este proyecto **no tiene CI/CD, por decisión de proyecto**. Todo lo que en otro
repositorio comprobaría un servidor al abrir un *pull request*, aquí lo comprueba
la máquina de quien desarrolla, antes de que el cambio salga de ella.

Esa apuesta tiene una consecuencia que conviene tener presente: **los gates solo
protegen si están instalados**. En otra solución de la casa se encontró que
`.git/hooks/` solo tenía los `.sample` —o sea, que ningún gate había corrido
nunca— y en ese hueco llevaban meses un centenar de cadenas sin traducir y una
prueba de política de seguridad en rojo sin que nadie lo supiera.

Instalación, **obligatoria**:

```bash
pre-commit install    # instala los hooks de commit Y de push
```

`default_install_hook_types` en la configuración instala los dos tipos de una
vez. Sin esa línea, `pre-commit install` solo pone el de commit, y el de push
—que es el que corre la suite— no llega a existir: el gate más importante nunca
se ejecutaría.

---

## Los tres momentos

| Cuándo | Qué corre | Coste | Lo lanza |
|---|---|---|---|
| **en cada commit** | gates baratos, solo si cambian ficheros relevantes | < 5 s | `.pre-commit-config.yaml` |
| **en cada push** | los gates rápidos + la suite entera | ~1 min | `scripts/preflight.py --tests` |
| **a mano** | además, la construcción del sitio de documentación | minutos | `python scripts/preflight.py --todo` |

El criterio de reparto es el coste: lo de cada commit tiene que ser instantáneo o
se acaba puenteando con `--no-verify`, y entonces no corre **ninguno** de los
demás tampoco.

---

## Los gates, uno a uno

| Gate | Tier | Qué garantiza |
|---|---|---|
| `entorno` | fast | El árbol instalado cumple `requirements*.txt` |
| `ruff` / `formato` | fast | Estilo, orden de imports y errores estáticos |
| `env-example` | fast | `.env.example` refleja los `Settings` reales |
| `catalogo` | fast | La matriz de trazabilidad está regenerada desde el catálogo |
| `arquitectura` | fast | Servicios desacoplados, `tenant_id` obligatorio, permisos declarados, cero valores a fuego |
| `trazabilidad` | fast | Nada se declara «hecho» sin cita en el código **y** en el manual |
| `contrato-headless` | fast | Todo servicio publica su contrato y toda ruta está documentada |
| `pruebas-sin-bd` | tests | Todo lo que no necesita infraestructura |
| `pruebas-con-bd` | tests | Aislamiento entre tenants, motor de procesos, persistencia |
| `docs` | todo | `mkdocs build --strict`: el manual construye y sus enlaces resuelven |

### `entorno` va primero, y es deliberado

Todos los demás gates dan por hecho el entorno en el que corren. Si el árbol
instalado no es el que declaran los manifiestos, lo que midan es otra cosa.

En otra solución de la casa, la primera vez que se comprobó esto salieron **12 de
50** restricciones violadas y las dos dependencias de desarrollo sin instalar —y
con ellas, 1.343 pruebas que no podían ejecutarse—. El sistema que sustituía a la
CI llevaba tiempo sin poder funcionar, y ningún gate podía verlo porque todos
daban por hecho su propio entorno.

### Los gates que son pruebas normales

No todo gate es un hook, y eso es a propósito: corren con `pytest`, salen en el
resumen y no hacen falta dos mecanismos para lo mismo.

| Prueba | Invariante |
|---|---|
| `test_contratos_arquitectura.py::test_ningun_servicio_importa_modulos_de_otro` | La separación en servicios no es decorativa |
| `…::test_el_nucleo_no_importa_servicios` | La dependencia va en un solo sentido |
| `…::test_toda_tabla_de_negocio_lleva_tenant_id` | Las dos redes de aislamiento no tienen punto ciego |
| `…::test_tenant_id_es_obligatorio_donde_existe` | Una fila con tenant nulo sería visible desde todos |
| `…::test_toda_ruta_de_escritura_exige_permiso` | Ninguna escritura sin permiso **declarado en la ruta** |
| `…::test_los_errores_de_dominio_tienen_codigo_estable` | Un cliente no depende del texto en castellano |
| `…::test_no_hay_urls_ni_credenciales_escritas_en_el_codigo` | Cero valores a fuego |
| `…::test_cada_servicio_usa_la_factoria` | Nadie se salta lo transversal |
| `…::test_los_ajustes_siempre_filtran_por_ambito` | La única tabla sin `tenant_id` justificada sigue acotada |
| `test_catalogo_trazabilidad.py` | El catálogo no puede decir que algo está hecho si no lo está |
| `test_headless_contract.py` | Todo existe como servicio con contrato antes que como pantalla |
| `test_rls_aislamiento.py` | Un tenant no ve ni escribe lo de otro, con un rol sin privilegios |

---

## Cuando un gate se pone en rojo

**Primero se entiende, no se desactiva.** Los gates de este repositorio han
encontrado fallos reales en su propio código el mismo día que se escribieron:

- Una ruta de validación que exponía el esquema del tenant sin exigir permiso.
- Una tabla sin `tenant_id` que quedaba fuera de las dos redes de aislamiento.
- Y el propio detector de valores a fuego, que marcaba patrones de validación
  como si fueran URLs: se afinó el detector, porque **un gate con falsos
  positivos se acaba desactivando, que es peor que no tenerlo**.

Si un gate está mal, se arregla el gate y se explica por qué. Si una excepción es
legítima, se añade a su lista **con el motivo escrito**: las listas de
excepciones de este repositorio llevan todas su razón al lado, y hay gates que
comprueban que la lleven.

---

## Por qué no hay CI

Es una decisión de proyecto, igual que en el resto de soluciones de la casa. Lo
que se gana: el ciclo es local, no hay que esperar a un servidor, y el que
desarrolla ve el fallo donde puede arreglarlo. Lo que se pierde, dicho
claramente: **nada obliga** a que los gates hayan corrido antes de que un cambio
llegue al repositorio. Depende de que estén instalados.

Por eso `./setup.sh instalar` los instala, y por eso este documento está enlazado
desde la primera página del manual.
