uniform vec2 uDir; uniform float uSigma;
void main() {
  vec2 px = uDir / vec2(textureSize(tex, 0));
  float s = max(uSigma, 0.01);
  int r = int(min(ceil(s * 3.0), 48.0));
  vec4 acc = texture(tex, uv); float w = 1.0;
  for (int i = 1; i <= r; i++) {
    float k = exp(-0.5 * float(i * i) / (s * s));
    acc += k * (texture(tex, uv + px * float(i)) + texture(tex, uv - px * float(i)));
    w += 2.0 * k;
  }
  fragColor = acc / w;
}
