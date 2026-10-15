"""Tipos compartidos por los dos proveedores de IA.

Existe por una razón concreta: hasta ahora `generar()` devolvía solo la Salida y
tiraba `respuesta.usage` en la misma línea. Con la información ya perdida,
`coste_estimado()` no era «código sin uso»: era una función imposible de llamar
con datos reales. Aquí viaja todo junto —salida, tokens, coste, intentos y
milisegundos— desde la llamada hasta quien lo tenga que guardar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .esquema import Salida


@dataclass(frozen=True)
class ResultadoIA:
    salida: Salida
    proveedor: str
    modelo: str
    tokens_entrada: int
    tokens_salida: int
    coste_usd: float
    intentos: int
    avisos_validacion: list[str] = field(default_factory=list)
    ms: int = 0

    def meta(self) -> dict[str, Any]:
        """Todo menos la salida, para guardarlo junto al JSON de recomendaciones.

        Mientras no exista la tabla `recomendaciones` que propone la
        especificación de datos, esto se mete como clave `_meta` dentro del JSON
        guardado. El día que exista, cada campo se reparte en su columna
        (proveedor, modelo, tokens_entrada, tokens_salida, coste_usd,
        avisos_validacion) y `_meta` desaparece del JSON. Se documenta así a
        propósito para que las dos especificaciones no colisionen en db.py.
        """
        return {
            "proveedor": self.proveedor,
            "modelo": self.modelo,
            "tokens_entrada": self.tokens_entrada,
            "tokens_salida": self.tokens_salida,
            "coste_usd": round(self.coste_usd, 6),
            "intentos": self.intentos,
            "avisos_validacion": list(self.avisos_validacion),
            "ms": self.ms,
        }

    def model_dump(self) -> dict[str, Any]:
        """Puente de compatibilidad con el `salida.model_dump()` de main.py.

        main.py es de otro dueño y hoy hace `salida.model_dump()` con lo que
        devuelve generar_recomendaciones. Al pasar a devolver este dataclass, esa
        línea reventaría con AttributeError y el endpoint daría un 500. Con este
        método sigue funcionando y además guarda el coste, que es justo lo que se
        estaba perdiendo. Cuando main.py pase a `resultado.salida.model_dump()`
        con su `datos["_meta"] = resultado.meta()`, esto se puede borrar.
        """
        datos = self.salida.model_dump()
        datos["_meta"] = self.meta()
        return datos


__all__ = ["ResultadoIA"]
