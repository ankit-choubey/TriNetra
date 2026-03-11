"""
Trinetra FastAPI Backend — Redis Pub/Sub Broker
Replaces Apache Kafka with Redis for agent event pipeline.
Agents subscribe to channels (topics) and publish events after processing.
"""
import json
import asyncio
import redis
import redis.asyncio as aioredis
from config import REDIS_URL


class RedisBroker:
    """
    Synchronous Redis Pub/Sub broker for agent communication.
    Used by agent_base.py (sync Python processes).
    """

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or REDIS_URL
        self.client = redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = None

    def publish(self, channel: str, message: dict):
        """Publish an event to a Redis channel (replaces Kafka producer)."""
        self.client.publish(channel, json.dumps(message))

    def subscribe(self, channels: list[str]):
        """Subscribe to Redis channels (replaces Kafka consumer)."""
        self.pubsub = self.client.pubsub()
        self.pubsub.subscribe(*channels)
        return self.pubsub

    def listen(self):
        """
        Blocking listener — yields messages from subscribed channels.
        Replaces Kafka consumer.poll().
        """
        if not self.pubsub:
            raise RuntimeError("Must call subscribe() before listen()")

        for message in self.pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    yield {
                        "channel": message["channel"],
                        "data": data,
                    }
                except json.JSONDecodeError:
                    continue

    def close(self):
        """Clean up connections."""
        if self.pubsub:
            self.pubsub.close()
        self.client.close()


class AsyncRedisBroker:
    """
    Async Redis Pub/Sub broker for the FastAPI backend.
    Listens to agent_status channel and pushes to WebSocket.
    """

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or REDIS_URL
        self.client = None
        self.pubsub = None

    async def connect(self):
        """Initialize async Redis connection."""
        self.client = aioredis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.client.pubsub()

    async def publish(self, channel: str, message: dict):
        """Publish event asynchronously."""
        if not self.client:
            await self.connect()
        await self.client.publish(channel, json.dumps(message))

    async def subscribe(self, *channels: str):
        """Subscribe to channels."""
        if not self.pubsub:
            await self.connect()
        await self.pubsub.subscribe(*channels)

    async def listen(self):
        """
        Async generator — yields messages from subscribed channels.
        Used by the backend to forward agent events to WebSocket.
        """
        if not self.pubsub:
            raise RuntimeError("Must call subscribe() before listen()")

        async for message in self.pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    yield {
                        "channel": message["channel"],
                        "data": data,
                    }
                except json.JSONDecodeError:
                    continue

    async def close(self):
        """Clean up connections."""
        if self.pubsub:
            await self.pubsub.close()
        if self.client:
            await self.client.close()
