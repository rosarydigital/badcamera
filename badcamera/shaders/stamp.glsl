uniform sampler2D uStamp; uniform vec4 uRect; uniform float uOpacity;  // uRect: x, y, w, h of the text block in uv
void main() {
  vec3 c = texture(tex, uv).rgb;
  vec2 s = (uv - uRect.xy) / uRect.zw;
  vec4 t = any(lessThan(s, vec2(0.0))) || any(greaterThan(s, vec2(1.0))) ? vec4(0.0) : texture(uStamp, s);
  fragColor = vec4(mix(c, t.rgb, t.a * uOpacity), 1.0);
}
