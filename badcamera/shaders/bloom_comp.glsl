uniform sampler2D uBloom; uniform float uAmount, uWhite; uniform vec3 uTint;
void main() {
  vec3 c = texture(tex, uv).rgb + texture(uBloom, uv).rgb * uTint * uAmount;
  c = c * (1.0 + c / max(uWhite * uWhite, 1e-3)) / (1.0 + c);  // extended Reinhard; white point 1 = identity
  fragColor = vec4(c, 1.0);
}
