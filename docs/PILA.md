# La pila: lo que queda por hacer

> **Qué es esto.** La lista única de lo pendiente en contecrm, en el orden en
> que se construye. Se trabaja siempre desde aquí: lo que se pide entra aquí,
> lo que se termina sale de aquí con su commit, y lo que se descubre a medias
> se apunta aquí en vez de quedarse en una conversación.
>
> Cada entrada dice **lo medido** —qué hay hoy, comprobado— y **lo que falta**.
> El orden lo decide el valor: primero lo que se ve y se usa cada día, después
> lo que abre ventas, al final lo que depende de otros.

Última revisión: 09-11-2026.

## En curso

### 1. Los estados se leen como texto, no como código

- **Pedido**: 08-11-2026 («los estados salen en crudo»). Decidido por
  formulario: declarar las listas, no adivinarlas en la pantalla.
- **Hecho**: cada servicio publica en su contrato (`components.x-opciones`)
  las listas de sus columnas y los estados de sus máquinas; la pantalla las usa
  para escribir «Abierta» en vez de «abierta». Primera familia declarada:
  presupuestos, contratos, suscripciones, pedidos, lecciones, actividades
  (estado y prioridad) y casos (estado y prioridad). Los casos no validaban su
  estado —aceptaban cualquier texto— y ahora sí.
- **Falta**: el resto de familias. Medido: de 208 campos de estado, tipo o
  motivo en los contratos, 12 declaraban su lista antes de empezar.
- **Abierto a propósito**: el `tipo` de actividad y el de caso entran también
  por plantillas y no son una lista cerrada hoy. Se resuelve con la entrada 2
  (que los defina el administrador).

## Siguientes, por orden

### 2. Todo configurable por el administrador: metodologías, embudos, etapas y estados

- **Pedido**: 09-11-2026 — «no veo dónde definir las metodologías ni los
  estados, cómo se llaman, qué tipos hay o cuántos hay, por ejemplo en
  oportunidades o en el embudo; debería ser todo superconfigurable,
  absolutamente todo, por administradores».
- **Medido**:
  - Embudos (`pipelines`) y etapas: se crean por API —con criterios de
    salida por etapa—, pero en pantalla sólo hay una tabla genérica
    («Procesos de venta», dentro de Oportunidades). No hay un editor de
    embudo: ordenar etapas, probabilidad, criterios, colores.
  - Metodologías: sólo se listan; no se pueden crear ni editar.
  - Estados: están escritos en el código (máquinas de lead y oportunidad, y
    tuplas en el resto). El tenant sólo puede **quitar** transiciones; no
    puede renombrar, añadir, ordenar ni decir cuántos hay.
- **Decidido por formulario (09-11-2026)**:
  - Estados: **todo** configurable por objeto —añadir, renombrar, ordenar,
    color, cuáles son finales y a cuáles se puede pasar desde cada uno—. El
    producto sigue sabiendo qué significa cada final (ganado, perdido,
    cerrado) para la previsión, las comisiones y el SLA.
  - Metodologías: **preguntas por etapa** (MEDDIC, BANT…) con puntuación,
    **pasos y playbook por etapa**, y **varias metodologías por embudo**.
- **Se construye en este orden**: (a) estados y transiciones como
  configuración del tenant, con los de fábrica como punto de partida; (b) el
  editor de embudos y etapas; (c) las metodologías; (d) todo ello en una
  sección de Administrar.
- **(c) hecho el 09-11-2026**: Administrar › Plataforma › Metodologías y
  playbooks —MEDDIC, BANT, SPIN, Challenger o propia, por embudo; pregunta,
  peso y desde qué etapa; pasos por etapa— y los criterios se marcan desde la
  ficha de la oportunidad.
- **(b) hecho el 09-11-2026**: Administrar › Plataforma › Embudos y etapas —
  crear embudos; nombre, probabilidad, color, estancamiento, final y ganada,
  criterios de salida, orden y quitar etapas moviendo sus oportunidades—.
- **(a) hecho el 09-11-2026** para lead y oportunidad: Administrar ›
  Plataforma › Estados de los objetos, el desplegable de estado en la cabecera
  de la ficha y el código preguntando por el significado. Falta extenderlo a
  los objetos que hoy guardan su estado en una tupla —casos, presupuestos,
  pedidos…—, dándoles máquina; con eso se cierra también la entrada 1.
- **Caso, hecho el 09-11-2026**: máquina configurable, el SLA para el reloj
  por significado («en pausa») y cerrar/reabrir desde el estado pasan por su
  camino. Medido: de más de 50 tuplas de estados, la mayoría son del sistema
  (trabajos, sagas, firmas, cargas) y no se configuran; las de negocio que
  quedan son actividad, presupuesto y contrato.
- **Actividad, hecho el 09-11-2026**: máquina configurable; vencidas,
  recordatorios, abiertas de la cuenta y salud del cliente por significado.
- **Presupuesto y contrato, hecho el 09-11-2026** (con estados propios,
  decidido por formulario). De paso, la aprobación del presupuesto, que no se
  podía resolver: ahora la abre orchestrator y sales aplica lo decidido.
  **Pendiente de ver en vivo**: el viaje por el bus, porque la pila local de
  procesos corre sin NATS. Con esto queda cerrada la entrada 2(a); la
  entrada 1 (listas legibles) queda cubierta para los objetos de negocio.

### 3. Las gráficas se leen al pasar el ratón — hecho el 09-11-2026

La forma de barras horizontales tenía encima la capa de puntería de las
columnas, en franjas verticales, y el ratón caía en la franja equivocada o en
ninguna; y la gráfica se dibujaba a 640 de ancho fijo, con lo que en una
tarjeta la letra se veía de 8,6 px. Ahora cada fila es su zona —también con el
teclado—, se resalta la señalada con su emergente y la gráfica mide su sitio.

### 4. Un GRC mucho más potente — hecho el 09-11-2026

- **Pedido**: 09-11-2026 — «el GRC debe ser mucho más potente, pudiendo llegar
  a tener un DEM o TCSEC como los que tiene Infor en sus herramientas».
- **Medido**: hoy hay riesgos, controles, cobertura del catálogo y
  segregación de funciones (CRM-07.03).
- **Aclarado por formulario (09-11-2026)**: «DEM» es la **matriz de
  segregación de funciones** —reglas de conflicto entre permisos y roles, con
  detección y mitigación—. De TCSEC, las tres partes: **clasificar la
  instalación por nivel** (D, C1, C2, B1…), **los controles exigidos por
  nivel** con sus evidencias y su comprobación automática donde se pueda, y
  **un informe exportable para auditoría**.
- **Hecho el 09-11-2026, la matriz de segregación**: pantalla en Administrar ›
  Gobierno y cumplimiento › Segregación de funciones con la matriz de reglas
  contra roles, el editor de reglas, quién está en conflicto con su excepción,
  el simulador «qué pasa si le doy este rol» y siete reglas de serie. Quitados
  los dos trozos que contestaban lo mismo (Seguridad y la pestaña de
  Cumplimiento); el de Seguridad no marcaba nunca la excepción.
- **Hecho el 09-11-2026, TCSEC**: pantalla en Administrar › Gobierno y
  cumplimiento › Clasificación TCSEC (CRM-07.03.02.11) con 15 requisitos de C1
  a A1 —11 medidos sobre el sistema, 4 atestiguados en el GRC—, el nivel
  alcanzado y el informe descargable. La pila local sale en D porque conecta
  como SUPERUSER.
- **Queda abierto, y se dice en la pantalla**: el control obligatorio de
  escritura por etiquetas (no copiar un dato a un nivel más bajo) no existe;
  sin él no hay B1. Construirlo es un bloque propio; sólo si se pide.

### 5. Las 41 capacidades críticas, alcanzables desde una pantalla

Declaradas hechas y con prueba; lo que no está medido es que un usuario llegue
a ellas. Se recorren una a una, como se hizo con lecciones.

### 6. Las 82 capacidades sin pantalla

El tope del guardián (`TOPE_SIN_PANTALLA`) está en 82. Bajan por familias.

### 7. Lo que el PATCH genérico ofrece y escribe el sistema

De 357 campos, 34 se cerraron el 08-11-2026 (hashes, sellos, contadores,
derivados). Quedan 323 que el código también escribe pero corrige una persona
—estado, notas, plazos—; se revisan por familia sólo si aparece un caso real.

## Dependen de otros

### 8. Apps móviles y complemento de correo

CRM-04.04.01.03, CRM-06.01.01.02 y CRM-06.02.01.03 están `en-curso`: existe
el servidor que necesitan; no hay ninguna app ni complemento.

### 9. contecmind no construye su imagen

`pillow>=13` (cierra 24 CVE) choca con `fastembed`, que en Python 3.12 exige
`pillow<13`. Se decide en su repositorio; mientras, la parte documental de
contecrm está degradada.

## Del usuario

- Rotar la clave de la API de Google.
- Revisar `exigir_opt_out` en el tenant de plataforma.
