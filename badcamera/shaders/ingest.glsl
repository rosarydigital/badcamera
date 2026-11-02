uniform int uMirror, uTransformed;
uniform mat3 uXform;
// camera rows arrive top-first and BGR
void main() {
  if (uTransformed == 1) {  // output uv -> source uv, black outside the source frame
    vec2 p = (uXform * vec3(uv, 1.0)).xy;
    vec2 e = step(vec2(0.0), p) * step(p, vec2(1.0));
    fragColor = vec4(texture(tex, vec2(p.x, 1.0 - p.y)).bgr * e.x * e.y, 1.0);
    return;
  }
  fragColor = vec4(texture(tex, vec2(uMirror == 1 ? 1.0 - uv.x : uv.x, 1.0 - uv.y)).bgr, 1.0);
}
