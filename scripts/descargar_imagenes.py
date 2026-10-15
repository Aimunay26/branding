"""Descarga las fotos de los referentes a local, una sola vez.

    ./.venv/bin/python scripts/descargar_imagenes.py

Por qué existe este script: enlazar directamente a upload.wikimedia.org en cada
generación de PDF no funciona. Wikimedia devuelve 429 (demasiadas peticiones) y
en el propio mensaje pide que no se haga. El resultado es un informe donde unas
fotos salen y otras no, según la suerte. Además de frágil, es abusivo con un
servicio gratuito.

Así que descargamos una vez, reescalamos a un tamaño razonable, y servimos desde
app/static/refs/. El PDF pasa a generarse sin red y sin sorpresas.

La atribución de cada foto sigue viviendo en referentes.json y se pinta en el
informe: las licencias CC BY y CC BY-SA la exigen.
"""

from __future__ import annotations

import io
import json
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
FICHERO = RAIZ / "contenido" / "referentes.json"
DESTINO = RAIZ / "app" / "static" / "refs"

# Wikimedia pide identificarse. Cámbialo por tu contacto real si publicas esto.
AGENTE = (
    "GeneradorBranding/1.0 (https://github.com/tu-usuario/generador-branding; "
    "tu-email@ejemplo.com) Python-urllib"
)
ANCHO_MAX = 600
PAUSA = 1.0  # segundos entre descargas: no machaquemos Wikimedia


def descargar(url: str) -> bytes:
    peticion = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(peticion, timeout=30) as resp:
        return resp.read()


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    datos = json.loads(FICHERO.read_text(encoding="utf-8"))
    referentes = datos["referentes"]

    ok, saltados, fallos = 0, 0, []

    for ref in referentes:
        imagen = ref.get("imagen") or {}
        url = imagen.get("url")
        if not url or not imagen.get("verificada"):
            saltados += 1
            continue

        ruta_rel = f"refs/{ref['id']}.jpg"
        ruta_abs = DESTINO / f"{ref['id']}.jpg"

        if ruta_abs.exists():
            imagen["local"] = ruta_rel
            ok += 1
            continue

        try:
            crudo = descargar(url)
            img = Image.open(io.BytesIO(crudo))
            img = img.convert("RGB")
            if img.width > ANCHO_MAX:
                alto = round(img.height * ANCHO_MAX / img.width)
                img = img.resize((ANCHO_MAX, alto), Image.LANCZOS)
            img.save(ruta_abs, "JPEG", quality=86, optimize=True)

            imagen["local"] = ruta_rel
            ok += 1
            kb = ruta_abs.stat().st_size / 1024
            print(f"  ok  {ref['nombre']:<20} {img.width}x{img.height}  {kb:.0f} KB")
        except Exception as e:  # noqa: BLE001
            fallos.append((ref["nombre"], repr(e)[:70]))
            print(f"  XX  {ref['nombre']:<20} {e}")

        time.sleep(PAUSA)

    FICHERO.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\n{ok} descargadas · {saltados} sin foto libre · {len(fallos)} fallos")
    if fallos:
        print("Fallaron (el informe usará mood board para estas):")
        for nombre, error in fallos:
            print(f"  - {nombre}: {error}")
    print(f"\nreferentes.json actualizado con las rutas locales.")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
