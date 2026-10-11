# Autopublisher

End-to-end **video-publishing pipeline** for product marketing. Fixed engine, variable context — the same engine ships clips for any product, you only touch the context file.

Built for short-form video platforms (TikTok, Instagram Reels, YouTube Shorts) with the design goal of **the product never deriving across clips** while atrezzo (props, scenery) varies.

## How it works

Everything that changes product-to-product lives in a single file (`contexto.json`):

```
contexto.json
  producto      — what we're selling, what it can never drift into
  atrezzo       — what we show it on, and where that library lives
  negativos     — hard constraints enforced on every generation
  referencia    — which reference account to pull video patterns from
  publicación   — which channels to post to
```

Supporting assets:

- `assets/videos.json` — the pool of generated clips with the product variant tagged on each.
- `marcas/brands.json` — the atrezzo library.

## Pipeline stages

| Stage | Directory | Responsibility |
|---|---|---|
| **Ingesta** | `ingesta/` | Pull reference videos from the configured source account. |
| **Clipper** | `clipper/` | Cut, trim, enforce aspect ratio, extract style. |
| **Motor** | `motor/` | Build the prompt (identity → change → action → negatives) and generate the clip. |
| **Fase 0** | `fase0/` | Pre-flight QA: product fidelity, atrezzo variance, duration. |
| **Marca** | `marca/`, `marcas/` | Brand library management (currently bottles as atrezzo for an LED topper lamp). |
| **Analítica** | `analitica/` | Post-publish performance tracking by variant. |
| **Publicar** | `publicar/` | Multi-channel scheduler and dispatcher. |
| **Tablero** | `tablero.html` | Static dashboard for the whole queue + results. |

## Design notes

- The **QA priority is product fidelity**: the engine can let atrezzo blur or vary, but the hero product (the LED topper lamp) must never derive — a soft dome instead of a precise topper breaks the ad.
- The **winning format cycles atrezzo on purpose**: three different bottles in four seconds visually says "fits whatever you already have". Variety is the message, not decoration.
- A single `contexto.json` means swapping to a new product (different hero, different atrezzo library, different reference account) is a configuration change, not a code change.

## Tech

- Python for the pipeline (`construir.py` is the main entry point).
- HTML dashboards for the queue (`autopublisher.html`, `tablero.html`).
- JSON-driven configuration throughout — no hard-coded brand or product.
- Local-first: everything runs on one machine, with the dashboard served statically.

## Status

Internal tool. Not accepting external contributions.
