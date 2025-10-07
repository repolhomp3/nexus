#!/usr/bin/env python3
"""Synthetic DJI-style drone data producer for Nexus."""

import json
import os
import random
import threading
import time
from datetime import datetime, timezone

import boto3

STREAM_NAME = os.getenv("DRONE_STREAM", "nexus-dev-client-intake")
REGION = os.getenv("AWS_REGION", "us-west-2")
SAMPLE_RATE_SECONDS = float(os.getenv("DRONE_SAMPLE_RATE", "2"))
DRONE_ID = os.getenv("DRONE_ID", "drone-alpha")

kinesis = boto3.client("kinesis", region_name=REGION)


def generate_payload(sequence: int) -> dict:
    base_lat = 37.7749
    base_lon = -122.4194
    jitter = lambda spread: random.uniform(-spread, spread)
    sensors = {
        "battery": round(random.uniform(30.0, 100.0), 2),
        "temperature": round(random.uniform(-5.0, 35.0), 2),
        "wind_speed": round(random.uniform(0.0, 12.0), 2),
        "payload_weight": round(random.uniform(0.0, 5.0), 2),
    }
    return {
        "droneId": DRONE_ID,
        "sequence": sequence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "position": {
            "lat": base_lat + jitter(0.01),
            "lon": base_lon + jitter(0.01),
            "alt": round(random.uniform(20.0, 120.0), 2),
        },
        "velocity": {
            "ground": round(random.uniform(0.0, 15.0), 2),
            "vertical": round(random.uniform(-2.0, 2.0), 2),
        },
        "sensors": sensors,
        "status": random.choice(["OK", "WARNING", "ALERT"]),
    }


def publish_loop():
    sequence = 0
    while True:
        payload = generate_payload(sequence)
        kinesis.put_record(
            StreamName=STREAM_NAME,
            Data=json.dumps(payload).encode("utf-8"),
            PartitionKey=payload["droneId"],
        )
        sequence += 1
        time.sleep(SAMPLE_RATE_SECONDS)


if __name__ == "__main__":
    print(f"Starting drone simulator for stream {STREAM_NAME} in {REGION}")
    thread = threading.Thread(target=publish_loop, daemon=True)
    thread.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("Simulator stopped")
