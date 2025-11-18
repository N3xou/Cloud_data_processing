from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import httpx
import asyncio
import logging
import time

from db import init_db, get_db
from models import Prediction, ExternalApiCall
import uuid
import json
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, REGISTRY
from fastapi.responses import Response

# OpenTelemetry imports
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.trace import Status, StatusCode
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# HF Space API endpoint
HF_SPACE_URL = "https://iYami-cloud.hf.space"
PREDICT_ENDPOINT = f"{HF_SPACE_URL}/api/predict"

# External API endpoint (configurable via env var)
EXTERNAL_API_URL = os.getenv("EXTERNAL_API_URL", "https://jsonplaceholder.typicode.com/posts/1") #"http://api:7860/mock-api") # Use local mock
HTTP_VERSION = os.getenv("HTTP_VERSION", "1.1")  # "1.1" or "2"
OUT_PROTOCOL = os.getenv("OUT_PROTOCOL", "h1")  # "h1" or "h2" for testing

# HTTP Client Configuration (all configurable via env vars)
OUT_MAX_CONNECTIONS = int(os.getenv("OUT_MAX_CONNECTIONS", "50"))  # Default: 50
OUT_MAX_KEEPALIVE = int(os.getenv("OUT_MAX_KEEPALIVE", "20"))  # Default: 20
OUT_KEEPALIVE_EXPIRY = float(os.getenv("OUT_KEEPALIVE_EXPIRY", "30.0"))  # Default: 30s
OUT_READ_TIMEOUT = float(os.getenv("OUT_READ_TIMEOUT", "180.0"))  # Default: 180s
OUT_CONNECT_TIMEOUT = float(os.getenv("OUT_CONNECT_TIMEOUT", "5.0"))  # Default: 5s
OUT_POOL_TIMEOUT_MS = int(os.getenv("OUT_POOL_TIMEOUT_MS", "0"))  # Default: 0 (no limit)

# HTTP Client Singleton with connection pooling
http_client_limits = httpx.Limits(
    max_keepalive_connections=OUT_MAX_KEEPALIVE,
    max_connections=OUT_MAX_CONNECTIONS,
    keepalive_expiry=OUT_KEEPALIVE_EXPIRY
)

# Convert pool timeout from ms to seconds (0 = None)
pool_timeout = None if OUT_POOL_TIMEOUT_MS == 0 else (OUT_POOL_TIMEOUT_MS / 1000.0)

http_client_timeout = httpx.Timeout(
    timeout=OUT_READ_TIMEOUT,
    connect=OUT_CONNECT_TIMEOUT,
    pool=pool_timeout
)

# Global HTTP client (singleton)
http2_enabled = (OUT_PROTOCOL == "h2" or HTTP_VERSION == "2")
global_http_client = httpx.AsyncClient(
    http2=http2_enabled,
    timeout=http_client_timeout,
    limits=http_client_limits,
    follow_redirects=True
)

# OpenTelemetry configuration
OTEL_COLLECTOR_ENDPOINT = os.getenv("OTEL_COLLECTOR_ENDPOINT", "otel-collector:4317")

# Create resource
resource = Resource(attributes={
    SERVICE_NAME: "cifar10-api"
})

# Setup tracing
trace_provider = TracerProvider(resource=resource)
trace_provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=OTEL_COLLECTOR_ENDPOINT,
            insecure=True
        )
    )
)
trace.set_tracer_provider(trace_provider)
tracer = trace.get_tracer(__name__)

# Setup metrics
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(
        endpoint=OTEL_COLLECTOR_ENDPOINT,
        insecure=True
    ),
    export_interval_millis=5000
)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter(__name__)

# Setup logging
logger_provider = LoggerProvider(resource=resource)
set_logger_provider(logger_provider)
logger_provider.add_log_record_processor(
    BatchLogRecordProcessor(
        OTLPLogExporter(
            endpoint=OTEL_COLLECTOR_ENDPOINT,
            insecure=True
        )
    )
)
handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
logging.getLogger().addHandler(handler)

# Create custom metrics
request_counter = meter.create_counter(
    "api.requests.total",
    description="Total number of API requests",
    unit="1"
)

error_counter = meter.create_counter(
    "api.errors.total",
    description="Total number of API errors",
    unit="1"
)

hf_latency_histogram = meter.create_histogram(
    "hf_space.call.duration",
    description="Duration of HF Space API calls",
    unit="ms"
)

hf_request_counter = meter.create_counter(
    "hf_space.requests.total",
    description="Total requests to HF Space",
    unit="1"
)

# NEW: Metrics for external API endpoint
external_api_request_counter = meter.create_counter(
    "external_api.requests.total",
    description="Total requests to external API endpoint",
    unit="1"
)

external_api_error_counter = meter.create_counter(
    "external_api.errors.total",
    description="Total errors in external API calls",
    unit="1"
)

external_api_duration = meter.create_histogram(
    "external_api.duration",
    description="Duration of external API calls",
    unit="ms"
)

db_write_duration = meter.create_histogram(
    "db_write.duration",
    description="Duration of database write operations",
    unit="ms"
)

# Direct Prometheus metrics (for better Grafana integration)
prom_external_requests = Counter(
    'external_api_requests_total',
    'Total external API requests',
    ['status']
)

prom_external_errors = Counter(
    'external_api_errors_total',
    'Total external API errors',
    ['error_type']
)

prom_external_duration = Histogram(
    'external_api_duration_seconds',
    'External API duration in seconds',
    ['http_version']
)

prom_db_write_duration = Histogram(
    'db_write_duration_seconds',
    'Database write duration in seconds'
)


# Lifespan handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting CIFAR-10 API with observability...")
    try:
        init_db()
        logger.info("✅ Database connected")
    except Exception as e:
        logger.error(f"⚠️ Database initialization failed: {e}")

    # Test HF Space connection
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{HF_SPACE_URL}/")
            logger.info(f"✅ HF Space reachable: {response.status_code}")
    except Exception as e:
        logger.warning(f"⚠️ Could not reach HF Space: {e}")

    logger.info(f"✅ API ready with OpenTelemetry instrumentation!")
    logger.info(f"⚙️ HTTP client config:")
    logger.info(f"   - Protocol: {OUT_PROTOCOL}")
    logger.info(f"   - Read timeout: {OUT_READ_TIMEOUT}s")
    logger.info(f"   - Connect timeout: {OUT_CONNECT_TIMEOUT}s")
    logger.info(f"   - Pool timeout: {OUT_POOL_TIMEOUT_MS}ms")
    logger.info(f"   - Max connections: {OUT_MAX_CONNECTIONS}")
    logger.info(f"   - Max keepalive: {OUT_MAX_KEEPALIVE}")
    logger.info(f"   - Keepalive expiry: {OUT_KEEPALIVE_EXPIRY}s")

    yield

    # Shutdown
    logger.info("👋 Shutting down API...")
    await global_http_client.aclose()


# FastAPI app
app = FastAPI(
    title="CIFAR-10 Classifier API with Observability",
    description="FastAPI wrapper with OpenTelemetry tracing, metrics, and logging",
    version="2.0.0",
    lifespan=lifespan
)

# Auto-instrument FastAPI
FastAPIInstrumentor.instrument_app(app)

# Auto-instrument HTTPX
HTTPXClientInstrumentor().instrument()

# Auto-instrument SQLAlchemy
from db import engine

SQLAlchemyInstrumentor().instrument(engine=engine)


@app.get("/", tags=["Health"])
def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "message": "CIFAR-10 API with observability",
        "hf_space": HF_SPACE_URL,
        "docs": "/docs",
        "observability": "enabled"
    }


@app.get("/health", tags=["Health"])
def health():
    """Health check endpoint"""
    request_counter.add(1, {"endpoint": "/health", "method": "GET"})
    return {"status": "healthy"}


@app.get("/metrics", tags=["Monitoring"])
def prometheus_metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/mock-api", tags=["Testing"])
async def mock_external_api(delay: int = 0):
    """
    Mock external API for testing purposes.
    Supports configurable delay to simulate slow downstream services.

    Query params:
    - delay: Response delay in seconds (0-120), default 0
    """
    import random

    # Validate delay range
    delay = max(0, min(delay, 120))

    if delay > 0:
        await asyncio.sleep(delay)

    return {
        "id": random.randint(1, 1000),
        "title": "Mock API Response",
        "body": "This is a simulated external API response",
        "delay_seconds": delay,
        "timestamp": time.time()
    }


@app.post("/external-call", tags=["Load Testing"])
async def external_call(db: Session = Depends(get_db)):
    """
    Load testing endpoint that:
    1. Calls an external API (configurable via EXTERNAL_API_URL env var)
    2. Validates and transforms the response
    3. Stores a compact record in the database
    4. Returns a summary JSON

    Designed for k6 load testing to study:
    - Client/server timeouts
    - Connection pool behavior
    - HTTP/1.1 vs HTTP/2 performance
    - Database impact on latency
    """
    request_id = str(uuid.uuid4())
    current_span = trace.get_current_span()
    trace_id = format(current_span.get_span_context().trace_id, "032x")
    correlation_id = f"req-{request_id[:8]}"

    overall_start = time.time()

    prom_external_requests.labels(status="started").inc()
    external_api_request_counter.add(1, {"endpoint": "/external-call", "method": "POST"})

    logger.info(
        "🔄 External API call started",
        extra={"trace_id": trace_id, "request_id": request_id, "correlation_id": correlation_id}
    )

    try:
        with tracer.start_as_current_span("call_external_api") as span:
            span.set_attribute("external.url", EXTERNAL_API_URL)
            span.set_attribute("http.version", HTTP_VERSION)
            span.set_attribute("request.id", request_id)

            api_start = time.time()

            try:
                response = await global_http_client.get(EXTERNAL_API_URL)
                response.raise_for_status()

                api_duration = (time.time() - api_start) * 1000

                prom_external_duration.labels(http_version=HTTP_VERSION).observe(api_duration / 1000)
                external_api_duration.record(api_duration, {"status": "success", "http_version": HTTP_VERSION})

                data = response.json()

                # Create compact summary
                if isinstance(data, dict):
                    summary = {
                        "title": data.get("title", "")[:100],
                        "keys": list(data.keys())[:10],
                        "size": len(str(data)),
                    }
                elif isinstance(data, list):
                    summary = {
                        "count": len(data),
                        "first_item": str(data[0])[:100] if data else None,
                    }
                else:
                    summary = {"type": str(type(data)), "value": str(data)[:100]}

                span.set_attribute("response.status", response.status_code)
                span.set_attribute("response.size", len(response.content))
                span.set_attribute("api.duration.ms", api_duration)

                logger.info(
                    "✅ External API responded",
                    extra={
                        "trace_id": trace_id,
                        "request_id": request_id,
                        "status": response.status_code,
                        "duration_ms": api_duration,
                    }
                )

            except httpx.HTTPError as api_error:
                api_duration = (time.time() - api_start) * 1000
                external_api_duration.record(api_duration, {"status": "error", "http_version": HTTP_VERSION})
                external_api_error_counter.add(1, {"error_type": "external_api_failed"})
                raise api_error

        # --- Database Write ---
        db_duration = 0
        if db is not None:
            with tracer.start_as_current_span("db_write") as db_span:
                db_start = time.time()

                api_call_record = ExternalApiCall(
                    request_id=request_id,
                    external_url=EXTERNAL_API_URL,
                    http_method="GET",
                    http_version=f"HTTP/{HTTP_VERSION}",
                    status_code=response.status_code,
                    response_summary=json.dumps(summary),
                    is_success=True,
                    request_duration_ms=0,
                    external_api_duration_ms=api_duration,
                    db_write_duration_ms=0,
                )

                db.add(api_call_record)
                db.commit()

                db_duration = (time.time() - db_start) * 1000
                db_span.set_attribute("db.duration.ms", db_duration)

                prom_db_write_duration.observe(db_duration / 1000)
                db_write_duration.record(db_duration, {"operation": "insert"})

                api_call_record.db_write_duration_ms = db_duration
                api_call_record.request_duration_ms = (time.time() - overall_start) * 1000
                db.commit()

                logger.info(
                    "💾 Stored in database",
                    extra={
                        "trace_id": trace_id,
                        "request_id": request_id,
                        "db_duration_ms": db_duration,
                    }
                )

        total_duration = (time.time() - overall_start) * 1000
        prom_external_requests.labels(status="success").inc()

        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "status": "success",
            "external_api": {
                "url": EXTERNAL_API_URL,
                "http_version": f"HTTP/{HTTP_VERSION}",
                "status_code": response.status_code,
                "duration_ms": round(api_duration, 2),
            },
            "database": {
                "write_duration_ms": round(db_duration, 2) if db else None,
                "stored": db is not None,
            },
            "performance": {
                "total_duration_ms": round(total_duration, 2),
                "breakdown": {
                    "external_api": round(api_duration, 2),
                    "database": round(db_duration, 2) if db else 0,
                    "overhead": round(total_duration - api_duration - (db_duration if db else 0), 2),
                },
            },
            "response_summary": summary,
        }

    except httpx.HTTPError as e:
        error_duration = (time.time() - overall_start) * 1000

        prom_external_requests.labels(status="error").inc()
        prom_external_errors.labels(error_type="http_error").inc()
        external_api_error_counter.add(1, {"error_type": "http_error"})

        logger.error(
            "❌ External API call failed",
            extra={
                "trace_id": trace_id,
                "request_id": request_id,
                "error": str(e),
                "duration_ms": error_duration,
            }
        )

        if db is not None:
            try:
                api_call_record = ExternalApiCall(
                    request_id=request_id,
                    external_url=EXTERNAL_API_URL,
                    http_method="GET",
                    http_version=f"HTTP/{HTTP_VERSION}",
                    status_code=0,
                    response_summary=json.dumps({"error": str(e)}),
                    is_success=False,
                    request_duration_ms=error_duration,
                    external_api_duration_ms=0,
                    db_write_duration_ms=0,
                )
                db.add(api_call_record)
                db.commit()
            except Exception as db_err:
                logger.error(f"Failed to log error to DB: {db_err}")

        raise HTTPException(status_code=502, detail=f"External API failed: {str(e)}")

    except Exception as e:
        prom_external_requests.labels(status="error").inc()
        prom_external_errors.labels(error_type="internal_error").inc()
        external_api_error_counter.add(1, {"error_type": "internal_error"})

        logger.error(
            "❌ Unexpected error",
            extra={"trace_id": trace_id, "request_id": request_id},
            exc_info=True
        )

        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict", tags=["Inference"])
async def predict(
        file: UploadFile = File(..., description="Image file to classify"),
        db: Session = Depends(get_db)
):
    """
    Classify an image using the HF Space model with full observability.

    This endpoint:
    1. Receives an image from the client
    2. Forwards it to the HF Space for inference (traced)
    3. Logs the prediction and metadata to PostgreSQL
    4. Emits metrics and logs with trace context
    5. Returns the result to the client
    """
    # Get current span for trace context
    current_span = trace.get_current_span()
    trace_id = format(current_span.get_span_context().trace_id, '032x')

    request_counter.add(1, {"endpoint": "/predict", "method": "POST"})

    try:
        # Validate file
        if not file.content_type.startswith('image/'):
            error_counter.add(1, {"endpoint": "/predict", "error": "invalid_file_type"})
            raise HTTPException(status_code=400, detail="File must be an image")

        logger.info(f"📥 Received image: {file.filename}", extra={"trace_id": trace_id})

        # Create a custom span for HF Space call
        with tracer.start_as_current_span("call_hf_space") as span:
            span.set_attribute("hf.space.url", HF_SPACE_URL)
            span.set_attribute("file.name", file.filename)
            span.set_attribute("file.content_type", file.content_type)

            start_time = time.time()

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    content = await file.read()
                    files = {'file': (file.filename, content, file.content_type)}

                    logger.info(f"📤 Calling HF Space: {PREDICT_ENDPOINT}", extra={"trace_id": trace_id})

                    response = await client.post(PREDICT_ENDPOINT, files=files)
                    response.raise_for_status()

                    result = response.json()

                    # Record latency
                    latency_ms = (time.time() - start_time) * 1000
                    hf_latency_histogram.record(latency_ms, {"status": "success"})
                    hf_request_counter.add(1, {"status": "success"})

                    span.set_attribute("hf.response.status", response.status_code)
                    span.set_attribute("hf.latency.ms", latency_ms)
                    span.set_status(Status(StatusCode.OK))

                    logger.info(
                        f"✅ HF Space responded in {latency_ms:.2f}ms",
                        extra={
                            "trace_id": trace_id,
                            "latency_ms": latency_ms,
                            "status_code": response.status_code
                        }
                    )

            except httpx.HTTPError as e:
                latency_ms = (time.time() - start_time) * 1000
                hf_latency_histogram.record(latency_ms, {"status": "error"})
                hf_request_counter.add(1, {"status": "error"})
                error_counter.add(1, {"endpoint": "/predict", "error": "hf_space_error"})

                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("hf.error", str(e))
                span.set_attribute("hf.latency.ms", latency_ms)

                logger.error(
                    f"❌ HF Space call failed: {e}",
                    extra={
                        "trace_id": trace_id,
                        "error": str(e),
                        "latency_ms": latency_ms,
                        "endpoint": PREDICT_ENDPOINT
                    },
                    exc_info=True
                )
                raise HTTPException(status_code=502, detail=f"HF Space inference failed: {str(e)}")

        # Extract prediction data
        prediction = result.get("prediction")
        probabilities = result.get("probabilities", {})
        confidence = result.get("confidence", 0.0)

        current_span.set_attribute("prediction.class", prediction)
        current_span.set_attribute("prediction.confidence", confidence)

        # Log to PostgreSQL
        if db is not None:
            try:
                pred_entry = Prediction(
                    filename=file.filename,
                    prediction=prediction,
                    probabilities=str(probabilities),
                    confidence=confidence
                )
                db.add(pred_entry)
                db.commit()

                logger.info(
                    f"✅ Prediction logged to database",
                    extra={"trace_id": trace_id, "prediction": prediction}
                )
            except Exception as db_err:
                logger.error(
                    f"⚠️ Database logging failed: {db_err}",
                    extra={"trace_id": trace_id},
                    exc_info=True
                )
                if db:
                    db.rollback()

        return {
            "filename": file.filename,
            "prediction": prediction,
            "confidence": confidence,
            "probabilities": probabilities,
            "inference_source": "hugging_face_space",
            "trace_id": trace_id
        }

    except HTTPException:
        raise
    except Exception as e:
        error_counter.add(1, {"endpoint": "/predict", "error": "internal_error"})
        logger.error(
            f"❌ Unexpected error: {e}",
            extra={"trace_id": trace_id},
            exc_info=True
        )
        return JSONResponse(
            content={"error": str(e), "trace_id": trace_id},
            status_code=500
        )