// The camera waking up, shutting down or running flat. Runs before effects, so the tape records all of it.
uniform float uBlur, uExpose, uTint, uKill, uBlink;
void main() {
  vec3 c = texture(tex, uv).rgb * 0.2;
  vec2 k = uBlur / uRes.y * vec2(uRes.y / uRes.x, 1.0);
  for (int i = 0; i < 8; i++) {
    float a = float(i) * 0.7854;
    c += texture(tex, uv + k * vec2(cos(a), sin(a))).rgb * 0.1;
  }
  c *= uExpose;
  c = mix(c, c * vec3(0.8, 0.95, 1.3), uTint);  // white balance hasn't found the room yet
  // Low-battery icon, blinking in the corner: a cell with one bar left.
  vec2 p = (uv - vec2(0.9, 0.86)) * vec2(uRes.x / uRes.y, 1.0) * 28.0;
  float shell = step(abs(p.x), 1.0) * step(abs(p.y), 0.5) * (1.0 - step(abs(p.x), 0.86) * step(abs(p.y), 0.36));
  float nub = step(abs(p.x + 1.1), 0.1) * step(abs(p.y), 0.2);
  float bar = step(abs(p.x - 0.62), 0.2) * step(abs(p.y), 0.26);
  c = mix(c, vec3(1.0), uBlink * max(max(shell, nub), bar));
  fragColor = vec4(c * (1.0 - uKill), 1.0);
}
