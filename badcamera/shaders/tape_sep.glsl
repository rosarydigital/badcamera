// Stage 2: split the composite signal back into luma and chroma with a line comb, the way a VCR's input does.
// Fine vertical detail gets mistaken for colour (cross-colour) and colour leaves dots in luma (dot crawl).
uniform int uPal, uComposite, uField;
void main() {
  ivec2 p = ivec2(gl_FragCoord.xy);
  ivec2 size = textureSize(tex, 0);
  vec4 c = texelFetch(tex, p, 0);
  if (uComposite == 0) { fragColor = vec4(c.xyz, 1.0); return; }
  float y;
  if (uPal == 1) {  // PAL's V axis alternates by line, so a simple line comb can't cancel it: notch the subcarrier instead
    float a = texelFetch(tex, p + ivec2(-2, 0), 0).a + texelFetch(tex, p + ivec2(2, 0), 0).a;
    float b = texelFetch(tex, p + ivec2(-1, 0), 0).a + texelFetch(tex, p + ivec2(1, 0), 0).a;
    y = (a + 2.0 * b + 2.0 * c.a) / 8.0;
  } else {
    float up = texelFetch(tex, ivec2(p.x, min(p.y + 2, size.y - 1)), 0).a, dn = texelFetch(tex, ivec2(p.x, max(p.y - 2, 0)), 0).a;
    y = c.a * 0.5 + (up + dn) * 0.25;
  }
  float chroma = c.a - y;
  int line = size.y - 1 - p.y;
  bool second = (line & 1) == 1;
  int fieldLine = line >> 1, flip = uPal == 1 ? 0 : (fieldLine + (second ? 1 : 0) + uField) & 1;
  int n = (p.x + flip * 2) & 3;
  float co = n == 0 ? 2.0 : n == 2 ? -2.0 : 0.0, si = n == 1 ? 2.0 : n == 3 ? -2.0 : 0.0;
  float v = uPal == 1 && (fieldLine & 1) == 1 ? -1.0 : 1.0;
  fragColor = vec4(y, chroma * co, chroma * si * v, 1.0);
}
