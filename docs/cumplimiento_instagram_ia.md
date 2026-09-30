# Cumplimiento — Instagram, IA, audio y marcas

Investigación del 14 sep 2026, a raíz de que la cuenta pasó de 7 publicaciones a 2.
**No es asesoría legal.** Para campañas pagadas o uso intensivo de marcas ajenas, abogado.

## Lo que sabemos y lo que no

- **No sabemos por qué desaparecieron los posts.** La API devuelve el mismo error si los
  borraste tú o si los retiró Instagram. La única forma de saberlo es **Configuración →
  Estado de la cuenta** en la app: ahí salen el contenido retirado, el motivo, las
  restricciones y si la cuenta sigue siendo recomendable, con opción de apelar
  ([Instagram](https://about.instagram.com/blog/announcements/instagram-outages-and-account-status)).
- **El audio no explica el post mudo**: no tenía pista de audio y también desapareció.
- **La etiqueta de IA no explica nada**: el retirado llevaba marca C2PA de IA y el
  superviviente no. No hay base para decir que etiquetar evita retiradas.
- **Publicar por la API oficial está permitido** y no es causa probable
  ([Mixpost](https://mixpost.app/blog/automate-instagram-posts-safely)).

## Los riesgos del flujo, de mayor a menor

### 1. Obligación legal de avisar que es IA — en vigor

Art. 50 del Reglamento europeo de IA, **aplicable desde el 2 ago 2026**
([Comisión Europea](https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act)):

- "Deepfake" incluye **objetos y lugares**, no solo personas. Un vídeo realista de manos,
  botellas y una habitación entra si puede parecer auténtico.
- Quien publica con fines comerciales es **responsable del despliegue**: nos aplica.
- **El marcado legible por máquina no basta**: "deployers cannot simply rely on the
  machine-readable marking". El aviso tiene que ser **visible o audible**, sin herramientas.
- No hay exención para publicidad. Multas de hasta **15 M€ o el 3 %** de facturación.

En España, el Proyecto de Ley Orgánica de IA **no está en vigor**: sigue en comisión desde
junio de 2026 ([Congreso](https://controlcongreso.com/iniciativas/congreso-aprueba-ley-uso-responsable-gobernanza-ia-121000096/)).
Da igual para esto: el reglamento europeo aplica directamente.

### 2. Audio de la cuenta de referencia

- Rights Manager **saca la huella de cada subida**, incluidos sonidos cortos de fondo, y puede
  silenciar, retirar o penalizar la cuenta ([Foxi](https://www.foximusic.com/blog/instagram-reels-music-copyright-legal-guide/)).
- **Las cuentas business solo tienen licencia para Meta Sound Collection**.
- Meta Sound Collection **se puede descargar en MP3** y usar en vídeo editado fuera, con
  licencia comercial **solo para plataformas de Meta** ([Meta](https://www.facebook.com/sound),
  [Shuttergen](https://shuttergen.com/resources/meta-music-library)).

### 3. Contenido no original

Desde el 30 abr 2026, las cuentas que publican sobre todo contenido ajeno **dejan de
recomendarse a no seguidores** ([PetaPixel](https://petapixel.com/2026/04/30/new-instagram-policies-target-reposted-content/),
[Tubefilter](https://www.tubefilter.com/2026/04/30/instagram-removes-algorithm-recommendations-repost-content-aggregator/)).
Cuenta como transformación: **voz propia, texto propio en pantalla, remezcla, comentario**.
Recrear un vídeo ajeno sin repostear el archivo es zona gris no aclarada por Meta, y reusar
su audio es la señal más evidente de que no es tuyo.

### 4. Marcas de terceros en las botellas

En la UE **no existe defensa de "uso incidental"** de marca; usar una marca ajena en material
promocional sin permiso puede infringir el art. 9 del Reglamento de marca de la UE
([Lexology](https://www.lexology.com/library/detail.aspx?g=165f13fc-634d-407e-b0a7-9d54c4a8786c)).
Una etiqueta de Fernet-Branca o Jack Daniel's en el anuncio de nuestro producto sugiere una
asociación que no existe, y encima la reproduce una IA.

### 5. Derechos de autor del vídeo de referencia

La idea y el estilo **no** están protegidos; la expresión concreta **sí**, y en la UE no hay
"fair use" ([JIPLP](https://academic.oup.com/jiplp/article/19/6/541/7633792),
[DLA Piper](https://www.dlapiper.com/en-us/insights/publications/2026/04/ai-and-copyright-major-issues-and-direction-of-travel-in-the-uk-eu-and-china-in-q2-2026/can-ai-generated-content-infringe-pre-existing-copyright-works)).
"Recrear plano a plano" se acerca a copiar expresión; "tomar la estructura" no.

### 6. Alcohol

La lista oficial de productos regulados **no recomendables** en Instagram es tabaco y vapeo,
productos para adultos y fármacos; el alcohol no aparece expresamente
([Instagram](https://help.instagram.com/313829416281232/)). Riesgo bajo para una demo de
lámpara, siempre que no promocione beber ni vender alcohol.

## La solución para el flujo

| Cambio | Estado |
|---|---|
| Etiqueta **visible** quemada en una esquina superior (`publicar/etiquetar_ia.py`) | hecho |
| `is_ai_generated: true` en cada contenedor | hecho |
| `publicar_clip.sh`: montar → **etiquetar** → alojar → publicar | hecho |
| Tabla `jobs`: columna `etiqueta_ia` y **no se aprueba sin ella** | hecho |
| `montar_audio.sh` acepta pista propia y **avisa** si el audio es de la referencia | hecho |
| Audio: Meta Sound Collection o locución propia, nunca el de la competencia | decisión tuya |
| Botellas sin marca reconocible, propias, o con la etiqueta no legible | decisión tuya |
| Prompt: tomar la **estructura** del reel, no "recrear plano a plano" | decisión tuya |
| Texto propio en pantalla o voz propia para contar como transformación | decisión tuya |
| Revisar **Estado de la cuenta** y apelar si hubo retiradas | tú, en la app |

## Dónde va la etiqueta, y por qué

- **Abajo no**: la interfaz de Reels (caption, usuario, botones) la tapa, y tapada no es perceptible.
- **Arriba al centro no**: en estos vídeos el topper baja por ahí. Centrada tapaba la varilla,
  que es el plano del mecanismo — lo único que no se puede tapar.
- **Esquina superior derecha** por defecto, a la altura del 12 % del alto. Comprobado en 4
  momentos del run 01: producto y botón siempre libres; en el último, solapa parte de la mano
  que entra a pulsar.
- Configurable por clip: `POSICION=arriba-izq bash publicar/publicar_clip.sh ...`
  (`arriba-der`, `arriba-izq`, `arriba-centro`). Las manos entran por lados distintos según el
  plano, así que ninguna esquina fija es perfecta para todos los vídeos.

