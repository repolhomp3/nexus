#!/usr/bin/env python3
import json
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from http.server import HTTPServer, BaseHTTPRequestHandler

class KubernetesMCP:
    def __init__(self):
        try:
            config.load_incluster_config()
        except:
            try:
                config.load_kube_config()
            except:
                print("Could not load Kubernetes configuration")
                
        self.v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.autoscaling_v1 = client.AutoscalingV1Api()
    
    def handle_request(self, request):
        method = request.get('method')
        params = request.get('params', {})
        
        if method == 'tools/list':
            return {
                "tools": [
                    {
                        "name": "list_pods",
                        "description": "List pods in a namespace",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "namespace": {"type": "string", "default": "default"}
                            }
                        }
                    },
                    {
                        "name": "scale_deployment",
                        "description": "Scale a deployment",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "deployment_name": {"type": "string"},
                                "namespace": {"type": "string", "default": "default"},
                                "replicas": {"type": "integer"}
                            },
                            "required": ["deployment_name", "replicas"]
                        }
                    },
                    {
                        "name": "get_cluster_status",
                        "description": "Get cluster health status",
                        "inputSchema": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "troubleshoot_pod",
                        "description": "Analyze pod issues",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "pod_name": {"type": "string"},
                                "namespace": {"type": "string", "default": "default"}
                            },
                            "required": ["pod_name"]
                        }
                    }
                ]
            }
        
        elif method == 'tools/call':
            tool_name = params.get('name')
            args = params.get('arguments', {})
            
            if tool_name == 'list_pods':
                return self.list_pods(args.get('namespace', 'default'))
            elif tool_name == 'scale_deployment':
                return self.scale_deployment(
                    args['deployment_name'],
                    args.get('namespace', 'default'),
                    args['replicas']
                )
            elif tool_name == 'get_cluster_status':
                return self.get_cluster_status()
            elif tool_name == 'troubleshoot_pod':
                return self.troubleshoot_pod(
                    args['pod_name'],
                    args.get('namespace', 'default')
                )
        
        return {"error": "Unknown method"}
    
    def list_pods(self, namespace):
        try:
            pods = self.v1.list_namespaced_pod(namespace)
            pod_list = []
            for pod in pods.items:
                pod_info = {
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "ready": sum(1 for c in pod.status.container_statuses or [] if c.ready),
                    "node": pod.spec.node_name
                }
                pod_list.append(pod_info)
            
            return {"content": [{"type": "text", "text": json.dumps(pod_list, indent=2)}]}
        except ApiException as e:
            return {"error": f"Kubernetes API error: {e}"}
    
    def scale_deployment(self, deployment_name, namespace, replicas):
        try:
            deployment = self.apps_v1.read_namespaced_deployment(deployment_name, namespace)
            deployment.spec.replicas = replicas
            
            self.apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                body=deployment
            )
            
            return {"content": [{"type": "text", "text": f"Scaled {deployment_name} to {replicas} replicas"}]}
        except ApiException as e:
            return {"error": f"Could not scale deployment: {e}"}
    
    def get_cluster_status(self):
        try:
            nodes = self.v1.list_node()
            node_status = []
            for node in nodes.items:
                conditions = {c.type: c.status for c in node.status.conditions or []}
                node_status.append({
                    "name": node.metadata.name,
                    "ready": conditions.get("Ready", "Unknown")
                })
            
            return {"content": [{"type": "text", "text": json.dumps(node_status, indent=2)}]}
        except ApiException as e:
            return {"error": f"Could not get cluster status: {e}"}
    
    def troubleshoot_pod(self, pod_name, namespace):
        try:
            pod = self.v1.read_namespaced_pod(pod_name, namespace)
            
            issues = []
            if pod.status.phase != "Running":
                issues.append(f"Pod is in {pod.status.phase} state")
            
            if pod.status.container_statuses:
                for container in pod.status.container_statuses:
                    if not container.ready:
                        issues.append(f"Container {container.name} is not ready")
            
            troubleshoot_info = {
                "pod_name": pod_name,
                "status": pod.status.phase,
                "issues": issues
            }
            
            return {"content": [{"type": "text", "text": json.dumps(troubleshoot_info, indent=2)}]}
        except ApiException as e:
            return {"error": f"Could not troubleshoot pod: {e}"}

class MCPHandler(BaseHTTPRequestHandler):
    def __init__(self, mcp_server, *args, **kwargs):
        self.mcp_server = mcp_server
        super().__init__(*args, **kwargs)
    
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            request = json.loads(post_data.decode('utf-8'))
            response = self.mcp_server.handle_request(request)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
    
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')

if __name__ == "__main__":
    server = KubernetesMCP()
    
    def handler(*args, **kwargs):
        MCPHandler(server, *args, **kwargs)
    
    httpd = HTTPServer(('0.0.0.0', 8000), handler)
    print("Kubernetes MCP Server running on port 8000")
    httpd.serve_forever()