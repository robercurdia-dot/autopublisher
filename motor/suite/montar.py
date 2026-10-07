#!/usr/bin/env python3
"""Monta la página de la suite: el tablero original del Autopublisher dentro
de la suite (suite.css + vistas.html + suite.js), con la piel Frutiger Aero.

El tablero original (tablero_original.html) no está en el repo: lleva
incrustados vídeos de referencia de terceros. Se baja del artifact.

    python3 motor/suite/montar.py   →  motor/suite/autopublisher_suite.html
"""
from pathlib import Path

AQUI = Path(__file__).resolve().parent

PIEL_TABLERO = '''  /* ---- piel Aero para el tablero: cristal claro sobre cielo ---- */
  :root[data-paleta="aero"] {
    color-scheme: light;
    --ground:      #D9F1FB;
    --lienzo:      #EEF9FE;
    --punto:       #BCDDEC;
    --surface:     rgba(255,255,255,.80);
    --surface-2:   rgba(222,242,251,.92);
    --ink:         #0F2E45;
    --ink-soft:    #3D6178;
    --ink-faint:   #6E8FA3;
    --line:        rgba(15,46,69,.11);
    --line-strong: rgba(15,46,69,.22);

    --verde:       #2E9E35;
    --ambar:       #0B93DC;
    --cobre:       #17A99B;
    --ladrillo:    #D9472A;
    --azul:        #1C7FD1;

    --ok-bg:       #E1F7D6;
    --ok-fg:       #23701F;
    --stop-bg:     #FFE6DF;
    --stop-fg:     #A33519;
    --espera-bg:   #FFF4D2;
    --espera-fg:   #7A5600;
    --gris-bg:     rgba(15,46,69,.07);
    --gris-fg:     #4F6F82;

    --display: "Mukta", "Segoe UI", -apple-system, sans-serif;
    --body:    "Mukta", "Segoe UI", -apple-system, sans-serif;
    --mono:    "JetBrains Mono", ui-monospace, Menlo, monospace;
  }

'''


def montar():
    s = (AQUI / "tablero_original.html").read_text(encoding="utf-8")
    s = s.replace("&display=swap", "&family=Mukta:wght@400;600;700&display=swap", 1)
    i = s.index("  /* ---- paleta Guagua: azul saturado")
    j = s.index("  * { box-sizing: border-box; }", i)
    s = s[:i] + PIEL_TABLERO + s[j:]
    s = s.replace('[data-paleta="guagua"]', '[data-paleta="aero"]')
    s = s.replace('raiz.setAttribute("data-paleta", "guagua")', 'raiz.setAttribute("data-paleta", "aero")')
    s = s.replace('var guardada = "lampara";', 'var guardada = "guagua";')
    s = s.replace('guardada = localStorage.getItem("paleta") || "lampara"', 'guardada = "guagua"')

    a = s.index('<div class="app">')
    b = s.index("<script>", a)
    tablero = s[a:b].rstrip()
    vistas = (AQUI / "vistas.html").read_text(encoding="utf-8").replace("<!--TABLERO-->", tablero)
    s = s[:a] + (AQUI / "suite.css").read_text(encoding="utf-8") + "\n" + vistas + "\n\n" + s[b:]
    fin = s.rindex("</body>")
    s = s[:fin] + (AQUI / "suite.js").read_text(encoding="utf-8") + "\n" + s[fin:]
    (AQUI / "autopublisher_suite.html").write_text(s, encoding="utf-8")
    return len(s)


if __name__ == "__main__":
    print(f"{montar():,} bytes")
