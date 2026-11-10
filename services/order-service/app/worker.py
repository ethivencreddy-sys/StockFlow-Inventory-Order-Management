import threading

from app.rabbitmq import run_outbox_publisher
from app.consumer import run_consumer


if __name__ == "__main__":
    publisher_thread = threading.Thread(
        target=run_outbox_publisher,
        kwargs={
            "poll_interval": 5,
            "batch_size": 50,
        },
        daemon=True,
    )

    consumer_thread = threading.Thread(
        target=run_consumer,
        daemon=False,
    )

    publisher_thread.start()
    consumer_thread.start()

    consumer_thread.join()