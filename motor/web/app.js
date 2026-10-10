(function () {
  var $ = function (id) { return document.getElementById(id); };
  var analisis = null, momentos = [], planes = null, cuenta = null, modo = "entrar";
  var grupo = "crear", elegida = "clipper", pendiente = null;

  // ------------------------------------------------------------ herramientas
  var ICONOS = {
    tijera: '<svg viewBox="0 0 24 24"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M8.1 7.9 20 20M8.1 16.1 20 4"/></svg>',
    chispa: '<svg viewBox="0 0 24 24"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/></svg>',
    cara: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg>',
    onda: '<svg viewBox="0 0 24 24"><path d="M3 12h2M7 8v8M11 5v14M15 8v8M19 11v2M21 12h0"/></svg>',
    avion: '<svg viewBox="0 0 24 24"><path d="M3 11 21 4l-7 17-3-7-8-3Z"/></svg>',
    calendario: '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
    grafica: '<svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>'
  };
  var HERRAMIENTAS = {
    crear: [
      { id: "clipper", titulo: "Clipper", sub: "Vídeo largo a Shorts", icono: "tijera", lista: true },
      { id: "generador", titulo: "Generador", sub: "Imagen y vídeo con IA", icono: "chispa" },
      { id: "avatares", titulo: "Avatares", sub: "Tu presentador IA", icono: "cara" },
      { id: "voces", titulo: "Voces", sub: "Locución natural", icono: "onda" }
    ],
    publicar: [
      { id: "autopublisher", titulo: "Autopublisher", sub: "Sube y programa", icono: "avion" },
      { id: "calendario", titulo: "Calendario", sub: "Qué sale y cuándo", icono: "calendario" },
      { id: "estadisticas", titulo: "Estadísticas", sub: "Lo que funciona", icono: "grafica" }
    ]
  };
  var PRONTO = {
    generador: "Imágenes, vídeos y anuncios con los mejores modelos de IA, pagando con tus tokens.",
    avatares: "Un presentador IA que habla a cámara con tu guion, con su cara y su voz siempre iguales.",
    voces: "Locuciones naturales en castellano, con tu voz clonada o una diseñada para tu canal.",
    autopublisher: "Conecta tus canales y deja tus clips programados en YouTube, TikTok e Instagram.",
    calendario: "Todo lo que va a salir y cuándo, en una vista de semana.",
    estadisticas: "Qué clips retienen y por qué, para que el clipper aprenda de tu canal."
  };

  function pintarMenu() {
    var barra = $("barra-herr"); barra.textContent = "";
    HERRAMIENTAS[grupo].forEach(function (h) {
      var b = document.createElement("button"); b.type = "button";
      b.className = "herr" + (h.id === elegida ? " elegida" : "");
      var txt = document.createElement("div");
      var t = texto("strong", h.titulo);
      if (!h.lista) { var e = texto("em", "pronto"); e.className = "etiqueta"; t.appendChild(e); }
      txt.appendChild(t); txt.appendChild(texto("span", h.sub));
      b.appendChild(txt);
      b.insertAdjacentHTML("beforeend", ICONOS[h.icono]);
      b.onclick = function () { elegida = h.id; pintarMenu(); };
      b.ondblclick = abrir;
      barra.appendChild(b);
    });
    var a = document.createElement("button"); a.type = "button"; a.className = "abrir";
    a.textContent = "Abrir"; a.insertAdjacentHTML("beforeend", '<span aria-hidden="true">↳</span>');
    a.onclick = abrir;
    barra.appendChild(a);
  }
  function cambiarGrupo(g) {
    grupo = g; elegida = HERRAMIENTAS[g][0].id;
    $("m-crear").className = g === "crear" ? "activo" : "";
    $("m-publicar").className = g === "publicar" ? "activo" : "";
    pintarMenu();
  }
  $("m-crear").onclick = function () { cambiarGrupo("crear"); };
  $("m-publicar").onclick = function () { cambiarGrupo("publicar"); };

  function ocultarTodo() {
    ["p-entrar", "p-restablecer", "p-pronto", "p-enlace", "p-momentos", "p-clips", "p-planes"].forEach(function (id) { $(id).hidden = true; });
  }
  function irA(id) { $(id).scrollIntoView({ behavior: "smooth", block: "start" }); }
  function abrir() {
    if (!cuenta) { pendiente = elegida; ocultarTodo(); $("p-entrar").hidden = false; return irA("p-entrar"); }
    ocultarTodo();
    if (elegida === "clipper") {
      $("p-enlace").hidden = false;
      if (momentos.length) $("p-momentos").hidden = false;
      if ($("clips").childNodes.length) $("p-clips").hidden = false;
      return irA("p-enlace");
    }
    var h = HERRAMIENTAS.crear.concat(HERRAMIENTAS.publicar).filter(function (x) { return x.id === elegida; })[0];
    $("pronto-titulo").textContent = h.titulo + " ";
    var em = texto("em", "muy pronto"); $("pronto-titulo").appendChild(em);
    $("pronto-texto").textContent = PRONTO[elegida];
    $("p-pronto").hidden = false; irA("p-pronto");
  }

  // ------------------------------------------------------------------ utilidades
  function api(ruta, datos) {
    var op = datos ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos) } : {};
    return fetch(ruta, op).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.status); return j; });
    });
  }
  function nota(id, t, mal) { $(id).textContent = t; $(id).className = "nota" + (mal ? " mal" : ""); }
  function texto(el, t) { var d = document.createElement(el); d.textContent = t; return d; }
  function esperar(id, alAcabar, idNota) {
    api("/api/trabajo?id=" + id).then(function (t) {
      if (t.estado === "en_curso") { nota(idNota, t.paso || "Trabajando…"); return setTimeout(function () { esperar(id, alAcabar, idNota); }, 4000); }
      if (t.estado === "fallido") { cargarCuenta(); return nota(idNota, "No ha salido: " + (t.motivo || "error desconocido") + (t.devuelto ? ". Te hemos devuelto los tokens." : ""), true); }
      alAcabar(t);
    }).catch(function (e) { nota(idNota, e.message, true); });
  }

  // ---------------------------------------------------------------- cuenta
  function cargarCuenta() {
    return api("/api/cuenta").then(function (c) {
      cuenta = c; $("saldo").hidden = false; $("b-salir").hidden = false;
      $("s-tokens").textContent = c.tokens.toLocaleString("es-ES") + " tokens";
      $("s-plan").textContent = c.plan_nombre;
      $("b-cuenta").textContent = "Mi cuenta";
      if (planes) pintarPlanes();
    });
  }
  function dentro() {
    return cargarCuenta().then(function () {
      $("p-entrar").hidden = true;
      if (pendiente) { elegida = pendiente; pendiente = null; pintarMenu(); abrir(); }
    });
  }
  $("b-cuenta").onclick = function () {
    if (!cuenta) { ocultarTodo(); $("p-entrar").hidden = false; return irA("p-entrar"); }
    pintarPlanes(); ocultarTodo(); $("p-planes").hidden = false; irA("p-planes");
  };
  $("n-planes").onclick = function (e) { e.preventDefault(); pintarPlanes(); ocultarTodo(); $("p-planes").hidden = false; irA("p-planes"); };
  $("n-herramientas").onclick = function (e) { e.preventDefault(); irA("herramientas"); };
  $("n-como").onclick = function (e) {
    e.preventDefault(); ocultarTodo();
    $("pronto-titulo").textContent = "Cómo ";
    $("pronto-titulo").appendChild(texto("em", "funciona"));
    $("pronto-texto").textContent = "Pega el enlace de un directo o un vídeo largo. Lo transcribimos entero, la IA elige los momentos con gancho, conflicto y remate, y te los damos cortados en vertical, con subtítulos, título y descripción. Cada paso cuesta unos tokens; si algo falla, se devuelven solos.";
    $("p-pronto").hidden = false; irA("p-pronto");
  };
  $("b-salir").onclick = function (e) { e.preventDefault(); api("/api/salir", {}).then(function () { location.reload(); }); };

  function cambiarModo(m) {
    modo = m;
    $("t-entrar").className = "pestana" + (m === "entrar" ? " activa" : "");
    $("t-registro").className = "pestana" + (m === "registro" ? " activa" : "");
    $("b-acceso").textContent = m === "entrar" ? "Entrar" : "Crear cuenta";
    $("clave").autocomplete = m === "entrar" ? "current-password" : "new-password";
    $("clave").placeholder = m === "entrar" ? "Contraseña" : "Contraseña (mínimo 10 caracteres)";
    nota("n-entrar", "");
  }
  $("t-entrar").onclick = function () { cambiarModo("entrar"); };
  $("t-registro").onclick = function () { cambiarModo("registro"); };
  $("f-entrar").onsubmit = function (e) {
    e.preventDefault();
    api(modo === "entrar" ? "/api/entrar" : "/api/registro", { email: $("email").value, clave: $("clave").value })
      .then(function () { $("clave").value = ""; return dentro(); })
      .catch(function (err) { nota("n-entrar", err.message, true); });
  };
  $("a-olvide").onclick = function (e) {
    e.preventDefault();
    if (!$("email").value) return nota("n-entrar", "Escribe tu email y vuelve a pulsar.", true);
    api("/api/olvide", { email: $("email").value }).then(function () {
      nota("n-entrar", "Si hay una cuenta con ese email, te hemos enviado un enlace para recuperarla.");
    }).catch(function (err) { nota("n-entrar", err.message, true); });
  };
  var tokenReset = new URLSearchParams(location.search).get("restablecer");
  $("f-restablecer").onsubmit = function (e) {
    e.preventDefault();
    api("/api/restablecer", { token: tokenReset, clave: $("clave-nueva").value }).then(function () {
      $("p-restablecer").hidden = true; dentro();
    }).catch(function (err) { nota("n-restablecer", err.message, true); });
  };

  function pintarPlanes() {
    if (!planes) return;
    var zona = $("planes"); zona.textContent = "";
    Object.keys(planes.planes).forEach(function (id) {
      var p = planes.planes[id], caja = document.createElement("div");
      caja.className = "plan" + (cuenta && cuenta.plan === id ? " actual" : "");
      caja.appendChild(texto("h3", p.nombre));
      caja.appendChild(texto("div", p.precio_eur ? p.precio_eur + " €/mes" : "Gratis")).className = "precio";
      caja.appendChild(texto("div", p.tokens_mes.toLocaleString("es-ES") + " tokens al mes"));
      var ul = document.createElement("ul");
      p.incluye.forEach(function (x) { ul.appendChild(texto("li", x)); });
      caja.appendChild(ul);
      if (cuenta && cuenta.plan === id) caja.appendChild(texto("p", "Tu plan")).className = "nota";
      else if (p.precio_eur) { var b = texto("button", "Pago con tarjeta, muy pronto"); b.className = "mini"; b.disabled = true; caja.appendChild(b); }
      zona.appendChild(caja);
    });
  }

  // ---------------------------------------------------------------- clipper
  $("f-enlace").onsubmit = function (e) {
    e.preventDefault();
    var b = e.target.querySelector("button"); b.disabled = true;
    nota("n-enlace", "Bajando el vídeo…");
    api("/api/analizar", { url: $("url").value }).then(function (r) {
      analisis = r.id; cargarCuenta();
      esperar(r.id, function (t) {
        nota("n-enlace", "«" + (t.fuente.titulo || "") + "»: transcrito. La IA está eligiendo los mejores momentos…");
        return api("/api/proponer", { id: analisis, n: 5 }).then(function (p) {
          momentos = p.momentos; pintarMomentos(); nota("n-enlace", ""); b.disabled = false; cargarCuenta();
        }).catch(function (err) { nota("n-enlace", err.message, true); b.disabled = false; });
      }, "n-enlace");
    }).catch(function (err) { nota("n-enlace", err.message, true); b.disabled = false; });
  };

  function pintarMomentos() {
    var lista = $("lista"); lista.textContent = "";
    momentos.forEach(function (m, i) {
      var fila = document.createElement("label"); fila.className = "momento";
      var c = document.createElement("input"); c.type = "checkbox"; c.checked = true; c.dataset.i = i;
      var cuerpo = document.createElement("div");
      cuerpo.appendChild(texto("strong", m.titulo));
      cuerpo.appendChild(texto("div", m.ini + " – " + m.fin)).className = "tiempo";
      cuerpo.appendChild(texto("div", "«" + m.gancho + "»")).className = "gancho";
      fila.appendChild(c); fila.appendChild(cuerpo); lista.appendChild(fila);
    });
    $("p-momentos").hidden = false; actualizarCosteCorte();
  }
  function actualizarCosteCorte() {
    var n = document.querySelectorAll("#lista input:checked").length;
    $("b-cortar").textContent = "Cortar " + n + " clip" + (n === 1 ? "" : "s") + (planes ? " · " + n * planes.costes.clip + " tokens" : "");
  }
  $("lista").onchange = actualizarCosteCorte;
  $("b-cortar").onclick = function () {
    var elegidos = Array.prototype.filter.call(document.querySelectorAll("#lista input"), function (c) { return c.checked; })
      .map(function (c) { return momentos[+c.dataset.i]; });
    if (!elegidos.length) return nota("n-momentos", "Elige al menos un momento.", true);
    $("b-cortar").disabled = true;
    nota("n-momentos", "Cortando y subtitulando…");
    api("/api/clipear", { id: analisis, momentos: elegidos }).then(function (r) {
      cargarCuenta();
      esperar(r.id, function (t) { pintarClips(r.id, t.clips); nota("n-momentos", ""); $("b-cortar").disabled = false; }, "n-momentos");
    }).catch(function (err) { nota("n-momentos", err.message, true); $("b-cortar").disabled = false; });
  };

  function copiar(boton, valor) {
    boton.onclick = function () { navigator.clipboard.writeText(valor).then(function () { boton.textContent = "Copiado"; }); };
  }
  function pintarClips(id, clips) {
    var zona = $("clips"); zona.textContent = "";
    clips.forEach(function (c) {
      var fila = document.createElement("div"); fila.className = "clip";
      var v = document.createElement("video"); v.controls = true; v.preload = "metadata"; v.src = "/api/clip?id=" + id + "&n=" + c.n;
      var info = document.createElement("div");
      info.appendChild(texto("div", "Título")).className = "tiempo";
      info.appendChild(texto("div", c.titulo)).className = "campo";
      var desc = (c.descripcion + "\n" + c.hashtags).trim();
      info.appendChild(texto("div", "Descripción")).className = "tiempo";
      info.appendChild(texto("div", desc)).className = "campo";
      var botones = document.createElement("div"); botones.className = "fila";
      var b1 = texto("button", "Copiar título"); b1.className = "mini"; copiar(b1, c.titulo);
      var b2 = texto("button", "Copiar descripción"); b2.className = "mini"; copiar(b2, desc);
      var a = texto("a", ""); a.href = "/api/clip?id=" + id + "&n=" + c.n + "&descargar=1";
      var b3 = texto("button", "Descargar"); b3.className = "mini sec"; a.appendChild(b3);
      botones.appendChild(b1); botones.appendChild(b2); botones.appendChild(a);
      info.appendChild(botones);
      fila.appendChild(v); fila.appendChild(info); zona.appendChild(fila);
    });
    $("p-clips").hidden = false;
  }

  // ---------------------------------------------------------------- arranque
  pintarMenu();
  api("/api/planes").then(function (p) {
    planes = p; var k = p.costes;
    $("n-costes").textContent = "Analizar: " + k.analizar_por_minuto + " token por minuto de vídeo · elegir momentos: " +
      k.proponer + " · cada clip: " + k.clip + ".";
    pintarPlanes();
  });
  if (tokenReset) { history.replaceState(null, "", "/"); $("p-restablecer").hidden = false; }
  else api("/api/yo").then(dentro).catch(function () {});
})();
