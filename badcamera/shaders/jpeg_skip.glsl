// Video-codec skip blocks: keep last frame's decoded block where the new source barely differs from it.
uniform sampler2D uSrc, uOld; uniform float uThreshold, uBlock; uniform int uKey;
void main() {
  vec2 res = vec2(textureSize(tex, 0)), origin = floor(gl_FragCoord.xy / uBlock) * uBlock;
  float d = 0.0;
  for (int j = 0; j < 4; j++) for (int i = 0; i < 4; i++) {
    vec2 q = (origin + (vec2(i, j) + 0.5) * uBlock / 4.0) / res;
    d += dot(abs(clamp(texture(uSrc, q).rgb, 0.0, 1.0) - texture(uOld, q).rgb), vec3(0.3333));
  }
  fragColor = (uKey == 1 || d / 16.0 > uThreshold) ? texture(tex, uv) : texture(uOld, uv);
}
