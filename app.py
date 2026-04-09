"""
Agente Regulatorio REE — Servidor Web
======================================
FastAPI + Server-Sent Events para respuestas en streaming.
Desplegable en Railway, Render o cualquier plataforma PaaS.
"""

import json
import os
import re
import asyncio
from pathlib import Path
from datetime import date
from typing import AsyncGenerator

import anthropic
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# ──────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────

app = FastAPI(title="Agente Regulatorio REE", docs_url=None, redoc_url=None)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ──────────────────────────────────────────────
# Datos regulatorios
# ──────────────────────────────────────────────

DATA_DIR = BASE_DIR / "data"


def _load(filename: str):
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


NORMATIVA_NACIONAL = _load("normativa_nacional.json")
NORMATIVA_EUROPEA = _load("normativa_europea.json")
CONSULTAS_PUBLICAS = _load("consultas_publicas.json")
BENCHMARK_EUROPEO = _load("benchmark_europeo.json")

# ──────────────────────────────────────────────
# Herramientas (misma lógica que en CLI)
# ──────────────────────────────────────────────

def buscar_normativa_nacional(query: str = "", tipo: str = "") -> str:
    resultados = []
    query_lower = query.lower()
    for norma in NORMATIVA_NACIONAL:
        if tipo and norma.get("type") != tipo:
            continue
        if query_lower:
            texto = (norma.get("title","") + " " + norma.get("summary","") + " " + norma.get("impactoREE","")).lower()
            if not any(w in texto for w in query_lower.split()):
                continue
        resultados.append({k: v for k, v in norma.items() if k != "detail"})
    if not resultados:
        return json.dumps({"mensaje": "No se encontraron normas.", "total": 0})
    return json.dumps({"total": len(resultados), "normas": resultados}, ensure_ascii=False)


def obtener_detalle_norma(id_norma: str) -> str:
    for norma in NORMATIVA_NACIONAL + NORMATIVA_EUROPEA:
        if norma.get("id") == id_norma:
            detail_texto = re.sub(r"<[^>]+>", " ", norma.get("detail", "")).strip()
            return json.dumps({**norma, "detail_texto": detail_texto}, ensure_ascii=False)
    return json.dumps({"error": f"Norma '{id_norma}' no encontrada."})


def buscar_normativa_europea(query: str = "", tipo: str = "") -> str:
    resultados = []
    query_lower = query.lower()
    for norma in NORMATIVA_EUROPEA:
        if tipo and norma.get("type") != tipo:
            continue
        if query_lower:
            texto = (norma.get("title","") + " " + norma.get("summary","") + " " + norma.get("impactoREE","")).lower()
            if not any(w in texto for w in query_lower.split()):
                continue
        resultados.append({k: v for k, v in norma.items() if k != "detail"})
    if not resultados:
        return json.dumps({"mensaje": "No se encontraron normas europeas.", "total": 0})
    return json.dumps({"total": len(resultados), "normas": resultados}, ensure_ascii=False)


def consultar_consultas_publicas(estado: str = "", organismo: str = "") -> str:
    from datetime import datetime
    hoy = date.today().isoformat()
    resultados = []
    for c in CONSULTAS_PUBLICAS:
        if estado and c.get("estado") != estado:
            continue
        if organismo and organismo.lower() not in c.get("organismo","").lower():
            continue
        enriquecida = dict(c)
        if c.get("estado") == "open" and c.get("fecha_cierre"):
            dias = (datetime.fromisoformat(c["fecha_cierre"]) - datetime.fromisoformat(hoy)).days
            enriquecida["dias_restantes"] = max(0, dias)
        resultados.append(enriquecida)
    if not resultados:
        return json.dumps({"mensaje": "No se encontraron consultas.", "total": 0})
    return json.dumps({"total": len(resultados), "consultas": resultados}, ensure_ascii=False)


def benchmark_pais(topico: str, pais: str = "") -> str:
    for t in BENCHMARK_EUROPEO.get("topicos", []):
        if t["id"] == topico or topico.lower() in t["nombre"].lower():
            if pais:
                for p, datos in t["paises"].items():
                    if pais.lower() in p.lower():
                        return json.dumps({"topico": t["nombre"], "pais": p, "datos": datos}, ensure_ascii=False)
                return json.dumps({"error": f"País '{pais}' no encontrado."})
            return json.dumps(t, ensure_ascii=False)
    return json.dumps({"error": f"Tópico '{topico}' no encontrado.", "disponibles": [t["id"] for t in BENCHMARK_EUROPEO.get("topicos",[])]})


def resumen_estado_regulatorio() -> str:
    nuevas_nac = [n for n in NORMATIVA_NACIONAL if n.get("tag") == "new"]
    mod_nac = [n for n in NORMATIVA_NACIONAL if n.get("tag") == "modified"]
    abiertas = [c for c in CONSULTAS_PUBLICAS if c.get("estado") == "open"]
    proximas = [c for c in CONSULTAS_PUBLICAS if c.get("estado") == "upcoming"]
    return json.dumps({
        "fecha_consulta": date.today().isoformat(),
        "normativa_nacional": {"total": len(NORMATIVA_NACIONAL), "nuevas": len(nuevas_nac), "modificadas": len(mod_nac)},
        "normativa_europea": {"total": len(NORMATIVA_EUROPEA)},
        "consultas": {"abiertas": len(abiertas), "proximas": len(proximas),
                      "detalle": [{"titulo": c["titulo"], "organismo": c["organismo"], "cierre": c.get("fecha_cierre")} for c in abiertas]},
        "alertas": [
            "TRF 6,58% fijada para 2026-2031 (Circular CNMC 2/2024)",
            "Plan Resiliencia Red: 7.500M€ inversión 2025-2030",
            "RDL 7/2026: autoconsumo 5km — adaptaciones técnicas requeridas",
            "NIS2: REE como entidad esencial — auditoría ciberseguridad obligatoria",
            "Reforma mercado UE (Reg. 2024/1747): CfD y mecanismo capacidad pendientes",
        ]
    }, ensure_ascii=False)


TOOL_FUNCTIONS = {
    "buscar_normativa_nacional": lambda a: buscar_normativa_nacional(**a),
    "obtener_detalle_norma": lambda a: obtener_detalle_norma(**a),
    "buscar_normativa_europea": lambda a: buscar_normativa_europea(**a),
    "consultar_consultas_publicas": lambda a: consultar_consultas_publicas(**a),
    "benchmark_pais": lambda a: benchmark_pais(**a),
    "resumen_estado_regulatorio": lambda a: resumen_estado_regulatorio(),
}

TOOLS = [
    {"name": "buscar_normativa_nacional", "description": "Busca normativa nacional española del sector eléctrico (leyes, RDL, RD, OM, circulares CNMC).", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "tipo": {"type": "string", "enum": ["ley","rdl","rd","om","circular"]}}}},
    {"name": "obtener_detalle_norma", "description": "Obtiene el detalle completo de una norma por su ID.", "input_schema": {"type": "object", "properties": {"id_norma": {"type": "string"}}, "required": ["id_norma"]}},
    {"name": "buscar_normativa_europea", "description": "Busca directivas, reglamentos y códigos de red europeos aplicables al sector eléctrico español.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "tipo": {"type": "string", "enum": ["directiva","reglamento","codigo_red"]}}}},
    {"name": "consultar_consultas_publicas", "description": "Lista consultas públicas regulatorias de CNMC, MITECO, ACER y Comisión Europea.", "input_schema": {"type": "object", "properties": {"estado": {"type": "string", "enum": ["open","closed","upcoming"]}, "organismo": {"type": "string"}}}},
    {"name": "benchmark_pais", "description": "Benchmark regulatorio europeo comparativo entre países.", "input_schema": {"type": "object", "properties": {"topico": {"type": "string", "enum": ["acceso-conexion","retribucion-tso","apoyo-renovables","almacenamiento","hidrogeno-verde"]}, "pais": {"type": "string"}}, "required": ["topico"]}},
    {"name": "resumen_estado_regulatorio", "description": "Resumen ejecutivo del estado regulatorio actual para REE.", "input_schema": {"type": "object", "properties": {}}},
]

SYSTEM_PROMPT = """Eres el Agente Regulatorio de REE (Red Eléctrica de España). Experto en el marco regulatorio del sector eléctrico español y europeo.

Proporcionas análisis precisos sobre normativa nacional (LSE, RDL, RD, OM, Circulares CNMC), normativa europea (Directivas, Reglamentos, Códigos de Red), consultas públicas y benchmarking europeo.

Usuario: Equipo de Asuntos Regulatorios de REE. Necesitan información técnica detallada e impacto en la actividad de REE.

Instrucciones:
1. Usa siempre las herramientas disponibles antes de responder.
2. Destaca el impacto específico en REE de cualquier norma.
3. Señala los plazos de consultas públicas abiertas.
4. Para benchmark europeo, identifica best practices aplicables a España.
5. Usa formato Markdown en tus respuestas (negrita, listas, tablas).
6. Responde siempre en español.

Fecha de referencia: 9 de abril de 2026."""

# ──────────────────────────────────────────────
# Streaming del agente
# ──────────────────────────────────────────────

async def stream_agente(messages: list) -> AsyncGenerator[str, None]:
    """Ejecuta el bucle agentico y emite SSE con el texto generado."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        yield f"data: {json.dumps({'type': 'error', 'text': 'ANTHROPIC_API_KEY no configurada.'})}\n\n"
        return

    client = anthropic.Anthropic(api_key=api_key)

    # Bucle agentico: puede haber varias rondas de tool calls antes de la respuesta final
    while True:
        # Notificar que estamos pensando
        yield f"data: {json.dumps({'type': 'thinking'})}\n\n"
        await asyncio.sleep(0)

        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.messages.create(
                model="claude-opus-4-6",
                max_tokens=8192,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        )

        # Añadir respuesta al historial
        messages.append({"role": "assistant", "content": response.content})

        # Respuesta final de texto
        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    # Enviar el texto completo de una vez
                    yield f"data: {json.dumps({'type': 'text', 'text': block.text})}\n\n"
                    await asyncio.sleep(0)
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            break

        # Ejecución de herramientas
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    # Notificar qué herramienta se está usando
                    yield f"data: {json.dumps({'type': 'tool', 'name': block.name})}\n\n"
                    await asyncio.sleep(0)

                    resultado = TOOL_FUNCTIONS.get(block.name, lambda a: "{}")(block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": resultado
                    })

            messages.append({"role": "user", "content": tool_results})
            # Continuar el bucle para que Claude genere la respuesta final
            continue

        # Stop reason inesperado
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        break

# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    history: list = []


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/chat")
async def chat(req: ChatRequest):
    """Endpoint de chat con streaming SSE."""
    # Reconstruir historial de mensajes
    messages = []
    for turn in req.history:
        messages.append({"role": "user", "content": turn["user"]})
        messages.append({"role": "assistant", "content": turn["assistant"]})
    messages.append({"role": "user", "content": req.message})

    return StreamingResponse(
        stream_agente(messages),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/api/normativa")
async def api_normativa():
    """Devuelve toda la normativa (nacional + europea) en JSON."""
    return {
        "nacional": NORMATIVA_NACIONAL,
        "europea": NORMATIVA_EUROPEA,
    }


@app.get("/api/consultas")
async def api_consultas():
    return CONSULTAS_PUBLICAS


@app.get("/api/benchmark")
async def api_benchmark():
    return BENCHMARK_EUROPEO


@app.get("/health")
async def health():
    return {"status": "ok", "date": date.today().isoformat()}


# ──────────────────────────────────────────────
# Arranque local
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
