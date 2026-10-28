// One texel per block: best (dx,dy) in px so that cur(block) ~ prev(block + d).
uniform sampler2D uPrev; uniform float uBlock; uniform int uSearch;
void main() {
  vec2 res = vec2(textureSize(tex, 0)), origin = floor(gl_FragCoord.xy) * uBlock, best_d = vec2(0.0);
  float best = 1e9;
  int st = max(1, uSearch / 3);  // coarse search keeps 720p60 headroom
  for (int dy = -uSearch; dy <= uSearch; dy += st) for (int dx = -uSearch; dx <= uSearch; dx += st) {
    float sad = 0.002 * float(dx * dx + dy * dy);  // prefer small motion on ties
    for (int j = 0; j < 4; j++) for (int i = 0; i < 4; i++) {
      vec2 q = origin + (vec2(i, j) + 0.5) * uBlock / 4.0;
      sad += dot(abs(texture(tex, q / res).rgb - texture(uPrev, (q + vec2(dx, dy)) / res).rgb), vec3(1.0));
    }
    if (sad < best) { best = sad; best_d = vec2(dx, dy); }
  }
  fragColor = vec4(best_d, 0.0, 1.0);
}
