// Centre-weighted average of a small image into one texel (camera metering).
void main() {
  ivec2 sz = textureSize(tex, 0);
  vec3 acc = vec3(0.0);
  float wsum = 0.0;
  for (int y = 0; y < sz.y; y++) for (int x = 0; x < sz.x; x++) {
    float w = 1.6 - vdist((vec2(x, y) + 0.5) / vec2(sz));
    acc += clamp(texelFetch(tex, ivec2(x, y), 0).rgb, 0.0, 1.0) * w;
    wsum += w;
  }
  fragColor = vec4(acc / wsum, 1.0);
}
