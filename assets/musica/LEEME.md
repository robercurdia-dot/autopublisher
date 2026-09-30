# Catálogo de sonidos

Lo que el nodo de sonido puede elegir. Vacío no hay nada que puntuar: el
emparejador solo ordena candidatos que pueda **escuchar**, es decir, que existan
como archivo en disco.

## Formato

`catalogo.json` es una lista de entradas:

```json
{
  "id": "meta_soft_bounce",
  "nombre": "Soft Bounce",
  "autor": "…",
  "origen": "coleccion_meta",
  "url": "…",
  "archivo": "soft_bounce.mp3"
}
```

`archivo` es relativo a esta carpeta. `origen` dice de dónde sale y con eso se
sabe cómo se va a publicar la pieza:

| origen             | qué es                                            | cómo se publica |
|--------------------|---------------------------------------------------|-----------------|
| `coleccion_meta`   | Colección de sonidos de Meta, MP3 descargado      | se monta con ffmpeg y **se publica por API** |
| `ig`               | sonido de la biblioteca de la app, vista previa capturada | el clip se exporta mudo y **se sube a mano** eligiendo ese sonido |

La diferencia no es estética: la API de Instagram **no puede seleccionar un
sonido de la biblioteca**. Solo un archivo montado permite la cadena automática.

## Cómo se llena

- **Colección de Meta**: Business Suite → Colección de sonidos → descargar. Una
  vez hecho, el catálogo es tuyo y se reutiliza en todas las piezas.
- **Biblioteca de la app**: requiere una sesión iniciada. El nodo busca con los
  términos que saca `buscar_sonido.py`, captura la vista previa de cada
  candidato y la guarda aquí para poder medirla.

## Uso

```bash
python3 ingesta/perfil_musical.py --todos            # mide las referencias
python3 ingesta/buscar_sonido.py lemon_art_negro     # ordena el catálogo
python3 publicar/preparar_sonido.py clip.mp4 lemon_art_negro   # elige + alinea
bash    publicar/publicar_clip.sh clip.mp4 clip_pista.m4a lemon_art_negro "caption"
```

`preparar_sonido.py` imprime las tres mejores candidatas y alinea la primera.
Con `--elegir <id>` mandas tú.

## Por qué se alinea y no al revés

Forzar al generador a cortar donde suena la música no se puede. Mover la música
para que caiga en los cortes del clip, sí: `alinear_audio.py` busca el
desplazamiento que más cortes hace coincidir con un golpe y recorta ahí.

Medido sobre el clip del run 01 (7 cortes, pista de control): 4 de 7 sin alinear,
5 de 7 alineado. Las referencias de la competencia se mueven entre 62 % y 80 %,
así que ese 71 % está dentro de lo que se ve en el sector.

## Efecto en la puerta de originalidad

Con el audio copiado de la referencia, `originalidad.py` daba 0,998 y suspendía.
Con pista propia alineada, el mismo clip da -0,028 y pasa. No hay que desactivar
ninguna comprobación: la señal que nos delataba desaparece sola.
