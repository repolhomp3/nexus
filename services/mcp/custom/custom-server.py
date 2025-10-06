#!/usr/bin/env python3
import json
import sys
import requests
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

class CustomMCP:
    def __init__(self):
        self.data_store = {}
    
    def handle_request(self, request):
        method = request.get('method')
        params = request.get('params', {})
        
        if method == 'tools/list':
            return {
                "tools": [
                    {
                        "name": "store_data",
                        "description": "Store key-value data",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "description": "Data key"},
                                "value": {"type": "string", "description": "Data value"}
                            },
                            "required": ["key", "value"]
                        }
                    },
                    {
                        "name": "get_data",
                        "description": "Retrieve stored data",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "description": "Data key"}
                            },
                            "required": ["key"]
                        }
                    },
                    {
                        "name": "get_weather",
                        "description": "Get weather info",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "city": {"type": "string", "description": "City name"}
                            },
                            "required": ["city"]
                        }
                    }
                ]
            }
        
        elif method == 'tools/call':
            tool_name = params.get('name')
            args = params.get('arguments', {})
            
            if tool_name == 'store_data':
                return self.store_data(args['key'], args['value'])
            elif tool_name == 'get_data':
                return self.get_data(args['key'])
            elif tool_name == 'get_weather':
                return self.get_weather(args['city'])
        
        return {"error": "Unknown method"}
    
    def store_data(self, key, value):
        self.data_store[key] = {
            "value": value,
            "timestamp": datetime.now().isoformat()
        }
        return {"content": [{"type": "text", "text": f"Stored '{key}' = '{value}'"}]}
    
    def get_data(self, key):
        if key in self.data_store:
            data = self.data_store[key]
            return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}
        else:
            return {"error": f"Key '{key}' not found"}
    
    def get_weather(self, city):
        try:
            url = f"https://wttr.in/{city}?format=j1"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                current = data['current_condition'][0]
                weather_info = {
                    "city": city,
                    "temperature": f"{current['temp_C']}°C",
                    "description": current['weatherDesc'][0]['value']
                }
                return {"content": [{"type": "text", "text": json.dumps(weather_info, indent=2)}]}
            else:
                return {"error": f"Weather API error: {response.status_code}"}
        
        except Exception as e:
            return {"error": f"Weather request failed: {str(e)}"}

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
    server = CustomMCP()
    
    def handler(*args, **kwargs):
        MCPHandler(server, *args, **kwargs)
    
    httpd = HTTPServer(('0.0.0.0', 8000), handler)
    print("Custom MCP Server running on port 8000")
    httpd.serve_forever()