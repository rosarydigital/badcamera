// Forward 8x8 DCT + quantization; each output texel is one coefficient of its block.
uniform float uQ[64];
const float PI = 3.14159265;
void main() {
  ivec2 p = ivec2(gl_FragCoord.xy), b = (p / 8) * 8, k = p - b, sz = textureSize(tex, 0);
  vec3 acc = vec3(0.0);
  for (int y = 0; y < 8; y++) {
    float cy = cos(float(2 * y + 1) * float(k.y) * PI / 16.0);
    for (int x = 0; x < 8; x++)
      acc += (texelFetch(tex, min(b + ivec2(x, y), sz - 1), 0).rgb - 128.0) * cos(float(2 * x + 1) * float(k.x) * PI / 16.0) * cy;
  }
  acc *= 0.25 * (k.x == 0 ? 0.70710678 : 1.0) * (k.y == 0 ? 0.70710678 : 1.0);
  float q = uQ[k.y * 8 + k.x];
  fragColor = vec4(floor(acc / q + 0.5) * q, 1.0);
}
