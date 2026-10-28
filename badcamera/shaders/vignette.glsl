uniform float uStrength, uSize, uSoft, uDarken; uniform vec3 uTint;
void main() {
  vec3 c = texture(tex, uv).rgb;
  float m = smoothstep(uSize, uSize + max(uSoft, 1e-3), vdist(uv)) * uStrength;
  fragColor = vec4(mix(c, c * (1.0 - uDarken) + uTint, m), 1.0);
}
