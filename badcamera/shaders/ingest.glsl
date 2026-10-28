uniform int uMirror;
// camera rows arrive top-first and BGR
void main() { fragColor = vec4(texture(tex, vec2(uMirror == 1 ? 1.0 - uv.x : uv.x, 1.0 - uv.y)).bgr, 1.0); }
