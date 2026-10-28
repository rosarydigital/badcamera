uniform sampler2D uC;
void main() {
  float y = texture(tex, uv).r;
  vec2 c = texture(uC, uv).gb - 128.0;
  fragColor = vec4(clamp(vec3(y + 1.402 * c.y, y - 0.344136 * c.x - 0.714136 * c.y, y + 1.772 * c.x) / 255.0, 0.0, 1.0), 1.0);
}
