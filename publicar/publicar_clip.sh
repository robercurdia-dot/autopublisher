#!/usr/bin/env bash
# publicar_clip.sh — del clip generado al link, en un solo paso.
#
# caption -> montar audio -> etiqueta de IA -> ORIGINALIDAD -> alojar -> publicar
# La puerta de originalidad va antes de alojar: si el clip se parece demasiado a su
# referencia (vídeo, audio o caption), no llega ni a subirse.
#
#   bash publicar_clip.sh clip.mp4 musica/pista.mp3 lemon_art_negro "caption propio"
#   ETIQUETA="AI-generated content" POSICION=arriba-izq bash publicar_clip.sh ...
#   VERTIENTE=sin_caras bash publicar_clip.sh ...   <- sin etiqueta quemada

set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$AQUI/.." && pwd)"
CLOUD="${CLOUDINARY_CLOUD:-deszdkw07}"
PRESET="${CLOUDINARY_PRESET:-auto_publisher}"
ETIQUETA="${ETIQUETA:-Contenido generado con IA}"
POSICION="${POSICION:-arriba-der}"
# Piezas con caras: etiqueta quemada + la nativa de Instagram. Sin caras: solo la
# nativa (is_ai_generated, que va siempre en publicar_grid.sh).
# Enmienda «etiqueta_solo_nativa»: no se quema nada por defecto. Con
# ETIQUETA_QUEMADA=si vuelve a pintarse, por si algún día hace falta.
ETIQUETA_QUEMADA="${ETIQUETA_QUEMADA:-no}"

[ $# -eq 4 ] || { echo 'Uso: bash publicar_clip.sh <clip.mp4> <archivo_audio> <id_referencia> "<caption>"'; exit 1; }
CLIP="$1"; AUDIO="$2"; REFERENCIA="$3"; CAPTION="$4"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

echo "== 0/5 · Caption frente al de la referencia =="
if ! python3 "$REPO/fase0/caption.py" revisar "$REFERENCIA" "$CAPTION"; then
  echo
  echo "ABORTADO: el caption no cumple lo aprendido (fase0/enmiendas.json)."
  echo "  Saca el esqueleto con: python3 fase0/caption.py borrador $REFERENCIA"
  exit 1
fi

echo
echo "== 1/5 · Montando audio =="
bash "$AQUI/montar_audio.sh" "$CLIP" "$AUDIO" "$TMP/con_audio.mp4"

echo
if [ "$ETIQUETA_QUEMADA" != "si" ]; then
  echo "== 2/5 · Sin etiqueta quemada =="
  echo "   La declaración va por la red: is_ai_generated=true en el paso 5."
  cp "$TMP/con_audio.mp4" "$TMP/final.mp4"
else
  echo "== 2/5 · Etiqueta visible de IA =="
  python3 "$AQUI/etiquetar_ia.py" "$TMP/con_audio.mp4" "$TMP/final.mp4" --texto "$ETIQUETA" --posicion "$POSICION"
fi

echo
echo "== 3/5 · Originalidad frente a '$REFERENCIA' =="
if ! python3 "$REPO/ingesta/originalidad.py" "$TMP/final.mp4" --referencia "$REFERENCIA" --caption "$CAPTION"; then
  echo
  echo "ABORTADO: se parece demasiado a la referencia. No se sube ni se publica."
  echo "  Audio -> pista propia o de Meta Sound Collection. Caption -> escrito nuevo."
  echo "  Vídeo -> otra escena o encuadre (fase0/prompts/plantilla_estructura.txt)."
  exit 1
fi

echo
echo "== 4/5 · Alojando =="
URL=$(curl -s --max-time 300 -X POST "https://api.cloudinary.com/v1_1/$CLOUD/video/upload" \
      -F "file=@$TMP/final.mp4" -F "upload_preset=$PRESET" \
      | python3 -c "import sys,json; print(json.load(sys.stdin).get('secure_url',''))")
[ -n "$URL" ] || { echo "   Falló la subida a Cloudinary"; exit 1; }
echo "   $URL"

echo
echo "== 5/5 · Publicando (is_ai_generated=true) =="
CLIP_LOCAL="$TMP/final.mp4" bash "$AQUI/publicar_grid.sh" "$CAPTION|$URL"
