"""Fixtures y fabricantes de respuestas para toda la suite.

Dos criterios que explican por qué esto está montado así:

1. Contra contenido REAL donde el contenido es el sujeto de la prueba (los ids,
   las opciones, el número de ítems por arquetipo) y contra contenido SINTÉTICO
   donde lo que se prueba es la fórmula (umbrales de tibieza, pesos). Una prueba
   de umbrales contra los 131 ítems reales se rompe cada vez que alguien añade
   una pregunta, y entonces se borra en vez de arreglarse.

2. Nada aquí importa app.informe, app.pdf ni app.main: esa cadena arrastra
   WeasyPrint, que en esta máquina no importa porque falta GTK. La suite tiene
   que poder ejecutarse sin eso.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

DIR_CONTENIDO = RAIZ / "contenido"


# ------------------------------------------------------------------ contenido real

@pytest.fixture(scope="session")
def contenido():
    from app import contenido as mod

    return mod


@pytest.fixture(scope="session")
def test_arq(contenido) -> dict[str, Any]:
    return contenido.test_arquetipos()


@pytest.fixture(scope="session")
def fichas(contenido) -> dict[str, Any]:
    """El mapa {id: ficha}, que es lo que `puntuar_arquetipos` indexa por id.

    Ojo: `contenido.arquetipos()` devuelve {'fichas', 'familias', 'lista'} y lo
    que el motor quiere es la clave 'fichas'. Pasarle el envoltorio entero
    revienta con un KeyError en la primera sombra que calcule.
    """
    return contenido.arquetipos()["fichas"]


@pytest.fixture(scope="session")
def familias(contenido) -> dict[str, Any]:
    return contenido.arquetipos()["familias"]


@pytest.fixture(scope="session")
def mods(contenido) -> dict[str, Any]:
    return contenido.modulos()


@pytest.fixture(scope="session")
def lexico(contenido) -> dict[str, Any]:
    return contenido.lexico_evasion()


# ------------------------------------------------------------------ utilidades

def preguntas_de(modulo: dict[str, Any]) -> list[dict[str, Any]]:
    """Todas las preguntas de un módulo, aplanando los bloques."""
    return [p for b in modulo.get("bloques", []) for p in b.get("preguntas", [])]


def todas_las_preguntas(mods: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(clave, p) for clave, m in mods.items() for p in preguntas_de(m)]


def centro_bipolar(pregunta: dict[str, Any]) -> float:
    """El punto muerto de ESTA bipolar, no el de la constante.

    Se calcula por pregunta a propósito: el día que entre una bipolar de escala 5
    el centro es 3, y una constante global lo daría por 4 sin avisar.
    """
    return (pregunta.get("escala", 7) + 1) / 2


# ------------------------------------------------------------------ fabricantes de respuestas del test

def respuestas_test_uniformes(test: dict[str, Any], valor: int) -> dict[str, int]:
    """El mismo valor a los 48 ítems. El perfil plano de manual."""
    return {it["id"]: valor for it in test["items"]}


def respuestas_test_definidas(
    test: dict[str, Any], arquetipo: str, alto: int = 5, bajo: int = 2
) -> dict[str, int]:
    """Un arquetipo arriba y los once restantes abajo."""
    return {
        it["id"]: (alto if it["arquetipo"] == arquetipo else bajo)
        for it in test["items"]
    }


# ------------------------------------------------------------------ fabricantes de respuestas de módulo

def _texto_evasivo() -> str:
    return "no sé"


def responder_al_centro(mods: dict[str, Any]) -> dict[str, Any]:
    """Contesta cada pregunta de módulo con la respuesta más escurrida posible.

    Es el sujeto que el producto entero existe para parar: el centro de todas las
    escalas, la opción de escape donde la hay, todas las casillas marcadas donde
    hay múltiple (marcar cuatro de cuatro es no elegir) y «no sé» en los textos.
    """
    salida: dict[str, Any] = {}
    for clave, modulo in mods.items():
        seccion: dict[str, Any] = {}
        for p in preguntas_de(modulo):
            tipo = p.get("tipo")
            if tipo == "likert5":
                seccion[p["id"]] = 3
            elif tipo == "bipolar":
                seccion[p["id"]] = centro_bipolar(p)
            elif tipo == "unica":
                evasivas = [o["valor"] for o in p.get("opciones", []) if o.get("evasiva")]
                opciones = [o["valor"] for o in p.get("opciones", [])]
                seccion[p["id"]] = evasivas[0] if evasivas else (opciones[0] if opciones else None)
            elif tipo == "multiple":
                opciones = [o["valor"] for o in p.get("opciones", [])]
                tope = int(p.get("max", len(opciones)) or len(opciones))
                seccion[p["id"]] = opciones[:tope]
            elif tipo == "ranking":
                seccion[p["id"]] = []  # incompleto: renunciar a renunciar
            elif tipo == "reparto100":
                opciones = [o["valor"] for o in p.get("opciones", [])]
                if opciones:
                    reparto = 100 // len(opciones)
                    seccion[p["id"]] = {v: reparto for v in opciones}
            elif tipo == "duelo":
                seccion[p["id"]] = {"elegido": "", "no_copio": ""}
            else:  # texto y texto_largo
                seccion[p["id"]] = _texto_evasivo()
        salida[clave] = seccion
    return salida


# ------------------------------------------------------------------ contenido sintético

def armar_test_sintetico(n_por_arquetipo: int = 4) -> dict[str, Any]:
    """Un test de arquetipos mínimo con la misma forma que el real.

    Sirve para probar la aritmética del motor sin depender de que el contenido
    real siga teniendo exactamente estos ítems mañana.

    El nombre empieza por «armar» y no por «test» a propósito: pytest recoge
    como prueba cualquier función `test_*` del módulo que la importe, y una
    fábrica de datos colada en el listado de pruebas es ruido puro.
    """
    arqs = ["A%02d" % i for i in range(1, 13)]
    items = [
        {"id": f"{a}-{n}", "texto": f"Ítem {n} de {a}", "arquetipo": a, "inverso": False}
        for a in arqs
        for n in range(1, n_por_arquetipo + 1)
    ]
    return {
        "escala": {"tipo": "likert5"},
        "items": items,
        "control": [
            {"id": "CTRL-1", "texto": "Marca el 2.", "valor_esperado": 2},
            {"id": "CTRL-2", "texto": "Marca el 5.", "valor_esperado": 5},
            {
                "id": "CTRL-3",
                "texto": "Control de consistencia.",
                "tipo_control": "consistencia",
                "pareja": "A01-2",
                "suma_esperada": 6,
                "tolerancia": 2,
            },
        ],
        "eleccion_forzada": [],
    }


def fichas_sinteticas(n_por_arquetipo: int = 4) -> dict[str, Any]:
    """Fichas mínimas para los doce arquetipos sintéticos.

    `puntuar_arquetipos` indexa las fichas por id para sacar el opuesto y la
    sombra: sin esto, cualquier prueba con contenido sintético muere en un
    KeyError que no tiene nada que ver con lo que se estaba probando.
    """
    arqs = ["A%02d" % i for i in range(1, 13)]
    return {
        a: {
            "id": a,
            "nombre": f"Arquetipo {a}",
            # El opuesto en la rueda: el que está seis posiciones más allá.
            "opuesto": arqs[(i + 6) % 12],
            "sombra": "se pasa de rosca.",
        }
        for i, a in enumerate(arqs)
    }


def modulo_sintetico(n: int = 10, clave: str = "comunicacion") -> dict[str, Any]:
    """Un módulo de n preguntas `unica`, cada una con una opción de escape.

    Diez preguntas para que cada respuesta escurrida valga un 10 % redondo y los
    umbrales (22 % por módulo, 20 % global) se puedan cruzar a mano.
    """
    preguntas = [
        {
            "id": f"SIN-{i}",
            "tipo": "unica",
            "texto": f"Pregunta sintética {i}",
            "opciones": [
                {"valor": "postura_a", "etiqueta": "Una postura"},
                {"valor": "postura_b", "etiqueta": "La contraria"},
                {"valor": "escape", "etiqueta": "Depende", "evasiva": True},
            ],
        }
        for i in range(1, n + 1)
    ]
    return {
        clave: {
            "id": clave,
            "nombre": "Módulo sintético",
            "bloques": [{"id": "unico", "nombre": "Bloque", "preguntas": preguntas}],
        }
    }


def respuestas_sinteticas(n: int = 10, escurridas: int = 0, clave: str = "comunicacion") -> dict[str, Any]:
    """Las `escurridas` primeras con la opción de escape; el resto con postura."""
    return {
        clave: {
            f"SIN-{i}": ("escape" if i <= escurridas else "postura_a")
            for i in range(1, n + 1)
        }
    }


# ------------------------------------------------------------------ fichas

def ficha_minima(
    paleta: list[dict[str, str]] | None = None,
    vocabulario: list[str] | None = None,
) -> dict[str, Any]:
    """Ficha de arquetipo con lo justo que leen paletas.py y activos.py."""
    return {
        "id": "CRE",
        "nombre": "El Creador",
        "visual": {
            "paleta": paleta
            if paleta is not None
            else [
                {"hex": "#2F5D50", "nombre": "Verde bosque", "rol": "dominante"},
                {"hex": "#C9A227", "nombre": "Oro viejo", "rol": "acento"},
                {"hex": "#1A1A1A", "nombre": "Negro tinta", "rol": "neutro"},
            ],
            "tipografia": {"titular": ["Playfair Display"], "texto": ["Inter"]},
        },
        "comunicacion": {
            "vocabulario": vocabulario if vocabulario is not None else ["oficio", "taller", "pieza"],
            "evitar": ["sinergia", "disrupción"],
        },
    }
