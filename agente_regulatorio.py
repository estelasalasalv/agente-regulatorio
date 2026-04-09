"""
Agente Regulatorio - Sector Eléctrico Español (REE/Red Eléctrica)
=================================================================
Agente conversacional basado en Claude Opus 4.6 con adaptive thinking.
Monitoriza normativa nacional, europea, consultas públicas y benchmark europeo.

Uso:
    python agente_regulatorio.py

Requiere:
    - ANTHROPIC_API_KEY en variable de entorno o en .env
    - pip install anthropic python-dotenv
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import date

import anthropic
from anthropic import beta_tool

# ──────────────────────────────────────────────
# Carga de datos regulatorios
# ──────────────────────────────────────────────

DATA_DIR = Path(__file__).parent / "data"


def _load(filename: str) -> list | dict:
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


NORMATIVA_NACIONAL = _load("normativa_nacional.json")
NORMATIVA_EUROPEA = _load("normativa_europea.json")
CONSULTAS_PUBLICAS = _load("consultas_publicas.json")
BENCHMARK_EUROPEO = _load("benchmark_europeo.json")


# ──────────────────────────────────────────────
# Definición de herramientas (tools)
# ──────────────────────────────────────────────

def buscar_normativa_nacional(query: str = "", tipo: str = "") -> str:
    """
    Busca en la normativa nacional (leyes, RDL, RD, OM, circulares CNMC).

    Args:
        query: Texto libre para buscar en título, resumen o impacto REE.
        tipo: Filtra por tipo de norma: 'ley', 'rdl', 'rd', 'om', 'circular'.

    Returns:
        JSON con las normas encontradas.
    """
    resultados = []
    query_lower = query.lower()
    for norma in NORMATIVA_NACIONAL:
        if tipo and norma.get("type") != tipo:
            continue
        if query_lower:
            texto = (
                norma.get("title", "") + " " +
                norma.get("summary", "") + " " +
                norma.get("impactoREE", "")
            ).lower()
            if not any(word in texto for word in query_lower.split()):
                continue
        # Excluir el HTML del detalle en resultados de búsqueda
        resultado = {k: v for k, v in norma.items() if k != "detail"}
        resultados.append(resultado)

    if not resultados:
        return json.dumps({"mensaje": "No se encontraron normas con los criterios indicados.", "total": 0})
    return json.dumps({"total": len(resultados), "normas": resultados}, ensure_ascii=False, indent=2)


def obtener_detalle_norma(id_norma: str) -> str:
    """
    Obtiene el detalle completo de una norma por su ID.

    Args:
        id_norma: Identificador de la norma (ej: 'LSE-24-2013', 'RDL-7-2026').

    Returns:
        JSON con todos los campos de la norma incluyendo el detalle HTML.
    """
    todas = NORMATIVA_NACIONAL + NORMATIVA_EUROPEA
    for norma in todas:
        if norma.get("id") == id_norma:
            # Limpiar HTML del detalle para presentación limpia
            detail_html = norma.get("detail", "")
            detail_texto = re.sub(r"<[^>]+>", " ", detail_html).strip()
            result = {**norma, "detail_texto": detail_texto}
            return json.dumps(result, ensure_ascii=False, indent=2)
    return json.dumps({"error": f"Norma con ID '{id_norma}' no encontrada."})


def buscar_normativa_europea(query: str = "", tipo: str = "") -> str:
    """
    Busca en la normativa europea (directivas, reglamentos, códigos de red).

    Args:
        query: Texto libre para buscar en título, resumen o impacto REE.
        tipo: Filtra por tipo: 'directiva', 'reglamento', 'codigo_red'.

    Returns:
        JSON con las normas europeas encontradas.
    """
    resultados = []
    query_lower = query.lower()
    for norma in NORMATIVA_EUROPEA:
        if tipo and norma.get("type") != tipo:
            continue
        if query_lower:
            texto = (
                norma.get("title", "") + " " +
                norma.get("summary", "") + " " +
                norma.get("impactoREE", "")
            ).lower()
            if not any(word in texto for word in query_lower.split()):
                continue
        resultado = {k: v for k, v in norma.items() if k != "detail"}
        resultados.append(resultado)

    if not resultados:
        return json.dumps({"mensaje": "No se encontraron normas europeas.", "total": 0})
    return json.dumps({"total": len(resultados), "normas": resultados}, ensure_ascii=False, indent=2)


def consultar_consultas_publicas(estado: str = "", organismo: str = "") -> str:
    """
    Lista las consultas públicas regulatorias activas, cerradas o próximas.

    Args:
        estado: Filtra por estado: 'open', 'closed', 'upcoming'.
        organismo: Filtra por organismo: 'CNMC', 'MITECO', 'ACER', 'Comisión Europea'.

    Returns:
        JSON con las consultas encontradas y sus plazos.
    """
    hoy = date.today().isoformat()
    resultados = []

    for consulta in CONSULTAS_PUBLICAS:
        if estado and consulta.get("estado") != estado:
            continue
        if organismo and organismo.lower() not in consulta.get("organismo", "").lower():
            continue

        # Calcular días restantes para consultas abiertas
        enriquecida = dict(consulta)
        if consulta.get("estado") == "open" and consulta.get("fecha_cierre"):
            from datetime import datetime
            dias = (datetime.fromisoformat(consulta["fecha_cierre"]) -
                    datetime.fromisoformat(hoy)).days
            enriquecida["dias_restantes"] = max(0, dias)

        resultados.append(enriquecida)

    if not resultados:
        return json.dumps({"mensaje": "No se encontraron consultas con esos criterios.", "total": 0})
    return json.dumps({"total": len(resultados), "consultas": resultados}, ensure_ascii=False, indent=2)


def benchmark_pais(topico: str, pais: str = "") -> str:
    """
    Consulta el benchmark europeo comparativo entre países para un tema regulatorio.

    Args:
        topico: Tema a comparar. Opciones: 'acceso-conexion', 'retribucion-tso',
                'apoyo-renovables', 'almacenamiento', 'hidrogeno-verde'.
        pais: Si se especifica, devuelve solo la información de ese país.
               Países disponibles: España, Francia, Alemania, Italia, Reino Unido, Portugal, Países Bajos.

    Returns:
        JSON con la comparativa del tema solicitado.
    """
    topicos = BENCHMARK_EUROPEO.get("topicos", [])

    # Buscar el tópico (flexible: por ID o por nombre parcial)
    topico_encontrado = None
    for t in topicos:
        if t["id"] == topico or topico.lower() in t["nombre"].lower():
            topico_encontrado = t
            break

    if not topico_encontrado:
        ids_disponibles = [t["id"] for t in topicos]
        return json.dumps({
            "error": f"Tópico '{topico}' no encontrado.",
            "topicos_disponibles": ids_disponibles
        })

    if pais:
        paises_data = topico_encontrado.get("paises", {})
        # Búsqueda flexible de país
        pais_encontrado = None
        for p in paises_data:
            if pais.lower() in p.lower():
                pais_encontrado = p
                break
        if pais_encontrado:
            return json.dumps({
                "topico": topico_encontrado["nombre"],
                "pais": pais_encontrado,
                "datos": paises_data[pais_encontrado]
            }, ensure_ascii=False, indent=2)
        return json.dumps({"error": f"País '{pais}' no encontrado en el benchmark."})

    return json.dumps(topico_encontrado, ensure_ascii=False, indent=2)


def resumen_estado_regulatorio() -> str:
    """
    Genera un resumen ejecutivo del estado regulatorio actual para REE/Red Eléctrica.
    Incluye estadísticas de normativa, consultas abiertas y cambios recientes.

    Returns:
        JSON con el resumen del estado regulatorio.
    """
    normas_nuevas_nac = [n for n in NORMATIVA_NACIONAL if n.get("tag") == "new"]
    normas_modificadas_nac = [n for n in NORMATIVA_NACIONAL if n.get("tag") == "modified"]
    normas_nuevas_eu = [n for n in NORMATIVA_EUROPEA if n.get("tag") in ("new", "eu")]
    consultas_abiertas = [c for c in CONSULTAS_PUBLICAS if c.get("estado") == "open"]
    consultas_proximas = [c for c in CONSULTAS_PUBLICAS if c.get("estado") == "upcoming"]

    resumen = {
        "fecha_consulta": date.today().isoformat(),
        "normativa_nacional": {
            "total": len(NORMATIVA_NACIONAL),
            "nuevas": len(normas_nuevas_nac),
            "modificadas": len(normas_modificadas_nac),
            "ultimas_novedades": [
                {"id": n["id"], "titulo": n["title"], "tag": n["tag"]}
                for n in (normas_nuevas_nac + normas_modificadas_nac)[:5]
            ]
        },
        "normativa_europea": {
            "total": len(NORMATIVA_EUROPEA),
            "activas": len(normas_nuevas_eu),
        },
        "consultas_publicas": {
            "abiertas": len(consultas_abiertas),
            "proximas": len(consultas_proximas),
            "detalle_abiertas": [
                {
                    "titulo": c["titulo"],
                    "organismo": c["organismo"],
                    "fecha_cierre": c.get("fecha_cierre")
                }
                for c in consultas_abiertas
            ]
        },
        "alertas_regulatorias": [
            "TRF fijada en 6,58% para 2026-2031 (Circular CNMC 2/2024)",
            "Plan Resiliencia Red: 7.500M€ inversión 2025-2030",
            "RDL 7/2026: autoconsumo 5km y gestor de autoconsumo - adaptaciones técnicas requeridas",
            "NIS2: REE como entidad esencial - auditoría ciberseguridad obligatoria",
            "Reforma mercado UE (Reg. 2024/1747): CfD y mecanismo de capacidad pendientes"
        ]
    }

    return json.dumps(resumen, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# Definición de herramientas para la API
# ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "buscar_normativa_nacional",
        "description": (
            "Busca en la base de datos de normativa nacional española del sector eléctrico: "
            "leyes, reales decretos-ley (RDL), reales decretos (RD), órdenes ministeriales (OM) "
            "y circulares CNMC. Especialmente relevante para conocer el marco regulatorio de REE."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto libre para buscar en títulos, resúmenes e impacto REE. Ej: 'retribución transporte', 'almacenamiento', 'acceso red'."
                },
                "tipo": {
                    "type": "string",
                    "enum": ["ley", "rdl", "rd", "om", "circular"],
                    "description": "Filtrar por tipo de norma (opcional)."
                }
            }
        }
    },
    {
        "name": "obtener_detalle_norma",
        "description": (
            "Obtiene el detalle completo de una norma específica por su ID único. "
            "Usar cuando se quiere profundizar en el contenido de una norma ya identificada."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id_norma": {
                    "type": "string",
                    "description": "ID único de la norma. Ej: 'LSE-24-2013', 'RDL-7-2026', 'DIR-2019-944', 'CIRC-CNMC-2-2024'."
                }
            },
            "required": ["id_norma"]
        }
    },
    {
        "name": "buscar_normativa_europea",
        "description": (
            "Busca en la normativa europea aplicable al sector eléctrico español: "
            "directivas UE, reglamentos UE (directamente aplicables) y códigos de red europeos. "
            "Incluye CEP, SO GL, CACM, RfG, RED III, NIS2 y las reformas más recientes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto libre para buscar. Ej: 'mercado interior', 'ciberseguridad', 'renovables', 'ENTSO-E'."
                },
                "tipo": {
                    "type": "string",
                    "enum": ["directiva", "reglamento", "codigo_red"],
                    "description": "Filtrar por tipo de instrumento europeo (opcional)."
                }
            }
        }
    },
    {
        "name": "consultar_consultas_publicas",
        "description": (
            "Lista y filtra las consultas públicas regulatorias en curso, cerradas o próximas "
            "de organismos como CNMC, MITECO, ACER y Comisión Europea que afectan al sector eléctrico y a REE."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "estado": {
                    "type": "string",
                    "enum": ["open", "closed", "upcoming"],
                    "description": "Filtrar por estado de la consulta: 'open' (abierta), 'closed' (cerrada), 'upcoming' (próxima)."
                },
                "organismo": {
                    "type": "string",
                    "description": "Filtrar por organismo regulador. Ej: 'CNMC', 'MITECO', 'ACER', 'Comisión Europea'."
                }
            }
        }
    },
    {
        "name": "benchmark_pais",
        "description": (
            "Consulta el benchmark regulatorio europeo comparativo entre países "
            "para temas como acceso a la red, retribución del TSO (WACC), apoyo a renovables, "
            "almacenamiento e hidrógeno verde. Permite comparar España con otros países europeos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topico": {
                    "type": "string",
                    "enum": ["acceso-conexion", "retribucion-tso", "apoyo-renovables", "almacenamiento", "hidrogeno-verde"],
                    "description": "Tema regulatorio a comparar entre países europeos."
                },
                "pais": {
                    "type": "string",
                    "description": "Si se especifica, devuelve solo los datos de ese país. Opciones: España, Francia, Alemania, Italia, Reino Unido, Portugal, Países Bajos."
                }
            },
            "required": ["topico"]
        }
    },
    {
        "name": "resumen_estado_regulatorio",
        "description": (
            "Genera un resumen ejecutivo del estado regulatorio actual para REE/Red Eléctrica: "
            "novedades normativas, consultas abiertas y alertas regulatorias prioritarias."
        ),
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]

# ──────────────────────────────────────────────
# Ejecución de herramientas
# ──────────────────────────────────────────────

TOOL_FUNCTIONS = {
    "buscar_normativa_nacional": lambda args: buscar_normativa_nacional(**args),
    "obtener_detalle_norma": lambda args: obtener_detalle_norma(**args),
    "buscar_normativa_europea": lambda args: buscar_normativa_europea(**args),
    "consultar_consultas_publicas": lambda args: consultar_consultas_publicas(**args),
    "benchmark_pais": lambda args: benchmark_pais(**args),
    "resumen_estado_regulatorio": lambda args: resumen_estado_regulatorio(),
}


def ejecutar_tool(nombre: str, argumentos: dict) -> str:
    func = TOOL_FUNCTIONS.get(nombre)
    if not func:
        return json.dumps({"error": f"Herramienta '{nombre}' no encontrada."})
    try:
        return func(argumentos)
    except Exception as e:
        return json.dumps({"error": f"Error ejecutando '{nombre}': {str(e)}"})


# ──────────────────────────────────────────────
# Prompt del sistema
# ──────────────────────────────────────────────

SYSTEM_PROMPT = f"""Eres el Agente Regulatorio de REE (Red Eléctrica de España), un asistente experto en el marco regulatorio del sector eléctrico español y europeo.

Tu función es proporcionar análisis precisos, actualizados y estratégicamente relevantes sobre:
- Normativa nacional (LSE, RDL, RD, OM, Circulares CNMC)
- Normativa europea (Directivas UE, Reglamentos UE de aplicación directa, Códigos de Red ENTSO-E)
- Consultas públicas en curso de CNMC, MITECO, ACER y Comisión Europea
- Benchmarking europeo de marcos regulatorios comparados

Perfil del usuario: Equipo de Asuntos Regulatorios de REE. Expertos en el sector con necesidad de información técnica detallada, análisis de impacto en la actividad de REE y posicionamiento estratégico.

Instrucciones de respuesta:
1. Usa siempre las herramientas disponibles para consultar la base de datos regulatoria antes de responder.
2. Destaca el **impacto específico en REE** de cualquier norma o desarrollo regulatorio.
3. Cuando identifiques consultas públicas abiertas, indica los plazos y recomienda la participación si es estratégicamente relevante.
4. Para el benchmark europeo, señala las best practices transferibles a España.
5. Sé preciso con las referencias normativas (número, año, artículo si aplica).
6. Si una pregunta implica incertidumbre regulatoria, identifícala explícitamente.
7. Responde siempre en español.

Fecha de referencia de los datos: 9 de abril de 2026.
"""

# ──────────────────────────────────────────────
# Bucle de conversación
# ──────────────────────────────────────────────

def cargar_api_key() -> str:
    """Carga la API key desde variable de entorno o archivo .env."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        print("❌ Error: No se encontró ANTHROPIC_API_KEY.")
        print("   Crea un archivo .env con: ANTHROPIC_API_KEY=tu_clave")
        print("   O define la variable de entorno ANTHROPIC_API_KEY.")
        sys.exit(1)
    return api_key


def agente_loop():
    """Bucle principal del agente regulatorio."""
    api_key = cargar_api_key()
    client = anthropic.Anthropic(api_key=api_key)

    print("=" * 65)
    print("  AGENTE REGULATORIO REE — Sector Eléctrico Español")
    print("  Powered by Claude Opus 4.6 con Adaptive Thinking")
    print("=" * 65)
    print("  Base de datos: Normativa Nacional · UE · Consultas · Benchmark")
    print("  Escribe 'salir' o 'exit' para terminar.")
    print("=" * 65)
    print()

    messages = []

    while True:
        # Entrada del usuario
        try:
            user_input = input("📋 Tu consulta: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nSesión terminada.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("salir", "exit", "quit"):
            print("Sesión terminada.")
            break

        messages.append({"role": "user", "content": user_input})

        # Bucle agentico: llamadas a herramientas hasta respuesta final
        while True:
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=8192,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # Añadir respuesta del asistente al historial
            messages.append({"role": "assistant", "content": response.content})

            # Si terminó (sin más tool calls)
            if response.stop_reason == "end_turn":
                # Mostrar respuesta de texto
                for block in response.content:
                    if block.type == "text":
                        print(f"\n🤖 Agente:\n{block.text}\n")
                break

            # Procesar tool calls
            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        print(f"   🔍 Consultando: {block.name}({json.dumps(block.input, ensure_ascii=False)})")
                        resultado = ejecutar_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": resultado
                        })

                messages.append({"role": "user", "content": tool_results})
                # Continuar el bucle para que Claude procese los resultados
                continue

            # Otro stop_reason inesperado
            break

        print("-" * 65)


# ──────────────────────────────────────────────
# Punto de entrada
# ──────────────────────────────────────────────

if __name__ == "__main__":
    agente_loop()
