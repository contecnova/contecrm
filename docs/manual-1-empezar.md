# Manual I — Empezar a usar la solución

Para quien acaba de clonar el repositorio y quiere verlo funcionando.

## Qué hace falta

- **Python 3.12** o superior. Nada más para el modo local.
- **Docker** solo si quieres levantarlo como en producción (ver más abajo por
  qué a veces hace falta).

## Instalación

```bash
git clone https://github.com/contecnova/contecrm.git
cd contecrm
./setup.sh instalar
```

Eso crea el entorno, instala las dependencias, genera un `.env` con **secretos
aleatorios** —nunca valores de ejemplo, que acaban llegando a producción porque
«ya venían así»— e instala los gates de git.

## Arrancar

```bash
./setup.sh arrancar
```

En unos segundos tienes los ocho servicios en pie con un Postgres embebido:

```
  ✓ tenancy :8001 listo          ✓ automation :8005 listo
  ✓ identity :8002 listo         ✓ integration :8006 listo
  ✓ metadata :8003 listo         ✓ eventing :8007 listo
  ✓ orchestrator :8004 listo     ✓ gateway :8080 listo
```

La documentación interactiva de la API está en
**<http://localhost:8080/api/v1/docs>**.

### Con Docker, y por qué a veces es obligatorio

```bash
./setup.sh arrancar --docker
```

Levanta Postgres, NATS y Redis de verdad, que es lo que hay en producción. La
diferencia **no es cosmética**: el Postgres embebido corre como superusuario, y
un superusuario **se salta las políticas de Row-Level Security aunque estén en
FORCE**. Un fallo de aislamiento entre tenants solo se reproduce fielmente aquí.

Para programar, el modo local basta y es mucho más rápido.

## Datos de demostración

```bash
./setup.sh demo
```

Crea un tenant `demo` con un plan, un administrador y la configuración inicial.
Imprime las credenciales al terminar.

## Primer recorrido

```bash
# 1. Entrar
TOKEN=$(curl -sX POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo.example.com","contrasena":"demo-contecrm-2026","tenant":"<id-del-tenant>"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Ver quién eres y qué puedes hacer
curl -s http://localhost:8080/api/v1/auth/me -H "Authorization: Bearer $TOKEN"

# 3. Crear un objeto propio del tenant, sin tocar el esquema de nadie
curl -sX POST http://localhost:8080/api/v1/metadata/objetos \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"nombre":"proyecto_obra","etiqueta":"Proyecto de obra"}'

# 4. Preguntar si unos datos serían válidos ANTES de enviarlos
curl -sX POST http://localhost:8080/api/v1/metadata/objetos/proyecto_obra/validar \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"datos":{"importe":-5}}'
```

La cuarta llamada es la que enseña de qué va esto: el sistema responde **qué
está mal y por qué**, con los mismos errores que daría al guardar, para que
cualquier frontend pueda enseñarlos sin reimplementar las reglas.

## Otros comandos

| Comando | Qué hace |
|---|---|
| `./setup.sh estado` | Qué está corriendo y si responde |
| `./setup.sh parar` | Para los servicios (los datos se conservan) |
| `./setup.sh migrar` | Aplica las migraciones de los ocho servicios y RLS |
| `./setup.sh gates` | Corre los gates locales, que aquí sustituyen a la CI |
| `tail -f var/log/<servicio>.log` | Los logs de un servicio |

## Si algo no arranca

**Un servicio dice «vivo pero NO listo».** El proceso responde pero algo de lo
que depende no está. Mira su log: el `/health/ready` dice exactamente qué
comprobación falla.

**Todos fallan al conectar con la base.** Borra `var/pgdata` y vuelve a
arrancar: el Postgres local se reinicializa solo.

**Un puerto está ocupado.** Los puertos se resuelven en `setup.sh`
(`puerto_de`); cámbialos ahí o para lo que los esté usando.

## Siguientes pasos

- **Qué puede hacer cada perfil** → [Manual II](manual-2-perfiles.md)
- **Qué sabe hacer el sistema**, capacidad por capacidad → [Manual III](manual-3-funcionalidades.md)
- **Configurarlo y operarlo** → [Manual IV](manual-4-configuracion.md)
- **Cómo está construido y por qué** → [Manual V](manual-5-arquitectura.md)
- **Contribuir** → [Gates locales](QUALITY_GATES.md). Empieza por ahí: los
  gates solo protegen si los instalas.
