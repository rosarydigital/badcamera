// Offline check of the plugin's sound: dsp_test preset in.raw out.raw (48 kHz float stereo) [noise]
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <vector>
#include "badcamera_dsp.h"
int main(int c, char **v) {
  std::ifstream f(v[2], std::ios::binary | std::ios::ate);
  size_t n = (size_t)f.tellg() / 8;
  f.seekg(0);
  std::vector<float> in(n * 2), l(n), r(n);
  f.read((char *)in.data(), in.size() * 4);
  for (size_t i = 0; i < n; i++) { l[i] = in[i * 2]; r[i] = in[i * 2 + 1]; }
  bc::Processor p;
  p.prepare(atoi(v[1]), 48000);
  double noise = c > 4 ? atof(v[4]) : 1;
  for (size_t i = 0; i < n; i += 512) { int k = (int)std::min<size_t>(512, n - i); p.process(&l[i], &r[i], k, noise, 1.0, 0.0); }
  for (size_t i = 0; i < n; i++) { in[i * 2] = l[i]; in[i * 2 + 1] = r[i]; }
  std::ofstream(v[3], std::ios::binary).write((char *)in.data(), in.size() * 4);
}
