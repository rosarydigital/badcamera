// Bleach bypass: the retained silver acts like a B&W layer overlaid on the colour image (NVIDIA SDK formulation).
uniform float uAmount, uContrast, uSaturation;
void main() {
  vec3 c = clamp(texture(tex, uv).rgb, 0.0, 1.0);
  float lum = dot(c, vec3(0.25, 0.65, 0.1));
  vec3 b = vec3(lum);
  vec3 r = mix(2.0 * c * b, 1.0 - 2.0 * (1.0 - b) * (1.0 - c), clamp(10.0 * (lum - 0.45), 0.0, 1.0));
  r = mix(c, r, uAmount);
  r = mix(vec3(luma(r)), r, 1.0 + uSaturation);
  fragColor = vec4((r - 0.5) * (1.0 + uContrast) + 0.5, 1.0);
}
