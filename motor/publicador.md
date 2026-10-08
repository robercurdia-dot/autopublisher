# Publicador de la cola → YouTube Studio

Instrucciones para la tarea programada que publica los clips que la suite deja en
la cola. La tarea conduce **Chrome con la sesión de Roberto** (Claude in Chrome), la
misma vía que se usó a mano el 8 oct. No se usa la API de YouTube: los vídeos subidos
con `videos.insert` desde un proyecto sin verificar quedan privados.

Canal: **ClipperZero** · `UCZjfgv3NmW68ikiMS1wIkrQ` (I mayúscula antes de «krQ»).

## Qué hacer en cada pasada

1. Lee la cola: `~/lampara-engine/motor/cola_publicacion.json`. Trabaja solo con los
   elementos en `"estado": "pendiente"` cuya hora (`cuando`, hora de Madrid) sea
   **posterior a ahora**. Si alguno ya ha pasado sin subirse, márcalo `fallido` con la
   nota «la hora pasó sin publicarse» y sigue.
2. Por cada uno, en orden de `cuando`:
   1. Copia `subir` (ya pesa menos de 9 MB) a tu carpeta de trabajo: la subida por
      Chrome solo admite ficheros que la sesión pueda leer y de menos de 10 MB.
   2. Abre `https://studio.youtube.com/channel/UCZjfgv3NmW68ikiMS1wIkrQ/videos/upload?d=ud`,
      localiza el `input type=file` con `find` y súbelo con `file_upload`.
   3. **Espera unos 10 s** a que aparezca el formulario de detalles. Si escribes antes,
      el texto se pierde.
   4. Título: pincha el campo, `cmd+a`, escribe `titulo`. Descripción: pincha el campo
      y escribe `descripcion`. **No pulses Escape nunca**: cierra el diálogo.
      Comprueba con una captura que los dos han entrado.
   5. Marca «No, no es contenido creado para niños» y **comprueba con un zoom** que ha
      quedado marcado: a veces el clic no entra.
   6. «Siguiente» tres veces hasta «Visibilidad». Despliega «Programar».
   7. Hora: localiza con `find` el campo de hora, triple clic sobre él y escribe la hora
      en formato `9:00 a.m.` / `1:00 p.m.`, y Enter.
   8. Zona horaria: abre «Zona horaria» y elige **«(GMT+0200) Hora local»** (Madrid en
      horario de verano; en invierno será GMT+0100). Sin esto puede quedar en otra zona.
   9. Fecha: abre el selector de fecha y elige el día de `cuando`.
   10. **Verifica con un zoom** que fecha, hora y zona son las correctas. Pulsa
       «Programar».
   11. El diálogo de confirmación muestra el enlace del Short. Llama a la herramienta
       `actualizar_cola` del motor o, si no la tienes, edita el JSON: `estado: "programado"`
       y `url` con el enlace.
3. Si algo falla en un elemento, márcalo `fallido` con una nota corta del motivo y pasa al
   siguiente. Si la subida quedó a medias, aparecerá como **borrador** en
   Contenido → Shorts: termínalo desde ahí («Editar borrador») en vez de subirlo otra vez.
4. Al acabar, borra las copias de tu carpeta de trabajo.

## Límites

- No publiques nada que no esté en la cola, ni cambies títulos o fechas.
- No toques vídeos ya publicados del canal.
- Si Chrome no responde, no reintentes en bucle: deja los elementos en `pendiente` para la
  siguiente pasada.
