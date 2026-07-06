import numpy as np
import scipy.special
from aerogen.constants import BEZIER_X_PRO, BEZIER_X_SIMPLE, DIFFUSER_X_MAX, DIFFUSER_X_MIN, MAX_DIFFUSER_SLOPE, MAX_STEP_PRO, MODE_PRO, MODE_SIMPLE, PRO_DEFAULTS, SLOPE_LIMIT, STEP_TOL, Y_ENDPOINT, Y_MAX, Y_MIN

def normalize_y_params(mode, y_params):
    y = [float(v) for v in y_params]
    if mode == MODE_SIMPLE:
        if len(y) < 2:
            y = [0.1, 0.1]
        return [Y_ENDPOINT, y[0], y[1], Y_ENDPOINT]
    if len(y) < 6:
        y = (y + PRO_DEFAULTS)[:6]
    return y[:6]

def get_bezier_x_coords(mode):
    return BEZIER_X_SIMPLE if mode == MODE_SIMPLE else BEZIER_X_PRO

def bernstein_bezier(x_cp, y_cp, n_samples=50):
    x_cp = np.asarray(x_cp, dtype=float)
    y_cp = np.asarray(y_cp, dtype=float)
    degree = len(x_cp) - 1
    t = np.linspace(0.0, 1.0, n_samples)
    bx = np.zeros(n_samples)
    by = np.zeros(n_samples)
    for i in range(degree + 1):
        coeff = scipy.special.comb(degree, i) * (1.0 - t) ** (degree - i) * t ** i
        bx += coeff * x_cp[i]
        by += coeff * y_cp[i]
    return (bx, by)

def evaluate_bezier_curve(mode, y_params, n=50):
    x_cp = get_bezier_x_coords(mode)
    y_cp = normalize_y_params(mode, y_params)
    return bernstein_bezier(x_cp, y_cp, n_samples=n)

def max_diffuser_slope(mode, y_params, n_samples=200):
    bx, by = evaluate_bezier_curve(mode, y_params, n=n_samples)
    mask = (bx >= DIFFUSER_X_MIN) & (bx <= DIFFUSER_X_MAX)
    bx, by = (bx[mask], by[mask])
    if len(bx) < 2:
        return 0.0
    dx = np.diff(bx)
    dy = np.diff(by)
    dx = np.where(np.abs(dx) < 1e-12, 1e-12, dx)
    return float(np.max(np.abs(dy / dx)))

def sanitize_y_params(mode, y_params):
    y = [float(v) for v in y_params]
    if mode == MODE_SIMPLE:
        if len(y) < 2:
            y = [0.1, 0.1]
        y[0] = float(np.clip(y[0], Y_MIN, Y_MAX))
        y[1] = float(np.clip(y[1], Y_MIN, Y_MAX))
        return y[:2]
    if len(y) < 6:
        y = (y + PRO_DEFAULTS)[:6]
    y = [float(np.clip(v, Y_MIN, Y_MAX)) for v in y[:6]]
    for i in range(1, len(y)):
        y[i] = float(np.clip(y[i], y[i - 1] - MAX_STEP_PRO, y[i - 1] + MAX_STEP_PRO))
        y[i] = float(np.clip(y[i], Y_MIN, Y_MAX))
    for i in range(len(y) - 2, -1, -1):
        y[i] = float(np.clip(y[i], y[i + 1] - MAX_STEP_PRO, y[i + 1] + MAX_STEP_PRO))
        y[i] = float(np.clip(y[i], Y_MIN, Y_MAX))
    return y

def repair_y_params(mode, y_params):
    y = sanitize_y_params(mode, y_params)
    for _ in range(48):
        if max_diffuser_slope(mode, y) <= MAX_DIFFUSER_SLOPE + STEP_TOL:
            return y
        if mode == MODE_SIMPLE:
            y[0] = Y_ENDPOINT + (y[0] - Y_ENDPOINT) * 0.88
            y[1] = Y_ENDPOINT + (y[1] - Y_ENDPOINT) * 0.88
        else:
            for i in range(1, 5):
                y[i] = Y_ENDPOINT + (y[i] - Y_ENDPOINT) * 0.9
        y = sanitize_y_params(mode, y)
    return y

def validate_y_params(mode, y_params):
    y = normalize_y_params(mode, y_params)
    if any((val < Y_MIN - STEP_TOL or val > Y_MAX + STEP_TOL for val in y)):
        return False
    if mode == MODE_SIMPLE and y[2] - Y_ENDPOINT > SLOPE_LIMIT + STEP_TOL:
        return False
    if mode == MODE_PRO:
        for i in range(len(y) - 1):
            if abs(y[i + 1] - y[i]) - MAX_STEP_PRO > STEP_TOL:
                return False
    if max_diffuser_slope(mode, y_params) > MAX_DIFFUSER_SLOPE + STEP_TOL:
        return False
    return True

def separation_penalty(mode, y_params):
    excess = max_diffuser_slope(mode, y_params) - MAX_DIFFUSER_SLOPE
    if excess <= 0.0:
        return 0.0
    return 100000.0 + 10000.0 * excess

def param_bounds(mode):
    n = 6 if mode == MODE_PRO else 2
    return [(Y_MIN, Y_MAX)] * n
