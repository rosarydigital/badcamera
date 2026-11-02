// What a sensor with its IR-cut filter out, lit by LEDs around the lens, sees. Colour is lost: IR reflectance replaces it.
uniform float uCenterX, uCenterY, uSpot, uRange, uReflect;
void main() {
  vec3 c = texture(tex, uv).rgb;
  // Near-IR reflectance roughly follows red: skin and fabric go pale, and blue goes dark. Bright scene light still counts.
  float ir = dot(c, vec3(0.72, 0.24, 0.04));
  ir = max(ir, 0.0) * (1.0 + uReflect * smoothstep(0.35, 0.9, c.r - 0.5 * c.b + 0.3));
  vec2 d = (uv - vec2(uCenterX, uCenterY)) * vec2(uRes.x / uRes.y, 1.0);
  float r2 = dot(d, d) / max(uSpot * uSpot, 1e-4);
  float light = uRange + (1.0 - uRange) / (1.0 + r2 * r2);  // bright pool in the middle, falling away fast towards the edges
  fragColor = vec4(vec3(ir * light), 1.0);
}
