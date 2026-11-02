// Automatic gain: hold the picture's average near a low target, the way an IR camera's AGC does.
uniform sampler2D uAvg;
uniform float uTarget;
void main() { fragColor = vec4(texture(tex, uv).rgb * clamp(uTarget / max(texture(uAvg, vec2(0.5)).x, 0.005), 0.15, 8.0), 1.0); }
