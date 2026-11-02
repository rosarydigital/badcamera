uniform sampler2D uB;
uniform float uP;
uniform int uKind;  // index into editor.TRANSITIONS
// 1 crossfade, 2 fade to black, 3 tape rewind, 4 tape pause, 5 tape stop
float bars(float y, float n, float speed) {  // the noise bands of a VCR picture search
  float v = fract(y * n + uTime * speed);
  return smoothstep(0.0, 0.12, v) * smoothstep(0.34, 0.2, v);
}
vec3 snow(vec2 p, float line) {
  float s = hash(vec2(floor(p.x * 260.0), line + floor(uTime * 60.0)));
  return vec3(smoothstep(0.35, 0.8, s));
}
void main() {
  vec3 a = texture(tex, uv).rgb, b = texture(uB, uv).rgb;
  float p = uP, line = floor(uv.y * 240.0);
  if (uKind == 1) { fragColor = vec4(mix(a, b, p), 1.0); return; }
  if (uKind == 2) { fragColor = vec4(p < 0.5 ? a * (1.0 - 2.0 * p) : b * (2.0 * p - 1.0), 1.0); return; }
  float w = sin(p * 3.14159);  // strength peaks mid-transition
  if (uKind == 3) {  // rewind: picture races past with noise bars and horizontal shear
    float y = fract(uv.y + uTime * 3.0 * w);
    float skew = 0.12 * w * (hash(vec2(line, floor(uTime * 60.0))) - 0.5);
    vec2 q = vec2(uv.x + skew, y);
    vec3 c = p < 0.5 ? texture(tex, q).rgb : texture(uB, q).rgb;
    fragColor = vec4(mix(c, snow(uv, line), bars(uv.y, 2.0, 2.5) * w), 1.0);
    return;
  }
  if (uKind == 4) {  // pause: held frame jittering with one noise bar, then playback resumes
    vec2 q = vec2(uv.x + 0.006 * w * (hash(vec2(line, floor(uTime * 30.0))) - 0.5), uv.y + 0.002 * w * sin(uTime * 60.0));
    vec3 c = p < 0.7 ? texture(tex, q).rgb : texture(uB, q).rgb;
    fragColor = vec4(mix(c, snow(uv, line), bars(uv.y, 1.0, 0.0) * w), 1.0);
    return;
  }
  // stop: picture collapses to deck blue, then the next recording rolls in
  vec3 blue = vec3(0.05, 0.1, 0.72);
  vec3 c = p < 0.5 ? mix(a, blue, smoothstep(0.1, 0.45, p)) : mix(blue, b, smoothstep(0.55, 0.9, p));
  fragColor = vec4(mix(c, snow(uv, line), bars(uv.y, 3.0, 4.0) * w * 0.6), 1.0);
}
