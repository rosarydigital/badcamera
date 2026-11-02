// A projected print: the frame weaves in the gate, exposure flickers, and the print carries dust and long scratches.
uniform float uWeaveX, uWeaveY, uFlicker, uDust, uScratches, uSeed;
float rnd(float a, float b) { return hash(vec2(a * 0.31 + uSeed, b * 0.73 + uSeed * 1.7)); }
void main() {
  vec2 p = uv + vec2(uWeaveX, uWeaveY);
  vec3 c = texture(tex, p).rgb * (1.0 + uFlicker);
  float aspect = uRes.x / uRes.y;
  for (int i = 0; i < 16; i++) {  // dust: dark or bright flecks, different every frame
    float f = float(i);
    if (rnd(f, 1.0) > uDust) continue;
    vec2 o = vec2(rnd(f, 2.0), rnd(f, 3.0)), d = (uv - o) * vec2(aspect, 1.0);
    d = mat2(cos(f), -sin(f), sin(f), cos(f)) * d;
    float size = 0.0012 + 0.0045 * rnd(f, 4.0) * rnd(f, 5.0);
    float mark = smoothstep(size * 1.6, size * 0.6, length(d * vec2(1.0, 0.25 + 2.0 * rnd(f, 6.0))));
    c = mix(c, vec3(rnd(f, 7.0) > 0.7 ? 0.95 : 0.05), mark * 0.85);
  }
  for (int i = 0; i < 3; i++) {  // scratches stay near one spot across frames, wobbling slightly
    float f = float(i) + 40.0;
    if (hash(vec2(f, floor(uTime * 0.7))) > uScratches) continue;
    float at = hash(vec2(f, floor(uTime * 0.7) + 2.0)) + 0.002 * sin(uTime * 13.0 + f);
    float line = smoothstep(0.0011, 0.0003, abs(uv.x - at)) * (0.5 + 0.5 * step(0.2, hash(vec2(floor(uv.y * 60.0), f + uSeed))));
    c = mix(c, vec3(0.9), line * 0.6);
  }
  fragColor = vec4(c, 1.0);
}
