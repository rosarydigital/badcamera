// CCD vertical smear: bright sources bleed along their whole sensor column.
uniform float uFalloff;
void main() {
  vec3 acc = vec3(0.0);
  for (int i = 0; i < 64; i++) {
    float y = (float(i) + 0.5) / 64.0;
    acc += texture(tex, vec2(uv.x, y)).rgb * exp(-abs(y - uv.y) * uFalloff);
  }
  fragColor = vec4(acc / 16.0, 1.0);
}
