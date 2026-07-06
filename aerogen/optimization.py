import numpy as np
import scipy.optimize
from aerogen.constants import MODE_PRO
from aerogen.geometry import param_bounds, repair_y_params, sanitize_y_params
from aerogen.solver import make_cache_key, objective_function, run_fem_pipeline

def optimize_diffuser(mode, y_init, _u_in_setter=None):
    y_init = repair_y_params(mode, sanitize_y_params(mode, y_init))
    bounds = param_bounds(mode)
    history = []
    seen = set()

    def record(params):
        clean = repair_y_params(mode, sanitize_y_params(mode, params))
        key = make_cache_key(mode, clean)
        if key in seen:
            return clean
        seen.add(key)
        try:
            data, _ = run_fem_pipeline(mode, clean, auto_repair=True)
            history.append({'y_params': [float(v) for v in clean], 'downforce': float(data['downforce'])})
        except Exception:
            pass
        return clean
    record(y_init)

    def obj(vec):
        return objective_function(mode, vec)
    de_result = scipy.optimize.differential_evolution(obj, bounds, x0=np.array(y_init), maxiter=24 if mode == MODE_PRO else 18, polish=False, seed=42, tol=0.02, mutation=(0.6, 1.2), recombination=0.8, callback=lambda xk, convergence: record(xk))
    seed = repair_y_params(mode, sanitize_y_params(mode, de_result.x.tolist()))
    record(seed)
    nm_result = scipy.optimize.minimize(obj, x0=seed, method='Nelder-Mead', options={'maxiter': 60 if mode == MODE_PRO else 80, 'xatol': 0.001}, callback=lambda xk: record(xk))
    optimal = repair_y_params(mode, sanitize_y_params(mode, nm_result.x.tolist()))
    record(optimal)
    if not history:
        return None
    initial_df = history[0]['downforce']
    opt_df = history[-1]['downforce']
    improvement = (opt_df - initial_df) / abs(initial_df) * 100.0 if abs(initial_df) > 1e-09 else 0.0
    return {'history': history, 'initial': {'y_params': [float(v) for v in y_init], 'downforce': float(initial_df)}, 'optimal': {'y_params': [float(v) for v in optimal], 'downforce': float(opt_df), 'improvement_pct': float(improvement)}}
