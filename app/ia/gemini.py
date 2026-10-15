"""Proveedor de recomendaciones con Gemini (Google).

Por defecto en este software: es rápido y barato, así que las recomendaciones
salen casi al momento. La clave se lee de GEMINI_API_KEY (o GOOGLE_API_KEY), que
el SDK recoge solo.

AVISO HONESTO: ni el identificador del modelo ni las tarifas de este fichero se
han podido verificar contra la documentación de Google desde este repositorio.
Están tal como llegaron. Compruébalos antes de facturar nada con esto y antes de
dar por bueno que el proveedor por defecto arranca.
"""

from __future__ import annotations

import os
from typing import Any

from .esquema import SISTEMA, Salida, construir_prompt

# Sin verificar contra la documentación de Google. Si este identificador no
# existe, el proveedor POR DEFECTO del producto falla en la primera llamada.
MODELO_POR_DEFECTO = "gemini-3.5-flash"

TARIFAS = {  # (entrada, salida) por millón de tokens, en dólares
    # Orientativas y sin verificar, las tres. Ver el aviso del docstring.
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.0),
}

MAX_TOKENS = 32000
TIMEOUT_MS = 120_000  # milisegundos en este SDK; sin verificar aquí


def modelo_activo(modelo: str | None = None) -> str:
    return modelo or os.environ.get("MODELO_IA") or MODELO_POR_DEFECTO


def generar(
    dossier: dict[str, Any],
    modelo: str | None = None,
    historial_extra: list[tuple[str, str]] | None = None,
) -> tuple[Salida, Any]:
    """Devuelve (salida, usage_metadata). Ver el docstring de claude.generar."""
    try:
        from google import genai
        from google.genai import errors, types
    except ImportError as e:
        raise RuntimeError(
            "Falta el paquete google-genai. Instálalo con "
            "`python -m pip install google-genai`."
        ) from e

    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        raise RuntimeError(
            "Falta GEMINI_API_KEY. Copia .env.example a .env y pon tu clave de "
            "https://aistudio.google.com/apikey"
        )

    modelo = modelo_activo(modelo)
    cliente = genai.Client(http_options={"timeout": TIMEOUT_MS})

    contenidos: list[Any] = [
        types.Content(role="user", parts=[types.Part(text=construir_prompt(dossier))])
    ]
    for rol, texto in historial_extra or []:
        contenidos.append(
            types.Content(
                role="model" if rol == "asistente" else "user",
                parts=[types.Part(text=texto)],
            )
        )

    # El import de arriba protege que el paquete exista; no protege que ESTA
    # versión acepte response_schema ni el resto de parámetros del config. Sin
    # este try, un SDK viejo sale como 500 con traza en vez de como mensaje.
    try:
        config = types.GenerateContentConfig(
            system_instruction=SISTEMA,
            response_mime_type="application/json",
            response_schema=Salida,
            max_output_tokens=MAX_TOKENS,
        )
    except TypeError as e:
        raise RuntimeError(
            f"El SDK de google-genai instalado no acepta uno de los parámetros "
            f"del config ({e}). Actualiza el paquete."
        ) from e

    try:
        respuesta = cliente.models.generate_content(
            model=modelo,
            contents=contenidos,
            config=config,
        )
    except errors.APIError as e:
        codigo = getattr(e, "code", "?")
        if codigo in (401, 403):
            raise RuntimeError(
                "La API key de Gemini no es válida o sin permisos. Revisa "
                "GEMINI_API_KEY en .env."
            ) from e
        if codigo == 429:
            raise RuntimeError(
                "Has superado el límite de peticiones de Gemini. Espera un minuto."
            ) from e
        if codigo == 404:
            raise RuntimeError(
                f"Gemini no conoce el modelo '{modelo}'. Los identificadores de "
                "este fichero no están verificados: revisa MODELO_IA en .env."
            ) from e
        raise RuntimeError(f"Error de la API de Gemini ({codigo}): {e}") from e
    except Exception as e:  # noqa: BLE001 — conexión u otros fallos del SDK
        raise RuntimeError(f"No se pudo generar con Gemini: {e}") from e

    salida = getattr(respuesta, "parsed", None)
    if salida is None:
        raise RuntimeError(
            "Gemini no devolvió una respuesta con el formato esperado. "
            "Prueba de nuevo o cambia de modelo."
        )
    # El SDK devuelve una instancia del propio Pydantic; por si acaso, normalizamos.
    if not isinstance(salida, Salida):
        salida = Salida.model_validate(salida)

    return salida, getattr(respuesta, "usage_metadata", None)


def coste_estimado(uso: Any, modelo: str | None = None) -> tuple[float, int, int]:
    """Devuelve (coste_usd, tokens_entrada, tokens_salida)."""
    modelo = modelo_activo(modelo)
    entrada, salida = TARIFAS.get(modelo, TARIFAS[MODELO_POR_DEFECTO])
    prompt_tok = int(getattr(uso, "prompt_token_count", 0) or 0)
    out_tok = int(getattr(uso, "candidates_token_count", 0) or 0)
    return (prompt_tok * entrada + out_tok * salida) / 1_000_000, prompt_tok, out_tok
