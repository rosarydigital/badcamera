uniform sampler2D uPrev; uniform float uAmount;
void main() { fragColor = mix(texture(tex, uv), texture(uPrev, uv), uAmount); }
