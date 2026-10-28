// On-camera flash: hot, slightly cool centre falling off to a dark background.
uniform float uStrength, uFalloff, uCool; uniform vec2 uCenter;
void main() {
  vec2 d = (uv - uCenter) * vec2(uRes.x / uRes.y, 1.0);
  float f = exp(-dot(d, d) * uFalloff);
  vec3 c = texture(tex, uv).rgb * (1.0 + uStrength * 2.5 * f) * mix(1.0 - uStrength * 0.6, 1.0, f);
  fragColor = vec4(mix(c, c * vec3(0.92, 0.98, 1.1), uCool * f), 1.0);
}
