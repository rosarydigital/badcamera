uniform float uExposure, uContrast, uSaturation, uTemp, uTint;
uniform vec3 uLift, uGamma, uGain;
void main() {
  vec3 c = texture(tex, uv).rgb * exp2(uExposure);
  c *= vec3(1.0 + 0.2 * uTemp, 1.0 - 0.2 * uTint, 1.0 - 0.2 * uTemp);
  c = c * (1.0 + uGain) + uLift * (1.0 - c);
  c = pow(max(c, 0.0), 1.0 / max(1.0 + uGamma, vec3(0.05)));
  c = (c - 0.5) * (1.0 + uContrast) + 0.5;
  fragColor = vec4(mix(vec3(luma(c)), c, 1.0 + uSaturation), 1.0);
}
