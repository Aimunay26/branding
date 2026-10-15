"""Paletas: el color declarado manda y el veto se respeta.

app/paletas.py no lo está reescribiendo nadie ahora mismo, así que estas pruebas
van contra el comportamiento real y son las que avisarán si alguien lo cambia.
"""

from __future__ import annotations

from conftest import ficha_minima

from app import paletas


def _por_id(salida):
    return {p["id"]: p for p in salida}


def _hexes(paleta):
    return [c["hex"].upper() for c in paleta["colores"]]


def _familias(paleta):
    fams = set()
    for c in paleta["colores"]:
        fams |= paletas.clasificar(c["hex"])
    return fams


# ------------------------------------------------------------------ el color declarado manda

def test_el_color_declarado_es_el_dominante_de_la_tuya(fichas):
    """El fallo que este módulo existe para arreglar: elegías verde y te salía el
    burdeos del Amante, sin rastro del verde por ninguna parte.

    Caso real, con la ficha real del Amante: el verde declarado tiene que ir el
    primero y con rol de dominante, y el burdeos de la ficha baja a acompañamiento.
    """
    amante = fichas["AMA"]
    salida = _por_id(paletas.generar({"VIS-CR-3": "verde"}, amante))
    tuya = salida["tuya"]

    assert tuya["colores"][0]["hex"] == "#2E7D46"
    assert tuya["colores"][0]["rol"] == "dominante"
    assert tuya["colores"][0]["nombre"] == "Verde"
    # Un solo dominante: el resto de la ficha entra como acompañamiento.
    assert [c["rol"] for c in tuya["colores"]].count("dominante") == 1
    assert "#7B1F32" in _hexes(tuya)  # el burdeos sigue, pero de secundario


def test_sin_color_declarado_manda_el_del_arquetipo(fichas):
    """Sin VIS-CR-3 no se inventa nada: se cae al dominante de la ficha."""
    amante = fichas["AMA"]
    tuya = _por_id(paletas.generar({}, amante))["tuya"]
    assert tuya["colores"][0]["hex"] == "#7B1F32"


# ------------------------------------------------------------------ el veto

def test_el_veto_saca_el_color_de_la_paleta_del_arquetipo(fichas):
    """Caso real completo: verde declarado, ficha del Amante y veto a los vivos.

    El Oro cálido (#C9A227) de la ficha es un color vivo, así que cae de las dos
    paletas y el subtítulo lo dice en vez de callarlo. El verde declarado
    (#2E7D46) no es vivo y sobrevive.
    """
    amante = fichas["AMA"]
    salida = _por_id(
        paletas.generar({"VIS-CR-3": "verde", "VIS-CR-2": ["no_vivos", "no_neon"]}, amante)
    )

    assert "#C9A227" not in _hexes(salida["tuya"])
    assert "#C9A227" not in _hexes(salida["arquetipo"])
    assert "vivo" not in _familias(salida["arquetipo"])
    assert "por tus vetos" in salida["arquetipo"]["subtitulo"]
    assert salida["tuya"]["colores"][0]["hex"] == "#2E7D46"


def test_el_veto_a_los_pasteles_se_respeta(fichas):
    amante = fichas["AMA"]
    salida = _por_id(paletas.generar({"VIS-CR-2": ["no_pasteles"]}, amante))
    for clave in ("tuya", "arquetipo"):
        assert "pastel" not in _familias(salida[clave]), clave


def test_una_paleta_vaciada_por_el_veto_se_rellena_con_neutros(fichas):
    """Vetarlo casi todo no puede devolver una paleta vacía: el informe se
    quedaría con un hueco donde debería haber una decisión."""
    ficha = ficha_minima(
        paleta=[
            {"hex": "#C1121F", "nombre": "Rojo", "rol": "dominante"},
            {"hex": "#1D4ED8", "nombre": "Azul", "rol": "secundario"},
        ]
    )
    salida = _por_id(paletas.generar({"VIS-CR-2": ["no_vivos"]}, ficha))
    colores = salida["arquetipo"]["colores"]
    # Dos y no tres: solo hay dos neutros seguros distintos que no repitan hex,
    # así que el relleno se queda ahí. Lo que importa es que no salga vacía y que
    # ninguno de los que entra esté vetado.
    assert len(colores) >= 2
    assert "vivo" not in _familias(salida["arquetipo"])


def test_la_polarizante_se_salta_el_veto_a_proposito(fichas):
    """AGUJERO CONOCIDO, escrito aquí para que no se cambie sin darse cuenta.

    El docstring del módulo dice que lo vetado «no aparece en ninguna paleta», y
    la polarizante sí lo mete: satura el color declarado al máximo (#00FF55 para
    el verde), que es un color vivo, aunque hayas vetado los vivos. Es coherente
    con lo que la paleta promete —«tu color al extremo, sin puntos medios»— y es
    incoherente con el docstring. Si alguien arregla una de las dos cosas, esta
    prueba falla y le manda a leer este comentario para decidir cuál.
    """
    salida = _por_id(
        paletas.generar(
            {"VIS-CR-3": "verde", "VIS-CR-2": ["no_neon", "no_vivos"]}, fichas["AMA"]
        )
    )
    assert "#00FF55" in _hexes(salida["polarizante"])
    assert "vivo" in paletas.clasificar("#00FF55")


def test_el_veto_al_negro_cambia_el_negro_de_la_polarizante(fichas):
    """Aquí el veto sí manda: el negro absoluto se sustituye por un grafito."""
    salida = _por_id(paletas.generar({"VIS-CR-2": ["no_negro"]}, fichas["AMA"]))
    hexes = _hexes(salida["polarizante"])
    assert "#0D0D0D" not in hexes
    assert "#474440" in hexes


# ------------------------------------------------------------------ monocromo

def test_el_caso_monocromo(fichas):
    """«Solo blanco y negro» no es una evasiva: es una decisión de color.

    Se trata como color propio (negro tinta de dominante, base clara detrás) y la
    polarizante, que no puede saturar un color sin matiz, mete un rojo señal como
    único punto de tensión.
    """
    salida = _por_id(paletas.generar({"VIS-CR-3": "negro_blanco"}, fichas["AMA"]))
    tuya = salida["tuya"]

    assert tuya["colores"][0]["hex"] == "#111111"
    assert tuya["colores"][0]["rol"] == "dominante"
    assert any(c["rol"] == "neutro" for c in tuya["colores"])
    assert "#D7261E" in _hexes(salida["polarizante"])


# ------------------------------------------------------------------ determinismo

def test_dos_ejecuciones_dan_exactamente_lo_mismo(fichas):
    """Aquí no entra la IA. Si el mismo cuestionario diera dos paletas distintas,
    el informe dejaría de ser auditable y no habría forma de discutirlo."""
    respuestas = {"VIS-CR-3": "morado", "VIS-CR-2": ["no_pasteles", "no_tierras"]}
    una = paletas.generar(respuestas, fichas["MAG"])
    otra = paletas.generar(respuestas, fichas["MAG"])
    assert una == otra


def test_el_orden_de_los_vetos_no_cambia_el_resultado(fichas):
    """Los vetos son un conjunto: que el usuario marque antes uno u otro no puede
    mover un solo hex."""
    a = paletas.generar({"VIS-CR-3": "azul", "VIS-CR-2": ["no_negro", "no_vivos"]}, fichas["SAB"])
    b = paletas.generar({"VIS-CR-3": "azul", "VIS-CR-2": ["no_vivos", "no_negro"]}, fichas["SAB"])
    assert a == b


# ------------------------------------------------------------------ clasificación

def test_los_acromaticos_mandan_sobre_el_tono():
    """Un gris no puede salir clasificado como «naranja apagado»: el veto al
    naranja se lo llevaría por delante."""
    assert paletas.clasificar("#111111") == {"negro"}
    assert paletas.clasificar("#FFFFFF") == {"blanco"}
    assert paletas.clasificar("#8A8A8A") == {"gris"}


def test_ninguno_veto_no_veta_nada(fichas):
    """La opción «Ninguno, no descarto nada» está marcada como evasiva en el
    contenido, pero no puede además romper la paleta."""
    con = paletas.generar({"VIS-CR-3": "rojo", "VIS-CR-2": ["ninguno_veto"]}, fichas["AMA"])
    sin = paletas.generar({"VIS-CR-3": "rojo"}, fichas["AMA"])
    assert con == sin
