uniform float uCell;
void main() {
  vec2 cell = max(uCell, 1.0) / uRes, base = floor(uv / cell) * cell;
  fragColor = 0.25 * (texture(tex, base + cell * vec2(0.25, 0.25)) + texture(tex, base + cell * vec2(0.75, 0.25))
                    + texture(tex, base + cell * vec2(0.25, 0.75)) + texture(tex, base + cell * vec2(0.75, 0.75)));
}
