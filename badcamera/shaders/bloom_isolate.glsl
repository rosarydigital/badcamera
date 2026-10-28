uniform float uGamma;
void main() { fragColor = vec4(pow(clamp(texture(tex, uv).rgb, 0.0, 1.0), vec3(uGamma)), 1.0); }
