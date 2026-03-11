"""
Trinetra Test Pipeline
Injects Kafka events and monitors agent progress.
"""
import json
import time
import os
import uuid
from confluent_kafka import Producer, Consumer, KafkaError

KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")

def get_producer():
    return Producer({"bootstrap.servers": KAFKA_BROKER})

def get_consumer(topics):
    c = Consumer({
        "bootstrap.servers": KAFKA_BROKER,
        "group.id": "test-monitor-group",
        "auto.offset.reset": "latest"
    })
    c.subscribe(topics)
    return c

def trigger_event(topic, app_id, data=None):
    p = get_producer()
    payload = {"application_id": app_id}
    if data:
        payload.update(data)
    
    p.produce(topic, key=app_id, value=json.dumps(payload).encode('utf-8'))
    p.flush()
    print(f" [TEST] Triggered event '{topic}' for app {app_id}")

def monitor_pipeline(app_id, timeout=60):
    topics = ["agent_status", "cam_generated", "compliance_failed"]
    c = get_consumer(topics)
    
    start_time = time.time()
    completed_agents = set()
    
    print(f" [TEST] Monitoring pipeline for app {app_id}...")
    
    try:
        while time.time() - start_time < timeout:
            msg = c.poll(1.0)
            if msg is None: continue
            if msg.error(): continue
            
            payload = json.loads(msg.value().decode('utf-8'))
            if payload.get("application_id") != app_id: continue
            
            topic = msg.topic()
            
            if topic == "agent_status":
                agent = payload.get("agent")
                status = payload.get("status")
                print(f" [AGENT] {agent}: {status}")
                if status == "COMPLETED":
                    completed_agents.add(agent)
            
            if topic == "cam_generated":
                print(f" [SUCCESS] CAM generated! Pipeline complete.")
                break
                
            if topic == "compliance_failed":
                print(f" [FAIL] Compliance check failed: {payload.get('missing_documents')}")
                break
                
    finally:
        c.close()

if __name__ == "__main__":
    # Example usage
    test_app_id = str(uuid.uuid4())
    print(f"Starting test for application: {test_app_id}")
    
    # 1. Start monitoring in a separate process or just run sequentially if testing single agents
    # For a full test, trigger 'application_created'
    trigger_event("application_created", test_app_id)
    
    # In a real test, you'd feed actual files to the mock backend first
    
    monitor_pipeline(test_app_id)
