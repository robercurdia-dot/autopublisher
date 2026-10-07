<script>
/* Suite: navegación entre herramientas y las herramientas que hablan con el
   motor local (host:autopublisher) a través de la capacidad mcp. */
(function () {
  "use strict";
  var SERVIDOR = "host:autopublisher";
  var mcp = null;
  var conectado = false;
  var miniaturas = {};          // ruta -> dataURL | "pendiente" | "error"
  var ultimos = [];             // últimos trabajos recibidos
  var dejarDeMirar = null;
  var tableroAjustado = false;

  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, hijos) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") n.className = attrs[k];
      else if (k === "text") n.textContent = attrs[k];
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
      else n.setAttribute(k, attrs[k]);
    });
    (hijos || []).forEach(function (h) { if (h) n.appendChild(typeof h === "string" ? document.createTextNode(h) : h); });
    return n;
  }

  /* ---------------- navegación ---------------- */

  var VISTAS = ["clipper", "autopublisher", "motor"];
  function mostrar(v) {
    if (VISTAS.indexOf(v) < 0) v = "clipper";
    VISTAS.forEach(function (x) { $("v-" + x).hidden = x !== v; });
    document.querySelectorAll("nav.rail button[data-vista]").forEach(function (b) {
      if (b.getAttribute("data-vista") === v) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    try { localStorage.setItem("suite.vista", v); } catch (e) {}
    if (v === "autopublisher" && !tableroAjustado) {
      // El tablero se encuadra midiendo su lienzo; oculto medía cero.
      tableroAjustado = true;
      requestAnimationFrame(function () { var b = $("b-ajustar"); if (b) b.click(); });
    }
    if (v === "motor" && conectado) cargarMotor();
  }
  document.querySelectorAll("nav.rail button[data-vista]").forEach(function (b) {
    b.addEventListener("click", function () { mostrar(b.getAttribute("data-vista")); });
  });
  var inicial = (location.hash || "").replace("#", "");
  if (VISTAS.indexOf(inicial) < 0) { try { inicial = localStorage.getItem("suite.vista") || "clipper"; } catch (e) { inicial = "clipper"; } }
  mostrar(inicial);

  /* ---------------- conexión con el motor ---------------- */

  function marcarConexion(estado, texto) {
    var c = $("conexion");
    c.className = "conexion" + (estado === "ok" ? " ok" : estado === "mal" ? " mal" : "");
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
      case "server_not_connected":
      case "not_granted":
      case "capability_disabled":
      case "capability_removed":
        return { titulo: "El motor no responde", texto: "Esta página no llega al motor de tu Mac.", pasos: true, caido: true };
      case "not_in_manifest":
        return { titulo: "El motor está desactivado para esta página", texto: "Se rechazó el permiso para usarlo. Puedes volver a darlo desde el menú Permisos de la página.", caido: true };
      case "cancelled":
        return { titulo: "Cancelado", texto: "No se confirmó la acción en la app, así que no se ha hecho nada." };
      case "server_unavailable":
        return { titulo: "El motor tarda en contestar", texto: "Puede que esté arrancando. Prueba de nuevo en unos segundos." };
      case "tool_error":
        return { titulo: "El motor devolvió un error", texto: (err.message || "").slice(0, 300) };
      default:
        return { titulo: "Algo falló al hablar con el motor", texto: (err && err.message ? err.message : code).slice(0, 300) };
    }
  }

  function conectar() {
    var usar = window.claude && typeof window.claude.use === "function" ? window.claude.use("mcp") : Promise.resolve(null);
    usar.then(function (ns) {
      mcp = ns;
      if (!mcp) {
        marcarConexion("mal", "sin motor");
        avisar("El motor no responde", "Esta vista no puede usar el motor local.", true);
        return;
      }
      mirarTrabajos();
    }).catch(function () {
      marcarConexion("mal", "sin motor");
      avisar("El motor no responde", "Esta vista no puede usar el motor local.", true);
    });
  }

  function alConectar() {
    if (conectado) return;
    conectado = true;
    marcarConexion("ok", "motor conectado");
    $("aviso-motor").hidden = true;
    $("c-enviar").disabled = false;
    $("c-actualizar").disabled = false;
    $("m-actualizar").disabled = false;
    if (!$("v-motor").hidden) cargarMotor();
  }

  function alCaer(err) {
    var e = explicar(err);
    if (e.caido) {
      conectado = false;
      marcarConexion("mal", "sin motor");
      $("c-enviar").disabled = true;
    }
    avisar(e.titulo, e.texto, e.pasos);
  }

  /* ---------------- clipper: trabajos ---------------- */

  function mirarTrabajos() {
    if (dejarDeMirar) dejarDeMirar();
    dejarDeMirar = mcp.watchTool(SERVIDOR, "trabajos", { limite: 20 }, function (ev) {
      if (ev.type === "data") {
        alConectar();
        var p = ev.result.payload || {};
        ultimos = p.trabajos || [];
        pintarTrabajos();
      } else {
        alCaer(ev.error);
      }
    }, { refetchInterval: 30000 });
  }

  function hace(t) {
    var s = Math.max(0, Date.now() / 1000 - t);
    if (s < 60) return "ahora";
    if (s < 3600) return "hace " + Math.round(s / 60) + " min";
    if (s < 86400) return "hace " + Math.round(s / 3600) + " h";
    return "hace " + Math.round(s / 86400) + " d";
  }
  function mmss(s) { s = Math.round(s); return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2); }
  function fuente(url) {
    try { var u = new URL(url); return u.hostname.replace(/^www\./, "") + u.pathname.replace(/\/$/, "") + (u.search ? u.search.slice(0, 16) : ""); }
    catch (e) { return url; }
  }

  var ESTADOS = { en_curso: ["curso", "en curso"], terminado: ["ok", "terminado"], fallido: ["stop", "fallido"] };

  function pintarTrabajos() {
    var cont = $("lista-trabajos");
    cont.textContent = "";
    if (!ultimos.length) {
      cont.appendChild(el("div", { class: "vacio-lista" }, [
        el("b", { text: "Todavía no hay trabajos." }),
        "Pega un enlace a la izquierda y pulsa «Sacar clips». En unos minutos aparecen aquí."]));
      return;
    }
    ultimos.forEach(function (t) {
      var est = ESTADOS[t.estado] || ["gris", t.estado];
      var art = el("article", { class: "trabajo" }, [
        el("div", { class: "trabajo-cab" }, [
          el("span", { class: "pin " + est[0], text: est[1] }),
          el("a", { class: "fuente", href: t.url, target: "_blank", rel: "noopener", text: fuente(t.url) }),
          el("span", { class: "cuando", text: hace(t.creado) })
        ])
      ]);
      if (t.estado === "en_curso" && t.registro && t.registro.length) {
        art.appendChild(el("pre", { class: "registro-t", text: t.registro.slice(-5).join("\n") }));
      }
      if (t.estado === "fallido") art.appendChild(el("div", { class: "motivo", text: t.motivo || "Falló sin dejar motivo." }));
      if (t.clips && t.clips.length) {
        var rej = el("div", { class: "clips" });
        t.clips.forEach(function (c) { rej.appendChild(tarjetaClip(c)); });
        art.appendChild(rej);
        var carpeta = (t.clips[0].archivos || [])[0];
        if (carpeta) art.appendChild(el("div", { class: "acciones" }, [
          el("button", { type: "button", class: "cristal-btn", text: "Abrir la carpeta", onclick: function () { abrir(carpeta, true); } })
        ]));
      }
      cont.appendChild(art);
    });
  }

  function tarjetaClip(c) {
    var ruta = (c.archivos || [])[0];
    var img = el("img", { alt: "Fotograma del clip " + c.n, loading: "lazy" });
    var marco = el("div", { class: "marco-clip" }, [img, el("span", { class: "dur", text: mmss(c.fin - c.ini) })]);
    if (c.publicado) marco.appendChild(el("span", { class: "pin ok pub", text: "publicado" }));
    pedirMiniatura(ruta, img);
    var acciones = el("div", { class: "acciones" }, [
      el("button", { type: "button", class: "cristal-btn", text: "Ver", onclick: function () { abrir(ruta, false); } })
    ]);
    (c.archivos || []).slice(1).forEach(function (r) {
      acciones.appendChild(el("button", { type: "button", class: "cristal-btn", text: /_fondo/.test(r) ? "Con fondo" : "Otra versión", onclick: function () { abrir(r, false); } }));
    });
    var texto = c.texto || "";
    return el("div", { class: "clip" }, [
      marco,
      el("div", { class: "datos" }, [
        el("span", { class: "puntos", text: c.puntos != null ? c.puntos.toFixed(2) : "–" }),
        el("span", { text: "· " + Math.round(c.ini) + "–" + Math.round(c.fin) + " s" }),
        el("span", { class: "pin gris", text: c.encuadre || "original" })
      ]),
      texto ? el("details", {}, [el("summary", { text: "«" + texto + "»" })]) : null,
      acciones
    ]);
  }

  function pedirMiniatura(ruta, img) {
    if (!ruta) return;
    var m = miniaturas[ruta];
    if (m && m !== "pendiente" && m !== "error") { img.src = m; return; }
    if (m === "pendiente") { (pedirMiniatura.espera[ruta] = pedirMiniatura.espera[ruta] || []).push(img); return; }
    miniaturas[ruta] = "pendiente";
    pedirMiniatura.espera[ruta] = [img];
    mcp.callTool(SERVIDOR, "miniatura", { ruta: ruta, segundo: 3, ancho: 240 }, { cache: { staleTime: 300000, gcTime: 86400000 } })
      .then(function (r) {
        var p = r.payload || {};
        miniaturas[ruta] = "data:" + p.mime + ";base64," + p.base64;
        (pedirMiniatura.espera[ruta] || []).forEach(function (i) { i.src = miniaturas[ruta]; });
      })
      .catch(function () { miniaturas[ruta] = "error"; });
  }
  pedirMiniatura.espera = {};

  function abrir(ruta, carpeta) {
    if (!mcp || !ruta) return;
    mcp.callTool(SERVIDOR, "abrir", { ruta: ruta, carpeta: !!carpeta }).catch(function (err) {
      if (err && err.code === "cancelled") return;
      alCaer(err);
    });
  }

  /* ---------------- clipper: encargo ---------------- */

  $("f-clip").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var url = $("c-url").value.trim();
    var nota = $("c-nota");
    nota.className = "nota-envio";
    if (!/^https?:\/\/\S+$/.test(url)) {
      nota.className = "nota-envio mal";
      nota.textContent = "Pega un enlace completo, empezando por https://.";
      $("c-url").focus();
      return;
    }
    var args = { url: url, cuantos: parseInt($("c-cuantos").value, 10), sesion_chrome: $("c-chrome").checked };
    if ($("c-dur").value) args.duracion = parseFloat($("c-dur").value);
    if ($("c-vocab").value.trim()) args.vocabulario = $("c-vocab").value.trim();
    if ($("c-fondo").value.trim()) args.fondo = $("c-fondo").value.trim();
    var boton = $("c-enviar");
    boton.disabled = true;
    nota.textContent = "Enviando al motor… si la app pide confirmarlo, acéptalo.";
    mcp.callTool(SERVIDOR, "clipear", args).then(function () {
      nota.textContent = "En marcha. Aparece arriba en Trabajos y se actualiza solo.";
      $("c-url").value = "";
      return mcp.invalidate(SERVIDOR, "trabajos").catch(function () {});
    }).catch(function (err) {
      nota.className = "nota-envio mal";
      var e = explicar(err);
      nota.textContent = e.titulo + ". " + e.texto;
      if (e.caido) alCaer(err);
    }).then(function () { boton.disabled = !conectado; });
  });

  $("c-actualizar").addEventListener("click", function () {
    if (mcp) mcp.invalidate(SERVIDOR, "trabajos").catch(function () {});
  });

  /* ---------------- motor ---------------- */

  function fila(k, v, clase) {
    return el("div", { class: "fila-m" }, [el("span", { class: "k", text: k }),
      clase ? el("span", { class: "pin " + clase, text: v }) : el("span", { class: "v", text: v })]);
  }

  function cargarMotor() {
    if (!mcp) return;
    mcp.callTool(SERVIDOR, "estado", {}, { cache: { refresh: true } }).then(function (r) {
      var e = r.payload || {};
      var cont = $("paneles-motor");
      cont.textContent = "";
      cont.appendChild(el("div", { class: "panel-m" }, [
        el("h2", { text: "Capacidades" }),
        fila("Subtítulos (whisper + libass)", e.subtitulos ? "listo" : "falta", e.subtitulos ? "ok" : "stop"),
        fila("Recorte sobre la cara", e.caras ? "listo" : "falta", e.caras ? "ok" : "stop"),
        fila("Generar con fal", (e.generacion || {}).fal || "?", "stop"),
        fila("Generar con Flashboards", (e.generacion || {}).flashboards || "?", "stop"),
        fila("Enmiendas activas", String(e.enmiendas_activas))
      ]));
      var cuentas = el("div", { class: "panel-m" }, [el("h2", { text: "Cuentas" })]);
      Object.keys(e.cuentas || {}).forEach(function (k) {
        var c = e.cuentas[k];
        cuentas.appendChild(fila(k.replace("_", " ") + (c.nombre ? " · " + c.nombre : ""),
          (c.estado || "?") + " · " + (c.via || "?")));
      });
      cont.appendChild(cuentas);
      var errs = e.errores_clipper || [];
      var abiertos = errs.filter(function (x) { return x.pendiente; });
      var panel = el("div", { class: "panel-m" }, [
        el("h2", { text: "Errores del clipper" }),
        fila("Registrados, cada uno con su test", String(errs.length)),
        fila("Con algo pendiente", String(abiertos.length), abiertos.length ? "espera" : "ok")
      ]);
      abiertos.forEach(function (x) { panel.appendChild(fila(x.id.replace(/_/g, " "), "pendiente", "espera")); });
      cont.appendChild(panel);
    }).catch(alCaer);
  }
  $("m-actualizar").addEventListener("click", cargarMotor);

  conectar();
})();
</script>
