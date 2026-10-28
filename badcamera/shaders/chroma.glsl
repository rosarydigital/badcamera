uniform float uAmount; uniform int uRadial;
void main() {
  vec2 o = (uRadial == 1 ? (uv - 0.5) * 2.0 : vec2(1.0, 0.0)) * uAmount / uRes;
  fragColor = vec4(texture(tex, uv + o).r, texture(tex, uv).g, texture(tex, uv - o).b, 1.0);
}
