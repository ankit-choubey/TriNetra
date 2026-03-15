import redis
import json

r = redis.Redis(host='localhost', port=6379, db=0)

topic = "parsing_completed"
payload = {"application_id": "3d3462a8-fa6e-44d9-9095-e830bc79ceaa", "status": "passed"}

print(f"Publishing {topic}")
r.publish(topic, json.dumps(payload))
