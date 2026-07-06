import { pressureCss, pressureFromValue } from "./colormap.js";

const TUNNEL_L = 5.0;
const TUNNEL_H = 2.0;
const Y_MIN = 0.05;
const Y_MAX = 0.40;

export class FlowViewer2D {
  constructor(canvas, { onControlDrag } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.data = null;
    this.ghost = null;
    this.mode = "simple";
    this.onControlDrag = onControlDrag;
    this.drag = null;
    this.layers = { pressure: true, arrows: true, particles: true, mesh: false, ghost: true };
    this.particles = Array.from({ length: 280 }, () => ({
      x: Math.random() * 0.3,
      y: 0.1 + Math.random() * 1.7,
      life: 40 + Math.random() * 60,
    }));
    this._dpr = 1;
    this._resize();
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(canvas.parentElement);
    canvas.addEventListener("mousedown", (e) => this._onDown(e));
    canvas.addEventListener("mousemove", (e) => this._onMove(e));
    window.addEventListener("mouseup", () => this._onUp());
    this._loop();
  }

  setMode(mode) {
    this.mode = mode;
  }

  _resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.floor(rect.width));
    const h = Math.max(1, Math.floor(rect.height));
    this._dpr = dpr;
    this.canvas.width = w * dpr;
    this.canvas.height = h * dpr;
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this._cssW = w;
    this._cssH = h;
  }

  resize() {
    this._resize();
  }

  setLayers(layers) {
    this.layers = { ...this.layers, ...layers };
  }

  update(data, ghost = null) {
    this.data = data;
    this.ghost = ghost;
  }

  _tx(x) { return (x / TUNNEL_L) * this._cssW; }
  _ty(y) { return (1 - y / TUNNEL_H) * this._cssH; }

  _screenToWorld(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    const lx = clientX - rect.left;
    const ly = clientY - rect.top;
    return {
      x: (lx / rect.width) * TUNNEL_L,
      y: (1 - ly / rect.height) * TUNNEL_H,
      lx,
      ly,
    };
  }

  _handles() {
    if (!this.data?.control_x?.length) return [];
    const { control_x: cx, control_y: cy } = this.data;
    const idxs = this.mode === "simple" ? [1, 2] : cx.map((_, i) => i);
    return idxs.map((i) => {
      const paramIdx = this.mode === "simple" ? i - 1 : i;
      const y = this.drag?.paramIdx === paramIdx ? this.drag.y : cy[i];
      return { i, paramIdx, x: cx[i], y };
    });
  }

  _hitHandle(lx, ly) {
    const r = 14;
    let best = null;
    let bestD = r;
    for (const h of this._handles()) {
      const dx = lx - this._tx(h.x);
      const dy = ly - this._ty(h.y);
      const d = Math.hypot(dx, dy);
      if (d < bestD) {
        bestD = d;
        best = h;
      }
    }
    return best;
  }

  _onDown(e) {
    const { lx, ly } = this._screenToWorld(e.clientX, e.clientY);
    const hit = this._hitHandle(lx, ly);
    if (hit) {
      this.drag = hit;
      this.canvas.style.cursor = "grabbing";
      e.preventDefault();
    }
  }

  _onMove(e) {
    const { lx, ly, y } = this._screenToWorld(e.clientX, e.clientY);
    if (this.drag) {
      const ny = Math.max(Y_MIN, Math.min(Y_MAX, y));
      this.drag.y = ny;
      if (this.onControlDrag) this.onControlDrag(this.drag.paramIdx, ny);
      return;
    }
    this.canvas.style.cursor = this._hitHandle(lx, ly) ? "grab" : "default";
  }

  _onUp() {
    this.drag = null;
    this.canvas.style.cursor = "default";
  }

  _floorY(px) {
    if (!this.data?.bezier_x?.length) return 0.05;
    const xs = this.data.bezier_x, ys = this.data.bezier_y;
    for (let i = 0; i < xs.length - 1; i++) {
      if (px >= xs[i] && px <= xs[i + 1]) {
        const t = (px - xs[i]) / (xs[i + 1] - xs[i]);
        return ys[i] * (1 - t) + ys[i + 1] * t;
      }
    }
    return px < 1.5 ? 0 : px > 3.5 ? 0 : 0.05;
  }

  _vel(px, py) {
    const g = this.data?.grid;
    const u0 = this.data?.u_in ?? 30;
    if (!g || px < 0 || px > TUNNEL_L || py < 0 || py > TUNNEL_H) return { u: u0, v: 0 };

    const gx = (px / TUNNEL_L) * (g.nx - 1);
    const gy = (py / TUNNEL_H) * (g.ny - 1);
    const x0 = Math.floor(gx), y0 = Math.floor(gy);
    const x1 = Math.min(x0 + 1, g.nx - 1), y1 = Math.min(y0 + 1, g.ny - 1);
    const fx = gx - x0, fy = gy - y0;
    const i = (y, x) => y * g.nx + x;
    const b = (a, b, c, d) => (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy;
    return {
      u: b(g.u[i(y0, x0)], g.u[i(y0, x1)], g.u[i(y1, x0)], g.u[i(y1, x1)]),
      v: b(g.v[i(y0, x0)], g.v[i(y0, x1)], g.v[i(y1, x0)], g.v[i(y1, x1)]),
    };
  }

  _drawHandles() {
    const handles = this._handles();
    if (!handles.length) return;
    const { ctx } = this;
    for (const h of handles) {
      const sx = this._tx(h.x);
      const sy = this._ty(h.y);
      const active = this.drag?.paramIdx === h.paramIdx;
      ctx.beginPath();
      ctx.arc(sx, sy, active ? 9 : 7, 0, Math.PI * 2);
      ctx.fillStyle = active ? "#1d4ed8" : "#ffffff";
      ctx.fill();
      ctx.strokeStyle = "#1d4ed8";
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(sx - 5, sy);
      ctx.lineTo(sx + 5, sy);
      ctx.moveTo(sx, sy - 5);
      ctx.lineTo(sx, sy + 5);
      ctx.strokeStyle = active ? "#fff" : "#1d4ed8";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }

  _draw() {
    const { ctx, data } = this;
    const w = this._cssW;
    const h = this._cssH;
    ctx.fillStyle = "#e8ebf0";
    ctx.fillRect(0, 0, w, h);
    if (!data?.elements) {
      ctx.fillStyle = "#6b7280";
      ctx.font = "13px Segoe UI, sans-serif";
      ctx.fillText("Run solver to display flow field", 20, 40);
      return;
    }

    const { nodes_x: nx, nodes_y: ny, elements, pressure } = data;
    const minP = Math.min(...pressure), maxP = Math.max(...pressure);

    if (this.layers.pressure) {
      for (let e = 0; e < elements.length; e++) {
        const [n1, n2, n3] = elements[e];
        ctx.beginPath();
        ctx.moveTo(this._tx(nx[n1]), this._ty(ny[n1]));
        ctx.lineTo(this._tx(nx[n2]), this._ty(ny[n2]));
        ctx.lineTo(this._tx(nx[n3]), this._ty(ny[n3]));
        ctx.closePath();
        ctx.fillStyle = pressureCss(pressureFromValue(pressure[e], minP, maxP));
        ctx.fill();
      }
    }

    if (this.layers.mesh) {
      ctx.strokeStyle = "rgba(255,255,255,0.35)";
      ctx.lineWidth = 0.4;
      for (let e = 0; e < elements.length; e++) {
        const [n1, n2, n3] = elements[e];
        ctx.beginPath();
        ctx.moveTo(this._tx(nx[n1]), this._ty(ny[n1]));
        ctx.lineTo(this._tx(nx[n2]), this._ty(ny[n2]));
        ctx.lineTo(this._tx(nx[n3]), this._ty(ny[n3]));
        ctx.closePath();
        ctx.stroke();
      }
    }

    if (this.layers.arrows && data.grid) {
      ctx.strokeStyle = "rgba(28,35,51,0.55)";
      ctx.lineWidth = 1;
      const cols = 22, rows = 9;
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const px = (c + 0.5) / cols * TUNNEL_L;
          const py = (r + 0.5) / rows * TUNNEL_H;
          if (py < this._floorY(px) + 0.04) continue;
          const { u, v } = this._vel(px, py);
          const sp = Math.hypot(u, v);
          if (sp < 0.4) continue;
          const sc = 0.011;
          const x0 = this._tx(px), y0 = this._ty(py);
          const x1 = this._tx(px + u * sc), y1 = this._ty(py + v * sc);
          ctx.beginPath();
          ctx.moveTo(x0, y0);
          ctx.lineTo(x1, y1);
          ctx.stroke();
        }
      }
    }

    if (this.layers.particles && data.grid) {
      ctx.fillStyle = "rgba(28,35,51,0.75)";
      for (const p of this.particles) {
        const vel = this._vel(p.x, p.y);
        p.x += vel.u * 0.003;
        p.y += vel.v * 0.003;
        p.life -= 0.4;
        const fh = this._floorY(p.x);
        if (p.x > TUNNEL_L || p.y > TUNNEL_H || p.y < fh + 0.02 || p.life <= 0) {
          p.x = Math.random() * 0.12;
          p.y = 0.08 + Math.random() * 1.6;
          p.life = 40 + Math.random() * 60;
        }
        ctx.beginPath();
        ctx.arc(this._tx(p.x), this._ty(p.y), 1.3, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    if (data.bezier_x?.length) {
      ctx.fillStyle = "#3d4450";
      ctx.strokeStyle = "#1c2333";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(this._tx(0), this._ty(0));
      ctx.lineTo(this._tx(1.5), this._ty(0));
      ctx.lineTo(this._tx(1.5), this._ty(data.bezier_y[0]));
      for (let i = 0; i < data.bezier_x.length; i++) {
        ctx.lineTo(this._tx(data.bezier_x[i]), this._ty(data.bezier_y[i]));
      }
      ctx.lineTo(this._tx(3.5), this._ty(data.bezier_y.at(-1)));
      ctx.lineTo(this._tx(3.5), this._ty(0));
      ctx.lineTo(this._tx(5), this._ty(0));
      ctx.lineTo(this._tx(5), this._ty(-0.08));
      ctx.lineTo(this._tx(0), this._ty(-0.08));
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }

    this._drawHandles();

    if (this.layers.ghost && this.ghost?.bezier_x?.length) {
      ctx.strokeStyle = "#f59e0b";
      ctx.lineWidth = 2.5;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      for (let i = 0; i < this.ghost.bezier_x.length; i++) {
        const x = this._tx(this.ghost.bezier_x[i]), y = this._ty(this.ghost.bezier_y[i]);
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  _loop() {
    this._draw();
    requestAnimationFrame(() => this._loop());
  }
}
