"""Motor de puntuación del test de arquetipos, de los tres módulos y de los
cinco índices que deciden si el informe se puede emitir.

Tres decisiones que separan esto de un test de arquetipos corriente:

1. Corrección de aquiescencia. La gente puntúa alto en todo ("sí, mi marca es
   sabia... y heroica... y creativa"). Restamos la media global de cada escala,
   así que lo que sale no es "cuánto te gusta cada arquetipo" sino tu perfil
   RELATIVO. Sin esto, el resultado es un ranking de deseabilidad social.

2. Escala teórica fija en vez de min-max sobre las 12 puntuaciones del sujeto.
   Un min-max forzaría al primario a 100 y al último a 0 SIEMPRE, y haría
   invisible el caso más informativo: el perfil plano.
   Ojo con la frase que estuvo aquí durante meses: «quien contesta lo mismo a
   todo sale con doce cincuentas» SOLO es cierto contestando 3. Comprobado: con
   5 en todo salen 54,2 para los ocho arquetipos sin ítem inverso y 41,7 para
   BUF, EXP, INO y GOB; con 1 en todo, al revés. Los 4 ítems inversos (BUF-4,
   EXP-4, INO-4, GOB-4) rompen la simetría de la corrección de aquiescencia
   porque no hay uno por arquetipo. Lo correcto sería 12 de 48, uno por
   arquetipo; se deja documentado y no se toca aquí, porque reescribir 8 ítems
   del instrumento en la misma versión en que se cambian 20 preguntas de módulo
   impide saber a qué se debe cualquier cambio en los resultados.

3. Un perfil plano es un diagnóstico, no un fallo de medida — pero se decide por
   el HUECO en cabeza, no por sigma a secas (ver `puntuar_arquetipos`).

Y una regla que atraviesa todo el fichero: una pregunta que se contesta tiene que
puntuar en algún sitio. Cada tipo nuevo necesita rama en `afinidad_por_modulo`,
en `_pregunta_es_tibia` y en el índice que le toque; si falta una, la pregunta se
contesta y el motor no la ve, que es el bug que ACC-RI-2 arrastró desde el día
uno.

Nada de aquí llama a la IA ni toca la base: mismos datos, mismo resultado.
"""

from __future__ import annotations

import difflib
import re
import statistics
import unicodedata
from typing import Any

# Con 4 ítems Likert 1-5 por arquetipo: bruto en [4, 20], media global en [1, 5],
# luego bruto - (4 x media) cae en [-16, 16]. Fijamos ahí la escala.
ITEMS_POR_ARQUETIPO = 4

UMBRAL_EMPATE = 5.0
UMBRAL_SOBREEXPRESION = 85.0
UMBRAL_PUNTO_CIEGO = 20.0
UMBRAL_INCOHERENCIA = 70.0

# Secundario y terciario ABSOLUTOS. Los umbrales relativos de antes (0,80 y 0,70
# de p1) hacían que definirse quitara arquetipos y que ser tibio los regalara:
# con la escala centrada la media de las 12 puntuaciones es siempre 50,0, así que
# con p1 < 62,5 el corte del secundario caía POR DEBAJO de 50 y se llamaba
# «secundario» a algo que el propio informe describe como «esto no va contigo».
UMBRAL_SECUNDARIO_ABS = 60.0
UMBRAL_TERCIARIO_ABS = 55.0
MARGEN_SECUNDARIO = 15.0   # y además el secundario no puede alejarse más de esto de p1

# Rondas de muro. Está arriba a propósito: antes vivía debajo de la función que la
# usa y solo funcionaba por resolución en tiempo de llamada.
MAX_RONDAS_TIBIEZA = 2

# Tibieza por sección. Un único saco escondía que el test se llevaba el 62 % del
# denominador: esconderse en los 48 ítems salía gratis porque el porcentaje global
# apenas se movía. Ahora cada sección tiene su propio umbral y dispara sola.
UMBRAL_TIBIEZA_TEST = 15.0     # % sobre los ítems contestados del test
UMBRAL_TIBIEZA_MODULO = 22.0   # % sobre las preguntas puntuables de CADA módulo
UMBRAL_TIBIEZA_GLOBAL = 20.0   # % sobre el denominador combinado
MIN_TEXTOS_POBRES = 2          # a partir de aquí dispara el motivo texto_pobre

LIKERT_TIBIO = 3          # el centro de la escala 1-5
BIPOLAR_ESCALA = 7        # el valor por defecto; el centro se calcula POR PREGUNTA

# Coherencia del perfil. El techo real de sigma es 25,0 (la mitad de los
# arquetipos arriba y la otra mitad abajo), no los 13,8 del patrón «5 en uno, 1 en
# el resto» que se usó para calibrar los umbrales viejos. Con 6,5 se llamaba
# «definido» a perfiles por debajo de la distribución nula: contestar al azar da
# sigma ~8,3 solo por varianza de muestreo con 4 ítems.
SIGMA_MAX_TEORICO = 25.0
SIGMA_PLANO = 8.5
SIGMA_DEFINIDO = 12.0

# El hueco en cabeza (p1 − p4) manda sobre sigma: es lo que decide si hay algo que
# contar. Sigma se queda como métrica secundaria, que es lo que siempre fue.
HUECO_PLANO = 6.0
HUECO_DEFINIDO = 12.0

# Control de estilo de respuesta: si dentro de cada arquetipo las respuestas se
# contradicen tanto como entre arquetipos, no hay perfil, hay ruido. Un
# respondiente coherente ronda 0,6; los clics al azar, 4.
RATIO_RUIDO = 2.5

# Diferencia mínima entre familias para acusar de tensión de identidad. Sin esto,
# cuatro familias empatadas a 50,0 exactos emiten el aviso más grave del informe
# con 0,0 puntos de diferencia, porque max() resuelve por orden de inserción.
MARGEN_TENSION_FAMILIA = 5.0

# Si la media global se va a un extremo, el sujeto ha contestado casi lo mismo a
# todo. El perfil relativo sigue siendo válido, pero conviene decírselo.
MEDIA_ACQUIESCENCIA_ALTA = 4.2
MEDIA_ACQUIESCENCIA_BAJA = 1.8

SECCIONES_MODULO = ("comunicacion", "visual", "acciones")


# --------------------------------------------------------------- utilidades

def _seccion(respuestas: dict[str, Any], nombre: str) -> dict[str, Any]:
    """Una sección de respuestas, siempre como dict. El cuestionario se puede
    enviar a medias y las secciones llegan a None más veces de las que parece."""
    if not isinstance(respuestas, dict):
        return {}
    valor = respuestas.get(nombre)
    return valor if isinstance(valor, dict) else {}


def _num(valor: Any) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _entero(valor: Any) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _lista(valor: Any) -> list[Any]:
    if isinstance(valor, list):
        return valor
    if valor in (None, "", {}):
        return []
    return [valor]


def _norm(texto: Any) -> str:
    """Normalización declarada en lexico_evasion.json: minúsculas, sin tildes,
    la puntuación a espacio y los espacios colapsados. Todas las comparaciones
    del léxico se hacen aquí; comparar contra el texto crudo sería una lista
    negra que se esquiva escribiendo «No sé.» con mayúscula."""
    if not isinstance(texto, str):
        texto = "" if texto is None else str(texto)
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    sin_tildes = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    limpio = re.sub(r"[^0-9a-z\s]", " ", sin_tildes)
    return " ".join(limpio.split())


def _texto_de(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def indice_preguntas(modulos: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """{id_pregunta: {'seccion', 'bloque', 'pregunta'}} de los tres módulos.

    Media docena de funciones necesitan ir de un id suelto a su pregunta; sin
    este índice cada una se escribiría su triple bucle y acabarían divergiendo.
    """
    salida: dict[str, dict[str, Any]] = {}
    for seccion, modulo in (modulos or {}).items():
        if not isinstance(modulo, dict):
            continue
        for bloque in modulo.get("bloques", []) or []:
            for pregunta in bloque.get("preguntas", []) or []:
                salida[pregunta["id"]] = {
                    "seccion": seccion,
                    "bloque": bloque,
                    "pregunta": pregunta,
                }
    return salida


def centro_bipolar(pregunta: dict[str, Any]) -> float:
    """El punto muerto de un deslizador, POR PREGUNTA.

    Calcularlo de una constante global era una bomba de relojería: el día que
    entrara un bipolar de escala 5, su centro sería 3 y la tibieza dejaría de
    detectarse en silencio.
    """
    escala = pregunta.get("escala", BIPOLAR_ESCALA)
    try:
        return (float(escala) + 1) / 2
    except (TypeError, ValueError):
        return (BIPOLAR_ESCALA + 1) / 2


def _valor_bipolar(pregunta: dict[str, Any], valor: Any) -> tuple[float | None, float, bool | None]:
    """(valor, centro, tocado).

    Un número suelto cuenta como respuesta deliberada. Antes no: el deslizador
    nacía en el centro y el propio programa escribía ese 4 con solo pintar la
    pregunta, así que un número suelto podía ser una pregunta sin contestar. Ese
    deslizador ya no existe — form.js pinta siete botones y ninguno viene
    marcado —, de modo que si hay número es porque alguien lo pulsó. Mantenerlo
    en None dejaba las nueve bipolares fuera del muro: ni en el numerador ni en
    el denominador, es decir, elegir el punto muerto salía gratis.

    Se sigue aceptando {'valor': n, 'tocado': bool} por si un cliente quiere
    declarar explícitamente que no se tocó (envíos parciales, importaciones).
    """
    centro = centro_bipolar(pregunta)
    tocado: bool | None = True
    if isinstance(valor, dict):
        tocado = bool(valor.get("tocado", True))
        valor = valor.get("valor")
    return _num(valor), centro, tocado


# ----------------------------------------------------- test de arquetipos

def _normalizar(corregido: float, n_items: int = ITEMS_POR_ARQUETIPO) -> float:
    """Lleva una puntuación corregida a 0-100 sobre la escala teórica.

    El rango depende del número de ítems del arquetipo (4 x n), no de una
    constante: con el rango fijo ±16, un envío parcial comprimía las
    puntuaciones hacia 50 sin avisar de nada.
    """
    tope = 4.0 * max(1, n_items)
    bruto = 100.0 * (corregido + tope) / (2 * tope)
    return round(max(0.0, min(100.0, bruto)), 1)


def puntuar_arquetipos(
    respuestas: dict[str, int],
    test: dict[str, Any],
    arquetipos: dict[str, Any],
    afinidad_global: dict[str, float] | None = None,
) -> dict[str, Any]:
    """respuestas: {id_item: valor 1-5}. Devuelve el perfil completo.

    `afinidad_global` es opcional y solo se usa como tercer criterio de
    desempate (lo que la persona ELIGE en los módulos, cuando el test empata y
    la elección forzada tampoco decide). Sin él, el desempate se queda en la
    tasa de elección forzada y el empate se declara en vez de inventarse.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    items = test["items"]
    indice = {it["id"]: it for it in items}

    # 1. Recodificar inversos.
    valores: dict[str, float] = {}
    for item_id, valor in respuestas.items():
        item = indice.get(item_id)
        if item is None:
            continue  # ítems de control y respuestas huérfanas
        v = _num(valor)
        if v is None:
            continue
        valores[item_id] = (6 - v) if item.get("inverso") else v

    if not valores:
        raise ValueError("No hay respuestas válidas del test de arquetipos.")

    media_global = statistics.fmean(valores.values())

    # 2 y 3. Bruto por arquetipo y corrección de aquiescencia.
    brutos: dict[str, float] = {}
    conteo: dict[str, int] = {}
    por_arquetipo: dict[str, list[float]] = {}
    for item_id, valor in valores.items():
        arq = indice[item_id]["arquetipo"]
        brutos[arq] = brutos.get(arq, 0.0) + valor
        conteo[arq] = conteo.get(arq, 0) + 1
        por_arquetipo.setdefault(arq, []).append(valor)

    # La invariante que nadie comprobaba. Un envío parcial producía un perfil de
    # aspecto normal calculado sobre 8 respuestas: mejor reventar aquí que emitir
    # un informe «definido» que no lo es.
    esperados = {it["arquetipo"] for it in items}
    for arq in sorted(esperados):
        if conteo.get(arq, 0) != ITEMS_POR_ARQUETIPO:
            raise ValueError(
                f"Faltan ítems del arquetipo {arq}: "
                f"{conteo.get(arq, 0)} de {ITEMS_POR_ARQUETIPO}"
            )

    puntuaciones: dict[str, float] = {}
    for arq, bruto in brutos.items():
        corregido = bruto - (conteo[arq] * media_global)
        puntuaciones[arq] = _normalizar(corregido, conteo[arq])

    # Elección forzada: lo menos falseable del test. Se usa como criterio de
    # desempate en los tres puestos, y por TASA, no por puntos brutos: los ocho
    # bloques reparten los arquetipos de forma desigual (CRE aparece en cuatro,
    # AMA/INO/COM/EXP/BUF en dos), así que sumar puntos favorece a Creador.
    fc = puntuar_eleccion_forzada(respuestas, test)
    tasa = fc["tasa"]

    def clave_orden(arq: str) -> tuple[float, float, float, str]:
        # Último criterio, el nombre: es arbitrario, pero es estable y auditable.
        # Antes ganaba el orden del fichero, que parecía un criterio y no lo era.
        return (
            puntuaciones[arq],
            tasa.get(arq, 0.0),
            (afinidad_global or {}).get(arq, 0.0),
            arq,
        )

    orden_arqs = sorted(puntuaciones, key=clave_orden, reverse=True)
    orden = [(a, puntuaciones[a]) for a in orden_arqs]
    primario, p1 = orden[0]

    # Desempate explícito en cabeza: si alguien está a menos de UMBRAL_EMPATE y
    # gana en tasa de elección forzada, se lo lleva.
    empate_con = [a for a, p in orden[1:] if (p1 - p) < UMBRAL_EMPATE]
    desempate_aplicado = False
    if empate_con:
        candidatos = [primario, *empate_con]
        ganador = max(candidatos, key=lambda a: (tasa.get(a, 0.0), puntuaciones[a], a))
        if ganador != primario and tasa.get(ganador, 0.0) > tasa.get(primario, 0.0):
            primario = ganador
            desempate_aplicado = True
            orden_arqs = sorted(
                puntuaciones, key=lambda a: (a == primario, *clave_orden(a)), reverse=True
            )
            orden = [(a, puntuaciones[a]) for a in orden_arqs]
            p1 = puntuaciones[primario]

    resto = [(a, p) for a, p in orden if a != primario]

    # Empates que NO se resuelven: se declaran. «Empatas en segundo lugar entre
    # cuatro, elige tú» es información; elegir por orden de fichero es mentir.
    def empatados_con(posicion: int) -> list[str]:
        if len(resto) <= posicion:
            return []
        referencia = resto[posicion][1]
        iguales = [a for a, p in resto[posicion:] if p == referencia]
        return iguales if len(iguales) > 1 else []

    empate_secundario = empatados_con(0)
    empate_terciario = empatados_con(1)

    secundario = None
    terciario = None
    if resto and resto[0][1] >= UMBRAL_SECUNDARIO_ABS and (p1 - resto[0][1]) <= MARGEN_SECUNDARIO:
        secundario = resto[0][0]
        if len(resto) > 1 and resto[1][1] >= UMBRAL_TERCIARIO_ABS:
            terciario = resto[1][0]

    # Coherencia: manda el hueco en cabeza. Sigma sigue publicándose porque es la
    # métrica que la portada lleva años enseñando, pero ya no decide sola.
    sigma = round(statistics.pstdev(puntuaciones.values()), 1)
    hueco = round(orden[0][1] - orden[3][1], 1) if len(orden) >= 4 else 0.0

    if hueco < HUECO_PLANO or (sigma < SIGMA_PLANO and hueco < HUECO_DEFINIDO):
        coherencia = "plano"
        lectura = (
            "Tu marca no tiene un arquetipo dominante claro. En branding eso no "
            "es neutralidad, es invisibilidad: si no eres nada en concreto, no "
            "hay razón para recordarte. Antes de tocar el logo o la ropa, "
            "necesitas decidir qué eres."
        )
    elif hueco >= HUECO_DEFINIDO and sigma >= SIGMA_PLANO:
        coherencia = "definido"
        lectura = (
            "Tu perfil está muy definido. Eso da reconocimiento inmediato; el "
            "riesgo es la caricatura. Vigila la sombra."
        )
    else:
        coherencia = "moderado"
        lectura = (
            "Tienes un arquetipo dominante, pero no domina con fuerza. Hay "
            "margen para afilar la identidad y ganar reconocimiento."
        )

    # Estilo de respuesta. Si dentro de cada arquetipo te contradices tanto como
    # entre arquetipos, el perfil no mide nada.
    var_intra = None
    var_entre = None
    estilo_respuesta = "coherente"
    if len(por_arquetipo) >= 2:
        var_intra = round(
            statistics.fmean(
                statistics.pvariance(vs) for vs in por_arquetipo.values() if len(vs) >= 2
            ),
            3,
        )
        var_entre = round(
            statistics.pvariance([statistics.fmean(vs) for vs in por_arquetipo.values()]), 3
        )
        if var_entre > 0 and (var_intra / var_entre) >= RATIO_RUIDO:
            estilo_respuesta = "ruido"

    # Sombra: sobreexpresión del primario y estado del arquetipo opuesto.
    ficha = arquetipos[primario]
    opuesto = ficha["opuesto"]
    p_opuesto = puntuaciones.get(opuesto, 50.0)
    distancia = p1 - min(puntuaciones.values())

    avisos: list[dict[str, str]] = []
    if estilo_respuesta == "ruido":
        avisos.append(
            {
                "tipo": "ruido",
                "titulo": "Esto no es un perfil, es ruido",
                "texto": (
                    "Dentro de cada arquetipo tus respuestas se contradicen tanto "
                    "como entre arquetipos. Eso no es un perfil: has ido rápido y "
                    "has contestado por impulso. Lo que salga de aquí describe tu "
                    "forma de rellenar formularios, no tu marca."
                ),
            }
        )
    if p1 >= UMBRAL_SOBREEXPRESION and distancia > 30:
        avisos.append(
            {
                "tipo": "sobreexpresion",
                "titulo": f"Riesgo de caricatura de {ficha['nombre']}",
                "texto": (
                    f"Tu arquetipo primario está muy por encima del resto. "
                    f"Llevado al extremo se convierte en su propia trampa: "
                    f"{ficha['sombra']}"
                ),
            }
        )
    if p_opuesto < UMBRAL_PUNTO_CIEGO:
        avisos.append(
            {
                "tipo": "punto_ciego",
                "titulo": f"Punto ciego: {arquetipos[opuesto]['nombre']}",
                "texto": (
                    f"Tu opuesto en la rueda está prácticamente ausente. No es "
                    f"un defecto, pero sí un ángulo muerto: te costará entender "
                    f"y conectar con quien se mueve por ahí."
                ),
            }
        )
    if media_global >= MEDIA_ACQUIESCENCIA_ALTA:
        avisos.append(
            {
                "tipo": "aquiescencia",
                "titulo": "Has dicho que sí a casi todo",
                "texto": (
                    "Tu media de respuesta es muy alta: casi todas las frases te "
                    "parecen ciertas para tu marca. El perfil que ves está "
                    "corregido para eso, así que sigue siendo útil, pero llegaría "
                    "más lejos si te hubieras atrevido a descartar. Una marca se "
                    "define tanto por lo que no es como por lo que es."
                ),
            }
        )
    elif media_global <= MEDIA_ACQUIESCENCIA_BAJA:
        avisos.append(
            {
                "tipo": "aquiescencia",
                "titulo": "Has dicho que no a casi todo",
                "texto": (
                    "Tu media de respuesta es muy baja: casi ninguna frase te "
                    "encaja. O tu marca es genuinamente atípica, o aún no sabes "
                    "qué quieres que sea. Merece la pena averiguar cuál de las dos "
                    "antes de seguir."
                ),
            }
        )
    if p_opuesto > UMBRAL_INCOHERENCIA and p1 > UMBRAL_INCOHERENCIA:
        avisos.append(
            {
                "tipo": "incoherencia",
                "titulo": "Tensión entre opuestos",
                "texto": (
                    f"{ficha['nombre']} y {arquetipos[opuesto]['nombre']} puntúan "
                    f"alto a la vez, y son opuestos en la rueda. O has encontrado "
                    f"una combinación genuinamente original, o tu marca está "
                    f"diciendo dos cosas incompatibles a la vez. Merece una "
                    f"decisión consciente."
                ),
            }
        )

    return {
        "puntuaciones": puntuaciones,
        "orden": [a for a, _ in orden],
        "primario": primario,
        "secundario": secundario,
        "terciario": terciario,
        "empate_secundario": empate_secundario,
        "empate_terciario": empate_terciario,
        "desempate_aplicado": desempate_aplicado,
        "tasa_fc": tasa,
        "concentracion_fc": fc["concentracion"],
        "media_global": round(media_global, 2),
        "sigma": sigma,
        "sigma_max_teorico": SIGMA_MAX_TEORICO,
        "hueco": hueco,
        "coherencia": coherencia,
        "lectura_coherencia": lectura,
        "estilo_respuesta": estilo_respuesta,
        "var_intra": var_intra,
        "var_entre": var_entre,
        "opuesto": opuesto,
        "avisos": avisos,
    }


def puntuar_eleccion_forzada(
    respuestas: dict[str, Any], test: dict[str, Any]
) -> dict[str, Any]:
    """Puntos, ocasiones y TASA de los bloques de elección forzada.

    Devuelve {'puntos', 'ocasiones', 'tasa', 'elegidos', 'concentracion'}. La
    tasa es lo único con lo que se puede desempatar: los ocho bloques no ofrecen
    los doce arquetipos el mismo número de veces, así que comparar puntos brutos
    era comparar oportunidades, no preferencias.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    puntos: dict[str, int] = {}
    ocasiones: dict[str, int] = {}
    elegidos: dict[str, str] = {}

    for bloque in test.get("eleccion_forzada", []) or []:
        for opcion in bloque.get("opciones", []):
            arq = opcion.get("arquetipo")
            if arq:
                ocasiones[arq] = ocasiones.get(arq, 0) + 1
        elegido = respuestas.get(bloque["id"])
        if elegido is None or elegido == "":
            continue
        for i, opcion in enumerate(bloque["opciones"]):
            # La respuesta puede llegar como índice o como texto del arquetipo.
            if str(elegido) in (str(i), opcion.get("arquetipo", "")):
                arq = opcion["arquetipo"]
                puntos[arq] = puntos.get(arq, 0) + opcion.get("puntos", 2)
                elegidos[bloque["id"]] = arq
                break

    tasa = {
        arq: round(puntos.get(arq, 0) / (2.0 * n), 3)
        for arq, n in ocasiones.items()
        if n
    }
    total = sum(puntos.values())
    concentracion = round(max(puntos.values()) / total, 3) if total else None

    return {
        "puntos": puntos,
        "ocasiones": ocasiones,
        "tasa": tasa,
        "elegidos": elegidos,
        "concentracion": concentracion,
    }


def puntuar_familias(
    puntuaciones: dict[str, float], familias: dict[str, Any]
) -> dict[str, Any]:
    """Media de cada familia cardinal. Más estable que el arquetipo suelto.

    `empate_familias` existe porque cuatro familias iguales es un dato, no una
    incoherencia: sin él, `max()` nombraba una dominante por orden de inserción.
    """
    medias: dict[str, float] = {}
    for clave, fam in familias.items():
        valores = [puntuaciones[a] for a in fam["arquetipos"] if a in puntuaciones]
        if valores:
            medias[clave] = round(statistics.fmean(valores), 1)
    dominante = max(medias, key=medias.get) if medias else None
    empate = (
        [k for k, v in medias.items() if abs(medias[dominante] - v) < 1.0]
        if dominante
        else []
    )
    return {
        "medias": medias,
        "dominante": dominante,
        "empate_familias": empate if len(empate) > 1 else [],
    }


def detectar_tension_identidad(
    primario: str,
    arquetipos: dict[str, Any],
    familias_resultado: dict[str, Any],
    familias: dict[str, Any],
) -> dict[str, str] | None:
    """La familia dominante no coincide con la familia del arquetipo primario.

    Señal de que la marca dice una cosa y su centro de gravedad está en otra. Es
    el aviso más grave del informe, así que exige una diferencia real: sin
    MARGEN_TENSION_FAMILIA se emitía con 0,0 puntos de diferencia a quien
    simplemente tenía las cuatro familias empatadas.
    """
    fam_primario = arquetipos[primario]["familia"]
    fam_dominante = familias_resultado.get("dominante")
    if not fam_dominante or fam_dominante == fam_primario:
        return None
    medias = familias_resultado.get("medias", {})
    if fam_primario not in medias or fam_dominante not in medias:
        return None
    if medias[fam_dominante] - medias[fam_primario] < MARGEN_TENSION_FAMILIA:
        return None
    return {
        "tipo": "tension_identidad",
        "titulo": "Tu centro de gravedad está en otro sitio",
        "texto": (
            f"Tu arquetipo primario es {arquetipos[primario]['nombre']}, de la "
            f"familia «{familias[fam_primario]['nombre']}». Pero el conjunto de "
            f"tus respuestas pesa más hacia «{familias[fam_dominante]['nombre']}». "
            f"Traducido: tu marca se presenta como una cosa y se mueve por otra. "
            f"Es la incoherencia más común y la más cara de arreglar tarde."
        ),
    }


# ------------------------------------------------------- afinidad de módulo

def _ficha_referente(ref_id: str, referentes: Any) -> dict[str, Any] | None:
    if isinstance(referentes, dict):
        ficha = referentes.get(ref_id)
        return ficha if isinstance(ficha, dict) else None
    for ficha in referentes or []:
        if isinstance(ficha, dict) and ficha.get("id") == ref_id:
            return ficha
    return None


def afinidad_por_modulo(
    respuestas: dict[str, Any],
    modulo: dict[str, Any],
    referentes: Any = None,
) -> dict[str, float]:
    """Afinidad de arquetipo que se deduce de las respuestas de un módulo.

    Cada opción del módulo lleva etiquetas de arquetipo. Sumamos las que el
    usuario ha elegido y normalizamos a 0-100 sobre el total del módulo. Sirve
    para triangular: lo que dices que eres frente a lo que eliges hacer.

    Todos los tipos tienen rama, incluidos los que no puntúan: una pregunta que
    se contesta y no aparece aquí es una pregunta que el motor no ve.
    `referentes` (para los duelos) se carga solo si hace falta.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    cuenta: dict[str, float] = {}

    def anotar(arqs: Any, peso: float = 1.0) -> None:
        for arq in arqs or []:
            if arq:
                cuenta[arq] = cuenta.get(arq, 0.0) + peso

    for bloque in modulo.get("bloques", []) or []:
        for pregunta in bloque.get("preguntas", []) or []:
            valor = respuestas.get(pregunta["id"])
            if valor is None or valor == "" or valor == [] or valor == {}:
                continue
            tipo = pregunta["tipo"]

            if tipo == "likert5":
                # Solo cuenta si está de acuerdo (4-5), con peso proporcional.
                v = _entero(valor)
                if v is None:
                    continue
                if v >= 4 and pregunta.get("arquetipos"):
                    anotar(pregunta["arquetipos"], peso=(v - 3) / 2)

            elif tipo == "bipolar":
                # Cada polo lleva sus etiquetas en el JSON (arquetipos_izq /
                # arquetipos_der). Mientras no las tenga, el bipolar sigue
                # puntuando en tibieza, en distinción y en las dimensiones, pero
                # no reparte arquetipo: inventarle uno sería peor que no darlo.
                v, centro, _tocado = _valor_bipolar(pregunta, valor)
                if v is None or centro <= 1 or v == centro:
                    continue
                peso = abs(v - centro) / (centro - 1)
                lado = "arquetipos_izq" if v < centro else "arquetipos_der"
                anotar(pregunta.get(lado), peso=peso)

            elif tipo in ("unica", "multiple"):
                elegidos = _lista(valor)
                for opcion in pregunta.get("opciones", []):
                    if opcion["valor"] in elegidos and opcion.get("arquetipos"):
                        anotar(opcion["arquetipos"])

            elif tipo == "ranking":
                # Pesos por puesto: elegir tercero no es lo mismo que elegir
                # primero, y la mecánica ya obliga a renunciar a las otras siete.
                opciones = {o["valor"]: o for o in pregunta.get("opciones", [])}
                for puesto, elegido in enumerate(_lista(valor)[:3]):
                    opcion = opciones.get(elegido)
                    if opcion and opcion.get("arquetipos"):
                        anotar(opcion["arquetipos"], peso=float(3 - puesto))

            elif tipo == "reparto100":
                # 25 puntos = un voto entero. Repartir 100 entre tres deja pesos
                # de 1,2-2,0; concentrar 60 en una vale por dos votos.
                if not isinstance(valor, dict):
                    continue
                opciones = {o["valor"]: o for o in pregunta.get("opciones", [])}
                for clave, puntos in valor.items():
                    p = _num(puntos)
                    opcion = opciones.get(clave)
                    if p and p > 0 and opcion and opcion.get("arquetipos"):
                        anotar(opcion["arquetipos"], peso=p / 25.0)

            elif tipo == "duelo":
                elegido = valor.get("elegido") if isinstance(valor, dict) else valor
                if not elegido:
                    continue
                if referentes is None:
                    from . import contenido as contenido_mod  # perezoso: scoring no depende del disco

                    referentes = contenido_mod.referentes()
                ficha = _ficha_referente(str(elegido), referentes)
                if ficha:
                    anotar(
                        [ficha.get("arquetipo_primario"), *ficha.get("arquetipos_secundarios", [])]
                    )

            elif tipo in ("texto", "texto_largo"):
                # Peso 0 a propósito: un texto libre no se puede repartir entre
                # arquetipos sin inventar. Puntúa en calidad_textos y en tibieza,
                # que es donde tiene sentido. La rama está aquí para que se vea
                # que la decisión es deliberada y no un tipo olvidado.
                continue

    total = sum(cuenta.values())
    if not total:
        return {}
    return {a: round(100.0 * v / total, 1) for a, v in cuenta.items()}


def triangular(
    perfil: dict[str, Any],
    afinidades: dict[str, dict[str, float]],
    arquetipos: dict[str, Any],
) -> list[dict[str, str]]:
    """Compara el arquetipo declarado en el test con el que revelan los módulos.

    El test mide lo que la persona CREE que es. Los módulos miden lo que está
    dispuesta a HACER. Cuando no coinciden, ahí está el trabajo real. Y cuando
    el módulo no apunta a ningún sitio, eso también se dice: callarse convertía
    la dilución en silencio.
    """
    hallazgos: list[dict[str, str]] = []
    primario = perfil["primario"]

    for nombre_modulo, afinidad in afinidades.items():
        if not afinidad:
            continue
        lider = max(afinidad, key=afinidad.get)
        if afinidad[lider] < 20:
            hallazgos.append(
                {
                    "tipo": "sin_lider_de_modulo",
                    "modulo": nombre_modulo,
                    "titulo": f"Tus decisiones de {nombre_modulo} no apuntan a ningún sitio",
                    "texto": (
                        f"Ninguna línea destaca en {nombre_modulo}: has repartido. "
                        f"Repartir es la forma educada de no elegir, y por fuera se "
                        f"ve igual que no tener criterio. Vuelve y quédate con menos "
                        f"cosas."
                    ),
                }
            )
            continue
        if lider == primario:
            continue
        hallazgos.append(
            {
                "tipo": "desajuste",
                "modulo": nombre_modulo,
                "titulo": f"Tu {nombre_modulo} no habla como {arquetipos[primario]['nombre']}",
                "texto": (
                    f"El test te sitúa en {arquetipos[primario]['nombre']}, pero "
                    f"tus decisiones de {nombre_modulo} apuntan a "
                    f"{arquetipos[lider]['nombre']}. O ajustas las decisiones al "
                    f"arquetipo, o reconoces que tu arquetipo real es otro. "
                    f"Sostener las dos cosas a la vez es lo que hace que una "
                    f"marca no acabe de cuajar."
                ),
            }
        )
    return hallazgos


# ------------------------------------------------------ calidad de textos

def _tiene_nombre_propio(texto: str) -> bool:
    """Un nombre propio o una cita literal. Con «las agencias grandes» no vale:
    el enemigo de COM-PA-3 tiene que tener nombre o no es un enemigo."""
    if re.search(r"[«\"“'][^»\"”']{3,}[»\"”']", texto):
        return True
    for frase in re.split(r"[.!?\n]+", texto):
        tokens = [t.strip("«»\"'()[],;:.¿?¡!") for t in frase.split()]
        tokens = [t for t in tokens if t]
        for i, token in enumerate(tokens):
            if i > 0 and len(token) > 1 and token[:1].isupper():
                return True
    return False


def _texto_es_pobre(
    pregunta_id: str,
    texto: Any,
    pregunta: dict[str, Any] | None,
    lexico: dict[str, Any] | None,
) -> tuple[bool, list[str]]:
    """¿Esta respuesta escrita dice algo que no pudiera decir cualquiera?

    Devuelve (es_pobre, motivos). El léxico es una lista negra, no un juez: no
    detecta el relleno bien escrito, y por eso vive en JSON y se amplía leyendo
    respuestas reales. Lo que sí atrapa es el 90 % de las huidas: «no sé», la
    muletilla de LinkedIn, el ejemplo copiado y el mínimo sin cumplir.
    """
    lexico = lexico if isinstance(lexico, dict) else {}
    pregunta = pregunta if isinstance(pregunta, dict) else {}
    minimos = (lexico.get("minimos") or {}).get(pregunta_id, {})

    crudo = _texto_de(texto)
    if not crudo:
        return True, ["vacio"]

    norm = _norm(crudo)

    # Los atajos de COM-PO-4 son respuestas legítimas y cortas a propósito: la
    # pregunta ofrece cuatro botones y castigarlos sería una trampa.
    if norm in {_norm(a) for a in minimos.get("atajos_validos", [])}:
        return False, []

    motivos: list[str] = []
    palabras = norm.split()

    min_chars = int(minimos.get("min_chars", pregunta.get("min_chars", 0) or 0))
    if len(crudo) < min_chars:
        motivos.append("corto")
    elif minimos.get("min_palabras") and len(palabras) < int(minimos["min_palabras"]):
        motivos.append("corto")
    elif minimos.get("min_lineas_utiles"):
        utiles = [ln for ln in crudo.splitlines() if len(ln.strip()) >= 15]
        if len(utiles) < int(minimos["min_lineas_utiles"]):
            motivos.append("corto")

    for frase in lexico.get("frases_vacias", []):
        f = _norm(frase)
        if not f:
            continue
        if norm == f:
            motivos.append("vacio")
            break
        if f in norm and len(norm.replace(f, " ").strip()) < 15:
            motivos.append("vacio")
            break

    for muletilla in lexico.get("muletillas_de_relleno", []):
        m = _norm(muletilla)
        if m and m in norm:
            if minimos.get("prohibe_muletillas") and norm == m:
                motivos.append("adjetivo_de_catalogo")
            if len(norm.replace(m, " ").strip()) < max(1, min_chars // 2):
                motivos.append("muletilla")
            break

    if pregunta_id in ("COM-PA-3", "COM-PA-3b"):
        for topico in lexico.get("enemigos_topico", []):
            t = _norm(topico)
            if t and t in norm:
                motivos.append("topico")
                break

    placeholder = pregunta.get("placeholder")
    if placeholder:
        tope = float(lexico.get("similitud_placeholder_max", 0.6))
        parecido = difflib.SequenceMatcher(None, norm, _norm(placeholder)).ratio()
        if parecido > tope:
            motivos.append("copia_el_ejemplo")

    if minimos.get("min_digitos") and not any(c.isdigit() for c in crudo):
        motivos.append("sin_cifra")

    if minimos.get("exige_nombre_propio") and not _tiene_nombre_propio(crudo):
        motivos.append("sin_nombre")

    if minimos.get("exige_comillas") and not re.search(r"[«»\"“”']", crudo):
        motivos.append("sin_comillas")

    if minimos.get("min_nombres"):
        # Dos nombres separados por coma, «y» o salto de línea. Es la comprobación
        # más floja del fichero y se queda así: pedir más es pedir formato.
        trozos = [t for t in re.split(r"[,\n]| y ", crudo) if len(t.strip()) >= 3]
        if len(trozos) < int(minimos["min_nombres"]):
            motivos.append("sin_nombre")

    for parte in minimos.get("plantilla", []):
        if _norm(parte) not in norm:
            motivos.append("plantilla_incompleta")
            break

    patron = minimos.get("exige_patron")
    if patron and not re.search(patron, crudo):
        motivos.append("sin_patron")

    if minimos.get("min_frases"):
        frases = [f for f in re.split(r"[.!?]+", crudo) if len(f.strip()) >= 10]
        if len(frases) < int(minimos["min_frases"]):
            motivos.append("frases_insuficientes")

    # Sin duplicados y en orden estable, que estos motivos se imprimen.
    vistos: list[str] = []
    for m in motivos:
        if m not in vistos:
            vistos.append(m)
    return bool(vistos), vistos


def _min_chars_no_copio(pregunta: dict[str, Any], lexico: dict[str, Any] | None) -> int:
    minimos = ((lexico or {}).get("minimos") or {}).get(f"{pregunta['id']}.no_copio", {})
    if minimos.get("min_chars"):
        return int(minimos["min_chars"])
    return int((pregunta.get("no_copio") or {}).get("min_chars", 0) or 0)


# ------------------------------------------------------------- tibieza

def _pregunta_es_tibia(
    pregunta: dict[str, Any],
    valor: Any,
    lexico: dict[str, Any] | None = None,
) -> tuple[bool, bool, str]:
    """(es_tibia, cuenta_para_el_total, motivo) de una respuesta de módulo.

    La versión anterior devolvía (False, False) para toda `unica`/`multiple` sin
    ninguna opción `evasiva`, así que 39 de las 41 preguntas de opción no
    entraban ni en el numerador ni en el denominador: el máximo era 77 y el 62 %
    eran los ítems del test. Ahora cuenta todo lo que se puede contestar, y la
    tibieza tiene cuatro formas distintas: el centro, la opción-escape, la
    dilución (marcarlo todo) y el texto que no dice nada.
    """
    tipo = pregunta.get("tipo")

    if tipo == "likert5":
        v = _entero(valor)
        return (v == LIKERT_TIBIO), True, "centro_likert"

    if tipo == "bipolar":
        v, centro, tocado = _valor_bipolar(pregunta, valor)
        if v is None:
            return False, False, ""
        if v == centro and tocado is False:
            # Solo se perdona el centro si el cliente declara que no se tocó.
            # Elegir a mano el punto muerto de una escala de siete SÍ es tibieza:
            # es la respuesta que no dice nada, y es justo lo que se persigue.
            return False, False, "bipolar_sin_tocar"
        return (v == centro), True, "centro_bipolar"

    if tipo == "unica":
        evasivas = {o["valor"] for o in pregunta.get("opciones", []) if o.get("evasiva")}
        return (valor in evasivas), True, "opcion_escape"

    if tipo == "multiple":
        evasivas = {o["valor"] for o in pregunta.get("opciones", []) if o.get("evasiva")}
        elegidos = _lista(valor)
        minimo = int(pregunta.get("min", 1) or 1)
        maximo = pregunta.get("max")
        if elegidos and evasivas and all(v in evasivas for v in elegidos):
            return True, True, "opcion_escape"
        if len(elegidos) < minimo:
            return True, True, "foco_cero"
        if maximo and len(elegidos) >= int(maximo):
            # Marcar 4 de 4 no es elegir cuatro cosas: es no elegir.
            return True, True, "dilucion"
        return False, True, ""

    if tipo == "ranking":
        exactamente = int(pregunta.get("exactamente", 3) or 3)
        return (len(_lista(valor)) != exactamente), True, "ranking_incompleto"

    if tipo == "reparto100":
        if not isinstance(valor, dict) or not valor:
            return True, True, "sin_dominante"
        puntos = [p for p in (_num(v) or 0.0 for v in valor.values())]
        con_puntos = [p for p in puntos if p > 0]
        if not con_puntos or max(con_puntos) < float(pregunta.get("min_dominante", 0) or 0):
            return True, True, "sin_dominante"
        if len(con_puntos) > int(pregunta.get("max_con_puntos", len(con_puntos))):
            return True, True, "dilucion"
        return False, True, ""

    if tipo == "duelo":
        if not isinstance(valor, dict) or not valor.get("elegido"):
            return True, True, "sin_elegir"
        texto = _texto_de(valor.get("no_copio"))
        if len(texto) < _min_chars_no_copio(pregunta, lexico):
            return True, True, "texto_pobre"
        pobre, _motivos = _texto_es_pobre(
            f"{pregunta['id']}.no_copio", texto, {}, lexico
        )
        return pobre, True, "texto_pobre"

    if tipo in ("texto", "texto_largo"):
        obligatorias = set((lexico or {}).get("obligatorias_para_el_muro", []))
        if pregunta["id"] not in obligatorias:
            # Los textos opcionales (VIS-LM-5, ACC-CA-3) no son terreno de
            # tibieza: no contestar dónde está tu límite no es esconderse.
            return False, False, ""
        pobre, motivos = _texto_es_pobre(pregunta["id"], valor, pregunta, lexico)
        return pobre, True, ("texto_pobre" if pobre else "")

    return False, False, ""


def indice_tibieza(
    respuestas: dict[str, Any],
    test: dict[str, Any],
    modulos: dict[str, dict[str, Any]],
    lexico: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mide cuánto se ha escondido el usuario, POR SECCIÓN.

    Un único porcentaje global era un saco donde el test se llevaba el 62 % del
    denominador: contestar 3 en los 48 ítems apenas movía la aguja. Ahora cada
    sección tiene su umbral y dispara sola, el test más duro que los módulos
    (15 % frente a 22 %) porque es donde más barato sale diluirse.

    `valor_previo` y `texto_previo` viajan a propósito: el muro tiene que poder
    enseñar lo que se contestó antes y comprobar que la respuesta nueva no es la
    misma. Y cada entrada dice si puede volver al muro (`al_muro`): los textos de
    `nunca_al_muro` se validan al pasar de pantalla y no se reofrecen, porque
    «escribe otra vez tu opinión impopular, más impopular» produce material
    falso, que es peor que material tibio.
    """
    lexico = lexico if isinstance(lexico, dict) else {}
    nunca = set(lexico.get("nunca_al_muro", []))

    tibias: list[dict[str, Any]] = []
    textos_pobres: list[dict[str, Any]] = []
    por_seccion: dict[str, dict[str, Any]] = {}

    # 1. Test de arquetipos: Likert 1-5, el 3 es tibieza. Los controles fuera:
    # tienen respuesta fija y se validan en validar_atencion.
    control_ids = {c["id"] for c in test.get("control", []) or []}
    resp_arq = _seccion(respuestas, "arquetipos")
    tibias_test = 0
    total_test = 0
    for item in test.get("items", []) or []:
        if item["id"] in control_ids:
            continue
        valor = resp_arq.get(item["id"])
        if valor is None or valor == "":
            continue
        total_test += 1
        if _entero(valor) == LIKERT_TIBIO:
            tibias_test += 1
            tibias.append(
                {
                    "seccion": "arquetipos",
                    "id": item["id"],
                    "motivo": "centro_likert",
                    "valor_previo": valor,
                    "al_muro": True,
                }
            )
    por_seccion["arquetipos"] = {
        "indice": round(100.0 * tibias_test / total_test, 1) if total_test else 0.0,
        "tibias": tibias_test,
        "total": total_test,
        "umbral": UMBRAL_TIBIEZA_TEST,
        "dispara": False,
    }
    por_seccion["arquetipos"]["dispara"] = (
        bool(total_test) and por_seccion["arquetipos"]["indice"] > UMBRAL_TIBIEZA_TEST
    )

    # 2. Los tres módulos, con todos los tipos.
    for nombre in SECCIONES_MODULO:
        resp_mod = _seccion(respuestas, nombre)
        modulo = (modulos or {}).get(nombre, {}) or {}
        tibias_mod = 0
        total_mod = 0
        for bloque in modulo.get("bloques", []) or []:
            for pregunta in bloque.get("preguntas", []) or []:
                valor = resp_mod.get(pregunta["id"])
                if valor is None or valor == "" or valor == [] or valor == {}:
                    continue
                escurridizo, cuenta, motivo = _pregunta_es_tibia(pregunta, valor, lexico)
                if not cuenta:
                    continue
                total_mod += 1
                if not escurridizo:
                    continue
                tibias_mod += 1
                al_muro = pregunta["id"] not in nunca
                entrada = {
                    "seccion": nombre,
                    "id": pregunta["id"],
                    "motivo": motivo,
                    "valor_previo": valor,
                    "al_muro": al_muro,
                }
                tibias.append(entrada)
                if pregunta["tipo"] in ("texto", "texto_largo"):
                    _pobre, motivos = _texto_es_pobre(
                        pregunta["id"], valor, pregunta, lexico
                    )
                    textos_pobres.append(
                        {
                            "seccion": nombre,
                            "id": pregunta["id"],
                            "motivos": motivos,
                            "texto_previo": _texto_de(valor),
                            "al_muro": al_muro,
                        }
                    )
        indice_mod = round(100.0 * tibias_mod / total_mod, 1) if total_mod else 0.0
        por_seccion[nombre] = {
            "indice": indice_mod,
            "tibias": tibias_mod,
            "total": total_mod,
            "umbral": UMBRAL_TIBIEZA_MODULO,
            "dispara": bool(total_mod) and indice_mod > UMBRAL_TIBIEZA_MODULO,
        }

    total = sum(s["total"] for s in por_seccion.values())
    n_tibias = sum(s["tibias"] for s in por_seccion.values())
    indice = round(100.0 * n_tibias / total, 1) if total else 0.0

    motivos: list[str] = [k for k, s in por_seccion.items() if s["dispara"]]
    if total and indice > UMBRAL_TIBIEZA_GLOBAL:
        motivos.append("global")
    if len(textos_pobres) >= MIN_TEXTOS_POBRES:
        motivos.append("texto_pobre")

    return {
        "indice": indice,
        "por_seccion": por_seccion,
        "tibias": n_tibias,
        "total": total,
        "umbral_global": UMBRAL_TIBIEZA_GLOBAL,
        "preguntas_tibias": tibias,
        "textos_pobres": textos_pobres,
        "motivos": motivos,
    }


def calidad_textos(
    respuestas: dict[str, Any],
    modulos: dict[str, dict[str, Any]],
    lexico: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calidad de las respuestas abiertas: las 19 obligatorias más los tres
    «lo que NO le copiaría» de los duelos.

    Es la única parte del informe que el programa no puede rellenar. Si aquí no
    hay material, lo que sale es el informe de la competencia con otro nombre.
    """
    lexico = lexico if isinstance(lexico, dict) else {}
    indice_p = indice_preguntas(modulos)
    obligatorias = list(lexico.get("obligatorias_para_el_muro", []))

    evaluables: list[tuple[str, str, Any, dict[str, Any]]] = []  # (id, seccion, texto, pregunta)
    for pid in obligatorias:
        ficha = indice_p.get(pid)
        if not ficha:
            continue
        seccion = ficha["seccion"]
        valor = _seccion(respuestas, seccion).get(pid)
        evaluables.append((pid, seccion, valor, ficha["pregunta"]))

    # Los duelos: el texto vive dentro del dict de la respuesta.
    for ficha in indice_p.values():
        pregunta = ficha["pregunta"]
        if pregunta.get("tipo") != "duelo":
            continue
        valor = _seccion(respuestas, ficha["seccion"]).get(pregunta["id"])
        texto = valor.get("no_copio") if isinstance(valor, dict) else None
        evaluables.append(
            (f"{pregunta['id']}.no_copio", ficha["seccion"], texto, {})
        )

    n_pedidas = len(evaluables)
    suma = 0.0
    evaluadas = 0
    pobres: list[dict[str, Any]] = []
    sin_contestar: list[str] = []
    copiados = 0

    for pid, seccion, valor, pregunta in evaluables:
        texto = _texto_de(valor)
        if not texto:
            sin_contestar.append(pid)
            continue
        evaluadas += 1
        pobre, motivos = _texto_es_pobre(pid, texto, pregunta, lexico)
        if not pobre:
            suma += 1.0
        elif motivos in (["muletilla"], ["copia_el_ejemplo"]):
            # Media respuesta: hay algo escrito, pero es de catálogo.
            suma += 0.5
        if "copia_el_ejemplo" in motivos:
            copiados += 1
        if pobre:
            pobres.append(
                {
                    "id": pid,
                    "seccion": seccion,
                    "motivos": motivos,
                    "texto_previo": texto,
                    "al_muro": pid not in set(lexico.get("nunca_al_muro", [])),
                }
            )

    avisos: list[dict[str, str]] = []
    if copiados >= 2:
        avisos.append(
            {
                "tipo": "texto_copiado",
                "titulo": "Has copiado el ejemplo",
                "texto": (
                    "El ejemplo es mío, la marca es tuya. Escríbelo otra vez con "
                    "algo que solo puedas decir tú."
                ),
            }
        )

    if not evaluadas:
        return {
            "indice": None,
            "nivel": "sin datos",
            "lectura": (
                f"No has escrito ninguna de las {n_pedidas} respuestas abiertas. "
                f"Son la única parte del informe que no puede rellenar el programa."
            ),
            "pedidas": n_pedidas,
            "evaluadas": 0,
            "pobres": pobres,
            "sin_contestar": sin_contestar,
            "avisos": avisos,
        }

    indice = round(100.0 * suma / evaluadas, 1)
    if indice < 40:
        nivel = "sin material"
        lectura = (
            f"De las {n_pedidas} respuestas escritas que te hemos pedido, "
            f"{len(pobres)} no dicen nada que no pudiera decir cualquiera de tu "
            f"sector. Esta parte no la puede rellenar el programa: si no la "
            f"escribes tú, tu informe va a ser el de tu competencia con otro nombre."
        )
    elif indice < 70:
        nivel = "a medias"
        lectura = (
            "Tienes material en unas cuantas y en otras te has escapado con una "
            "frase de manual. Las que se han quedado en nada están marcadas: son "
            "exactamente las que harían que alguien te reconociera sin ver tu nombre."
        )
    else:
        nivel = "con material propio"
        lectura = (
            "Aquí hay cosas que solo puedes decir tú. Esta es la parte del informe "
            "que ninguna otra persona podría haber generado, y es la que hay que "
            "repetir hasta el aburrimiento."
        )

    return {
        "indice": indice,
        "nivel": nivel,
        "lectura": lectura,
        "pedidas": n_pedidas,
        "evaluadas": evaluadas,
        "pobres": pobres,
        "sin_contestar": sin_contestar,
        "avisos": avisos,
    }


# ------------------------------------------------------ atención y muro

def validar_atencion(respuestas: dict[str, Any], test: dict[str, Any]) -> dict[str, Any]:
    """Comprueba los ítems de control. Antes no los comprobaba NADIE.

    `valor_esperado` estaba escrito en el JSON desde el primer día y no lo leía
    ninguna línea del proyecto: el filtro que parecía hacerlo cruzaba
    `test['items']` con ids que viven en `test['control']`, otro array, así que
    nunca casaba con nada. Un cuestionario contestado al azar producía un
    informe con la misma pinta que uno honesto.
    """
    resp = _seccion(respuestas, "arquetipos")
    fallados: list[str] = []
    sin_datos: list[str] = []
    controles = test.get("control", []) or []

    for control in controles:
        cid = control["id"]
        valor = _entero(resp.get(cid))
        if valor is None:
            sin_datos.append(cid)
            continue
        tipo = control.get("tipo_control", "valor_fijo")
        if tipo == "consistencia":
            # Dos frases que dicen lo contrario: sus valores tienen que sumar
            # aproximadamente lo mismo. Se distingue por la clave, no por el id.
            pareja = _entero(resp.get(control.get("pareja")))
            if pareja is None:
                sin_datos.append(cid)
                continue
            suma = float(control.get("suma_esperada", 6))
            tolerancia = float(control.get("tolerancia", 2))
            if abs(valor + pareja - suma) > tolerancia:
                fallados.append(cid)
        else:
            # CTRL-1 y CTRL-2 se reconocen por llevar `valor_esperado`, no por su
            # id: si algún día se añade un control sin ese campo, se ignora en vez
            # de suspender a todo el mundo.
            esperado = _entero(control.get("valor_esperado"))
            if esperado is None:
                sin_datos.append(cid)
            elif valor != esperado:
                fallados.append(cid)

    n = len(fallados)
    aviso: dict[str, str] | None = None
    if n == 0:
        estado = "ok"
    elif n == 1:
        estado = "dudoso"
        aviso = {
            "tipo": "atencion",
            "titulo": "Una de las preguntas trampa no cuadra",
            "texto": (
                "Has fallado una de las preguntas de control. Puede ser un "
                "despiste; el perfil sigue siendo utilizable, pero tómalo como "
                "una hipótesis y no como un diagnóstico."
            ),
        }
    else:
        estado = "sin_validez"
        aviso = {
            "tipo": "atencion",
            "titulo": "Este informe no vale nada",
            "texto": (
                f"Has fallado {n} de las {len(controles)} preguntas de control. O "
                f"no leíste las frases, o contestaste al azar. No hay perfil que "
                f"sacar de ahí: hay que repetir el test entero. No es un castigo, "
                f"es que los números que saldrían serían inventados."
            ),
        }

    return {
        "de": len(controles),
        "pasados": len(controles) - n - len(sin_datos),
        "fallados": fallados,
        "sin_datos": sin_datos,
        "estado": estado,
        "aviso": aviso,
    }


def preguntas_planas(
    respuestas: dict[str, Any], test: dict[str, Any], n_max: int = 16
) -> dict[str, Any]:
    """Los ítems del test donde la respuesta empata con la propia media.

    Existe porque el muro era matemáticamente insatisfacible: `veredicto_definicion`
    dispara también por perfil plano, pero el frontend solo sabía reconstruir
    pasos desde `preguntas_tibias`, así que un perfil plano con 0 tibias veía
    «Te devuelvo esas 0» y un pasillo sin salida.

    Devuelve {'preguntas', 'bloques_fc_pendientes', 'media_global'}: la spec
    hablaba de una lista con una «clave hermana», que no existe; un dict con las
    dos cosas es lo que main.py puede mandar tal cual al cliente.
    """
    resp = _seccion(respuestas, "arquetipos")
    items = {it["id"]: it for it in test.get("items", []) or []}

    valores: dict[str, float] = {}
    for item_id, valor in resp.items():
        item = items.get(item_id)
        v = _num(valor)
        if item is None or v is None:
            continue
        valores[item_id] = (6 - v) if item.get("inverso") else v

    salida: list[dict[str, Any]] = []
    media = None
    if valores:
        media = statistics.fmean(valores.values())
        # Los cuatro arquetipos de cabeza: es donde el empate hace más daño,
        # porque son los que van a salir en la portada.
        brutos: dict[str, list[float]] = {}
        for item_id, v in valores.items():
            brutos.setdefault(items[item_id]["arquetipo"], []).append(v)
        cabeza = sorted(
            brutos, key=lambda a: (statistics.fmean(brutos[a]), a), reverse=True
        )[:4]
        candidatos = [
            (item_id, v)
            for item_id, v in valores.items()
            if items[item_id]["arquetipo"] in cabeza and abs(v - media) < 0.6
        ]
        candidatos.sort(key=lambda par: (abs(par[1] - media), par[0]))
        for item_id, _v in candidatos[:n_max]:
            salida.append(
                {
                    "seccion": "arquetipos",
                    "id": item_id,
                    "motivo": "empata_con_tu_media",
                    "valor_previo": resp.get(item_id),
                    "al_muro": True,
                }
            )

    # Si el planismo viene de un test contestado sin ningún 3, la única forma de
    # mover sigma es la elección forzada.
    pendientes = [
        bloque["id"]
        for bloque in test.get("eleccion_forzada", []) or []
        if resp.get(bloque["id"]) in (None, "")
    ]

    return {
        "preguntas": salida,
        "bloques_fc_pendientes": pendientes,
        "media_global": round(media, 2) if media is not None else None,
    }


def veredicto_definicion(
    tibieza: dict[str, Any],
    perfil: dict[str, Any],
    atencion: dict[str, Any] | None = None,
    textos: dict[str, Any] | None = None,
    ronda: int = 0,
) -> dict[str, Any]:
    """¿Hay que parar al usuario y hacerle repetir, o ya puede pasar?

    Cuatro disparadores por orden de gravedad: informe sin validez (controles
    fallados), textos que no dicen nada, tibieza por sección y perfil plano.
    `que_devolver` dice QUÉ hay que repreguntar, porque no todo se arregla
    devolviendo las tibias: con un perfil plano no hay tibias que devolver.

    `ronda` es cuántas veces ya se le ha hecho repetir, y tiene que venir del
    servidor. Fijarla a mano en MAX_RONDAS_TIBIEZA hacía el estado 'tibio'
    estructuralmente inalcanzable y la portada acusaba de esconderse en el punto
    medio a gente con 0 % de tibieza y perfil plano: dos cosas distintas con el
    mismo texto.
    """
    # Compatibilidad con la llamada vieja veredicto_definicion(tibieza, perfil, ronda),
    # que sigue viva en main.py hasta que se reescriba esa capa.
    if isinstance(atencion, (int, float)) and not isinstance(atencion, bool):
        ronda, atencion = int(atencion), None

    atencion = atencion if isinstance(atencion, dict) else {}
    textos = textos if isinstance(textos, dict) else {}
    pobres = textos.get("pobres", [])

    motivos: list[str] = []
    if atencion.get("estado") == "sin_validez":
        motivos.append("sin_validez")
    if len(pobres) >= MIN_TEXTOS_POBRES:
        motivos.append("texto_pobre")
    if any(s.get("dispara") for s in (tibieza.get("por_seccion") or {}).values()) or (
        tibieza.get("total") and tibieza.get("indice", 0.0) > UMBRAL_TIBIEZA_GLOBAL
    ):
        motivos.append("tibieza")
    if perfil.get("coherencia") == "plano":
        motivos.append("plano")

    if not motivos:
        return {
            "estado": "definido",
            "repetir": False,
            "ronda": ronda,
            "motivo": None,
            "motivos": [],
            "que_devolver": None,
            "texto": "",
        }

    motivo = motivos[0]
    que_devolver = {
        "sin_validez": "test_completo",
        "texto_pobre": "textos",
        "tibieza": "tibias",
        "plano": "planas",
    }[motivo]

    # Sin validez no admite «ya has repetido bastante»: un informe inventado no
    # mejora por insistir, así que repetir es True siempre.
    if motivo == "sin_validez":
        estado, repetir = "sin_validez", True
    elif motivo == "plano":
        estado, repetir = "plano_sin_tibieza", ronda < MAX_RONDAS_TIBIEZA
    elif ronda < MAX_RONDAS_TIBIEZA:
        estado, repetir = "tibio", True
    else:
        estado, repetir = "tibio_persistente", False

    textos_portada = {
        "sin_validez": (
            "Has fallado las preguntas de control. Lo que salga de aquí no "
            "describe tu marca: describe cómo rellenas formularios."
        ),
        "texto_pobre": (
            "Las respuestas escritas son la única parte que no puede rellenar el "
            "programa, y las has dejado en frases de manual."
        ),
        "tibieza": (
            "Contestaste demasiado por el punto medio. Una marca no se construye "
            "desde el «a veces»."
        ),
        "plano": (
            "No eres tibio: es que has dicho lo mismo de todo. Doce cincuentas no "
            "son una marca, y eso es peor que esconderse en el centro, porque "
            "desde fuera no se distingue de no tener opinión."
        ),
    }

    return {
        "estado": estado,
        "repetir": repetir,
        "ronda": ronda,
        "motivo": motivo,
        "motivos": motivos,
        "que_devolver": que_devolver,
        "texto": textos_portada[motivo],
    }


# ---------------------------------------------------------------- índices

def indice_distincion(
    respuestas: dict[str, Any],
    modulos: dict[str, dict[str, Any]],
    categoria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cuánto te separas de tu categoría, en lo que tu categoría hace.

    Mide el sector tal como lo describe la persona, no el sector real: quien se
    equivoque al contestar COM-CX-3 sacará un 100 en color siendo un clon. Por
    eso el retorno trae siempre los componentes con las etiquetas elegidas: el
    índice no se puede enseñar sin enseñar sobre qué se ha calculado.

    No entra ningún ACC-DI-*: distinción no es audacia. Un perfil prudente puede
    sacar 100 con un color raro y un formato fijo sin salir en vídeo una sola vez.
    """
    categoria = categoria if isinstance(categoria, dict) else {}
    indice_p = indice_preguntas(modulos)
    com = _seccion(respuestas, "comunicacion")
    vis = _seccion(respuestas, "visual")
    acc = _seccion(respuestas, "acciones")

    def etiqueta(pid: str, valor: Any) -> str:
        ficha = indice_p.get(pid)
        if not ficha or valor in (None, ""):
            return str(valor) if valor not in (None, "") else ""
        for opcion in ficha["pregunta"].get("opciones", []):
            if opcion["valor"] == valor:
                return opcion.get("etiqueta", str(valor))
        return str(valor)

    componentes: dict[str, dict[str, Any]] = {}

    # d_color (30): el color que llevas frente a los que están ocupados.
    color = vis.get("VIS-CR-3")
    ocupados = _lista(com.get("COM-CX-3"))
    if color and ocupados:
        if color in ocupados:
            d = 0.0
        elif color == "negro_blanco":
            # Blanco y negro no es esconderse (colores.json lo trata como color
            # declarado), pero tampoco es un color propio: se queda a medio gas.
            d = 60.0
        else:
            d = 100.0
        componentes["color"] = {
            "peso": 30,
            "valor": d,
            "detalle": (
                f"Tú: {etiqueta('VIS-CR-3', color)}. En tu sector: "
                f"{', '.join(etiqueta('COM-CX-3', o) for o in ocupados)}."
            ),
        }

    # d_tono (20): las bipolares de tono frente al tono de la categoría.
    patron = (categoria.get("tono_categoria") or {}).get(com.get("COM-CX-5"))
    if patron:
        aciertos = 0
        evaluadas = 0
        for pid, lado_categoria in patron.items():
            ficha = indice_p.get(pid)
            if not ficha:
                continue
            v, centro, _tocado = _valor_bipolar(ficha["pregunta"], com.get(pid))
            if v is None or v == centro:
                # Las que están en el centro salen del denominador: ya las
                # castiga la tibieza y contarlas aquí sería penalizar dos veces.
                continue
            evaluadas += 1
            lado_usuario = "izq" if v < centro else "der"
            if lado_usuario != lado_categoria:
                aciertos += 1
        if evaluadas:
            componentes["tono"] = {
                "peso": 20,
                "valor": round(100.0 * aciertos / evaluadas, 1),
                "detalle": (
                    f"Tu sector suena «{etiqueta('COM-CX-5', com.get('COM-CX-5'))}»: "
                    f"te separas de él en {aciertos} de {evaluadas} ejes de tono."
                ),
            }

    # d_formato (20): tu ancla frente al formato de todos.
    ancla = acc.get("ACC-CT-2")
    formato_todos = com.get("COM-CX-4")
    if ancla and formato_todos:
        d = 0.0 if ancla == formato_todos else 100.0
        componentes["formato"] = {
            "peso": 20,
            "valor": d,
            "detalle": (
                f"Tú: {etiqueta('ACC-CT-2', ancla)}. Tu sector: "
                f"{etiqueta('COM-CX-4', formato_todos)}."
            ),
        }

    # d_sello (20): sello visual y ritual. El único componente que se podía
    # calcular antes de que existiera el bloque de categoría.
    sellos = [s for s in _lista(vis.get("VIS-RO-5")) if s != "ninguna_firma"]
    rituales = _lista(acc.get("ACC-RI-1"))
    if vis.get("VIS-RO-5") is not None or acc.get("ACC-RI-1") is not None:
        if not sellos and not rituales:
            d = 0.0
        elif sellos and rituales:
            d = 100.0
        else:
            d = 50.0
        componentes["sello"] = {
            "peso": 20,
            "valor": d,
            "detalle": (
                f"Sello visual: {', '.join(etiqueta('VIS-RO-5', s) for s in sellos) or 'ninguno'}. "
                f"Ritual: {', '.join(etiqueta('ACC-RI-1', r) for r in rituales) or 'ninguno'}."
            ),
        }

    # d_diferir (10): «que nadie se fije en mí» / «que me miren». No hay ítem
    # propio y no se añade uno: el presupuesto de preguntas está agotado.
    ficha_au1 = indice_p.get("VIS-AU-1")
    if ficha_au1:
        v, _centro, _tocado = _valor_bipolar(ficha_au1["pregunta"], vis.get("VIS-AU-1"))
        escala = float(ficha_au1["pregunta"].get("escala", BIPOLAR_ESCALA))
        if v is not None and escala > 1:
            componentes["diferir"] = {
                "peso": 10,
                "valor": round(100.0 * (v - 1) / (escala - 1), 1),
                "detalle": f"VIS-AU-1: {v} de {int(escala)}.",
            }

    pesos = sum(c["peso"] for c in componentes.values())
    indice = (
        round(sum(c["peso"] * c["valor"] for c in componentes.values()) / pesos, 1)
        if pesos
        else None
    )

    if indice is None:
        nivel, lectura = "sin datos", ""
    elif indice < 35:
        nivel = "clon"
        lectura = (
            "Tu marca es la marca de tu sector. Usas el color de todos, el tono de "
            "todos y el formato de todos. No te van a olvidar: no te van a llegar a "
            "ver. Cambia UNA de las tres cosas, y cámbiala del todo."
        )
    elif indice < 65:
        nivel = "reconocible con esfuerzo"
        lectura = (
            "Te distingues en algo, pero no lo bastante para que alguien te describa "
            "sin decir tu nombre. Coge el eje donde ya vas por delante y exagéralo "
            "hasta que resulte incómodo."
        )
    else:
        nivel = "inconfundible"
        lectura = (
            "Vas por otro sitio que tu categoría. Ahora el trabajo es no cambiarlo: "
            "la distinción se pierde por aburrimiento del dueño, no por el mercado."
        )

    avisos: list[dict[str, str]] = []
    d_color = componentes.get("color", {}).get("valor")
    d_formato = componentes.get("formato", {}).get("valor")
    d_tono = componentes.get("tono", {}).get("valor", 100.0)
    if d_color == 0 and d_formato == 0 and d_tono <= 33:
        # El aviso cita las etiquetas concretas y los dos nombres de COM-CX-6: sin
        # los nombres es una acusación, con ellos es algo que se puede ir a mirar.
        confundido = _dos_nombres(com.get("COM-CX-6"))
        cierre = (
            f" Los dos con los que te confunden son {confundido[0]} y {confundido[1]}: "
            f"tu informe no puede arreglar eso, solo tú."
            if confundido
            else " Tu informe no puede arreglar eso, solo tú."
        )
        color_sector = etiqueta("COM-CX-3", ocupados[0]) if ocupados else "ese color"
        avisos.append(
            {
                "tipo": "clon_de_categoria",
                "titulo": "Eres tu categoría con otro nombre",
                "texto": (
                    f"Has dicho que en tu sector todos usan {color_sector} y todos "
                    f"publican {etiqueta('COM-CX-4', formato_todos)}, y has elegido "
                    f"exactamente eso.{cierre}"
                ),
            }
        )

    return {
        "indice": indice,
        "nivel": nivel,
        "lectura": lectura,
        "componentes": componentes,
        "avisos": avisos,
    }


def _dos_nombres(texto: Any) -> tuple[str, str] | None:
    """Los dos nombres de COM-CX-6, para poder citarlos en el aviso de clon."""
    crudo = _texto_de(texto)
    if not crudo:
        return None
    trozos = [t.strip(" .,;") for t in re.split(r"[,\n]| y ", crudo)]
    trozos = [t for t in trozos if len(t) >= 3]
    if len(trozos) < 2:
        return None
    return trozos[0], trozos[1]


def indice_consistencia(
    respuestas: dict[str, Any], modulos: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Aguante: la probabilidad de que esto siga en pie dentro de un año.

    Una marca es repetición. Todo lo que mide este índice es si la persona ha
    dicho que va a repetir algo, cada cuánto, y si soporta el silencio de los
    primeros meses. Es el único índice que compensa la falta de audacia.
    """
    com = _seccion(respuestas, "comunicacion")
    vis = _seccion(respuestas, "visual")
    acc = _seccion(respuestas, "acciones")

    componentes: dict[str, dict[str, Any]] = {}

    def anotar(clave: str, peso: float, valor: float | None, detalle: str = "") -> None:
        if valor is None:
            return
        componentes[clave] = {
            "peso": peso,
            "valor": round(max(0.0, min(1.0, valor)), 3),
            "detalle": detalle,
        }

    def likert(valor: Any) -> float | None:
        v = _num(valor)
        return None if v is None else (v - 1) / 4.0

    anotar("COM-LI-6", 2.0, likert(com.get("COM-LI-6")), "Repetir sin aburrirse")
    anotar("ACC-HO-3", 2.0, likert(acc.get("ACC-HO-3")), "Aguantar sin respuesta")

    cadencia = com.get("COM-CA-3")
    mapa_cadencia = {
        "diario": 1.0,
        "semanal_3": 0.9,
        "semanal_1": 0.85,
        "quincenal": 0.6,
        "campanas": 0.15,
    }
    anotar("COM-CA-3", 2.0, mapa_cadencia.get(cadencia), f"Cadencia: {cadencia or '—'}")

    rituales = _lista(acc.get("ACC-RI-1"))
    if acc.get("ACC-RI-1") is not None:
        anotar("ACC-RI-1", 1.5, min(len(rituales), 3) / 3.0, f"{len(rituales)} rituales")

    ri2 = _texto_de(acc.get("ACC-RI-2"))
    if acc.get("ACC-RI-2") is not None:
        if re.search(r"(?i)\bcada\b", ri2) and len(ri2) >= 30:
            anotar("ACC-RI-2", 1.5, 1.0, "El ritual tiene periodicidad escrita")
        elif ri2:
            anotar("ACC-RI-2", 1.5, 0.4, "Hay ritual, pero sin «cada»")
        else:
            anotar("ACC-RI-2", 1.5, 0.0, "Sin ritual escrito")

    ri3 = acc.get("ACC-RI-3")
    if ri3 is not None:
        pobre, _m = _texto_es_pobre("ACC-RI-3", ri3, {}, _lexico_de_reserva())
        anotar("ACC-RI-3", 1.0, 0.0 if pobre else 1.0, "El detalle concreto del ritual")

    anotar("VIS-AU-3", 1.0, likert(vis.get("VIS-AU-3")), "Uniforme")
    anotar("VIS-CA-7", 1.0, likert(vis.get("VIS-CA-7")), "Peinado estable")

    mapa_horizonte = {"meses_3": 0.2, "meses_6_12": 0.6, "anios_2_3": 1.0, "largo": 1.0}
    anotar(
        "ACC-HO-2",
        1.0,
        mapa_horizonte.get(acc.get("ACC-HO-2")),
        f"Horizonte: {acc.get('ACC-HO-2') or '—'}",
    )

    pesos = sum(c["peso"] for c in componentes.values())
    indice = (
        round(100.0 * sum(c["peso"] * c["valor"] for c in componentes.values()) / pesos, 1)
        if pesos
        else None
    )

    if indice is None:
        nivel, lectura = "sin datos", ""
    elif indice < 40:
        nivel = "no va a durar"
        lectura = (
            "Has dicho que no piensas repetirte y que no aguantas el silencio. Una "
            "marca es repetición: sin eso esto es una campaña, y las campañas no se "
            "recuerdan."
        )
    elif indice < 70:
        nivel = "sostenible con disciplina"
        lectura = (
            "Te da para durar si te lo montas con calendario y no con ganas. Lo que "
            "se cae siempre es lo que depende del ánimo del día."
        )
    else:
        nivel = "hecho para durar"
        lectura = (
            "Tienes lo más difícil de enseñar: aguante. Con esto compensas cualquier "
            "falta de audacia."
        )

    return {
        "indice": indice,
        "nivel": nivel,
        "lectura": lectura,
        "componentes": componentes,
    }


def _lexico_de_reserva() -> dict[str, Any]:
    """El léxico, si se puede cargar. `indice_consistencia` juzga un texto y no
    recibe el fichero: antes de inventarse un criterio, se lee el de verdad."""
    try:
        from . import contenido as contenido_mod

        return contenido_mod.lexico_evasion()
    except Exception:  # noqa: BLE001 - sin léxico se juzga por longitud y ya
        return {}


def medias_por_dimension(
    respuestas: dict[str, Any], modulos: dict[str, dict[str, Any]]
) -> dict[str, float]:
    """Media 0-100 de cada `dimension` declarada en los módulos.

    27 preguntas traen el campo `dimension` desde que se escribió el contenido y
    no lo leía ni una línea del proyecto. Publica constancia, firma_visual,
    uniforme, exposicion, confrontacion_directa y vulnerabilidad, entre otras:
    son ejes más estables que el arquetipo suelto y no dependen del test.
    """
    acumulado: dict[str, list[float]] = {}
    for pid, ficha in indice_preguntas(modulos).items():
        pregunta = ficha["pregunta"]
        dimension = pregunta.get("dimension")
        if not dimension:
            continue
        valor = _seccion(respuestas, ficha["seccion"]).get(pid)
        if valor is None or valor == "":
            continue
        if pregunta["tipo"] == "likert5":
            v = _num(valor)
            if v is None:
                continue
            acumulado.setdefault(dimension, []).append(100.0 * (v - 1) / 4.0)
        elif pregunta["tipo"] == "bipolar":
            v, _centro, _tocado = _valor_bipolar(pregunta, valor)
            escala = float(pregunta.get("escala", BIPOLAR_ESCALA))
            if v is None or escala <= 1:
                continue
            acumulado.setdefault(dimension, []).append(100.0 * (v - 1) / (escala - 1))

    return {d: round(statistics.fmean(vs), 1) for d, vs in sorted(acumulado.items())}


def _cuenta_activos_fuertes(activos: Any) -> int:
    """El recuento de activos fuertes lo decide app.activos, no este módulo.

    Si llega el dict de `sistema_activos` se usa su clave 'fuertes' tal cual. Si
    llega la lista pelada se replica su regla (fuerza >= 2 y la tipografía no
    cuenta, porque no la ha elegido nadie: viene de la ficha del arquetipo).
    """
    if isinstance(activos, dict):
        if "fuertes" in activos:
            return int(activos["fuertes"] or 0)
        activos = activos.get("activos", [])
    return sum(
        1
        for a in activos or []
        if isinstance(a, dict) and a.get("fuerza", 0) >= 2 and a.get("tipo") != "tipografia"
    )


def indice_invisibilidad(
    perfil: dict[str, Any],
    tibieza: dict[str, Any],
    distincion: dict[str, Any],
    consistencia: dict[str, Any],
    activos: Any,
) -> dict[str, Any]:
    """El riesgo de que no te vean. Es el índice que va a portada.

    El orden de los pesos no es decorativo: distinción y consistencia miden cómo
    se va a VER la marca; sigma y tibieza solo miden cómo se contestó el
    cuestionario. Un informe que ponga por delante lo segundo está evaluando el
    formulario, no la marca.
    """
    perfil = perfil if isinstance(perfil, dict) else {}
    tibieza = tibieza if isinstance(tibieza, dict) else {}
    distincion = distincion if isinstance(distincion, dict) else {}
    consistencia = consistencia if isinstance(consistencia, dict) else {}

    d = distincion.get("indice")
    d = 50.0 if d is None else float(d)
    c = consistencia.get("indice")
    c = 50.0 if c is None else float(c)
    sigma = _num(perfil.get("sigma")) or 0.0
    s = min(100.0, 100.0 * sigma / SIGMA_DEFINIDO)
    t = 100.0 - float(tibieza.get("indice", 0.0) or 0.0)
    n_fuertes = _cuenta_activos_fuertes(activos)
    a = 100.0 * min(n_fuertes, 3) / 3.0

    componentes = {
        "distincion": {"peso": 30, "valor": round(d, 1)},
        "consistencia": {"peso": 25, "valor": round(c, 1)},
        "sigma": {"peso": 20, "valor": round(s, 1)},
        "tibieza": {"peso": 15, "valor": round(t, 1)},
        "activos": {"peso": 10, "valor": round(a, 1), "fuertes": n_fuertes},
    }
    visibilidad = 0.30 * d + 0.25 * c + 0.20 * s + 0.15 * t + 0.10 * a
    indice = round(100.0 - visibilidad, 1)

    salidas = (
        " Las dos salidas que no te obligan a exponerte siguen abiertas: contraste "
        "(un color y un formato que no use nadie de tu sector) y repetición (lo "
        "mismo, el mismo día, durante un año)."
    )

    if indice >= 60:
        nivel = "riesgo alto"
        # Nombramos el sumando que más resta, no el más bajo a secas: lo que
        # importa es dónde se pierde más visibilidad, ponderado.
        peor = max(
            ("distincion", (100.0 - d) * 0.30),
            ("consistencia", (100.0 - c) * 0.25),
            ("activos", (100.0 - a) * 0.10),
            key=lambda par: par[1],
        )[0]
        cabecera = {
            "distincion": (
                "Tu problema no es que no te definas: es que te defines igual que "
                "todos los de tu sector."
            ),
            "consistencia": (
                "Tu problema no es la falta de ideas: es que no vas a repetir "
                "ninguna el tiempo suficiente."
            ),
            "activos": (
                "Tienes opiniones y no tienes con qué te reconozcan: nadie puede "
                "describirte sin decir tu nombre."
            ),
        }[peor]
        lectura = cabecera + salidas
    elif indice >= 35:
        nivel = "riesgo medio"
        lectura = (
            "Se te ve, pero hay que estar mirando. Con un eje llevado al extremo "
            "pasas de «lo he visto en algún sitio» a «esto es tuyo»." + salidas
        )
    else:
        nivel = "riesgo bajo"
        lectura = (
            "Te van a ver. A partir de aquí el riesgo cambia de bando: lo que se "
            "pierde es por cambiar de idea, no por falta de visibilidad."
        )

    return {
        "indice": indice,
        "nivel": nivel,
        "lectura": lectura,
        "visibilidad": round(visibilidad, 1),
        "componentes": componentes,
        "peor": max(
            ("distincion", (100.0 - d) * 0.30),
            ("consistencia", (100.0 - c) * 0.25),
            ("activos", (100.0 - a) * 0.10),
            key=lambda par: par[1],
        )[0],
    }


def indice_audacia(
    respuestas: dict[str, Any], modulo_acciones: dict[str, Any]
) -> dict[str, Any]:
    """Cuánto está dispuesto a exponerse. Calibra el atrevimiento de las
    recomendaciones: no tiene sentido proponer un manifiesto público a quien no
    está dispuesto ni a salir en vídeo.

    Promedia 7 ítems: los 6 de `disposicion` más ACC-CA-1 de `causas`. El filtro
    listaba también un bloque `disposicion_audacia` que no existe en el JSON
    desde que existe el JSON: una cadena muerta que aparentaba un criterio.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    valores: list[int] = []
    for bloque in modulo_acciones.get("bloques", []) or []:
        if bloque["id"] not in ("disposicion", "causas"):
            continue
        for pregunta in bloque.get("preguntas", []) or []:
            if pregunta["tipo"] != "likert5":
                continue
            v = _entero(respuestas.get(pregunta["id"]))
            if v is not None:
                valores.append(v)

    if not valores:
        return {"indice": None, "nivel": "desconocido", "lectura": ""}

    indice = round(100.0 * (statistics.fmean(valores) - 1) / 4, 1)
    if indice < 35:
        nivel = "prudente"
        lectura = (
            "Estás dispuesto a poco riesgo de exposición. Las recomendaciones se "
            "ajustarán a eso: una marca prudente puede funcionar, pero necesita "
            "compensar con consistencia y calidad, porque no va a ganar por "
            "visibilidad."
        )
    elif indice < 65:
        nivel = "equilibrado"
        lectura = (
            "Aceptas exponerte hasta cierto punto. Es la zona más común y también "
            "la más fácil de volver tibia: elige dos o tres gestos audaces y "
            "sostenlos, en vez de repartir el atrevimiento en todo."
        )
    else:
        nivel = "audaz"
        lectura = (
            "Estás dispuesto a exponerte de verdad. Es la materia prima de una "
            "marca memorable — y también de una crisis. Merece la pena decidir de "
            "antemano dónde está tu línea roja, antes de que te la haga cruzar el "
            "impulso del momento."
        )
    return {"indice": indice, "nivel": nivel, "lectura": lectura}


# ------------------------------------------------ puentes con app.activos

def sistema_activos(
    respuestas: dict[str, Any],
    modulos: dict[str, Any] | None = None,
    paletas: list[dict[str, Any]] | None = None,
    ficha: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atajo a `app.activos.sistema_activos`. El motor de activos vive allí.

    Está aquí porque `indice_invisibilidad` necesita el recuento de activos
    fuertes y porque hay documentación que lo llama desde este módulo. No
    reimplementa nada: si la lógica cambia, cambia en un solo sitio.
    """
    from . import activos as activos_mod

    return activos_mod.sistema_activos(respuestas, modulos, paletas, ficha)


def contradicciones_de_permanencia(
    respuestas: dict[str, Any], modulos: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Choques entre lo que se ha prometido publicar y lo que se puede sostener.

    Los calcula `app.activos.regla_repeticion`; aquí solo se les da la forma de
    aviso ({tipo, titulo, texto}) para que el informe los meta en la lista de
    siempre sin tocar las plantillas. Se conservan los `ids` citados: un aviso
    sin la cita de las dos preguntas es una regañina.
    """
    from . import activos as activos_mod

    salida: list[dict[str, Any]] = []
    for choque in activos_mod.regla_repeticion(respuestas).get("contradicciones", []):
        salida.append(
            {
                "tipo": "permanencia",
                "titulo": "Eso no se sostiene",
                "texto": choque.get("texto", ""),
                "ids": choque.get("ids", []),
            }
        )
    return salida
