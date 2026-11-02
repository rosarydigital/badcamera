// Stage 1: picture to video signal. Two fields are woven from the current and previous frame, then YIQ and,
// on a composite path, chroma modulated onto the subcarrier at exactly four samples per cycle.
uniform sampler2D uPrev;
uniform float uInterlace;
uniform int uPal, uComposite, uField;
vec3 yiq(vec3 c) { return mat3(0.299, 0.596, 0.211, 0.587, -0.274, -0.523, 0.114, -0.322, 0.312) * c; }
void main() {
  ivec2 p = ivec2(gl_FragCoord.xy);
  int line = textureSize(tex, 0).y - 1 - p.y;
  bool second = (line & 1) == 1;
  vec3 c = texture(tex, uv).rgb;
  if (second) c = mix(c, texture(uPrev, uv).rgb, uInterlace);
  vec3 s = yiq(c);
  // Band-limit colour before modulating it, as an encoder does, so it doesn't alias into luma.
  vec2 d = vec2(1.0) / vec2(textureSize(tex, 0));
  vec2 iq = s.yz * 0.4;
  iq += 0.2 * (yiq(texture(tex, uv + vec2(d.x, 0.0)).rgb).yz + yiq(texture(tex, uv - vec2(d.x, 0.0)).rgb).yz);
  iq += 0.1 * (yiq(texture(tex, uv + vec2(d.x * 2.0, 0.0)).rgb).yz + yiq(texture(tex, uv - vec2(d.x * 2.0, 0.0)).rgb).yz);
  int fieldLine = line >> 1, flip = uPal == 1 ? 0 : (fieldLine + (second ? 1 : 0) + uField) & 1;
  int n = (p.x + flip * 2) & 3;
  float co = n == 0 ? 1.0 : n == 2 ? -1.0 : 0.0, si = n == 1 ? 1.0 : n == 3 ? -1.0 : 0.0;
  float v = uPal == 1 && (fieldLine & 1) == 1 ? -1.0 : 1.0;  // PAL flips one colour axis every line
  float comp = s.x + iq.x * co + iq.y * si * v;
  fragColor = vec4(s.x, iq, uComposite == 1 ? comp : s.x);
}
