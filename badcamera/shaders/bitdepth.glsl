uniform float uLevels, uAmount; uniform int uDither;
const float BAYER[16] = float[16](0., 8., 2., 10., 12., 4., 14., 6., 3., 11., 1., 9., 15., 7., 13., 5.);
void main() {
  vec3 c = texture(tex, uv).rgb;
  ivec2 p = ivec2(gl_FragCoord.xy) % 4;
  float t = uDither == 1 ? hash(gl_FragCoord.xy + float(uFrame % 997) * 1.37) - 0.5 : uDither == 2 ? (BAYER[p.y * 4 + p.x] + 0.5) / 16.0 - 0.5 : 0.0;
  float n = max(uLevels - 1.0, 1.0);
  fragColor = vec4(floor(clamp(c, 0.0, 1.0) * n + 0.5 + t * uAmount) / n, 1.0);
}
