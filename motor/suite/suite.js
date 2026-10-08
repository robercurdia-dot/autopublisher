<script>
/* Suite: el flujo completo de un clip.
   Analizar (motor) → proponer momentos (Claude, capacidad sample) → cortar
   (motor) → título y fecha → cola de publicación (motor) → el publicador la
   sube a YouTube Studio. El motor es el servidor local host:autopublisher. */
(function () {
  "use strict";
  var SERVIDOR = "host:autopublisher";
  var mcp = null, sample = null;
  var conectado = false;
  var miniaturas = {}, esperaMini = {};
  var trabajosVistos = [];
  var colaVista = [];
  var dejarDeMirar = null;
  var tableroAjustado = false;

  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, hijos) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") n.className = attrs[k];
      else if (k === "text") n.textContent = attrs[k];
      else if (k === "value") n.value = attrs[k];
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
      else n.setAttribute(k, attrs[k]);
    });
    (hijos || []).forEach(function (h) { if (h) n.appendChild(typeof h === "string" ? document.createTextNode(h) : h); });
    return n;
  }
  function guardar(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  function leer(k, d) { try { var v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } }

  /* ---------------- navegación ---------------- */

  var VISTAS = ["clipper", "publicacion", "autopublisher", "motor"];
  function mostrar(v) {
    if (VISTAS.indexOf(v) < 0) v = "clipper";
    VISTAS.forEach(function (x) { $("v-" + x).hidden = x !== v; });
    document.querySelectorAll("nav.rail button[data-vista]").forEach(function (b) {
      if (b.getAttribute("data-vista") === v) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    guardar("suite.vista", v);
    if (v === "autopublisher" && !tableroAjustado) {
      tableroAjustado = true;
      requestAnimationFrame(function () { var b = $("b-ajustar"); if (b) b.click(); });
    }
    if (v === "motor" && conectado) cargarMotor();
    if (v === "publicacion" && conectado) cargarCola();
  }
  document.querySelectorAll("nav.rail button[data-vista]").forEach(function (b) {
    b.addEventListener("click", function () { mostrar(b.getAttribute("data-vista")); });
  });
  var inicial = (location.hash || "").replace("#", "");
  mostrar(VISTAS.indexOf(inicial) >= 0 ? inicial : leer("suite.vista", "clipper"));

  /* ---------------- conexión ---------------- */

  function marcarConexion(estado, texto) {
    $("conexion").className = "conexion" + (estado === "ok" ? " ok" : estado === "mal" ? " mal" : "");
    $("conexion-txt").textContent = texto;
  }
  function avisar(titulo, texto, pasos) {
    $("aviso-motor").hidden = false;
    $("aviso-titulo").textContent = titulo;
    $("aviso-texto").textContent = texto;
    $("aviso-pasos").hidden = !pasos;
  }
  function explicar(err) {
    var code = (err && err.code) || "upstream_error";
    switch (code) {
      case "server_not_connected": case "not_granted": case "capability_disabled": case "capability_removed":
        return { titulo: "El motor no responde", texto: "Esta página no llega al motor de tu Mac.", pasos: true, caido: true };
      case "not_in_manifest":
        return { titulo: "El motor está desactivado para esta página", texto: "Se rechazó el permiso. Puedes darlo desde el menú Permisos de la página.", caido: true };
      case "cancelled":
        return { titulo: "Cancelado", texto: "No se confirmó en la app, así que no se ha hecho nada." };
      case "server_unavailable":
        return { titulo: "El motor tarda en contestar", texto: "Puede que esté arrancando. Prueba de nuevo en unos segundos." };
      case "tool_error":
        return { titulo: "El motor dice que no", texto: (err.message || "").replace(/^\w+Error: /, "").slice(0, 300) };
      default:
        return { titulo: "Algo falló al hablar con el motor", texto: (err && err.message ? err.message : code).slice(0, 300) };
    }
  }
  function alConectar() {
    if (conectado) return;
    conectado = true;
    marcarConexion("ok", "motor conectado");
    $("aviso-motor").hidden = true;
    ["c-enviar", "c-actualizar", "m-actualizar", "p-actualizar"].forEach(function (id) { $(id).disabled = false; });
    if (!$("v-motor").hidden) cargarMotor();
    if (!$("v-publicacion").hidden) cargarCola();
  }
  function alCaer(err) {
    var e = explicar(err);
    if (e.caido) { conectado = false; marcarConexion("mal", "sin motor"); $("c-enviar").disabled = true; }
    avisar(e.titulo, e.texto, e.pasos);
  }
  function llamar(tool, args, opciones) { return mcp.callTool(SERVIDOR, tool, args || {}, opciones).then(function (r) { return r.payload; }); }

  (window.claude && typeof window.claude.use === "function" ? window.claude.use("mcp") : Promise.resolve(null))
    .then(function (ns) {
      mcp = ns;
      if (!mcp) { marcarConexion("mal", "sin motor"); avisar("El motor no responde", "Esta vista no puede usar el motor local.", true); return; }
      dejarDeMirar = mcp.watchTool(SERVIDOR, "trabajos", { limite: 20 }, function (ev) {
        if (ev.type === "data") { alConectar(); trabajosVistos = (ev.result.payload || {}).trabajos || []; pintarTrabajos(); }
        else alCaer(ev.error);
      }, { refetchInterval: 30000 });
    })
    .catch(function () { marcarConexion("mal", "sin motor"); avisar("El motor no responde", "Esta vista no puede usar el motor local.", true); });
  if (window.claude && typeof window.claude.use === "function") {
    window.claude.use("sample").then(function (s) { sample = s; pintarTrabajos(); }).catch(function () {});
  }

  /* ---------------- utilidades ---------------- */

  function hace(t) {
    var s = Math.max(0, Date.now() / 1000 - t);
    if (s < 60) return "ahora";
    if (s < 3600) return "hace " + Math.round(s / 60) + " min";
    if (s < 86400) return "hace " + Math.round(s / 3600) + " h";
    return "hace " + Math.round(s / 86400) + " d";
  }
  function mmss(s) { s = Math.round(s); return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2); }
  function seg(txt) { var p = String(txt).trim().split(":"); return p.length === 2 ? (+p[0]) * 60 + (+p[1]) : +txt; }
  function fuente(url) {
    try { var u = new URL(url); return u.hostname.replace(/^www\./, "") + u.pathname.replace(/\/$/, "") + (u.search ? u.search.slice(0, 16) : ""); }
    catch (e) { return url || ""; }
  }
  var ESTADOS = { en_curso: ["curso", "en curso"], terminado: ["ok", "listo"], fallido: ["stop", "fallido"] };
  function pin(estado) { var e = ESTADOS[estado] || ["gris", estado]; return el("span", { class: "pin " + e[0], text: e[1] }); }

  /* ---------------- pintar trabajos ---------------- */

  function pintarTrabajos() {
    var cont = $("lista-trabajos");
    if (!conectado && !trabajosVistos.length) return;
    cont.textContent = "";
    if (!trabajosVistos.length) {
      cont.appendChild(el("div", { class: "vacio-lista cristal" }, [el("b", { text: "Todavía no hay nada." }),
        "Pega un enlace arriba y pulsa «Analizar»."]));
      return;
    }
    trabajosVistos.forEach(function (t) {
      cont.appendChild(t.tipo === "analisis" ? tarjetaAnalisis(t) : tarjetaClips(t));
    });
  }

  function cabecera(t, titulo) {
    return el("div", { class: "trabajo-cab" }, [pin(t.estado),
      el("a", { class: "fuente", href: t.url || "#", target: "_blank", rel: "noopener", text: titulo || fuente(t.url) }),
      el("span", { class: "cuando", text: hace(t.creado) })]);
  }

  function tarjetaAnalisis(t) {
    var f = t.fuente || {};
    var art = el("article", { class: "trabajo cristal" }, [cabecera(t, f.titulo)]);
    if (t.estado === "en_curso") art.appendChild(el("pre", { class: "registro-t", text: (t.registro || []).slice(-3).join("\n") || "Empezando…" }));
    if (t.estado === "fallido") art.appendChild(el("div", { class: "motivo", text: t.motivo || "Falló sin dejar motivo." }));
    if (t.estado !== "terminado") return art;
    art.appendChild(el("div", { class: "datos-fuente", text: [f.canal ? "@" + f.canal : null, f.duracion ? mmss(f.duracion) : null,
      f.frases ? f.frases + " frases transcritas" : null].filter(Boolean).join(" · ") }));
    var props = leer("suite.propuestas." + t.id, null);
    var zona = el("div", { class: "propuestas" });
    art.appendChild(zona);
    if (props) pintarPropuestas(zona, t, props);
    else {
      var boton = el("button", { type: "button", class: "aqua pequeño", text: "Proponer momentos" });
      var nota = el("div", { class: "nota-envio" });
      if (!sample) { boton.disabled = true; nota.textContent = "Para proponer momentos, la página necesita permiso para preguntar a Claude."; }
      boton.addEventListener("click", function () { proponer(t, zona, boton, nota); });
      zona.appendChild(el("div", { class: "acciones" }, [boton]));
      zona.appendChild(nota);
    }
    return art;
  }

  /* ---------------- proponer momentos (Claude) ---------------- */

  var REGLAS = [
    "Eres editor de Shorts en castellano de España para un canal de clips de streamers.",
    "Lee la transcripción (cada línea: mm:ss frase) y elige los N mejores momentos para Shorts.",
    "Cada momento:",
    "- dura entre 20 y 45 segundos y es una idea completa que se entiende sin contexto;",
    "- EMPIEZA en una frase de entrada fuerte (el gancho tiene que estar en el primer segundo): nunca a mitad de idea, nunca tras una coma. Usa como inicio el mm:ss exacto de la línea con la que arranca;",
    "- TERMINA en un cierre de frase (el remate dentro), con el mm:ss del final de la última frase;",
    "- prioriza opinión fuerte, polémica, humor, una revelación o una frase citable;",
    "- EVITA a terceros en situaciones delicadas (pacientes, menores, datos de salud o personales), promociones pagadas y momentos que dependen de algo que no se entiende sin ver lo anterior.",
    "Título: máximo 70 caracteres, el nombre del creador en mayúsculas más una cita literal o una promesa clara, un emoji al final. Descripción: una o dos frases que expliquen el momento.",
    "Responde SOLO con JSON: {\"momentos\":[{\"ini\":\"mm:ss\",\"fin\":\"mm:ss\",\"gancho\":\"primera frase del clip\",\"por_que\":\"en pocas palabras\",\"titulo\":\"…\",\"descripcion\":\"…\",\"hashtags\":\"#a #b #shorts\"}]} ordenado de mejor a peor."
  ].join("\n");

  function proponer(t, zona, boton, nota) {
    boton.disabled = true;
    nota.className = "nota-envio";
    nota.textContent = "Leyendo la transcripción…";
    var n = parseInt($("c-cuantos").value, 10) || 6;
    var limite = 150000;
    (sample.limits ? sample.limits().then(function (l) { limite = l.maxInputBytes || limite; }).catch(function () {}) : Promise.resolve())
      .then(function () { return llamar("transcripcion", { analisis: t.id, bloque: 0 }); })
      .then(function (tr) {
        var cuerpo = tr.texto;
        if (new Blob([cuerpo]).size > limite * 0.8) return llamar("transcripcion", { analisis: t.id, bloque: 15 }).then(function (x) { return [tr, x.texto]; });
        return [tr, cuerpo];
      })
      .then(function (par) {
        var tr = par[0];
        nota.textContent = "Claude está eligiendo los momentos…";
        var entrada = REGLAS.replace("los N mejores", "los " + n + " mejores") +
          "\n\nVídeo: «" + (tr.titulo || "") + "» de " + (tr.canal || "") + " (" + mmss(tr.duracion || 0) + ")\n\nTRANSCRIPCIÓN\n" + par[1];
        return sample.json(entrada, { modelTier: "complex", onText: function () { nota.textContent = "Claude está eligiendo los momentos…"; } })
          .then(function (r) { return { tr: tr, r: r }; });
      })
      .then(function (x) {
        var momentos = ((x.r && x.r.momentos) || []).map(function (m) {
          return { ini: m.ini, fin: m.fin, gancho: m.gancho || "", por_que: m.por_que || "", titulo: (m.titulo || "").slice(0, 100),
                   descripcion: m.descripcion || "", hashtags: m.hashtags || "", elegido: true,
                   url: x.tr.url, canal: x.tr.canal };
        });
        if (!momentos.length) throw { code: "empty_completion", message: "Claude no devolvió momentos." };
        guardar("suite.propuestas." + t.id, momentos);
        zona.textContent = "";
        pintarPropuestas(zona, t, momentos);
      })
      .catch(function (err) {
        boton.disabled = false;
        nota.className = "nota-envio mal";
        if (err && err.code === "not_granted") nota.textContent = "Sin permiso para preguntar a Claude: dalo en el menú Permisos de la página.";
        else if (err && err.code === "rate_limited") nota.textContent = "Demasiadas peticiones seguidas. Espera un minuto y vuelve a pulsar.";
        else if (err && err.code === "invalid_json") nota.textContent = "La respuesta no vino en el formato esperado. Vuelve a pulsar.";
        else if (err && (err.code === "tool_error" || err.code === "server_not_connected")) { var e = explicar(err); nota.textContent = e.titulo + ". " + e.texto; }
        else nota.textContent = "No se pudieron proponer momentos: " + ((err && err.message) || "error desconocido");
      });
  }

  function pintarPropuestas(zona, t, momentos) {
    var lista = el("div", { class: "lista-propuestas" });
    momentos.forEach(function (m, k) {
      var caja = el("input", { type: "checkbox", "aria-label": "Cortar este momento" });
      caja.checked = m.elegido !== false;
      caja.addEventListener("change", function () { m.elegido = caja.checked; guardar("suite.propuestas." + t.id, momentos); });
      var ini = el("input", { type: "text", class: "tiempo", value: m.ini, "aria-label": "Inicio" });
      var fin = el("input", { type: "text", class: "tiempo", value: m.fin, "aria-label": "Final" });
      [ini, fin].forEach(function (inp, j) {
        inp.addEventListener("change", function () { m[j ? "fin" : "ini"] = inp.value.trim(); guardar("suite.propuestas." + t.id, momentos); });
      });
      lista.appendChild(el("div", { class: "propuesta" }, [
        caja,
        el("div", { class: "prop-cuerpo" }, [
          el("div", { class: "prop-titulo", text: m.titulo }),
          el("div", { class: "prop-gancho", text: "«" + m.gancho + "»" }),
          el("div", { class: "prop-meta" }, [ini, el("span", { text: "–" }), fin,
            el("span", { class: "prop-dur", text: Math.round(seg(m.fin) - seg(m.ini)) + " s" }),
            el("span", { class: "prop-porque", text: m.por_que })])
        ])
      ]));
    });
    var nota = el("div", { class: "nota-envio" });
    var cortar = el("button", { type: "button", class: "aqua pequeño", text: "Cortar los marcados" });
    cortar.addEventListener("click", function () {
      var elegidos = momentos.filter(function (m) { return m.elegido !== false; });
      if (!elegidos.length) { nota.className = "nota-envio mal"; nota.textContent = "Marca al menos un momento."; return; }
      var malos = elegidos.filter(function (m) { return !(seg(m.fin) > seg(m.ini)); });
      if (malos.length) { nota.className = "nota-envio mal"; nota.textContent = "Revisa los tiempos: el final tiene que ir después del inicio."; return; }
      cortar.disabled = true;
      nota.className = "nota-envio";
      nota.textContent = "Enviando al motor… si la app pide confirmarlo, acéptalo.";
      llamar("clipear", {
        analisis: t.id,
        tramos: elegidos.map(function (m) { return seg(m.ini) + "-" + seg(m.fin); }).join(","),
        propuestas: elegidos.map(function (m) { return { titulo: m.titulo, descripcion: m.descripcion, hashtags: m.hashtags, gancho: m.gancho }; }),
        vocabulario: $("c-vocab").value.trim() || undefined,
        corregir: $("c-corregir").value.trim() || undefined
      }).then(function () {
        nota.textContent = "Cortando. Los clips aparecen arriba en unos minutos.";
        return mcp.invalidate(SERVIDOR, "trabajos").catch(function () {});
      }).catch(function (err) {
        cortar.disabled = false;
        var e = explicar(err); nota.className = "nota-envio mal"; nota.textContent = e.titulo + ". " + e.texto;
      });
    });
    var rehacer = el("button", { type: "button", class: "cristal-btn", text: "Proponer otros" });
    rehacer.addEventListener("click", function () { guardar("suite.propuestas." + t.id, null); try { localStorage.removeItem("suite.propuestas." + t.id); } catch (e) {} pintarTrabajos(); });
    zona.appendChild(lista);
    zona.appendChild(el("div", { class: "acciones" }, [cortar, rehacer]));
    zona.appendChild(nota);
  }

  /* ---------------- clips y programación ---------------- */

  function tarjetaClips(t) {
    var art = el("article", { class: "trabajo cristal" }, [cabecera(t, t.tramos ? "Clips elegidos · " + fuente(t.url) : fuente(t.url))]);
    if (t.estado === "en_curso") art.appendChild(el("pre", { class: "registro-t", text: (t.registro || []).slice(-4).join("\n") || "Empezando…" }));
    if (t.estado === "fallido") art.appendChild(el("div", { class: "motivo", text: t.motivo || "Falló sin dejar motivo." }));
    if (t.clips && t.clips.length) {
      var rej = el("div", { class: "clips" });
      t.clips.forEach(function (c) { rej.appendChild(tarjetaClip(c)); });
      art.appendChild(rej);
    }
    return art;
  }

  function descripcionCompleta(c) {
    var p = c.propuesta || {};
    var partes = [p.descripcion || ""];
    var o = c.origen || {};
    var pie = [];
    if (o.url) pie.push("🎥 Vídeo completo: " + o.url);
    if (o.canal) pie.push("📺 Canal original: @" + o.canal);
    if (pie.length) partes.push(pie.join("\n"));
    partes.push(p.hashtags || "#shorts");
    return partes.filter(Boolean).join("\n\n").trim();
  }

  function siguienteHueco() {
    // La próxima hora en punto libre a partir de mañana a las 9:00, una por hora hasta las 13:00.
    var ocupadas = colaVista.map(function (x) { return x.cuando; });
    var d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0);
    for (var i = 0; i < 60; i++) {
      var iso = d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2) + "T" + ("0" + d.getHours()).slice(-2) + ":00";
      if (ocupadas.indexOf(iso) < 0) return iso;
      d.setHours(d.getHours() + 1);
      if (d.getHours() > 13) { d.setDate(d.getDate() + 1); d.setHours(9); }
    }
    return "";
  }

  function tarjetaClip(c) {
    var ruta = (c.archivos || [])[0];
    var img = el("img", { alt: "Fotograma del clip " + c.n, loading: "lazy" });
    var marco = el("div", { class: "marco-clip" }, [img, el("span", { class: "dur", text: mmss(c.fin - c.ini) })]);
    pedirMiniatura(ruta, img);
    var enCola = colaVista.filter(function (x) { return x.archivo === ruta; })[0];
    var p = c.propuesta || {};
    var titulo = el("input", { type: "text", class: "campo-pub", maxlength: "100", value: p.titulo || "", placeholder: "Título", "aria-label": "Título" });
    var desc = el("textarea", { class: "campo-pub", rows: "4", "aria-label": "Descripción" });
    desc.value = descripcionCompleta(c);
    var cuando = el("input", { type: "datetime-local", class: "campo-pub", value: siguienteHueco(), "aria-label": "Fecha de publicación" });
    var nota = el("div", { class: "nota-envio" });
    var boton = el("button", { type: "button", class: "aqua pequeño", text: "Programar" });
    boton.addEventListener("click", function () {
      if (!titulo.value.trim()) { nota.className = "nota-envio mal"; nota.textContent = "Escribe un título."; titulo.focus(); return; }
      if (!cuando.value) { nota.className = "nota-envio mal"; nota.textContent = "Elige fecha y hora."; return; }
      boton.disabled = true; nota.className = "nota-envio"; nota.textContent = "Preparando la subida…";
      llamar("programar", { archivo: ruta, titulo: titulo.value.trim(), descripcion: desc.value, cuando: cuando.value.slice(0, 16) })
        .then(function (item) { colaVista.push(item); nota.textContent = "En la cola para el " + item.cuando.replace("T", " a las ") + "."; boton.textContent = "Programado"; })
        .catch(function (err) { boton.disabled = false; var e = explicar(err); nota.className = "nota-envio mal"; nota.textContent = e.texto || e.titulo; });
    });
    var form = enCola
      ? el("div", { class: "nota-envio", text: "En la cola · " + enCola.cuando.replace("T", " ") + (enCola.url ? " · en YouTube" : "") })
      : el("div", { class: "form-pub" }, [titulo, desc, cuando, el("div", { class: "acciones" }, [boton,
          el("button", { type: "button", class: "cristal-btn", text: "Ver", onclick: function () { abrir(ruta, false); } })]), nota]);
    return el("div", { class: "clip clip-pub" }, [marco,
      el("details", {}, [el("summary", { text: "«" + (c.texto || "") + "»" })]), form]);
  }

  function pedirMiniatura(ruta, img) {
    if (!ruta || !mcp) return;
    var m = miniaturas[ruta];
    if (m && m !== "pendiente" && m !== "error") { img.src = m; return; }
    (esperaMini[ruta] = esperaMini[ruta] || []).push(img);
    if (m === "pendiente") return;
    miniaturas[ruta] = "pendiente";
    mcp.callTool(SERVIDOR, "miniatura", { ruta: ruta, segundo: 3, ancho: 240 }, { cache: { staleTime: 300000, gcTime: 86400000 } })
      .then(function (r) { var p = r.payload || {}; miniaturas[ruta] = "data:" + p.mime + ";base64," + p.base64; esperaMini[ruta].forEach(function (i) { i.src = miniaturas[ruta]; }); })
      .catch(function () { miniaturas[ruta] = "error"; });
  }
  function abrir(ruta, carpeta) {
    if (!mcp || !ruta) return;
    mcp.callTool(SERVIDOR, "abrir", { ruta: ruta, carpeta: !!carpeta }).catch(function (err) { if (!err || err.code !== "cancelled") alCaer(err); });
  }

  /* ---------------- encargo ---------------- */

  $("f-clip").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var url = $("c-url").value.trim(), nota = $("c-nota");
    nota.className = "nota-envio";
    if (!/^https?:\/\/\S+$/.test(url)) { nota.className = "nota-envio mal"; nota.textContent = "Pega un enlace completo, empezando por https://."; $("c-url").focus(); return; }
    var rapido = $("c-modo").value === "rapido";
    var args = { url: url, sesion_chrome: $("c-chrome").checked };
    if ($("c-vocab").value.trim()) args.vocabulario = $("c-vocab").value.trim();
    if (rapido) { args.cuantos = parseInt($("c-cuantos").value, 10); if ($("c-corregir").value.trim()) args.corregir = $("c-corregir").value.trim(); }
    $("c-enviar").disabled = true;
    nota.textContent = "Enviando al motor… si la app pide confirmarlo, acéptalo.";
    llamar(rapido ? "clipear" : "analizar", args).then(function () {
      nota.textContent = rapido ? "En marcha: el clipper elige solo y los clips aparecen abajo." : "Bajando y transcribiendo. Cuando termine, pulsa «Proponer momentos».";
      $("c-url").value = "";
      return mcp.invalidate(SERVIDOR, "trabajos").catch(function () {});
    }).catch(function (err) {
      var e = explicar(err); nota.className = "nota-envio mal"; nota.textContent = e.titulo + ". " + e.texto; if (e.caido) alCaer(err);
    }).then(function () { $("c-enviar").disabled = !conectado; });
  });
  $("c-actualizar").addEventListener("click", function () { if (mcp) mcp.invalidate(SERVIDOR, "trabajos").catch(function () {}); });

  /* ---------------- cola ---------------- */

  var ESTADO_COLA = { pendiente: ["curso", "esperando al publicador"], programado: ["ok", "programado en YouTube"],
                      publicado: ["ok", "publicado"], fallido: ["stop", "falló"], cancelado: ["gris", "cancelado"] };
  function cargarCola() {
    if (!mcp) return;
    llamar("cola", {}, { cache: { refresh: true } }).then(function (r) {
      colaVista = (r && r.cola) || [];
      var cont = $("lista-cola");
      cont.textContent = "";
      if (!colaVista.length) {
        cont.appendChild(el("div", { class: "vacio-lista cristal" }, [el("b", { text: "La cola está vacía." }), "Programa un clip desde el Clipper y aparecerá aquí con su fecha."]));
        return;
      }
      colaVista.forEach(function (x) {
        var e = ESTADO_COLA[x.estado] || ["gris", x.estado];
        cont.appendChild(el("div", { class: "fila-cola cristal" }, [
          el("div", { class: "cola-cuando", text: x.cuando.replace("T", " ") }),
          el("div", { class: "cola-titulo" }, [el("span", { text: x.titulo }), x.nota ? el("small", { text: x.nota }) : null]),
          el("span", { class: "pin " + e[0], text: e[1] }),
          x.url ? el("a", { href: x.url, target: "_blank", rel: "noopener", class: "cristal-btn", text: "Abrir" }) : null
        ]));
      });
      pintarTrabajos();
    }).catch(alCaer);
  }
  $("p-actualizar").addEventListener("click", cargarCola);

  /* ---------------- motor ---------------- */

  function fila(k, v, clase) {
    return el("div", { class: "fila-m" }, [el("span", { class: "k", text: k }), clase ? el("span", { class: "pin " + clase, text: v }) : el("span", { class: "v", text: v })]);
  }
  function cargarMotor() {
    if (!mcp) return;
    llamar("estado", {}, { cache: { refresh: true } }).then(function (e) {
      var cont = $("paneles-motor");
      cont.textContent = "";
      cont.appendChild(el("div", { class: "panel-m cristal" }, [el("h2", { text: "Capacidades" }),
        fila("Subtítulos (whisper + libass)", e.subtitulos ? "listo" : "falta", e.subtitulos ? "ok" : "stop"),
        fila("Recorte sobre la cara y webcam", e.caras ? "listo" : "falta", e.caras ? "ok" : "stop"),
        fila("Proponer momentos (Claude)", sample ? "listo" : "sin permiso", sample ? "ok" : "espera"),
        fila("Generar con fal", (e.generacion || {}).fal || "?", "stop"),
        fila("Enmiendas activas", String(e.enmiendas_activas))]));
      var cuentas = el("div", { class: "panel-m cristal" }, [el("h2", { text: "Cuentas" })]);
      Object.keys(e.cuentas || {}).forEach(function (k) {
        var c = e.cuentas[k];
        cuentas.appendChild(fila(k.replace("_", " ") + (c.nombre ? " · " + c.nombre : ""), (c.estado || "?") + " · " + (c.via || "?")));
      });
      cont.appendChild(cuentas);
      var errs = e.errores_clipper || [], abiertos = errs.filter(function (x) { return x.pendiente; });
      var panel = el("div", { class: "panel-m cristal" }, [el("h2", { text: "Errores del clipper" }),
        fila("Registrados, cada uno con su test", String(errs.length)),
        fila("Con algo pendiente", String(abiertos.length), abiertos.length ? "espera" : "ok")]);
      abiertos.forEach(function (x) { panel.appendChild(fila(x.id.replace(/_/g, " "), "pendiente", "espera")); });
      cont.appendChild(panel);
    }).catch(alCaer);
  }
  $("m-actualizar").addEventListener("click", cargarMotor);
})();
</script>
