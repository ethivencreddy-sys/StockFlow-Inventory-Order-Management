
import json
import time

from sqlalchemy import Column, DateTime, String
from sqlalchemy.exc import IntegrityError

from app.database import Base, SessionLocal, engine
from app.models import utc_now
from app.rabbitmq import (
    QUEUE_NAME,
    ROUTING_KEY,
    MAX_ATTEMPTS,
    get_connection,
    declare_topology,
    publish_retry,
    publish_dead_letter,
)


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id = Column(String(36), primary_key=True)
    event_type = Column(String(100), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=False)


def process_event(message: dict):
    """Record an event once using its unique Outbox ID."""

    event_id = message.get("event_id")
    event_type = message.get("event_type")
    event_data = message.get("data")

    if not event_id or not event_type or not isinstance(event_data, dict):
        raise ValueError("Invalid event message")

    if event_type != ROUTING_KEY:
        raise ValueError(f"Unsupported event type: {event_type}")

    db = SessionLocal()

    try:
        existing = (
            db.query(ProcessedEvent)
            .filter(ProcessedEvent.event_id == event_id)
            .first()
        )

        if existing:
            print(f"Duplicate event ignored: {event_id}", flush=True)
            return

        record = ProcessedEvent(
            event_id=event_id,
            event_type=event_type,
            processed_at=utc_now(),
        )

        db.add(record)

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            print(f"Duplicate event ignored: {event_id}", flush=True)
            return

        print(
            f"Successfully processed {event_type}: "
            f"Order ID {event_data.get('order_id')}",
            flush=True,
        )

    finally:
        db.close()


def callback(ch, method, properties, body):
    """Handle valid, invalid, retryable and permanently failed messages."""

    headers = properties.headers or {}

    try:
        attempts = max(
            0,
            int(headers.get("x-processing-attempts", 0)),
        )
    except (TypeError, ValueError):
        attempts = 0

    # Step 1: Decode and validate JSON.
    try:
        message = json.loads(body.decode("utf-8"))

        if not isinstance(message, dict):
            raise ValueError("Event message must be a JSON object")

    except Exception as parse_error:
        print(
            f"Invalid message received: {parse_error}",
            flush=True,
        )

        dead_letter_message = {
            "event_type": "invalid.message",
            "data": {
                "raw_body": body.decode("utf-8", errors="replace"),
            },
        }

        try:
            publish_dead_letter(
                ch,
                dead_letter_message,
                MAX_ATTEMPTS,
                f"Invalid message: {parse_error}",
            )

            ch.basic_ack(
                delivery_tag=method.delivery_tag,
            )

            print(
                "Malformed message moved to DLQ.",
                flush=True,
            )

        except Exception as publish_error:
            print(
                f"DLQ publishing failed: {publish_error}",
                flush=True,
            )

            ch.stop_consuming()

        return

    # Step 2: Process valid JSON messages.
    try:
        process_event(message)

        ch.basic_ack(
            delivery_tag=method.delivery_tag,
        )

    except Exception as exc:
        next_attempt = attempts + 1

        print(
            f"Consumer processing failed: {exc}",
            flush=True,
        )

        try:
            if next_attempt < MAX_ATTEMPTS:
                publish_retry(
                    ch,
                    message,
                    next_attempt,
                )

                print(
                    f"Message scheduled for retry "
                    f"{next_attempt}/{MAX_ATTEMPTS}",
                    flush=True,
                )

            else:
                publish_dead_letter(
                    ch,
                    message,
                    next_attempt,
                    str(exc),
                )

                print(
                    f"Message moved to DLQ after "
                    f"{next_attempt} attempts",
                    flush=True,
                )

            # Acknowledge original only after confirmed publishing.
            ch.basic_ack(
                delivery_tag=method.delivery_tag,
            )

        except Exception as publish_error:
            print(
                f"Retry/DLQ publishing failed: {publish_error}",
                flush=True,
            )

            # Leave original message unacknowledged.
            # It will be redelivered when the connection closes.
            ch.stop_consuming()


def run_consumer():
    """Consume order events with bounded retries and DLQ handling."""

    Base.metadata.create_all(bind=engine)

    while True:
        connection = None

        try:
            connection = get_connection()
            channel = connection.channel()

            declare_topology(channel)
            channel.confirm_delivery()
            channel.basic_qos(prefetch_count=1)

            channel.basic_consume(
                queue=QUEUE_NAME,
                on_message_callback=callback,
                auto_ack=False,
            )

            print(
                f"StockFlow consumer listening on {QUEUE_NAME}",
                flush=True,
            )

            channel.start_consuming()

        except KeyboardInterrupt:
            print("Consumer stopped.", flush=True)
            break

        except Exception as exc:
            print(
                f"Consumer connection error: {exc}",
                flush=True,
            )
            time.sleep(5)

        finally:
            if connection and connection.is_open:
                connection.close()
