(function () {
  var $ = function (id) { return document.getElementById(id); };
  var analisis = null, momentos = [];

  function api(ruta, datos) {
    var op = datos ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos) } : {};
    return fetch(ruta, op).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.status); return j; });
    });
  }
  function nota(id, texto, mal) { $(id).textContent = texto; $(id).className = "nota" + (mal ? " mal" : ""); }
  function esperar(id, alAcabar, idNota) {
    api("/api/trabajo?id=" + id).then(function (t) {
      if (t.estado === "en_curso") { nota(idNota, t.paso || "Trabajando…"); return setTimeout(function () { esperar(id, alAcabar, idNota); }, 4000); }
      if (t.estado === "fallido") { cargarCuenta(); return nota(idNota, "No ha salido: " + (t.motivo || "error desconocido") + (t.devuelto ? ". Te hemos devuelto los tokens." : ""), true); }
      alAcabar(t);
    }).catch(function (e) { nota(idNota, e.message, true); });
  }
  function texto(el, t) { var d = document.createElement(el); d.textContent = t; return d; }

  var planes = null, cuenta = null;
  function cargarCuenta() {
    return api("/api/cuenta").then(function (c) {
      cuenta = c; $("saldo").hidden = false;
      $("s-tokens").textContent = c.tokens.toLocaleString("es-ES") + " tokens";
      $("s-plan").textContent = "Plan " + c.plan_nombre;
      if (planes) pintarPlanes();
    });
  }
  function dentro() { $("p-entrar").hidden = true; $("p-enlace").hidden = false; return cargarCuenta(); }
  api("/api/planes").then(function (p) {
    planes = p;
    var k = p.costes;
    $("n-costes").textContent = "Analizar: " + k.analizar_por_minuto + " token por minuto de vídeo · elegir momentos: " +
      k.proponer + " · cada clip: " + k.clip + ".";
  });
  var modo = "entrar";
  var tokenReset = new URLSearchParams(location.search).get("restablecer");
  if (tokenReset) { history.replaceState(null, "", "/"); $("p-restablecer").hidden = false; }
  else api("/api/yo").then(dentro).catch(function () { $("p-entrar").hidden = false; });
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
  $("a-olvide").onclick = function (e) {
    e.preventDefault();
    if (!$("email").value) return nota("n-entrar", "Escribe tu email y vuelve a pulsar.", true);
    api("/api/olvide", { email: $("email").value }).then(function () {
      nota("n-entrar", "Si hay una cuenta con ese email, te hemos enviado un enlace para recuperarla.");
    }).catch(function (err) { nota("n-entrar", err.message, true); });
  };
  $("f-restablecer").onsubmit = function (e) {
    e.preventDefault();
    api("/api/restablecer", { token: tokenReset, clave: $("clave-nueva").value }).then(function () {
      $("p-restablecer").hidden = true; dentro();
    }).catch(function (err) { nota("n-restablecer", err.message, true); });
  };
  function pintarPlanes() {
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
  $("b-planes").onclick = function () { pintarPlanes(); $("p-planes").hidden = !$("p-planes").hidden; };
  $("b-salir").onclick = function () { api("/api/salir", {}).then(function () { location.reload(); }); };

  $("f-entrar").onsubmit = function (e) {
    e.preventDefault();
    api(modo === "entrar" ? "/api/entrar" : "/api/registro", { email: $("email").value, clave: $("clave").value })
      .then(function () { $("clave").value = ""; return dentro(); })
      .catch(function (err) { nota("n-entrar", err.message, true); });
  };

  $("f-enlace").onsubmit = function (e) {
    e.preventDefault();
    var b = e.target.querySelector("button"); b.disabled = true;
    nota("n-enlace", "Bajando el vídeo…");
    api("/api/analizar", { url: $("url").value }).then(function (r) {
      analisis = r.id; cargarCuenta();
      esperar(r.id, function (t) {
        nota("n-enlace", "«" + (t.fuente.titulo || "") + "»: transcrito. Claude está eligiendo los mejores momentos…");
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
      cuerpo.appendChild(texto("div", m.titulo)).style.fontWeight = "600";
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
})();
