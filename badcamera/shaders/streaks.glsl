uniform int uRays; uniform float uLength, uAngle, uDecay, uTwinkle, uSpectral;
vec3 spectrum(float x) { return 0.5 + 0.5 * cos(6.2831853 * (x + vec3(0.0, 0.33, 0.67))); }
void main() {
  vec3 acc = vec3(0.0);
  for (int r = 0; r < uRays; r++) {
    float fr = float(r), a = uAngle + 6.2831853 * fr / float(uRays);
    float tw = 1.0 - uTwinkle * (0.5 + 0.5 * sin(uTime * (2.0 + 3.0 * hash(vec2(fr, 1.0))) + fr * 2.39));  // each ray twinkles on its own
    vec2 dir = vec2(cos(a) * uRes.y / uRes.x, sin(a)) * uLength * (0.7 + 0.6 * hash(vec2(fr, 5.0))) / 24.0;
    for (int i = 1; i <= 24; i++) {
      float k = float(i) / 24.0;
      acc += texture(tex, uv + dir * float(i)).rgb * exp(-uDecay * k) * tw * mix(vec3(1.0), spectrum(k * 0.8), uSpectral);
    }
  }
  fragColor = vec4(acc / 24.0, 1.0);
}
