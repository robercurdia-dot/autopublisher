# Catálogo de marcas

`brands.json` es la fuente única. Añadir una marca = una entrada + una foto. Cero código.

## Qué es esto realmente

No es "el catálogo de marcas". Es una **biblioteca de bloques de cambio**, que hoy son todos de
botella porque la botella es el elemento recurrente del contenido que hacemos ahora.

El motor no sabe de botellas: recibe un vídeo de referencia, unas imágenes, y un prompt que dice
en prosa qué se mantiene y qué cambia. El `bloque_botella` **es** ese bloque de cambio. Si mañana
lo recurrente es otra cosa, se escribe otro bloque con otra foto y el motor no se entera.

## Procedencia — se registra, no se prohíbe

Cada asset lleva un campo `procedencia` con uno de cuatro orígenes:

| Origen | Cuándo | Riesgo |
|---|---|---|
| `propia` | Botella tuya, fotografiada por ti | Ninguno. Es lo que hace la cuenta de referencia |
| `web` | Búsqueda web: captura de pantalla o descarga | **Solo en la etiqueta.** Para forma, color, decorado y escena va bien |
| `proveedor` | Catálogo de CJ | Las fichas de cotas no sirven; solo fotos reales |
| `generada` | Que el modelo invente la etiqueta | Cerrado: sale ilegible siempre |

El punto medido por el nodo de inteligencia es estrecho y conviene no ampliarlo de más:
**reproducir la etiqueta de una marca a partir de un asset de marketing sale ilegible**, y lo
ilegible es el fallo que delata un clip generado al instante. Todo lo demás que se ancle con una
imagen de la web funciona.

La vía de búsqueda está en el nodo `Pic Reff`: buscar, capturar la página o bajar el archivo, y
anotar de dónde salió. En local no hay proxy de por medio, así que `curl` basta.

## Las fotos

Solo está la de Jack Daniel's. Faltan once.

No hacen falta URLs públicas: fal las sube con `upload_file` desde disco. Requisitos:

- Foto real del producto, botella entera, fondo limpio.
- Etiqueta legible — es lo que el modelo tiene que reproducir.
- Si se puede, luz cálida. Una foto de estudio en blanco frío choca con la escena cálida del vídeo y el objeto deriva. Jack Daniel's va en estudio frío y aun así salió bien, así que no es descalificante, solo peor.

## Los dos flujos

**A — réplica directa.** Vídeo de referencia y poco más: replica el clip variando el decorado.
**No toca la botella**, así que no usa esta biblioteca. Cero decisiones tuyas.

**B — pieza a medida.** Aquí entra esta biblioteca: eliges botella, escribes guión, se monta la voz.
El ensayo sin `--confirmar` es el punto de intervención — imprime el prompt completo, lo editas,
vuelves a lanzar.

En la tabla `jobs` esto es una columna `modo` junto a `prompt_version`, que ya estaba en el esquema acordado. No son dos motores, es el mismo con la puerta abierta o cerrada.
