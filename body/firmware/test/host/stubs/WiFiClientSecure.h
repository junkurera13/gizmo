#pragma once
inline const char* mock_health_ca=nullptr;
struct WiFiClientSecure { void setCACert(const char* ca) { mock_health_ca=ca; } };
