// A consumer CRT viewed up close: curved glass, visible scan structure that thickens with brightness, phosphor mask and glow.
uniform sampler2D uGlow, uPersist;
uniform float uCurve, uMask, uScan, uBloom, uLines, uFlicker, uPersistence, uCorner;
vec2 bend(vec2 p) {
  vec2 c = p * 2.0 - 1.0;
  c *= 1.0 + uCurve * dot(c.yx, c.yx) * vec2(0.08, 0.12);
  return c * 0.5 + 0.5;
}
void main() {
  vec2 p = bend(uv);
  if (p.x < 0.0 || p.x > 1.0 || p.y < 0.0 || p.y > 1.0) { fragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
  vec2 e = (p - 0.5) * 2.0;
  float corner = 1.0 - smoothstep(1.0 - uCorner, 1.0, max(abs(e.x), abs(e.y)) * 0.6 + 0.4 * length(e) * 0.72);
  vec3 c = texture(tex, p).rgb;
  c = mix(c, max(c, texture(uPersist, p).rgb * 0.85), uPersistence);  // phosphor decay
  // Scanlines: the beam is wider when bright, so highlights close the gaps.
  float L = uLines, f = fract(p.y * L) - 0.5, y = luma(c);
  float width = mix(0.26, 0.5, sqrt(clamp(y, 0.0, 1.0)));
  float fit = smoothstep(2.2, 4.0, uRes.y / L);  // too few output pixels per line would turn scanlines into moire
  c *= mix(1.0, 1.15 * exp(-f * f / (2.0 * width * width * 0.6)), uScan * fit);
  // Slot mask: red, green and blue stripes in staggered triads.
  float cell = max(uRes.y / 1080.0 * 3.0, 3.0), x = gl_FragCoord.x / cell;
  float row = floor(gl_FragCoord.y / cell * 0.5);
  x += mod(row, 2.0) * 0.5;
  float k = fract(x);
  vec3 mask = vec3(k < 0.333 ? 1.0 : 0.0, k >= 0.333 && k < 0.666 ? 1.0 : 0.0, k >= 0.666 ? 1.0 : 0.0);
  c *= mix(vec3(1.0), mask * 2.1 + 0.3, uMask);
  c += uBloom * texture(uGlow, p).rgb;
  c *= 1.0 + uFlicker * 0.03 * sin(uTime * 376.99);
  fragColor = vec4(c * corner, 1.0);
}
