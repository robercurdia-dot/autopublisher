# Autopublisher — qué nos separa de construirlo de verdad

Estado a 5 de octubre de 2026.

## Cómo funciona hoy

El autopublisher y el autoclipper **se ejecutan desde esta máquina**, conducidos por
Claude Code. Funciona aquí porque aquí están tres cosas que un servidor no tendría:

- **la sesión de Chrome** de Roberto, con TikTok, Instagram y Facebook ya autenticados
- **las credenciales locales** (`fase0/.env`, `credenciales_ig.env` fuera del repo)
- **ffmpeg, yt-dlp y Python** con numpy y Pillow instalados

Si la máquina está apagada o la sesión cerrada, no pasa nada: no hay nada corriendo solo.

---

## Lo que ya NO es bloqueo

Para no volver a discutir lo que está resuelto:

| antes | ahora |
|---|---|
| No se podían bajar vídeos de referencia (la API de cobalt daba 405) | `yt-dlp` instalado; `clipper/descargar.py` baja de TikTok, Instagram, YouTube, X, Facebook |
| La web `zularalamp.vercel.app` no cargaba (30 sep – 4 oct) | Responde 200, con precio, botón de compra y Stripe |
| El token de Instagram caducaba el 6 oct | Renovado hasta el **29 nov 2026** |
| El producto derivaba de forma entre planos | Invariante corregido (estaba invertido) y medido en píxeles sobre la foto de estudio |
| Las piezas salían sin gancho | `quemar_gancho.py`, paso obligatorio de la cadena |
| Se copiaba la forma de cuentas con la audiencia muerta | `auditar_cuenta.py` las separa antes de tomarlas como modelo |

---

## 1. Bloqueos que no son código

Dinero, cuentas y configuración. Ninguno se arregla programando.

### 1.1 La web vende pero no mide — **el más urgente**

La página existe y cobra, pero **no tiene ninguna analítica**: ni píxel de Meta, ni Google,
ni Vercel Analytics. Consecuencias:

- **No se puede medir conversión.** Seguimos sin saber si alguien que ve una pieza compra.
- **La pauta de Meta queda ciega.** Sin píxel, Meta no puede optimizar a compra ni atribuir
  ventas. Gastar en anuncios ahora sería pagar sin poder leer el resultado.

Hace falta: **píxel de Meta** en la web y **enlaces con UTM** distintos por plataforma en las
tres bios, para saber de dónde llega cada visita.

### 1.2 Sin saldo de generación

| proveedor | estado |
|---|---|
| fal | clave válida en `fase0/.env`, **saldo $0, cuenta bloqueada** («Exhausted balance») |
| Flashboards | **saldo $0** tras el run 07 |

Tarifas verificadas en las páginas de los modelos, para una pieza de 12 s:

| modelo | con vídeo de referencia | solo texto o imagen |
|---|---|---|
| MiniMax H3 Max 768p | ~$2,23 (la referencia de vídeo cuesta más que la generación) | **$0,96** |
| Seedance 2.5 720p | ~$3,41 | $5,68 |

### 1.3 Facebook no publica

El uploader de Reels se queda en «Subiendo vídeo» indefinidamente: seis intentos, mismo
resultado, incluso con el fichero que funcionó el 24 sep. Es Facebook, no nosotros.

La salida es la API, y para eso falta **una acción de Roberto**: en la app `Auto publisher`
(ID `27572026672438979`) añadir el caso de uso de páginas, y aceptar el consentimiento de Meta.
Eso da `pages_manage_posts` y permite un token de página para Zulara Lamp
(`61594468992342`). No requiere revisión de Meta porque la app está en desarrollo y Roberto
administra la app y la página.

---

## 2. Lo que solo funciona en esta máquina

Lo que habría que resolver para que el sistema corriera en un servidor.

| pieza | por qué está atada aquí | salida |
|---|---|---|
| **Publicar en TikTok** | Se hace conduciendo Chrome con la sesión de Roberto. La única API disponible exige alojar el vídeo en Higgsfield, que está descartado | Navegador sin cabeza con la sesión guardada en el servidor, o aceptar que este paso sea manual |
| **Barrido del nicho en Instagram** | Usa `/api/v1/media/{id}/info/` desde la sesión del navegador | Igual que TikTok |
| **Generar por el board de Flashboards** | Necesita una pestaña viva; sin ella solo hay vía sin pestaña, que **no acepta vídeo de referencia** | Pasar la generación a fal, que es HTTP puro |
| **Credenciales** | En ficheros locales | Gestor de secretos del servidor |
| **Entorno de Python** | Frágil: `brew install yt-dlp` metió un Python que tapó al del sistema y rompió los scripts el 5 oct | Un entorno virtual propio del proyecto, fijado |
| **ffmpeg** | Esta build no trae `drawtext`; los rótulos se pintan con PIL y se superponen | Funciona igual en un servidor, pero hay que replicar la instalación |

---

## 3. Piezas sin construir

Por orden de lo que desbloquean.

1. **Medición de conversión** — píxel + UTM (ver 1.1). Sin esto no hay forma de saber si el
   negocio funciona.
2. **Disparador de fal en la cadena principal.** El código existe en `fase0/validar_fal.py`
   pero no está conectado a `construir_prompt.py` → generar → `publicar_clip.sh`.
3. **`publicar_fb.sh` contra la API de Reels** (`POST /{page-id}/video_reels`, tres fases).
   Bloqueado por 1.3.
4. **Programar lo que hoy hay que acordarse de lanzar:**
   - recogida de métricas a las 6 h de publicar (`analitica/recoger.py`)
   - **renovación del token de Instagram** (`publicar/renovar_token_ig.py`). Ojo: el script
     renueva *cuando se ejecuta* y quedan menos de 15 días, pero **nada lo ejecuta solo**.
     Si nadie lo lanza antes del 29 de noviembre, la publicación en Instagram se cae.
5. **Transcripción** con `whisper.cpp` en local. Daría al autoclipper una quinta señal para
   vídeos con habla y permitiría subtítulos automáticos. Hoy el clipper puntúa solo por imagen
   y ritmo, así que elegiría mal en un pódcast.
6. **OCR de los rótulos de la competencia** con el framework Vision de macOS
   (`pyobjc-framework-Vision`). Los ganchos del nicho van quemados en pantalla; hoy se leen a ojo.
7. **Chequeo automático de la silueta del producto.** Sigue siendo juicio humano sobre la tira
   de planos (`qa_producto` bloquea la aprobación hasta que alguien la mira).
8. **Panel de estado.** El artifact Autopublisher está congelado desde el 25 sep. Puede
   reconstruirse leyendo `db/jobs.db` y `fase0/enmiendas.json`, pero **solo mostrará estado:
   una página publicada no puede ejecutar los scripts**.

---

## 4. Deuda técnica

### El constructor de prompts no tiene tests, y se ha contradicho seis veces

`tests/` está vacío. Cada uno de estos fallos generó un prompt que se contradecía a sí mismo,
y el modelo obedeció a la parte equivocada:

1. La regla decía «nunca abras con el producto solo en una mano» y el bloque SHOTS abría
   exactamente así (run 06). La regla iba como prosa; los planos, como instrucción.
2. SUPPORT decía «una botella» y SHOTS pedía los soportes [1] a [4].
3. La cabecera decía «9 shots» y la lista tenía 4.
4. Reglas en castellano dentro de un prompt en inglés.
5. `@Video1` con papel `directa` reclamaba el producto mientras `@Image1` decía ser su autoridad.
6. El prompt citaba `@Video1` en una tirada donde no se adjuntó ningún vídeo.

Un test que construya el prompt para varias combinaciones y compruebe su coherencia interna
(número de planos, unidades, anclajes que existen, idioma) habría cazado los seis.

### El invariante del producto estuvo invertido desde el principio

El texto decía «más ancho arriba»; el producto es más ancho abajo. Lo arrastraron cinco
tiradas. Hoy el invariante está medido en píxeles sobre `producto/negro_mate_estudio.jpg`,
pero **nada impide que vuelva a pasar con otro producto**. La enmienda
`cotas_del_invariante_verificadas` lo exige; ningún código lo comprueba.

---

## 5. Qué haría falta para un servicio de verdad

Si algún día se quiere que funcione sin esta máquina:

- **Un servidor** donde corra el motor
- **Una cola de trabajos y una API**, para que un panel o un botón pueda lanzar una tirada y
  consultar su estado
- **Gestor de secretos** en lugar de ficheros `.env`
- **Resolver los pasos de navegador** (TikTok, barrido de Instagram): o un navegador sin
  cabeza con sesión persistente, o asumir que esos pasos siguen siendo manuales
- **Programador de tareas** para métricas y renovación de tokens
- **Descarga propia de referencias y música en el servidor**: los vídeos de terceros y las
  pistas de la Colección de Meta **no están en el repo** por licencia, así que un servidor
  no los tendría
- **Avisos** cuando algo falla, en vez de enterarse al abrir la sesión

---

## 6. Orden recomendado

1. **Píxel de Meta + UTM en las bios.** Gratis. Sin esto ninguna otra inversión se puede medir.
2. **Recargar fal** con poco (~$10) y conectar su disparador a la cadena. Quita la pestaña
   abierta y las colas atascadas.
3. **Caso de uso de páginas en la app de Meta** → `publicar_fb.sh`. Facebook fue la
   plataforma con más alcance de la única pieza que llegó a subir (448 visionados).
4. **Programar la renovación del token de Instagram** antes del 29 de noviembre.
5. **Tests del constructor de prompts.**
6. Después, y solo si hay señal de venta: pauta en Meta, y pensar en el servidor.
