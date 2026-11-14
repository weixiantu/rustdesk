// ============================================================================
// ZowinDesk 自有版本号（macOS 端）。发新版时只需把 kZdBuild +1、kZdVersion 改名。
//
// 与 Windows / 安卓端互相独立：
//   1) kZdBuild += 1，kZdVersion 改为 V<编号>；
//   2) 官网 version-macos.json 的 min_build 对齐到同一个 kZdBuild。
// Windows 的 version.json 与安卓的 version-android.json 不受本文件影响。
// ============================================================================

/// 与官网 version-macos.json 的 min_build 对齐。
const int kZdBuild = 14;

/// 用户可见版本号（关于页 / Finder 显示用）。
const String kZdVersion = 'V14';
