"""Paletas de color deterministas, fieles a lo que el usuario declaró.

El fallo que esto arregla: antes la paleta del informe salía SOLO de la ficha del
arquetipo primario. Si elegías verde como tu color, te salía el burdeos del
Amante y ni rastro del verde. Aquí el color que declaraste (VIS-CR-3) es el
protagonista, sí o sí, y lo que vetaste (VIS-CR-2) no aparece en ninguna paleta.

Se generan tres paletas, no una:
  1. «La tuya»        — tu color de dominante, con acentos del arquetipo que no vetes.
  2. «La del arquetipo» — la del arquetipo puro, pero filtrando tus vetos.
  3. «La polarizante»  — tu color llevado al extremo + negro + blanco. La que divide.

Nada de IA: es reproducible y auditable. La IA solo las justifica después.
"""

from __future__ import annotations

import colorsys
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
DIR_CONTENIDO = RAIZ / "contenido"

# Respuestas de las que sale el color, del módulo visual.
PREGUNTA_MI_COLOR = "VIS-CR-3"      # unica: el color con el que quiero que me asocien
PREGUNTA_VETOS = "VIS-CR-2"         # multiple: los colores que NO me pondría


@lru_cache(maxsize=1)
def _datos() -> dict[str, Any]:
    with (DIR_CONTENIDO / "colores.json").open(encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ clasificación

def _hsl(hexc: str) -> tuple[float, float, float]:
    """hex #RRGGBB -> (hue 0-360, saturación 0-1, luminosidad 0-1)."""
    h = hexc.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    return hh * 360, ss, ll


def _hue_familia(h: float) -> str:
    """Nombre de la familia de tono para un ángulo de matiz."""
    tabla = [
        (15, "rojo"), (45, "naranja"), (70, "amarillo"), (160, "verde"),
        (200, "cian"), (255, "azul"), (290, "morado"), (335, "rosa"), (360, "rojo"),
    ]
    for tope, nombre in tabla:
        if h < tope:
            return nombre
    return "rojo"


def clasificar(hexc: str) -> set[str]:
    """Etiquetas de familia de un color, para comparar y para vetar.

    Devuelve un conjunto que puede mezclar tono ('verde') y acabado ('vivo',
    'pastel', 'neon', 'tierra', 'negro', 'blanco', 'gris'). El veto compara contra
    este conjunto: si tocas cualquiera de sus etiquetas, el color cae.
    """
    h, s, l = _hsl(hexc)
    tags: set[str] = set()

    # Acromáticos: mandan sobre el tono.
    if s < 0.12:
        if l < 0.20:
            tags.add("negro")
        elif l > 0.85:
            tags.add("blanco")
        else:
            tags.add("gris")
        return tags

    tags.add(_hue_familia(h))
    if l < 0.18:
        tags.add("negro")
    if s > 0.85 and l > 0.55:
        tags.add("neon")
    if s > 0.60 and 0.28 < l < 0.72:
        tags.add("vivo")
    if l > 0.75 and s < 0.65:
        tags.add("pastel")
    # Tierra: matiz cálido, poco saturado, ni muy claro ni muy oscuro.
    if 15 <= h <= 65 and s < 0.55 and 0.20 < l < 0.68:
        tags.add("tierra")
    return tags


def _hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, max(0, min(1, l)), max(0, min(1, s)))
    return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))


# ------------------------------------------------------------------ generación

def _familias_vetadas(respuestas_visual: dict[str, Any]) -> set[str]:
    vetos = respuestas_visual.get(PREGUNTA_VETOS) or []
    if not isinstance(vetos, list):
        vetos = [vetos]
    mapa = _datos()["vetos"]
    familias: set[str] = set()
    for v in vetos:
        familias.update(mapa.get(v, []))
    return familias


def _vetado(hexc: str, vetadas: set[str]) -> bool:
    return bool(clasificar(hexc) & vetadas)


def _color(hexc: str, nombre: str, rol: str) -> dict[str, str]:
    return {"hex": hexc.upper(), "nombre": nombre, "rol": rol}


def _neutro_seguro(vetadas: set[str], preferir_claro: bool) -> dict[str, str]:
    d = _datos()["neutros_seguros"]
    orden = ("claro", "oscuro", "medio") if preferir_claro else ("oscuro", "claro", "medio")
    for clave in orden:
        n = d[clave]
        if not _vetado(n["hex"], vetadas):
            return _color(n["hex"], n["nombre"], "neutro")
    n = d["medio"]
    return _color(n["hex"], n["nombre"], "neutro")


def generar(
    respuestas_visual: dict[str, Any], ficha_primaria: dict[str, Any]
) -> list[dict[str, Any]]:
    """Devuelve las tres paletas. `respuestas_visual` = estado['visual']."""
    datos = _datos()
    vetadas = _familias_vetadas(respuestas_visual)
    paleta_arq = ficha_primaria.get("visual", {}).get("paleta", [])

    declarado_val = respuestas_visual.get(PREGUNTA_MI_COLOR)
    declarado = datos["colores_declarados"].get(declarado_val)

    paletas = [
        _paleta_tuya(declarado, paleta_arq, vetadas),
        _paleta_arquetipo(paleta_arq, vetadas),
        _paleta_polarizante(declarado, vetadas),
    ]
    return [p for p in paletas if p and p["colores"]]


def _acentos_arquetipo(
    paleta_arq: list[dict[str, Any]], vetadas: set[str], excluir_tono: str | None
) -> list[dict[str, str]]:
    """Colores de la ficha que sobreviven al veto, sin repetir el tono dominante."""
    salida: list[dict[str, str]] = []
    for c in paleta_arq:
        hexc = c.get("hex", "")
        if not hexc or _vetado(hexc, vetadas):
            continue
        if excluir_tono and excluir_tono in clasificar(hexc):
            continue
        salida.append(_color(hexc, c.get("nombre", ""), c.get("rol", "secundario")))
    return salida


def _paleta_tuya(
    declarado: dict[str, Any] | None,
    paleta_arq: list[dict[str, Any]],
    vetadas: set[str],
) -> dict[str, Any]:
    """Tu color de protagonista; el arquetipo pasa a acompañamiento."""
    colores: list[dict[str, str]] = []
    tono_dom: str | None = None

    if declarado and not declarado.get("monocromo"):
        tono_dom = _hue_familia(declarado["hue"])
        colores.append(_color(declarado["hex"], declarado["nombre"], "dominante"))
    elif declarado and declarado.get("monocromo"):
        # «Solo blanco y negro»: dominante negro, base blanca.
        colores.append(_color("#111111", "Negro tinta", "dominante"))
        colores.append(_neutro_seguro(vetadas, preferir_claro=True))
    else:
        # No declaró color: caemos al dominante del arquetipo (sin veto).
        for c in paleta_arq:
            if not _vetado(c["hex"], vetadas):
                colores.append(_color(c["hex"], c.get("nombre", ""), "dominante"))
                tono_dom = next(iter(clasificar(c["hex"]) & {
                    "rojo", "naranja", "amarillo", "verde", "cian", "azul", "morado", "rosa"}), None)
                break

    for c in _acentos_arquetipo(paleta_arq, vetadas, excluir_tono=tono_dom):
        if len(colores) >= 5:
            break
        if c["hex"] not in {x["hex"] for x in colores}:
            colores.append(c)

    if not any(c["rol"] == "neutro" for c in colores) and len(colores) < 5:
        colores.append(_neutro_seguro(vetadas, preferir_claro=True))

    # Solo el color declarado manda: lo demás que venía como 'dominante' del
    # arquetipo baja a acompañamiento.
    for c in colores[1:]:
        if c["rol"] == "dominante":
            c["rol"] = "secundario"

    return {
        "id": "tuya",
        "nombre": "La tuya",
        "subtitulo": "Tu color de protagonista. Fiel a lo que elegiste.",
        "colores": colores[:5],
    }


def _paleta_arquetipo(
    paleta_arq: list[dict[str, Any]], vetadas: set[str]
) -> dict[str, Any]:
    """La del arquetipo puro, filtrando los vetos (reemplazando lo caído)."""
    colores: list[dict[str, str]] = []
    reemplazos = 0
    for c in paleta_arq:
        hexc = c.get("hex", "")
        if not hexc:
            continue
        if _vetado(hexc, vetadas):
            reemplazos += 1
            continue
        colores.append(_color(hexc, c.get("nombre", ""), c.get("rol", "secundario")))

    # Si el veto vació la paleta, la rellenamos con neutros seguros.
    while len(colores) < 3:
        n = _neutro_seguro(vetadas, preferir_claro=len(colores) % 2 == 0)
        if n["hex"] in {x["hex"] for x in colores}:
            break
        colores.append(n)

    sub = "La del arquetipo puro."
    if reemplazos:
        sub = f"La del arquetipo, con {reemplazos} color(es) fuera por tus vetos."
    return {
        "id": "arquetipo",
        "nombre": "La del arquetipo",
        "subtitulo": sub,
        "colores": colores[:5],
    }


def _paleta_polarizante(
    declarado: dict[str, Any] | None, vetadas: set[str]
) -> dict[str, Any]:
    """Tu color saturado al máximo + negro + blanco. Sin medias tintas."""
    colores: list[dict[str, str]] = []

    if declarado and declarado.get("hue") is not None:
        vivo = _hex(declarado["hue"], 1.0, 0.5)
        colores.append(_color(vivo, f"{declarado['nombre']} al máximo", "dominante"))
    elif declarado and declarado.get("monocromo"):
        colores.append(_color("#D7261E", "Rojo señal", "acento"))

    # Negro y blanco como contraste extremo, salvo veto.
    if "negro" not in vetadas:
        colores.append(_color("#0D0D0D", "Negro absoluto", "neutro"))
    else:
        # Sustituto del negro vetado: un grafito que ya no lee como negro.
        colores.append(_color("#474440", "Grafito", "neutro"))
    if "blanco" not in vetadas:
        colores.append(_color("#FFFFFF", "Blanco puro", "neutro"))
    else:
        colores.append(_color("#EDEAE3", "Piedra clara", "neutro"))

    if not colores:
        return {"id": "polarizante", "nombre": "La polarizante", "subtitulo": "", "colores": []}

    return {
        "id": "polarizante",
        "nombre": "La polarizante",
        "subtitulo": "Tu color al extremo, sin puntos medios. La que te hace memorable — o te trae enemigos.",
        "colores": colores,
    }


def recargar() -> None:
    _datos.cache_clear()
