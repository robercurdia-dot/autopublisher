# Fase 0 — Validación de la API de fal

**Objetivo:** confirmar que fal se comporta igual que Flashboards antes de escribir nada serio.
**Criterio de salida:** calidad equivalente a lo que salía por Flashboards.

## Qué hace exactamente

Reproduce el clip de Jack Daniel's que salió bien el 05/09/2026 por Flashboards,
cambiando **una sola variable: el proveedor**. Mismo video de referencia, misma foto de
botella, mismo prompt, mismos parámetros.

No se añade el bloque de "product accuracy" de `flashboards_audio_labios_y_producto.md`
a propósito: no formaba parte de la tirada validada, y además describe el cono al revés
(ver nota abajo).

## Antes de correrlo

```bash
pip3 install fal-client
echo 'FAL_KEY=tu-clave' > .env        # la clave sale de fal.ai/dashboard/keys
```

## Correrlo

```bash
python3 validar_fal.py
```

Ensayo: sube las referencias al CDN de fal (gratis), imprime el payload exacto y el coste
estimado, y **para**. No cobra nada.

```bash
python3 validar_fal.py --confirmar
```

Dispara de verdad. ~$1,81. Deja el clip, la metadata y los frames de QA en `runs/<fecha>/`.

## Lo que hay que mirar al salir

1. Silueta y proporción del topper (es una **pantalla de lámpara: ancha arriba, estrecha
   abajo**, no un cono al revés ni una cúpula).
2. Negro mate sin brillo.
3. Luz cálida por debajo de la tapa.
4. Etiqueta de Jack Daniel's nítida y legible.
5. Que **no** haya salido el rótulo quemado del video fuente.
6. El **cargo real** en el panel de fal, no el estimado.

## Diferencias de fal frente a Flashboards (verificadas el 11/09/2026)

| | Flashboards | fal |
|---|---|---|
| Nombres de parámetros | `image_urls`, `video_urls`, `duration`, `aspect_ratio`, `resolution`, `generate_audio` | **idénticos** |
| Límites de referencias | 9 img / 3 vid / 3 audio | **idénticos** |
| `generate_audio` por defecto | `true` (trampa) | `true` (misma trampa) |
| Subir un vídeo | a mano, arrastrando al board | `fal_client.upload_file()` |
| Precio de 10 s 720p con vídeo ref | $2,26 (suma la duración del adjunto) | **~$1,81** (multiplica la tarifa por 0,6) |
| Doble `prepare` | invalida el disparo | no existe ese paso |
| Descargar el output | botón Download del board (R2 bloqueado) | URL directa |

**Pendiente de comprobar en el primer disparo:** fal documenta que las referencias se
citan en el prompt con `@Video1` / `@Image1`. El prompt validado las nombra en prosa
("the reference video", "the reference image"). Si el resultado ignora las referencias,
la primera corrección es anclar con `@Video1` / `@Image1` — y solo eso, una variable a la vez.
