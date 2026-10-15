"""Gráficos para el informe.

Se generan como SVG inline. WeasyPrint no ejecuta JavaScript, así que cualquier
librería de gráficos de cliente (Chart.js y compañía) sale en blanco en el PDF.
Y el SVG, al ser vectorial, no pixela al ampliar y no engorda el fichero.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")  # antes de importar pyplot: sin esto intenta abrir ventana

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

TINTA = "#1A1A1A"
SUAVE = "#C9C4BC"

# El orden de la rueda no es decorativo. Está construido para que cada arquetipo
# quede a 180° de su opuesto (INO↔BUF, SAB↔AMA, EXP↔COM, FOR↔GOB, MAG↔CRE,
# HER↔CUI) y para que las cuatro familias caigan en cuadrantes contiguos. Con un
# orden arbitrario, el informe habla de "tu opuesto en la rueda" mientras el
# dibujo los pone al lado: el gráfico contradiría al texto.
ORDEN_RUEDA = [
    "INO", "SAB", "EXP",  # independencia
    "FOR", "MAG", "HER",  # maestría
    "BUF", "AMA", "COM",  # pertenencia
    "GOB", "CRE", "CUI",  # estabilidad
]


def _extraer_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)  # si no se cierra, la memoria crece en cada informe
    svg = buf.getvalue()
    return svg[svg.index("<svg") :]


def radar_arquetipos(
    puntuaciones: dict[str, float],
    nombres: dict[str, str],
    color: str = "#C1440E",
) -> str:
    """Radar de los 12 arquetipos.

    Dibujamos la línea del 50 porque, con corrección de aquiescencia, 50 es la
    media: por encima es "esto te define", por debajo "esto no va contigo". Sin
    esa referencia el radar es solo una forma bonita.
    """
    claves = [k for k in ORDEN_RUEDA if k in puntuaciones]
    claves += [k for k in puntuaciones if k not in ORDEN_RUEDA]  # por si acaso
    valores = [puntuaciones[k] for k in claves]
    etiquetas = [nombres.get(k, k) for k in claves]

    angulos = np.linspace(0, 2 * np.pi, len(claves), endpoint=False).tolist()
    valores_cerrados = valores + valores[:1]
    angulos_cerrados = angulos + angulos[:1]

    fig, ax = plt.subplots(figsize=(6.4, 6.4), subplot_kw=dict(polar=True))
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)

    ax.plot(angulos_cerrados, valores_cerrados, linewidth=2.2, color=color)
    ax.fill(angulos_cerrados, valores_cerrados, alpha=0.20, color=color)

    # Línea de la media.
    ax.plot(
        angulos_cerrados,
        [50] * len(angulos_cerrados),
        linewidth=1,
        linestyle=(0, (4, 4)),
        color=SUAVE,
    )

    ax.set_xticks(angulos)
    ax.set_xticklabels(etiquetas, fontsize=9.5, color=TINTA)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75])
    ax.set_yticklabels(["", "media", ""], fontsize=7.5, color=SUAVE)
    ax.spines["polar"].set_color(SUAVE)
    ax.spines["polar"].set_linewidth(0.8)
    ax.grid(color=SUAVE, linewidth=0.5, alpha=0.6)
    ax.set_facecolor("none")

    return _extraer_svg(fig)


def barras_familias(
    medias: dict[str, float],
    nombres: dict[str, str],
    color: str = "#C1440E",
) -> str:
    """Las 4 familias cardinales, ordenadas."""
    orden = sorted(medias.items(), key=lambda kv: kv[1])
    etiquetas = [nombres.get(k, k) for k, _ in orden]
    valores = [v for _, v in orden]

    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    barras = ax.barh(etiquetas, valores, color=color, height=0.55)
    barras[-1].set_alpha(1.0)
    for b in barras[:-1]:
        b.set_alpha(0.35)

    ax.axvline(50, color=SUAVE, linewidth=1, linestyle=(0, (4, 4)))
    ax.set_xlim(0, 100)
    ax.set_xticks([])
    ax.tick_params(axis="y", length=0, labelsize=10, colors=TINTA)
    for lado in ("top", "right", "bottom", "left"):
        ax.spines[lado].set_visible(False)

    for barra, valor in zip(barras, valores):
        ax.text(
            valor + 2,
            barra.get_y() + barra.get_height() / 2,
            f"{valor:.0f}",
            va="center",
            fontsize=9,
            color=TINTA,
        )

    ax.set_facecolor("none")
    return _extraer_svg(fig)


def barras_triangulacion(
    perfil: dict[str, float],
    afinidades: dict[str, dict[str, float]],
    nombres: dict[str, str],
    color: str = "#C1440E",
) -> str:
    """Lo que dices que eres frente a lo que eliges hacer, arquetipo a arquetipo.

    El gráfico más incómodo del informe, y por eso el más útil.
    """
    combinada: dict[str, float] = {}
    for afinidad in afinidades.values():
        for arq, valor in afinidad.items():
            combinada[arq] = combinada.get(arq, 0.0) + valor
    if not combinada:
        return ""

    total = sum(combinada.values())
    combinada = {a: 100.0 * v / total for a, v in combinada.items()}

    claves = sorted(perfil, key=perfil.get, reverse=True)[:6]
    declarado = [perfil.get(k, 0.0) for k in claves]
    # Reescalamos la afinidad a 0-100 para poder compararla visualmente.
    tope = max(combinada.values()) or 1.0
    revelado = [100.0 * combinada.get(k, 0.0) / tope for k in claves]
    etiquetas = [nombres.get(k, k) for k in claves]

    y = np.arange(len(claves))
    alto = 0.36

    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.barh(y + alto / 2, declarado, height=alto, color=color, alpha=0.9, label="Dices que eres")
    ax.barh(y - alto / 2, revelado, height=alto, color=TINTA, alpha=0.35, label="Eliges hacer")

    ax.set_yticks(y)
    ax.set_yticklabels(etiquetas, fontsize=10, color=TINTA)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([])
    ax.tick_params(axis="y", length=0)
    for lado in ("top", "right", "bottom", "left"):
        ax.spines[lado].set_visible(False)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.set_facecolor("none")

    return _extraer_svg(fig)
