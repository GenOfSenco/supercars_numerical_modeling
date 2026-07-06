import numpy as np
from aerogen.constants import MAX_DIFFUSER_SLOPE, RHO, U_IN
from aerogen.geometry import max_diffuser_slope

def compute_metrics(mode, y_params, downforce, floor_x, floor_p, u_in, avg_velocity):
    slope = max_diffuser_slope(mode, y_params)
    slope_deg = float(np.rad2deg(np.arctan(slope)))
    separation_risk = float(np.clip(slope / MAX_DIFFUSER_SLOPE, 0.0, 2.0) * 100.0)
    q_inf = 0.5 * RHO * u_in ** 2
    ref_area = 2.0
    cl = downforce / (q_inf * ref_area) if q_inf > 1e-09 else 0.0
    cp_recovery = 0.0
    if len(floor_p) >= 2:
        p_in = floor_p[0]
        p_out = floor_p[-1]
        cp_recovery = float((p_out - p_in) / q_inf) if q_inf > 1e-09 else 0.0
    return {'max_slope_deg': slope_deg, 'separation_risk_pct': separation_risk, 'cl_proxy': float(cl), 'cp_recovery': cp_recovery, 'dynamic_pressure': float(q_inf), 'avg_underbody_velocity': float(avg_velocity)}
