uniform float uLuma, uChroma, uChromaSize, uShadows, uBanding, uHot;
void main() {
  vec3 c = texture(tex, uv).rgb;
  float l = clamp(luma(c), 0.0, 1.0);
  vec2 s = vec2(float(uFrame % 997) * 3.71, float(uFrame % 991) * 1.93);
  // Shot noise grows with sqrt(signal); the read-noise floor dominates the shadows.
  float sigma = uLuma * mix(sqrt(l + 0.02), 1.0 - 0.7 * l, uShadows);
  c += (hash(gl_FragCoord.xy + s) + hash(gl_FragCoord.xy + s + 71.3) + hash(gl_FragCoord.xy + s + 19.9) - 1.5) * 2.0 * sigma;
  // Blotchy chroma noise, worst in the shadows.
  vec2 q = gl_FragCoord.xy / max(uChromaSize, 1.0) + s;
  vec2 ch = vec2(vnoise(q), vnoise(q + 41.7)) - 0.5;
  c += vec3(ch.x, -0.5 * (ch.x + ch.y), ch.y) * uChroma * 2.0 * (1.0 - l);
  // Per-row read-out banding.
  c += (hash(vec2(floor(gl_FragCoord.y), s.x)) - 0.5) * uBanding * 0.15 * (1.0 - l);
  // Hot pixels are a fixed pattern on a real sensor, so these deliberately don't move.
  if (hash(floor(gl_FragCoord.xy) * 1.37 + 0.5) > 1.0 - uHot * 0.0006)
    c += vec3(hash(gl_FragCoord.xy + 3.1), hash(gl_FragCoord.xy + 7.3), hash(gl_FragCoord.xy + 1.9)) * (1.0 - l);
  fragColor = vec4(c, 1.0);
}
