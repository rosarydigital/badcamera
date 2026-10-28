uniform float uAmount, uSize, uShadow; uniform int uMono, uMode, uAnimate;
void main() {
  vec3 c = texture(tex, uv).rgb;
  vec2 cell = floor(gl_FragCoord.xy / max(uSize, 1.0));
  vec2 seed = uAnimate == 1 ? vec2(float(uFrame % 1009) * 7.31, float(uFrame % 997) * 3.17) : vec2(0.0);
  vec3 n = vec3(hash(cell + seed), hash(cell + seed + 101.7), hash(cell + seed + 233.1)) - 0.5;
  if (uMono == 1) n = vec3(n.r);
  n *= uAmount * mix(1.0, 1.0 - clamp(luma(c), 0.0, 1.0), uShadow);
  fragColor = vec4(uMode == 0 ? c + n : blendOverlay(clamp(c, 0.0, 1.0), 0.5 + n), 1.0);
}
