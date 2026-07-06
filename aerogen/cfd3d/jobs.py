import json
import threading
import uuid
from pathlib import Path
from aerogen.cfd3d.solver3d import run_cfd3d
from aerogen.json_util import json_sanitize
from aerogen.constants import U_IN
from aerogen.geometry import sanitize_y_params
from aerogen.physics import compute_metrics
RUNS_ROOT = Path(__file__).resolve().parent.parent.parent / 'cfd_runs'
RUNS_ROOT.mkdir(exist_ok=True)
_job_lock = threading.Lock()
_job_state = {'id': None, 'status': 'idle', 'progress': 0, 'message': 'Idle', 'result': None, 'error': None}

def _job_update(**kwargs):
    with _job_lock:
        _job_state.update(kwargs)

def get_job_status():
    with _job_lock:
        return dict(_job_state)

def _job_thread(mode, y_params, u_in):
    job_id = str(uuid.uuid4())[:8]
    run_dir = RUNS_ROOT / job_id
    run_dir.mkdir(parents=True, exist_ok=True)

    def progress(pct, msg):
        _job_update(progress=pct, message=msg)
    try:
        y_params = sanitize_y_params(mode, y_params)
        _job_update(id=job_id, status='running', progress=5, message='Building 3D grid…', error=None, result=None)
        outcome = run_cfd3d(mode, y_params, u_in=u_in, max_iter=4000, progress_cb=progress)
        metrics = compute_metrics(mode, y_params, outcome['downforce'], outcome.get('floor_pressure_x', []), outcome.get('floor_pressure_p', []), u_in, outcome.get('avg_velocity', u_in))
        result = {'job_id': job_id, 'run_dir': str(run_dir), **outcome, **metrics, 'u_in': float(u_in), 'y_params': [float(v) for v in y_params]}
        (run_dir / 'result.json').write_text(json.dumps(json_sanitize(result), indent=2), encoding='utf-8')
        _job_update(status='done', progress=100, message='3D CFD complete', result=result)
    except Exception as exc:
        _job_update(status='error', message=str(exc), error=str(exc), progress=0)

def start_cfd3d_job(mode, y_params, u_in=U_IN):
    with _job_lock:
        if _job_state['status'] == 'running':
            return (False, '3D CFD job already running')
    t = threading.Thread(target=_job_thread, args=(mode, y_params, float(u_in)), daemon=True)
    t.start()
    return (True, '3D Python CFD started')
