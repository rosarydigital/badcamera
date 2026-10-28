uniform sampler2D uBlur; uniform float uAmount;
void main() {
  vec3 c = texture(tex, uv).rgb, b = texture(uBlur, uv).rgb;
  fragColor = vec4(c + (c - b) * uAmount * (1.0 - abs(2.0 * clamp(luma(c), 0.0, 1.0) - 1.0)), 1.0);
}
