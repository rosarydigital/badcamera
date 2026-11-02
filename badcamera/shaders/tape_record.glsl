// Stage 3: what the tape can hold. Luma is band-limited FM with pre-emphasis, which rings around edges.
// Chroma is heterodyned down to a narrow colour-under band: very low resolution, delayed, and blended between lines.
uniform float uLumaSigma, uChromaSigma, uChromaDelay, uRing, uRingWidth, uSmear, uChromaBlend, uSat;
float gauss(float x, float s) { return exp(-0.5 * x * x / (s * s)); }
float lumaAt(float dx) { return texture(tex, uv + vec2(dx / uRes.x, 0.0)).x; }
float lowpassed(float at, float sigma) {
  float sum = 0.0, weight = 0.0, step_ = max(sigma * 0.75, 0.75);
  for (int i = -5; i <= 5; i++) {
    float w = gauss(float(i) * step_, sigma);
    sum += lumaAt(at + float(i) * step_) * w;
    weight += w;
  }
  return sum / weight;
}
void main() {
  float y = lowpassed(0.0, uLumaSigma);
  // Pre-emphasis: an unsharp lobe either side of an edge, which is the halo around dark objects on bright backgrounds.
  float wide = lowpassed(0.0, uRingWidth);
  float ring = uRing * (y - wide);
  // FM recovers slowly from a big transition: a faint trail to the right of strong edges.
  float trail = lowpassed(-uRingWidth * 3.0, uRingWidth * 2.0);
  y = y + ring - uSmear * (y - trail) * 0.5;

  ivec2 p = ivec2(gl_FragCoord.xy);
  vec2 iq = vec2(0.0);
  float weight = 0.0, step_ = max(uChromaSigma * 0.5, 0.75);
  float lineUp = 2.0 / uRes.y;
  for (int i = -7; i <= 7; i++) {
    float dx = float(i) * step_, w = gauss(dx, uChromaSigma);
    vec2 q = vec2(uv.x + (dx - uChromaDelay) / uRes.x, uv.y);
    iq += w * mix(texture(tex, q).yz, 0.5 * (texture(tex, q + vec2(0.0, lineUp)).yz + texture(tex, q - vec2(0.0, lineUp)).yz), uChromaBlend);
    weight += w;
  }
  fragColor = vec4(y, iq / weight * uSat, 1.0);
}
