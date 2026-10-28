uniform sampler3D uLut; uniform float uIntensity, uSize;
void main() {
  vec3 c = texture(tex, uv).rgb;
  vec3 l = texture(uLut, clamp(c, 0.0, 1.0) * ((uSize - 1.0) / uSize) + 0.5 / uSize).rgb;
  fragColor = vec4(mix(c, l, uIntensity), 1.0);
}
