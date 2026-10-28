uniform float uThreshold;
void main() { vec3 c = texture(tex, uv).rgb; fragColor = vec4(c * smoothstep(uThreshold, uThreshold + 0.1, luma(c)), 1.0); }
