"""
Trinetra Agent Base Class
Base class for all 13 agents. Handles Redis Pub/Sub consumption, status publishing,
and the standard agent lifecycle.

Migration: Kafka → Redis Pub/Sub (March 2026)
- confluent_kafka.Consumer → redis.pubsub.subscribe()
- confluent_kafka.Producer → redis.publish()
- process() interface is 100% unchanged — all 13 agent main.py files work as-is.
"""
import os
import json
import signal
import sys
import time
from dotenv import load_dotenv

# Load .env from agents/ directory (auto-loads API keys for all agents)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import redis
from .logger import get_logger
from .ucso_client import UcsoClient


class AgentBase:
    """
    Base class providing Redis Pub/Sub boilerplate for every Trinetra agent.

    Subclasses must implement:
        - process(self, application_id: str, ucso: dict) -> dict
          Returns the namespace data to PATCH.

    Class attributes that subclasses must set:
        - AGENT_NAME: str          e.g., "compliance-agent"
        - LISTEN_TOPICS: list[str] e.g., ["application_created"]
        - OUTPUT_NAMESPACE: str    e.g., "compliance"
        - OUTPUT_EVENT: str        e.g., "compliance_passed"
    """

    AGENT_NAME = "base-agent"
    LISTEN_TOPICS = []
    OUTPUT_NAMESPACE = ""
    OUTPUT_EVENT = ""

    def __init__(self):
        self.logger = get_logger(self.AGENT_NAME)
        self.ucso_client = UcsoClient()
        self.running = True

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.pubsub = None

        # Graceful shutdown
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, frame):
        self.logger.info(f"{self.AGENT_NAME} received shutdown signal.")
        self.running = False

    def publish_event(self, topic: str, application_id: str, extra: dict = None):
        """Publish a Redis event after successful processing."""
        message = {
            "application_id": application_id,
            "source_agent": self.AGENT_NAME,
            **(extra or {}),
        }
        self.redis_client.publish(topic, json.dumps(message))
        self.logger.info(
            f"Published event to '{topic}'",
            extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
        )

    def publish_status(self, application_id: str, status: str, error_code: str = None):
        """Publish agent status to the agent_status channel for WebSocket broadcast."""
        # Prevent infinite loop: monitor-agent listens to agent_status, so it shouldn't publish its own status
        if self.AGENT_NAME == "monitor-agent":
            return

        message = {
            "application_id": application_id,
            "agent": self.AGENT_NAME,
            "status": status,
            "error_code": error_code,
        }
        self.redis_client.publish("agent_status", json.dumps(message))

    def process(self, application_id: str, ucso: dict) -> dict:
        """
        Core processing logic. Must be overridden by each agent.

        Args:
            application_id: UUID of the loan application.
            ucso: The full UCSO dictionary.

        Returns:
            A dictionary containing the data to PATCH into OUTPUT_NAMESPACE.
        """
        raise NotImplementedError("Subclasses must implement process()")

    def run(self):
        """Main event loop with auto-reconnect on Redis failures."""
        max_retries = 999  # Effectively infinite
        retry_count = 0

        while self.running and retry_count < max_retries:
            try:
                self.pubsub = self.redis_client.pubsub()
                self.pubsub.subscribe(*self.LISTEN_TOPICS)
                self.logger.info(
                    f"{self.AGENT_NAME} started. Listening on: {self.LISTEN_TOPICS}"
                )
                retry_count = 0  # Reset on successful start

                while self.running:
                    msg = self.pubsub.get_message(timeout=1.0)
                    if msg is None:
                        continue
                    if msg["type"] != "message":
                        continue

                    payload = {}
                    try:
                        payload = json.loads(msg["data"])
                        application_id = payload.get("application_id")
                        if not application_id:
                            self.logger.warning("Received message without application_id, skipping.")
                            continue

                        self.logger.info(
                            f"Processing application {application_id}",
                            extra={"agent_name": self.AGENT_NAME, "application_id": application_id},
                        )
                        self.publish_status(application_id, "PROCESSING")

                        # Fetch current UCSO state
                        ucso = self.ucso_client.get_ucso(application_id)

                        # Run agent-specific logic
                        result = self.process(application_id, ucso)

                        # PATCH the result into the correct namespace
                        if result and self.OUTPUT_NAMESPACE:
                            # Backend expects a JSON object, not a list
                            if isinstance(result, list):
                                result = {"data": result}
                            self.ucso_client.patch_namespace(
                                application_id, self.OUTPUT_NAMESPACE, result
                            )

                        # Publish success event
                        if self.OUTPUT_EVENT:
                            self.publish_event(self.OUTPUT_EVENT, application_id)

                        self.publish_status(application_id, "COMPLETED")

                    except Exception as e:
                        self.logger.error(
                            f"Error processing message: {e}",
                            exc_info=True,
                            extra={"agent_name": self.AGENT_NAME, "application_id": payload.get("application_id", "unknown")},
                        )
                        self.publish_status(
                            payload.get("application_id", "unknown"),
                            "FAILED",
                            error_code=type(e).__name__,
                        )

            except Exception as e:
                retry_count += 1
                self.logger.error(
                    f"Redis connection lost ({type(e).__name__}: {e}). "
                    f"Reconnecting in 5s... (attempt {retry_count})"
                )
                time.sleep(5)

                # Recreate pubsub on reconnect
                try:
                    if self.pubsub:
                        self.pubsub.close()
                except Exception:
                    pass

                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
                self.redis_client = redis.from_url(redis_url, decode_responses=True)

        if self.pubsub:
            self.pubsub.close()
        self.redis_client.close()
        self.logger.info(f"{self.AGENT_NAME} shut down gracefully.")
