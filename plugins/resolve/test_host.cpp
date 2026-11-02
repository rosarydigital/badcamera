// A tiny OpenFX host for testing without Resolve: loads the plugin, describes everything, then renders a frame through a chosen plugin.
// Usage: test_host BadCamera.ofx list | test_host BadCamera.ofx render <plugin id> in.rgbaf out.rgbaf w h [key=value ...]
#include <dlfcn.h>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <string>
#include <vector>
#include "ofxCore.h"
#include "ofxImageEffect.h"
#include "ofxMemory.h"
#include "ofxMultiThread.h"
#include "ofxParam.h"
#include "ofxProperty.h"

struct Prop { std::vector<std::string> s; std::vector<int> i; std::vector<double> d; std::vector<void *> p; };
struct Props { std::map<std::string, Prop> m; };
struct Param { std::string name, type; Props props; };
struct Clip { Props props; };
struct Effect { Props props; std::map<std::string, Clip> clips; std::map<std::string, Param> params; std::vector<float> *in = nullptr, *out = nullptr; int w = 0, h = 0; };

#define SETTER(NAME, T, FIELD, CONV) \
  static OfxStatus NAME(OfxPropertySetHandle h, const char *k, int i, T v) { auto &f = ((Props *)h)->m[k].FIELD; if ((int)f.size() <= i) f.resize(i + 1); f[i] = CONV; return kOfxStatOK; }
#define GETTER(NAME, T, FIELD, CONV) \
  static OfxStatus NAME(OfxPropertySetHandle h, const char *k, int i, T *v) { auto &m = ((Props *)h)->m; auto it = m.find(k); if (it == m.end() || (int)it->second.FIELD.size() <= i) return kOfxStatErrUnknown; *v = CONV; return kOfxStatOK; }
SETTER(setP, void *, p, v) SETTER(setS, const char *, s, std::string(v)) SETTER(setD, double, d, v) SETTER(setI, int, i, v)
GETTER(getP, void *, p, it->second.p[i]) GETTER(getD, double, d, it->second.d[i]) GETTER(getI, int, i, it->second.i[i])
static OfxStatus getS(OfxPropertySetHandle h, const char *k, int i, char **v) { auto &m = ((Props *)h)->m; auto it = m.find(k); if (it == m.end() || (int)it->second.s.size() <= i) return kOfxStatErrUnknown; *v = (char *)it->second.s[i].c_str(); return kOfxStatOK; }
static OfxStatus getIN(OfxPropertySetHandle h, const char *k, int n, int *v) { for (int i = 0; i < n; i++) if (getI(h, k, i, v + i) != kOfxStatOK) return kOfxStatErrUnknown; return kOfxStatOK; }

static OfxPropertySuiteV1 PS;
static OfxParameterSuiteV1 QS;
static OfxImageEffectSuiteV1 ES;
static int defined = 0;
static std::map<std::string, std::string> overrides;

static OfxStatus getPS(OfxImageEffectHandle h, OfxPropertySetHandle *p) { *p = (OfxPropertySetHandle)&((Effect *)h)->props; return kOfxStatOK; }
static OfxStatus getParams(OfxImageEffectHandle h, OfxParamSetHandle *p) { *p = (OfxParamSetHandle)h; return kOfxStatOK; }
static OfxStatus clipDefine(OfxImageEffectHandle h, const char *n, OfxPropertySetHandle *p) { *p = (OfxPropertySetHandle)&((Effect *)h)->clips[n].props; return kOfxStatOK; }
static OfxStatus clipHandle(OfxImageEffectHandle h, const char *n, OfxImageClipHandle *c, OfxPropertySetHandle *) { auto &m = ((Effect *)h)->clips; if (!m.count(n)) return kOfxStatErrUnknown; *c = (OfxImageClipHandle)&m[n]; return kOfxStatOK; }
static Effect *cur = nullptr;
static OfxStatus clipImage(OfxImageClipHandle c, OfxTime, const OfxRectD *, OfxPropertySetHandle *out) {
  auto *img = new Props;
  bool src = c == (OfxImageClipHandle)&cur->clips[kOfxImageEffectSimpleSourceClipName];
  void *data = src ? cur->in->data() : cur->out->data();
  auto h = (OfxPropertySetHandle)img;
  setP(h, kOfxImagePropData, 0, data);
  int b[4] = {0, 0, cur->w, cur->h};
  for (int i = 0; i < 4; i++) setI(h, kOfxImagePropBounds, i, b[i]);
  setI(h, kOfxImagePropRowBytes, 0, cur->w * 16);
  *out = h;
  return kOfxStatOK;
}
static OfxStatus clipRelease(OfxPropertySetHandle h) { delete (Props *)h; return kOfxStatOK; }

static OfxStatus pDefine(OfxParamSetHandle s, const char *type, const char *n, OfxPropertySetHandle *p) { auto &q = ((Effect *)s)->params[n]; q.name = n; q.type = type; *p = (OfxPropertySetHandle)&q.props; defined++; return kOfxStatOK; }
static OfxStatus pHandle(OfxParamSetHandle s, const char *n, OfxParamHandle *h, OfxPropertySetHandle *) { auto &m = ((Effect *)s)->params; if (!m.count(n)) return kOfxStatErrUnknown; *h = (OfxParamHandle)&m[n]; return kOfxStatOK; }
static OfxStatus pValue(OfxParamHandle h, OfxTime, ...) {
  auto *q = (Param *)h;
  va_list a;
  va_start(a, h);
  auto &d = q->props.m[kOfxParamPropDefault];
  auto o = overrides.find(q->name);
  if (q->type == kOfxParamTypeDouble) { *va_arg(a, double *) = o != overrides.end() ? atof(o->second.c_str()) : d.d.at(0); }
  else if (q->type == kOfxParamTypeInteger || q->type == kOfxParamTypeBoolean) { *va_arg(a, int *) = o != overrides.end() ? atoi(o->second.c_str()) : d.i.at(0); }
  else if (q->type == kOfxParamTypeChoice) {
    int v = d.i.empty() ? 0 : d.i[0];
    if (o != overrides.end()) { auto &c = q->props.m[kOfxParamPropChoiceOption].s; for (size_t i = 0; i < c.size(); i++) if (c[i] == o->second) v = (int)i; }
    *va_arg(a, int *) = v;
  } else if (q->type == kOfxParamTypeString) { *va_arg(a, char **) = (char *)d.s.at(0).c_str(); }
  else for (int i = 0; i < 3; i++) *va_arg(a, double *) = d.d.at(i);
  va_end(a);
  return kOfxStatOK;
}

static const void *fetch(OfxPropertySetHandle, const char *name, int) {
  if (!strcmp(name, kOfxPropertySuite)) return &PS;
  if (!strcmp(name, kOfxParameterSuite)) return &QS;
  if (!strcmp(name, kOfxImageEffectSuite)) return &ES;
  return nullptr;
}

int main(int c, char **v) {
  PS = {}; QS = {}; ES = {};
  PS.propSetPointer = setP; PS.propSetString = setS; PS.propSetDouble = setD; PS.propSetInt = setI;
  PS.propGetPointer = getP; PS.propGetString = getS; PS.propGetDouble = getD; PS.propGetInt = getI; PS.propGetIntN = getIN;
  QS.paramDefine = pDefine; QS.paramGetHandle = pHandle; QS.paramGetValueAtTime = pValue;
  ES.getPropertySet = getPS; ES.getParamSet = getParams; ES.clipDefine = clipDefine; ES.clipGetHandle = clipHandle; ES.clipGetImage = clipImage; ES.clipReleaseImage = clipRelease;
  static Props hostProps;
  static OfxHost host{(OfxPropertySetHandle)&hostProps, fetch};
  void *lib = dlopen(v[1], RTLD_NOW);
  if (!lib) { printf("dlopen: %s\n", dlerror()); return 1; }
  auto count = (int (*)())dlsym(lib, "OfxGetNumberOfPlugins");
  auto get = (OfxPlugin * (*)(int)) dlsym(lib, "OfxGetPlugin");
  int n = count();
  bool render = !strcmp(v[2], "render");
  std::string want = render ? v[3] : "";
  for (int i = 3; i < c; i++) { auto s = std::string(v[i]); auto e = s.find('='); if (e != std::string::npos) overrides[s.substr(0, e)] = s.substr(e + 1); }
  for (int i = 0; i < n; i++) {
    OfxPlugin *p = get(i);
    if (strcmp(p->pluginApi, kOfxImageEffectPluginApi)) { printf("bad api\n"); return 1; }
    p->setHost(&host);
    if (render && want != p->pluginIdentifier) continue;
    if (p->mainEntry(kOfxActionLoad, nullptr, nullptr, nullptr) != kOfxStatOK) { printf("load failed %s\n", p->pluginIdentifier); return 1; }
    Effect fx;
    if (p->mainEntry(kOfxActionDescribe, &fx, nullptr, nullptr) != kOfxStatOK) { printf("describe failed\n"); return 1; }
    Effect ctx;
    if (p->mainEntry(kOfxImageEffectActionDescribeInContext, &ctx, nullptr, nullptr) != kOfxStatOK) { printf("context failed\n"); return 1; }
    if (!render) {
      printf("%s | %s | %s | %d params\n", p->pluginIdentifier, fx.props.m[kOfxPropLabel].s[0].c_str(), fx.props.m[kOfxImageEffectPluginPropGrouping].s[0].c_str(), (int)ctx.params.size());
      continue;
    }
    int w = atoi(v[6]), h = atoi(v[7]);
    std::vector<float> in((size_t)w * h * 4), out((size_t)w * h * 4);
    std::ifstream(v[4], std::ios::binary).read((char *)in.data(), in.size() * 4);
    ctx.in = &in; ctx.out = &out; ctx.w = w; ctx.h = h; cur = &ctx;
    setD((OfxPropertySetHandle)&ctx.props, kOfxImageEffectPropFrameRate, 0, 30.0);
    p->mainEntry(kOfxActionCreateInstance, &ctx, nullptr, nullptr);
    Props args;
    OfxStatus st = kOfxStatOK;
    int frames = overrides.count("frames") ? atoi(overrides["frames"].c_str()) : 1;
    for (int f = 0; f < frames; f++) {
      setD((OfxPropertySetHandle)&args, kOfxPropTime, 0, (double)f);
      st = p->mainEntry(kOfxImageEffectActionRender, &ctx, (OfxPropertySetHandle)&args, nullptr);
      if (st != kOfxStatOK) { printf("render failed %d\n", st); return 1; }
    }
    p->mainEntry(kOfxActionDestroyInstance, &ctx, nullptr, nullptr);
    std::ofstream(v[5], std::ios::binary).write((char *)out.data(), out.size() * 4);
    printf("rendered %s\n", p->pluginIdentifier);
  }
  return 0;
}
