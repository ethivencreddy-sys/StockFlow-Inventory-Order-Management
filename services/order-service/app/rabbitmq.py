
import json
import os
import time

import pika
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import OutboxEvent, utc_now


RABBITMQ_URL = os.getenv(
    "RABBITMQ_URL",
    "amqp://stockflow:password@localhost:5672/%2F",
)

EXCHANGE_NAME = "stockflow.events"

QUEUE_NAME = "stockflow.order.events"
RETRY_QUEUE = "stockflow.order.retry"
DLQ_QUEUE = "stockflow.order.dlq"

ROUTING_KEY = "order.created"

RETRY_ROUTING_KEY = "order.retry"
DLQ_ROUTING_KEY = "order.dlq"

MAX_ATTEMPTS = 3
RETRY_DELAY_MS = 5000


def get_connection():
    parameters = pika.URLParameters(RABBITMQ_URL)
    parameters.socket_timeout = 5
    parameters.blocked_connection_timeout = 5
    return pika.BlockingConnection(parameters)


def declare_topology(channel):
    """Declare durable main, retry and dead-letter queues."""

    channel.exchange_declare(
        exchange=EXCHANGE_NAME,
        exchange_type="topic",
        durable=True,
    )

    # Main order events queue.
    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True,
        arguments={
                 "x-queue-type": "classic",
                },
)

    channel.queue_bind(
        queue=QUEUE_NAME,
        exchange=EXCHANGE_NAME,
        routing_key=ROUTING_KEY,
    )

    # Retry queue: messages return to the main queue
    # after the configured delay.
    channel.queue_declare(
        queue=RETRY_QUEUE,
        durable=True,
        arguments={
            "x-message-ttl": RETRY_DELAY_MS,
            "x-dead-letter-exchange": EXCHANGE_NAME,
            "x-dead-letter-routing-key": ROUTING_KEY,
        },
    )

    channel.queue_bind(
        queue=RETRY_QUEUE,
        exchange=EXCHANGE_NAME,
        routing_key=RETRY_ROUTING_KEY,
    )

    # Dead-letter queue: failed messages remain here.
    channel.queue_declare(
        queue=DLQ_QUEUE,
        durable=True,
    )

    channel.queue_bind(
        queue=DLQ_QUEUE,
        exchange=EXCHANGE_NAME,
        routing_key=DLQ_ROUTING_KEY,
    )


def publish_message(
    channel,
    routing_key: str,
    message: dict,
    headers: dict | None = None,
):
    """Publish a persistent message with broker confirmation."""

    channel.basic_publish(
        exchange=EXCHANGE_NAME,
        routing_key=routing_key,
        body=json.dumps(message),
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type="application/json",
            headers=headers or {},
        ),
        mandatory=True,
    )


def publish_event(
    event_id: str,
    event_type: str,
    event_data: dict,
) -> bool:
    """Publish an event and require broker confirmation."""

    connection = None

    try:
        connection = get_connection()
        channel = connection.channel()

        declare_topology(channel)
        channel.confirm_delivery()

        message = {
            "event_id": event_id,
            "event_type": event_type,
            "data": event_data,
        }

        confirmed = channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key=event_type,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
            ),
            mandatory=True,
        )

        return confirmed is not False

    except Exception as exc:
        print(f"RabbitMQ publishing failed: {exc}", flush=True)
        return False

    finally:
        if connection and connection.is_open:
            connection.close()


def publish_retry(channel, message: dict, attempts: int):
    """Publish failed messages to the delayed retry queue."""

    publish_message(
        channel,
        RETRY_ROUTING_KEY,
        message,
        headers={
            "x-processing-attempts": attempts,
        },
    )


def publish_dead_letter(channel, message: dict, attempts: int, error: str):
    """Publish permanently failed messages to the DLQ."""

    publish_message(
        channel,
        DLQ_ROUTING_KEY,
        message,
        headers={
            "x-processing-attempts": attempts,
            "x-failure-reason": error[:500],
        },
    )


def publish_pending_events(batch_size: int = 50) -> int:
    """Publish pending outbox events and mark confirmed deliveries."""

    published_count = 0
    db: Session = SessionLocal()

    try:
        pending_events = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at.asc())
            .limit(batch_size)
            .all()
        )

        for event in pending_events:
            event.attempts += 1

            try:
                event_data = json.loads(event.payload)

                success = publish_event(
                    event.id,
                    event.event_type,
                    event_data,
                )

                if success:
                    event.published_at = utc_now()
                    event.last_error = None
                    published_count += 1
                else:
                    event.last_error = (
                        "RabbitMQ publisher confirmation failed"
                    )

            except Exception as exc:
                event.last_error = str(exc)

            db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

    return published_count


def run_outbox_publisher(
    poll_interval: int = 5,
    batch_size: int = 50,
):
    """Continuously publish pending outbox events."""

    print("StockFlow outbox publisher started.", flush=True)

    while True:
        try:
            count = publish_pending_events(batch_size)

            if count:
                print(
                    f"Published {count} outbox event(s).",
                    flush=True,
                )

        except Exception as exc:
            print(f"Outbox publisher error: {exc}", flush=True)

        time.sleep(poll_interval)
