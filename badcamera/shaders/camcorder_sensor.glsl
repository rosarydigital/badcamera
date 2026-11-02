// The camera in front of the tape: a small single CCD, soft zoom lens and automatic everything.
uniform sampler2D uAvg;
uniform vec2 uOffset;
uniform float uRoll, uZoom, uFocus, uKnee, uGain, uNoise, uMoire, uShadowChroma, uSeed, uHunt;
uniform vec3 uWB;
float rnd(vec2 p) { return hash(p + uSeed * 91.7); }
vec3 at(vec2 p) { return texture(tex, p).rgb; }
void main() {
  // Handheld sway, as a small move and roll of the whole frame.
  float aspect = uRes.x / uRes.y, c = cos(uRoll), s = sin(uRoll);
  vec2 p = (uv - 0.5) * vec2(aspect, 1.0);
  p = mat2(c, -s, s, c) * p / uZoom;
  p = p / vec2(aspect, 1.0) + 0.5 + uOffset;
  // Lens and autofocus softness: a small disc of samples.
  vec3 col = at(p) * 0.2;
  for (int i = 0; i < 8; i++) {
    float a = float(i) * 0.7854 + 0.3;
    col += at(p + uFocus * vec2(cos(a), sin(a)) / vec2(uRes.y * aspect, uRes.y)) * 0.1;
  }
  // Colour comes from a mosaic of filters, so fine luma detail turns into faint false colour.
  vec2 cell = vec2(1.0 / 720.0, 1.0 / 480.0);
  float y = luma(col), d = y - luma(at(p + cell));
  vec2 g = floor(p * vec2(720.0, 480.0));
  col += uMoire * d * vec3(mod(g.x, 2.0) - 0.5, mod(g.x + g.y, 2.0) - 0.5, mod(g.y, 2.0) - 0.5) * 2.0;

  // AGC: gain rises as the scene gets darker, and the sensor noise rises with it.
  float avg = texture(uAvg, vec2(0.5)).x;
  float dark = clamp((0.42 - avg) / 0.42, 0.0, 1.0);
  float gain = (1.0 + uGain * dark * 2.2) * (1.0 + uHunt * dark * dark * 0.35);  // in the dark, exposure can't settle
  col *= uWB * gain;
  y = luma(col);
  // Colour is turned down in shadows, where it would be nothing but noise.
  col = mix(vec3(y), col, mix(1.0, smoothstep(0.02, 0.32, y), uShadowChroma));
  // Short dynamic range: highlights roll off fast and clip to a slightly warm white.
  col = mix(col, 1.0 - exp(-(col - uKnee) / (1.0 - uKnee)) * (1.0 - uKnee), step(uKnee, col));
  col = min(col * vec3(1.0, 0.99, 0.97), vec3(1.0));
  float n = (rnd(gl_FragCoord.xy) - 0.5) + (rnd(gl_FragCoord.xy + 7.3) - 0.5);
  float amp = uNoise * gain * mix(1.6, 0.5, sqrt(clamp(y, 0.0, 1.0)));
  col += amp * n + amp * 0.6 * vec3(rnd(gl_FragCoord.xy + 1.1) - 0.5, 0.0, rnd(gl_FragCoord.xy + 2.2) - 0.5);
  fragColor = vec4(col, 1.0);
}
