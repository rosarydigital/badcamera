// Gain, ghosting and tint on top of the IR image. uGlow is a blurred copy for highlight bloom; uTrail holds the slow-exposure history.
uniform sampler2D uGlow, uTrail;
uniform float uGhost, uBloom, uNoise, uGain, uHum, uHumSpeed, uHot, uSeed, uPhosphor;
uniform vec3 uTint;
float rnd(vec2 p) { return hash(p + uSeed * 83.3); }
void main() {
  float now = texture(tex, uv).x;
  float past = texture(uTrail, uv).x;
  float y = mix(now, past, uGhost);  // sense-up: long exposure smears motion into ghosts
  y = y * uGain + uBloom * texture(uGlow, uv).x;
  // Heavy AGC: noise is coarse and rises in the dark.
  vec2 cell = floor(gl_FragCoord.xy / max(uRes.y / 360.0, 1.0));
  float n = (rnd(cell) + rnd(cell + 3.1) + rnd(cell + 7.9)) / 1.5 - 1.0;
  y += uNoise * n * mix(1.3, 0.45, sqrt(clamp(y, 0.0, 1.0)));
  y += step(1.0 - 0.00035 * uHot, hash(cell * 0.73)) * 0.7;  // hot pixels stay put between frames
  // Ground-loop hum: a soft dark bar rolling up the frame.
  float roll = sin(6.2831853 * (uv.y + uTime * uHumSpeed));
  y *= 1.0 - uHum * (0.5 + 0.5 * roll) * 0.28;
  float l = clamp(y, 0.0, 1.0);
  // Tubes and tinted monitors bloom to near-white at the top of their range.
  vec3 c = mix(l * uTint, vec3(l), uPhosphor * l * l);
  fragColor = vec4(c, 1.0);
}
