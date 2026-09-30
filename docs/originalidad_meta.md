# Originalidad en Meta — cómo no caer en "contenido no original"

## Lo que dice Meta

- Desde el **30 abr 2026**, las cuentas que publican sobre todo contenido ajeno **dejan de
  recomendarse a no seguidores**. Es original lo que grabas o haces tú, o lo ajeno transformado de
  verdad: texto propio, edición creativa, voz, comentario ([Tubefilter](https://www.tubefilter.com/2026/04/30/instagram-removes-algorithm-recommendations-repost-content-aggregator/),
  [PetaPixel](https://petapixel.com/2026/04/30/new-instagram-policies-target-reposted-content/)).
- **No basta**: cambiar la velocidad, recortar o poner el crédito del autor original.
- Facebook **detecta duplicados automáticamente** y les baja la distribución
  ([PPC Land](https://ppc.land/facebook-introduces-stronger-measures-against-unoriginal-content-creators/)).
- Meta **no publica umbrales**. Los "70 %", "coseno 0,75" o "90 días" que circulan salen de blogs.

## Lo que medimos nosotros (14 sep 2026)

Similitud visual con `lemon_art_negro` (dHash, mejor coincidencia por fotograma):

| Comparación | Estructura |
|---|---|
| sí misma | 1,000 |
| toma casi idéntica | 0,964 |
| otro reel, mismo set | 0,718 |
| otro reel, otro set | 0,631 |
| **nuestro run 01** | **0,598** |

El run 01 se parece a su referencia **menos** que dos reels distintos de la competencia entre sí.
La deriva de escena que parecía un defecto es lo que lo aleja. Lo que lo delataba era el **audio
idéntico** y el **caption copiado**.

Es un proxy grueso: un modelo de embeddings vería más parecido semántico (mismo producto, misma
acción) que un dHash. Para afinarlo haría falta un modelo tipo CLIP, que hoy no está instalado.

## El principio

**Anclar lo que vende, variar lo que identifica.**

| Se copia | Se cambia siempre |
|---|---|
| El concepto y la estructura en tres actos | La habitación, el decorado, el escenario |
| El ritmo de cortes | El encuadre y los ángulos |
| Las acciones que resuelven objeciones (varilla, botón) | Las botellas |
| El producto, idéntico al real | El audio: propio o Meta Sound Collection |
| | El caption: escrito nuevo |
| | Una capa propia: texto en pantalla o voz |

## Herramientas

- `ingesta/originalidad.py` — puerta antes de publicar: vídeo, audio y caption contra la
  referencia y la biblioteca. Sale con error si algo FALLA.
- `fase0/prompts/plantilla_estructura.txt` — prompt que toma la estructura y no la escena.
  Sustituye al "recreate shot for shot" del run 01. **Sin probar todavía**: cuesta un disparo.
