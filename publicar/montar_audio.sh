#!/usr/bin/env bash
# montar_audio.sh — pega una pista de audio sobre el clip generado.
#
# El generador devuelve SIEMPRE vídeo mudo (generate_audio va forzado a false).
#
#   bash montar_audio.sh clip.mp4 musica/pista.mp3 salida.mp4   <- recomendado
#   bash montar_audio.sh clip.mp4 lemon_art_negro salida.mp4    <- audio de la referencia (riesgo)
#
# Por qué no el audio de la referencia: Rights Manager saca la huella de cada subida y
# puede silenciar, retirar o penalizar la cuenta; las cuentas business solo tienen licencia
# para Meta Sound Collection; y reusar el audio de otra cuenta es la señal más clara de
# contenido no original, que desde el 30 abr 2026 pierde recomendaciones.

set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ $# -eq 3 ] || { echo "Uso: bash montar_audio.sh <clip.mp4> <archivo_audio | id_referencia> <salida.mp4>"; exit 1; }
CLIP="$1"; FUENTE="$2"; OUT="$3"
[ -f "$CLIP" ] || { echo "No existe el clip: $CLIP"; exit 1; }

if [ -f "$FUENTE" ]; then
  AUDIO="$FUENTE"
else
  AUDIO="$REPO/assets/audio/$FUENTE.m4a"
  [ -f "$AUDIO" ] || { echo "No hay audio de '$FUENTE'. Pásalo antes por ingesta/analizar_referencia.py"; exit 1; }
  echo "AVISO: audio sacado de la referencia '$FUENTE' (cuenta ajena)."
  echo "       Riesgo de silenciado o retirada por Rights Manager y de contenido no original."
  echo "       Preferible: pista de Meta Sound Collection o locución propia."
fi

dur() { ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$1"; }
printf "vídeo %.2f s · audio %.2f s\n" "$(dur "$CLIP")" "$(dur "$AUDIO")"

# -c:v copy no recodifica. -movflags +faststart pone el moov al principio: sin eso
# el clip no se reproduce en streaming hasta bajarlo entero.
ffmpeg -v error -y -i "$CLIP" -i "$AUDIO" \
  -c:v copy -c:a aac -b:a 128k -map 0:v:0 -map 1:a:0 -shortest \
  -movflags +faststart "$OUT"

printf "listo: %s · %.2f s\n" "$OUT" "$(dur "$OUT")"
