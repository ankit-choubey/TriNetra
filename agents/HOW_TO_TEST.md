# How to Verify Trinetra Agents

To verify that the 13 agents are working correctly, follow these steps:

## Prerequisites
1.  **Kafka Running**: Ensure Kafka is running (locally or via Docker).
2.  **Dependencies**: Install test dependencies:
    ```bash
    pip install flask requests confluent-kafka
    ```

## Step 1: Start the Mock Backend
This script simulates the Spring Boot API, allowing agents to GET/PATCH the UCSO state.
```bash
python agents/test_mock_backend.py
```

## Step 2: Start the Agents
You can run agents individually to test them, or run all via Docker. For testing one agent (e.g., Compliance):
```bash
export BACKEND_URL=http://localhost:8080
export KAFKA_BROKER=localhost:9092
python agents/compliance-agent/main.py
```

## Step 3: Run the Test Pipeline
This script injects a test event and listens for agent responses.
```bash
python agents/test_pipeline.py
```

## Step 4: Verify the UCSO State
After the test runs, you can check the final UCSO JSON in `/tmp/trinetra_mock/<application_id>.json`. This file will contain all the patches made by the agents.

## Testing a Full Chain (Example)
1.  Start Mock Backend.
2.  Start `compliance-agent`, `doc-agent`, `gst-agent`.
3.  Upload a dummy PDF to the mock backend:
    ```bash
    curl -F "file=@test.pdf" -F "application_id=123" -F "doc_type=ANNUAL_REPORT" http://localhost:8080/api/files/upload
    ```
4.  Trigger the pipeline:
    ```bash
    python agents/test_pipeline.py  # (Inside, it triggers 'application_created')
    ```
5.  Watch the logs to see the agents process the file in sequence!
