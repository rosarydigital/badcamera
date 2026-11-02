// BadCamera for DaVinci Resolve (and any OpenFX host). One small plugin per effect, plus "BadCamera Look" for whole presets.
// Frames go to the BadCamera engine on this computer and come back through the same GPU chain as the app.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#define CLOSE closesocket
typedef SOCKET sock_t;
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
#define CLOSE close
typedef int sock_t;
#endif

#include "ofxCore.h"
#include "ofxImageEffect.h"
#include "ofxMemory.h"
#include "ofxMultiThread.h"
#include "ofxParam.h"
#include "ofxProperty.h"
#include "tables.h"

static const int PORT = 47128;
static OfxHost *gHost = nullptr;
static OfxPropertySuiteV1 *P = nullptr;
static OfxParameterSuiteV1 *Q = nullptr;
static OfxImageEffectSuiteV1 *E = nullptr;

static std::string home_path(const char *name) {
#ifdef _WIN32
  const char *h = getenv("USERPROFILE");
#else
  const char *h = getenv("HOME");
#endif
  return std::string(h ? h : ".") + "/.config/badcamera/" + name;
}

static std::vector<std::string> preset_names() {
  std::vector<std::string> out;
  std::ifstream f(home_path("presets.txt"));
  std::string line;
  while (std::getline(f, line))
    if (!line.empty()) out.push_back(line);
  if (out.empty())
    for (auto p : BUILTIN_PRESETS) out.push_back(p);
  return out;
}

static std::string json_str(const std::string &s) {
  std::string o = "\"";
  for (char c : s) {
    if (c == '"' || c == '\\') o += '\\';
    if ((unsigned char)c >= 0x20) o += c;
  }
  return o + "\"";
}

// ---- connection to the engine ----

static std::string engine_path() {
  if (const char *e = getenv("BADCAMERA_ENGINE")) return e;
  std::ifstream f(home_path("engine"));
  std::string line;
  std::getline(f, line);
  return line;
}

static void start_engine() {
  std::string path = engine_path();
  if (path.empty()) return;
#ifdef _WIN32
  std::string cmd = "\"" + path + "\" --serve";
  STARTUPINFOA si{};
  si.cb = sizeof(si);
  PROCESS_INFORMATION pi{};
  CreateProcessA(nullptr, cmd.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi);
#else
  if (fork() == 0) {
    setsid();
    unsetenv("LD_LIBRARY_PATH");  // the host's libraries are not the engine's
    execl(path.c_str(), path.c_str(), "--serve", (char *)nullptr);
    _exit(127);
  }
#endif
}

static sock_t try_connect() {
  sock_t s = socket(AF_INET, SOCK_STREAM, 0);
  sockaddr_in a{};
  a.sin_family = AF_INET;
  a.sin_port = htons(PORT);
  a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  if (connect(s, (sockaddr *)&a, sizeof(a)) != 0) {
    CLOSE(s);
    return (sock_t)-1;
  }
  int one = 1;
  setsockopt(s, IPPROTO_TCP, TCP_NODELAY, (const char *)&one, sizeof(one));
  return s;
}

static bool send_all(sock_t s, const void *data, size_t n) {
  const char *p = (const char *)data;
  while (n) {
    auto k = send(s, p, (int)std::min<size_t>(n, 1 << 24), 0);
    if (k <= 0) return false;
    p += k;
    n -= (size_t)k;
  }
  return true;
}

static bool recv_all(sock_t s, void *data, size_t n) {
  char *p = (char *)data;
  while (n) {
    auto k = recv(s, p, (int)std::min<size_t>(n, 1 << 24), 0);
    if (k <= 0) return false;
    p += k;
    n -= (size_t)k;
  }
  return true;
}

struct Instance {
  sock_t sock = (sock_t)-1;
  long long id = 0;
  std::mutex lock;
  std::vector<float> in;
  OfxImageClipHandle src = nullptr, dst = nullptr;
  OfxParamSetHandle params = nullptr;
};
static long long gNextId = 1;

static bool connected(Instance *in) {
  using clock = std::chrono::steady_clock;
  static clock::time_point lastFail{};
  if (in->sock != (sock_t)-1) return true;
  in->sock = try_connect();
  if (in->sock != (sock_t)-1) return true;
  // Never hold up the host's render over a missing engine: after a failed start, don't try again for a minute.
  if (engine_path().empty() || (lastFail != clock::time_point{} && clock::now() - lastFail < std::chrono::seconds(60))) return false;
  start_engine();
  for (int i = 0; i < 100 && in->sock == (sock_t)-1; i++) {  // first launch can take a few seconds
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    in->sock = try_connect();
  }
  if (in->sock == (sock_t)-1) lastFail = clock::now();
  return in->sock != (sock_t)-1;
}

// ---- describing ----

static void describe(OfxImageEffectHandle h, const std::string &label, const std::string &group) {
  OfxPropertySetHandle e;
  E->getPropertySet(h, &e);
  P->propSetString(e, kOfxPropLabel, 0, label.c_str());
  P->propSetString(e, kOfxImageEffectPluginPropGrouping, 0, group.c_str());
  P->propSetString(e, kOfxImageEffectPropSupportedContexts, 0, kOfxImageEffectContextFilter);
  P->propSetString(e, kOfxImageEffectPropSupportedContexts, 1, kOfxImageEffectContextGeneral);
  P->propSetString(e, kOfxImageEffectPropSupportedPixelDepths, 0, kOfxBitDepthFloat);
  P->propSetInt(e, kOfxImageEffectPropSupportsTiles, 0, 0);
  P->propSetInt(e, kOfxImageEffectPropSupportsMultiResolution, 0, 0);
  P->propSetInt(e, kOfxImageEffectPluginPropSingleInstance, 0, 0);
  P->propSetInt(e, kOfxImageEffectPluginPropHostFrameThreading, 0, 0);
  P->propSetString(e, kOfxImageEffectPluginRenderThreadSafety, 0, kOfxImageEffectRenderInstanceSafe);
  P->propSetInt(e, kOfxImageEffectPropTemporalClipAccess, 0, 0);
}

static void define_clips(OfxImageEffectHandle h) {
  for (const char *name : {kOfxImageEffectSimpleSourceClipName, kOfxImageEffectOutputClipName}) {
    OfxPropertySetHandle c;
    E->clipDefine(h, name, &c);
    P->propSetString(c, kOfxImageEffectPropSupportedComponents, 0, kOfxImageComponentRGBA);
    P->propSetInt(c, kOfxImageClipPropOptional, 0, 0);
  }
}

static void define_mix(OfxParamSetHandle set) {
  OfxPropertySetHandle p;
  Q->paramDefine(set, kOfxParamTypeDouble, "bc_mix", &p);
  P->propSetString(p, kOfxPropLabel, 0, "Mix");
  P->propSetDouble(p, kOfxParamPropDefault, 0, 1.0);
  P->propSetDouble(p, kOfxParamPropMin, 0, 0.0);
  P->propSetDouble(p, kOfxParamPropMax, 0, 1.0);
  P->propSetDouble(p, kOfxParamPropDisplayMin, 0, 0.0);
  P->propSetDouble(p, kOfxParamPropDisplayMax, 0, 1.0);
  P->propSetString(p, kOfxParamPropDoubleType, 0, kOfxParamDoubleTypeScale);
}

static void define_param(OfxParamSetHandle set, const ParamDef &d) {
  OfxPropertySetHandle p;
  std::string k = d.kind;
  if (k == "float") {
    Q->paramDefine(set, kOfxParamTypeDouble, d.key, &p);
    P->propSetDouble(p, kOfxParamPropDefault, 0, d.value);
    P->propSetDouble(p, kOfxParamPropMin, 0, d.lo);
    P->propSetDouble(p, kOfxParamPropMax, 0, d.hi);
    P->propSetDouble(p, kOfxParamPropDisplayMin, 0, d.lo);
    P->propSetDouble(p, kOfxParamPropDisplayMax, 0, d.hi);
  } else if (k == "int") {
    Q->paramDefine(set, kOfxParamTypeInteger, d.key, &p);
    P->propSetInt(p, kOfxParamPropDefault, 0, (int)d.value);
    P->propSetInt(p, kOfxParamPropMin, 0, (int)d.lo);
    P->propSetInt(p, kOfxParamPropMax, 0, (int)d.hi);
    P->propSetInt(p, kOfxParamPropDisplayMin, 0, (int)d.lo);
    P->propSetInt(p, kOfxParamPropDisplayMax, 0, (int)d.hi);
  } else if (k == "bool") {
    Q->paramDefine(set, kOfxParamTypeBoolean, d.key, &p);
    P->propSetInt(p, kOfxParamPropDefault, 0, (int)d.value);
  } else if (k == "enum") {
    Q->paramDefine(set, kOfxParamTypeChoice, d.key, &p);
    int def = 0;
    for (size_t i = 0; i < d.options.size(); i++) {
      P->propSetString(p, kOfxParamPropChoiceOption, (int)i, d.options[i]);
      if (!strcmp(d.options[i], d.text)) def = (int)i;
    }
    P->propSetInt(p, kOfxParamPropDefault, 0, def);
  } else if (k == "color") {
    Q->paramDefine(set, kOfxParamTypeRGB, d.key, &p);
    for (int i = 0; i < 3; i++) P->propSetDouble(p, kOfxParamPropDefault, i, d.vec[i]);
  } else if (k == "vec3") {
    Q->paramDefine(set, kOfxParamTypeDouble3D, d.key, &p);
    for (int i = 0; i < 3; i++) {
      P->propSetDouble(p, kOfxParamPropDefault, i, d.vec[i]);
      P->propSetDouble(p, kOfxParamPropMin, i, d.lo);
      P->propSetDouble(p, kOfxParamPropMax, i, d.hi);
      P->propSetDouble(p, kOfxParamPropDisplayMin, i, d.lo);
      P->propSetDouble(p, kOfxParamPropDisplayMax, i, d.hi);
    }
  } else {
    Q->paramDefine(set, kOfxParamTypeString, d.key, &p);
    P->propSetString(p, kOfxParamPropDefault, 0, d.text);
  }
  P->propSetString(p, kOfxPropLabel, 0, d.label);
}

// ---- rendering ----

// One keyframed value as JSON. Returns "" for a param this effect doesn't have.
static std::string read_param(OfxParamSetHandle set, const ParamDef &d, OfxTime t) {
  OfxParamHandle h;
  if (Q->paramGetHandle(set, d.key, &h, nullptr) != kOfxStatOK) return "";
  std::ostringstream o;
  o.precision(17);
  std::string k = d.kind;
  if (k == "float") {
    double v = 0;
    Q->paramGetValueAtTime(h, t, &v);
    o << v;
  } else if (k == "int") {
    int v = 0;
    Q->paramGetValueAtTime(h, t, &v);
    o << v;
  } else if (k == "bool") {
    int v = 0;
    Q->paramGetValueAtTime(h, t, &v);
    o << (v ? "true" : "false");
  } else if (k == "enum") {
    int v = 0;
    Q->paramGetValueAtTime(h, t, &v);
    o << json_str(d.options.empty() ? "" : d.options[std::min<size_t>(v, d.options.size() - 1)]);
  } else if (k == "color") {
    double r = 0, g = 0, b = 0;
    Q->paramGetValueAtTime(h, t, &r, &g, &b);
    o << "[" << r << "," << g << "," << b << "]";
  } else if (k == "vec3") {
    double r = 0, g = 0, b = 0;
    Q->paramGetValueAtTime(h, t, &r, &g, &b);
    o << "[" << r << "," << g << "," << b << "]";
  } else {
    char *s = nullptr;
    Q->paramGetValueAtTime(h, t, &s);
    o << json_str(s ? s : "");
  }
  return o.str();
}

static OfxStatus render(OfxImageEffectHandle fx, OfxPropertySetHandle inArgs, int index) {
  void *data = nullptr;
  OfxPropertySetHandle e;
  E->getPropertySet(fx, &e);
  P->propGetPointer(e, kOfxPropInstanceData, 0, &data);
  auto *in = (Instance *)data;
  if (!in) return kOfxStatFailed;
  OfxTime t;
  P->propGetDouble(inArgs, kOfxPropTime, 0, &t);

  OfxPropertySetHandle srcImg = nullptr, dstImg = nullptr;
  if (E->clipGetImage(in->src, t, nullptr, &srcImg) != kOfxStatOK) return kOfxStatFailed;
  if (E->clipGetImage(in->dst, t, nullptr, &dstImg) != kOfxStatOK) {
    E->clipReleaseImage(srcImg);
    return kOfxStatFailed;
  }
  void *sp, *dp;
  int sb[4], db[4], srow, drow;
  P->propGetPointer(srcImg, kOfxImagePropData, 0, &sp);
  P->propGetPointer(dstImg, kOfxImagePropData, 0, &dp);
  P->propGetIntN(srcImg, kOfxImagePropBounds, 4, sb);
  P->propGetIntN(dstImg, kOfxImagePropBounds, 4, db);
  P->propGetInt(srcImg, kOfxImagePropRowBytes, 0, &srow);
  P->propGetInt(dstImg, kOfxImagePropRowBytes, 0, &drow);
  int w = sb[2] - sb[0], h = sb[3] - sb[1];

  double mix = 1.0;
  OfxParamHandle mh;
  if (Q->paramGetHandle(in->params, "bc_mix", &mh, nullptr) == kOfxStatOK) Q->paramGetValueAtTime(mh, t, &mix);

  double fps = 24.0;
  P->propGetDouble(e, kOfxImageEffectPropFrameRate, 0, &fps);
  std::ostringstream json;
  json.precision(17);  // noise is seeded from time, so it has to arrive exact
  json << "{\"instance\":" << in->id << ",\"w\":" << w << ",\"h\":" << h << ",\"time\":" << t / std::max(fps, 1.0) << ",\"frame\":" << (long long)t;
  if (index < (int)EFFECTS.size()) {
    const EffectDef &def = EFFECTS[index];
    json << ",\"effect\":" << json_str(def.type) << ",\"params\":{";
    bool first = true;
    for (const auto &d : def.params) {
      std::string v = read_param(in->params, d, t);
      if (v.empty()) continue;
      json << (first ? "" : ",") << json_str(d.key) << ":" << v;
      first = false;
    }
    json << "}";
  } else {
    OfxParamHandle ph;
    int choice = 0;
    Q->paramGetHandle(in->params, "bc_look", &ph, nullptr);
    Q->paramGetValueAtTime(ph, t, &choice);
    auto names = preset_names();
    json << ",\"preset\":" << json_str(names[std::min<size_t>(choice, names.size() - 1)]);
  }
  json << "}";
  std::string header = json.str();

  in->in.resize((size_t)w * h * 4);
  for (int y = 0; y < h; y++) memcpy(in->in.data() + (size_t)y * w * 4, (char *)sp + (size_t)y * srow, (size_t)w * 16);

  bool ok = false;
  std::vector<float> out((size_t)w * h * 4);
  {
    std::lock_guard<std::mutex> guard(in->lock);
    if (connected(in)) {
      unsigned int n = (unsigned int)header.size();
      ok = send_all(in->sock, &n, 4) && send_all(in->sock, header.data(), n) && send_all(in->sock, in->in.data(), out.size() * 4) && recv_all(in->sock, out.data(), out.size() * 4);
      if (!ok) {
        CLOSE(in->sock);
        in->sock = (sock_t)-1;
      }
    }
  }
  const float *res = ok ? out.data() : in->in.data();  // if the engine can't run, pass the picture through rather than fail the render
  float m = ok ? (float)mix : 0.0f;
  for (int y = 0; y < h; y++) {
    auto *d = (float *)((char *)dp + (size_t)y * drow);
    const float *r = res + (size_t)y * w * 4, *s = in->in.data() + (size_t)y * w * 4;
    for (int x = 0; x < w; x++, d += 4, r += 4, s += 4) {
      for (int c = 0; c < 3; c++) d[c] = s[c] + (r[c] - s[c]) * m;
      d[3] = s[3];  // keep the clip's own alpha
    }
  }
  E->clipReleaseImage(srcImg);
  E->clipReleaseImage(dstImg);
  return kOfxStatOK;
}

static OfxStatus entry(int index, const char *action, const void *handle, OfxPropertySetHandle inArgs, OfxPropertySetHandle) {
  auto fx = (OfxImageEffectHandle)handle;
  bool look = index >= (int)EFFECTS.size();
  if (!strcmp(action, kOfxActionLoad)) {
    P = (OfxPropertySuiteV1 *)gHost->fetchSuite(gHost->host, kOfxPropertySuite, 1);
    Q = (OfxParameterSuiteV1 *)gHost->fetchSuite(gHost->host, kOfxParameterSuite, 1);
    E = (OfxImageEffectSuiteV1 *)gHost->fetchSuite(gHost->host, kOfxImageEffectSuite, 1);
#ifdef _WIN32
    WSADATA w;
    WSAStartup(MAKEWORD(2, 2), &w);
#endif
    return (P && Q && E) ? kOfxStatOK : kOfxStatErrMissingHostFeature;
  }
  if (!strcmp(action, kOfxActionDescribe)) {
    if (look) describe(fx, "BadCamera Look", "BadCamera");
    else describe(fx, EFFECTS[index].label, std::string("BadCamera/") + EFFECTS[index].group);
    return kOfxStatOK;
  }
  if (!strcmp(action, kOfxImageEffectActionDescribeInContext)) {
    define_clips(fx);
    OfxParamSetHandle set;
    E->getParamSet(fx, &set);
    if (look) {
      OfxPropertySetHandle p;
      Q->paramDefine(set, kOfxParamTypeChoice, "bc_look", &p);
      P->propSetString(p, kOfxPropLabel, 0, "Look");
      auto names = preset_names();
      for (size_t i = 0; i < names.size(); i++) P->propSetString(p, kOfxParamPropChoiceOption, (int)i, names[i].c_str());
    }
    define_mix(set);
    if (!look)
      for (const auto &d : EFFECTS[index].params) define_param(set, d);
    return kOfxStatOK;
  }
  if (!strcmp(action, kOfxActionCreateInstance)) {
    auto *in = new Instance;
    in->id = gNextId++;
    E->clipGetHandle(fx, kOfxImageEffectSimpleSourceClipName, &in->src, nullptr);
    E->clipGetHandle(fx, kOfxImageEffectOutputClipName, &in->dst, nullptr);
    E->getParamSet(fx, &in->params);
    OfxPropertySetHandle e;
    E->getPropertySet(fx, &e);
    P->propSetPointer(e, kOfxPropInstanceData, 0, in);
    return kOfxStatOK;
  }
  if (!strcmp(action, kOfxActionDestroyInstance)) {
    void *data = nullptr;
    OfxPropertySetHandle e;
    E->getPropertySet(fx, &e);
    P->propGetPointer(e, kOfxPropInstanceData, 0, &data);
    auto *in = (Instance *)data;
    if (in) {
      if (in->sock != (sock_t)-1) CLOSE(in->sock);
      delete in;
    }
    return kOfxStatOK;
  }
  if (!strcmp(action, kOfxImageEffectActionRender)) return render(fx, inArgs, index);
  return kOfxStatReplyDefault;
}

static void set_host(OfxHost *h) { gHost = h; }

// OFX gives an entry point no way to know which plugin it is, so each plugin gets its own stamped-out function.
template <int N>
static OfxStatus main_entry(const char *a, const void *h, OfxPropertySetHandle i, OfxPropertySetHandle o) {
  return entry(N, a, h, i, o);
}

static const int MAX_PLUGINS = 64;
static std::string gIds[MAX_PLUGINS];
static OfxPlugin gPlugins[MAX_PLUGINS];

template <int... N>
static void fill(std::integer_sequence<int, N...>) {
  OfxPluginEntryPoint *entries[] = {main_entry<N>...};
  int count = (int)EFFECTS.size() + 1;
  for (int i = 0; i < count; i++) {
    gIds[i] = i < (int)EFFECTS.size() ? std::string("com.rosarydigital.badcamera.") + EFFECTS[i].type : "com.rosarydigital.badcamera.look";
    gPlugins[i] = {kOfxImageEffectPluginApi, 1, gIds[i].c_str(), 1, 0, set_host, entries[i]};
  }
}

extern "C" {
OfxExport int OfxGetNumberOfPlugins(void) {
  static bool once = (fill(std::make_integer_sequence<int, MAX_PLUGINS>{}), true);
  (void)once;
  return (int)EFFECTS.size() + 1;
}
OfxExport OfxPlugin *OfxGetPlugin(int n) {
  OfxGetNumberOfPlugins();
  return &gPlugins[n];
}
}
