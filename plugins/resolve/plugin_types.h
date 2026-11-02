#pragma once
#include <string>
#include <vector>

struct ParamDef {
  const char *key, *label, *kind;
  double value, lo, hi;
  double vec[3];
  const char *text;
  std::vector<const char *> options;
};

struct EffectDef {
  const char *type, *label, *group;
  std::vector<ParamDef> params;
};
