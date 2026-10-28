uniform float uSigmaS, uSigmaL;
void main() {
  vec2 px = 1.0 / vec2(textureSize(tex, 0));
  vec3 c0 = texture(tex, uv).rgb, acc = vec3(0.0);
  float wsum = 0.0;
  int r = int(clamp(ceil(uSigmaS * 2.0), 1.0, 8.0));
  for (int j = -r; j <= r; j++) for (int i = -r; i <= r; i++) {
    vec3 c = texture(tex, uv + vec2(i, j) * px).rgb, d = c - c0;
    float w = exp(-float(i * i + j * j) / (2.0 * uSigmaS * uSigmaS) - dot(d, d) / (2.0 * uSigmaL * uSigmaL));
    acc += c * w; wsum += w;
  }
  fragColor = vec4(acc / wsum, 1.0);
}
