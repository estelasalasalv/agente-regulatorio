# Agente Regulatorio REE

Asistente de inteligencia regulatoria para el sector eléctrico español, basado en Claude Opus 4.6.

## Características

- **Chat con IA** — Consultas en lenguaje natural sobre normativa y regulación
- **Normativa Nacional** — LSE, RDL, RD, Órdenes Ministeriales, Circulares CNMC
- **Normativa Europea** — Directivas UE, Reglamentos, Códigos de Red ENTSO-E
- **Consultas Públicas** — CNMC, MITECO, ACER con seguimiento de plazos
- **Benchmark Europeo** — Comparativa regulatoria entre 7 países (WACC, acceso red, renovables, almacenamiento, H2)

## Despliegue en Railway (recomendado)

1. Sube este repositorio a GitHub
2. Ve a [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Selecciona el repositorio
4. En **Variables de entorno**, añade:
   ```
   ANTHROPIC_API_KEY = tu_clave_api
   ```
5. Railway desplegará automáticamente y te dará una URL pública

## Ejecución local

```bash
pip install -r requirements.txt
cp .env.example .env          # Editar con tu API key
uvicorn app:app --reload
# Abrir http://localhost:8000
```

## Estructura

```
AgenteEstela/
├── app.py                    # Servidor FastAPI
├── agente_regulatorio.py     # Versión CLI (opcional)
├── templates/index.html      # Interfaz web
├── data/
│   ├── normativa_nacional.json
│   ├── normativa_europea.json
│   ├── consultas_publicas.json
│   └── benchmark_europeo.json
├── Procfile                  # Para Railway/Heroku
├── railway.json              # Config Railway
└── requirements.txt
```
