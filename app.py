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
import hashlib
from pathlib import Path
from datetime import date, datetime
from typing import AsyncGenerator

import anthropic
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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
# Endpoints
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/normativa")
async def api_normativa():
    """Devuelve toda la normativa (nacional + europea) en JSON."""
    return {
        "nacional": NORMATIVA_NACIONAL,
        "europea": NORMATIVA_EUROPEA,
    }


@app.get("/api/consultas")
async def api_consultas():
    # Siempre lee del disco para reflejar actualizaciones recientes
    return _load("consultas_publicas.json")


# ──────────────────────────────────────────────
# Actualización de consultas (SSE streaming)
# ──────────────────────────────────────────────

FUENTES_CONSULTA = [
    {
        "organismo": "CNMC",
        "url": "https://www.cnmc.es/participa/consultas-publicas",
        "descripcion": "Consultas públicas energía — CNMC",
    },
    {
        "organismo": "MITECO",
        "url": "https://www.miteco.gob.es/es/energia/participacion.html",
        "descripcion": "Participación pública energía — MITECO",
    },
    {
        "organismo": "OS (Red Eléctrica)",
        "url": "https://www.ree.es/es/clientes/consultas-publicas",
        "descripcion": "Tablón consultas OS — Red Eléctrica",
    },
    {
        "organismo": "Comisión Europea",
        "url": "https://energy.ec.europa.eu/consultations_en",
        "descripcion": "Consultas energía — Comisión Europea",
    },
]

PROMPT_EXTRACCION = """Eres un extractor de datos regulatorios. Analiza el contenido de esta página web y extrae TODAS las consultas públicas del sector eléctrico que encuentres.

Para cada consulta devuelve un objeto JSON con estos campos exactos (usa null si no está disponible):
- id: string identificador único (organismo_año_num, ej: "CNMC-2026-01")
- titulo: string título completo de la consulta
- organismo: string nombre del organismo ({organismo})
- estado: "open" | "closed" | "upcoming"
- fecha_publicacion: string ISO "YYYY-MM-DD" o null
- fecha_cierre: string ISO "YYYY-MM-DD" o null
- resumen: string descripción breve (máx 300 chars)
- enlace: string URL directa a la consulta o null
- expediente: string número de expediente o null
- relevanciaREE: string impacto para Red Eléctrica o null

Responde ÚNICAMENTE con un array JSON válido, sin texto adicional, sin markdown, sin explicaciones.
Si no encuentras consultas del sector eléctrico, responde con [].
Solo incluye consultas relacionadas con electricidad, red eléctrica, transporte, distribución, renovables, almacenamiento o mercado eléctrico. Excluye gas, agua u otros sectores."""


def _id_consulta(titulo: str, organismo: str) -> str:
    """Genera un ID único reproducible a partir del título."""
    raw = f"{organismo}_{titulo}".lower()[:80]
    return hashlib.md5(raw.encode()).hexdigest()[:10]


async def stream_actualizar_consultas() -> AsyncGenerator[str, None]:
    """Visita cada fuente oficial, extrae consultas con Claude y actualiza el JSON."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        yield f"data: {json.dumps({'type':'error','msg':'ANTHROPIC_API_KEY no configurada.'})}\n\n"
        return

    client = anthropic.Anthropic(api_key=api_key)

    nuevas_total: list[dict] = []
    errores: list[str] = []

    for fuente in FUENTES_CONSULTA:
        org = fuente["organismo"]
        url = fuente["url"]

        yield f"data: {json.dumps({'type':'progreso','msg':f'Consultando {org}...','org':org})}\n\n"
        await asyncio.sleep(0)

        try:
            # Claude fetch la URL y extrae las consultas
            prompt_org = PROMPT_EXTRACCION.replace("{organismo}", org)

            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda u=url, p=prompt_org: client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=4096,
                    tools=[{"type": "web_fetch_20260209", "name": "web_fetch"}],
                    messages=[{
                        "role": "user",
                        "content": f"Visita esta URL y extrae las consultas públicas del sector eléctrico según las instrucciones.\n\nURL: {u}\n\n{p}"
                    }]
                )
            )

            # Extraer el texto final de la respuesta
            texto = ""
            for block in response.content:
                if hasattr(block, "text"):
                    texto += block.text

            # Parsear el JSON devuelto por Claude
            texto = texto.strip()
            # Limpiar posible markdown fence
            texto = re.sub(r"^```(?:json)?\s*", "", texto)
            texto = re.sub(r"\s*```$", "", texto)

            if texto and texto.startswith("["):
                consultas_raw: list[dict] = json.loads(texto)
                # Normalizar y añadir ID si falta
                for c in consultas_raw:
                    if not c.get("id"):
                        c["id"] = _id_consulta(c.get("titulo",""), org)
                    c["organismo"] = org  # forzar organismo correcto
                    # Asegurar campos mínimos
                    for campo in ["titulo","estado","fecha_publicacion","fecha_cierre",
                                   "resumen","enlace","expediente","relevanciaREE"]:
                        c.setdefault(campo, None)

                nuevas_total.extend(consultas_raw)
                yield f"data: {json.dumps({'type':'progreso','msg':f'{org}: {len(consultas_raw)} consulta(s) encontrada(s)','org':org,'n':len(consultas_raw)})}\n\n"
            else:
                yield f"data: {json.dumps({'type':'progreso','msg':f'{org}: sin consultas eléctricas detectadas','org':org,'n':0})}\n\n"

        except Exception as e:
            errores.append(f"{org}: {str(e)[:120]}")
            yield f"data: {json.dumps({'type':'progreso','msg':f'{org}: error — {str(e)[:80]}','org':org,'error':True})}\n\n"

        await asyncio.sleep(0.1)

    # ── Combinar con las existentes, evitando duplicados por título ──
    existentes: list[dict] = _load("consultas_publicas.json")
    titulos_existentes = {c.get("titulo","").lower().strip() for c in existentes}
    ids_existentes = {c.get("id","") for c in existentes}

    realmente_nuevas = []
    for c in nuevas_total:
        titulo_norm = (c.get("titulo") or "").lower().strip()
        if titulo_norm and titulo_norm not in titulos_existentes and c.get("id") not in ids_existentes:
            realmente_nuevas.append(c)
            titulos_existentes.add(titulo_norm)

    # Marcar cerradas las que ya pasaron su fecha de cierre
    hoy = date.today().isoformat()
    actualizadas = list(existentes)
    for c in actualizadas:
        if c.get("estado") == "open" and c.get("fecha_cierre") and c["fecha_cierre"] < hoy:
            c["estado"] = "closed"

    # Añadir las nuevas al principio
    actualizadas = realmente_nuevas + actualizadas

    # Guardar
    consultas_path = DATA_DIR / "consultas_publicas.json"
    with open(consultas_path, "w", encoding="utf-8") as f:
        json.dump(actualizadas, f, ensure_ascii=False, indent=2)

    # Actualizar variable global en memoria
    global CONSULTAS_PUBLICAS
    CONSULTAS_PUBLICAS = actualizadas

    resumen = {
        "type": "completado",
        "nuevas": len(realmente_nuevas),
        "total": len(actualizadas),
        "errores": errores,
        "fecha_actualizacion": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "msg": f"Actualización completada: {len(realmente_nuevas)} nueva(s) consulta(s) añadida(s). Total: {len(actualizadas)}."
    }
    yield f"data: {json.dumps(resumen)}\n\n"


@app.post("/api/actualizar-consultas")
async def actualizar_consultas():
    """Lanza la actualización de consultas con SSE para seguimiento en tiempo real."""
    return StreamingResponse(
        stream_actualizar_consultas(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/api/benchmark")
async def api_benchmark():
    return BENCHMARK_EUROPEO


# ──────────────────────────────────────────────
# Análisis IA de normativa (SSE streaming)
# ──────────────────────────────────────────────

PROMPT_ANALISIS_NORMATIVA = """Eres un experto jurídico en regulación del sistema eléctrico español con profundo conocimiento técnico.

Analiza la normativa cuyo texto puedes obtener mediante la herramienta de búsqueda web en la URL indicada.

Identifica ÚNICAMENTE los artículos o disposiciones con relevancia para estos cuatro temas:
1. sector_electrico — sector eléctrico en general (generación, transporte, distribución, mercado)
2. acceso_conexion — acceso y conexión a redes eléctricas (solicitudes, permisos, nudos, capacidad)
3. control_tension — control de tensión y calidad del suministro (reactiva, estabilidad, procedimientos de operación)
4. sf6 — SF6 y gases fluorados en equipos eléctricos de alta tensión (GIS, interruptores, transformadores)

Para cada artículo relevante determina:
- Si es NUEVO (se introduce ex novo) o MODIFICADO (modifica texto previo de otra norma) o DEROGADO
- Si es MODIFICADO: qué ha cambiado exactamente vs la versión anterior
- Implicaciones concretas para el Operador del Sistema (Red Eléctrica / REE-OS)
- Implicaciones concretas para los transportistas del sistema eléctrico

Responde ÚNICAMENTE con JSON válido (sin markdown, sin explicaciones):
{
  "resumen_ejecutivo": "string: 2-3 frases sobre objeto y alcance de la norma",
  "ambito": "string: ámbito de aplicación",
  "implicaciones_globales_os": "string: resumen consolidado para el OS",
  "implicaciones_globales_transportista": "string: resumen consolidado para el transportista",
  "articulos": [
    {
      "numero": "string: 'Art. 5' o 'Disposición transitoria 2ª'",
      "titulo": "string: epígrafe del artículo",
      "estado": "nuevo|modificado|derogado",
      "texto": "string: resumen del contenido (máx 250 chars)",
      "cambios": "string|null: qué ha cambiado (solo si modificado)",
      "normativa_referencia": "string|null: si el contenido procede de o modifica otra norma previa, indica cuál (p.ej. 'PO 3.1, aprobado por Resolución de 6 de octubre de 2000'). Solo si aplica.",
      "temas": ["sector_electrico","acceso_conexion","control_tension","sf6"],
      "relevancia": "alta|media|baja",
      "implicaciones_os": "string",
      "implicaciones_transportista": "string"
    }
  ]
}"""


async def stream_analizar_normativa(norm_id: str, url: str, titulo: str) -> AsyncGenerator[str, None]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        yield f"data: {json.dumps({'type':'error','msg':'ANTHROPIC_API_KEY no configurada.'})}\n\n"
        return

    client = anthropic.Anthropic(api_key=api_key)

    yield f"data: {json.dumps({'type':'progreso','msg':'Obteniendo texto completo de la normativa desde BOE…'})}\n\n"
    await asyncio.sleep(0)

    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.messages.create(
                model="claude-opus-4-6",
                max_tokens=8192,
                tools=[{"type": "web_fetch_20260209", "name": "web_fetch"}],
                messages=[{
                    "role": "user",
                    "content": (
                        f"Visita esta URL del BOE, lee el texto completo de la norma y analízala según las instrucciones.\n\n"
                        f"URL: {url}\n"
                        f"Título: {titulo}\n\n"
                        f"{PROMPT_ANALISIS_NORMATIVA}"
                    )
                }]
            )
        )

        yield f"data: {json.dumps({'type':'progreso','msg':'Procesando análisis artículo por artículo…'})}\n\n"
        await asyncio.sleep(0)

        texto = ""
        for block in response.content:
            if hasattr(block, "text"):
                texto += block.text

        texto = texto.strip()
        texto = re.sub(r"^```(?:json)?\s*", "", texto)
        texto = re.sub(r"\s*```$", "", texto)

        if texto and texto.startswith("{"):
            analisis = json.loads(texto)
            analisis["type"] = "resultado"
            analisis["norm_id"] = norm_id
            yield f"data: {json.dumps(analisis)}\n\n"
        else:
            yield f"data: {json.dumps({'type':'error','msg':'Respuesta inesperada del modelo: ' + texto[:200]})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type':'error','msg':str(e)[:250]})}\n\n"


@app.post("/api/analizar-normativa")
async def analizar_normativa_endpoint(request: Request):
    """Analiza una normativa con IA y devuelve artículos relevantes via SSE."""
    body = await request.json()
    return StreamingResponse(
        stream_analizar_normativa(body["id"], body["url"], body["titulo"]),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


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
