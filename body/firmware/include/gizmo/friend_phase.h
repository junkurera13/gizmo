#pragma once
#include <stdint.h>
namespace gizmo {
enum class FriendPhase : uint8_t { kOff, kNeedConfig, kHealth, kConnecting, kOnline, kBackoff };
const char* friend_phase_name(FriendPhase phase);
}
