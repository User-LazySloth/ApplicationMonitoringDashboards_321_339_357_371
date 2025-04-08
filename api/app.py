from flask import Flask, jsonify, request, Response
import random
import logging
from datetime import datetime
import uuid
from kafka import KafkaProducer
import json
import os
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    Summary,
    generate_latest,
    CONTENT_TYPE_LATEST,
    start_http_server,
)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


REQUEST_COUNT = Counter(
    "app_requests_total", "Total Request Count", ["method", "endpoint", "http_status"]
)

REQUEST_LATENCY = Histogram(
    "app_request_latency_seconds",
    "Request Latency",
    ["method", "endpoint"],
    buckets=[0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120],
)

ERROR_COUNTER = Counter(
    "app_errors_total", "Total Error Count", ["error_type", "endpoint"]
)

REQUEST_SIZE = Summary(
    "app_request_size_bytes", "Request Size in Bytes", ["method", "endpoint"]
)

ENDPOINT_USAGE = Counter("app_endpoint_usage", "Endpoint Usage Count", ["endpoint"])

IN_PROGRESS_REQUESTS = Gauge(
    "app_in_progress_requests", "Number of requests currently being processed"
)

RESPONSE_TIME = Summary(
    "app_response_time_seconds", "Response Time in seconds", ["method", "endpoint"]
)


try:
    producer = KafkaProducer(
        bootstrap_servers=[os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        api_version=(2, 5, 0),
        max_request_size=10485760,
        request_timeout_ms=30000,
    )
    logging.info("Kafka Producer initialized successfully")
except Exception as e:
    logging.error(f"Failed to initialize Kafka Producer: {e}")
    producer = None

ENDPOINTS = ["EP1", "EP2", "EP3", "EP4", "EP5"]
LOG_TOPIC = "application_logs"
ERROR_TOPIC = "application_errors"


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route("/api/<endpoint>", methods=["GET", "POST"])
def handle_request(endpoint):

    IN_PROGRESS_REQUESTS.inc()

    REQUEST_SIZE.labels(method=request.method, endpoint=endpoint).observe(
        request.content_length or 0
    )

    ENDPOINT_USAGE.labels(endpoint=endpoint).inc()

    REQUEST_COUNT.labels(
        method=request.method, endpoint=endpoint, http_status=404
    ).inc()

    if endpoint not in ENDPOINTS:
        error_type = "Invalid Endpoint"
        ERROR_COUNTER.labels(error_type=error_type, endpoint=endpoint).inc()

        error_log = {
            "timestamp": datetime.now().isoformat(),
            "error_type": error_type,
            "endpoint": endpoint,
        }

        if producer:
            try:
                producer.send(ERROR_TOPIC, error_log)
                producer.flush()
                logging.info(f"Error log sent to Kafka: {error_log}")
            except Exception as e:
                logging.error(f"Failed to send error to Kafka: {e}")

        IN_PROGRESS_REQUESTS.dec()
        return jsonify({"error": "Invalid endpoint"}), 404

    REQUEST_COUNT.labels(
        method=request.method, endpoint=endpoint, http_status=200
    ).inc()

    with REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).time():
        request_id = str(uuid.uuid4())
        response_time = random.uniform(10, 500)

        RESPONSE_TIME.labels(method=request.method, endpoint=endpoint).observe(
            response_time
        )

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "request_id": request_id,
            "endpoint": endpoint,
            "method": request.method,
            "response_time": response_time,
        }

        if producer:
            try:
                producer.send(LOG_TOPIC, log_entry)
                producer.flush()
                logging.info(f"Log sent to Kafka: {log_entry}")
            except Exception as e:
                logging.error(f"Failed to send log to Kafka: {e}")

        IN_PROGRESS_REQUESTS.dec()
        return jsonify(
            {
                "status": "success",
                "request_id": request_id,
                "message": f"Processed {endpoint} successfully",
            }
        )


if __name__ == "__main__":
    start_http_server(8000)
    app.run(host="0.0.0.0", port=5000)
