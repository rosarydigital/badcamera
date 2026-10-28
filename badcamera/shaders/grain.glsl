uniform sampler2D uGrain; uniform float uAmount, uScale, uShadow; uniform int uAnimate;
void main() {
  vec3 c = texture(tex, uv).rgb;
  vec2 off = uAnimate == 1 ? vec2(hash(vec2(float(uFrame % 997), 1.0)), hash(vec2(3.0, float(uFrame % 991)))) : vec2(0.0);
  float n = texture(uGrain, gl_FragCoord.xy / (vec2(textureSize(uGrain, 0)) * max(uScale, 0.1)) + off).r - 0.5;
  fragColor = vec4(c + n * uAmount * mix(1.0, 1.0 - clamp(luma(c), 0.0, 1.0), uShadow), 1.0);
}
