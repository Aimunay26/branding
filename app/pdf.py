"""Informe en PDF con WeasyPrint (HTML + CSS → PDF).

Plantilla y CSS propios, separados de los de la web: la web es responsive y con
JavaScript, el PDF es papel A4 con @page. Mezclarlos da un PDF feo.

WeasyPrint no ejecuta JavaScript, así que los gráficos llegan ya renderizados
como SVG desde graficos.py.

El import de weasyprint es PEREZOSO y va dentro de generar(). No es un capricho
de estilo: weasyprint carga GTK/Pango por ctypes al importarse, y en una máquina
sin esas librerías (Windows sin el runtime de GTK) el import revienta. Como
main.py importa este módulo, un import arriba tumbaba el servidor ENTERO: la app
no arrancaba y la única función que se perdía era la descarga del PDF. Con el
import aquí dentro, todo lo demás —cuestionario, informe web, IA— funciona igual
y solo falla la ruta del PDF, con un 503 y un mensaje que dice qué falta.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

RAIZ = Path(__file__).resolve().parent
DIR_PLANTILLAS = RAIZ / "templates"
DIR_ESTATICOS = RAIZ / "static"

_entorno = Environment(
    loader=FileSystemLoader(str(DIR_PLANTILLAS)),
    autoescape=select_autoescape(["html"]),
)


def generar(
    registro: dict[str, Any],
    resultado: dict[str, Any],
    recomendaciones: dict[str, Any] | None = None,
) -> bytes:
    """Devuelve los bytes del PDF, o lanza RuntimeError si falta GTK/Pango.

    El RuntimeError lo traduce main.py a un 503 con este mismo mensaje: es un
    servidor mal montado, no un error del usuario ni un fallo del informe.
    """
    try:
        from weasyprint import CSS, HTML
    except (ImportError, OSError) as e:
        # OSError además de ImportError: weasyprint importa bien y falla al
        # cargar las librerías nativas por ctypes, que no siempre es ImportError.
        raise RuntimeError(
            "No se puede generar el PDF en este servidor: falta el runtime de "
            "GTK/Pango que WeasyPrint necesita. El informe completo se ve en la "
            "web y las recomendaciones de la IA funcionan igual; lo único que no "
            f"sale es la descarga en PDF. Detalle técnico: {e}"
        ) from e

    plantilla = _entorno.get_template("informe_pdf.html")
    html = plantilla.render(
        informe=registro,
        r=resultado,
        recomendaciones=recomendaciones,
    )

    # base_url mal puesto es el error número uno con WeasyPrint: sin él, ni las
    # imágenes ni el CSS cargan y sale un PDF en blanco.
    return HTML(string=html, base_url=str(DIR_ESTATICOS)).write_pdf(
        stylesheets=[CSS(filename=str(DIR_ESTATICOS / "css" / "pdf.css"))]
    )
