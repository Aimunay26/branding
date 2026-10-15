"""Post-validación determinista de lo que devuelve el modelo.

El esquema Pydantic obliga a que la respuesta tenga la FORMA correcta. No obliga
a que diga nada. Un modelo puede entregar tres direcciones que son la misma idea
peinada de tres maneras, con tres enemigos que son «la mediocridad» escrita de
tres formas, y el esquema la aceptará encantado.

Aquí se mide eso con números en vez de con impresiones: solapamiento de trigramas
entre direcciones, longitudes, tópicos prohibidos y claves de activo que existan
de verdad en el dossier. Las reglas duras bloquean y provocan UN reintento
correctivo con la lista literal de lo incumplido; las blandas solo se anotan,
para poder medir con el tiempo si el modelo mejora o empeora.

Por qué un solo reintento y no un bucle: el endpoint de recomendaciones todavía
no pide autenticación. Un bucle de tres o cuatro intentos convierte eso en una
factura abierta. Dos llamadas es el techo.

Sin dependencias de paquetes externos: solo stdlib.
"""

from __future__ import annotations

import itertools
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from .esquema import IDS_PALETA, Salida

RAIZ = Path(__file__).resolve().parent.parent.parent
DIR_CONTENIDO = RAIZ / "contenido"

# Umbrales de solapamiento. 0,18 sobre trigramas de palabra es el punto donde dos
# textos que comparten estructura Y tema saltan, y dos textos del mismo idioma
# sobre temas distintos no. El de los enemigos es más alto porque son frases
# cortas: comparten más vocabulario por pura estadística.
UMBRAL_CONCEPTO = 0.18
UMBRAL_ENEMIGO = 0.25

MIN_CARACTERES_ENEMIGO = 40
MAX_PALABRAS_UNA_SOLA_COSA = 6
MAX_PALABRAS_ESLOGAN = 7
MAX_PALABRAS_BAR = 15

RE_ID_PREGUNTA = re.compile(r"\b(?:COM|VIS|ACC)-[A-Z]{2}-\d\b")
RE_CIFRA = re.compile(r"\b\d{1,3}(?:[.,]\d)?\b")

# Respaldo por si contenido/activos.json todavía no existe (lo crea otra mano) o
# viene sin estas claves. Sin esto, R3 y R7 se caerían enteras y la validación
# dejaría pasar justo lo que existe para bloquear.
_TOPICOS_RESPALDO: dict[str, list[str]] = {
    "enemigos": [
        "la mediocridad",
        "lo generico",
        "el status quo",
        "la superficialidad",
        "el ruido",
        "la falta de autenticidad",
        "la zona de confort",
    ],
    "consultoria": [
        "se autentico",
        "cuenta tu historia",
        "aporta valor",
        "aportar valor",
        "conecta con tu audiencia",
        "zona de confort",
        "storytelling",
        "marca personal",
        "posicionamiento estrategico",
        "propuesta de valor",
        "soluciones a medida",
        "tu socio estrategico",
    ],
    "marcadores_oposicion": [
        "contra",
        "frente a",
        "en contra de",
        "basta de",
        "al reves de",
        "harto",
        "rechaza",
        "no",
    ],
}


# ----------------------------------------------------------------- normalización

def _norm(texto: Any) -> str:
    """Minúsculas, sin diacríticos, sin puntuación y con los espacios colapsados.

    Se quita la puntuación en vez de sustituirla por nada para que «marca-blanca»
    y «marca blanca» cuenten como lo mismo: si el modelo cambia un guión para
    parecer distinto, no lo va a conseguir.
    """
    t = unicodedata.normalize("NFKD", str(texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = "".join(" " if unicodedata.category(c).startswith("P") else c for c in t)
    return re.sub(r"\s+", " ", t).strip()


def _palabras(texto: Any) -> list[str]:
    n = _norm(texto)
    return n.split() if n else []


def _trigramas(texto: Any) -> set[tuple[str, ...]]:
    """Conjunto de ternas de palabras consecutivas.

    Con menos de tres palabras degrada a bigramas, y con menos de dos a palabras
    sueltas: en un `una_sola_cosa` de cuatro palabras no hay trigramas suficientes
    para medir nada, y devolver el conjunto vacío haría que el Jaccard saliera 0
    justo donde más se copian.
    """
    p = _palabras(texto)
    if len(p) >= 3:
        return {tuple(p[i : i + 3]) for i in range(len(p) - 2)}
    if len(p) == 2:
        return {tuple(p)}
    return {(x,) for x in p}


def _jaccard(a: set[Any], b: set[Any]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _pct(x: float) -> str:
    return f"{round(x * 100)} %"


def _contiene_frase(texto_norm: str, frase_norm: str) -> bool:
    """Busca una frase como secuencia de palabras completas, no como subcadena.

    Sin esto, el marcador «no» daría positivo dentro de «nosotros» y R3 aceptaría
    cualquier cosa.
    """
    if not frase_norm:
        return False
    return f" {frase_norm} " in f" {texto_norm} "


# -------------------------------------------------------------------- contenido

@lru_cache(maxsize=1)
def _topicos() -> dict[str, list[str]]:
    """Listas de contenido/activos.json, ya normalizadas y con respaldo."""
    crudo: dict[str, Any] = {}
    ruta = DIR_CONTENIDO / "activos.json"
    try:
        with ruta.open(encoding="utf-8") as f:
            crudo = json.load(f).get("topicos_prohibidos") or {}
    except (OSError, ValueError):
        crudo = {}

    salida: dict[str, list[str]] = {}
    for clave, respaldo in _TOPICOS_RESPALDO.items():
        lista = crudo.get(clave) or respaldo
        salida[clave] = [_norm(x) for x in lista if _norm(x)]
    return salida


def _tagline_arquetipo(dossier: dict[str, Any]) -> str:
    """El ejemplo_tagline del arquetipo primario, normalizado.

    Es la única frase corta que hoy imprime el informe y es idéntica para todos
    los que comparten primario: si un eslogan «propio» coincide con ella, no es
    propio. No viaja en el dossier, así que se busca por el nombre del arquetipo.
    """
    directo = (dossier.get("arquetipo") or {}).get("ejemplo_tagline")
    if directo:
        return _norm(directo)

    nombre = (dossier.get("arquetipo") or {}).get("primario")
    if not nombre:
        return ""
    try:
        from .. import contenido
    except ImportError:
        return ""
    try:
        fichas = contenido.arquetipos()["fichas"]
    except Exception:  # noqa: BLE001 — sin contenido, esta regla simplemente no aplica
        return ""
    for ficha in fichas.values():
        if ficha.get("nombre") == nombre or ficha.get("id") == nombre:
            return _norm((ficha.get("comunicacion") or {}).get("ejemplo_tagline"))
    return ""


# ---------------------------------------------------------------------- reglas

def validar(salida: Salida, dossier: dict[str, Any]) -> dict[str, list[str]]:
    """Devuelve {'duros': [...], 'blandos': [...]}.

    Los duros son los que van literales al prompt de reintento, así que cada uno
    lleva su cifra: «comparten el 34 % de trigramas» le dice al modelo qué tiene
    que romper; «las direcciones se parecen» no le dice nada.
    """
    duros: list[str] = []
    blandos: list[str] = []
    recs = list(salida.recomendaciones)
    topicos = _topicos()

    _r1_titulos(recs, duros)
    _r2_distincion(recs, duros)
    _r3_enemigo(recs, topicos, duros)
    _r4_paletas(salida, recs, dossier, duros)
    _r5_una_sola_cosa(recs, dossier, duros)
    _r6_activos(recs, dossier, duros, blandos)

    _r7_topicos(salida, topicos, blandos)
    _r8_anclaje(recs, blandos)
    _r9_acciones(recs, blandos)
    _r10_identidad_verbal(recs, blandos)
    _r11_prueba_del_bar(recs, dossier, blandos)

    return {"duros": duros, "blandos": blandos}


def _r1_titulos(recs: list[Any], duros: list[str]) -> None:
    titulos = [_norm(r.titulo) for r in recs]
    if len(recs) != 3 or len(set(titulos)) != len(titulos):
        duros.append(
            f"Hay {len(recs)} direcciones o dos títulos iguales. Tienen que ser "
            "tres, con tres títulos distintos."
        )


def _huella(rec: Any) -> str:
    return f"{rec.concepto} {rec.una_sola_cosa} {rec.postura}"


def _r2_distincion(recs: list[Any], duros: list[str]) -> None:
    huellas = [_trigramas(_huella(r)) for r in recs]
    for i, j in itertools.combinations(range(len(recs)), 2):
        solape = _jaccard(huellas[i], huellas[j])
        if solape >= UMBRAL_CONCEPTO:
            duros.append(
                f"Las direcciones {i + 1} y {j + 1} comparten el {_pct(solape)} "
                "de trigramas en concepto + una_sola_cosa + postura: son la "
                "misma idea escrita dos veces."
            )


def _r3_enemigo(recs: list[Any], topicos: dict[str, list[str]], duros: list[str]) -> None:
    for i, rec in enumerate(recs, start=1):
        enemigo = rec.enemigo or ""
        norm = _norm(enemigo)

        if len(enemigo.strip()) < MIN_CARACTERES_ENEMIGO:
            duros.append(
                f"El enemigo de la dirección {i} tiene {len(enemigo.strip())} "
                f"caracteres y el mínimo son {MIN_CARACTERES_ENEMIGO}: «{enemigo}». "
                "Con nombres y sin eufemismos."
            )

        if not any(
            _contiene_frase(norm, m) for m in topicos["marcadores_oposicion"]
        ):
            duros.append(
                f"El enemigo de la dirección {i} no dice contra qué está: "
                "«contra», «frente a», «basta de»... Sin oposición explícita no "
                "es un enemigo, es una descripción."
            )

        for topico in topicos["enemigos"]:
            if _contiene_frase(norm, topico):
                duros.append(
                    f"El enemigo de la dirección {i} es el tópico «{topico}». "
                    "Eso no es un enemigo: es una excusa. Nombra a alguien o una "
                    "práctica concreta."
                )
                break

    enemigos = [_trigramas(r.enemigo) for r in recs]
    for i, j in itertools.combinations(range(len(recs)), 2):
        solape = _jaccard(enemigos[i], enemigos[j])
        if solape >= UMBRAL_ENEMIGO:
            duros.append(
                f"Los enemigos de las direcciones {i + 1} y {j + 1} comparten el "
                f"{_pct(solape)} de trigramas: es un enemigo repetido, no tres."
            )


def _r4_paletas(
    salida: Salida, recs: list[Any], dossier: dict[str, Any], duros: list[str]
) -> None:
    reales = {
        p.get("id")
        for p in (dossier.get("paletas") or [])
        if isinstance(p, dict) and p.get("id")
    }
    # Si el dossier no trae paletas (informe sin módulo visual), solo se puede
    # comprobar contra el catálogo. Bloquear ahí sería castigar al usuario por un
    # hueco que no es suyo.
    validos = reales or set(IDS_PALETA)

    usados = [r.paleta_id for r in recs]
    for i, pid in enumerate(usados, start=1):
        if pid not in validos:
            duros.append(
                f"La dirección {i} usa la paleta '{pid}', que no está entre las "
                f"generadas ({', '.join(sorted(validos))}). Elige una de esas."
            )

    for j in salida.justificacion_paletas:
        if j.paleta_id not in validos:
            duros.append(
                f"Justificas la paleta '{j.paleta_id}', que no se ha generado. "
                f"Las que hay son: {', '.join(sorted(validos))}."
            )

    if len(usados) >= 2 and len(set(usados)) == 1 and len(validos) > 1:
        duros.append(
            f"Las tres direcciones usan la misma paleta ('{usados[0]}'). Si el "
            "color no cambia, las tres direcciones se ven iguales."
        )

    nivel = (dossier.get("audacia") or {}).get("nivel")
    if nivel == "audaz" and "polarizante" in validos and "polarizante" not in usados:
        duros.append(
            "El perfil es audaz y ninguna dirección usa la paleta polarizante. "
            "A un audaz no le propongas prudencia."
        )


def _r5_una_sola_cosa(
    recs: list[Any], dossier: dict[str, Any], duros: list[str]
) -> None:
    tagline = _tagline_arquetipo(dossier)

    for i, rec in enumerate(recs, start=1):
        palabras = _palabras(rec.una_sola_cosa)
        if len(palabras) > MAX_PALABRAS_UNA_SOLA_COSA:
            duros.append(
                f"La una_sola_cosa de la dirección {i} tiene {len(palabras)} "
                f"palabras y el máximo son {MAX_PALABRAS_UNA_SOLA_COSA}: "
                f"«{rec.una_sola_cosa}»."
            )
        if "y" in palabras:
            duros.append(
                f"La una_sola_cosa de la dirección {i} lleva una «y»: "
                f"«{rec.una_sola_cosa}». Sobra la mitad. Elige cuál."
            )

        candidatos = list(rec.eslogan_candidatos or [])
        for c in candidatos:
            n = len(_palabras(c))
            if n > MAX_PALABRAS_ESLOGAN:
                duros.append(
                    f"Un eslogan de la dirección {i} tiene {n} palabras y el "
                    f"máximo son {MAX_PALABRAS_ESLOGAN}: «{c}»."
                )
            if tagline and _norm(c) == tagline:
                duros.append(
                    f"Un eslogan de la dirección {i} es el tagline de ejemplo de "
                    f"su arquetipo: «{c}». Ese lo tienen ya todos los que "
                    "comparten primario."
                )
        normalizados = [_norm(c) for c in candidatos]
        if len(set(normalizados)) != len(normalizados):
            duros.append(
                f"Los tres eslóganes de la dirección {i} no son tres: hay dos "
                "iguales."
            )


def _r6_activos(
    recs: list[Any],
    dossier: dict[str, Any],
    duros: list[str],
    blandos: list[str],
) -> None:
    declarados = dossier.get("activos_declarados") or []
    if not declarados:
        # El dossier puede llegar sin el bloque (informe antiguo, o el módulo de
        # activos todavía no desplegado). Exigir claves de una lista que no
        # existe sería bloquear siempre; se anota y se sigue.
        blandos.append(
            "El dossier no trae `activos_declarados`: no se ha podido comprobar "
            "si los activos elegidos son reales."
        )
        return

    validas = {a.get("clave") for a in declarados if isinstance(a, dict)}
    fuerza = {
        a.get("clave"): a.get("fuerza", 0)
        for a in declarados
        if isinstance(a, dict)
    }
    vetadas = {
        a.get("clave")
        for a in declarados
        if isinstance(a, dict) and _es_veto_duro(a.get("conflicto"))
    }

    for i, rec in enumerate(recs, start=1):
        elegidos = list(rec.activos_elegidos or [])
        claves = [e.clave for e in elegidos]

        if len(set(claves)) != len(claves):
            duros.append(
                f"La dirección {i} repite el mismo activo dos veces. Dos o tres "
                "activos DISTINTOS."
            )

        for e in elegidos:
            if e.clave not in validas:
                duros.append(
                    f"La dirección {i} propone el activo '{e.clave}', que no "
                    "está en `activos_declarados`. Te lo has inventado: elige "
                    f"de esta lista: {', '.join(sorted(str(v) for v in validas))}."
                )
                continue
            if not fuerza.get(e.clave):
                duros.append(
                    f"La dirección {i} propone el activo '{e.clave}', que tiene "
                    "fuerza 0: la persona ha dicho que no lleva nada de eso."
                )
            if e.clave in vetadas:
                duros.append(
                    f"La dirección {i} propone el activo '{e.clave}', que está "
                    "marcado con un conflicto de veto: choca con algo que la "
                    "persona ha vetado."
                )

            sitios = [s for s in (e.donde_aparece or []) if str(s).strip()]
            if len(sitios) != 3:
                duros.append(
                    f"El activo '{e.clave}' de la dirección {i} tiene "
                    f"{len(sitios)} sitios donde aparece y tienen que ser 3, "
                    "concretos."
                )


def _es_veto_duro(conflicto: Any) -> bool:
    """Un conflicto cuenta como veto duro salvo que venga explícitamente flojo.

    El formato exacto del campo `conflicto` lo fija app/activos.py, que es de
    otra mano. Se acepta booleano, cadena o dict y, ante la duda, se considera
    veto: proponer un activo vetado es peor que no proponerlo.
    """
    if not conflicto:
        return False
    if isinstance(conflicto, dict):
        return conflicto.get("nivel", "duro") != "blando"
    return True


def _volcado(salida: Salida) -> str:
    return _norm(json.dumps(salida.model_dump(), ensure_ascii=False))


def _r7_topicos(
    salida: Salida, topicos: dict[str, list[str]], blandos: list[str]
) -> None:
    texto = _volcado(salida)
    for topico in topicos["consultoria"]:
        if _contiene_frase(texto, topico):
            blandos.append(f"Tópico de consultoría en la salida: «{topico}».")


def _r8_anclaje(recs: list[Any], blandos: list[str]) -> None:
    for i, rec in enumerate(recs, start=1):
        texto = rec.por_que_a_ti or ""
        if not (RE_ID_PREGUNTA.search(texto) or RE_CIFRA.search(texto)):
            blandos.append(
                f"El por_que_a_ti de la dirección {i} no cita ninguna respuesta "
                "ni ninguna cifra: no se puede comprobar."
            )


def _r9_acciones(recs: list[Any], blandos: list[str]) -> None:
    for i, rec in enumerate(recs, start=1):
        acciones = list(rec.acciones or [])
        if len(acciones) != 3:
            blandos.append(
                f"La dirección {i} tiene {len(acciones)} acciones en vez de 3."
            )
        con_cifra = sum(1 for a in acciones if any(c.isdigit() for c in str(a)))
        if con_cifra < 2:
            blandos.append(
                f"Solo {con_cifra} de las acciones de la dirección {i} llevan "
                "una cifra, una cadencia o una fecha. Sin número no es una acción."
            )


def _r10_identidad_verbal(recs: list[Any], blandos: list[str]) -> None:
    for i, rec in enumerate(recs, start=1):
        verbal = rec.identidad_verbal
        apertura = _norm(getattr(verbal, "frase_de_apertura", ""))
        cierre = _norm(getattr(verbal, "frase_de_cierre", ""))
        if not apertura or not cierre:
            blandos.append(
                f"La identidad verbal de la dirección {i} tiene la apertura o el "
                "cierre en blanco."
            )
        elif apertura == cierre:
            blandos.append(
                f"La dirección {i} abre y cierra con la misma frase."
            )


def _r11_prueba_del_bar(
    recs: list[Any], dossier: dict[str, Any], blandos: list[str]
) -> None:
    identidad = dossier.get("identidad") or {}
    nombres = [
        _norm(identidad.get("nombre")),
        _norm(identidad.get("artistico")),
    ]
    nombres = [n for n in nombres if len(n) >= 3]

    for i, rec in enumerate(recs, start=1):
        frase = rec.prueba_del_bar or ""
        n = len(_palabras(frase))
        if n > MAX_PALABRAS_BAR:
            blandos.append(
                f"La prueba del bar de la dirección {i} tiene {n} palabras y el "
                f"máximo son {MAX_PALABRAS_BAR}."
            )
        norm = _norm(frase)
        for nombre in nombres:
            if _contiene_frase(norm, nombre):
                blandos.append(
                    f"La prueba del bar de la dirección {i} dice su nombre "
                    f"(«{nombre}»). Quien habla en el bar no lo dice: lo describe."
                )
                break


__all__ = ["validar", "UMBRAL_CONCEPTO", "UMBRAL_ENEMIGO"]
