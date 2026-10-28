uniform float uWobble, uChromaShift, uChromaBlur, uTracking, uNoise, uScan, uSaturation, uSoft, uRing, uLines, uDropouts, uJumps, uBlack;
vec3 toYIQ(vec3 c) { return mat3(0.299, 0.596, 0.211, 0.587, -0.274, -0.523, 0.114, -0.322, 0.312) * c; }
vec3 toRGB(vec3 c) { return mat3(1.0, 1.0, 1.0, 0.956, -0.272, -1.106, 0.621, -0.647, 1.703) * c; }
float Y(vec2 p) { return toYIQ(texture(tex, p).rgb).x; }
void main() {
  float t = uTime, ft = floor(t * 30.0);
  // Occasional vertical jump when sync is lost for a moment.
  float jt = floor(t * 12.0);
  float y = uv.y + step(1.0 - 0.04 * uJumps, hash(vec2(jt, 7.7))) * (hash(vec2(jt, 3.1)) - 0.5) * 0.06;
  // Sample at tape-line centres: ~480 visible lines regardless of output size.
  float L = max(uLines, 2.0), line = floor(y * L), ly = (line + 0.5) / L;
  float jitter = hash(vec2(line, floor(t * 60.0))) - 0.5;
  float off = uWobble * (0.0015 * sin(ly * 10.0 + t * 2.0) + 0.0015 * jitter);
  float tr = uTracking * smoothstep(0.08, 0.0, abs(ly - (1.0 - fract(t * 0.05))));  // tracking band drifting down
  off += tr * 0.03 * jitter + uTracking * smoothstep(0.025, 0.0, ly) * 0.05 * (hash(vec2(line, t)) - 0.2);  // head-switch noise at the bottom
  vec2 p = vec2(uv.x + off, ly), px = vec2(1.0 / uRes.x, 0.0), lv = vec2(0.0, 1.0 / L);

  // Luma: ~240-line horizontal softness, then edge-enhancement ringing like a VCR's sharpness circuit.
  float s = max(uSoft, 0.01);
  float soft = 0.4 * Y(p) + 0.2 * (Y(p + px * s) + Y(p - px * s)) + 0.1 * (Y(p + px * 2.0 * s) + Y(p - px * 2.0 * s));
  float wide = (Y(p + px * 4.0 * s) + Y(p - px * 4.0 * s) + Y(p + px * 2.0 * s) + Y(p - px * 2.0 * s)) * 0.25;
  float luma_ = soft + uRing * (soft - wide);

  // Chroma: low bandwidth, delayed to the right, averaged with the line above (comb filter), plus colour streak noise.
  vec2 iq = vec2(0.0);
  for (int i = 0; i < 8; i++) {
    vec2 q = p + vec2((float(i) - 3.5) * uChromaBlur + uChromaShift, 0.0) / uRes;
    iq += toYIQ(texture(tex, q).rgb).yz + toYIQ(texture(tex, q - lv).rgb).yz;
  }
  vec2 streak = vec2(hash(vec2(floor(gl_FragCoord.x / 24.0), line + ft)), hash(vec2(line, floor(gl_FragCoord.x / 24.0) + t))) - 0.5;
  vec3 c = toRGB(vec3(luma_, iq / 16.0 * uSaturation + streak * uNoise * 0.6));

  // Tape noise is smeared along the line, not per pixel.
  float sn = hash(vec2(floor(gl_FragCoord.x / 3.0), line) + fract(t * 7.0) * 500.0);
  c += (sn - 0.5) * uNoise + tr * step(0.97, sn) * 0.8;
  // Dropouts: short bright streaks where the oxide is missing.
  if (hash(vec2(line, ft)) > 1.0 - 0.006 * uDropouts) {
    float d = uv.x - hash(vec2(line, ft + 1.7)), len = 0.03 + 0.15 * hash(vec2(line, ft + 9.1));
    c = mix(c, vec3(0.92), smoothstep(0.0, 0.01, d) * smoothstep(len, len - 0.03, d) * 0.85);
  }
  c = c * (1.0 - uBlack) + uBlack;
  c *= 1.0 - uScan * (0.5 - 0.5 * cos(6.2831853 * fract(y * L)));
  fragColor = vec4(c, 1.0);
}
