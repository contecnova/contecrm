# Accesibilidad (WCAG 2.2 AA)

Esta página dice **qué cumple hoy** la interfaz que viene con el producto, **cómo
se comprueba** y **qué no cumple todavía**. Es una auditoría, no una declaración
de intenciones: una página de accesibilidad que solo dice «cumplimos WCAG AA» no
la puede usar nadie para decidir nada, y es lo primero que pide un pliego público.

## Qué se comprueba solo

La accesibilidad se rompe al mes siguiente de arreglarla si nadie la vuelve a
mirar, así que aquí no se audita una vez: **corre en el preflight, con la suite
del front**.

**Lo que caza `eslint-plugin-jsx-a11y`**, con la configuración recomendada
completa: imágenes sin texto alternativo, manejadores de ratón sobre elementos que
no son interactivos, `tabindex` positivos, roles inventados, etiquetas sin control
asociado. Está activado como **error**, no como aviso: un aviso que no rompe nada
se acumula.

**Y lo que no caza, que es lo que de verdad hace inutilizable una pantalla**
(`src/pruebas/accesibilidad.test.ts`):

| Comprobación | Por qué importa |
| --- | --- |
| Toda pantalla tiene un `h1` | Quien navega con lector salta por encabezados; sin uno de primer nivel, la única forma de saber dónde está es leerlo todo |
| Todo campo tiene etiqueta asociada, envolvente o `aria-label` | Un `placeholder` no es una etiqueta: desaparece al escribir y muchos lectores no lo anuncian |
| Lo que cambia al pulsar se anuncia (`role="status"`) | Si al pulsar «calcular» aparece un resultado y nada lo dice, quien no ve la pantalla no se entera de que ha pasado algo |
| Las cabeceras de tabla llevan `scope` | Sin él, un lector no sabe si una celda de cabecera describe su columna o su fila |
| El color nunca va solo | Es el fallo más común en un panel: rojo y verde sin texto. Uno de cada doce hombres ve dos celdas idénticas |

Estas cinco comprobaciones **encontraron fallos reales al escribirse**, no
hipotéticos: tres pantallas cambiaban su contenido al pulsar un botón sin
anunciarlo, y la lista de un módulo se recargaba en silencio.

## Qué cumple hoy

Contra los criterios de la WCAG 2.2 nivel AA que aplican a una aplicación de
gestión:

| Criterio | Estado | Cómo |
| --- | --- | --- |
| 1.1.1 Contenido no textual | Cumple | Toda imagen lleva `alt`; los iconos decorativos van con `aria-hidden` |
| 1.3.1 Información y relaciones | Cumple | Tablas con `scope`, formularios con `label`, encabezados jerárquicos |
| 1.4.1 Uso del color | Cumple | Comprobado: ningún estado se distingue solo por color |
| 1.4.3 Contraste mínimo | Cumple | La paleta se define en tokens con contraste ≥ 4,5:1 sobre el fondo, en los dos temas |
| 1.4.11 Contraste de elementos no textuales | Cumple | Bordes e indicadores de foco a ≥ 3:1 |
| 2.1.1 Teclado | Cumple | No hay interacción exclusiva de ratón; lo comprueba el linter |
| 2.4.1 Evitar bloques | Cumple | Enlace «saltar al contenido» como primer elemento enfocable |
| 2.4.3 Orden del foco | Cumple | El orden del DOM es el orden visual; no se usan `tabindex` positivos |
| 2.4.7 Foco visible | Cumple | Anillo de foco propio, no el del navegador suprimido |
| 2.5.8 Tamaño del objetivo (2.2) | Cumple | Los objetivos interactivos tienen 24 px de lado como mínimo |
| 3.1.1 Idioma de la página | Cumple | `lang` declarado y cambiado con el idioma del usuario |
| 3.3.1 Identificación de errores | Cumple | El error dice qué campo y por qué, con texto además del color |
| 3.3.2 Etiquetas o instrucciones | Cumple | Comprobado en el preflight |
| 4.1.2 Nombre, función, valor | Cumple | Componentes nativos; los roles se comprueban con el linter |
| 4.1.3 Mensajes de estado | Cumple | `role="status"` en lo que cambia sin recargar |

## Qué NO cumple todavía

Esta sección es la que hace útil el documento. Lo que está aquí **está aquí a
propósito**, no por olvido:

**1.4.10 Reflujo a 320 px con zoom al 400 %.** Las pantallas se adaptan al móvil,
pero las **tablas anchas siguen necesitando desplazamiento horizontal**. Una tabla
de ocho columnas a 320 px no cabe de ninguna manera, y las alternativas
—convertirla en tarjetas apiladas— hacen que comparar filas, que es para lo que
existe una tabla, deje de ser posible. Lo que hay hoy: la tabla se desplaza dentro
de su contenedor y no arrastra la página entera.

**2.4.11 Foco no oscurecido.** Con la cabecera fija en pantallas cortas, un
elemento enfocado en la parte superior del contenido puede quedar parcialmente
tapado al llegar a él con el tabulador.

**1.2.x Audio y vídeo.** No aplica: la interfaz no incluye contenido multimedia. Si
un tenant incrusta vídeo en un artículo de conocimiento, los subtítulos son suyos
— y conviene decirlo en el pliego en vez de dejarlo implícito.

**3.2.6 Ayuda consistente (2.2).** La ayuda en producto existe y está en el mismo
sitio en todas las pantallas, pero **no todas tienen capítulo asociado**: las que
no lo tienen lo dicen en vez de llevar al índice.

## Lo que depende de quien despliega

Tres cosas que esta interfaz no puede garantizar sola y conviene saber:

- **El contraste de la marca.** Si un tenant configura su paleta corporativa, los
  colores son los suyos. El producto avisa cuando la combinación baja del mínimo,
  pero no la bloquea: un cliente puede tener razones para asumirlo, y lo que sí
  hace falta es que sea una decisión y no un accidente.
- **Los contenidos del tenant.** Un artículo de conocimiento escrito sin
  encabezados o un documento adjunto sin capa de texto no los arregla la interfaz.
- **Y la interfaz propia.** Si se sustituye el front de referencia —que es
  legítimo y está previsto—, esta auditoría deja de aplicar a lo que se ponga en su
  lugar.

## Cómo probarlo tú

```bash
cd frontend && npm run verificar     # linter de accesibilidad + comprobaciones + build
```

Y a mano, que es lo que de verdad encuentra cosas:

1. **Con el tabulador**, de arriba a abajo, sin tocar el ratón. Si se puede hacer
   todo lo de la pantalla, va bien.
2. **Con el zoom al 200 %.** Nada debe desaparecer ni solaparse.
3. **Con un lector de pantalla** —VoiceOver en macOS, NVDA en Windows— abriendo una
   ficha y guardando un cambio. Es la prueba que más cosas encuentra y la que menos
   se hace.
