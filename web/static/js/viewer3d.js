import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { pressureFromValue, pressureRgb01 } from "./colormap.js";

const CAR_WIDTH = 1.8;
const TUNNEL_L = 5.0;
const TUNNEL_H = 2.0;

export class TunnelViewer3D {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xe8ebf0);
    this.scene.fog = new THREE.Fog(0xe8ebf0, 8, 18);

    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 50);
    this.camera.position.set(3.5, 2.2, 4.5);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.target.set(2.5, 0.4, 0);
    this.controls.autoRotate = false;
    this.controls.autoRotateSpeed = 0.5;

    const hemi = new THREE.HemisphereLight(0xffffff, 0x8a94a6, 0.9);
    this.scene.add(hemi);
    const dir = new THREE.DirectionalLight(0xffffff, 0.65);
    dir.position.set(4, 6, 2);
    dir.castShadow = true;
    this.scene.add(dir);

    this.tunnelGroup = new THREE.Group();
    this.floorGroup = new THREE.Group();
    this.ghostGroup = new THREE.Group();
    this.scene.add(this.tunnelGroup, this.floorGroup, this.ghostGroup);

    this._buildTunnelFrame();
    this._resize();
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(canvas.parentElement);
    this._animate();
  }

  _buildTunnelFrame() {
    const box = new THREE.BoxGeometry(TUNNEL_L, TUNNEL_H, CAR_WIDTH);
    const edges = new THREE.EdgesGeometry(box);
    const line = new THREE.LineSegments(
      edges,
      new THREE.LineBasicMaterial({ color: 0x9aa3b2, transparent: true, opacity: 0.55 })
    );
    line.position.set(TUNNEL_L / 2, TUNNEL_H / 2, 0);
    this.tunnelGroup.add(line);

    const inlet = new THREE.Mesh(
      new THREE.PlaneGeometry(0.02, TUNNEL_H),
      new THREE.MeshBasicMaterial({ color: 0x1d4ed8, transparent: true, opacity: 0.25 })
    );
    inlet.position.set(0, TUNNEL_H / 2, 0);
    this.tunnelGroup.add(inlet);
  }

  _extrudeFloor(bezierX, bezierY, pressureSamples, ghost = false) {
    if (!bezierX?.length) return new THREE.Group();

    const halfW = CAR_WIDTH / 2;
    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    shape.lineTo(1.5, 0);
    shape.lineTo(1.5, bezierY[0]);
    for (let i = 0; i < bezierX.length; i++) shape.lineTo(bezierX[i], bezierY[i]);
    shape.lineTo(3.5, bezierY[bezierY.length - 1]);
    shape.lineTo(3.5, 0);
    shape.lineTo(5, 0);
    shape.lineTo(5, -0.02);
    shape.lineTo(0, -0.02);
    shape.closePath();

    const geom = new THREE.ExtrudeGeometry(shape, {
      depth: CAR_WIDTH,
      bevelEnabled: false,
      curveSegments: 24,
    });
    geom.translate(0, 0, -halfW);

    const pos = geom.attributes.position;
    const colors = new Float32Array(pos.count * 3);
    const floorP = pressureSamples || [];
    const minP = floorP.length ? Math.min(...floorP) : 0;
    const maxP = floorP.length ? Math.max(...floorP) : 1;

    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      let p = minP;
      if (floorP.length && bezierX.length) {
        let best = 0, bestD = 1e9;
        for (let j = 0; j < bezierX.length; j++) {
          const d = Math.abs(bezierX[j] - x);
          if (d < bestD) { bestD = d; best = j; }
        }
        p = floorP[Math.min(best, floorP.length - 1)] ?? minP;
      }
      const rgb = ghost
        ? { r: 0.96, g: 0.62, b: 0.04 }
        : pressureRgb01(pressureFromValue(p, minP, maxP));
      colors[i * 3] = rgb.r;
      colors[i * 3 + 1] = rgb.g;
      colors[i * 3 + 2] = rgb.b;
    }
    geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));

    const mat = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.55,
      metalness: ghost ? 0.1 : 0.25,
      transparent: ghost,
      opacity: ghost ? 0.45 : 1,
      side: THREE.DoubleSide,
    });

    const mesh = new THREE.Mesh(geom, mat);
    mesh.castShadow = !ghost;
    mesh.receiveShadow = true;

    const group = new THREE.Group();
    group.add(mesh);

    if (ghost) {
      const topLine = new THREE.BufferGeometry().setFromPoints(
        bezierX.map((x, i) => new THREE.Vector3(x, bezierY[i], 0))
      );
      const line = new THREE.Line(
        topLine,
        new THREE.LineDashedMaterial({ color: 0xf59e0b, dashSize: 0.08, gapSize: 0.05 })
      );
      line.computeLineDistances();
      group.add(line);
    }
    return group;
  }

  setAutoRotate(on) {
    this.controls.autoRotate = !!on;
  }

  update(data, ghost = null) {
    this.floorGroup.clear();
    this.ghostGroup.clear();

    if (data?.bezier_x) {
      this.floorGroup.add(
        this._extrudeFloor(data.bezier_x, data.bezier_y, data.floor_pressure_p, false)
      );
    }
    if (ghost?.bezier_x) {
      this.ghostGroup.add(
        this._extrudeFloor(ghost.bezier_x, ghost.bezier_y, null, true)
      );
    }
  }

  resize() {
    this._resize();
  }

  _resize() {
    const w = Math.max(1, this.canvas.clientWidth);
    const h = Math.max(1, this.canvas.clientHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _animate() {
    requestAnimationFrame(() => this._animate());
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
