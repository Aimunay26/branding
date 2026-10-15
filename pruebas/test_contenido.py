"""El contenido JSON: que parsea, que no se repite y que sigue teniendo lo que
el código busca por su nombre.

Esta es la prueba más barata del proyecto y la que más disgustos evita. Todo el
cuestionario vive en contenido/*.json y se edita a mano: una coma de más deja la
aplicación sin arrancar, un id duplicado hace que una respuesta pise a otra sin
error ninguno, y renombrar VIS-CR-3 rompe las paletas, los activos y el índice de
distinción a la vez, en silencio y solo en tiempo de ejecución.
"""

from __future__ import annotations

import json
import re

import pytest

from conftest import DIR_CONTENIDO, preguntas_de

TIPOS_CON_OPCIONES = {"unica", "multiple", "ranking", "reparto100"}

# Ficheros del cuestionario. referentes.json y arquetipos.json son catálogos y se
# comprueban aparte, con sus propias reglas.
FICHEROS_JSON = sorted(DIR_CONTENIDO.glob("*.json"))


# ------------------------------------------------------------------ parseo

def test_hay_contenido_que_comprobar():
    """Guarda contra el falso verde: si el glob no encuentra nada, las pruebas
    parametrizadas de abajo pasarían todas sin ejecutar ni una comprobación."""
    assert len(FICHEROS_JSON) >= 8


@pytest.mark.parametrize("ruta", FICHEROS_JSON, ids=lambda r: r.name)
def test_todos_los_json_parsean(ruta):
    with ruta.open(encoding="utf-8") as f:
        datos = json.load(f)
    assert isinstance(datos, (dict, list))


@pytest.mark.parametrize("ruta", FICHEROS_JSON, ids=lambda r: r.name)
def test_todos_los_json_van_en_utf8_sin_bom(ruta):
    """El proyecto está en español: las tildes y las eñes están en todas partes.
    Un BOM al principio hace que json.load reviente con un mensaje que no dice
    nada de la causa."""
    crudo = ruta.read_bytes()
    assert not crudo.startswith(b"\xef\xbb\xbf"), "el fichero lleva BOM"
    crudo.decode("utf-8")


# ------------------------------------------------------------------ ids

def _ids_del_cuestionario(test_arq, mods) -> list[tuple[str, str]]:
    """(id, de dónde sale) de todo lo que puede acabar en `respuestas`."""
    salida: list[tuple[str, str]] = []
    for it in test_arq["items"]:
        salida.append((it["id"], "test_arquetipos.items"))
    for c in test_arq.get("control", []):
        salida.append((c["id"], "test_arquetipos.control"))
    for b in test_arq.get("eleccion_forzada", []):
        salida.append((b["id"], "test_arquetipos.eleccion_forzada"))
    for clave, modulo in mods.items():
        for p in preguntas_de(modulo):
            salida.append((p["id"], f"modulo_{clave}"))
    return salida


def test_ningun_id_se_repite_en_todo_el_cuestionario(test_arq, mods):
    """Todas las respuestas viven en el mismo diccionario por sección, y dos ids
    iguales significan que una respuesta pisa a la otra sin dar un solo error."""
    vistos: dict[str, str] = {}
    repetidos: list[str] = []
    for pid, origen in _ids_del_cuestionario(test_arq, mods):
        if pid in vistos:
            repetidos.append(f"{pid} (en {vistos[pid]} y en {origen})")
        vistos[pid] = origen
    assert repetidos == [], "ids repetidos: " + "; ".join(repetidos)


def test_los_items_del_test_son_cuatro_por_arquetipo(test_arq):
    """ITEMS_POR_ARQUETIPO = 4 es una invariante del motor: la escala teórica de
    ±16 sale de ahí. Si el contenido deja de cumplirla, las puntuaciones se
    comprimen hacia el 50 sin que nadie se entere."""
    conteo: dict[str, int] = {}
    for it in test_arq["items"]:
        conteo[it["arquetipo"]] = conteo.get(it["arquetipo"], 0) + 1
    assert len(conteo) == 12
    assert set(conteo.values()) == {4}, conteo


def test_los_arquetipos_del_test_existen_en_las_fichas(test_arq, fichas):
    del_test = {it["arquetipo"] for it in test_arq["items"]}
    assert del_test <= set(fichas), del_test - set(fichas)


# ------------------------------------------------------------------ opciones

def test_toda_opcion_tiene_valor_y_etiqueta(mods):
    """Sin `valor` no se puede guardar la respuesta; sin `etiqueta` el informe
    imprime el valor crudo («semanal_3») en la cara del usuario."""
    fallos: list[str] = []
    for clave, modulo in mods.items():
        for p in preguntas_de(modulo):
            if p.get("tipo") not in TIPOS_CON_OPCIONES:
                continue
            # COM-CA-2 no lleva opciones propias: las hereda de COM-CA-1 con
            # `opciones_de`. Ese caso se comprueba en su propia prueba.
            if p.get("opciones_de"):
                continue
            opciones = p.get("opciones")
            if not opciones:
                fallos.append(f"{clave}/{p['id']}: tipo {p['tipo']} sin opciones")
                continue
            for i, o in enumerate(opciones):
                if not o.get("valor"):
                    fallos.append(f"{clave}/{p['id']}[{i}]: sin valor")
                if not o.get("etiqueta"):
                    fallos.append(f"{clave}/{p['id']}[{i}]: sin etiqueta")
    assert fallos == [], "\n".join(fallos)


def test_las_opciones_derivadas_apuntan_a_una_pregunta_con_opciones(mods):
    """`opciones_de` es la forma de que «¿cuál de los sitios que has elegido es
    tu casa principal?» no repita la lista a mano. Si apunta a un id que no
    existe, la pregunta se pinta vacía y no hay forma de contestarla."""
    todas = {p["id"]: p for modulo in mods.values() for p in preguntas_de(modulo)}
    derivadas = [p for p in todas.values() if p.get("opciones_de")]
    assert derivadas, "ya no queda ninguna pregunta con opciones derivadas"
    for p in derivadas:
        origen = todas.get(p["opciones_de"])
        assert origen is not None, f"{p['id']} deriva de {p['opciones_de']}, que no existe"
        assert origen.get("opciones"), f"{p['opciones_de']} no tiene opciones que prestar"


def test_los_valores_de_una_pregunta_no_se_repiten(mods):
    fallos: list[str] = []
    for clave, modulo in mods.items():
        for p in preguntas_de(modulo):
            if p.get("tipo") not in TIPOS_CON_OPCIONES:
                continue
            valores = [o.get("valor") for o in p.get("opciones", [])]
            if len(valores) != len(set(valores)):
                fallos.append(f"{clave}/{p['id']}: {valores}")
    assert fallos == [], "\n".join(fallos)


def test_las_multiples_tienen_min_menor_que_max(mods):
    """Con min == max no hay elección: cualquier respuesta válida dispara además
    la regla de dilución de la tibieza («marcar cuatro de cuatro es no elegir»),
    o sea que la pregunta es imposible de contestar bien."""
    fallos: list[str] = []
    for clave, modulo in mods.items():
        for p in preguntas_de(modulo):
            if p.get("tipo") != "multiple":
                continue
            minimo = int(p.get("min", 1) or 1)
            maximo = int(p.get("max", len(p.get("opciones", []))) or 0)
            if maximo and minimo >= maximo:
                fallos.append(f"{clave}/{p['id']}: min={minimo} max={maximo}")
    assert fallos == [], "\n".join(fallos)


def test_las_preguntas_tienen_tipo_conocido(mods):
    conocidos = TIPOS_CON_OPCIONES | {"likert5", "bipolar", "texto", "texto_largo", "duelo"}
    desconocidos = [
        f"{clave}/{p['id']}: {p.get('tipo')}"
        for clave, modulo in mods.items()
        for p in preguntas_de(modulo)
        if p.get("tipo") not in conocidos
    ]
    assert desconocidos == [], "\n".join(desconocidos)


# ------------------------------------------------------------------ lo que el código busca por su nombre

IDS_CRITICOS = {
    "VIS-CR-3": "el color declarado: paletas.py, activos.py y el índice de distinción",
    "VIS-CR-2": "los vetos de color: paletas.py y el conflicto de activos.py",
    "VIS-RO-5": "el sello personal: sistema de activos y reconocimiento a 3 segundos",
    "ACC-CT-2": "el formato ancla: activos, distinción y la regla de 12 meses",
    "ACC-RI-1": "los rituales",
    "ACC-RI-2": "el ritual escrito",
    "COM-CA-3": "la cadencia de publicación",
}


@pytest.mark.parametrize("pid", sorted(IDS_CRITICOS))
def test_los_ids_que_el_codigo_lee_por_nombre_siguen_existiendo(pid, mods):
    todos = {p["id"] for modulo in mods.values() for p in preguntas_de(modulo)}
    assert pid in todos, f"{pid} lo lee el código por su nombre para {IDS_CRITICOS[pid]}"


BLOQUES_CRITICOS = {
    "acciones": ["disposicion", "causas"],
}


@pytest.mark.parametrize(
    "modulo,bloque",
    [(m, b) for m, bs in BLOQUES_CRITICOS.items() for b in bs],
)
def test_los_bloques_que_el_codigo_lee_por_nombre_siguen_existiendo(modulo, bloque, mods):
    """`indice_audacia` promedia los ítems de `disposicion` y excluye `causas`
    por el id del bloque. Si el bloque se renombra, el índice sigue calculándose
    y sale mal, que es la peor forma de fallar."""
    ids = {b.get("id") for b in mods[modulo]["bloques"]}
    assert bloque in ids, f"falta el bloque {bloque} en modulo_{modulo}.json"


def test_no_hay_bloques_fantasma_en_el_codigo(mods):
    """`indice_audacia` filtraba por un bloque `disposicion_audacia` que no
    existe en ningún JSON: una cadena muerta que aparentaba una exclusión que
    no ocurría."""
    ids = {b.get("id") for modulo in mods.values() for b in modulo["bloques"]}
    assert "disposicion_audacia" not in ids


def test_todos_los_ids_citados_en_el_codigo_existen(test_arq, mods):
    """Barrido automático: cualquier id con forma de pregunta que aparezca entre
    comillas en app/*.py tiene que existir en el contenido.

    Es la red que evita que renombrar una pregunta se descubra tres semanas
    después, en un informe de un usuario real, como una clave que sale vacía.
    """
    raiz = DIR_CONTENIDO.parent / "app"
    patron = re.compile(r'"((?:COM|VIS|ACC|CTRL|FC)-[A-Z]{2}-\d+b?)"')

    existentes = {pid for pid, _ in _ids_del_cuestionario(test_arq, mods)}
    # Los `no_copio` de los duelos se citan como VIS-DU-1.no_copio; el id base ya
    # está en la lista.
    faltan: dict[str, set[str]] = {}
    for fichero in sorted(raiz.rglob("*.py")):
        for pid in patron.findall(fichero.read_text(encoding="utf-8")):
            if pid not in existentes:
                faltan.setdefault(pid, set()).add(str(fichero.relative_to(raiz.parent)))

    assert not faltan, "ids citados en el código que ya no existen: " + "; ".join(
        f"{pid} ({', '.join(sorted(fich))})" for pid, fich in sorted(faltan.items())
    )


# ------------------------------------------------------------------ léxico y activos

def test_el_lexico_apunta_a_preguntas_que_existen(lexico, mods):
    todos = {p["id"] for modulo in mods.values() for p in preguntas_de(modulo)}
    fallos = []
    for pid in lexico["obligatorias_para_el_muro"]:
        if pid not in todos:
            fallos.append(f"obligatorias_para_el_muro: {pid}")
    for pid in lexico["minimos"]:
        base = pid.split(".")[0]
        if base not in todos:
            fallos.append(f"minimos: {pid}")
    assert fallos == [], "\n".join(fallos)


def test_los_sellos_traen_su_peso_de_activo(mods):
    """`sistema_activos` lee `peso_activo` para saber qué sello es fuerte y cuál
    te encasilla. Sin peso, todos valdrían igual y el recuento de activos fuertes
    dejaría de significar nada.

    La tabla vive en contenido/activos.json y no dentro de cada opción de
    modulo_visual.json: así se puede tocar sin pelearse con quien está editando
    las preguntas. Lo que hay que garantizar es que ninguna opción se quede fuera.
    """
    with (DIR_CONTENIDO / "activos.json").open(encoding="utf-8") as f:
        pesos = json.load(f)["peso_activo"]

    for pid in ("VIS-RO-5", "ACC-RI-1", "ACC-CT-2"):
        tabla = pesos.get(pid)
        assert tabla, f"activos.json no trae pesos para {pid}"
        pregunta = next(
            p for modulo in mods.values() for p in preguntas_de(modulo) if p["id"] == pid
        )
        for o in pregunta["opciones"]:
            assert o["valor"] in tabla, f"{pid}/{o['valor']} sin peso_activo en activos.json"
            assert 0 <= int(tabla[o["valor"]]) <= 3

    # Los dos extremos que la prosa del contenido ya declara.
    assert pesos["VIS-RO-5"]["ninguna_firma"] == 0
    assert pesos["VIS-RO-5"]["gafas"] == 3


def test_los_colores_declarados_cubren_las_opciones_de_vis_cr_3(mods):
    """Si una opción de color no está en colores.json, `paletas.generar` la trata
    como «no declaró color» y cae al del arquetipo: el fallo exacto que ese
    módulo existe para arreglar, reintroducido por la puerta de atrás."""
    with (DIR_CONTENIDO / "colores.json").open(encoding="utf-8") as f:
        colores = json.load(f)
    pregunta = next(p for p in preguntas_de(mods["visual"]) if p["id"] == "VIS-CR-3")
    declarados = set(colores["colores_declarados"])
    for o in pregunta["opciones"]:
        if o.get("evasiva"):
            continue
        assert o["valor"] in declarados, f"VIS-CR-3/{o['valor']} no está en colores.json"


def test_los_vetos_de_color_cubren_las_opciones_de_vis_cr_2(mods):
    with (DIR_CONTENIDO / "colores.json").open(encoding="utf-8") as f:
        colores = json.load(f)
    pregunta = next(p for p in preguntas_de(mods["visual"]) if p["id"] == "VIS-CR-2")
    for o in pregunta["opciones"]:
        assert o["valor"] in colores["vetos"], f"VIS-CR-2/{o['valor']} no está en colores.json"


# ------------------------------------------------------------------ arquetipos

def test_cada_ficha_tiene_lo_que_leen_el_motor_y_las_plantillas(fichas):
    fallos = []
    for arq, ficha in fichas.items():
        for clave in ("nombre", "opuesto", "sombra", "visual", "comunicacion"):
            if clave not in ficha:
                fallos.append(f"{arq}: falta {clave}")
        paleta = ficha.get("visual", {}).get("paleta")
        if not paleta:
            fallos.append(f"{arq}: sin paleta")
            continue
        for c in paleta:
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", c.get("hex", "")):
                fallos.append(f"{arq}: hex inválido {c.get('hex')!r}")
    assert fallos == [], "\n".join(fallos)


def test_el_opuesto_de_cada_arquetipo_existe_y_es_reciproco(fichas):
    fallos = []
    for arq, ficha in fichas.items():
        opuesto = ficha.get("opuesto")
        if opuesto not in fichas:
            fallos.append(f"{arq}: opuesto {opuesto!r} no existe")
        elif fichas[opuesto].get("opuesto") != arq:
            fallos.append(f"{arq} apunta a {opuesto}, pero {opuesto} apunta a {fichas[opuesto].get('opuesto')}")
    assert fallos == [], "\n".join(fallos)
