import numpy as np
import scipy.sparse
import scipy.sparse.linalg
from scipy.interpolate import LinearNDInterpolator
from aerogen.constants import J_EPS, RHO, TUNNEL_H, TUNNEL_L

def solve_potential_flow(nodes_x, nodes_y, elements, boundary_elements, u_in):
    n_nodes = len(nodes_x)
    x1 = nodes_x[elements[:, 0]]
    y1 = nodes_y[elements[:, 0]]
    x2 = nodes_x[elements[:, 1]]
    y2 = nodes_y[elements[:, 1]]
    x3 = nodes_x[elements[:, 2]]
    y3 = nodes_y[elements[:, 2]]
    jacobian = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
    abs_j = np.where(np.abs(jacobian) < J_EPS, J_EPS, np.abs(jacobian))
    b1, b2, b3 = (y2 - y3, y3 - y1, y1 - y2)
    c1, c2, c3 = (x3 - x2, x1 - x3, x2 - x1)
    b = np.column_stack([b1, b2, b3])
    c = np.column_stack([c1, c2, c3])
    i_arr, j_arr, v_arr = ([], [], [])
    for i in range(3):
        for j in range(3):
            i_arr.append(elements[:, i])
            j_arr.append(elements[:, j])
            v_arr.append((b[:, i] * b[:, j] + c[:, i] * c[:, j]) / (2.0 * abs_j))
    k = scipy.sparse.coo_matrix((np.concatenate(v_arr), (np.concatenate(i_arr), np.concatenate(j_arr))), shape=(n_nodes, n_nodes)).tocsr()
    f = np.zeros(n_nodes)
    if 'Inlet' in boundary_elements:
        inlet = boundary_elements['Inlet']
        n1, n2 = (inlet[:, 0], inlet[:, 1])
        dx = nodes_x[n1] - nodes_x[n2]
        dy = nodes_y[n1] - nodes_y[n2]
        length = np.sqrt(dx ** 2 + dy ** 2)
        length = np.where(length < J_EPS, J_EPS, length)
        contrib = 0.5 * length * -u_in
        np.add.at(f, n1, contrib)
        np.add.at(f, n2, contrib)
    if 'Outlet' in boundary_elements:
        outlet_nodes = np.unique(boundary_elements['Outlet'])
        penalty = scipy.sparse.coo_matrix((np.full(len(outlet_nodes), 1000000000000.0), (outlet_nodes, outlet_nodes)), shape=(n_nodes, n_nodes)).tocsr()
        k = k + penalty
        f[outlet_nodes] = 0.0
    used = np.unique(elements)
    unused = np.setdiff1d(np.arange(n_nodes), used)
    if len(unused) > 0:
        k = k + scipy.sparse.coo_matrix((np.ones(len(unused)), (unused, unused)), shape=(n_nodes, n_nodes)).tocsr()
        f[unused] = 0.0
    return scipy.sparse.linalg.spsolve(k, f)

def compute_velocities_and_pressures(nodes_x, nodes_y, elements, phi):
    x1, y1 = (nodes_x[elements[:, 0]], nodes_y[elements[:, 0]])
    x2, y2 = (nodes_x[elements[:, 1]], nodes_y[elements[:, 1]])
    x3, y3 = (nodes_x[elements[:, 2]], nodes_y[elements[:, 2]])
    jacobian = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
    sign = np.sign(jacobian)
    sign[sign == 0] = 1.0
    jacobian = np.where(np.abs(jacobian) < J_EPS, J_EPS * sign, jacobian)
    b1, b2, b3 = (y2 - y3, y3 - y1, y1 - y2)
    c1, c2, c3 = (x3 - x2, x1 - x3, x2 - x1)
    p1, p2, p3 = (phi[elements[:, 0]], phi[elements[:, 1]], phi[elements[:, 2]])
    u = (b1 * p1 + b2 * p2 + b3 * p3) / jacobian
    v = (c1 * p1 + c2 * p2 + c3 * p3) / jacobian
    pressure = -0.5 * RHO * (u ** 2 + v ** 2)
    return (u, v, pressure)

def integrate_downforce(nodes_x, nodes_y, elements, boundary_elements, pressure):
    edge_to_tri = {}
    for tri_idx, (v1, v2, v3) in enumerate(elements):
        for edge in ((min(v1, v2), max(v1, v2)), (min(v2, v3), max(v2, v3)), (min(v3, v1), max(v3, v1))):
            edge_to_tri[edge] = tri_idx
    f_down = 0.0
    if 'Floor' not in boundary_elements:
        return f_down
    for n1, n2 in boundary_elements['Floor']:
        x_mid = 0.5 * (nodes_x[n1] + nodes_x[n2])
        if 1.5 + 1e-05 < x_mid < 3.5 - 1e-05:
            edge = (min(n1, n2), max(n1, n2))
            if edge in edge_to_tri:
                f_down += -pressure[edge_to_tri[edge]] * abs(nodes_x[n2] - nodes_x[n1])
    return f_down

def get_floor_pressure_profile(nodes_x, nodes_y, elements, boundary_elements, pressure):
    edge_to_tri = {}
    for tri_idx, (v1, v2, v3) in enumerate(elements):
        for edge in ((min(v1, v2), max(v1, v2)), (min(v2, v3), max(v2, v3)), (min(v3, v1), max(v3, v1))):
            edge_to_tri[edge] = tri_idx
    xs, ps = ([], [])
    if 'Floor' in boundary_elements:
        for n1, n2 in boundary_elements['Floor']:
            x_mid = 0.5 * (nodes_x[n1] + nodes_x[n2])
            if 1.5 + 1e-05 < x_mid < 3.5 - 1e-05:
                edge = (min(n1, n2), max(n1, n2))
                if edge in edge_to_tri:
                    xs.append(x_mid)
                    ps.append(pressure[edge_to_tri[edge]])
    if not xs:
        return ([], [])
    order = np.argsort(xs)
    return (np.array(xs)[order].tolist(), np.array(ps)[order].tolist())

def interpolate_to_regular_grid(nodes_x, nodes_y, elements, u, v, pressure, nx=80, ny=25):
    cx = np.mean(nodes_x[elements], axis=1)
    cy = np.mean(nodes_y[elements], axis=1)
    max_samples = 2500
    if len(cx) > max_samples:
        stride = int(np.ceil(len(cx) / max_samples))
        cx, cy = (cx[::stride], cy[::stride])
        u, v, pressure = (u[::stride], v[::stride], pressure[::stride])
    points = np.column_stack([cx, cy])
    x_grid = np.linspace(0.0, TUNNEL_L, nx)
    y_grid = np.linspace(0.0, TUNNEL_H, ny)
    xx, yy = np.meshgrid(x_grid, y_grid)
    grid_pts = np.column_stack([xx.ravel(), yy.ravel()])
    iu = LinearNDInterpolator(points, u, fill_value=0.0)
    iv = LinearNDInterpolator(points, v, fill_value=0.0)
    ip = LinearNDInterpolator(points, pressure, fill_value=0.0)
    gu = np.nan_to_num(iu(grid_pts).reshape(ny, nx), nan=0.0)
    gv = np.nan_to_num(iv(grid_pts).reshape(ny, nx), nan=0.0)
    gp = np.nan_to_num(ip(grid_pts).reshape(ny, nx), nan=0.0)
    return {'nx': nx, 'ny': ny, 'x': x_grid.tolist(), 'y': y_grid.tolist(), 'u': gu.flatten().tolist(), 'v': gv.flatten().tolist(), 'p': gp.flatten().tolist()}
