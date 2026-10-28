uniform float uCell, uGap, uSubpixel, uBright, uScanBar, uMoire;
void main() {
  float cs = max(uCell, 1.0);
  vec2 f = gl_FragCoord.xy / cs, fr = fract(f);
  vec3 c = texture(tex, (floor(f) + 0.5) * cs / uRes).rgb;
  float sx = fr.x * 3.0, s = floor(sx);
  vec3 mask = mix(vec3(1.0), (s < 1.0 ? vec3(1, 0, 0) : s < 2.0 ? vec3(0, 1, 0) : vec3(0, 0, 1)) * 3.0, uSubpixel);
  float gx = uSubpixel > 0.0 ? fract(sx) : fr.x, h = uGap * 0.5;
  float g = step(h, fr.y) * step(fr.y, 1.0 - h) * step(h, gx) * step(gx, 1.0 - h);
  c *= mask * g * uBright;
  // Filming a screen: a rolling refresh band and drifting moire between the pixel grid and the camera's.
  c *= 1.0 - uScanBar * 0.45 * exp(-pow((fract(uv.y - uTime * 0.17) - 0.5) * 7.0, 2.0));
  float ph = 6.2831853 * (gl_FragCoord.x * 0.011 + gl_FragCoord.y * (0.004 + 0.002 * sin(uTime * 0.21)) + uTime * 0.08);
  c *= 1.0 - uMoire * 0.3 * (0.5 + 0.5 * cos(ph + vec3(0.0, 2.1, 4.2)));
  fragColor = vec4(c, 1.0);
}
