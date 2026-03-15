import redis
import json
import time

r = redis.Redis(host='localhost', port=6379, db=0)

topic = "model_selected"
payload = {"application_id": "3d3462a8-fa6e-44d9-9095-e830bc79ceaa", "status": "passed"}

print(f"Publishing {topic}")
r.publish(topic, json.dumps(payload))
time.sleep(1)

topic = "risk_generated"
print(f"Publishing {topic}")
r.publish(topic, json.dumps(payload))
time.sleep(1)

topic = "stress_completed"
print(f"Publishing {topic}")
r.publish(topic, json.dumps(payload))
