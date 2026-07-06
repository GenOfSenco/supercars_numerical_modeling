import json
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from aerogen.cfd3d.jobs import get_job_status, start_cfd3d_job
from aerogen.constants import MODE_PRO, MODE_SIMPLE, WEB_DIR_NAME
from aerogen.mesh import init_gmsh, shutdown_gmsh
from aerogen.optimization import optimize_diffuser
from aerogen.solver import build_solve_response, set_inlet_velocity
from aerogen.json_util import json_sanitize
from aerogen.validation import run_validation_report
WEB_ROOT = Path(__file__).resolve().parent.parent / WEB_DIR_NAME
STATIC_ROOT = WEB_ROOT / 'static'

class AerogenHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        return

    def _safe_write(self, data: bytes):
        try:
            self.wfile.write(data)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, payload, status=200):
        body = json.dumps(json_sanitize(payload)).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self._safe_write(body)

    def _send_file(self, path: Path):
        if not path.is_file():
            self.send_response(404)
            self.end_headers()
            return
        mime, _ = mimetypes.guess_type(str(path))
        data = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime or 'application/octet-stream')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self._safe_write(data)

    def do_GET(self):
        route = self.path.split('?', 1)[0]
        if route in ('/', '/index.html'):
            return self._send_file(WEB_ROOT / 'index.html')
        if route.startswith('/static/'):
            rel = route[len('/static/'):]
            target = (STATIC_ROOT / rel).resolve()
            static_resolved = STATIC_ROOT.resolve()
            if static_resolved not in target.parents and target != static_resolved:
                self.send_response(403)
                self.end_headers()
                return
            return self._send_file(target)
        if route == '/api/cfd3d/status':
            return self._send_json(get_job_status())
        if route == '/api/validate':
            try:
                qs = parse_qs(urlparse(self.path).query)
                mode = qs.get('mode', [MODE_SIMPLE])[0]
                if mode not in (MODE_SIMPLE, MODE_PRO):
                    mode = MODE_SIMPLE
                return self._send_json({'status': 'success', **run_validation_report(mode=mode)})
            except Exception as exc:
                return self._send_json({'status': 'error', 'message': str(exc)}, status=500)
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        params = json.loads(self.rfile.read(length).decode('utf-8'))
        if self.path == '/api/solve':
            mode = params.get('mode', MODE_SIMPLE)
            if mode not in (MODE_SIMPLE, MODE_PRO):
                mode = MODE_SIMPLE
            if 'u_in' in params:
                set_inlet_velocity(float(params['u_in']))
            y_params = params.get('y_params', [0.1, 0.1])
            result = build_solve_response(mode, y_params)
            if 'error' in result:
                self._send_json({'status': 'error', 'message': result['error']})
            else:
                self._send_json({'status': 'success', **result})
            return
        if self.path == '/api/cfd3d/start':
            try:
                mode = params.get('mode', MODE_SIMPLE)
                if mode not in (MODE_SIMPLE, MODE_PRO):
                    mode = MODE_SIMPLE
                if 'u_in' in params:
                    set_inlet_velocity(float(params['u_in']))
                y_params = params.get('y_params', [0.1, 0.1])
                ok, message = start_cfd3d_job(mode, y_params, float(params.get('u_in', 30)))
                if ok:
                    self._send_json({'status': 'success', 'message': message})
                else:
                    self._send_json({'status': 'error', 'message': message})
            except Exception as exc:
                self._send_json({'status': 'error', 'message': str(exc)})
            return
        if self.path == '/api/optimize':
            try:
                mode = params.get('mode', MODE_SIMPLE)
                if 'u_in' in params:
                    set_inlet_velocity(float(params['u_in']))
                y_init = params.get('y_params', [0.1, 0.1])
                outcome = optimize_diffuser(mode, y_init, set_inlet_velocity)
                if outcome is None:
                    self._send_json({'status': 'error', 'message': 'Optimization produced no valid steps.'})
                else:
                    self._send_json({'status': 'success', 'mode': mode, **outcome})
            except Exception as exc:
                self._send_json({'status': 'error', 'message': str(exc)})
            return
        self.send_response(404)
        self.end_headers()

def run_server(port=8000):
    init_gmsh()
    httpd = HTTPServer(('', port), AerogenHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        shutdown_gmsh()
