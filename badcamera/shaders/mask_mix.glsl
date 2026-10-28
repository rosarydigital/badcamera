uniform sampler2D uB; uniform float uSize, uSoft; uniform int uInvert;
void main() {
  float m = smoothstep(uSize, uSize + max(uSoft, 1e-3), vdist(uv));
  fragColor = mix(texture(tex, uv), texture(uB, uv), uInvert == 1 ? 1.0 - m : m);
}
