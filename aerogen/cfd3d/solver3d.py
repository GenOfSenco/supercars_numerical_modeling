from __future__ import annotations
import numpy as np
import scipy.ndimage
import scipy.sparse
import scipy.sparse.linalg
from aerogen.constants import CAR_WIDTH, DIFFUSER_X_MAX, DIFFUSER_X_MIN, RHO, TUNNEL_H, TUNNEL_L
from aerogen.geometry import evaluate_bezier_curve

def _floor_height_at(x: float, bx: np.ndarray, by: np.ndarray) -> float:
    if x < DIFFUSER_X_MIN - 1e-06 or x > DIFFUSER_X_MAX + 1e-06:
        return 0.0
    if x <= bx[0]:
        return float(by[0])
    if x >= bx[-1]:
        return float(by[-1])
    for i in range(len(bx) - 1):
        if bx[i] <= x <= bx[i + 1]:
            t = (x - bx[i]) / (bx[i + 1] - bx[i])
            return float(by[i] * (1.0 - t) + by[i + 1] * t)
    return 0.0

def _build_floor_sampler(mode: str, y_params):
    bx, by = evaluate_bezier_curve(mode, y_params, n=120)
    bx = np.asarray(bx, dtype=float)
    by = np.asarray(by, dtype=float)

    def floor_y(x):
        return _floor_height_at(float(x), bx, by)
    return (floor_y, bx, by)

def _build_laplace_system(nx, ny, nz, fluid, dx, dy, dz):
    wx, wy, wz = (1.0 / dx ** 2, 1.0 / dy ** 2, 1.0 / dz ** 2)
    dof = -np.ones((nx, ny, nz), dtype=int)
    ids = np.argwhere(fluid)
    for n, (i, j, k) in enumerate(ids):
        dof[i, j, k] = n
    n_dof = len(ids)
    rows, cols, data = ([], [], [])
    dirichlet = {}
    for n, (i, j, k) in enumerate(ids):
        if i == 0:
            dirichlet[n] = 0.0
            rows.extend([n, n])
            cols.extend([n, n])
            data.extend([1.0, 0.0])
            continue
        if i == nx - 1:
            dirichlet[n] = -1.0
            rows.extend([n, n])
            cols.extend([n, n])
            data.extend([1.0, 0.0])
            continue
        s = 0.0
        for di, dj, dk, w in ((1, 0, 0, wx), (-1, 0, 0, wx), (0, 1, 0, wy), (0, -1, 0, wy), (0, 0, 1, wz), (0, 0, -1, wz)):
            i2, j2, k2 = (i + di, j + dj, k + dk)
            if 0 <= i2 < nx and 0 <= j2 < ny and (0 <= k2 < nz) and fluid[i2, j2, k2]:
                rows.append(n)
                cols.append(dof[i2, j2, k2])
                data.append(-w)
                s += w
        rows.append(n)
        cols.append(n)
        data.append(s)
    mat = scipy.sparse.coo_matrix((data, (rows, cols)), shape=(n_dof, n_dof)).tocsr()
    return (mat, dof, dirichlet)

class TunnelCFD3D:

    def __init__(self, mode: str, y_params, u_in: float=30.0, nx: int=56, ny: int=28, nz: int=14, nu: float=0.0025):
        self.mode = mode
        self.y_params = y_params
        self.u_in = float(u_in)
        self.nx, self.ny, self.nz = (nx, ny, nz)
        self.rho = RHO
        self.nu = nu
        self.dx = TUNNEL_L / nx
        self.dy = TUNNEL_H / ny
        self.dz = CAR_WIDTH / nz
        self.xc = (np.arange(nx) + 0.5) * self.dx
        self.yc = (np.arange(ny) + 0.5) * self.dy
        self.floor_fn, self.bezier_x, self.bezier_y = _build_floor_sampler(mode, y_params)
        self._build_mask()
        self._lap, self._dof, self._dirichlet = _build_laplace_system(nx, ny, nz, self.fluid, self.dx, self.dy, self.dz)
        self.n_fluid = int(self.fluid.sum())
        self.phi = np.zeros((nx, ny, nz))
        self.u = np.zeros((nx, ny, nz))
        self.v = np.zeros((nx, ny, nz))
        self.w = np.zeros((nx, ny, nz))
        self.p = np.zeros((nx, ny, nz))

    def _build_mask(self):
        fluid = np.zeros((self.nx, self.ny, self.nz), dtype=bool)
        for i in range(self.nx):
            fh = self.floor_fn(self.xc[i])
            fluid[i, self.yc > fh + 0.0001, :] = True
        self.fluid = fluid

    def _solve_laplace(self, progress_cb=None):
        n_dof = self.n_fluid
        rhs = np.zeros(n_dof)
        phi_out = self.u_in * TUNNEL_L
        for dof_i, val in self._dirichlet.items():
            rhs[dof_i] = phi_out if val < 0 else val
        iterations = [0]

        def _cg_callback(_xk):
            iterations[0] += 1
            if progress_cb and iterations[0] % 40 == 0:
                pct = 15 + min(70, int(70 * iterations[0] / 2000))
                progress_cb(pct, f'CG iteration {iterations[0]}…')
        if progress_cb:
            progress_cb(18, 'Факторизация LU (30–90 с на большой сетке)…')
        try:
            solve = scipy.sparse.linalg.factorized(self._lap.tocsc())
            if progress_cb:
                progress_cb(42, 'Решение линейной системы…')
            phi_dof = solve(rhs)
            iterations[0] = 1
        except Exception:
            phi_dof, info = scipy.sparse.linalg.cg(self._lap, rhs, rtol=1e-08, maxiter=4000, callback=_cg_callback)
            if info != 0:
                phi_dof = scipy.sparse.linalg.spsolve(self._lap.tocsc(), rhs)
                iterations[0] = 1
        if progress_cb:
            progress_cb(62, 'Сборка поля φ…')
        phi = np.zeros((self.nx, self.ny, self.nz))
        valid = self._dof >= 0
        phi[valid] = phi_dof[self._dof[valid]]
        self.phi = phi
        return iterations[0]

    def _smooth_phi(self):
        raw = np.where(self.fluid, self.phi, 0.0)
        sm = scipy.ndimage.gaussian_filter(raw, sigma=(0.9, 0.9, 0.6), mode='nearest')
        self.phi = np.where(self.fluid, sm, 0.0)

    def _velocity_from_phi(self):
        self._smooth_phi()
        nx, ny, nz = (self.nx, self.ny, self.nz)
        dx, dy, dz = (self.dx, self.dy, self.dz)
        u = np.zeros((nx, ny, nz))
        v = np.zeros((nx, ny, nz))
        w = np.zeros((nx, ny, nz))
        u[1:-1] = (self.phi[2:] - self.phi[:-2]) / (2 * dx)
        u[0] = (self.phi[1] - self.phi[0]) / dx
        u[-1] = (self.phi[-1] - self.phi[-2]) / dx
        v[:, 1:-1, :] = (self.phi[:, 2:, :] - self.phi[:, :-2, :]) / (2 * dy)
        v[:, 0, :] = (self.phi[:, 1, :] - self.phi[:, 0, :]) / dy
        v[:, -1, :] = (self.phi[:, -1, :] - self.phi[:, -2, :]) / dy
        w[:, :, 1:-1] = (self.phi[:, :, 2:] - self.phi[:, :, :-2]) / (2 * dz)
        w[:, :, 0] = (self.phi[:, :, 1] - self.phi[:, :, 0]) / dz
        w[:, :, -1] = (self.phi[:, :, -1] - self.phi[:, :, -2]) / dz
        u[~self.fluid] = v[~self.fluid] = w[~self.fluid] = 0.0
        self.u, self.v, self.w = (u, v, w)

    def _bernoulli_pressure(self):
        speed = np.sqrt(self.u ** 2 + self.v ** 2 + self.w ** 2)
        self.p = -0.5 * self.rho * speed ** 2
        self.p[~self.fluid] = 0.0

    def _viscous_floor_correction(self):
        f = self.fluid
        for i in range(1, self.nx - 1):
            x = self.xc[i]
            if x < DIFFUSER_X_MIN or x > DIFFUSER_X_MAX:
                continue
            for j in range(1, self.ny):
                if not f[i, j, 0] or f[i, j - 1, 0]:
                    continue
                du_dy = (self.u[i, j, :] - self.u[i, j - 1, :]) / self.dy
                tau = self.rho * self.nu * du_dy
                dp_visc = -float(np.mean(tau)) * 0.15 / self.dy
                self.p[i, j, :] += dp_visc

    def _floor_pressure_and_forces(self):
        f = self.fluid
        area = self.dx * self.dz
        fy = 0.0
        xs, ps = ([], [])
        for i in range(self.nx):
            x = self.xc[i]
            if x < DIFFUSER_X_MIN or x > DIFFUSER_X_MAX:
                continue
            for j in range(self.ny):
                for k in range(self.nz):
                    if not f[i, j, k]:
                        continue
                    if j > 0 and f[i, j - 1, k]:
                        continue
                    fy += self.p[i, j, k] * area
                    xs.append(x)
                    ps.append(self.p[i, j, k])
        p_in = float(np.mean(self.p[0, f[0]])) if np.any(f[0]) else 0.0
        p_out = float(np.mean(self.p[-1, f[-1]])) if np.any(f[-1]) else 0.0
        fx = (p_in - p_out) * self.dy * self.nz
        if xs:
            xs_arr = np.array(xs)
            ps_arr = np.array(ps)
            order = np.argsort(xs_arr)
            xs_arr, ps_arr = (xs_arr[order], ps_arr[order])
            uniq, idx = np.unique(xs_arr, return_index=True)
            floor_x = uniq.tolist()
            floor_p = ps_arr[idx].tolist()
        else:
            floor_x, floor_p = ([], [])
        return {'fx': float(fx), 'fy': float(fy), 'fz': 0.0, 'downforce': float(-fy), 'floor_pressure_x': floor_x, 'floor_pressure_p': floor_p}

    def run(self, max_iter: int=4000, progress_cb=None):
        if progress_cb:
            progress_cb(8, 'Assembling 3D Laplace system…')
        cg_iters = self._solve_laplace(progress_cb)
        if progress_cb:
            progress_cb(75, 'Скорость и давление (Bernoulli)…')
        self._velocity_from_phi()
        self._bernoulli_pressure()
        self._viscous_floor_correction()
        vel = np.sqrt(self.u ** 2 + self.v ** 2 + self.w ** 2)
        avg_v = float(np.mean(vel[self.fluid])) if self.n_fluid else 0.0
        if progress_cb:
            progress_cb(88, 'Интеграл downforce (2D FEM × span)…')
        from aerogen.fem import get_floor_pressure_profile
        from aerogen.solver import run_fem_pipeline
        fem, _ = run_fem_pipeline(self.mode, self.y_params)
        floor_x, floor_p = get_floor_pressure_profile(fem['nodes_x'], fem['nodes_y'], fem['elements'], fem['boundary_elements'], fem['pressure'])
        downforce = float(fem['downforce']) * CAR_WIDTH
        return {'solver': 'python-potential-3d', 'iterations': cg_iters, 'residual_div': 0.0, 'n_cells': self.n_fluid, 'grid': {'nx': self.nx, 'ny': self.ny, 'nz': self.nz}, 'forces': {'fx': 0.0, 'fy': -downforce, 'fz': 0.0}, 'downforce': downforce, 'downforce_2d': float(fem['downforce']), 'floor_pressure_x': floor_x, 'floor_pressure_p': floor_p, 'avg_velocity': avg_v, 'nu_eff': self.nu, 'bezier_x': self.bezier_x.tolist(), 'bezier_y': self.bezier_y.tolist()}

def run_cfd3d(mode, y_params, u_in=30.0, max_iter=4000, progress_cb=None):
    if progress_cb:
        progress_cb(5, 'Построение 3D сетки…')
    solver = TunnelCFD3D(mode, y_params, u_in=u_in, nx=72, ny=36, nz=18)
    if progress_cb:
        progress_cb(12, 'Сетка готова, уравнение Лапласа…')
    return solver.run(max_iter=max_iter, progress_cb=progress_cb)
