// BadCamera Hardware: the app's hardware sounds as a VST3 effect. One menu, three knobs.
#include "public.sdk/source/main/pluginfactory.h"
#include "public.sdk/source/vst/vstaudioeffect.h"
#include "public.sdk/source/vst/vstsinglecomponenteffect.h"
#include "pluginterfaces/base/ibstream.h"
#include "pluginterfaces/vst/ivstparameterchanges.h"
#include "base/source/fstreamer.h"
#include <cstring>
#include "badcamera_dsp.h"

using namespace Steinberg;
using namespace Steinberg::Vst;

enum { kPreset, kNoise, kMix, kOutput };
static const FUID kUid(0x7C1A52B3, 0x4D9E4F1A, 0x9A6B3E21, 0xBADCA3E5);

class Effect : public SingleComponentEffect {
 public:
  static FUnknown *create(void *) { return (IAudioProcessor *)new Effect; }

  tresult PLUGIN_API initialize(FUnknown *ctx) SMTG_OVERRIDE {
    tresult r = SingleComponentEffect::initialize(ctx);
    if (r != kResultOk) return r;
    addAudioInput(STR16("Input"), SpeakerArr::kStereo);
    addAudioOutput(STR16("Output"), SpeakerArr::kStereo);
    auto *list = new StringListParameter(STR16("Hardware"), kPreset, nullptr, ParameterInfo::kCanAutomate | ParameterInfo::kIsList);
    for (int i = 0; i < bc::NUM_PRESETS; i++) {
      String128 name;
      for (int k = 0;; k++) {
        name[k] = bc::PRESET_NAMES[i][k];
        if (!name[k]) break;
      }
      list->appendString(name);
    }
    parameters.addParameter(list);
    parameters.addParameter(new RangeParameter(STR16("Tape noise"), kNoise, STR16("%"), 0, 200, 100));
    parameters.addParameter(STR16("Mix"), STR16("%"), 0, 1.0, ParameterInfo::kCanAutomate, kMix);
    parameters.addParameter(new RangeParameter(STR16("Output"), kOutput, STR16("dB"), -24, 12, 0));
    return kResultOk;
  }

  tresult PLUGIN_API setBusArrangements(SpeakerArrangement *in, int32 ni, SpeakerArrangement *out, int32 no) SMTG_OVERRIDE {
    if (ni == 1 && no == 1 && in[0] == out[0] && SpeakerArr::getChannelCount(in[0]) <= 2) return SingleComponentEffect::setBusArrangements(in, ni, out, no);
    return kResultFalse;
  }
  tresult PLUGIN_API canProcessSampleSize(int32 s) SMTG_OVERRIDE { return s == kSample32 ? kResultTrue : kResultFalse; }
  tresult PLUGIN_API setupProcessing(ProcessSetup &s) SMTG_OVERRIDE {
    sr = s.sampleRate;
    dsp.prepare(preset, sr);
    return SingleComponentEffect::setupProcessing(s);
  }

  tresult PLUGIN_API process(ProcessData &d) SMTG_OVERRIDE {
    if (d.inputParameterChanges) {
      for (int32 i = 0; i < d.inputParameterChanges->getParameterCount(); i++) {
        auto *q = d.inputParameterChanges->getParameterData(i);
        int32 off;
        ParamValue v;
        if (!q || q->getPoint(q->getPointCount() - 1, off, v) != kResultTrue) continue;
        apply(q->getParameterId(), v);
      }
    }
    if (!d.numInputs || !d.numOutputs || !d.numSamples) return kResultOk;
    auto &in = d.inputs[0];
    auto &out = d.outputs[0];
    int ch = out.numChannels;
    for (int c = 0; c < ch; c++) {
      float *src = in.channelBuffers32[std::min(c, in.numChannels - 1)];
      if (src != out.channelBuffers32[c]) memcpy(out.channelBuffers32[c], src, (size_t)d.numSamples * sizeof(float));
    }
    dsp.process(out.channelBuffers32[0], ch > 1 ? out.channelBuffers32[1] : nullptr, d.numSamples, noise, mix, output);
    out.silenceFlags = 0;
    return kResultOk;
  }

  tresult PLUGIN_API setState(IBStream *s) SMTG_OVERRIDE {
    IBStreamer r(s, kLittleEndian);
    double v[4];
    for (double &x : v)
      if (!r.readDouble(x)) return kResultFalse;
    for (int i = 0; i < 4; i++) {
      apply(i, v[i]);
      SingleComponentEffect::setParamNormalized(i, v[i]);
    }
    return kResultOk;
  }
  tresult PLUGIN_API getState(IBStream *s) SMTG_OVERRIDE {
    IBStreamer w(s, kLittleEndian);
    for (int i = 0; i < 4; i++) w.writeDouble(getParamNormalized(i));
    return kResultOk;
  }

 private:
  void apply(ParamID id, ParamValue v) {
    if (id == kPreset) {
      int p = std::min((int)(v * (bc::NUM_PRESETS - 1) + 0.5), bc::NUM_PRESETS - 1);
      if (p != preset) {
        preset = p;
        dsp.prepare(preset, sr);
      }
    } else if (id == kNoise) noise = v * 2;
    else if (id == kMix) mix = v;
    else if (id == kOutput) output = -24 + v * 36;
  }
  bc::Processor dsp;
  int preset = 0;
  double sr = 48000, noise = 1, mix = 1, output = 0;
};

BEGIN_FACTORY_DEF("rosarydigital", "https://github.com/rosarydigital/badcamera", "mailto:noreply@example.com")
DEF_CLASS2(INLINE_UID_FROM_FUID(kUid), PClassInfo::kManyInstances, kVstAudioEffectClass, "BadCamera Hardware", 0, "Fx|Distortion", "1.0.0", kVstVersionString, Effect::create)
END_FACTORY
