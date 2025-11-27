import asyncio
import json
import logging
import os
import time
from aiokafka import AIOKafkaConsumer
import aio_pika
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# OpenTelemetry
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME

# Configuration
BROKER_MODE = os.getenv("BROKER_MODE", "kafka")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
DATABASE_URL = os.getenv("DATABASE_URL")
EXTERNAL_API_URL = os.getenv("EXTERNAL_API_URL")
OTEL_COLLECTOR_ENDPOINT = os.getenv("OTEL_COLLECTOR_ENDPOINT", "otel-collector:4317")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup OpenTelemetry
resource = Resource(attributes={SERVICE_NAME: "external-worker"})
trace_provider = TracerProvider(resource=resource)
trace_provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter(endpoint=OTEL_COLLECTOR_ENDPOINT, insecure=True)
    )
)
trace.set_tracer_provider(trace_provider)
tracer = trace.get_tracer(__name__)

# Database
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# HTTP client
http_client = httpx.AsyncClient(timeout=180.0)


async def process_async_upstream(message_data):
    """
    Scenario A: Worker calls external API and saves to DB
    """
    correlation_id = message_data.get("correlation_id")

    with tracer.start_as_current_span("process_async_upstream") as span:
        span.set_attribute("correlation_id", correlation_id)
        span.set_attribute("scenario", "async-upstream")

        try:
            # Call external API
            logger.info(f"📞 Calling external API", extra={"correlation_id": correlation_id})
            start_time = time.time()

            response = await http_client.get(message_data["external_url"])
            response.raise_for_status()
            duration_ms = (time.time() - start_time) * 1000

            result = response.json()

            # Save to DB
            db = SessionLocal()
            try:
                from models import ExternalApiCall

                record = ExternalApiCall(
                    request_id=correlation_id,
                    correlation_id=correlation_id,
                    external_url=message_data["external_url"],
                    http_method="GET",
                    http_version="HTTP/1.1",
                    status_code=response.status_code,
                    response_summary=json.dumps(result),
                    is_success=True,
                    request_duration_ms=duration_ms,
                    external_api_duration_ms=duration_ms,
                    db_write_duration_ms=0
                )
                db.add(record)
                db.commit()

                logger.info(
                    f"✅ Processed async-upstream",
                    extra={"correlation_id": correlation_id, "duration_ms": duration_ms}
                )
            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ Failed: {e}", extra={"correlation_id": correlation_id})


async def process_async_downstream(message_data):
    """
    Scenario B: Worker only saves to DB (External API already called by API)
    """
    correlation_id = message_data.get("correlation_id")

    with tracer.start_as_current_span("process_async_downstream") as span:
        span.set_attribute("correlation_id", correlation_id)
        span.set_attribute("scenario", "async-downstream")

        try:
            db = SessionLocal()
            try:
                from models import ExternalApiCall

                record = ExternalApiCall(
                    request_id=correlation_id,
                    correlation_id=correlation_id,
                    external_url=message_data["external_url"],
                    http_method="GET",
                    http_version="HTTP/1.1",
                    status_code=message_data["status_code"],
                    response_summary=json.dumps(message_data["response_data"]),
                    is_success=True,
                    request_duration_ms=message_data["duration_ms"],
                    external_api_duration_ms=message_data["duration_ms"],
                    db_write_duration_ms=0
                )
                db.add(record)
                db.commit()

                logger.info(f"💾 Saved async-downstream", extra={"correlation_id": correlation_id})
            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ Failed: {e}", extra={"correlation_id": correlation_id})


async def consume_kafka():
    """Kafka consumer"""
    consumer = AIOKafkaConsumer(
        "async_upstream",
        "async_downstream",
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_deserializer=lambda m: json.loads(m.decode('utf-8')),
        group_id="external-worker-group"
    )

    await consumer.start()
    logger.info("✅ Kafka consumer started")

    try:
        async for msg in consumer:
            data = msg.value
            scenario = data.get("scenario")

            if scenario == "async-upstream":
                await process_async_upstream(data)
            elif scenario == "async-downstream":
                await process_async_downstream(data)
    finally:
        await consumer.stop()


async def consume_rabbitmq():
    """RabbitMQ consumer"""
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()

    async def process_message(message: aio_pika.IncomingMessage):
        async with message.process():
            data = json.loads(message.body.decode())
            scenario = data.get("scenario")

            if scenario == "async-upstream":
                await process_async_upstream(data)
            elif scenario == "async-downstream":
                await process_async_downstream(data)

    queue_upstream = await channel.declare_queue("async_upstream", durable=True)
    queue_downstream = await channel.declare_queue("async_downstream", durable=True)

    await queue_upstream.consume(process_message)
    await queue_downstream.consume(process_message)

    logger.info("✅ RabbitMQ consumer started")

    # Keep running
    await asyncio.Future()


async def main():
    logger.info(f"🚀 Starting worker in {BROKER_MODE} mode")

    if BROKER_MODE == "kafka":
        await consume_kafka()
    elif BROKER_MODE == "rabbitmq":
        await consume_rabbitmq()
    else:
        logger.error(f"Unknown BROKER_MODE: {BROKER_MODE}")


if __name__ == "__main__":
    asyncio.run(main())