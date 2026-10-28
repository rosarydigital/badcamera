// Pseudo lens flare: ghosts and a halo of the bright-pass image, mirrored through the lens centre.
uniform int uGhosts; uniform float uDispersal, uHalo, uHaloWidth, uChroma, uRainbow;
vec3 spectrum(float x) { return 0.5 + 0.5 * cos(6.2831853 * (x + vec3(0.0, 0.33, 0.67))); }
vec3 split(vec2 p, vec2 dir) { return vec3(texture(tex, p + dir * uChroma).r, texture(tex, p).g, texture(tex, p - dir * uChroma).b); }
void main() {
  vec2 tc = 1.0 - uv, gv = (vec2(0.5) - tc) * uDispersal, dir = normalize(gv + 1e-5);
  vec3 acc = vec3(0.0);
  for (int i = 0; i < uGhosts; i++) {
    vec2 o = fract(tc + gv * float(i));
    float d = length(vec2(0.5) - o) / 0.70711;
    acc += split(o, dir) * pow(max(1.0 - d, 0.0), 10.0) * mix(vec3(1.0), spectrum(d * 1.3 + float(i) * 0.17), uRainbow);
  }
  vec2 ho = fract(tc + dir * uHaloWidth * vec2(uRes.y / uRes.x, 1.0));
  float hd = length(vec2(0.5) - ho) / 0.70711;
  acc += split(ho, dir) * pow(max(1.0 - hd, 0.0), 5.0) * uHalo * mix(vec3(1.0), spectrum(hd), uRainbow);
  fragColor = vec4(acc, 1.0);
}
