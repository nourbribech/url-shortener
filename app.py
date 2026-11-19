import json
import logging
import os
import secrets
import string
import time
import uuid

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, HttpUrl

# ---- Configuration: read from the environment (12-factor) ----
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
'''I don’t hardcode settings. In Docker or Kubernetes I change behavior with env vars, not by rebuilding the image (the 12-factor idea). I give it a sensible default and call .upper() so info still works.'''

# ---- Structured logging: one JSON object per line ----
class JsonFormatter(logging.Formatter): #Formatter instances are used to convert a LogRecord to text.
    def format(self, record): #Format the specified record as dict instead of text (overrides the original format meth)
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
            **getattr(record, "fields", {}), # spreads the key and values of the dict in  record.fields and adds it to the entry dict
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
log = logging.getLogger("url-shortener")
log.addHandler(handler)
log.setLevel(LOG_LEVEL)
log.propagate = False

# ---- Metrics ---- prometheus
REQUESTS = Counter("http_requests_total", "Total HTTP requests",#how much traffic, and how many errors?
                   ["method", "path", "status"])
LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["path"])#how slow are we
SHORTENED = Counter("urls_shortened_total", "Total URLs shortened")#counts URLs created

app = FastAPI(title="URL Shortener")
URLS: dict[str, dict] = {}  # in-memory storage, lost on restart
ALPHABET = string.ascii_lowercase + string.digits

# ---- Tracing: only enabled if an OTLP endpoint is configured ----
if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)

#middleware for observability in one place 
@app.middleware("http")  #this function should run for every HTTP request
async def observe(request: Request, call_next):
    """Runs around every request: times it, counts it, logs it."""
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request) #request = the incoming HTTP requestcall next:the function that passes the request to the next layer, eventually reaching your endpointresponse = what your endpoint returns
        status = response.status_code
        response.headers["x-request-id"] = request_id
        return response
    except Exception:
        log.exception("unhandled error", extra={"fields": {"request_id": request_id}})
        raise
    finally:
        duration = time.perf_counter() - start
        route = request.scope.get("route")
        path = route.path if route else "unmatched"
        REQUESTS.labels(request.method, path, str(status)).inc()
        LATENCY.labels(path).observe(duration)
        log.info("request", extra={"fields": {
            "request_id": request_id, "method": request.method,
            "path": request.url.path, "status": status,
            "duration_ms": round(duration * 1000, 2)}})

class ShortenIn(BaseModel):
    url: HttpUrl


def new_code(length: int = 6) -> str: #builds a 6-character random string and loops until it finds one not already in URLS
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if code not in URLS:
            return code


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/stats/{code}")
def stats(code: str):
    entry = URLS.get(code)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown code")
    return {"code": code, "url": entry["url"], "clicks": entry["clicks"]}


@app.post("/shorten", status_code=201)
def shorten(payload: ShortenIn):
    code = new_code()
    URLS[code] = {"url": str(payload.url), "clicks": 0}
    SHORTENED.inc()
    return {"code": code}


# NOTE: this catch-all route must stay last
@app.get("/{code}")
def follow(code: str):
    entry = URLS.get(code)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown code")
    entry["clicks"] += 1
    return RedirectResponse(entry["url"], status_code=307)