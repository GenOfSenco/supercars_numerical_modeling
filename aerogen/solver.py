import numpy as np
from aerogen.constants import MODE_PRO, U_IN
from aerogen.fem import compute_velocities_and_pressures, get_floor_pressure_profile, integrate_downforce, interpolate_to_regular_grid, solve_potential_flow
from aerogen.geometry import evaluate_bezier_curve, get_bezier_x_coords, max_diffuser_slope, normalize_y_params, repair_y_params, sanitize_y_params, separation_penalty, validate_y_params
from aerogen.mesh import generate_mesh
eval_cache = {}
current_u_in = U_IN

def set_inlet_velocity(u_in):
    global current_u_in
    current_u_in = float(u_in)

def get_inlet_velocity():
    return current_u_in

def make_cache_key(mode, y_params):
    y = normalize_y_params(mode, y_params)
    u_tag = round(current_u_in, 3)
    if mode == MODE_PRO:
        return (mode, u_tag, *tuple((round(v, 5) for v in y)))
    return (mode, u_tag, round(y[1], 5), round(y[2], 5))

def run_fem_pipeline(mode, y_params, auto_repair=False):
    y_params = repair_y_params(mode, y_params) if auto_repair else sanitize_y_params(mode, y_params)
    cache_key = make_cache_key(mode, y_params)
    if cache_key in eval_cache:
        return (eval_cache[cache_key], y_params)
    nodes_x, nodes_y, elements, boundary_elements = generate_mesh(mode, y_params)
    phi = solve_potential_flow(nodes_x, nodes_y, elements, boundary_elements, current_u_in)
    u, v, pressure = compute_velocities_and_pressures(nodes_x, nodes_y, elements, phi)
    f_down = integrate_downforce(nodes_x, nodes_y, elements, boundary_elements, pressure)
    record = {'obj': -f_down, 'downforce': f_down, 'nodes_x': nodes_x, 'nodes_y': nodes_y, 'elements': elements, 'boundary_elements': boundary_elements, 'phi': phi, 'u': u, 'v': v, 'pressure': pressure, 'repaired': True}
    eval_cache[cache_key] = record
    return (record, y_params)

def objective_function(mode, y_params):
    y_params = [float(v) for v in y_params]
    if not validate_y_params(mode, y_params):
        return 100000.0
    sep = separation_penalty(mode, y_params)
    if sep > 0.0:
        return sep
    cache_key = make_cache_key(mode, y_params)
    if cache_key in eval_cache:
        return eval_cache[cache_key]['obj']
    try:
        record, _ = run_fem_pipeline(mode, y_params)
        return record['obj']
    except Exception:
        return 100000.0

def build_solve_response(mode, y_params):
    from aerogen.physics import compute_metrics
    raw = sanitize_y_params(mode, y_params)
    try:
        data, y_used = run_fem_pipeline(mode, raw, auto_repair=False)
    except Exception as exc:
        return {'error': str(exc)}
    slope = max_diffuser_slope(mode, raw)
    y_cp = normalize_y_params(mode, raw)
    opt_vars = raw if mode == MODE_PRO else raw[:2]
    grid = interpolate_to_regular_grid(data['nodes_x'], data['nodes_y'], data['elements'], data['u'], data['v'], data['pressure'])
    bx, by = evaluate_bezier_curve(mode, raw)
    floor_x, floor_p = get_floor_pressure_profile(data['nodes_x'], data['nodes_y'], data['elements'], data['boundary_elements'], data['pressure'])
    vel_mag = np.sqrt(data['u'] ** 2 + data['v'] ** 2)
    metrics = compute_metrics(mode, raw, data['downforce'], floor_x, floor_p, current_u_in, float(np.mean(vel_mag)))
    from aerogen.validation import conference_metrics
    conf = conference_metrics(mode, raw, float(data['downforce']), metrics['separation_risk_pct'], current_u_in)
    return {'mode': mode, 'y_params': [float(v) for v in opt_vars], 'slope_warning': bool(slope > 0.2125 + 1e-05), 'control_x': get_bezier_x_coords(mode).tolist(), 'control_y': [float(v) for v in y_cp], 'downforce': float(data['downforce']), 'max_clearance': float(max(y_cp)), 'u_in': float(current_u_in), 'nodes_x': data['nodes_x'].tolist(), 'nodes_y': data['nodes_y'].tolist(), 'elements': data['elements'].tolist(), 'pressure': data['pressure'].tolist(), 'velocity_mag': vel_mag.tolist(), 'bezier_x': bx.tolist(), 'bezier_y': by.tolist(), 'floor_pressure_x': floor_x, 'floor_pressure_p': floor_p, 'grid': grid, **metrics, **conf}
