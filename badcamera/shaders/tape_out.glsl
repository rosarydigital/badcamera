// Stage 5: back to a picture. Levels are clipped like a video signal, and the sides stay as the black blanking of a raw capture.
uniform float uBlack, uWhite, uKnee, uOverscan, uBlank;
vec3 rgb(vec3 c) { return mat3(1.0, 1.0, 1.0, 0.956, -0.272, -1.106, 0.621, -0.647, 1.703) * c; }
void main() {
  vec2 p = 0.5 + (uv - 0.5) * (1.0 - uOverscan);
  vec3 s = texture(tex, p).xyz;
  float y = s.x;
  y = y > uKnee ? uKnee + (1.0 - uKnee) * (1.0 - exp(-(y - uKnee) / (1.0 - uKnee))) : y;  // white clipper
  y = uBlack + y * (uWhite - uBlack);  // lifted pedestal, compressed range
  vec3 c = clamp(rgb(vec3(y, s.yz)), 0.0, 1.0);
  float edge = step(uBlank, p.x) * step(uBlank, 1.0 - p.x);  // horizontal blanking
  fragColor = vec4(c * edge, 1.0);
}
