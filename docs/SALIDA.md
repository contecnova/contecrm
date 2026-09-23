# Reversibilidad y plan de salida

Este documento dice **cómo se sale de contecrm**: qué se lleva el cliente, en qué
formato, cuánto tarda y qué deja de funcionar. Está escrito con la misma seriedad
que la documentación de entrada, y por una razón práctica: **un cliente que no
sabe cómo salir no acaba de entrar**. En cualquier compra mediana, alguien pregunta
esto antes de firmar; que la respuesta esté escrita y sea comprobable vale más que
cualquier argumento comercial.

También está escrito porque es una obligación razonable: quien contrata un sistema
donde vive su relación con sus clientes tiene derecho a poder llevárselo.

## Lo que se lleva el cliente

**Todo lo suyo.** No una selección:

| Qué | Formato | Dónde |
| --- | --- | --- |
| Datos de negocio | CSV y JSON, uno por objeto, incluidos los campos personalizados | Exportación completa del tenant |
| Configuración | JSON: objetos, campos, layouts, validaciones, automatizaciones, plantillas, reglas de compartición | El mismo paquete que usa la promoción entre entornos |
| Adjuntos y documentos | Los ficheros originales, con su ruta y su relación | Carpeta con manifiesto |
| Actividades e interacciones | CSV/JSON; los correos también en EML | Con su vínculo al registro |
| Auditoría | JSON con la cadena de hashes | Íntegra, para poder demostrar que no se alteró |
| Histórico de cambios | JSON por registro | Quién cambió qué y cuándo |
| Usuarios y permisos | JSON | Sin contraseñas: no se pueden exportar y no se guardan en claro |

**En formatos que no son nuestros.** CSV, JSON, EML, vCard, iCalendar. Lo que se
exporta se abre con una hoja de cálculo o se importa en otro sistema sin pasar por
ninguna herramienta de la casa — que es lo que distingue una exportación de una
copia de seguridad propietaria.

## Lo que no se puede llevar, y por qué

Corto y honesto:

- **Las contraseñas.** Se guardan con un derivado irreversible: no existen en
  claro ni siquiera para nosotros.
- **Las claves de cifrado gestionadas por nosotros.** Si el cliente trae la suya
  (BYOK), la tiene desde el principio; si usa la nuestra, los datos se exportan
  **descifrados** y la clave no se entrega — entregarla no le serviría de nada y
  sí afectaría a la seguridad de los demás.
- **Los datos derivados de modelos**: puntuaciones, salud de cuenta, propensiones.
  Se exportan como números con su fecha, pero **el modelo no viaja**: está
  entrenado con datos agregados y no es del cliente. Las señales de entrada sí
  viajan, que es lo que permite reconstruirlo en otro sitio.

## Cuánto tarda y cómo se comprueba

- **La exportación se pide y se prepara**, no se genera en el momento: un tenant
  grande son horas y una descarga que caduca a la mitad no vale.
- **El plazo comprometido está en el contrato de servicio**, y el tiempo real de
  la última exportación se puede consultar.
- **Y se verifica.** La exportación incluye un manifiesto con el recuento por
  objeto y la huella de cada fichero, y hay un procedimiento para comprobar que lo
  descargado coincide con lo que dice el manifiesto. Una exportación que nadie ha
  verificado tiene el mismo valor que una copia que nadie ha restaurado.

## Qué deja de funcionar al salir

Lo que hay que planificar **antes** de cortar:

1. **Las integraciones salientes.** Webhooks, CDC hacia el lago del cliente y
   sincronizaciones con su suite dejan de mandar. Lo que ya llegó a sus sistemas se
   queda allí.
2. **Las audiencias en plataformas publicitarias.** Dejan de actualizarse y, sobre
   todo, **dejan de propagarse las bajas**: hay que retirarlas en la plataforma o
   seguirá viendo anuncios gente que se dio de baja.
3. **Los enlaces compartidos y los portales de invitado.** Dejan de resolver.
4. **Las firmas electrónicas en curso.** Las completadas tienen su prueba dentro de
   la exportación; las que estén a medias hay que cerrarlas o repetirlas fuera.
5. **Los enlaces a documentos y notas externas** siguen funcionando, porque nunca
   estuvieron aquí: apuntan al almacenamiento del cliente.

## Qué pasa con los datos después

- **Se borran en el plazo acordado**, no «cuando toque»: por defecto, treinta días
  después de confirmar que la exportación está bien, para dejar margen a que el
  cliente detecte que le falta algo.
- **Se borran también las copias de seguridad** cuando expira su retención, y esa
  fecha se dice: una copia con noventa días de retención significa que los datos
  desaparecen del todo noventa días después, no antes, y afirmar lo contrario sería
  mentir.
- **Y se entrega un certificado de borrado** con qué se borró, cuándo y de dónde,
  incluidas las copias y los entornos de pruebas — que es donde más veces se queda
  una copia olvidada.

## Qué no se hace

Dos prácticas del sector que aquí no existen, y conviene que conste:

- **No se cobra por exportar.** La exportación completa es parte del servicio.
  Cobrar por salir convierte la reversibilidad en una barrera con otro nombre.
- **No hay formatos propios ni cifrados.** Nada de lo que se entrega necesita una
  herramienta nuestra para abrirse.

## Cómo se prueba que esto es verdad

La exportación de salida **se puede pedir en cualquier momento**, no solo al
terminar el contrato. La recomendación es hacerlo una vez durante la implantación,
cuando todavía hay confianza y tiempo: es el único momento en el que comprobar el
plan de salida no cuesta nada, y el único en el que descubrir que falta algo tiene
arreglo.
