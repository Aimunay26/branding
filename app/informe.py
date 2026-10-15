"""Ensambla el informe: de las respuestas crudas al resultado completo.

Este módulo no calcula nada por su cuenta a propósito. Los índices viven en
`scoring`, los activos en `activos`, las paletas en `paletas`: aquí solo se
llaman en el orden correcto y se le da al resultado la forma que leen las dos
plantillas y el dossier de la IA. Cuando una regla de negocio aparece escrita
en este fichero es que está en el sitio equivocado.

El orden de las llamadas de `construir` sí es una decisión: `indice_invisibilidad`
depende de tibieza, distinción, consistencia y del sistema de activos, y el
sistema de activos depende de las paletas y de la ficha del primario.
"""

from __future__ import annotations

from typing import Any

from . import activos as activos_mod, contenido, graficos, paletas as paletas_mod, scoring

# La escala se manda UNA vez en la cabecera del dossier. Sin ella, un «3/5» en
# ciento y pico respuestas es un número sin unidades y el modelo se lo inventa.
ESCALA_LIKERT = {"1": "nada, no va conmigo", "3": "a veces", "5": "sí, totalmente"}

# El bloque de categoría: el fondo contra el que la persona tiene que destacar.
# La IA lo necesita entero para no proponer justo lo que ya hace todo el gremio.
IDS_CATEGORIA = {
    "oficio": "COM-CX-1",
    "lo_que_hacen_todos": "COM-CX-2",
    "colores_ocupados": "COM-CX-3",
    "formato_de_todos": "COM-CX-4",
    "tono_de_todos": "COM-CX-5",
    "me_confunden_con": "COM-CX-6",
}

# Contra qué se define, con SUS palabras. COM-PA-3b es la frase literal que oye
# en su profesión: es lo único del cuestionario que se puede citar entrecomillado.
IDS_ENEMIGO = ("COM-PA-3", "COM-PA-3b", "COM-NA-4", "COM-PO-1", "ACC-CA-2", "ACC-CA-3")

# Vetos del cuerpo. La opción que veta no lleva ninguna marca en el JSON: lo que
# la delata es su `descripcion` («Descartado del todo», «nunca te lo
# propondremos»). Se listan los valores conocidos y además se comprueba la
# descripción, para que una opción nueva no se cuele como permitida.
VETOS_CUERPO = {
    "VIS-LM-1": {"nunca", "me_haria"},
    "VIS-LM-2": {"no", "me_pondria"},
    "VIS-LM-3": {"nunca_maq"},
    "VIS-LM-4": {"no_cirugia", "abierto", "prefiero_no"},
}
FRASES_DE_VETO = ("descartado", "no te lo propondremos", "nunca te lo propondremos")

# Vetos del pelo. Solo tres, y solo las respuestas que cierran una puerta: un
# «barba corta» es una elección, no un límite, y meterlo aquí sería inflar la
# lista de exclusión hasta que el modelo deje de leerla.
VETO_PELO_LARGO = ("VIS-CA-2", "nada")        # no toca el largo
VETO_PELO_COLOR = ("VIS-CA-3", "natural")     # solo si es lo ÚNICO que acepta
VETO_PELO_MANTENIMIENTO = ("VIS-CA-6", "bajo")  # su descripción ya dice qué cae

# Límites de comunicación: likert donde un 1 o un 2 significa «no cuentes con eso».
IDS_LIMITE_COMUNICACION = (
    "COM-LI-1", "COM-LI-2", "COM-LI-3", "COM-LI-4", "COM-LI-5", "COM-LI-6",
    "ACC-DI-1", "ACC-DI-2", "ACC-DI-3", "ACC-DI-4", "ACC-DI-5", "ACC-DI-6",
)
UMBRAL_LIMITE_LIKERT = 2

ID_VETO_LIBRE = "VIS-LM-5"

# Las preguntas de veto, para poder decir «no lo contestó» en vez de callarse.
# «No tengo vetos» y «no llegó a esa pantalla» son cosas distintas y hoy el
# modelo no las distinguía: las vacías desaparecían en silencio.
IDS_VETO = (
    "VIS-RO-2", "VIS-CR-2", "VIS-LM-1", "VIS-LM-2", "VIS-LM-3", "VIS-LM-4",
    ID_VETO_LIBRE, "VIS-CA-2", "VIS-CA-3", "VIS-CA-6",
)


# ------------------------------------------------------------------ ensamblado

def construir(
    respuestas: dict[str, Any],
    ronda: int = 0,
    lexico: dict[str, Any] | None = None,
    categoria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """respuestas = {identidad: {...}, arquetipos: {...}, comunicacion: {...},
    visual: {...}, acciones: {...}}

    `ronda` es cuántas veces se ha hecho repetir a esta persona, y la decide el
    servidor (columna borradores.ronda). Antes se fijaba aquí a
    MAX_RONDAS_TIBIEZA, así que el estado 'tibio' era inalcanzable y la portada
    acusaba de esconderse en el punto medio a quien tenía 0 % de tibieza.

    `lexico` y `categoria` llegan de fuera para que el que llama pueda cachearlos
    (main.py los lee una vez); si no llegan se leen del disco, porque un informe
    sin léxico mide la calidad de los textos por longitud y sale peor.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    lexico = lexico if isinstance(lexico, dict) else _contenido_opcional("lexico_evasion")
    categoria = categoria if isinstance(categoria, dict) else _contenido_opcional("categoria")

    datos = contenido.arquetipos()
    fichas = datos["fichas"]
    familias = datos["familias"]
    test = contenido.test_arquetipos()
    mods = contenido.modulos()

    # Revienta con ValueError si el test viene a medias, y así tiene que ser:
    # main.py lo traduce a un 400. Un perfil calculado sobre ocho respuestas
    # tiene la misma pinta que uno completo y no vale nada.
    perfil = scoring.puntuar_arquetipos(respuestas.get("arquetipos") or {}, test, fichas)

    # Definición: atención y textos ANTES que el veredicto, porque los dos son
    # disparadores suyos y más graves que la tibieza.
    atencion = scoring.validar_atencion(respuestas, test)
    textos = scoring.calidad_textos(respuestas, mods, lexico)
    tibieza = scoring.indice_tibieza(respuestas, test, mods, lexico)
    veredicto = scoring.veredicto_definicion(tibieza, perfil, atencion, textos, ronda=ronda)

    fam = scoring.puntuar_familias(perfil["puntuaciones"], familias)
    tension = scoring.detectar_tension_identidad(perfil["primario"], fichas, fam, familias)

    afinidades = {
        nombre: scoring.afinidad_por_modulo(respuestas.get(nombre) or {}, mods[nombre])
        for nombre in scoring.SECCIONES_MODULO
    }
    triangulacion = scoring.triangular(perfil, afinidades, fichas)
    audacia = scoring.indice_audacia(respuestas.get("acciones") or {}, mods["acciones"])

    ficha_primaria = fichas[perfil["primario"]]
    lista_paletas = paletas_mod.generar(respuestas.get("visual") or {}, ficha_primaria)
    color = _color_de_marca(lista_paletas, ficha_primaria)

    # El sistema de activos necesita las paletas y la ficha, así que va aquí y no
    # antes. De él sale la salida memorable entera: lo que se repite, lo que se
    # reconoce en tres segundos y las palabras propias.
    sistema = activos_mod.sistema_activos(respuestas, mods, lista_paletas, ficha_primaria)
    activos = sistema["activos"]

    distincion = scoring.indice_distincion(respuestas, mods, categoria)
    consistencia = scoring.indice_consistencia(respuestas, mods)
    dimensiones = scoring.medias_por_dimension(respuestas, mods)
    invisibilidad = scoring.indice_invisibilidad(
        perfil, tibieza, distincion, consistencia, sistema
    )
    permanencia = scoring.contradicciones_de_permanencia(respuestas)

    nombres_arq = {a: fichas[a]["nombre"] for a in fichas}
    nombres_fam = {k: v["nombre"] for k, v in familias.items()}

    # Todos los avisos caen en la misma lista para que «Lo que deberías vigilar»
    # los pinte sin una rama nueva por origen. El orden es el de gravedad: el
    # perfil, la tensión, los controles fallados, los textos, el clon de
    # categoría, los activos y las contradicciones de permanencia.
    avisos = list(perfil["avisos"])
    if tension:
        avisos.append(tension)
    if atencion.get("aviso"):
        avisos.append(atencion["aviso"])
    avisos.extend(textos.get("avisos") or [])
    avisos.extend(distincion.get("avisos") or [])
    avisos.extend(sistema.get("avisos") or [])
    avisos.extend(permanencia)

    refs = contenido.referentes_afines(
        perfil["primario"], perfil["secundario"], perfil["terciario"], limite=6
    )

    return {
        "perfil": perfil,
        "tibieza": tibieza,
        "veredicto": veredicto,
        "ronda": ronda,
        "familias": fam,
        "afinidades": afinidades,
        "triangulacion": triangulacion,
        "audacia": audacia,
        "avisos": avisos,
        "color_marca": color,
        "paletas": lista_paletas,
        "ficha_primaria": ficha_primaria,
        "ficha_secundaria": fichas.get(perfil["secundario"]) if perfil["secundario"] else None,
        "ficha_terciaria": fichas.get(perfil["terciario"]) if perfil["terciario"] else None,
        "referentes": refs,
        "nombres_arquetipos": nombres_arq,
        "nombres_familias": nombres_fam,
        # --- salida memorable (app.activos) ---
        "activos": activos,
        "activos_fuertes": sistema["fuertes"],
        "conflictos_activos": sistema["conflictos"],
        "identificabilidad": activos_mod.indice_identificabilidad(activos, respuestas),
        "reconocimiento_3s": activos_mod.reconocimiento_3s(activos, respuestas),
        "regla_repeticion": activos_mod.regla_repeticion(respuestas),
        "identidad_verbal": activos_mod.identidad_verbal(respuestas, ficha_primaria),
        "una_sola_cosa_borrador": activos_mod.una_sola_cosa_borrador(
            respuestas, activos, mods
        ),
        # Los eslóganes los escribe la IA (Salida.recomendaciones[].eslogan_candidatos)
        # y no hay forma determinista de sacarlos del cuestionario: una frase
        # corta montada con plantillas suena a plantilla. Va vacío a propósito, y
        # el PDF ya pinta los de la IA cuando existen.
        "eslogan_candidatos": [],
        # --- índices nuevos ---
        "atencion": atencion,
        "calidad_textos": textos,
        "distincion": distincion,
        "consistencia": consistencia,
        "invisibilidad": invisibilidad,
        "medias_por_dimension": dimensiones,
        "permanencia": permanencia,
        # Los mismos dos objetos con el nombre corto. Las dos especificaciones de
        # este cambio los bautizaron distinto ('textos'/'calidad_textos' y
        # 'dimensiones'/'medias_por_dimension') y el resultado se guarda en la
        # base: publicar los dos nombres cuesta unas líneas de JSON y evita que
        # una plantilla futura pinte una sección vacía por buscar el otro.
        "textos": textos,
        "dimensiones": dimensiones,
        "graficos": {
            "radar": graficos.radar_arquetipos(perfil["puntuaciones"], nombres_arq, color),
            "familias": graficos.barras_familias(fam["medias"], nombres_fam, color),
            "triangulacion": graficos.barras_triangulacion(
                perfil["puntuaciones"], afinidades, nombres_arq, color
            ),
        },
    }


def _contenido_opcional(nombre: str) -> dict[str, Any]:
    """Lee un JSON de contenido por su función, sin reventar si no está.

    `lexico_evasion` y `categoria` son ficheros nuevos: si el despliegue va por
    delante del contenido, el informe tiene que salir igual y perder solo el
    índice que dependa de ellos, no la página entera.
    """
    funcion = getattr(contenido, nombre, None)
    if funcion is None:
        return {}
    try:
        datos = funcion()
    except Exception:  # noqa: BLE001 - falta el fichero o está roto; se sigue sin él
        return {}
    return datos if isinstance(datos, dict) else {}


def _color_de_marca(lista_paletas: list[dict[str, Any]], ficha: dict[str, Any]) -> str:
    """El color de marca es el dominante de «La tuya»: el que el usuario declaró.

    Así el CSS `--marca` y los gráficos usan TU color, no el acento del arquetipo.
    Si no hay paletas (visual sin responder), caemos a la ficha como antes.
    """
    for p in lista_paletas:
        if p["id"] == "tuya" and p["colores"]:
            dom = next((c for c in p["colores"] if c["rol"] == "dominante"), p["colores"][0])
            return dom["hex"]
    paleta = ficha.get("visual", {}).get("paleta", [])
    for rol in ("acento", "dominante"):
        for c in paleta:
            if c.get("rol") == rol:
                return c["hex"]
    return paleta[0]["hex"] if paleta else "#C1440E"


# ------------------------------------------------------------------ dossier

def dossier_para_ia(
    respuestas: dict[str, Any], resultado: dict[str, Any]
) -> dict[str, Any]:
    """Lo que se le manda al modelo. Números y respuestas, no conclusiones.

    Dos reglas mandan aquí y explican todo lo que falta:

    1. Fuera los datos personales que no son señal de branding. Apellidos y
       correo no dicen nada de una marca y viajaban a un proveedor externo en
       cada llamada.
    2. Fuera la prosa que ya ha escrito el programa. `lectura_coherencia`,
       `audacia.lectura` y el `texto` de cada aviso son diagnósticos redactados:
       un modelo al que le das el diagnóstico hecho lo parafrasea y devuelve el
       informe que ya tenías. Van los números en crudo, que no puede inventarse.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    resultado = resultado if isinstance(resultado, dict) else {}
    perfil = resultado.get("perfil") or {}
    fichas = contenido.arquetipos()["fichas"]
    mods = contenido.modulos()
    indice = scoring.indice_preguntas(mods)

    def nombre(a: str | None) -> str | None:
        return fichas[a]["nombre"] if a and a in fichas else None

    puntuaciones = perfil.get("puntuaciones") or {}
    opuesto = perfil.get("opuesto")

    legibles: dict[str, list[dict[str, Any]]] = {}
    sin_contestar: dict[str, list[str]] = {}
    for seccion in scoring.SECCIONES_MODULO:
        legibles[seccion], sin_contestar[seccion] = _legible(
            respuestas.get(seccion) or {}, seccion, mods
        )

    identificabilidad = dict(resultado.get("identificabilidad") or {})
    identificabilidad.pop("lectura", None)

    return {
        # Cabecera: cómo se leen los números que vienen después.
        "escala_likert": ESCALA_LIKERT,
        "identidad": _identidad_minima(respuestas),
        "definicion": {
            "tibieza": (resultado.get("tibieza") or {}).get("indice"),
            "veredicto": (resultado.get("veredicto") or {}).get("estado"),
            "motivos": (resultado.get("veredicto") or {}).get("motivos") or [],
            "ronda": resultado.get("ronda"),
        },
        "paletas": [
            {
                "id": p["id"],
                "nombre": p["nombre"],
                "colores": [c["hex"] for c in p["colores"]],
            }
            for p in resultado.get("paletas") or []
        ],
        "arquetipo": {
            "primario": nombre(perfil.get("primario")),
            "secundario": nombre(perfil.get("secundario")),
            "terciario": nombre(perfil.get("terciario")),
            "puntuaciones": {
                fichas[a]["nombre"]: p for a, p in puntuaciones.items() if a in fichas
            },
            "coherencia": perfil.get("coherencia"),
            # Los números con los que se decide si un perfil está definido. Con
            # ellos el modelo puede discutir el diagnóstico; con la lectura ya
            # escrita solo puede repetirlo.
            "sigma": perfil.get("sigma"),
            "sigma_max_teorico": perfil.get("sigma_max_teorico"),
            "hueco": perfil.get("hueco"),
            "media_global": perfil.get("media_global"),
            "estilo_respuesta": perfil.get("estilo_respuesta"),
            "opuesto": {
                "arquetipo": nombre(opuesto),
                "puntuacion": puntuaciones.get(opuesto),
            },
            "sombra_del_primario": (fichas.get(perfil.get("primario")) or {}).get("sombra"),
            "familia_dominante": (resultado.get("familias") or {}).get("dominante"),
        },
        "avisos": _avisos_para_ia(resultado.get("avisos") or [], perfil, fichas),
        # La triangulación viaja como hecho (qué módulo se desvía y de qué
        # forma), no como párrafo: sus `titulo` y `texto` se imprimen tal cual en
        # el informe, y el encargo le prohíbe al modelo escribir una lectura que
        # se parezca a algo ya impreso. Debajo van las afinidades en crudo, que
        # son de donde sale el desajuste y no se pueden parafrasear.
        "triangulacion": [
            {"tipo": t.get("tipo"), "modulo": t.get("modulo")}
            for t in resultado.get("triangulacion") or []
            if isinstance(t, dict)
        ],
        "afinidades_por_modulo": {
            modulo: {
                fichas[a]["nombre"] if a in fichas else a: v for a, v in (valores or {}).items()
            }
            for modulo, valores in (resultado.get("afinidades") or {}).items()
        },
        # `audacia.nivel` lo lee la post-validación (regla R4: a un audaz no se le
        # propone prudencia). La lectura se queda fuera: le sugería al modelo que
        # un perfil prudente se conformara.
        "audacia": {
            "indice": (resultado.get("audacia") or {}).get("indice"),
            "nivel": (resultado.get("audacia") or {}).get("nivel"),
        },
        "indices": {
            clave: {
                "indice": (resultado.get(clave) or {}).get("indice"),
                "nivel": (resultado.get(clave) or {}).get("nivel"),
            }
            for clave in ("distincion", "consistencia", "invisibilidad")
        },
        "identificabilidad": identificabilidad,
        "dimensiones": resultado.get("medias_por_dimension") or {},
        "categoria": _categoria_declarada(respuestas, indice),
        "enemigo_declarado": _enemigo_declarado(respuestas, indice),
        "activos_declarados": _activos_para_ia(resultado.get("activos") or []),
        "limites_duros": _limites_duros(respuestas, indice),
        "eleccion_forzada": _eleccion_forzada(respuestas, perfil),
        "control_atencion": resultado.get("atencion") or {},
        "donde_se_escondio": _donde_se_escondio(
            resultado.get("tibieza") or {}, indice
        ),
        "calidad_textos": {
            "indice": (resultado.get("calidad_textos") or {}).get("indice"),
            "pobres": [
                {"id": p.get("id"), "motivos": p.get("motivos") or []}
                for p in (resultado.get("calidad_textos") or {}).get("pobres") or []
            ],
        },
        "respuestas_modulos": legibles,
        "sin_contestar": sin_contestar,
        "referentes_afines": [
            {
                "nombre": r["nombre"],
                "arquetipo": r["arquetipo_primario"],
                "titular": r.get("titular"),
                "gesto_diferenciador": r.get("gesto_diferenciador"),
                "prendas_firma": r.get("prendas_firma") or [],
                "riesgo": r.get("riesgo"),
            }
            for r in resultado.get("referentes") or []
        ],
    }


def _identidad_minima(respuestas: dict[str, Any]) -> dict[str, Any]:
    """Nombre de pila, nombre artístico y tipo de marca. Nada más.

    Apellidos y correo no aportan un gramo de señal de branding y viajaban al
    proveedor de IA en cada llamada. El nombre de pila se queda porque la
    post-validación comprueba con él la prueba del bar (quien habla de ti en un
    bar no dice tu nombre: te describe).
    """
    identidad = respuestas.get("identidad")
    identidad = identidad if isinstance(identidad, dict) else {}
    return {
        "nombre": identidad.get("nombre"),
        "artistico": identidad.get("artistico"),
        "tipo_marca": identidad.get("tipo_marca"),
    }


def _avisos_para_ia(
    avisos: list[dict[str, Any]], perfil: dict[str, Any], fichas: dict[str, Any]
) -> list[dict[str, Any]]:
    """Los avisos sin su párrafo, con el número que los provocó.

    El `texto` es prosa ya redactada. Lo que el modelo no puede deducir es la
    puntuación: un punto ciego con 12,5 y otro con 19,9 se cuentan distinto.
    """
    puntuaciones = perfil.get("puntuaciones") or {}
    salida: list[dict[str, Any]] = []
    for aviso in avisos:
        if not isinstance(aviso, dict):
            continue
        entrada: dict[str, Any] = {
            "tipo": aviso.get("tipo"),
            "titulo": aviso.get("titulo"),
        }
        if aviso.get("ids"):
            entrada["ids"] = aviso["ids"]

        arquetipo = None
        if aviso.get("tipo") == "punto_ciego":
            arquetipo = perfil.get("opuesto")
        elif aviso.get("tipo") == "sobreexpresion":
            arquetipo = perfil.get("primario")
        if arquetipo:
            entrada["arquetipo"] = arquetipo
            entrada["nombre_arquetipo"] = (fichas.get(arquetipo) or {}).get("nombre")
            entrada["puntuacion"] = puntuaciones.get(arquetipo)

        salida.append(entrada)
    return salida


def _categoria_declarada(
    respuestas: dict[str, Any], indice: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """El sector tal como lo describe la persona: el fondo contra el que destaca.

    Va con las etiquetas y no con los valores porque la regla del encargo es que
    ninguna dirección se parezca a esto, y «post_semanal» no se parece a nada.
    """
    return {
        clave: _respuesta_legible(respuestas, pid, indice)
        for clave, pid in IDS_CATEGORIA.items()
    }


def _enemigo_declarado(
    respuestas: dict[str, Any], indice: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Contra qué se define, con sus palabras y citando el id.

    Se manda por id de pregunta y no con nombres bonitos: la regla del sistema
    obliga al modelo a citar (COM-PA-3) cuando use esto, y no puede citar lo que
    no ha visto escrito.
    """
    salida: dict[str, Any] = {}
    for pid in IDS_ENEMIGO:
        valor = _respuesta_legible(respuestas, pid, indice)
        if valor not in (None, "", []):
            salida[pid] = valor
    return salida


def _activos_para_ia(activos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Los activos tal cual, menos la regla de uso.

    La `clave` es contrato: la post-validación tumba la salida si el modelo
    propone un activo que no está en esta lista. La regla de uso se queda fuera
    porque es texto del informe, no material de decisión.
    """
    salida: list[dict[str, Any]] = []
    for activo in activos:
        if not isinstance(activo, dict):
            continue
        salida.append(
            {
                "clave": activo.get("clave"),
                "tipo": activo.get("tipo"),
                "valor": activo.get("valor"),
                "etiqueta": activo.get("etiqueta"),
                "fuente_ids": activo.get("fuente_ids") or [],
                "fuerza": activo.get("fuerza"),
                "declarado": activo.get("declarado"),
                "conflicto": activo.get("conflicto"),
            }
        )
    return salida


def _limites_duros(
    respuestas: dict[str, Any], indice: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """La lista de exclusión: lo que no se le propone bajo ningún concepto.

    Cada entrada lleva la `consecuencia`, que es la `descripcion` de la opción
    elegida y donde está lo operativo («Olvidamos el estilo de oficina clásico»).
    Antes se tiraba y quedaba la etiqueta sola, que dice qué no quiere pero no
    qué implica.

    `sin_contestar` es la clave que faltaba: sin ella el modelo no distingue «no
    tengo vetos» de «no llegó a esa pantalla», y rellenar ese hueco es
    exactamente donde se inventan las recomendaciones inviables.
    """
    def contestada(pid: str) -> Any:
        """El valor de una pregunta, buscando su sección en el índice.

        No se lee `respuestas['visual']` a pelo aunque hoy todas estas preguntas
        vivan ahí: el día que una se mueva de módulo, el límite desaparecería en
        silencio y la IA propondría justo lo vetado.
        """
        ficha = indice.get(pid)
        return (respuestas.get(ficha["seccion"]) or {}).get(pid) if ficha else None

    cuerpo: dict[str, dict[str, Any]] = {}
    for pid, valores_veto in VETOS_CUERPO.items():
        valor = contestada(pid)
        entrada = _entrada_de_opcion(pid, valor, indice)
        if entrada is None:
            continue
        if valor in valores_veto or _parece_veto(entrada.get("consecuencia")):
            cuerpo[pid] = entrada

    pelo: dict[str, dict[str, Any]] = {}
    for pid, valor_veto in (VETO_PELO_LARGO, VETO_PELO_MANTENIMIENTO):
        if contestada(pid) == valor_veto:
            pelo[pid] = _entrada_de_opcion(pid, valor_veto, indice)
    pid, valor_veto = VETO_PELO_COLOR
    if _lista(contestada(pid)) == [valor_veto]:
        # Solo si es lo único que acepta: marcarlo junto a otras tres opciones no
        # es un límite, es una preferencia más.
        pelo[pid] = _entrada_de_opcion(pid, valor_veto, indice)

    comunicacion: list[dict[str, Any]] = []
    for pid in IDS_LIMITE_COMUNICACION:
        ficha = indice.get(pid)
        if ficha is None:
            continue
        valor = (respuestas.get(ficha["seccion"]) or {}).get(pid)
        try:
            v = int(valor)
        except (TypeError, ValueError):
            continue
        if v <= UMBRAL_LIMITE_LIKERT:
            comunicacion.append(
                {
                    "id": pid,
                    "etiqueta": f"ha dicho {v}/5 a: {ficha['pregunta']['texto']}",
                    "valor": v,
                }
            )

    faltan = [
        pid
        for pid in IDS_VETO
        if pid in indice
        and (respuestas.get(indice[pid]["seccion"]) or {}).get(pid) in (None, "", [], {})
    ]

    return {
        "ropa_vetada": _entradas_de_multiple(respuestas, "VIS-RO-2", indice),
        "colores_vetados": _entradas_de_multiple(respuestas, "VIS-CR-2", indice),
        "cuerpo": cuerpo,
        "pelo": pelo,
        "comunicacion": comunicacion,
        "veto_libre": _texto_crudo(respuestas, ID_VETO_LIBRE, indice),
        "sin_contestar": faltan,
    }


def _eleccion_forzada(
    respuestas: dict[str, Any], perfil: dict[str, Any]
) -> dict[str, Any]:
    """Los ocho dilemas del test, con el dilema y lo que eligió.

    Es el dato menos falseable del cuestionario —hay que renunciar a tres cosas
    para quedarse con una— y hasta ahora no llegaba al modelo de ninguna forma:
    solo viajaba la tasa, ya agregada, dentro del perfil.
    """
    test = contenido.test_arquetipos()
    resp = respuestas.get("arquetipos") if isinstance(respuestas.get("arquetipos"), dict) else {}
    fichas = contenido.arquetipos()["fichas"]

    bloques: list[dict[str, Any]] = []
    for bloque in test.get("eleccion_forzada", []) or []:
        elegido = resp.get(bloque["id"])
        entrada: dict[str, Any] = {
            "id": bloque["id"],
            "dilema": bloque.get("enunciado"),
            "elegido": None,
            "arquetipo": None,
        }
        if elegido not in (None, ""):
            for i, opcion in enumerate(bloque.get("opciones", []) or []):
                # La respuesta llega como índice de opción o como el propio
                # arquetipo, según por dónde entre: las dos formas son válidas.
                if str(elegido) in (str(i), opcion.get("arquetipo", "")):
                    entrada["elegido"] = opcion.get("texto")
                    entrada["arquetipo"] = (
                        fichas.get(opcion.get("arquetipo"), {}).get("nombre")
                        or opcion.get("arquetipo")
                    )
                    break
        bloques.append(entrada)

    return {
        "bloques": bloques,
        "tasa_fc": {
            fichas[a]["nombre"] if a in fichas else a: t
            for a, t in (perfil.get("tasa_fc") or {}).items()
        },
        "concentracion": perfil.get("concentracion_fc"),
        "desempate_aplicado": perfil.get("desempate_aplicado"),
    }


def _donde_se_escondio(
    tibieza: dict[str, Any], indice: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Las preguntas concretas donde se escapó, con su texto y el motivo.

    Se calculaban y se tiraban: al modelo solo le llegaba el porcentaje, así que
    podía decir «te has escondido» pero no dónde. El texto de los ítems del test
    se busca aparte porque el test no está en el índice de los módulos.
    """
    test = contenido.test_arquetipos()
    textos_test = {
        item["id"]: item.get("texto")
        for item in (test.get("items") or []) + (test.get("control") or [])
    }

    salida: list[dict[str, Any]] = []
    for entrada in tibieza.get("preguntas_tibias") or []:
        if not isinstance(entrada, dict):
            continue
        pid = entrada.get("id")
        ficha = indice.get(pid)
        texto = ficha["pregunta"]["texto"] if ficha else textos_test.get(pid)
        salida.append(
            {
                "id": pid,
                "seccion": entrada.get("seccion"),
                "pregunta": texto,
                "motivo": entrada.get("motivo"),
            }
        )
    return salida


# --------------------------------------------------- lectura de respuestas

def _lista(valor: Any) -> list[Any]:
    if isinstance(valor, list):
        return valor
    if valor in (None, "", {}):
        return []
    return [valor]


def _parece_veto(descripcion: Any) -> bool:
    """¿La descripción de la opción dice que eso no se propone?

    Red de seguridad para las opciones que se añadan al JSON después de esta
    tabla: el veto vive en la prosa de la opción, no en un campo, así que una
    opción nueva podría colarse como permitida sin que nadie se entere.
    """
    if not isinstance(descripcion, str):
        return False
    minuscula = descripcion.lower()
    return any(frase in minuscula for frase in FRASES_DE_VETO)


def _opciones(
    pregunta: dict[str, Any], indice: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Las opciones de una pregunta, resolviendo `opciones_de`.

    COM-CA-2 («¿cuál será tu casa principal?») no tiene opciones propias: se
    elige entre lo que se marcó en COM-CA-1. Sin resolver la referencia, su
    respuesta viajaba al modelo como el valor crudo («linkedin») en vez de como
    la etiqueta, que es lo que sí se puede leer.
    """
    opciones = pregunta.get("opciones") or []
    if opciones:
        return opciones
    referida = pregunta.get("opciones_de")
    if not referida:
        return []
    indice = indice if indice is not None else scoring.indice_preguntas(contenido.modulos())
    ficha = indice.get(referida)
    return (ficha["pregunta"].get("opciones") or []) if ficha else []


def _opcion(
    pregunta: dict[str, Any],
    valor: Any,
    indice: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    for opcion in _opciones(pregunta, indice):
        if opcion.get("valor") == valor:
            return opcion
    return None


def _entrada_de_opcion(
    pid: str, valor: Any, indice: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """{'id', 'etiqueta', 'consecuencia'} de una opción elegida."""
    ficha = indice.get(pid)
    if ficha is None or valor in (None, "", [], {}):
        return None
    opcion = _opcion(ficha["pregunta"], valor, indice)
    if opcion is None:
        return {"id": pid, "etiqueta": str(valor), "consecuencia": None}
    return {
        "id": pid,
        "etiqueta": opcion.get("etiqueta"),
        "consecuencia": opcion.get("descripcion"),
    }


def _entradas_de_multiple(
    respuestas: dict[str, Any], pid: str, indice: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    ficha = indice.get(pid)
    if ficha is None:
        return []
    valor = (respuestas.get(ficha["seccion"]) or {}).get(pid)
    entradas = [_entrada_de_opcion(pid, v, indice) for v in _lista(valor)]
    return [e for e in entradas if e]


def _texto_crudo(
    respuestas: dict[str, Any], pid: str, indice: dict[str, dict[str, Any]]
) -> str | None:
    """El texto libre tal y como lo escribió, sin recortar ni reformular.

    VIS-LM-5 es un veto en prosa: cualquier limpieza puede cambiar lo que veta.
    """
    ficha = indice.get(pid)
    if ficha is None:
        return None
    valor = (respuestas.get(ficha["seccion"]) or {}).get(pid)
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


def _respuesta_legible(
    respuestas: dict[str, Any], pid: str, indice: dict[str, dict[str, Any]]
) -> Any:
    """La respuesta a una pregunta suelta, ya en etiquetas o en texto.

    Devuelve lista si la pregunta es de opción múltiple, cadena si es única o de
    texto, y None si no está contestada: la forma la marca la pregunta, no lo
    que haya llegado.
    """
    ficha = indice.get(pid)
    if ficha is None:
        return None
    pregunta = ficha["pregunta"]
    valor = (respuestas.get(ficha["seccion"]) or {}).get(pid)
    if valor in (None, "", [], {}):
        return None

    tipo = pregunta.get("tipo")
    if tipo == "multiple":
        return [
            (_opcion(pregunta, v, indice) or {}).get("etiqueta", str(v))
            for v in _lista(valor)
        ]
    if tipo == "unica":
        return (_opcion(pregunta, valor, indice) or {}).get("etiqueta", str(valor))
    return valor if isinstance(valor, (str, int, float, list, dict)) else str(valor)


def _legible(
    respuestas: dict[str, Any],
    modulo_id: str,
    mods: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Convierte {id_pregunta: valor} en pares pregunta/respuesta con texto.

    Devuelve (respuestas_legibles, sin_contestar). Lo segundo existe porque
    descartar los vacíos en silencio hacía indistinguibles «no tengo vetos» y
    «no lo contestó», que para una recomendación son cosas opuestas.

    Cada entrada lleva el `id`: la regla del encargo obliga al modelo a citar
    (COM-PA-3) o (VIS-RO-5) cuando use una respuesta, y sin el identificador no
    puede citar nada. Y lleva la `consecuencia` de la opción elegida, que es
    donde está lo operativo de la respuesta.
    """
    respuestas = respuestas if isinstance(respuestas, dict) else {}
    mods = mods if isinstance(mods, dict) else contenido.modulos()
    indice = scoring.indice_preguntas(mods)
    modulo = mods.get(modulo_id) or {}
    salida: list[dict[str, Any]] = []
    sin_contestar: list[str] = []
    nombres_referentes: dict[str, str] | None = None

    for bloque in modulo.get("bloques", []) or []:
        for pregunta in bloque.get("preguntas", []) or []:
            valor = respuestas.get(pregunta["id"])
            if valor in (None, "", [], {}):
                sin_contestar.append(pregunta["id"])
                continue

            tipo = pregunta["tipo"]
            consecuencia = None

            if tipo in ("unica", "multiple"):
                elegidos = valor if isinstance(valor, list) else [valor]
                opciones = [
                    o for o in _opciones(pregunta, indice) if o["valor"] in elegidos
                ]
                etiquetas = [o["etiqueta"] for o in opciones]
                texto = ", ".join(etiquetas) if etiquetas else str(valor)
                if len(opciones) == 1:
                    # Con una sola opción elegida la descripción es la
                    # consecuencia de ESA elección. Con cinco marcadas, no.
                    consecuencia = opciones[0].get("descripcion")

            elif tipo == "bipolar":
                escala = pregunta.get("escala", 7)
                medio = (escala + 1) / 2
                crudo = valor.get("valor") if isinstance(valor, dict) else valor
                try:
                    v = float(crudo)
                except (TypeError, ValueError):
                    sin_contestar.append(pregunta["id"])
                    continue
                polo = pregunta["polo_izq"] if v < medio else pregunta["polo_der"]
                if v == medio:
                    texto = (
                        f"En el punto medio entre «{pregunta['polo_izq']}» y "
                        f"«{pregunta['polo_der']}»"
                    )
                else:
                    fuerza = abs(v - medio) / (medio - 1) if medio > 1 else 0
                    grado = "claramente" if fuerza > 0.6 else "ligeramente"
                    texto = f"{grado} hacia «{polo}» ({crudo}/{escala})"

            elif tipo == "likert5":
                texto = f"{valor}/5"

            elif tipo == "ranking":
                # El orden es la respuesta: el primero es el que va a repetir
                # hasta hartarse. Y lo que deja fuera dice tanto como lo que
                # elige, así que la renuncia viaja explícita.
                opciones = {o["valor"]: o for o in _opciones(pregunta, indice)}
                elegidos = [v for v in _lista(valor) if v in opciones]
                puestos = [
                    f"{i}.º {opciones[v]['etiqueta']}" for i, v in enumerate(elegidos, 1)
                ]
                resto = [
                    o["etiqueta"] for v, o in opciones.items() if v not in elegidos
                ]
                texto = ", ".join(puestos) if puestos else str(valor)
                if resto:
                    texto += "; renuncia a: " + ", ".join(resto)

            elif tipo == "reparto100":
                opciones = {o["valor"]: o for o in _opciones(pregunta, indice)}
                if isinstance(valor, dict):
                    con_puntos = [
                        (v, p)
                        for v, p in valor.items()
                        if isinstance(p, (int, float)) and p > 0
                    ]
                    con_puntos.sort(key=lambda par: (-par[1], par[0]))
                    partes = [
                        f"{opciones.get(v, {}).get('etiqueta', v)} {int(p)} puntos"
                        for v, p in con_puntos
                    ]
                    a_cero = len(opciones) - len(con_puntos)
                    texto = ", ".join(partes) if partes else str(valor)
                    if partes and a_cero > 0:
                        texto += "; el resto a cero"
                else:
                    # Respuestas antiguas: la pregunta era de opción única antes
                    # de convertirse en reparto. Se lee como lo que era.
                    texto = opciones.get(valor, {}).get("etiqueta", str(valor))

            elif tipo == "duelo":
                if nombres_referentes is None:
                    nombres_referentes = {
                        r["id"]: r["nombre"] for r in contenido.referentes()
                    }
                elegido = valor.get("elegido") if isinstance(valor, dict) else valor
                no_copio = valor.get("no_copio") if isinstance(valor, dict) else None
                if not elegido:
                    sin_contestar.append(pregunta["id"])
                    continue
                texto = f"Elige {nombres_referentes.get(str(elegido), str(elegido))}"
                if isinstance(no_copio, str) and no_copio.strip():
                    texto += f"; NO le copiaría: «{no_copio.strip()}»"

            else:
                texto = str(valor)

            entrada: dict[str, Any] = {
                "id": pregunta["id"],
                "bloque": bloque["nombre"],
                "pregunta": pregunta["texto"],
                "respuesta": texto,
            }
            # Las claves vacías se omiten en vez de ir a null: son 145 preguntas
            # y cada clave inútil se paga en tokens de entrada.
            if pregunta.get("dimension"):
                entrada["dimension"] = pregunta["dimension"]
            if consecuencia:
                entrada["consecuencia"] = consecuencia
            salida.append(entrada)

    return salida, sin_contestar
