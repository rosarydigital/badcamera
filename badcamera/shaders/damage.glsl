// Tape faults at a moment on the timeline, plus the slow wear of an old tape. Runs on the finished picture.
uniform float uTear, uDropout, uJump, uLoss, uStatic, uRoll, uJolt, uAge, uSeed;
float rnd(float a, float b) { return hash(vec2(a * 0.137 + uSeed * 91.0, b * 0.731 + uSeed * 37.0)); }
vec3 snow(vec2 px) {
  float n = hash(vec2(floor(px.x / 2.0), floor(px.y / 2.0)) + uSeed * 311.0);
  return vec3(smoothstep(0.25, 0.85, n));
}
void main() {
  float line = floor((1.0 - uv.y) * 480.0);
  vec2 p = uv;
  float jt = floor(uTime * 30.0);  // something hits the camera
  p = (p - 0.5) * (1.0 - 0.05 * uJolt) + 0.5 + uJolt * 0.045 * (vec2(hash(vec2(jt, 1.3)), hash(vec2(jt, 2.7))) - 0.5);
  p.y = fract(p.y + uRoll * uTime * 2.3);  // sync lost: the picture rolls
  float wander = uAge * uAge * 0.006 * sin(line * 0.05 + uTime * 3.0);
  // Old tape picks up its own faults: a tracking tear that wanders in now and then.
  float autoTear = step(0.9, hash(vec2(floor(uTime * 0.6), 4.2))) * smoothstep(0.35, 1.0, uAge);
  float tear = max(uTear, autoTear);
  float at = fract(0.77 - uTime * 0.13 + hash(vec2(floor(uTime * 0.6), 9.1)));
  float band = tear * smoothstep(0.1 * tear + 0.03, 0.0, abs(1.0 - uv.y - at));
  p.x += wander + band * 0.14 * (rnd(line, 1.0) - 0.5) + uJump * 0.05 * sin(line * 0.31 + uTime * 40.0);
  p.y += uJump * 0.08 * (rnd(floor(uTime * 24.0), 2.0) - 0.5);
  vec3 c = texture(tex, fract(p)).rgb;
  // Wear: colour fades, contrast sags, the picture softens a little and breathes.
  float y = luma(c);
  c = mix(c, vec3(y), uAge * 0.45);
  c = mix(c, c * 0.92 + 0.05, uAge);
  c *= 1.0 + 0.05 * uAge * sin(uTime * 7.0) * sin(uTime * 2.3);
  // Dropouts: white streaks, more of them with age and during a burst.
  float rate = uDropout * 0.09 + uAge * uAge * 0.008;
  if (rnd(line, 3.0) < rate) {
    float s = rnd(line, 4.0), len = 0.03 + 0.25 * pow(rnd(line, 5.0), 2.0);
    if (uv.x > s && uv.x < s + len) c = mix(c, vec3(0.95), 0.85);
  }
  c = mix(c, snow(gl_FragCoord.xy) * 0.85, band * step(0.55, rnd(floor(gl_FragCoord.x / 18.0), line)));
  c = mix(c, snow(gl_FragCoord.xy), uStatic);
  c = mix(c, vec3(0.04, 0.05, 0.1) + snow(gl_FragCoord.xy) * 0.08, uLoss);  // no signal
  fragColor = vec4(c, 1.0);
}
