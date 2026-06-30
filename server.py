#!/usr/bin/env python3
"""
Local dev server for WXY Shopping Guide.
Serves static files from the script's directory,
and proxies /api/chat to AI providers (Qwen / DeepSeek / VolcEngine).

Usage:  python3 server.py
Server:  http://localhost:8765
"""

import http.server
import json
import urllib.request
import urllib.error
import os
import sys
import mimetypes

# ── Configuration ────────────────────────────────────────────────────────────

PORT = 8766
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ── AI API proxy ────────────────────────────────────────────────────────────

def call_ai_api(provider, api_key, req_body):
    """Forward request to the selected AI provider. Returns (http_status, body_dict)."""
    base_urls = {
        'qwen':       'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'deepseek':   'https://api.deepseek.com/v1',
        'volcengine': 'https://ark.cn-beijing.volces.com/api/v3',
    }
    base = base_urls.get(provider, base_urls['qwen'])
    url = base + '/chat/completions'

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}',
    }
    data = json.dumps(req_body).encode('utf-8')

    try:
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='replace')
        try:
            return e.code, json.loads(err_body)
        except Exception:
            return e.code, {'error': {'message': err_body[:500], 'code': 'HTTPError'}}
    except Exception as e:
        return 502, {'error': {'message': str(e), 'code': 'ProxyError'}}


# ── Request handler ──────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    """
    GET  → serve static files from BASE_DIR (SPA mode: '/' → index.html)
    POST /api/chat → proxy to AI provider
    """

    # ── Static file serving ────────────────────────────────────────────────

    def _serve_static(self, raw_path):
        # 1. Strip scheme+host if the proxy forwarded a full URL.
        if raw_path.startswith(('http://', 'https://')):
            from urllib.parse import urlparse
            raw_path = urlparse(raw_path).path or '/'

        # 2. Remove query string.
        raw_path = raw_path.split('?')[0]

        # 3. SPA fallback: '/' → index.html
        if raw_path == '/':
            raw_path = '/index.html'

        # 4. Security: reject anything still trying to escape.
        #    normpath resolves '..' components.
        clean = os.path.normpath(raw_path)  # e.g. '/index.html' or '/ai-shopping/api.js'
        #    Reject if the normalized path tries to leave the web root.
        #    We only allow paths under '/' (i.e. under BASE_DIR after join).
        #    clean must not start with '..'.
        if clean.startswith('..'):
            self.send_error(403, 'Forbidden')
            return

        # 5. Build filesystem path: join BASE_DIR with the path (strip leading '/').
        #    e.g. '/index.html' → 'index.html' → BASE_DIR + '/index.html'
        rel = clean.lstrip('/')
        fs_path = os.path.join(BASE_DIR, rel)

        # 6. Final safety net: resolve symlinks, ensure still inside BASE_DIR.
        try:
            real_base   = os.path.realpath(BASE_DIR)
            real_target = os.path.realpath(fs_path)
            if not real_target.startswith(real_base + os.sep) and real_target != real_base:
                self.send_error(403, 'Forbidden')
                return
        except OSError:
            self.send_error(404, 'File not found')
            return

        if not os.path.isfile(fs_path):
            self.send_error(404, 'File not found')
            return

        # 7. Serve the file.
        try:
            mime, _ = mimetypes.guess_type(fs_path)
            mime = mime or 'application/octet-stream'
            with open(fs_path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)
            print(f'[200] {raw_path}', file=sys.stderr)
        except Exception as e:
            print(f'[ERR] {fs_path}: {e}', file=sys.stderr)
            self.send_error(500, 'Internal error')

    def do_GET(self):
        self._serve_static(self.path)

    # ── QCC (企查查) MCP proxy endpoint ────────────────────────────────

    def _handle_qcc_query(self):
        """Proxy: query company registration status via 企查查 MCP."""
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length).decode('utf-8')
            req = json.loads(raw)
        except Exception as e:
            self._reply_json(400, {'error': 'Invalid request: ' + str(e)})
            return

        company_name = req.get('companyName', '').strip()
        credit_code = req.get('creditCode', '').strip()

        if not company_name and not credit_code:
            self._reply_json(400, {'error': 'companyName or creditCode required'})
            return

        # 企查查 Bearer Token（服务端持有，不依赖前端传入）
        api_key = req.get('apiKey', '') or 'MjbMIpK9kLeVputyjTJJurXbGXVSBOLcXTDTHaNps8H3YesB'
        qcc_url = 'https://agent.qcc.com/mcp/company/stream'

        # ── Step 1: list available tools ──
        list_req = {
            'jsonrpc': '2.0',
            'method': 'tools/list',
            'id': 1
        }
        tools = self._qcc_rpc_call(qcc_url, api_key, list_req)
        if not tools:
            print('[QCC] tools/list failed, trying tools/call directly', file=sys.stderr)

        # ── Step 2: query company registration info ──
        # Use get_company_registration_info which returns 登记状态 field
        search_keyword = credit_code if credit_code else company_name
        reg_req = {
            'jsonrpc': '2.0',
            'method': 'tools/call',
            'params': {
                'name': 'get_company_registration_info',
                'arguments': {'searchKey': search_keyword}
            },
            'id': 2
        }

        reg_result = self._qcc_rpc_call(qcc_url, api_key, reg_req)

        if not reg_result:
            self._reply_json(200, {
                'success': True,
                'source': 'qcc_mcp',
                'companyName': company_name,
                'creditCode': credit_code,
                'isDeregistered': None,
                'status': 'unknown',
                'detail': '无法获取企查查查询结果，请手动确认',
                'raw': None
            })
            return

        # ── Step 3: parse result ──
        parsed = self._parse_qcc_result(reg_result, company_name, credit_code)
        self._reply_json(200, parsed)

    def _qcc_rpc_call(self, url, api_key, payload):
        """Make a JSON-RPC call to the QCC MCP server (supports SSE streaming)."""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
            'Accept': 'text/event-stream, application/json'
        }
        data = json.dumps(payload).encode('utf-8')

        try:
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw_body = resp.read().decode('utf-8', errors='replace')

            # Handle SSE format: may start with "event: message\n" then "data: {...}"
            # or directly "data: {...}"
            lines = raw_body.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line.startswith('data: '):
                    json_str = line[6:]
                    try:
                        parsed = json.loads(json_str)
                        if 'result' in parsed or 'error' in parsed:
                            return parsed
                    except json.JSONDecodeError:
                        continue

            # No SSE data line found — try plain JSON
            try:
                return json.loads(raw_body)
            except json.JSONDecodeError:
                print(f'[QCC] Non-JSON response: {raw_body[:200]}', file=sys.stderr)
                return None

        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')[:500]
            print(f'[QCC] HTTP {e.code}: {err_body}', file=sys.stderr)
            return None
        except Exception as e:
            print(f'[QCC] RPC error: {e}', file=sys.stderr)
            return None

    def _parse_qcc_result(self, result, company_name, credit_code):
        """Parse QCC MCP response to extract deregistration status.
        
        企查查 get_company_registration_info returns JSON text with 登记状态 field.
        Active:        '存续（在营、开业、在册）'
        Deregistered:  '注销' or '吊销'
        """
        import datetime
        import json as _json

        base = {
            'success': True,
            'source': 'qcc_mcp',
            'companyName': company_name,
            'creditCode': credit_code,
            'queryTime': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'isDeregistered': None,
            'status': 'unknown',
            'detail': '',
            'registrationStatus': '',
            'legalRep': '',
            'registeredCapital': '',
            'establishDate': '',
            'raw': result
        }

        # MCP tools/call returns: {"result": {"content": [{"type": "text", "text": "..."}]}}
        content = result.get('result', {})
        if not isinstance(content, dict):
            return base

        text_parts = content.get('content', [])
        if not isinstance(text_parts, list):
            return base

        for part in text_parts:
            if not isinstance(part, dict) or part.get('type') != 'text':
                continue
            text = part.get('text', '')
            if not text:
                continue

            # Try to parse as JSON (企查查 returns JSON string in the text field)
            try:
                data = _json.loads(text)
            except (_json.JSONDecodeError, ValueError):
                data = {}

            if isinstance(data, dict):
                reg_status = data.get('登记状态', '')
                base['registrationStatus'] = reg_status
                base['legalRep'] = data.get('法定代表人', '')
                base['registeredCapital'] = data.get('注册资本', '')
                base['establishDate'] = data.get('成立日期', '')
                # Override company name with official name from QCC if available
                if data.get('企业名称'):
                    base['companyName'] = data['企业名称']
                if data.get('统一社会信用代码'):
                    base['creditCode'] = data['统一社会信用代码']

                if reg_status:
                    # Deregistered keywords
                    dereg_kw = ['注销', '吊销', '撤销']
                    active_kw = ['存续', '在营', '开业', '在册']

                    is_dereg = any(kw in reg_status for kw in dereg_kw)
                    is_active = any(kw in reg_status for kw in active_kw)

                    if is_dereg:
                        base['isDeregistered'] = True
                        base['status'] = 'deregistered'
                        base['detail'] = f'登记状态：{reg_status}'
                    elif is_active:
                        base['isDeregistered'] = False
                        base['status'] = 'active'
                        base['detail'] = f'登记状态：{reg_status}'
                    else:
                        base['detail'] = f'登记状态：{reg_status}（需人工核实）'
                else:
                    # Fallback: check raw text for keywords
                    dereg_kw = ['注销', '吊销']
                    active_kw = ['存续', '在营']
                    if any(kw in text for kw in dereg_kw):
                        base['isDeregistered'] = True
                        base['status'] = 'deregistered'
                        base['detail'] = '企业已注销/吊销'
                    elif any(kw in text for kw in active_kw):
                        base['isDeregistered'] = False
                        base['status'] = 'active'
                        base['detail'] = '企业存续在营'
                    else:
                        base['detail'] = text[:200]

                print(f'[QCC] {base["companyName"]} → {reg_status} | isDeregistered={base["isDeregistered"]}', file=sys.stderr)
                return base

        return base

    def _reply_json(self, status, body):
        """Send a JSON response."""
        resp = json.dumps(body, ensure_ascii=False)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(resp.encode('utf-8'))

    # ── AI chat proxy endpoint ───────────────────────────────────────────

    def do_POST(self):
        path_only = self.path.split('?')[0]
        if path_only in ('/api/chat',):
            self._handle_chat()
        elif path_only in ('/api/qcc/query',):
            self._handle_qcc_query()
        else:
            self.send_error(404, 'Not Found')

    def _handle_chat(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length).decode('utf-8')
            ctype = self.headers.get('Content-Type', '')

            if 'application/json' in ctype:
                req = json.loads(raw)
            else:
                from urllib.parse import parse_qs
                params = parse_qs(raw)
                req = json.loads(params.get('data', ['{}'])[0])

            provider = req.get('provider', 'qwen')
            api_key = req.get('apiKey', '')
            body = req.get('body', {})
            model = body.get('model', '?')

            print(f'[Chat] {provider}/{model} → calling API...', file=sys.stderr)
            status, resp_body = call_ai_api(provider, api_key, body)
            print(f'[Chat] API returned {status}', file=sys.stderr)

            resp = json.dumps({'status': status, 'body': resp_body}, ensure_ascii=False)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(resp.encode('utf-8'))

        except Exception as e:
            print(f'[Chat] Internal error: {e}', file=sys.stderr)
            err = json.dumps({
                'status': 502,
                'body': {'error': {'message': str(e), 'code': 'InternalError'}}
            })
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(err.encode('utf-8'))

    # ── CORS preflight ───────────────────────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    # ── Suppress the default access log ──────────────────────────────────

    def log_message(self, fmt, *args):
        pass


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print(f' Serving : {BASE_DIR}', file=sys.stderr)
    print(f' URL     : http://localhost:{PORT}', file=sys.stderr)
    print(f' Ready   : Ctrl+C to stop', file=sys.stderr)
    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n Stopped.', file=sys.stderr)
        server.server_close()
