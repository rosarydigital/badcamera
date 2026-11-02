// Real-time versions of the app's hardware sounds, tuned to the same measured targets as badcamera/audio.py.
// The rule from the app holds: level control rides the program, so noise stays a fixed distance under it, on quiet clips too.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <string>
#include <vector>

namespace bc {

static const char *const PRESET_NAMES[] = {"Original", "VHS linear SP", "VHS linear EP", "VHS Hi-Fi", "Camcorder mic", "Old landline", "2000s cell phone", "Cassette", "AM radio", "CCTV mic"};
static const int NUM_PRESETS = 10;

inline double dbToGain(double db) { return std::pow(10.0, db / 20.0); }

struct Biquad {
  double b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0, z1 = 0, z2 = 0;
  void set(bool high, double f, double sr, double q = 0.7071) {
    double w = 2 * M_PI * std::min(f, sr * 0.45) / sr, c = std::cos(w), a = std::sin(w) / (2 * q), n = 1 + a;
    b0 = (high ? (1 + c) / 2 : (1 - c) / 2) / n;
    b1 = (high ? -(1 + c) : 1 - c) / n;
    b2 = b0;
    a1 = -2 * c / n;
    a2 = (1 - a) / n;
  }
  double run(double x) {
    double y = b0 * x + z1;
    z1 = b1 * x - a1 * y + z2;
    z2 = b2 * x - a2 * y;
    return y;
  }
};

struct Compressor {
  double threshold = 1, ratio = 1, attack = 0, release = 0, makeup = 1, env = 0;
  void set(double threshDb, double r, double attackMs, double releaseMs, double makeupDb, double sr) {
    threshold = dbToGain(threshDb);
    ratio = r;
    attack = std::exp(-1 / (attackMs * 0.001 * sr));
    release = std::exp(-1 / (releaseMs * 0.001 * sr));
    makeup = dbToGain(makeupDb);
  }
  double run(double x) {
    double a = std::fabs(x);
    env = a > env ? attack * env + (1 - attack) * a : release * env + (1 - release) * a;
    double gain = env > threshold ? std::pow(env / threshold, 1 / ratio - 1) : 1;
    return x * gain * makeup;
  }
};

struct Flutter {  // a short delay line whose length is modulated: the same thing a speed wobble does to pitch
  std::vector<double> buf;
  size_t pos = 0;
  double phase = 0, depth = 0, rate = 0, sr = 48000;
  void set(double hz, double percent, double sampleRate) {
    sr = sampleRate;
    rate = 2 * M_PI * hz / sr;
    depth = percent / 100.0 * sr / (2 * M_PI * hz);  // peak speed change = 2*pi*f*delay swing
    buf.assign((size_t)(depth * 2 + 8), 0.0);
    pos = 0;
  }
  double run(double x) {
    if (depth <= 0) return x;
    buf[pos] = x;
    phase += rate;
    if (phase > 2 * M_PI) phase -= 2 * M_PI;
    double d = depth * (1 + std::sin(phase)) + 1, r = (double)pos - d;
    while (r < 0) r += (double)buf.size();
    size_t i = (size_t)r;
    double f = r - (double)i, y = buf[i] * (1 - f) + buf[(i + 1) % buf.size()] * f;
    pos = (pos + 1) % buf.size();
    return y;
  }
};

struct DarkNoise {  // pink noise through a soft lowpass: real tape noise measured dark, not hissy
  uint32_t seed = 22222;
  double b0 = 0, b1 = 0, b2 = 0, lp = 0, a = 0.5;
  void set(double tone, double sr) { a = 1 - std::exp(-2 * M_PI * tone / sr); }
  double run() {
    seed = seed * 1664525u + 1013904223u;
    double w = (double)(int32_t)seed / 2147483648.0;
    b0 = 0.99765 * b0 + w * 0.0990460;
    b1 = 0.96300 * b1 + w * 0.2965164;
    b2 = 0.57000 * b2 + w * 1.0526913;
    lp += a * ((b0 + b1 + b2 + w * 0.1848) - lp);
    return lp;
  }
};

struct Settings {
  double hp = 0, lp = 0, noiseDb = -200, tone = 5000, wow = 0, flutter = 0, makeup = 0, humDb = -200, humHz = 60;
  double compT = 0, compR = 1, compA = 8, compRel = 250, compM = 0;
  double whineDb = -200;
  int codec = 0;  // 1 mu-law, 2 GSM-like
  bool mono = true;
};

inline Settings settings_for(int preset) {
  Settings s;
  switch (preset) {
    case 1: s.hp = 100; s.lp = 11500; s.noiseDb = -44; s.wow = 0.17; s.flutter = 0.05; s.compT = -18; s.compR = 2.5; s.makeup = 2; break;
    case 2: s.hp = 100; s.lp = 5800; s.noiseDb = -42; s.wow = 0.3; s.flutter = 0.1; s.compT = -18; s.compR = 2.5; s.makeup = 2; break;
    case 3: s.hp = 20; s.noiseDb = -72; s.mono = false; break;
    case 4: s.hp = 130; s.lp = 7000; s.noiseDb = -46; s.tone = 4000; s.compT = -26; s.compR = 3; s.compA = 6; s.compRel = 500; s.compM = 2; s.makeup = 4; s.whineDb = -68; break;
    case 5: s.hp = 300; s.lp = 3400; s.noiseDb = -42; s.tone = 3000; s.compT = -20; s.compR = 3; s.compM = 2; s.makeup = 4; s.codec = 1; break;
    case 6: s.hp = 300; s.lp = 3400; s.noiseDb = -52; s.tone = 3000; s.compT = -22; s.compR = 3; s.compM = 2; s.makeup = 5; s.codec = 2; break;
    case 7: s.hp = 40; s.lp = 13000; s.noiseDb = -42; s.tone = 7000; s.wow = 0.14; s.flutter = 0.05; s.mono = false; s.makeup = 2; break;
    case 8: s.hp = 120; s.lp = 4800; s.noiseDb = -40; s.tone = 4500; s.compT = -24; s.compR = 4; s.compA = 2; s.compRel = 80; s.compM = 3; s.makeup = 3; s.humDb = -62; break;
    case 9: s.hp = 320; s.lp = 3000; s.noiseDb = -42; s.tone = 3500; s.compT = -24; s.compR = 3; s.compA = 4; s.compRel = 300; s.compM = 2; s.makeup = 4; s.humDb = -56; break;
    default: break;
  }
  return s;
}

class Channel {
 public:
  void prepare(int preset, double sampleRate) {
    sr = sampleRate;
    s = settings_for(preset);
    hp1.set(true, std::max(s.hp, 1.0), sr);
    hp2.set(true, std::max(s.hp, 1.0), sr);
    double lp = s.lp > 0 ? s.lp * 1.3 : sr * 0.45;
    lp1.set(false, lp, sr);
    lp2.set(false, lp, sr);
    comp.set(s.compT, s.compR, s.compA, s.compRel, s.compM, sr);
    wow.set(0.7, s.wow, sr);
    flut.set(9.3, s.flutter, sr);
    noise.set(s.tone, sr);
    hold = held = 0;
    step = s.codec ? sr / 8000.0 : 1;
    level = 0.1;
    t = 0;
    attack = std::exp(-1 / (0.05 * sr));
    decay = std::exp(-1 / (3.0 * sr));
  }
  // x: program sample. amount: tape noise 0-2. leveled: where this channel's loudest moments have been sitting.
  double run(double x, double amount) {
    double a = std::fabs(x);
    level = a > level ? attack * level + (1 - attack) * a : decay * level + (1 - decay) * a;
    level = std::max(level, 0.003);  // near-silence can't blast the noise
    double gain = 0.1 / level;       // to record level
    double y = x * gain;
    if (s.hp > 0) y = hp1.run(y);
    if (s.lp > 0) y = lp1.run(y);
    if (s.compR > 1) y = comp.run(y);
    y = flut.run(wow.run(y));
    if (s.wow > 0) y = std::tanh(y);
    t += 1 / sr;
    double extra = amount * noise.run() * dbToGain(s.noiseDb) * 0.14;
    if (s.humDb > -100) extra += amount * dbToGain(s.humDb) * (std::sin(2 * M_PI * s.humHz * t) + 0.5 * std::sin(6 * M_PI * s.humHz * t));
    if (s.whineDb > -100) extra += amount * dbToGain(s.whineDb) * std::sin(2 * M_PI * 1180 * t);
    y += extra;
    if (s.codec) y = codec(y);
    if (s.lp > 0) y = lp2.run(y);
    if (s.hp > 0) y = hp2.run(y);
    return y / gain * dbToGain(s.makeup);
  }

 private:
  double codec(double x) {  // telephone paths run at 8 kHz, companded
    hold += 1;
    if (hold >= step) {
      hold -= step;
      double v = std::max(-1.0, std::min(1.0, x));
      double mu = std::copysign(std::log1p(255 * std::fabs(v)) / std::log1p(255.0), v);
      double levels = s.codec == 1 ? 127.0 : 31.0;
      mu = std::round(mu * levels) / levels;
      held = std::copysign((std::pow(256.0, std::fabs(mu)) - 1) / 255, mu);
    }
    return held;
  }
  Settings s;
  Biquad hp1, hp2, lp1, lp2;
  Compressor comp;
  Flutter wow, flut;
  DarkNoise noise;
  double sr = 48000, hold = 0, held = 0, step = 1, level = 0.1, t = 0, attack = 0, decay = 0;
};

class Processor {
 public:
  void prepare(int newPreset, double sampleRate) {
    preset = newPreset;
    mono = settings_for(preset).mono;
    for (auto &c : ch) c.prepare(preset, sampleRate);
  }
  void process(float *l, float *r, int n, double noise, double mix, double output) {
    double out = dbToGain(output);
    for (int i = 0; i < n; i++) {
      double a = l[i], b = r ? r[i] : l[i], wa = a, wb = b;
      if (preset) {
        if (mono) wa = wb = ch[0].run(0.5 * (a + b), noise);
        else {
          wa = ch[0].run(a, noise);
          wb = ch[1].run(b, noise);
        }
      }
      l[i] = (float)((a + (wa - a) * mix) * out);
      if (r) r[i] = (float)((b + (wb - b) * mix) * out);
    }
  }

 private:
  Channel ch[2];
  int preset = 0;
  bool mono = true;
};

}  // namespace bc
