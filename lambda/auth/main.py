import json
import os
import secrets
from datetime import datetime, timedelta, timezone

import boto3

STS_CLIENT = boto3.client("sts")
MIN_TTL = 900
MAX_TTL = 3600


def _clamp_ttl(value: int) -> int:
    return max(MIN_TTL, min(MAX_TTL, value))


def _parse_body(event):
    body = event.get("body") or {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {}
    return body


def lambda_handler(event, _context):
    """Issue temporary bearer credentials for Nexus data ingest."""
    project = os.getenv("PROJECT", "nexus")
    role_arn = os.getenv("TOKEN_ROLE_ARN")
    data_stream = os.getenv("CLIENT_DATA_STREAM")
    video_stream = os.getenv("CLIENT_VIDEO_STREAM")
    firehose_stream = os.getenv("CLIENT_FIREHOSE_STREAM")

    if not role_arn:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "TOKEN_ROLE_ARN not configured"}),
        }

    body = _parse_body(event)
    user = body.get("user", "anonymous")
    ttl_seconds = _clamp_ttl(int(body.get("ttl", 1800)))

    session_name = f"{project}-{user}-{secrets.token_hex(4)}"[:64]

    try:
        assumed = STS_CLIENT.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            DurationSeconds=ttl_seconds,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"Failed to mint bearer token: {exc}"}),
        }

    creds = assumed["Credentials"]

    response = {
        "token": secrets.token_urlsafe(32),
        "tokenType": "Bearer",
        "user": user,
        "project": project,
        "expires": creds["Expiration"].isoformat(),
        "streams": {
            "kinesisData": data_stream,
            "kinesisVideo": video_stream,
            "firehoseDelivery": firehose_stream,
        },
        "credentials": {
            "accessKeyId": creds["AccessKeyId"],
            "secretAccessKey": creds["SecretAccessKey"],
            "sessionToken": creds["SessionToken"],
        },
        "issuedAt": datetime.now(timezone.utc).isoformat(),
        "ttlSeconds": ttl_seconds,
    }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response),
    }
