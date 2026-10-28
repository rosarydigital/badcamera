uniform int uNearest;
void main() {
  vec2 s = vec2(textureSize(tex, 0));
  fragColor = texture(tex, uNearest == 1 ? (floor(uv * s) + 0.5) / s : uv);
}
