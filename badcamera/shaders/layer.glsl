// A second picture on top of the first: picture-in-picture, inserts and CCTV walls.
uniform sampler2D uTop;
uniform vec4 uRect;
uniform float uOpacity;
void main() {
  vec3 c = texture(tex, uv).rgb;
  vec2 p = (uv - uRect.xy) / uRect.zw;
  if (p.x >= 0.0 && p.x <= 1.0 && p.y >= 0.0 && p.y <= 1.0) c = mix(c, texture(uTop, p).rgb, uOpacity);
  fragColor = vec4(c, 1.0);
}
