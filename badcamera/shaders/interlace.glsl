uniform sampler2D uPrev; uniform float uAmount, uLine; uniform int uField;
void main() {
  vec4 cur = texture(tex, uv);
  bool other = mod(floor(gl_FragCoord.y / max(uLine, 1.0)), 2.0) == float(uField);  // this field was captured a frame earlier
  fragColor = other ? mix(cur, texture(uPrev, uv), uAmount) : cur;
}
