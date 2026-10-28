const float PI = 3.14159265;
void main() {
  ivec2 p = ivec2(gl_FragCoord.xy), b = (p / 8) * 8, k = p - b;
  vec3 acc = vec3(0.0);
  for (int v = 0; v < 8; v++) {
    float cv = (v == 0 ? 0.70710678 : 1.0) * cos(float(2 * k.y + 1) * float(v) * PI / 16.0);
    for (int u = 0; u < 8; u++)
      acc += texelFetch(tex, b + ivec2(u, v), 0).rgb * (u == 0 ? 0.70710678 : 1.0) * cos(float(2 * k.x + 1) * float(u) * PI / 16.0) * cv;
  }
  fragColor = vec4(0.25 * acc + 128.0, 1.0);
}
