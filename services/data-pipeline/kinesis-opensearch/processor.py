#!/usr/bin/env python3
"""Stream processed Kinesis events into OpenSearch for visualization."""

import json
import os
import time
from typing import Dict, Iterable

import boto3
import requests
from requests.auth import HTTPBasicAuth

REGION = os.getenv("AWS_REGION", "us-west-2")
KINESIS_STREAM = os.getenv("PROCESSED_STREAM", "nexus-dev-processed")
POLL_SECONDS = float(os.getenv("KINESIS_POLL_INTERVAL", "2"))
OPENSEARCH_ENDPOINT = os.getenv("OPENSEARCH_ENDPOINT", "http://opensearch.nexus-observability.svc.cluster.local:9200")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "drone-events")
USERNAME = os.getenv("OPENSEARCH_USERNAME", "admin")
PASSWORD = os.getenv("OPENSEARCH_PASSWORD", "admin123")

kinesis = boto3.client("kinesis", region_name=REGION)
session = requests.Session()
auth = HTTPBasicAuth(USERNAME, PASSWORD) if USERNAME and PASSWORD else None


def ensure_index() -> None:
    response = session.get(f"{OPENSEARCH_ENDPOINT}/{OPENSEARCH_INDEX}", auth=auth, timeout=10)
    if response.status_code == 404:
        mapping = {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "normalized": {
                        "properties": {
                            "latitude": {"type": "float"},
                            "longitude": {"type": "float"},
                            "altitude_m": {"type": "float"},
                            "captured_at": {"type": "date"},
                        }
                    }
                }
            },
        }
        session.put(
            f"{OPENSEARCH_ENDPOINT}/{OPENSEARCH_INDEX}",
            data=json.dumps(mapping),
            headers={"Content-Type": "application/json"},
            auth=auth,
            timeout=10,
        )


def iter_shard_iterators() -> Iterable[Dict[str, str]]:
    response = kinesis.list_shards(StreamName=KINESIS_STREAM)
    for shard in response.get("Shards", []):
        shard_id = shard["ShardId"]
        iterator = kinesis.get_shard_iterator(
            StreamName=KINESIS_STREAM,
            ShardId=shard_id,
            ShardIteratorType="LATEST",
        )
        yield {"ShardId": shard_id, "Iterator": iterator["ShardIterator"]}


def write_to_opensearch(doc: Dict) -> None:
    session.post(
        f"{OPENSEARCH_ENDPOINT}/{OPENSEARCH_INDEX}/_doc",
        data=json.dumps(doc),
        headers={"Content-Type": "application/json"},
        auth=auth,
        timeout=10,
    )


def process_stream() -> None:
    ensure_index()
    shard_states = list(iter_shard_iterators())
    while True:
        for shard in shard_states:
            iterator = shard.get("Iterator")
            if not iterator:
                continue
            response = kinesis.get_records(ShardIterator=iterator, Limit=100)
            shard["Iterator"] = response.get("NextShardIterator")
            for record in response.get("Records", []):
                try:
                    payload = json.loads(record["Data"])
                    write_to_opensearch(payload)
                except json.JSONDecodeError:
                    continue
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    print(f"Streaming {KINESIS_STREAM} into OpenSearch index {OPENSEARCH_INDEX}")
    process_stream()
