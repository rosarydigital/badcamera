uniform sampler2D uOver; uniform float uStrength, uDrift; uniform int uMode;
void main() {
  // Slow drift / breathing so a fixed texture doesn't sit frozen on the image.
  vec2 q = (uv - 0.5) * (1.0 - 0.04 * uDrift * (0.5 + 0.5 * sin(uTime * 0.37))) + 0.5 + uDrift * 0.04 * vec2(sin(uTime * 0.23), cos(uTime * 0.31));
  vec3 b = texture(tex, uv).rgb, o = texture(uOver, q).rgb * (1.0 - uDrift * 0.25 * (0.5 + 0.5 * sin(uTime * 0.9))), r;
  if (uMode == 0) r = 1.0 - (1.0 - clamp(b, 0.0, 1.0)) * (1.0 - o);
  else if (uMode == 1) r = b + o;
  else if (uMode == 2) r = blendOverlay(clamp(b, 0.0, 1.0), o);
  else r = b * o;
  fragColor = vec4(mix(b, r, uStrength), 1.0);
}
