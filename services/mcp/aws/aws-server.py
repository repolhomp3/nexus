#!/usr/bin/env python3
"""AWS MCP service for Nexus."""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

REGION = os.getenv("AWS_REGION", "us-west-2")
DEFAULT_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.titan-text-lite-v1")
DRONE_GLUE_DATABASE = os.getenv("DRONE_GLUE_DATABASE", "nexus_observations")
DRONE_GLUE_TABLE = os.getenv("DRONE_GLUE_TABLE", "drone_catalog")
DRONE_PROCESSED_STREAM = os.getenv("DRONE_PROCESSED_STREAM")


class AWSMCP:
    def __init__(self):
        self.session = None
        self.init_aws_session()
        self.glue = None
        self.kinesis = None
        if self.session:
            self.glue = self.session.client("glue", region_name=REGION)
            self.kinesis = self.session.client("kinesis", region_name=REGION)

    def init_aws_session(self) -> None:
        try:
            self.session = boto3.Session(region_name=REGION)
            sts = self.session.client("sts")
            sts.get_caller_identity()
        except (NoCredentialsError, ClientError):
            self.session = None

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        method = request.get("method")
        params = request.get("params", {})

        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "list_s3_buckets",
                        "description": "List S3 buckets",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "invoke_bedrock_model",
                        "description": "Invoke Bedrock model",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "prompt": {"type": "string", "description": "Text prompt"},
                                "max_tokens": {"type": "integer", "default": 100},
                                "model_id": {"type": "string", "description": "Override model ID"},
                            },
                            "required": ["prompt"],
                        },
                    },
                    {
                        "name": "list_glue_jobs",
                        "description": "List AWS Glue jobs",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "start_glue_job",
                        "description": "Start a Glue job run",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "job_name": {"type": "string", "description": "Glue job name"}
                            },
                            "required": ["job_name"],
                        },
                    },
                    {
                        "name": "get_glue_job_status",
                        "description": "Get Glue job run status",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "job_name": {"type": "string", "description": "Glue job name"},
                                "run_id": {"type": "string", "description": "Job run ID"},
                            },
                            "required": ["job_name", "run_id"],
                        },
                    },
                    {
                        "name": "process_drone_event",
                        "description": "Normalize drone telemetry against the Glue catalog and emit a silver-tier record to Kinesis.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "payload": {
                                    "type": "object",
                                    "description": "Raw drone payload as parsed JSON",
                                },
                                "partitionKey": {
                                    "type": "string",
                                    "description": "Partition key for the processed Kinesis stream",
                                },
                            },
                            "required": ["payload"],
                        },
                    },
                ]
            }

        if method == "tools/call":
            if not self.session:
                return {"error": "AWS credentials not configured"}

            tool_name = params.get("name")
            args = params.get("arguments", {})

            if tool_name == "list_s3_buckets":
                return self.list_s3_buckets()
            if tool_name == "invoke_bedrock_model":
                return self.invoke_bedrock_model(
                    args["prompt"],
                    args.get("max_tokens", 100),
                    args.get("model_id") or DEFAULT_MODEL_ID,
                )
            if tool_name == "list_glue_jobs":
                return self.list_glue_jobs()
            if tool_name == "start_glue_job":
                return self.start_glue_job(args["job_name"])
            if tool_name == "get_glue_job_status":
                return self.get_glue_job_status(args["job_name"], args["run_id"])
            if tool_name == "process_drone_event":
                return self.process_drone_event(args)

        return {"error": "Unknown method"}

    def list_s3_buckets(self):
        try:
            s3 = self.session.client("s3")
            response = s3.list_buckets()
            buckets = [bucket["Name"] for bucket in response.get("Buckets", [])]
            return {"content": [{"type": "text", "text": json.dumps(buckets)}]}
        except Exception as exc:  # pylint: disable=broad-except
            return {"error": f"S3 error: {exc}"}

    def invoke_bedrock_model(self, prompt, max_tokens, model_id):
        try:
            bedrock = self.session.client("bedrock-runtime", region_name=REGION)
            body = {
                "inputText": prompt,
                "textGenerationConfig": {"maxTokenCount": min(max_tokens, 3072)},
            }

            response = bedrock.invoke_model(modelId=model_id, body=json.dumps(body))
            result = json.loads(response["body"].read())
            output_text = result["results"][0]["outputText"]

            return {"content": [{"type": "text", "text": output_text}]}
        except Exception as exc:  # pylint: disable=broad-except
            return {"error": f"Bedrock error: {exc}"}

    def list_glue_jobs(self):
        try:
            glue = self.session.client("glue", region_name=REGION)
            response = glue.get_jobs()
            jobs = [
                {
                    "name": job["Name"],
                    "role": job["Role"],
                    "created": job.get("CreatedOn").isoformat() if job.get("CreatedOn") else None,
                    "last_modified": job.get("LastModifiedOn").isoformat() if job.get("LastModifiedOn") else None,
                }
                for job in response.get("Jobs", [])
            ]
            return {"content": [{"type": "text", "text": json.dumps(jobs, indent=2)}]}
        except Exception as exc:  # pylint: disable=broad-except
            return {"error": f"Glue error: {exc}"}

    def start_glue_job(self, job_name):
        try:
            glue = self.session.client("glue", region_name=REGION)
            response = glue.start_job_run(JobName=job_name)
            result = {
                "job_name": job_name,
                "run_id": response["JobRunId"],
                "status": "STARTING",
            }
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
        except Exception as exc:  # pylint: disable=broad-except
            return {"error": f"Glue job start error: {exc}"}

    def get_glue_job_status(self, job_name, run_id):
        try:
            glue = self.session.client("glue", region_name=REGION)
            response = glue.get_job_run(JobName=job_name, RunId=run_id)
            job_run = response["JobRun"]
            result = {
                "job_name": job_name,
                "run_id": run_id,
                "state": job_run.get("JobRunState"),
                "started_on": job_run.get("StartedOn").isoformat() if job_run.get("StartedOn") else None,
                "completed_on": job_run.get("CompletedOn").isoformat() if job_run.get("CompletedOn") else None,
                "execution_time": job_run.get("ExecutionTime", 0),
            }
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
        except Exception as exc:  # pylint: disable=broad-except
            return {"error": f"Glue job status error: {exc}"}

    def process_drone_event(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not DRONE_PROCESSED_STREAM:
            return {"error": "DRONE_PROCESSED_STREAM environment variable not configured"}
        if not self.glue or not self.kinesis:
            return {"error": "AWS clients unavailable"}

        payload = args.get("payload")
        if not isinstance(payload, dict):
            return {"error": "payload must be a JSON object"}

        partition_key = args.get("partitionKey") or payload.get("droneId") or "nexus-drone"

        try:
            table_meta = self.glue.get_table(DatabaseName=DRONE_GLUE_DATABASE, Name=DRONE_GLUE_TABLE)
            schema_cols = [col["Name"] for col in table_meta["Table"]["StorageDescriptor"].get("Columns", [])]
        except ClientError as exc:
            return {"error": f"Glue catalog lookup failed: {exc}"}

        normalized = {col: payload.get(col) for col in schema_cols if col in payload}
        normalized.setdefault("drone_id", payload.get("droneId"))
        normalized.setdefault("captured_at", payload.get("timestamp"))
        if payload.get("position"):
            position = payload["position"]
            normalized.setdefault("latitude", position.get("lat"))
            normalized.setdefault("longitude", position.get("lon"))
            normalized.setdefault("altitude_m", position.get("alt"))
        if payload.get("sensors"):
            normalized.setdefault("sensor_snapshot", payload["sensors"])

        enriched_event = {
            "raw": payload,
            "normalized": normalized,
            "catalogReference": {
                "database": DRONE_GLUE_DATABASE,
                "table": DRONE_GLUE_TABLE,
            },
        }

        try:
            self.kinesis.put_record(
                StreamName=DRONE_PROCESSED_STREAM,
                Data=json.dumps(enriched_event).encode("utf-8"),
                PartitionKey=partition_key,
            )
        except ClientError as exc:
            return {"error": f"Failed to publish to processed stream: {exc}"}

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "status": "processed",
                            "partitionKey": partition_key,
                            "stream": DRONE_PROCESSED_STREAM,
                            "attributes": list(normalized.keys()),
                        },
                        indent=2,
                    ),
                }
            ]
        }


class MCPHandler(BaseHTTPRequestHandler):
    def __init__(self, mcp_server, *args, **kwargs):
        self.mcp_server = mcp_server
        super().__init__(*args, **kwargs)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        post_data = self.rfile.read(content_length)

        try:
            request = json.loads(post_data.decode("utf-8"))
            response = self.mcp_server.handle_request(request)

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode("utf-8"))
        except Exception as exc:  # pylint: disable=broad-except
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    server = AWSMCP()

    def handler(*args, **kwargs):
        MCPHandler(server, *args, **kwargs)

    httpd = HTTPServer(("0.0.0.0", 8000), handler)
    print("AWS MCP Server running on port 8000")
    httpd.serve_forever()
