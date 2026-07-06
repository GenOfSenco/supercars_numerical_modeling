const STOPS = [
  [38, 56, 115],
  [46, 134, 193],
  [111, 192, 179],
  [230, 210, 120],
];

export function pressureNorm(t) {
  return Math.max(0, Math.min(1, t));
}

function lerpStops(t) {
  t = pressureNorm(t);
  const idx = t * (STOPS.length - 1);
  const i0 = Math.floor(idx);
  const i1 = Math.min(i0 + 1, STOPS.length - 1);
  const f = idx - i0;
  const c0 = STOPS[i0];
  const c1 = STOPS[i1];
  return [
    Math.round(c0[0] * (1 - f) + c1[0] * f),
    Math.round(c0[1] * (1 - f) + c1[1] * f),
    Math.round(c0[2] * (1 - f) + c1[2] * f),
  ];
}

export function pressureCss(t) {
  const [r, g, b] = lerpStops(t);
  return `rgb(${r},${g},${b})`;
}

export function pressureRgb01(t) {
  const [r, g, b] = lerpStops(t);
  return { r: r / 255, g: g / 255, b: b / 255 };
}

export function pressureFromValue(value, minP, maxP) {
  const range = maxP - minP || 1;
  return pressureNorm((value - minP) / range);
}
