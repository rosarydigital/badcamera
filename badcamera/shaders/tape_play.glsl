// Stage 4: replay. Mechanical timing errors bend the picture line by line, the heads add noise,
// and damage to the oxide drops the signal out. A dropout compensator patches gaps with the line above.
uniform float uJitter, uWave, uFlag, uNoise, uChromaNoise, uDropouts, uTracking, uHeadSwitch, uHeadGain, uSeed, uStreak, uChromaLoss;
uniform int uHeadLines;
float rnd(float a, float b) { return hash(vec2(a * 0.137 + uSeed, b * 0.731 + uSeed * 0.37)); }
float wander(float t) {  // smooth noise over time or lines
  float i = floor(t), f = fract(t);
  f = f * f * (3.0 - 2.0 * f);
  return mix(hash(vec2(i, 3.3)), hash(vec2(i + 1.0, 3.3)), f) - 0.5;
}
float lineNoise(float x, float line, float len) {  // noise smeared along the scanline, never per pixel
  float k = x / len, i = floor(k), f = fract(k);
  return mix(rnd(i, line), rnd(i + 1.0, line), f * f * (3.0 - 2.0 * f)) - 0.5;
}
void main() {
  ivec2 size = textureSize(tex, 0);
  float H = float(size.y), W = float(size.x);
  float top = H - 1.0 - floor(gl_FragCoord.y);  // 0 at the top of the picture
  float pos = top / H, field = mod(top, 2.0), fieldLine = floor(top * 0.5), x = gl_FragCoord.x;

  // Slow timing wander, plus a per-line tremble. Each field gets its own.
  float t = uTime;
  float slow = wander(fieldLine * 0.035 + t * 1.3 + field * 7.0) + 0.5 * wander(fieldLine * 0.11 - t * 2.1 + 11.0);
  float dx = uWave * slow + uJitter * (rnd(top, 1.0) - 0.5);
  dx += uFlag * pow(max(0.0, 1.0 - pos * 9.0), 2.0) * (0.7 + wander(t * 3.0));  // tension skew bends the top of the picture

  // Head switching: the last lines of each field come from the head that's about to leave the tape.
  float bottom = top - (H - float(uHeadLines));
  float inBar = step(0.0, bottom);
  float into_ = clamp(bottom / float(uHeadLines), 0.0, 1.0);
  dx += inBar * uHeadSwitch * (16.0 + 26.0 * into_ * into_ + 8.0 * (rnd(top, 2.0) - 0.5) + 8.0 * wander(t * 11.0));

  // Tracking error: a band of mistimed, noisy lines drifting up the picture.
  float band = 0.0;
  if (uTracking > 0.0) {
    float centre = fract(0.15 - t * 0.021 + 0.08 * wander(t * 0.4));
    float dist = abs(pos - centre);
    dist = min(dist, 1.0 - dist);
    band = uTracking * smoothstep(0.075, 0.0, dist);
    dx += band * 22.0 * (rnd(top, 3.0) - 0.5);
  }

  vec3 s = texture(tex, vec2((x + dx) / W, uv.y)).xyz;
  // The two video heads never match: alternate fields differ very slightly in level.
  s.x *= 1.0 + uHeadGain * (field - 0.5);

  // FM noise is short horizontal streaks. Colour noise is much longer ones, from the narrow colour-under band.
  float amp = uNoise * (1.0 + 7.0 * band);
  s.x += amp * (lineNoise(x, top, uStreak) + 0.6 * lineNoise(x + 40.0, top + 500.0, uStreak * 2.2));
  s.yz += uChromaNoise * (1.0 + 4.0 * band) * vec2(lineNoise(x, top + 900.0, 26.0), lineNoise(x, top + 1500.0, 36.0));
  if (rnd(top, 4.0) < uChromaLoss) s.yz *= 0.15;  // the colour killer trips on a bad line

  // Dropouts: oxide missing for a stretch. The compensator repeats the line above; long ones leave a white sliver.
  float cells = floor(x / 42.0);
  for (int i = 0; i < 2; i++) {
    float lane = float(i);
    if (rnd(top + lane * 37.0, 5.0) < uDropouts * 0.012) {
      float start = rnd(top + lane * 37.0, 6.0) * W, len = 12.0 + 90.0 * pow(rnd(top + lane * 37.0, 7.0), 3.0);
      if (x > start && x < start + len) {
        s = texelFetch(tex, ivec2(int(x), min(int(gl_FragCoord.y) + 2, size.y - 1)), 0).xyz;
        float tail = smoothstep(0.0, 8.0, x - start) * smoothstep(0.0, 8.0, start + len - x);
        s.x += 0.55 * tail * step(0.72, rnd(top + lane, 8.0));
        s.yz *= 0.4;
      }
    }
  }
  // Hash inside the head-switch bar, where sync is unusable.
  float hs = inBar * uHeadSwitch * step(0.45, rnd(floor(x / 30.0), top));
  s.x = mix(s.x, 0.45 + rnd(x, top) * 0.5, hs * 0.55 * into_);
  s.yz *= 1.0 - inBar * uHeadSwitch * 0.6;
  fragColor = vec4(s, 1.0);
}
