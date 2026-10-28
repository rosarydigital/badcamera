uniform sampler2D uHeld, uPrev, uMotion; uniform float uBlock, uResidual;
void main() {
  vec2 d = texelFetch(uMotion, ivec2(gl_FragCoord.xy / uBlock), 0).xy / uRes;
  vec3 resid = texture(tex, uv).rgb - texture(uPrev, uv + d).rgb;
  fragColor = vec4(texture(uHeld, uv + d).rgb + resid * uResidual, 1.0);
}
