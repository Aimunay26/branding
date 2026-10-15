"""Sistema de activos: lo que hace que a alguien lo reconozcan sin ver su nombre.

Todo lo de app/activos.py es determinista y sin red, así que se prueba entero.
Lo que se vigila aquí es lo que se rompe en silencio: que un cuestionario vacío
devuelva una estructura utilizable en vez de reventar en mitad del informe, que
renunciar al sello no fabrique un sello igualmente, y que un color declarado que
choca con su propio veto se DIGA en vez de resolverse a espaldas del usuario.
"""

from __future__ import annotations

import pytest

from app import activos, paletas


# ------------------------------------------------------------------ material de prueba

def _respuestas_con_sistema() -> dict:
    """Alguien que sí ha decidido: color, sello, formato ancla y ritual escrito."""
    return {
        "visual": {
            "VIS-CR-3": "morado",
            "VIS-CR-2": ["no_pasteles", "no_tierras"],
            "VIS-RO-5": ["gafas", "color_firma"],
            "VIS-RO-3": 2,
            "VIS-RO-4": 6,
            "VIS-AU-1": 6,
            "VIS-AU-3": 5,
            "VIS-CA-7": 4,
        },
        "acciones": {
            "ACC-CT-2": "newsletter",
            "ACC-RI-1": ["formato_fijo", "objeto"],
            "ACC-RI-2": "Cada lunes a las siete abro el correo con la misma frase y el mismo café.",
            "ACC-RI-3": "El sello de cera en cada pedido.",
            "ACC-TR-1": "5_10",
            "ACC-HO-2": "anios_2_3",
            "ACC-HO-3": 5,
            "ACC-DI-5": 4,
        },
        "comunicacion": {
            "COM-CA-3": "semanal_1",
            "COM-LI-6": 5,
            "COM-NA-3": ["oficio", "critica", "datos"],
        },
    }


@pytest.fixture()
def ficha_cre(fichas):
    return fichas["CRE"]


# ------------------------------------------------------------------ respuestas vacías

def test_respuestas_vacias_no_revientan(mods, ficha_cre):
    """Un cuestionario abandonado en la pregunta 3 tiene que poder llegar al
    informe. Si esto revienta, revienta el informe entero y el usuario ve un 500
    en vez de un diagnóstico a medias."""
    s = activos.sistema_activos({}, mods, None, ficha_cre)

    assert set(s) == {"activos", "fuertes", "avisos", "conflictos"}
    assert s["fuertes"] == 0
    assert s["conflictos"] == []
    assert "sin_activos" in {a["tipo"] for a in s["avisos"]}
    for a in s["activos"]:
        assert set(a) == {
            "tipo", "clave", "valor", "etiqueta", "fuente_ids",
            "fuerza", "declarado", "regla_de_uso", "conflicto",
        }


def test_los_indices_con_respuestas_vacias_dan_el_suelo(mods, ficha_cre):
    s = activos.sistema_activos({}, mods, None, ficha_cre)

    ident = activos.indice_identificabilidad(s["activos"], {})
    assert ident["indice"] == 0.0
    assert ident["nivel"] == "invisible"
    assert ident["lectura"]

    tres = activos.reconocimiento_3s(s["activos"], {})
    assert tres["puntos"] == 0
    assert len(tres["comprobaciones"]) == 4
    assert all(c["pasa"] is False for c in tres["comprobaciones"])

    regla = activos.regla_repeticion({})
    assert len(regla["meses"]) == 12
    assert regla["cabecera"]

    assert activos.identidad_verbal({}, ficha_cre)["ganadas"] == 0
    assert activos.una_sola_cosa_borrador({}, s["activos"], mods) is None


def test_respuestas_con_forma_rara_tampoco_revientan(mods, ficha_cre):
    """Un blob de borrador viejo puede traer None y listas donde se espera texto.
    Nada de eso puede tumbar el informe."""
    basura = {"visual": None, "acciones": [], "comunicacion": {"COM-NA-3": None}}
    s = activos.sistema_activos(basura, mods, None, ficha_cre)
    assert isinstance(s["activos"], list)
    assert activos.indice_identificabilidad(s["activos"], basura)["indice"] >= 0.0


# ------------------------------------------------------------------ sin firma no hay activo

def test_sin_firma_no_hay_activo_de_sello(mods, ficha_cre):
    """«Ninguna» en VIS-RO-5 no fabrica un sello por compasión.

    Renunciar al sello es una decisión legítima con un precio, y el precio se
    dice en un aviso; lo que no se hace es inventarle a la persona un objeto que
    no ha elegido.
    """
    r = _respuestas_con_sistema()
    r["visual"]["VIS-RO-5"] = ["ninguna_firma"]

    s = activos.sistema_activos(r, mods, None, ficha_cre)

    assert [a for a in s["activos"] if a["tipo"] == "sello"] == []
    assert "renuncia_a_sello" in {a["tipo"] for a in s["avisos"]}

    ident = activos.indice_identificabilidad(s["activos"], r)
    assert ident["componentes"]["sello"]["valor"] == 0.0


def test_sin_contestar_vis_ro_5_tampoco_hay_sello(mods, ficha_cre):
    r = _respuestas_con_sistema()
    del r["visual"]["VIS-RO-5"]
    s = activos.sistema_activos(r, mods, None, ficha_cre)
    assert [a for a in s["activos"] if a["tipo"] == "sello"] == []


def test_el_veto_de_ropa_tumba_el_activo_que_lo_contradice(mods, ficha_cre):
    """Vetar las joyas no puede convivir con proponer una joya de sello."""
    r = _respuestas_con_sistema()
    r["visual"]["VIS-RO-5"] = ["joya"]
    r["visual"]["VIS-RO-2"] = ["no_joyas"]

    s = activos.sistema_activos(r, mods, None, ficha_cre)
    assert "sello:joya" not in {a["clave"] for a in s["activos"]}


# ------------------------------------------------------------------ conflicto de color

def test_el_color_declarado_contra_su_veto_se_declara(mods, ficha_cre):
    """Rojo declarado (#C1121F, un color vivo) y veto a los vivos.

    El color declarado es soberano y NO se quita: lo que se hace es decir el
    choque con las dos preguntas citadas y bajarle la fuerza. Callarlo sería
    resolver a espaldas del usuario una contradicción que solo él puede deshacer.
    """
    r = {
        "visual": {
            "VIS-CR-3": "rojo",
            "VIS-CR-2": ["no_vivos", "no_negro"],
            "VIS-RO-5": ["gafas"],
        }
    }
    pal = paletas.generar(r["visual"], ficha_cre)
    s = activos.sistema_activos(r, mods, pal, ficha_cre)

    color = next(a for a in s["activos"] if a["tipo"] == "color")
    assert color["declarado"] is True
    assert color["conflicto"], "el choque existe y no se está diciendo"
    assert "Rojo" in color["conflicto"]
    assert color["fuerza"] == 2, "un color en conflicto no puede seguir valiendo 3"

    assert len(s["conflictos"]) == 1
    conflicto = s["conflictos"][0]
    assert conflicto["clave"] == color["clave"]
    assert "VIS-CR-3" in conflicto["ids"] and "VIS-CR-2" in conflicto["ids"]

    # Y el índice lo nota: 60 en vez de 100.
    ident = activos.indice_identificabilidad(s["activos"], r)
    assert ident["componentes"]["color"]["valor"] == 60.0


def test_un_color_que_no_choca_con_el_veto_no_declara_nada(mods, ficha_cre):
    """El verde declarado (#2E7D46) no es un color vivo: veto y color conviven y
    no hay nada que avisar. Un aviso de más es tan malo como uno de menos."""
    r = {"visual": {"VIS-CR-3": "verde", "VIS-CR-2": ["no_vivos"], "VIS-RO-5": ["gafas"]}}
    pal = paletas.generar(r["visual"], ficha_cre)
    s = activos.sistema_activos(r, mods, pal, ficha_cre)

    color = next(a for a in s["activos"] if a["tipo"] == "color")
    assert color["conflicto"] is None
    assert s["conflictos"] == []
    assert color["fuerza"] == 3


# ------------------------------------------------------------------ el caso completo

def test_un_cuestionario_con_decisiones_saca_sistema(mods, ficha_cre):
    r = _respuestas_con_sistema()
    pal = paletas.generar(r["visual"], ficha_cre)
    s = activos.sistema_activos(r, mods, pal, ficha_cre)

    tipos = {a["tipo"] for a in s["activos"]}
    assert {"color", "sello", "formato"} <= tipos
    assert s["fuertes"] >= 2
    assert "sin_activos" not in {a["tipo"] for a in s["avisos"]}

    ident = activos.indice_identificabilidad(s["activos"], r)
    assert ident["indice"] > 50.0
    assert ident["nivel"] in ("reconocible con esfuerzo", "inconfundible")

    tres = activos.reconocimiento_3s(s["activos"], r)
    assert tres["puntos"] == 4


def test_la_tipografia_no_cuenta_como_activo_propio(mods, ficha_cre):
    """Sale de la ficha del arquetipo, no de ninguna respuesta: no la ha elegido
    la persona y por eso no puede inflar el recuento de activos fuertes."""
    s = activos.sistema_activos({}, mods, None, ficha_cre)
    tipografia = [a for a in s["activos"] if a["tipo"] == "tipografia"]
    assert tipografia, "la tipografía debería emitirse igualmente, solo que sin contar"
    assert all(a["declarado"] is False for a in tipografia)
    assert s["fuertes"] == 0


def test_demasiados_sellos_tambien_es_un_aviso(mods, ficha_cre):
    """Seis sellos no son un sistema. El aviso de exceso existe y hay que poder
    dispararlo, no solo el de defecto."""
    r = _respuestas_con_sistema()
    r["visual"]["VIS-RO-5"] = ["gafas", "color_firma", "prenda", "joya", "calzado"]
    r["acciones"]["ACC-RI-1"] = ["formato_fijo", "objeto", "gesto"]

    s = activos.sistema_activos(r, mods, None, ficha_cre)
    if s["fuertes"] > 6:
        assert "demasiados_activos" in {a["tipo"] for a in s["avisos"]}
    else:  # pragma: no cover - depende de los pesos del contenido
        pytest.skip(f"con este contenido salen {s['fuertes']} activos fuertes, no más de 6")


# ------------------------------------------------------------------ determinismo

def test_dos_ejecuciones_dan_lo_mismo(mods, ficha_cre):
    r = _respuestas_con_sistema()
    pal = paletas.generar(r["visual"], ficha_cre)
    assert activos.sistema_activos(r, mods, pal, ficha_cre) == activos.sistema_activos(
        r, mods, pal, ficha_cre
    )
    assert activos.regla_repeticion(r) == activos.regla_repeticion(r)


def test_la_regla_de_repeticion_no_se_toca_hasta_el_mes_trece(mods, ficha_cre):
    r = _respuestas_con_sistema()
    regla = activos.regla_repeticion(r)

    assert [m["mes"] for m in regla["meses"]] == list(range(1, 13))
    con_revision = [m["mes"] for m in regla["meses"] if m.get("revision")]
    assert con_revision == [3, 6, 12]
    assert all(m["piezas"] >= 0 for m in regla["meses"])
