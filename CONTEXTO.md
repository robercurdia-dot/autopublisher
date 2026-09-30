# Motor fijo, contexto variable

El motor no sabe qué vende. Recibe un vídeo de referencia, unas imágenes y un prompt con la
estructura **identidad → cambio → acción → negativos**, y devuelve un clip. Eso no cambia.

Todo lo demás es relleno de esa estructura, y vive en un solo sitio: **`contexto.json`**.

```
contexto.json          ← lo único que se toca al cambiar de producto
  producto             qué se vende, y qué no puede derivar nunca
  atrezzo              sobre qué se enseña, y dónde está esa biblioteca
  negativos            qué prohibir siempre
  referencia           de qué cuenta bajamos vídeos
  publicación          dónde se publica

assets/videos.json     qué clips hay y qué variante de producto sale en cada uno
marcas/brands.json     la biblioteca de atrezzo de hoy (botellas)
```

## Qué es producto y qué es atrezzo

Hoy vendemos una **lámpara-topper LED** que convierte cualquier botella en lámpara de mesa.
Las botellas son el soporte, no la mercancía.

Eso fija la prioridad del QA: **el producto no puede derivar**. Si una etiqueta de atrezzo sale
floja, es un objeto borroso sobre una mesa. Si el topper sale como una cúpula, el clip no vende.

Y explica por qué el formato ganador desfila botellas: tres distintas en cuatro segundos son la
propuesta de valor puesta en imagen — *encaja en cualquiera que tengas*. La variedad es el
argumento, no la decoración.

## Cambiar de producto

Editar `contexto.json`: producto, atrezzo, negativos, cuenta de referencia. El motor, el esquema
de `jobs` y el board se quedan como están.
