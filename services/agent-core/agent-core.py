#!/usr/bin/env python3
"""Nexus Agent Core service."""

import argparse
import json
import logging
import os
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
import requests
import yaml

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DEFAULT_REGION = "us-west-2"
DEFAULT_MODEL = "amazon.titan-text-lite-v1"


@dataclass
class BedrockConfig:
    model_id: str = DEFAULT_MODEL
    max_token_count: int = 200


@dataclass
class AgentCoreConfig:
    region: str = DEFAULT_REGION
    bedrock: BedrockConfig = field(default_factory=BedrockConfig)
    mcp_endpoints: Dict[str, str] = field(default_factory=lambda: {
        "aws": "http://aws-mcp.nexus-mcp.svc.cluster.local",
        "database": "http://database-mcp.nexus-mcp.svc.cluster.local",
        "custom": "http://custom-mcp.nexus-mcp.svc.cluster.local",
        "k8s": "http://k8s-mcp.nexus-mcp.svc.cluster.local",
    })
    data_pipelines: Dict[str, str] = field(default_factory=dict)


def load_config(path: Optional[str]) -> AgentCoreConfig:
    """Load YAML config from disk and merge with defaults."""
    config = AgentCoreConfig()
    if not path:
        return config

    cfg_path = Path(path)
    if not cfg_path.exists():
        LOGGER.warning("Config path %s does not exist; using defaults", cfg_path)
        return config

    with cfg_path.open("r", encoding="utf-8") as handle:
        try:
            payload = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            LOGGER.error("Failed to parse config %s: %s", cfg_path, exc)
            return config

    region = payload.get("aws", {}).get("region") or payload.get("region")
    if region:
        config.region = region

    bedrock_cfg = payload.get("bedrock", {})
    if isinstance(bedrock_cfg, dict):
        preferred_models: List[str] = bedrock_cfg.get("preferredModels") or []
        model_id = bedrock_cfg.get("modelId") or (preferred_models[0] if preferred_models else config.bedrock.model_id)
        config.bedrock.model_id = model_id or DEFAULT_MODEL
        text_cfg = bedrock_cfg.get("textGeneration", {}) or bedrock_cfg.get("textGenerationConfig", {})
        if isinstance(text_cfg, dict) and text_cfg.get("maxTokenCount"):
            config.bedrock.max_token_count = int(text_cfg["maxTokenCount"])

    endpoints = payload.get("mcpEndpoints")
    if isinstance(endpoints, dict):
        config.mcp_endpoints.update({k: v for k, v in endpoints.items() if v})

    pipelines = payload.get("dataPipelines") or {}
    if isinstance(pipelines, dict):
        config.data_pipelines.update({k: str(v) for k, v in pipelines.items() if v})

    return config


class AgentCore:
    def __init__(self, config: AgentCoreConfig):
        self.config = config
        region = os.getenv("AWS_REGION", config.region)
        self.bedrock = boto3.client("bedrock-runtime", region_name=region)
        self.mcp_endpoints = config.mcp_endpoints
        self.data_pipelines = config.data_pipelines
        self.max_token_count = config.bedrock.max_token_count
        self.model_id = config.bedrock.model_id

    def call_mcp_tool(self, server: str, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Call MCP server tool."""
        url = self.mcp_endpoints.get(server)
        if not url:
            return {"error": f"Unknown MCP server: {server}"}

        payload = {
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }

        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception("Error calling MCP tool %s on %s", tool, server)
            return {"error": str(exc)}

    def invoke_bedrock(self, prompt: str) -> str:
        """Invoke Bedrock model for reasoning."""
        try:
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                body=json.dumps(
                    {
                        "inputText": prompt,
                        "textGenerationConfig": {"maxTokenCount": self.max_token_count},
                    }
                ),
            )
            result = json.loads(response["body"].read())
            return result["results"][0]["outputText"]
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception("Bedrock invocation failed")
            return f"Bedrock error: {exc}"

    def execute_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """Execute agentic workflow."""
        task = workflow.get("task", "")

        if "bedrock" in task.lower():
            prompt = workflow.get("prompt", "Hello from Nexus Agent Core!")
            result = self.invoke_bedrock(prompt)
            return {"workflow": "bedrock_test", "result": result}

        if "s3" in task.lower():
            result = self.call_mcp_tool("aws", "list_s3_buckets", {})
            return {"workflow": "s3_list", "result": result}

        if "weather" in task.lower():
            city = workflow.get("city", "San Francisco")
            weather = self.call_mcp_tool("custom", "get_weather", {"city": city})
            analysis = self.invoke_bedrock(f"Analyze this weather: {weather}")
            storage = self.call_mcp_tool(
                "custom",
                "store_data",
                {
                    "key": f"weather_{city}",
                    "value": analysis,
                },
            )
            return {
                "workflow": "weather_analysis",
                "steps": [
                    {"step": "get_weather", "result": weather},
                    {"step": "ai_analysis", "result": analysis},
                    {"step": "store_result", "result": storage},
                ],
            }

        if "database" in task.lower():
            query = workflow.get("query", "SELECT * FROM users")
            result = self.call_mcp_tool("database", "execute_query", {"query": query})
            return {"workflow": "database_query", "result": result}

        if "kubernetes" in task.lower() or "k8s" in task.lower():
            if "scale" in task.lower():
                deployment = workflow.get("deployment_name", "agent-core")
                replicas = workflow.get("replicas", 3)
                result = self.call_mcp_tool(
                    "k8s",
                    "scale_deployment",
                    {"deployment_name": deployment, "replicas": replicas},
                )
                return {"workflow": "k8s_scale", "result": result}
            if "status" in task.lower() or "health" in task.lower():
                result = self.call_mcp_tool("k8s", "get_cluster_status", {})
                analysis = self.invoke_bedrock(f"Analyze this Kubernetes cluster status: {result}")
                return {
                    "workflow": "k8s_health_check",
                    "steps": [
                        {"step": "get_status", "result": result},
                        {"step": "ai_analysis", "result": analysis},
                    ],
                }
            if "pods" in task.lower():
                namespace = workflow.get("namespace", "default")
                result = self.call_mcp_tool("k8s", "list_pods", {"namespace": namespace})
                return {"workflow": "k8s_list_pods", "result": result}
            if "troubleshoot" in task.lower():
                pod_name = workflow.get("pod_name")
                if pod_name:
                    result = self.call_mcp_tool("k8s", "troubleshoot_pod", {"pod_name": pod_name})
                    analysis = self.invoke_bedrock(f"Provide troubleshooting recommendations: {result}")
                    return {
                        "workflow": "k8s_troubleshoot",
                        "steps": [
                            {"step": "analyze_pod", "result": result},
                            {"step": "ai_recommendations", "result": analysis},
                        ],
                    }
                return {"error": "pod_name required for troubleshooting"}
            result = self.call_mcp_tool("k8s", "get_cluster_status", {})
            return {"workflow": "k8s_general", "result": result}

        if "drone" in task.lower():
            event = workflow.get("event") or {}
            if not isinstance(event, dict):
                return {"error": "event must be provided as an object"}
            partition_key = workflow.get("partition_key") or event.get("droneId") or "nexus-drone"
            transform_result = self.call_mcp_tool(
                "aws",
                "process_drone_event",
                {"payload": event, "partitionKey": partition_key},
            )
            if "error" in transform_result:
                return {"workflow": "drone_ingest", "error": transform_result["error"]}
            summary_prompt = (
                "Summarize this drone telemetry for an ops console, highlighting key metrics: "
                f"{transform_result}"
            )
            summary = self.invoke_bedrock(summary_prompt)
            return {
                "workflow": "drone_ingest",
                "steps": [
                    {"step": "normalize", "result": transform_result},
                    {"step": "bedrock_summary", "result": summary},
                ],
                "outputStream": self.data_pipelines.get("processedStream"),
            }

        if "glue" in task.lower():
            if "start" in task.lower():
                job_name = workflow.get("job_name", "my-etl-job")
                start_result = self.call_mcp_tool("aws", "start_glue_job", {"job_name": job_name})
                try:
                    run_data = json.loads(start_result["content"][0]["text"])  # type: ignore[index]
                    run_id = run_data["run_id"]
                    status_result = self.call_mcp_tool(
                        "aws",
                        "get_glue_job_status",
                        {"job_name": job_name, "run_id": run_id},
                    )
                    analysis = self.invoke_bedrock(f"Analyze this Glue job execution: {status_result}")
                    return {
                        "workflow": "glue_job_execution",
                        "steps": [
                            {"step": "start_job", "result": start_result},
                            {"step": "check_status", "result": status_result},
                            {"step": "ai_analysis", "result": analysis},
                        ],
                    }
                except Exception as exc:  # pylint: disable=broad-except
                    LOGGER.exception("Failed to process Glue job run metadata")
                    return {"workflow": "glue_job_execution", "error": str(exc)}
            jobs_result = self.call_mcp_tool("aws", "list_glue_jobs", {})
            analysis = self.invoke_bedrock(f"Analyze these Glue jobs and suggest optimizations: {jobs_result}")
            return {
                "workflow": "glue_jobs_analysis",
                "steps": [
                    {"step": "list_jobs", "result": jobs_result},
                    {"step": "ai_analysis", "result": analysis},
                ],
            }

        return {"error": "Unknown workflow"}


class AgentHandler(BaseHTTPRequestHandler):
    def __init__(self, agent_core: AgentCore, *args, **kwargs):
        self.agent_core = agent_core
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - keep BaseHTTPRequestHandler signature
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def do_POST(self) -> None:  # noqa: D401 - HTTP handler
        content_length = int(self.headers.get("Content-Length", "0"))
        post_data = self.rfile.read(content_length)

        try:
            request = json.loads(post_data.decode("utf-8"))
            method = request.get("method")
            if method == "workflow/execute":
                result = self.agent_core.execute_workflow(request.get("params", {}))
            else:
                result = {"error": "Unknown method"}

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode("utf-8"))
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception("Agent core request failed")
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode("utf-8"))

    def do_GET(self) -> None:  # noqa: D401 - HTTP handler
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        elif self.path == "/metrics":
            metrics = (
                "# HELP agent_core_requests_total Total requests processed\n"
                "# TYPE agent_core_requests_total counter\n"
                "agent_core_requests_total 42\n"
                "# HELP agent_core_active_workflows Active workflows\n"
                "# TYPE agent_core_active_workflows gauge\n"
                "agent_core_active_workflows 3\n"
            )
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(metrics.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self) -> None:  # noqa: D401 - HTTP handler
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def run_server(agent_core: AgentCore) -> None:
    def handler(*args, **kwargs):
        AgentHandler(agent_core, *args, **kwargs)

    httpd = HTTPServer(("0.0.0.0", 8000), handler)
    LOGGER.info("Agent Core running on port 8000")
    httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Nexus Agent Core service")
    parser.add_argument("--config", dest="config_path", type=str, help="Path to settings YAML file", default=None)
    args = parser.parse_args()

    config = load_config(args.config_path)
    agent_core = AgentCore(config)
    run_server(agent_core)


if __name__ == "__main__":
    main()
