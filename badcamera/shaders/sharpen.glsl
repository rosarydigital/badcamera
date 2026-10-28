uniform float uAmount;
void main() {
  vec2 px = 1.0 / vec2(textureSize(tex, 0));
  vec3 c = texture(tex, uv).rgb;
  vec3 n = texture(tex, uv + vec2(px.x, 0)).rgb + texture(tex, uv - vec2(px.x, 0)).rgb
         + texture(tex, uv + vec2(0, px.y)).rgb + texture(tex, uv - vec2(0, px.y)).rgb;
  fragColor = vec4(c + (4.0 * c - n) * uAmount, 1.0);
}
