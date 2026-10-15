"""El script de reclamación manual de informes huérfanos.

Se prueba entero contra una base de datos de usar y tirar en tmp_path. La de
verdad (datos/branding.db) no se toca ni de lectura: una prueba que escribe en
la base del proyecto es una prueba que un día borra algo.

Lo que se vigila es lo que hace peligroso a este script: que no le quite un
informe a nadie, que no acepte una cuenta sin verificar, y que la confirmación
escrita sirva de algo.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture()
def script(tmp_path, monkeypatch):
    """Carga scripts/reclamar_informes.py apuntando a una base de usar y tirar.

    El script vive fuera de app/ y no es un módulo importable por su nombre, así
    que se carga por ruta. Es el mismo fichero que se ejecuta a mano.
    """
    from app import db

    datos = tmp_path / "datos"
    datos.mkdir()
    monkeypatch.setattr(db, "DIR_DATOS", datos)
    monkeypatch.setattr(db, "RUTA_DB", datos / "branding.db")
    db.inicializar()

    ruta = RAIZ / "scripts" / "reclamar_informes.py"
    spec = importlib.util.spec_from_file_location("reclamar_informes_prueba", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    yield modulo
    sys.modules.pop(spec.name, None)


def _crear_usuario(db, email: str, con_google: bool = True, verificado: bool = True) -> int:
    with db.conexion(escritura=True) as con:
        cur = con.execute(
            "INSERT INTO usuarios (google_sub, email, email_verificado, nombre, anonimo, "
            "creado_en, visto_en) VALUES (?, ?, ?, ?, 0, ?, ?)",
            (
                f"sub-{email}" if con_google else None,
                email,
                1 if verificado else 0,
                "Quien sea",
                db._ahora(),
                db._ahora(),
            ),
        )
        return int(cur.lastrowid)


def _crear_informe(db, nombre: str, usuario_id: int | None = None) -> int:
    with db.conexion(escritura=True) as con:
        cur = con.execute(
            "INSERT INTO informes (creado_en, nombre, email, tipo_marca, respuestas, "
            "resultado, usuario_id, token_acceso) VALUES (?, ?, ?, ?, ?, ?, ?, "
            "lower(hex(randomblob(16))))",
            (db._ahora(), nombre, "quien@ejemplo.com", "personal", json.dumps({}), json.dumps({}), usuario_id),
        )
        return int(cur.lastrowid)


def _dueno(db, informe_id: int):
    with db.conexion() as con:
        return con.execute("SELECT usuario_id FROM informes WHERE id = ?", (informe_id,)).fetchone()[0]


# ------------------------------------------------------------------ parseo de argumentos

def test_parsear_ids_acepta_la_lista_de_la_ayuda(script):
    assert script.parsear_ids("1,2,3") == [1, 2, 3]
    assert script.parsear_ids(" 4 , 4 , 5 ") == [4, 5]  # sin repetidos


@pytest.mark.parametrize("entrada", ["", "  ", "1,dos", "-1", "3.5"])
def test_parsear_ids_rechaza_lo_que_no_es_un_id(script, entrada):
    with pytest.raises(ValueError):
        script.parsear_ids(entrada)


# ------------------------------------------------------------------ el guardián de la cuenta

def test_solo_vale_una_cuenta_de_google_verificada(script):
    from app import db

    _crear_usuario(db, "sin-google@ejemplo.com", con_google=False)
    _crear_usuario(db, "sin-verificar@ejemplo.com", verificado=False)
    _crear_usuario(db, "buena@ejemplo.com")

    assert script.buscar_usuario("sin-google@ejemplo.com") is None
    assert script.buscar_usuario("sin-verificar@ejemplo.com") is None
    assert script.buscar_usuario("BUENA@ejemplo.com") is not None  # el correo no distingue mayúsculas


# ------------------------------------------------------------------ reclamar

def test_reclama_solo_los_informes_sin_dueno(script):
    from app import db

    mio = _crear_usuario(db, "mio@ejemplo.com")
    ajeno = _crear_usuario(db, "ajeno@ejemplo.com")
    libre = _crear_informe(db, "Huérfano")
    con_dueno = _crear_informe(db, "De otro", usuario_id=ajeno)

    reclamados = script.reclamar(mio, [libre, con_dueno])

    assert reclamados == [libre]
    assert _dueno(db, libre) == mio
    assert _dueno(db, con_dueno) == ajeno, "le ha quitado el informe a otro"


def test_reclamar_deja_rastro_en_eventos(script):
    from app import db

    usuario = _crear_usuario(db, "rastro@ejemplo.com")
    informe = _crear_informe(db, "Huérfano")
    script.reclamar(usuario, [informe])

    with db.conexion() as con:
        filas = con.execute(
            "SELECT usuario_id, tipo, clave, valor FROM eventos WHERE tipo = 'reclamacion'"
        ).fetchall()
    assert len(filas) == 1
    assert dict(filas[0]) == {
        "usuario_id": usuario,
        "tipo": "reclamacion",
        "clave": str(informe),
        "valor": "manual",
    }


def test_el_token_de_acceso_no_cambia_al_reclamar(script):
    """Los enlaces ya compartidos tienen que seguir vivos. Cambiar el token al
    reclamar sería romperle a alguien un enlace que ya envió por correo."""
    from app import db

    usuario = _crear_usuario(db, "token@ejemplo.com")
    informe = _crear_informe(db, "Huérfano")
    with db.conexion() as con:
        antes = con.execute("SELECT token_acceso FROM informes WHERE id = ?", (informe,)).fetchone()[0]

    script.reclamar(usuario, [informe])

    with db.conexion() as con:
        despues = con.execute("SELECT token_acceso FROM informes WHERE id = ?", (informe,)).fetchone()[0]
    assert antes == despues


# ------------------------------------------------------------------ el camino completo, con confirmación

def test_main_sin_la_confirmacion_correcta_no_toca_nada(script, monkeypatch, capsys):
    from app import db

    usuario = _crear_usuario(db, "duda@ejemplo.com")
    informe = _crear_informe(db, "Huérfano")

    monkeypatch.setattr("builtins.input", lambda *_: "sí")
    codigo = script.main(["--email", "duda@ejemplo.com", "--informes", str(informe)])

    assert codigo == 1
    assert _dueno(db, informe) is None
    assert "Abortado" in capsys.readouterr().out
    assert usuario  # el usuario existía; lo que no ha pasado es la asignación


def test_main_con_la_confirmacion_correcta_asigna(script, monkeypatch, capsys):
    from app import db

    usuario = _crear_usuario(db, "seguro@ejemplo.com")
    a = _crear_informe(db, "Uno")
    b = _crear_informe(db, "Dos")

    monkeypatch.setattr("builtins.input", lambda *_: "2")
    codigo = script.main(["--email", "seguro@ejemplo.com", "--informes", f"{a},{b}"])

    salida = capsys.readouterr().out
    assert codigo == 0
    assert _dueno(db, a) == usuario and _dueno(db, b) == usuario
    # El aviso de la copia previa a la migración se imprime siempre, no se esconde.
    assert "branding-pre-v2.db" in salida


def test_main_avisa_de_los_ids_que_no_existen(script, monkeypatch, capsys):
    from app import db

    _crear_usuario(db, "faltan@ejemplo.com")
    monkeypatch.setattr("builtins.input", lambda *_: "0")
    codigo = script.main(["--email", "faltan@ejemplo.com", "--informes", "9998,9999"])

    salida = capsys.readouterr().out
    assert codigo == 0
    assert "NO EXISTE" in salida
    assert "No hay nada que reclamar" in salida


def test_main_rechaza_un_correo_sin_cuenta_de_google(script, capsys):
    codigo = script.main(["--email", "nadie@ejemplo.com", "--informes", "1"])
    assert codigo == 1
    assert "Continuar con Google" in capsys.readouterr().err
