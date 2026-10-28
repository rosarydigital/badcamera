uniform float uAmount; uniform int uMode;
void main() {
  vec3 c = texture(tex, uv).rgb;
  fragColor = vec4(mix(c, vec3(uMode == 1 ? max(c.r, max(c.g, c.b)) : luma(c)), uAmount), 1.0);
}
