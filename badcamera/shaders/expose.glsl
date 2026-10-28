uniform sampler2D uAvg; uniform float uTarget, uAE, uMaxEv, uAWB, uHunt;
void main() {
  vec3 avg = max(texelFetch(uAvg, ivec2(0), 0).rgb, vec3(1e-3));
  float l = max(luma(avg), 1e-3);
  float ev = clamp(log2(uTarget / l), -uMaxEv, uMaxEv) * uAE;
  ev += uHunt * 0.6 * (0.6 * sin(uTime * 0.9) + 0.4 * sin(uTime * 2.3 + 1.7));  // metering never quite settles
  vec3 wb = mix(vec3(1.0), vec3(l) / avg, uAWB);  // grey-world white balance
  fragColor = vec4(texture(tex, uv).rgb * exp2(ev) * wb / max(luma(wb), 1e-3), 1.0);
}
