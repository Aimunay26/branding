"""Motor de puntuación: perfil, tibieza y controles de atención.

Estas pruebas están escritas contra la especificación de app/scoring.py, no
contra el código que había antes: varias fijan por escrito el arreglo de un bug
concreto (el número de BUG que citan es el de la especificación) para que no se
pueda deshacer sin que salte algo.

Los números que aparecen con `pytest.approx` (41,7 · 54,2 · 45,8 · 58,3) no son
mágicos: salen de la escala teórica ±16 y de que solo hay cuatro ítems inversos
para doce arquetipos. Si cambian, algo de la corrección de aquiescencia se ha
movido y hay que decidirlo, no aceptarlo.
"""

from __future__ import annotations

import pytest

from conftest import (
    armar_test_sintetico,
    fichas_sinteticas,
    modulo_sintetico,
    responder_al_centro,
    respuestas_sinteticas,
    respuestas_test_definidas,
    respuestas_test_uniformes,
)

from app import scoring


# ------------------------------------------------------------------ perfil

def test_perfil_definido_saca_su_arquetipo_en_cabeza(test_arq, fichas):
    """Un 5 al Creador y un 2 al resto tiene que salir Creador."""
    respuestas = respuestas_test_definidas(test_arq, "CRE")
    perfil = scoring.puntuar_arquetipos(respuestas, test_arq, fichas)

    assert perfil["primario"] == "CRE"
    assert perfil["puntuaciones"]["CRE"] == max(perfil["puntuaciones"].values())
    assert perfil["orden"][0] == "CRE"


def test_un_perfil_con_hueco_en_cabeza_es_definido(test_arq, fichas):
    """BUG 6: la coherencia se decidía SOLO por sigma, y sigma se comprime tras
    la corrección de aquiescencia.

    Con un 5 al Creador y un 2 a los otros once, sigma sale ~10,1 y el corte
    viejo (10,5) llamaba «moderado» a un perfil con 32 puntos de hueco entre el
    primero y el cuarto. Manda el hueco; sigma pasa a métrica secundaria.
    """
    perfil = scoring.puntuar_arquetipos(
        respuestas_test_definidas(test_arq, "CRE"), test_arq, fichas
    )
    orden = sorted(perfil["puntuaciones"].values(), reverse=True)
    assert orden[0] - orden[3] >= scoring.HUECO_DEFINIDO
    assert perfil["hueco"] == pytest.approx(orden[0] - orden[3], abs=0.05)
    assert perfil["coherencia"] == "definido"


def test_perfil_plano_sale_con_doce_cincuentas(test_arq, fichas):
    """Contestar 3 a todo da 50,0 en los doce. Es el caso que el producto existe
    para detectar, y el que un min-max sobre el sujeto haría invisible."""
    respuestas = respuestas_test_uniformes(test_arq, 3)
    perfil = scoring.puntuar_arquetipos(respuestas, test_arq, fichas)

    assert set(perfil["puntuaciones"].values()) == {50.0}
    assert perfil["sigma"] == pytest.approx(0.0, abs=0.05)
    assert perfil["coherencia"] == "plano"


def test_los_cuatro_items_inversos_rompen_la_simetria(test_arq, fichas):
    """Contestar 5 a todo NO da doce cincuentas, y el docstring del módulo lo
    decía mal durante mucho tiempo.

    Solo hay 4 ítems inversos (BUF-4, EXP-4, INO-4, GOB-4) para 12 arquetipos, así
    que la corrección de aquiescencia deja de ser simétrica: esos cuatro
    arquetipos caen a 41,7 y los otros ocho suben a 54,2. Si esta prueba falla,
    o se han añadido ítems inversos o se ha cambiado la fórmula de recodificación.
    """
    con_inverso = {it["arquetipo"] for it in test_arq["items"] if it.get("inverso")}
    assert con_inverso == {"BUF", "EXP", "INO", "GOB"}

    perfil = scoring.puntuar_arquetipos(
        respuestas_test_uniformes(test_arq, 5), test_arq, fichas
    )
    for arq, p in perfil["puntuaciones"].items():
        esperado = 41.7 if arq in con_inverso else 54.2
        assert p == pytest.approx(esperado, abs=0.15), f"{arq} salió {p}"

    # Y al revés: con 1 en todo se da la vuelta.
    perfil_bajo = scoring.puntuar_arquetipos(
        respuestas_test_uniformes(test_arq, 1), test_arq, fichas
    )
    for arq, p in perfil_bajo["puntuaciones"].items():
        esperado = 58.3 if arq in con_inverso else 45.8
        assert p == pytest.approx(esperado, abs=0.15), f"{arq} salió {p}"


def test_respuestas_huerfanas_no_cuentan(test_arq, fichas):
    """Un id que no está en el test se ignora, no revienta."""
    respuestas = respuestas_test_definidas(test_arq, "SAB")
    respuestas["ID-QUE-NO-EXISTE"] = 5
    respuestas["CTRL-1"] = 2  # los controles tampoco son ítems
    perfil = scoring.puntuar_arquetipos(respuestas, test_arq, fichas)
    assert perfil["primario"] == "SAB"


def test_sin_ninguna_respuesta_valida_falla_con_mensaje(test_arq, fichas):
    with pytest.raises(ValueError):
        scoring.puntuar_arquetipos({}, test_arq, fichas)


def test_faltar_items_de_un_arquetipo_no_se_traga_en_silencio(test_arq, fichas):
    """BUG 15 de la especificación.

    Con un envío parcial, la escala teórica de ±16 comprime las puntuaciones
    hacia el 50 sin avisar: el arquetipo con dos ítems parece más templado de lo
    que es. Tiene que reventar con un ValueError que diga cuántos faltan.
    """
    respuestas = respuestas_test_definidas(test_arq, "CRE")
    faltan = [it["id"] for it in test_arq["items"] if it["arquetipo"] == "CRE"][:2]
    for item_id in faltan:
        del respuestas[item_id]

    with pytest.raises(ValueError) as excinfo:
        scoring.puntuar_arquetipos(respuestas, test_arq, fichas)
    assert "CRE" in str(excinfo.value)


# ------------------------------------------------------------------ tibieza

def _tibieza(respuestas, test, mods, lexico=None):
    """Atajo con la firma de cuatro argumentos, que es la buena.

    El `lexico` es lo que hace medible «esto no dice nada» en las respuestas
    escritas: sin él, las ocho preguntas de texto no entran ni en el numerador ni
    en el denominador y el posicionamiento entero se pasa con un «no sé».
    """
    return scoring.indice_tibieza(respuestas, test, mods, lexico)


def test_todo_al_centro_dispara_la_tibieza(test_arq, mods, lexico):
    """El sujeto que el producto existe para parar: 3 en los 48 ítems y la
    respuesta más escurrida posible en los tres módulos."""
    respuestas = responder_al_centro(mods)
    respuestas["arquetipos"] = respuestas_test_uniformes(test_arq, 3)

    t = _tibieza(respuestas, test_arq, mods, lexico)

    # 50 % es un suelo deliberadamente flojo: lo que se comprueba es que el
    # detector no se traga un cuestionario contestado entero por el punto medio,
    # no un número exacto que cambie cada vez que se añade una pregunta.
    assert t["indice"] > 50.0
    assert t["tibias"] > 0
    assert t["preguntas_tibias"], "hay tibieza pero no se dice en cuáles"
    assert len(t["preguntas_tibias"]) == t["tibias"]


def test_perfil_con_postura_no_dispara(test_arq, lexico):
    """48 ítems sin un solo 3 y diez preguntas de módulo con postura: 0 %.

    Se usa un módulo sintético a propósito. Fabricar 76 respuestas «buenas»
    contra el contenido real haría que esta prueba se rompiera cada vez que
    alguien añade una pregunta, y una prueba que se rompe por eso se acaba
    borrando.
    """
    mods = modulo_sintetico(10)
    respuestas = respuestas_sinteticas(10, escurridas=0)
    respuestas["arquetipos"] = respuestas_test_definidas(test_arq, "CRE")

    t = _tibieza(respuestas, test_arq, mods, lexico)

    assert t["tibias"] == 0
    assert t["indice"] == 0.0
    assert t["preguntas_tibias"] == []


def test_el_denominador_incluye_las_preguntas_de_opcion(test_arq, lexico):
    """BUG 1: las `unica` cuya respuesta no era evasiva no contaban ni en el
    numerador ni en el denominador.

    Consecuencia real: el denominador máximo era 77 y los 48 ítems del test se
    llevaban el 62 % del índice, así que esconderse en los módulos salía gratis.
    Las diez preguntas sintéticas tienen que sumar diez al total, contestadas
    con postura o con escape.
    """
    mods = modulo_sintetico(10)
    respuestas = respuestas_sinteticas(10, escurridas=0)
    respuestas["arquetipos"] = respuestas_test_definidas(test_arq, "CRE")

    t = _tibieza(respuestas, test_arq, mods, lexico)
    assert t["total"] == 58  # 48 ítems del test + 10 preguntas de módulo
    assert t["por_seccion"]["comunicacion"]["total"] == 10


def test_cada_seccion_tiene_su_propio_umbral(test_arq, lexico):
    """Un módulo escurrido al 30 % dispara aunque el global se quede por debajo.

    Es el punto de la especificación: denominador POR SECCIÓN. Con un saco único,
    tres de diez respuestas escurridas en un módulo se diluyen entre los 48 ítems
    del test y no las ve nadie.
    """
    mods = modulo_sintetico(10)
    respuestas = respuestas_sinteticas(10, escurridas=3)
    respuestas["arquetipos"] = respuestas_test_definidas(test_arq, "CRE")

    t = _tibieza(respuestas, test_arq, mods, lexico)

    assert t["por_seccion"]["comunicacion"]["indice"] == pytest.approx(30.0, abs=0.1)
    assert t["por_seccion"]["comunicacion"]["dispara"] is True
    assert t["por_seccion"]["arquetipos"]["dispara"] is False
    # 3 de 58 es un 5,2 % global: sin umbral por sección esto pasaría de largo.
    assert t["indice"] < scoring.UMBRAL_TIBIEZA_GLOBAL
    assert "comunicacion" in t["motivos"]


def test_la_tibieza_dice_la_respuesta_previa(test_arq, lexico):
    """El muro tiene que poder enseñar lo que contestaste antes y compararlo con
    lo nuevo. Sin `valor_previo` no hay muro, hay una pantalla que repregunta a
    ciegas."""
    mods = modulo_sintetico(10)
    respuestas = respuestas_sinteticas(10, escurridas=4)
    respuestas["arquetipos"] = respuestas_test_definidas(test_arq, "CRE")

    t = _tibieza(respuestas, test_arq, mods, lexico)
    tibias = [p for p in t["preguntas_tibias"] if p["seccion"] == "comunicacion"]
    assert len(tibias) == 4
    for p in tibias:
        assert p["valor_previo"] == "escape"
        assert p["motivo"]


# ------------------------------------------------------------------ controles de atención

def test_controles_de_atencion_bien_contestados(test_arq):
    """`valor_esperado` no lo leía nadie en todo el proyecto: el filtro de
    scoring aparentaba una validación que no existía."""
    respuestas = {"arquetipos": dict(respuestas_test_definidas(test_arq, "CRE"))}
    for c in test_arq["control"]:
        if c.get("tipo_control") == "consistencia":
            pareja = respuestas["arquetipos"][c["pareja"]]
            respuestas["arquetipos"][c["id"]] = c["suma_esperada"] - pareja
        else:
            respuestas["arquetipos"][c["id"]] = c["valor_esperado"]

    a = scoring.validar_atencion(respuestas, test_arq)
    assert a["fallados"] == []
    assert a["sin_datos"] == []
    assert a["estado"] == "ok"
    assert a["aviso"] is None


def test_dos_controles_fallados_invalidan_el_informe(test_arq):
    respuestas = {"arquetipos": dict(respuestas_test_definidas(test_arq, "CRE"))}
    fijos = [c for c in test_arq["control"] if c.get("tipo_control", "valor_fijo") == "valor_fijo"]
    assert len(fijos) >= 2, "el contenido ya no trae dos controles de valor fijo"
    for c in fijos:
        # Un valor que no es el pedido, sea cual sea el pedido.
        respuestas["arquetipos"][c["id"]] = 1 if c["valor_esperado"] != 1 else 4

    a = scoring.validar_atencion(respuestas, test_arq)
    assert len(a["fallados"]) >= 2
    assert a["estado"] == "sin_validez"
    assert a["aviso"]["tipo"] == "atencion"


def test_control_sin_contestar_no_es_un_fallo(test_arq):
    """Que falte una respuesta no es lo mismo que contestarla mal: uno es un
    cuestionario a medias y el otro es contestar al azar."""
    respuestas = {"arquetipos": dict(respuestas_test_definidas(test_arq, "CRE"))}
    a = scoring.validar_atencion(respuestas, test_arq)
    assert a["fallados"] == []
    assert len(a["sin_datos"]) == len(test_arq["control"])
    assert a["estado"] == "ok"


def test_el_control_de_consistencia_tiene_tolerancia(test_arq):
    """CTRL-3 empareja con otro ítem: se compara la SUMA, con tolerancia. Sin
    tolerancia, cualquiera que matice un punto sale como respondiente al azar."""
    c3 = next((c for c in test_arq["control"] if c.get("tipo_control") == "consistencia"), None)
    assert c3 is not None, "el contenido ya no trae el control de consistencia"

    respuestas = {"arquetipos": dict(respuestas_test_definidas(test_arq, "CRE"))}
    for c in test_arq["control"]:
        if c.get("tipo_control") != "consistencia":
            respuestas["arquetipos"][c["id"]] = c["valor_esperado"]

    pareja = respuestas["arquetipos"][c3["pareja"]]
    # Dentro de la tolerancia: pasa.
    respuestas["arquetipos"][c3["id"]] = c3["suma_esperada"] - pareja + c3["tolerancia"]
    assert scoring.validar_atencion(respuestas, test_arq)["fallados"] == []

    # Un punto por encima de la tolerancia: falla.
    respuestas["arquetipos"][c3["id"]] = c3["suma_esperada"] - pareja + c3["tolerancia"] + 1
    assert c3["id"] in scoring.validar_atencion(respuestas, test_arq)["fallados"]


# ------------------------------------------------------------------ constantes

def test_el_tope_de_rondas_esta_declarado_antes_de_usarse():
    """MAX_RONDAS_TIBIEZA vivía después de la función que la usa y funcionaba
    solo porque Python resuelve los globales en tiempo de llamada. Sigue siendo
    una constante y tiene que valer 2."""
    assert scoring.MAX_RONDAS_TIBIEZA == 2


def test_los_umbrales_de_tibieza_son_los_de_la_especificacion():
    assert scoring.UMBRAL_TIBIEZA_TEST == 15.0
    assert scoring.UMBRAL_TIBIEZA_MODULO == 22.0
    assert scoring.UMBRAL_TIBIEZA_GLOBAL == 20.0


def test_sigma_plano_esta_por_encima_de_la_distribucion_nula():
    """SIGMA_PLANO valía 6,5, por DEBAJO del ~8,3 que sale por pura varianza de
    muestreo con 4 ítems: llamaba «definido» al ruido."""
    assert scoring.SIGMA_PLANO >= 8.5
    assert scoring.SIGMA_DEFINIDO >= 12.0


def test_no_quedan_umbrales_relativos_de_secundario():
    """BUG 9: con un corte relativo a p1, definirse quitaba arquetipos y ser tibio
    los regalaba. Los umbrales pasan a ser absolutos."""
    assert hasattr(scoring, "UMBRAL_SECUNDARIO_ABS")
    assert scoring.UMBRAL_SECUNDARIO_ABS == 60.0
    assert not hasattr(scoring, "UMBRAL_SECUNDARIO"), (
        "UMBRAL_SECUNDARIO relativo sigue ahí: los dos criterios conviven y uno miente"
    )


# ------------------------------------------------------------------ el motor completo, sin reventar

def test_el_test_sintetico_tambien_puntua():
    """El motor no puede depender de que los ítems se llamen como se llaman hoy."""
    test = armar_test_sintetico()
    respuestas = {it["id"]: 3 for it in test["items"]}
    perfil = scoring.puntuar_arquetipos(respuestas, test, fichas_sinteticas())
    assert set(perfil["puntuaciones"].values()) == {50.0}
    assert perfil["coherencia"] == "plano"


# ------------------------------------------------------------------ el veredicto del muro

def _atencion_ok():
    return {"de": 3, "pasados": 3, "fallados": [], "sin_datos": [], "estado": "ok", "aviso": None}


def _sin_tibieza():
    return {"indice": 0.0, "por_seccion": {}, "tibias": 0, "total": 58,
            "preguntas_tibias": [], "textos_pobres": [], "motivos": []}


def test_un_informe_sin_validez_manda_repetir_el_test_entero(test_arq, fichas):
    """Fallar dos controles no se arregla repreguntando las tibias: no hay perfil
    del que sacar tibias. Se repite el test completo, y se repite aunque ya se
    hayan gastado las dos rondas."""
    perfil = scoring.puntuar_arquetipos(
        respuestas_test_definidas(test_arq, "CRE"), test_arq, fichas
    )
    atencion = {"de": 3, "pasados": 1, "fallados": ["CTRL-1", "CTRL-2"], "sin_datos": [],
                "estado": "sin_validez", "aviso": {"tipo": "atencion"}}

    v = scoring.veredicto_definicion(
        _sin_tibieza(), perfil, atencion, {"pobres": []}, ronda=scoring.MAX_RONDAS_TIBIEZA
    )

    assert v["estado"] == "sin_validez"
    assert v["repetir"] is True
    assert v["que_devolver"] == "test_completo"


def test_un_perfil_definido_y_con_material_pasa(test_arq, fichas):
    perfil = scoring.puntuar_arquetipos(
        respuestas_test_definidas(test_arq, "CRE"), test_arq, fichas
    )
    v = scoring.veredicto_definicion(_sin_tibieza(), perfil, _atencion_ok(), {"pobres": []}, ronda=0)

    assert v["repetir"] is False
    assert v["estado"] == "definido"
    assert v["motivos"] == []


def test_un_perfil_plano_sin_tibieza_no_se_acusa_de_tibio(test_arq, fichas):
    """BUG 5: la portada acusaba de esconderse en el punto medio a gente con 0 %
    de tibieza. No es lo mismo escurrirse que decir lo mismo de todo, y el
    remedio tampoco: con perfil plano no hay tibias que devolver."""
    perfil = scoring.puntuar_arquetipos(
        respuestas_test_uniformes(test_arq, 3), test_arq, fichas
    )
    assert perfil["coherencia"] == "plano"

    v = scoring.veredicto_definicion(_sin_tibieza(), perfil, _atencion_ok(), {"pobres": []}, ronda=0)

    assert "plano" in v["motivos"]
    assert v["que_devolver"] == "planas"
    assert v["repetir"] is True


def test_agotadas_las_rondas_se_deja_pasar(test_arq, fichas):
    """El muro no puede ser un pasillo sin salida: a la tercera se pasa, con el
    diagnóstico puesto.

    El estado depende del motivo, y esa distinción es el arreglo del BUG 5: a
    quien tiene el perfil plano se le dice 'plano_sin_tibieza' («has dicho lo
    mismo de todo»), no 'tibio_persistente' («te has escondido en el centro»).
    Son dos diagnósticos distintos y hasta ahora salían con el mismo texto.
    """
    perfil = scoring.puntuar_arquetipos(
        respuestas_test_uniformes(test_arq, 3), test_arq, fichas
    )
    v = scoring.veredicto_definicion(
        _sin_tibieza(), perfil, _atencion_ok(), {"pobres": []}, ronda=scoring.MAX_RONDAS_TIBIEZA
    )
    assert v["repetir"] is False
    assert v["estado"] == "plano_sin_tibieza"


def test_agotadas_las_rondas_con_tibieza_de_verdad_es_tibio_persistente(test_arq, fichas):
    perfil = scoring.puntuar_arquetipos(
        respuestas_test_definidas(test_arq, "CRE"), test_arq, fichas
    )
    tibieza = {
        "indice": 45.0,
        "por_seccion": {"comunicacion": {"indice": 45.0, "tibias": 9, "total": 20,
                                         "umbral": scoring.UMBRAL_TIBIEZA_MODULO, "dispara": True}},
        "tibias": 9, "total": 20, "preguntas_tibias": [], "textos_pobres": [],
        "motivos": ["comunicacion"],
    }
    v = scoring.veredicto_definicion(
        tibieza, perfil, _atencion_ok(), {"pobres": []}, ronda=scoring.MAX_RONDAS_TIBIEZA
    )
    assert v["repetir"] is False
    assert v["estado"] == "tibio_persistente"


def test_el_muro_por_plano_devuelve_preguntas_de_verdad(test_arq, fichas):
    """Si el veredicto dice «planas», tiene que haber planas que devolver. Un
    muro que dice «te devuelvo esas 0» y no repregunta nada es un callejón."""
    respuestas = respuestas_test_uniformes(test_arq, 3)
    perfil = scoring.puntuar_arquetipos(respuestas, test_arq, fichas)
    planas = scoring.preguntas_planas({"arquetipos": respuestas}, test_arq)

    # Devuelve un dict, no la lista suelta que decía la especificación: main.py
    # necesita mandar al cliente las preguntas Y los bloques de elección forzada
    # que faltan, porque con un test sin ningún 3 la única forma de mover sigma
    # es la elección forzada.
    assert planas["preguntas"], "perfil plano sin una sola pregunta que devolver"
    assert all(p["seccion"] == "arquetipos" for p in planas["preguntas"])
    assert all("valor_previo" in p for p in planas["preguntas"])
    assert planas["bloques_fc_pendientes"] == [b["id"] for b in test_arq["eleccion_forzada"]]


# ------------------------------------------------------------------ calidad de los textos

def test_un_no_se_en_todos_los_textos_no_cuela(mods, lexico):
    """Las ocho preguntas de texto son el posicionamiento entero. Antes ni
    entraban en el cálculo y se pasaban escribiendo «no sé»."""
    respuestas = {
        "comunicacion": {pid: "no sé" for pid in lexico["obligatorias_para_el_muro"]},
        "visual": {},
        "acciones": {},
    }
    c = scoring.calidad_textos(respuestas, mods, lexico)

    assert c["indice"] < 40.0
    assert c["nivel"] == "sin material"
    assert c["pobres"], "no dice cuáles se han quedado en nada"


def test_copiar_el_ejemplo_se_detecta(mods, lexico):
    """El placeholder es del programa; la marca es del usuario. Copiarlo dos
    veces dispara un aviso propio, distinto del índice."""
    placeholders = {}
    for modulo in mods.values():
        for b in modulo.get("bloques", []):
            for p in b.get("preguntas", []):
                if p.get("placeholder") and p["id"] in lexico["obligatorias_para_el_muro"]:
                    placeholders[p["id"]] = p["placeholder"]
    assert len(placeholders) >= 2, "el contenido ya no trae placeholders que copiar"

    respuestas = {"comunicacion": {}, "visual": {}, "acciones": {}}
    for pid, texto in placeholders.items():
        seccion = {"COM": "comunicacion", "VIS": "visual", "ACC": "acciones"}[pid[:3]]
        respuestas[seccion][pid] = texto

    c = scoring.calidad_textos(respuestas, mods, lexico)
    copiadas = [p for p in c["pobres"] if "copia_el_ejemplo" in p.get("motivos", [])]
    assert len(copiadas) >= 2
    assert "texto_copiado" in {a["tipo"] for a in c.get("avisos", [])}
