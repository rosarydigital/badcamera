// Drifting film light leak, screened over the frame, strongest towards the edges.
uniform float uStrength, uSpeed, uScale, uEdge; uniform vec3 uColorA, uColorB;
void main() {
  vec3 c = texture(tex, uv).rgb;
  float t = uTime * uSpeed;
  vec2 p = uv * vec2(uRes.x / uRes.y, 1.0) * uScale;
  float n = fbm(p + vec2(t * 0.7, -t * 0.4)), m = fbm(p * 0.6 - vec2(t * 0.3, t * 0.5) + 9.3);
  float edge = mix(1.0, smoothstep(0.2, 1.0, abs(uv.x - 0.5) * 2.0 + 0.25 * (1.0 - uv.y)), uEdge);
  float leak = smoothstep(0.32, 0.72, n) * edge * (0.65 + 0.35 * sin(uTime * uSpeed * 2.3 + m * 6.0));
  vec3 L = mix(uColorA, uColorB, smoothstep(0.3, 0.7, m)) * leak * uStrength;
  fragColor = vec4(1.0 - (1.0 - clamp(c, 0.0, 1.0)) * (1.0 - clamp(L, 0.0, 1.0)), 1.0);
}
