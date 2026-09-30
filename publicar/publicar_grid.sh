#!/usr/bin/env bash
# publicar_grid.sh — publica un vídeo al grid de Instagram (Fase 0: <1.000 seguidores).
#
# Es el script que la spec y el playbook daban por "la versión correcta para Fase 0"
# y que no existía. Mismo sondeo correcto del contenedor, SIN trial_params.
#
# Uso:
#   CRED_FILE=./credenciales_ig.env bash publicar_grid.sh "CAPTION|URL_VIDEO"
#
# No publica sin que escribas PUBLICAR. Publicar es irreversible y público.

set -euo pipefail

API="https://graph.instagram.com/v25.0"
CRED_FILE="${CRED_FILE:-./credenciales_ig.env}"

[ -f "$CRED_FILE" ] || { echo "No encuentro $CRED_FILE"; exit 1; }
# shellcheck disable=SC1090
source "$CRED_FILE"
: "${IG_USER_ID:?falta IG_USER_ID}" "${ACCESS_TOKEN:?falta ACCESS_TOKEN}"

[ $# -ge 1 ] || { echo 'Uso: bash publicar_grid.sh "CAPTION|URL_VIDEO"'; exit 1; }

ENTRADA="$1"
CAPTION="${ENTRADA%%|*}"
VIDEO_URL="${ENTRADA#*|}"
[ "$CAPTION" != "$VIDEO_URL" ] || { echo "Formato: \"CAPTION|URL_VIDEO\""; exit 1; }

# ---- 0. comprobar la fase de la cuenta, no darla por supuesta ----
echo "== Cuenta =="
CUENTA=$(curl -s "$API/$IG_USER_ID?fields=username,followers_count&access_token=$ACCESS_TOKEN")
echo "   $CUENTA"
SEG=$(echo "$CUENTA" | sed -n 's/.*"followers_count":\([0-9]*\).*/\1/p')
if [ -n "$SEG" ] && [ "$SEG" -ge 1000 ]; then
  echo "   AVISO: $SEG seguidores. Trial reels ya está disponible — quizá quieras"
  echo "   publicar_trial_reels.sh en vez de este script."
fi

# ---- 0-bis. GUARDA: nunca publicar un vídeo mudo ----
# El generador devuelve siempre vídeo sin pista de audio. El run 01 se publicó
# en silencio por saltarse el montaje. Esto lo hace imposible, no improbable.
if [ -n "${CLIP_LOCAL:-}" ] && [ -f "$CLIP_LOCAL" ]; then
  PISTAS=$(ffprobe -v error -select_streams a -show_entries stream=codec_name -of csv=p=0 "$CLIP_LOCAL" || true)
  if [ -z "$PISTAS" ]; then
    echo
    echo "ABORTADO: $CLIP_LOCAL no tiene pista de audio."
    echo "  Móntalo antes:  bash montar_audio.sh \"$CLIP_LOCAL\" <id_referencia> salida.mp4"
    exit 1
  fi
  echo "   audio: $PISTAS"
fi

# ---- 1. contenedor (cuerpo JSON: los captions llevan emojis y comillas) ----
echo
echo "== Creando contenedor =="
CUERPO=$(python3 - "$VIDEO_URL" "$CAPTION" <<'PY'
import json, sys
# is_ai_generated: autodeclaración de IA. Meta la exige para vídeo fotorrealista
# generado o alterado, y lo no declarado es lo que pierde recomendación.
# Va siempre a true: todo lo que sale de este pipeline es vídeo generado.
print(json.dumps({"media_type": "REELS", "video_url": sys.argv[1], "caption": sys.argv[2],
                  "is_ai_generated": True}))
PY
)
RESP=$(curl -s -X POST "$API/$IG_USER_ID/media?access_token=$ACCESS_TOKEN" \
  -H "Content-Type: application/json" -d "$CUERPO")
CONTENEDOR=$(echo "$RESP" | sed -n 's/.*"id":"\([0-9]*\)".*/\1/p')
[ -n "$CONTENEDOR" ] || { echo "   Falló: $RESP"; exit 1; }
echo "   id: $CONTENEDOR"

# ---- 2. sondear hasta FINISHED. NUNCA una espera fija ----
# El sleep 30 a ciegas del script original falló cuando Cloudinary devolvió 429.
echo
echo "== Procesando =="
# Un ERROR suelto NO es terminal: Instagram puede dar ERROR en una lectura temprana
# y acabar en FINISHED segundos después. Documentado en SPEC_APP_INTEGRADA §4 y
# observado el 14 sep (contenedor 18075962381521034: ERROR a los 12 s, FINISHED
# después). Solo se aborta si el ERROR se sostiene; EXPIRED sí es definitivo.
ERRORES=0
for i in $(seq 1 60); do
  EST=$(curl -s "$API/$CONTENEDOR?fields=status_code,status&access_token=$ACCESS_TOKEN")
  CODIGO=$(echo "$EST" | sed -n 's/.*"status_code":"\([A-Z_]*\)".*/\1/p')
  printf "\r   [%02d] %s   " "$i" "${CODIGO:-...}"
  case "$CODIGO" in
    FINISHED) echo; echo "   listo"; break ;;
    EXPIRED)  echo; echo "   $EST"; echo "   Caducado: sin publicar."; exit 1 ;;
    ERROR)
      ERRORES=$((ERRORES + 1))
      if [ "$ERRORES" -ge 4 ]; then
        echo; echo "   $EST"; echo "   ERROR sostenido ($ERRORES lecturas): sin publicar."; exit 1
      fi ;;
    *) ERRORES=0 ;;
  esac
  sleep 10
done
[ "$CODIGO" = "FINISHED" ] || { echo; echo "   Sigue sin terminar. NO publico."; exit 1; }

# ---- 3. puerta humana. La spec la llama no negociable ----
echo
echo "== Confirmación =="
echo "   Cuenta:  @$(echo "$CUENTA" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"
echo "   Destino: GRID (sin trial_params)"
  echo "   IA:      declarada (is_ai_generated=true)"
echo "   Caption: $CAPTION"
echo
printf "   Escribe PUBLICAR para publicar de verdad: "
read -r OK
[ "$OK" = "PUBLICAR" ] || { echo "   Cancelado. El contenedor caduca solo."; exit 0; }

# ---- 4. publicar ----
echo
echo "== Publicando =="
PUB=$(curl -s -X POST "$API/$IG_USER_ID/media_publish" \
  -d "creation_id=$CONTENEDOR" -d "access_token=$ACCESS_TOKEN")
POST_ID=$(echo "$PUB" | sed -n 's/.*"id":"\([0-9]*\)".*/\1/p')
[ -n "$POST_ID" ] || { echo "   Falló: $PUB"; exit 1; }

# ---- 5. verificar DÓNDE cayó, no darlo por hecho ----
echo
echo "== Verificando =="
curl -s "$API/$POST_ID?fields=id,media_type,media_product_type,permalink&access_token=$ACCESS_TOKEN"
echo
