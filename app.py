from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import httpx
import logging
import time

from db import init_db, get_db
from models import Prediction

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

    logger.info("✅ API ready with OpenTelemetry instrumentation!")
    yield

    # Shutdown
    logger.info("👋 Shutting down API...")


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
    #commit status