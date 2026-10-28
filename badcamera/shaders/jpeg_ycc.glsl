void main() {
  vec3 c = clamp(texture(tex, uv).rgb, 0.0, 1.0) * 255.0;
  fragColor = vec4(dot(c, vec3(0.299, 0.587, 0.114)),
                   dot(c, vec3(-0.168736, -0.331264, 0.5)) + 128.0,
                   dot(c, vec3(0.5, -0.418688, -0.081312)) + 128.0, 1.0);
}
