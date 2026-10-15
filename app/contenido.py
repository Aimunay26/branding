"""Carga del contenido editable (arquetipos, test, módulos, referentes).

Todo el contenido vive en JSON bajo contenido/ para poder reescribir preguntas,
paletas o referentes sin tocar una línea de Python.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
DIR_CONTENIDO = RAIZ / "contenido"


def _cargar(nombre: str) -> dict[str, Any]:
    ruta = DIR_CONTENIDO / nombre
    if not ruta.exists():
        raise FileNotFoundError(
            f"Falta el fichero de contenido {ruta}. "
            f"El contenido vive en {DIR_CONTENIDO} y no se genera solo."
        )
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def arquetipos() -> dict[str, Any]:
    """Devuelve {'fichas': {id: ficha}, 'familias': {...}, 'lista': [...]}."""
    datos = _cargar("arquetipos.json")
    fichas = {a["id"]: a for a in datos["arquetipos"]}
    return {
        "fichas": fichas,
        "familias": datos["familias"],
        "lista": datos["arquetipos"],
    }


@lru_cache(maxsize=1)
def test_arquetipos() -> dict[str, Any]:
    return _cargar("test_arquetipos.json")


@lru_cache(maxsize=1)
def referentes() -> list[dict[str, Any]]:
    return _cargar("referentes.json")["referentes"]


@lru_cache(maxsize=1)
def modulos() -> dict[str, dict[str, Any]]:
    return {
        "comunicacion": _cargar("modulo_comunicacion.json"),
        "visual": _cargar("modulo_visual.json"),
        "acciones": _cargar("modulo_acciones.json"),
    }


@lru_cache(maxsize=1)
def lexico_evasion() -> dict[str, Any]:
    """Léxico de evasión, mínimos por pregunta de texto y tope de parecido.

    Lo leen scoring.calidad_textos y form.js (vía /api/contenido): es la tabla que
    hace medible «esto no dice nada». Vive en JSON y no en Python a propósito, porque
    es una lista negra que se amplía leyendo respuestas reales, no una constante.
    """
    return _cargar("lexico_evasion.json")


@lru_cache(maxsize=1)
def nombres() -> dict[str, Any]:
    """Apellidos comunes y territorios para las sugerencias de nombre de marca.

    Lo consume form.js vía /api/contenido. Vivía duplicado en el JavaScript, y
    dos copias de la misma tabla se separan el día que alguien edita una: las
    sugerencias seguían saliendo de la copia vieja sin avisar de nada.
    """
    return _cargar("nombres.json")


@lru_cache(maxsize=1)
def categoria() -> dict[str, Any]:
    """Tablas de contraste con la categoría, para indice_distincion.

    Traducen lo que la persona dice de su sector (COM-CX-3/4/5) a algo comparable
    valor a valor con lo que dice de sí misma (VIS-CR-3, ACC-CT-2 y las cuatro
    bipolares de tono). Sin este fichero el índice de distinción no es calculable.
    """
    return _cargar("categoria.json")


def referentes_afines(
    primario: str,
    secundario: str | None = None,
    terciario: str | None = None,
    limite: int = 6,
    max_por_arquetipo: int = 2,
) -> list[dict[str, Any]]:
    """Referentes afines al arquetipo del usuario, con diversidad forzada.

    Ordenar por afinidad a secas llena la lista de un solo arquetipo: un
    Creador+Mago acabaría viendo seis Creadores y ningún Mago, que es justo la
    mitad que le falta. Por eso limitamos cuántos referentes pueden compartir
    arquetipo primario, y solo relajamos el tope si no hay material suficiente.
    """
    objetivo = {primario} | ({secundario} if secundario else set()) | (
        {terciario} if terciario else set()
    )

    def puntuar(ref: dict[str, Any]) -> tuple[int, int]:
        puntos = 0
        if ref["arquetipo_primario"] == primario:
            puntos += 10
        elif ref["arquetipo_primario"] == secundario:
            puntos += 7
        elif ref["arquetipo_primario"] in objetivo:
            puntos += 5
        puntos += 3 * len(objetivo & set(ref.get("arquetipos_secundarios", [])))
        # A igualdad, primero los que tienen foto con licencia libre.
        tiene_imagen = 1 if ref.get("imagen", {}).get("verificada") else 0
        return (puntos, tiene_imagen)

    candidatos = [r for r in referentes() if puntuar(r)[0] > 0]
    candidatos.sort(key=puntuar, reverse=True)

    elegidos: list[dict[str, Any]] = []
    usados: dict[str, int] = {}

    for tope in (max_por_arquetipo, len(candidatos)):  # segunda pasada sin tope
        for ref in candidatos:
            if len(elegidos) >= limite:
                break
            if ref in elegidos:
                continue
            arq = ref["arquetipo_primario"]
            if usados.get(arq, 0) >= tope:
                continue
            elegidos.append(ref)
            usados[arq] = usados.get(arq, 0) + 1
        if len(elegidos) >= limite:
            break

    return elegidos


def recargar() -> None:
    """Vacía la caché. Útil en desarrollo tras editar un JSON."""
    for fn in (arquetipos, test_arquetipos, referentes, modulos, lexico_evasion, categoria, nombres):
        fn.cache_clear()
