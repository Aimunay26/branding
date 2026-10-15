"""Activos distintivos: lo que hace que a alguien lo reconozcan sin verle la cara.

El fallo que esto arregla: las respuestas que SON la marca (el color que declaras,
el sello que llevas siempre, el formato que publicas pase lo que pase, el gesto
que repites) acababan trituradas en una cuota de afinidad por arquetipo cuya
única salida era «el líder del módulo coincide o no con el primario». Aquí se
convierten en una lista tipada, con fuerza numérica y regla de uso, que el
informe puede imprimir y la IA puede citar por su `clave`.

Todo es determinista y auditable: mismos datos, mismo resultado. La IA no entra
aquí. Los pesos viven en contenido/activos.json para poder discutirlos sin tocar
código.

Dos decisiones de diseño que conviene no revertir sin pensarlo:

1. El punto medio exacto de los bipolares NO genera activo. El frontend escribe
   el 4 en los nueve deslizadores solo con pintarlos, así que un 4 no es una
   postura: es un valor por defecto. Preferimos perder un activo antes que
   inventarle una silueta a quien no ha tocado el deslizador.
2. El bloque limites_corporales (VIS-LM-*) no genera activos ni vetos de activo.
   Ese bloque le promete a la persona que ninguna respuesta suma ni resta, y
   convertir el derecho a no hablar del propio cuerpo en material de marca es
   exactamente el límite que este producto no cruza.

Ninguna función revienta si falta una respuesta: el cuestionario se puede enviar
incompleto y los módulos de contenido están cambiando debajo. Cuando falta el
dato, el activo no se emite y se deja constancia del motivo.
"""

from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import contenido, paletas as paletas_mod

RAIZ = Path(__file__).resolve().parent.parent
DIR_CONTENIDO = RAIZ / "contenido"

# El centro de los bipolares de escala 7. Es el valor que el software rellena
# solo (form.js pinta el deslizador ya en el medio), no una respuesta.
CENTRO_BIPOLAR = 4

# Piezas al mes que implica cada cadencia de COM-CA-3. Son medias conservadoras:
# «casi todos los días» son 20 laborables, no 30.
PIEZAS_POR_CADENCIA = {
    "diario": 20,
    "semanal_3": 12,
    "semanal_1": 4,
    "quincenal": 2,
    "campanas": 1,
}

# Horas reales a la semana que declara ACC-TR-1. El tramo abierto de arriba se
# cierra en 30: por encima de eso ya no es una restricción, es un trabajo.
HORAS_POR_TRAMO = {
    "menos_2": 2,
    "2_5": 5,
    "5_10": 10,
    "10_20": 20,
    "mas_20": 30,
}

# Opciones de VIS-CA-3 que implican tinte. Si no hay ninguna, la regla del
# peinado habla de forma y no de color: no se le pide a nadie que mantenga un
# color de pelo que ha dicho que no se haría.
OPCIONES_TINTE = {"matiz", "rubio", "negro", "pelirrojo", "fantasia"}

# Valores de ACC-RI-1 que son formato (una cita fija) y no gesto.
RITUALES_FORMATO = {"formato_fijo", "seccion"}
RITUALES_GESTO = {"gesto", "saludo", "gracias", "objeto", "regalo", "color"}

# Orden de desempate cuando varios activos empatan a fuerza máxima. No es
# estético: un sello y un formato son cosas que alguien puede nombrar de
# memoria («las gafas», «el boletín»), y un color o una tipografía, no. Sin este
# orden, «una sola cosa» saldría distinta según en qué orden se emitieran los
# activos, y eso rompe la promesa de que el motor es determinista.
ORDEN_DESEMPATE = (
    "sello", "formato", "gesto", "uniforme", "silueta",
    "peinado", "encuadre", "palabra", "color", "tipografia",
)

_SECCION_POR_PREFIJO = {"COM": "comunicacion", "VIS": "visual", "ACC": "acciones"}


# ------------------------------------------------------------------ contenido

@lru_cache(maxsize=1)
def _datos() -> dict[str, Any]:
    with (DIR_CONTENIDO / "activos.json").open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _nombres() -> dict[str, Any]:
    ruta = DIR_CONTENIDO / "nombres.json"
    if not ruta.exists():
        return {}
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _colores() -> dict[str, Any]:
    with (DIR_CONTENIDO / "colores.json").open(encoding="utf-8") as f:
        return json.load(f)


def recargar() -> None:
    """Vacía la caché de contenido. Útil en desarrollo tras editar un JSON."""
    for fn in (_datos, _nombres, _colores):
        fn.cache_clear()


# ------------------------------------------------------------------ utilidades

def _normalizar(texto: Any) -> str:
    """Minúsculas y sin tildes. Compara respuestas escritas a mano con catálogo."""
    if texto is None:
        return ""
    descompuesto = unicodedata.normalize("NFKD", str(texto).lower())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _r(respuestas: dict[str, Any], pid: str) -> Any:
    """Valor de una pregunta por su id, mire en la sección que mire.

    El id lleva el módulo dentro (VIS-, COM-, ACC-), así que normalmente basta
    con una búsqueda directa. La segunda pasada existe porque las preguntas se
    están moviendo de bloque mientras se escribe esto: si una cambia de sitio,
    el activo no debe desaparecer en silencio.
    """
    if not isinstance(respuestas, dict):
        return None
    seccion = _SECCION_POR_PREFIJO.get(pid[:3])
    if seccion:
        bloque = respuestas.get(seccion)
        if isinstance(bloque, dict):
            valor = bloque.get(pid)
            if valor not in (None, "", []):
                return valor
    for bloque in respuestas.values():
        if isinstance(bloque, dict) and bloque.get(pid) not in (None, "", []):
            return bloque[pid]
    return None


def _num(valor: Any) -> int | None:
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def _lista(valor: Any) -> list[Any]:
    if valor in (None, "", []):
        return []
    return list(valor) if isinstance(valor, list) else [valor]


def _texto(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def _indice_preguntas(mods: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """{id_pregunta: pregunta} de los tres módulos. Sin caché a propósito.

    Los módulos se están reescribiendo en paralelo; cachear aquí obligaría a
    recordar dos invalidaciones distintas y el coste de rehacerlo es una vuelta
    sobre unas ciento cuarenta preguntas.
    """
    if mods is None:
        try:
            mods = contenido.modulos()
        except Exception:
            return {}
    indice: dict[str, dict[str, Any]] = {}
    for modulo in (mods or {}).values():
        for bloque in (modulo or {}).get("bloques", []):
            for pregunta in bloque.get("preguntas", []):
                if pregunta.get("id"):
                    indice[pregunta["id"]] = pregunta
    return indice


def _etiqueta_opcion(
    pid: str, valor: Any, mods: dict[str, Any] | None = None
) -> str:
    """Etiqueta legible de una opción. Si no se encuentra, devuelve el valor."""
    pregunta = _indice_preguntas(mods).get(pid, {})
    for opcion in pregunta.get("opciones", []):
        if opcion.get("valor") == valor:
            return opcion.get("etiqueta", str(valor))
    return str(valor) if valor is not None else ""


def _texto_pregunta(pid: str, mods: dict[str, Any] | None = None, tope: int = 120) -> str:
    """El enunciado de una pregunta, recortado para poder citarlo dentro de otra frase.

    Algunas preguntas de disposición son escenarios de tres líneas. Citar el
    escenario entero dentro de una contradicción la entierra: se cita la primera
    frase, que es donde está la pregunta de verdad.
    """
    texto = _indice_preguntas(mods).get(pid, {}).get("texto", pid).strip()
    if len(texto) <= tope:
        return texto
    for corte in (". ", "? ", "! "):
        if corte in texto[:tope + 40]:
            return texto.split(corte)[0] + corte.strip()
    return texto[:tope].rstrip() + "…"


def _rotulo(pid: str, valor: str, campo: str, mods: dict[str, Any] | None = None) -> str:
    """`sujeto` o `nombre` corto de una opción, con la etiqueta larga de reserva."""
    tabla = _datos().get("etiquetas_activo", {}).get(pid, {})
    entrada = tabla.get(valor)
    if isinstance(entrada, dict) and entrada.get(campo):
        return entrada[campo]
    return _etiqueta_opcion(pid, valor, mods)


def _regla(tipo: str, etiqueta: str = "", valor: str = "") -> str:
    """Rellena la plantilla de regla de uso y deja la frase con mayúscula inicial.

    La mayúscula no está en la plantilla porque el hueco puede ir al principio y
    lo que entra ahí (una palabra propia, el texto de un gesto) llega en
    minúsculas tal y como lo escribió la persona.
    """
    plantilla = _datos().get("reglas_de_uso", {}).get(tipo, "")
    frase = plantilla.replace("{etiqueta}", etiqueta or "").replace("{valor}", valor or "")
    frase = frase.strip()
    return frase[:1].upper() + frase[1:] if frase else ""


def _activo(
    tipo: str,
    clave: str,
    valor: Any,
    etiqueta: str,
    fuente_ids: list[str],
    fuerza: int,
    declarado: bool,
    regla_de_uso: str,
) -> dict[str, Any]:
    """Un activo. Estas claves son contrato: el informe y la IA leen justo estas."""
    return {
        "tipo": tipo,
        "clave": clave,
        "valor": valor,
        "etiqueta": etiqueta,
        "fuente_ids": fuente_ids,
        "fuerza": fuerza,
        "declarado": declarado,
        "regla_de_uso": regla_de_uso,
        "conflicto": None,
    }


# ------------------------------------------------------------------ derivación

def _color_declarado(respuestas: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    valor = _r(respuestas, "VIS-CR-3")
    if not isinstance(valor, str):
        return None, None
    return valor, _colores().get("colores_declarados", {}).get(valor)


def _hex_dominante(paletas: list[dict[str, Any]] | None, ficha: dict[str, Any]) -> str | None:
    """El hex dominante de «La tuya», que ya viene generada por app/paletas.py."""
    for paleta in paletas or []:
        if paleta.get("id") == "tuya" and paleta.get("colores"):
            colores = paleta["colores"]
            dom = next((c for c in colores if c.get("rol") == "dominante"), colores[0])
            return dom.get("hex")
    paleta_ficha = (ficha or {}).get("visual", {}).get("paleta", [])
    return paleta_ficha[0].get("hex") if paleta_ficha else None


def _activo_color(
    respuestas: dict[str, Any], paletas: list[dict[str, Any]] | None, ficha: dict[str, Any]
) -> dict[str, Any] | None:
    hexc = _hex_dominante(paletas, ficha)
    valor_declarado, declarado = _color_declarado(respuestas)

    if declarado:
        nombre = str(declarado.get("nombre", "tu color")).lower()
        # El monocromo NO es una evasiva: paletas.py lo trata como color propio
        # («solo blanco y negro» es una decisión estética completa). Pero rinde
        # menos que un tono: en una foto pequeña no hay nada que asociar.
        fuerza = 2 if declarado.get("monocromo") else 3
        etiqueta = f"Tu {nombre}"
        return _activo(
            "color", "color:dominante", hexc or declarado.get("hex"), etiqueta,
            ["VIS-CR-3"], fuerza, True, _regla("color", etiqueta=etiqueta),
        )

    if not hexc:
        return None
    # Sin VIS-CR-3 el color sale de la ficha: existe, pero no es suyo, y el
    # índice de identificabilidad lo cuenta como cero.
    etiqueta = "El color de tu arquetipo"
    return _activo(
        "color", "color:dominante", hexc, etiqueta,
        ["VIS-CR-3"], 1, False, _regla("color", etiqueta=etiqueta),
    )


def _activo_tipografia(ficha: dict[str, Any]) -> dict[str, Any] | None:
    titulares = (ficha or {}).get("visual", {}).get("tipografia", {}).get("titular", [])
    if not titulares:
        return None
    fuente = titulares[0]
    return _activo(
        "tipografia", "tipografia:arquetipo", fuente, fuente,
        [], 1, False, _regla("tipografia", valor=fuente),
    )


def _activo_silueta(
    respuestas: dict[str, Any], mods: dict[str, Any] | None
) -> dict[str, Any] | None:
    indice = _indice_preguntas(mods)
    polos: list[str] = []
    distancias: list[int] = []
    for pid in ("VIS-RO-3", "VIS-RO-4"):
        v = _num(_r(respuestas, pid))
        if v is None:
            continue
        distancias.append(abs(v - CENTRO_BIPOLAR))
        if v == CENTRO_BIPOLAR:
            continue  # el centro exacto lo escribe el software, no la persona
        pregunta = indice.get(pid, {})
        polo = pregunta.get("polo_izq") if v < CENTRO_BIPOLAR else pregunta.get("polo_der")
        if polo:
            polos.append(str(polo))

    if not distancias or not polos:
        return None
    d = max(distancias)
    if d == 0:
        return None
    fuerza = 3 if d >= 2 else 2

    valor = ", ".join(polos)
    etiqueta = polos[0] + "".join(f", {p[:1].lower()}{p[1:]}" for p in polos[1:])
    return _activo(
        "silueta", "silueta:polos", valor, etiqueta,
        ["VIS-RO-3", "VIS-RO-4"], fuerza, True, _regla("silueta", etiqueta=etiqueta),
    )


def _activos_sello(
    respuestas: dict[str, Any], mods: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], bool]:
    """Devuelve (activos, renuncia). `renuncia` es True si solo hay 'ninguna_firma'."""
    elegidos = [v for v in _lista(_r(respuestas, "VIS-RO-5")) if isinstance(v, str)]
    if not elegidos:
        return [], False
    utiles = [v for v in elegidos if v != "ninguna_firma"]
    if not utiles:
        return [], True

    pesos = _datos().get("peso_activo", {}).get("VIS-RO-5", {})
    salida: list[dict[str, Any]] = []
    for valor in utiles:
        sujeto = _rotulo("VIS-RO-5", valor, "sujeto", mods)
        salida.append(
            _activo(
                "sello", f"sello:{valor}", _etiqueta_opcion("VIS-RO-5", valor, mods),
                sujeto, ["VIS-RO-5"], int(pesos.get(valor, 1)), True,
                _regla("sello", etiqueta=sujeto),
            )
        )
    return salida, False


def _activo_peinado(
    respuestas: dict[str, Any], mods: dict[str, Any] | None
) -> dict[str, Any] | None:
    v = _num(_r(respuestas, "VIS-CA-7"))
    if v is None or v < 4:
        return None
    tintes = {t for t in _lista(_r(respuestas, "VIS-CA-3")) if t in OPCIONES_TINTE}
    tipo_regla = "peinado_con_color" if tintes else "peinado"
    return _activo(
        "peinado", "peinado:VIS-CA-7", "El mismo peinado siempre", "Tu peinado",
        ["VIS-CA-7"] + (["VIS-CA-3"] if tintes else []),
        3 if v >= 5 else 2, True, _regla(tipo_regla),
    )


def _activo_uniforme(respuestas: dict[str, Any]) -> dict[str, Any] | None:
    v = _num(_r(respuestas, "VIS-AU-3"))
    if v is None or v < 4:
        return None
    return _activo(
        "uniforme", "uniforme:VIS-AU-3", "La misma combinación de prendas",
        "Tu uniforme", ["VIS-AU-3"], 3 if v >= 5 else 2, True, _regla("uniforme"),
    )


def _activo_encuadre(respuestas: dict[str, Any]) -> dict[str, Any] | None:
    v = _num(_r(respuestas, "VIS-AU-1"))
    if v is None:
        return None
    texto = _datos().get("encuadre_por_audacia", {}).get(str(v))
    if not texto:
        return None  # el 4 es null: punto muerto, no postura
    fuerza = 3 if v in (1, 2, 6, 7) else 2
    return _activo(
        "encuadre", "encuadre:audacia", texto, "Tu encuadre",
        ["VIS-AU-1"], fuerza, True, _regla("encuadre", valor=texto),
    )


def _activos_formato_y_gesto(
    respuestas: dict[str, Any], mods: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], bool]:
    """Formato ancla, rituales de ACC-RI-1 y el gesto propio de ACC-RI-2.

    El booleano de vuelta avisa de que ACC-RI-1 se ha contestado en categoría:
    hoy la pregunta devuelve «un color que siempre llevas» y no CUÁL.
    """
    salida: list[dict[str, Any]] = []
    pesos = _datos().get("peso_activo", {})
    sin_concretar = False

    ancla = _r(respuestas, "ACC-CT-2")
    if isinstance(ancla, str):
        sujeto = _rotulo("ACC-CT-2", ancla, "sujeto", mods)
        salida.append(
            _activo(
                "formato", "formato:ancla", _etiqueta_opcion("ACC-CT-2", ancla, mods),
                sujeto, ["ACC-CT-2"], int(pesos.get("ACC-CT-2", {}).get(ancla, 3)),
                True, _regla("formato", etiqueta=sujeto),
            )
        )

    for valor in _lista(_r(respuestas, "ACC-RI-1")):
        if not isinstance(valor, str):
            continue
        peso = int(pesos.get("ACC-RI-1", {}).get(valor, 1))
        etiqueta_larga = _etiqueta_opcion("ACC-RI-1", valor, mods)
        sujeto = _rotulo("ACC-RI-1", valor, "sujeto", mods)
        if valor in RITUALES_FORMATO:
            salida.append(
                _activo(
                    "formato", f"formato:ACC-RI-1.{valor}", etiqueta_larga, sujeto,
                    ["ACC-RI-1"], peso, True, _regla("formato", etiqueta=sujeto),
                )
            )
            sin_concretar = True
        elif valor in RITUALES_GESTO:
            salida.append(
                _activo(
                    "gesto", f"gesto:ACC-RI-1.{valor}", etiqueta_larga, sujeto,
                    ["ACC-RI-1"], peso, True, _regla("gesto", valor=etiqueta_larga),
                )
            )
            sin_concretar = True

    propio = _texto(_r(respuestas, "ACC-RI-2"))
    if propio:
        # La ayuda de la pregunta pide literalmente «Cada [cuándo], hago [qué]».
        # Si el texto no trae el cuándo, es una intención, no un gesto.
        normalizado = _normalizar(propio)
        con_patron = "cada" in normalizado and len(normalizado) >= 15
        salida.append(
            _activo(
                "gesto", "gesto:propio", propio, "Tu gesto propio",
                ["ACC-RI-2"], 3 if con_patron else 1, True,
                _regla("gesto", valor=propio),
            )
        )

    return salida, sin_concretar


def _activos_palabra(
    respuestas: dict[str, Any], ficha: dict[str, Any], mods: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Palabras propias. Hoy es un apaño y se dice: no hay pregunta de vocabulario.

    Si algún día existe ACC-RI-3 («¿qué palabra dices tú siempre?») o COM-PO-3,
    esa respuesta manda y el rastreo por los textos largos se apaga: una palabra
    que la persona ha escrito a propósito vale más que una que hemos pescado.
    """
    directa = _r(respuestas, "ACC-RI-3") or _r(respuestas, "COM-PO-3")
    palabras: list[str] = []
    for candidata in _lista(directa):
        texto = _texto(candidata)
        if texto:
            palabras.append(texto)

    if not palabras:
        vocabulario = (ficha or {}).get("comunicacion", {}).get("vocabulario", [])
        corpus = " ".join(
            _normalizar(_texto(_r(respuestas, pid)))
            for pid in ("COM-PA-1", "COM-PA-2", "COM-PA-3", "COM-PA-4", "COM-NA-4")
        )
        tokens = {t for t in _tokens(corpus) if len(t) >= 4}
        for termino in vocabulario:
            norm = _normalizar(termino)
            if len(norm) < 4:
                continue
            encontrada = norm in corpus if " " in norm else norm in tokens
            if encontrada and termino not in palabras:
                palabras.append(termino)

    if not palabras:
        # Activo hueco a propósito: el informe tiene que poder decir «te falta
        # esto» en vez de callarlo y dejar la sección coja sin explicación.
        return [
            _activo(
                "palabra", "palabra:1", None, "Ninguna palabra propia",
                ["COM-PA-2", "COM-PA-3"], 0, False,
                "No hay ninguna palabra que sea tuya. Elige una y métela en todo lo que firmes.",
            )
        ]

    return [
        _activo(
            "palabra", f"palabra:{i}", palabra, f"«{palabra}»",
            ["ACC-RI-3"] if directa else ["COM-PA-2", "COM-PA-3"],
            2, True, _regla("palabra", valor=f"«{palabra}»"),
        )
        for i, palabra in enumerate(palabras, start=1)
    ]


def _tokens(texto_normalizado: str) -> set[str]:
    limpio = "".join(c if c.isalnum() else " " for c in texto_normalizado)
    return set(limpio.split())


# ------------------------------------------------------------------ filtrado

def _filtrar(
    activos: list[dict[str, Any]], respuestas_visual: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Aplica vetos_de_activo. Devuelve (activos que sobreviven, conflictos).

    Un veto de ropa elimina el activo que lo contradice. El color es la
    excepción: lo declarado manda siempre, así que un veto de color no lo quita,
    lo DECLARA en conflicto y le baja la fuerza. Arreglar la paleta es de
    app/paletas.py; aquí solo se dice la verdad de lo que la persona ha pedido.
    """
    if not isinstance(respuestas_visual, dict):
        respuestas_visual = {}
    tabla = _datos().get("vetos_de_activo", {})
    conf = _datos().get("conflicto_color", {})

    claves_fuera: set[str] = set()
    palabras_prohibidas: set[str] = set()
    vetos_color: list[str] = []

    for pid, mapa in tabla.items():
        if pid.startswith("_"):
            continue
        for valor in _lista(respuestas_visual.get(pid)):
            for accion in mapa.get(valor, []) if isinstance(mapa, dict) else []:
                if accion.startswith("@prohibe_palabra:"):
                    palabras_prohibidas.add(_normalizar(accion.split(":", 1)[1]))
                elif accion.startswith("@conflicto_color"):
                    vetos_color.append(valor)
                elif accion.startswith("@"):
                    continue
                else:
                    claves_fuera.add(accion)

    # ¿El color declarado pertenece de verdad a alguna familia vetada? Si no,
    # veto y color conviven y no hay nada que declarar.
    conflicto_texto: str | None = None
    declarado_val = respuestas_visual.get("VIS-CR-3")
    declarado = _colores().get("colores_declarados", {}).get(declarado_val)
    if declarado and vetos_color:
        familias_color = paletas_mod.clasificar(declarado["hex"])
        for veto in vetos_color:
            familias_veto = set(conf.get("familias", {}).get(veto, []))
            if familias_color & familias_veto:
                conflicto_texto = (
                    conf.get("texto", "")
                    .replace("{color}", str(declarado.get("nombre", "tu color")))
                    .replace("{familia}", conf.get("etiquetas", {}).get(veto, veto))
                )
                break

    salida: list[dict[str, Any]] = []
    conflictos: list[dict[str, Any]] = []
    for activo in activos:
        if activo["clave"] in claves_fuera:
            continue
        texto_activo = _normalizar(f"{activo.get('valor')} {activo.get('etiqueta')}")
        if any(p and p in texto_activo for p in palabras_prohibidas):
            continue
        if activo["tipo"] == "color" and conflicto_texto and activo["declarado"]:
            activo["conflicto"] = conflicto_texto
            activo["fuerza"] = min(activo["fuerza"], 2)
            conflictos.append(
                {
                    "clave": activo["clave"],
                    "ids": ["VIS-CR-3", "VIS-CR-2", "VIS-RO-2"],
                    "texto": conflicto_texto,
                }
            )
        salida.append(activo)

    return salida, conflictos


# ------------------------------------------------------------------ sistema

def sistema_activos(
    respuestas: dict[str, Any],
    mods: dict[str, Any] | None,
    paletas: list[dict[str, Any]] | None,
    ficha: dict[str, Any] | None,
) -> dict[str, Any]:
    """Todos los activos distintivos que salen del cuestionario.

    Devuelve {'activos': list, 'fuertes': int, 'avisos': list, 'conflictos': list}.
    Los avisos comparten forma con los de scoring ({tipo, titulo, texto}) para que
    el informe los añada a la lista de siempre sin tocar las plantillas.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    ficha = ficha if isinstance(ficha, dict) else {}
    visual = respuestas.get("visual") if isinstance(respuestas.get("visual"), dict) else {}

    activos: list[dict[str, Any]] = []
    avisos: list[dict[str, Any]] = []

    color = _activo_color(respuestas, paletas, ficha)
    if color:
        activos.append(color)

    silueta = _activo_silueta(respuestas, mods)
    if silueta:
        activos.append(silueta)

    sellos, renuncia = _activos_sello(respuestas, mods)
    activos.extend(sellos)
    if renuncia:
        avisos.append(
            {
                "tipo": "renuncia_a_sello",
                "titulo": "Has renunciado a tener sello",
                "texto": (
                    "Es una opción legítima y tiene precio: te reconocerán por lo "
                    "que haces y por tu constancia, no por tu imagen, y eso tarda "
                    "años en vez de meses. Si en algún momento quieres acortar el "
                    "camino, vuelve a VIS-RO-5 y elige una sola cosa."
                ),
            }
        )

    for candidato in (
        _activo_peinado(respuestas, mods),
        _activo_uniforme(respuestas),
        _activo_encuadre(respuestas),
    ):
        if candidato:
            activos.append(candidato)

    formatos_gestos, sin_concretar = _activos_formato_y_gesto(respuestas, mods)
    activos.extend(formatos_gestos)
    if sin_concretar:
        avisos.append(
            {
                "tipo": "activo_sin_concretar",
                "titulo": "Tu ritual no tiene nombre propio",
                "texto": (
                    "Has marcado la categoría, no el objeto. Un activo sin nombre "
                    "propio no se reconoce: vuelve y escribe cuál."
                ),
            }
        )

    activos.extend(_activos_palabra(respuestas, ficha, mods))

    tipografia = _activo_tipografia(ficha)
    if tipografia:
        activos.append(tipografia)

    activos, conflictos = _filtrar(activos, visual)

    # La tipografía no cuenta: no la ha elegido la persona en ninguna pregunta,
    # viene de la ficha del arquetipo y por eso no es suya.
    fuertes = sum(1 for a in activos if a["fuerza"] >= 2 and a["tipo"] != "tipografia")

    if fuertes < 2:
        avisos.append(
            {
                "tipo": "sin_activos",
                "titulo": "No tienes con qué te reconozcan",
                "texto": (
                    "Tienes opiniones, no marca. De todo el cuestionario no sale ni "
                    "una sola cosa que alguien pueda describir de memoria: ni un "
                    "color, ni un objeto, ni un formato fijo. Vuelve a VIS-RO-5, "
                    "ACC-CT-2 y ACC-RI-2 y elige algo. Cualquier cosa aburrida "
                    "repetida cincuenta veces vale más que esto."
                ),
            }
        )
    elif fuertes > 6:
        avisos.append(
            {
                "tipo": "demasiados_activos",
                "titulo": "Seis sellos no son un sistema",
                "texto": (
                    "Son un disfraz. Quédate con tres: el color, uno visual y uno "
                    "de formato. Los otros se caen solos en el mes cuatro y se "
                    "llevan por delante la credibilidad de los que quedan."
                ),
            }
        )

    return {
        "activos": activos,
        "fuertes": fuertes,
        "avisos": avisos,
        "conflictos": conflictos,
    }


# ------------------------------------------------------------------ índices

def indice_identificabilidad(
    activos: list[dict[str, Any]], respuestas: dict[str, Any]
) -> dict[str, Any]:
    """¿Hay algo que repetir? Mide material propio, no calidad de posicionamiento.

    Frontera con los otros índices: este mide si EXISTE un activo; la distinción
    (si además te separa de tu gremio) necesita el bloque de contexto de sector
    que hoy no existe, y no se calcula aquí ni se adivina.

    Los pesos se renormalizan sobre los componentes con dato, así que un
    cuestionario a medias no sale artificialmente bajo por lo que no contestó.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    activos = activos or []
    utiles = [a for a in activos if a.get("tipo") != "tipografia"]

    componentes: dict[str, dict[str, Any]] = {}

    # --- color (25)
    color = next((a for a in utiles if a["tipo"] == "color"), None)
    if color is None:
        d_color = 0.0
    elif not color["declarado"]:
        d_color = 0.0
    elif color["fuerza"] >= 3:
        d_color = 100.0
    else:
        d_color = 60.0  # monocromo o en conflicto con su propio veto
    componentes["color"] = {"peso": 25, "valor": d_color}

    # --- sello (20)
    sellos = [a for a in utiles if a["tipo"] == "sello"]
    if any(a["fuerza"] >= 2 for a in sellos):
        d_sello = 100.0
    elif sellos:
        d_sello = 50.0
    else:
        d_sello = 0.0
    componentes["sello"] = {"peso": 20, "valor": d_sello}

    # --- formato (20)
    ancla = _r(respuestas, "ACC-CT-2")
    rituales = {v for v in _lista(_r(respuestas, "ACC-RI-1")) if isinstance(v, str)}
    if ancla and rituales & RITUALES_FORMATO:
        d_formato = 100.0
    elif ancla:
        d_formato = 60.0
    else:
        d_formato = 0.0
    componentes["formato"] = {"peso": 20, "valor": d_formato}

    # --- gesto (20)
    propio = next((a for a in utiles if a["clave"] == "gesto:propio"), None)
    if propio and propio["fuerza"] >= 3:
        d_gesto = 100.0
    elif any(a["tipo"] == "gesto" for a in utiles):
        d_gesto = 60.0
    else:
        d_gesto = 0.0
    componentes["gesto"] = {"peso": 20, "valor": d_gesto}

    # --- disposición a repetir (15). Único componente que puede faltar del todo.
    valores = [
        v for v in (_num(_r(respuestas, pid))
                    for pid in ("COM-LI-6", "ACC-HO-3", "VIS-AU-3", "VIS-CA-7"))
        if v is not None
    ]
    if valores:
        media = sum(valores) / len(valores)
        componentes["repeticion"] = {
            "peso": 15,
            "valor": max(0.0, min(100.0, 100.0 * (media - 1) / 4)),
        }

    total_pesos = sum(c["peso"] for c in componentes.values())
    indice = round(
        sum(c["peso"] * c["valor"] for c in componentes.values()) / total_pesos, 1
    ) if total_pesos else 0.0

    if indice < 35:
        nivel = "invisible"
        lectura = (
            "No hay nada que repetir. Da igual lo bien que esté tu posicionamiento: "
            "si no hay un color, un objeto o un formato que vuelva cada semana, "
            "nadie va a poder describirte cuando no estés delante. Empieza por lo "
            "más barato: un color y un día de la semana."
        )
    elif indice < 65:
        nivel = "reconocible con esfuerzo"
        lectura = (
            "Tienes con qué, pero repartido. Coge los dos activos más fuertes de tu "
            "lista y súbelos al 100 % de tus piezas durante doce meses; el resto, "
            "apárcalo."
        )
    else:
        nivel = "inconfundible"
        lectura = (
            "Tienes un sistema. El trabajo de aquí en adelante no es mejorarlo: es "
            "no tocarlo. Los sistemas de identidad se rompen por aburrimiento del "
            "dueño, nunca por hartazgo del público."
        )

    return {
        "indice": indice,
        "nivel": nivel,
        "lectura": lectura,
        "componentes": {
            k: {"peso": v["peso"], "valor": round(v["valor"], 1)}
            for k, v in componentes.items()
        },
    }


def reconocimiento_3s(
    activos: list[dict[str, Any]], respuestas: dict[str, Any]
) -> dict[str, Any]:
    """Lo que le queda a alguien que pasa el dedo por tu perfil tres segundos.

    Cuatro comprobaciones y no cinco. La quinta natural —que tu color no sea el
    de todo tu sector— exige un bloque de contexto competitivo que hoy no se
    pregunta, y preferimos un hueco declarado a un número inventado.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    activos = activos or []

    sellos = [v for v in _lista(_r(respuestas, "VIS-RO-5")) if v != "ninguna_firma"]
    rituales = {v for v in _lista(_r(respuestas, "ACC-RI-1")) if isinstance(v, str)}
    v_uniforme = _num(_r(respuestas, "VIS-AU-3")) or 0
    v_peinado = _num(_r(respuestas, "VIS-CA-7")) or 0

    comprobaciones = [
        {
            "pasa": bool(_r(respuestas, "VIS-CR-3")),
            "texto": "Hay un color que es tuyo y lo has dicho en voz alta.",
            "fuente": "VIS-CR-3",
        },
        {
            "pasa": bool(sellos),
            "texto": "Hay un detalle visible que llevas siempre.",
            "fuente": "VIS-RO-5",
        },
        {
            "pasa": bool(_r(respuestas, "ACC-CT-2")),
            "texto": "Hay algo que publicas siempre, pase lo que pase.",
            "fuente": "ACC-CT-2",
        },
        {
            "pasa": bool(
                v_uniforme >= 4 or v_peinado >= 4 or (rituales & {"color", "objeto", "gesto"})
            ),
            "texto": "Hay una constante que se repite en todas tus piezas.",
            "fuente": "VIS-AU-3 / VIS-CA-7 / ACC-RI-1",
        },
    ]
    puntos = sum(1 for c in comprobaciones if c["pasa"])

    if puntos <= 1:
        lectura = "Si alguien pasa el dedo por tu perfil tres segundos, no le queda nada."
    elif puntos == 2:
        lectura = "Le queda una cosa. Con una se puede empezar."
    else:
        lectura = "En tres segundos te reconocen."

    return {"puntos": puntos, "comprobaciones": comprobaciones, "lectura": lectura}


# ------------------------------------------------------------------ calendario

def regla_repeticion(respuestas: dict[str, Any]) -> dict[str, Any]:
    """Doce meses de repetición, calculados. No lo escribe la IA a propósito.

    Un calendario es aritmética sobre cuatro respuestas: si lo genera un modelo
    cambia en cada llamada y deja de ser auditable. Las revisiones van por
    criterio cumplido (¿te han descrito con tu activo?) y no por fecha, porque
    una fecha invita a esperar y un criterio invita a comprobar.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    mods = None
    try:
        mods = contenido.modulos()
    except Exception:
        mods = None

    cadencia_val = _r(respuestas, "COM-CA-3")
    piezas = PIEZAS_POR_CADENCIA.get(cadencia_val, 4)
    horas_val = _r(respuestas, "ACC-TR-1")
    horas = HORAS_POR_TRAMO.get(horas_val)

    ancla_val = _r(respuestas, "ACC-CT-2")
    ancla = _etiqueta_opcion("ACC-CT-2", ancla_val, mods) if ancla_val else ""

    rituales: list[str] = []
    for valor in _lista(_r(respuestas, "ACC-RI-1")):
        if isinstance(valor, str):
            rituales.append(_etiqueta_opcion("ACC-RI-1", valor, mods))
    propio = _texto(_r(respuestas, "ACC-RI-2"))
    if propio:
        rituales.append(propio)

    revisiones = {
        3: (
            f"¿Has publicado {piezas * 3} piezas? Si no, el problema es la cadencia, "
            "no el mensaje: bájala un nivel y sigue."
        ),
        6: (
            "¿Alguien te ha descrito con tu activo sin que tú lo nombraras? Si no, "
            "súbelo de tamaño, no lo cambies."
        ),
        12: "Ahora, y solo ahora, puedes cambiar UN activo. Uno.",
    }

    meses = [
        {
            "mes": m,
            "piezas": piezas,
            "ancla": ancla,
            "rituales": list(rituales),
            "revision": revisiones.get(m),
        }
        for m in range(1, 13)
    ]

    return {
        "cabecera": (
            "Ninguno de tus activos se toca hasta el mes 13. Cambiar de sello a los "
            "cuatro meses no es mejorar: es empezar de cero y tirar los cuatro meses."
        ),
        "cadencia": {
            "valor": cadencia_val,
            "etiqueta": _etiqueta_opcion("COM-CA-3", cadencia_val, mods) if cadencia_val else "",
            "piezas_mes": piezas,
            "horas_semana": horas,
            "etiqueta_horas": _etiqueta_opcion("ACC-TR-1", horas_val, mods) if horas_val else "",
        },
        "meses": meses,
        "contradicciones": _contradicciones(respuestas, mods),
    }


def _contradicciones(
    respuestas: dict[str, Any], mods: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Choques entre lo que se ha prometido publicar y lo que se puede sostener.

    Cada una cita los dos ids y las dos etiquetas: sin la cita es una regañina,
    con la cita es una contradicción que la persona puede ir a mirar y arreglar.
    """
    salida: list[dict[str, Any]] = []

    cadencia = _r(respuestas, "COM-CA-3")
    horas = _r(respuestas, "ACC-TR-1")
    ancla = _r(respuestas, "ACC-CT-2")
    rituales = {v for v in _lista(_r(respuestas, "ACC-RI-1")) if isinstance(v, str)}
    video = _num(_r(respuestas, "ACC-DI-5"))
    horizonte = _r(respuestas, "ACC-HO-2")
    aguante = _num(_r(respuestas, "ACC-HO-3"))

    def etiqueta(pid: str, valor: Any) -> str:
        return _etiqueta_opcion(pid, valor, mods)

    if cadencia in ("diario", "semanal_3") and horas in ("menos_2", "2_5"):
        salida.append(
            {
                "ids": ["COM-CA-3", "ACC-TR-1"],
                "texto": (
                    f"Has dicho que publicarás «{etiqueta('COM-CA-3', cadencia)}» y que "
                    f"tienes «{etiqueta('ACC-TR-1', horas)}» a la semana. No sale. La "
                    "cadencia es lo primero que se cae y arrastra todo lo demás: "
                    "bájala un nivel ahora, no en el mes tres."
                ),
            }
        )

    if ancla in ("video_semanal", "directo_ancla") and video is not None and video <= 2:
        que_cae = "el vídeo" if ancla == "video_semanal" else "el directo"
        salida.append(
            {
                "ids": ["ACC-CT-2", "ACC-DI-5"],
                "texto": (
                    f"Has fijado «{etiqueta('ACC-CT-2', ancla)}» como lo único que "
                    f"publicarás siempre y has puesto {video}/5 a "
                    f"«{_texto_pregunta('ACC-DI-5', mods)}». Una de las dos cosas es "
                    f"mentira, y la que se va a caer es {que_cae}."
                ),
            }
        )

    if "formato_fijo" in rituales and cadencia == "campanas":
        salida.append(
            {
                "ids": ["ACC-RI-1", "COM-CA-3"],
                "texto": (
                    f"Te has comprometido a «{etiqueta('ACC-RI-1', 'formato_fijo')}» y a "
                    f"la vez has dicho que publicarás «{etiqueta('COM-CA-3', cadencia)}». "
                    "Un formato fijo a rachas no es un formato fijo: es una cita a la "
                    "que faltas, y a esas la gente deja de venir."
                ),
            }
        )

    if horizonte == "meses_3" and aguante is not None and aguante <= 2:
        salida.append(
            {
                "ids": ["ACC-HO-2", "ACC-HO-3"],
                "texto": (
                    f"Esperas resultados «{etiqueta('ACC-HO-2', horizonte)}» y has puesto "
                    f"{aguante}/5 a «{_texto_pregunta('ACC-HO-3', mods)}». Con esa "
                    "combinación lo dejas en el mes cuatro, justo antes de que empiece "
                    "a funcionar. O alargas el plazo o te montas victorias pequeñas "
                    "por el camino."
                ),
            }
        )

    return salida


# ------------------------------------------------------------------ palabras

def identidad_verbal(
    respuestas: dict[str, Any], ficha: dict[str, Any]
) -> dict[str, Any]:
    """Cinco palabras que son tuyas y cinco que no vuelves a decir.

    Se distingue lo ganado de lo prestado: una palabra del arquetipo que la
    persona no usa nunca se le va a caer en el mes dos, y decirlo por adelantado
    vale más que fingir que tiene cinco.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    ficha = ficha if isinstance(ficha, dict) else {}
    comunicacion = ficha.get("comunicacion", {})
    vocabulario = list(comunicacion.get("vocabulario", []))

    corpus = " ".join(
        _normalizar(_texto(_r(respuestas, pid))) for pid in ("COM-PA-2", "COM-PA-3")
    )
    for valor in _lista(_r(respuestas, "COM-NA-3")):
        corpus += " " + _normalizar(_etiqueta_opcion("COM-NA-3", valor))
    tokens = _tokens(corpus)

    propias: list[dict[str, str]] = []
    for termino in vocabulario:
        norm = _normalizar(termino)
        if not norm:
            continue
        usada = norm in corpus if " " in norm else norm in tokens
        if usada:
            propias.append({"palabra": termino, "origen": "tuya"})
    ganadas = len(propias)

    for termino in vocabulario:
        if len(propias) >= 5:
            break
        if any(p["palabra"] == termino for p in propias):
            continue
        propias.append({"palabra": termino, "origen": "prestada"})
    propias = propias[:5]

    prohibidas: list[dict[str, str]] = []

    def añadir(palabra: str, origen: str) -> None:
        limpia = palabra.strip(" .,;:—-").strip()
        if not limpia or len(prohibidas) >= 5:
            return
        if any(_normalizar(p["palabra"]) == _normalizar(limpia) for p in prohibidas):
            return
        prohibidas.append({"palabra": limpia, "origen": origen})

    for frase in _partir(_texto(_r(respuestas, "COM-NA-4"))):
        añadir(frase, "COM-NA-4")
    for frase in _partir(comunicacion.get("evitar", "")):
        añadir(frase, "arquetipo")
    for valor in _lista(_r(respuestas, "COM-CX-3")):
        añadir(_etiqueta_opcion("COM-CX-3", valor), "COM-CX-3")

    return {"propias": propias, "prohibidas": prohibidas, "ganadas": ganadas}


def _partir(texto: str) -> list[str]:
    """Parte un texto libre en frases cortas por los signos que separan ideas."""
    if not texto:
        return []
    trozos = [texto]
    for signo in (".", ";", ",", "\n"):
        siguiente: list[str] = []
        for t in trozos:
            siguiente.extend(t.split(signo))
        trozos = siguiente
    return [t.strip() for t in trozos if len(t.strip()) > 2]


# ------------------------------------------------------------------ una cosa

def una_sola_cosa_borrador(
    respuestas: dict[str, Any],
    activos: list[dict[str, Any]],
    mods: dict[str, Any] | None = None,
) -> str | None:
    """Candidato determinista de «una sola cosa», para que el informe sin IA no
    salga vacío. Se pinta rotulado como borrador: la versión buena la escribe la
    IA, que sí puede juzgar si suena a algo. Devuelve None si falta material.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    territorios = _lista(_r(respuestas, "COM-NA-3"))
    if not territorios:
        return None
    primero = territorios[0]

    datos = _nombres()
    sustantivo = datos.get("territorios", {}).get(primero)
    if not sustantivo:
        sustantivo = _etiqueta_opcion("COM-NA-3", primero, mods)
    if not sustantivo:
        return None
    articulo = datos.get("articulos_territorio", {}).get(primero, "el")

    candidatos = [
        a for a in (activos or [])
        if a.get("tipo") != "tipografia" and a.get("fuerza", 0) >= 1 and a.get("valor")
    ]
    if not candidatos:
        return None
    def prioridad(a: dict[str, Any]) -> tuple[int, int]:
        tipo = a.get("tipo", "")
        posicion = ORDEN_DESEMPATE.index(tipo) if tipo in ORDEN_DESEMPATE else len(ORDEN_DESEMPATE)
        return (-a["fuerza"], posicion)

    mejor = min(candidatos, key=prioridad)
    nombre = _nombre_corto(mejor, respuestas, mods)
    if not nombre:
        return None

    cabeza = f"{articulo} {str(sustantivo).lower()}".strip()
    return f"{cabeza[:1].upper()}{cabeza[1:]} {_de(nombre)}"


def _de(nombre: str) -> str:
    """«de» + sintagma, contrayendo de+el en del como manda el español."""
    if nombre.startswith("el "):
        return "del " + nombre[3:]
    return "de " + nombre


def _nombre_corto(
    activo: dict[str, Any], respuestas: dict[str, Any], mods: dict[str, Any] | None
) -> str:
    """Sintagma corto de un activo, para meterlo dentro de una frase."""
    clave = activo.get("clave", "")
    tipo = activo.get("tipo", "")

    if clave.startswith("sello:"):
        return _rotulo("VIS-RO-5", clave.split(":", 1)[1], "nombre", mods)
    if clave == "formato:ancla":
        valor = _r(respuestas, "ACC-CT-2")
        return _rotulo("ACC-CT-2", valor, "nombre", mods) if valor else "el formato"
    # Los rituales llevan el id de la pregunta y el valor dentro de la clave:
    # «gesto:ACC-RI-1.objeto».
    if "ACC-RI-1." in clave:
        return _rotulo("ACC-RI-1", clave.split("ACC-RI-1.", 1)[1], "nombre", mods)
    if tipo == "color":
        _, declarado = _color_declarado(respuestas)
        if declarado:
            return f"el {str(declarado.get('nombre', 'color')).lower()}"
        return "el color"
    if tipo == "palabra" and activo.get("valor"):
        return f"la palabra «{activo['valor']}»"
    return {
        "silueta": "la silueta",
        "peinado": "el peinado",
        "uniforme": "el uniforme",
        "encuadre": "el encuadre",
        "gesto": "el gesto",
        "formato": "el formato",
    }.get(tipo, "")
