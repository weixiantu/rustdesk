#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZowinDesk 安卓端构建期补丁（在 GitHub Actions 里执行，不提交进仓库）。

用法： python3 zd_android_patch.py <zd_icons.json>
工作目录必须是 RustDesk 仓库根目录。

设计要点：
  1. 复用官方 1.5.1 APK 里已编译的 librustdesk.so，因此不重新编译 Rust；
     IP / Key 由 Dart 层在启动时写入 option（等价于官方 App 里手工填服务器，
     且设置入口被隐藏，用户改不了）。
  2. 隐藏「ID/中继服务器」菜单：把设置页的 _hideServer 直接固定为 true。
  3. 品牌化：应用名 / 图标 / 通知 / 无障碍服务 / 关于页 / 官网链接 / 登录入口。
  4. 升级提醒：与 Windows V13 同款（可关闭弹窗 + 稍后 + 连接守卫），
     但读取独立的 version-android.json，下载 APK 并通过 FileProvider 拉起安装。
"""
import base64
import json
import os
import re
import sys

ROOT = os.getcwd()
ICONS_JSON = sys.argv[1] if len(sys.argv) > 1 else "zd_icons.json"

ZD_SERVER = "43.139.157.84"
ZD_KEY = "PMEoK7kHVXLlHB4td8wk13ezTwKABynXQucZURTZtuo="
ZD_VERSION_URL = "https://www.zowinda.com/zowindesk/version-android.json"
ZD_APK_URL = "https://www.zowinda.com/zowindesk/ZowinDesk-android.apk"

# ---------------------------------------------------------------- 基础工具 ----

def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def write(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)


def rep(path, old, new, expect=1, label=""):
    s = read(path)
    n = s.count(old)
    if n != expect:
        raise SystemExit("FAIL %s: %s -> found %d, expected %d" %
                         (path, label or old[:60], n, expect))
    write(path, s.replace(old, new))
    print("  OK %-46s %s" % (label or old[:46], path.split("/")[-1]))


def rep_re(path, pattern, new, expect=1, label=""):
    s = read(path)
    s2, n = re.subn(pattern, new, s, flags=re.S)
    if n != expect:
        raise SystemExit("FAIL %s: regex %s -> found %d, expected %d" %
                         (path, label, n, expect))
    write(path, s2)
    print("  OK %-46s %s" % (label, path.split("/")[-1]))


def add_imports(path, imports, label=""):
    lines = read(path).splitlines(True)
    idx = max(i for i, l in enumerate(lines) if l.startswith("import "))
    for imp in reversed(imports):
        lines.insert(idx + 1, imp + "\n")
    write(path, "".join(lines))
    print("  OK %-46s %s" % (label or "imports", path.split("/")[-1]))


# ------------------------------------------------------------ 新增 Dart 模块 ----

ZD_VERSION_DART = r"""// ZowinDesk 自有版本号（安卓端）。发新版时只需把 kZdBuild +1、kZdVersion 改名。
const int kZdBuild = 13;
const String kZdVersion = 'V13';
"""

ZD_CONFIG_DART = r"""// ZowinDesk 固定服务器配置。
// 复用官方 librustdesk.so，Rust 层常量无法重编译，因此在启动时把配置写入 option。
// 这与官方 App 的「ID/中继服务器」设置页写入的是同一组 option；
// 由于该设置入口已被隐藏，用户无法改回，效果等同于 Windows 端编译期常量。
import 'package:flutter_hbb/models/platform_model.dart';

class ZdConfig {
  ZdConfig._();

  static bool _applied = false;

  static Future<void> apply() async {
    if (_applied) return;
    _applied = true;
    try {
      await bind.mainSetOption(
          key: 'custom-rendezvous-server', value: '__ZD_SERVER__');
      await bind.mainSetOption(key: 'relay-server', value: '');
      await bind.mainSetOption(key: 'api-server', value: '');
      await bind.mainSetOption(key: 'key', value: '__ZD_KEY__');
    } catch (_) {
      _applied = false; // FFI 尚未就绪时，下一次进主界面会重试
    }
  }
}
""".replace("__ZD_SERVER__", ZD_SERVER).replace("__ZD_KEY__", ZD_KEY)

ZD_UPGRADE_DART = r"""// ============================================================================
// ZowinDesk 安卓端升级提示模块（纯 Dart，与 Windows V13 行为一致）
//
//   1) 前期（version-android.json min_build <= kZdBuild）完全静默，装完即用；
//   2) 后台换 Key 后把 min_build 调高即提示升级，弹窗【始终可关闭】：
//      稍后 / 右上角 X / 点击遮罩 / 返回键都能关，下载中也能取消；
//   3) 关闭后本次启动不再自动弹，用户下次点「连接」时再次提醒；
//   4) 不升级就建立不了连接：点「连接」会被 onConnectAttempt() 拦下；
//   5) 检查走独立 HTTPS，不依赖 hbbs 通道（换 Key 后该通道本身已断）；
//   6) 下载 APK 后通过 FileProvider + ACTION_VIEW 直接拉起系统安装界面。
//
// 触发时机：启动后 3 秒 / 每 10 分钟 / 用户点「连接」。
// ============================================================================

import 'dart:async';
import 'dart:convert';
import 'dart:io';

// crypto 已在 pubspec.lock（传递依赖），无需改动 pubspec.yaml。
// ignore: depend_on_referenced_packages
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:get/get.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';

import 'zd_version.dart';

/// 安卓端专用版本清单，独立维护，改动它不会让线上 Windows 客户端误弹窗。
const String kZdVersionUrl = '__ZD_VERSION_URL__';

/// 固定 APK 文件名，清单里的 download_url 可覆盖。
const String kZdDefaultDownloadUrl = '__ZD_APK_URL__';

class ZdUpgrade {
  ZdUpgrade._();

  static const MethodChannel _installChannel =
      MethodChannel('zowindesk/install');

  static Timer? _startupTimer;
  static Timer? _periodicTimer;
  static DateTime? _lastFailureCheck;
  static bool _dialogShown = false;
  static bool _upgradeRequired = false;
  static bool _snoozed = false;
  static bool _cancelled = false;
  static http.Client? _downloadClient;
  static Map<String, dynamic>? _info;
  static String _localPath = '';

  /// 0 = 等待操作，1 = 下载中，2 = 已拉起安装，3 = 失败
  static final ValueNotifier<int> phase = ValueNotifier<int>(0);
  static final ValueNotifier<double> progress = ValueNotifier<double>(0);
  static final ValueNotifier<String> status = ValueNotifier<String>('');

  /// 在主界面 initState 调用。
  static void start() {
    if (_startupTimer != null || _periodicTimer != null) return;
    _startupTimer = Timer(const Duration(seconds: 3), () {
      _checkSilently();
    });
    _periodicTimer = Timer.periodic(const Duration(minutes: 10), (_) {
      _checkSilently();
    });
  }

  /// 连接状态异常 / 用户点连接时只静默复查（5 分钟节流），绝不弹窗骚扰。
  static void onConnectionFailure() {
    final now = DateTime.now();
    final last = _lastFailureCheck;
    if (last != null && now.difference(last) < const Duration(minutes: 5)) {
      return;
    }
    _lastFailureCheck = now;
    _checkSilently(silentOnly: true);
  }

  /// 在 connection_page.dart 的 onConnect() 开头调用。
  /// 返回 false = 已弹出升级提示、本次不发起连接（不升级使用不了）。
  static bool onConnectAttempt() {
    if (!_upgradeRequired) return true;
    _showDialog();
    return false;
  }

  static int _asInt(dynamic v) {
    if (v is int) return v;
    if (v is String) return int.tryParse(v) ?? 0;
    return 0;
  }

  /// 静默检查：任何网络 / 解析异常一律放过，绝不弹错误提示。
  /// 判定条件只有一个：min_build > 本客户端 kZdBuild。
  static Future<void> _checkSilently({bool silentOnly = false}) async {
    if (_dialogShown) return;
    try {
      final uri = Uri.parse('$kZdVersionUrl?b=$kZdBuild');
      final resp = await http
          .get(uri, headers: {'Cache-Control': 'no-cache'})
          .timeout(const Duration(seconds: 5));
      if (resp.statusCode != 200) return;
      final decoded =
          jsonDecode(utf8.decode(resp.bodyBytes, allowMalformed: true));
      if (decoded is! Map) return;
      final minBuild = _asInt(decoded['min_build']);
      // 前期 min_build == kZdBuild（或更低）时什么都不做，用户零感知。
      if (minBuild <= kZdBuild) {
        _upgradeRequired = false;
        _info = null;
        return;
      }
      _upgradeRequired = true;
      _info = Map<String, dynamic>.from(decoded);
      // 启动后自动提示一次即可；点过「稍后」后不再自动弹，只等点连接。
      if (!silentOnly && !_snoozed) _showDialog();
    } catch (_) {
      // 清单 404 / 断网 / JSON 异常都不影响正常使用，静默放过。
    }
  }

  static String _downloadUrl() {
    final v = _info?['download_url'];
    if (v is String && v.trim().isNotEmpty) return v.trim();
    return kZdDefaultDownloadUrl;
  }

  /// 可关闭的升级弹窗：没有 PopScope(canPop:false)，barrierDismissible 为 true，
  /// 提供「稍后」与右上角 X；任何关闭方式都会中止进行中的下载。
  static void _showDialog() {
    if (_dialogShown) return;
    final ctx = Get.context;
    if (ctx == null) return; // 界面未就绪，下一轮定时检查会重试
    _dialogShown = true;
    _cancelled = false;
    phase.value = 0;
    progress.value = 0;
    status.value = '';

    final title = (_info?['title'] ?? 'ZowinDesk 需要升级').toString();
    final message = (_info?['message'] ??
            '连接服务已升级，请安装新版本后继续使用。\n'
                '升级完成前无法建立连接，可点「稍后」先关闭本提示。')
        .toString();

    void dismiss() {
      if (Get.isDialogOpen ?? false) Get.back();
    }

    Get.dialog(
      ValueListenableBuilder<int>(
        valueListenable: phase,
        builder: (context, p, _) => AlertDialog(
          title: Row(children: [
            const Icon(Icons.system_update_alt, color: Color(0xFF2F65BA)),
            const SizedBox(width: 8),
            Expanded(child: Text(title)),
            IconButton(
              icon: const Icon(Icons.close, size: 20),
              tooltip: '关闭',
              onPressed: dismiss,
            ),
          ]),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(message),
              const SizedBox(height: 16),
              if (p == 1)
                ValueListenableBuilder<double>(
                  valueListenable: progress,
                  builder: (_, v, __) => LinearProgressIndicator(value: v),
                ),
              if (p == 1) const SizedBox(height: 8),
              ValueListenableBuilder<String>(
                valueListenable: status,
                builder: (_, s, __) => Text(
                  s.isEmpty ? '点击下方按钮自动下载并安装新版本。' : s,
                  style: const TextStyle(fontSize: 12, color: Colors.grey),
                ),
              ),
            ],
          ),
          actions: [
            if (p == 3)
              TextButton(
                onPressed: startDownload,
                child: const Text('重试'),
              ),
            if (p == 3)
              TextButton(
                onPressed: () async {
                  final u = Uri.tryParse(_downloadUrl());
                  if (u != null) {
                    await launchUrl(u, mode: LaunchMode.externalApplication);
                  }
                },
                child: const Text('手动下载'),
              ),
            TextButton(
              onPressed: dismiss,
              child: Text(p == 1 ? '取消并稍后' : '稍后'),
            ),
            ElevatedButton(
              onPressed: (p == 1 || p == 2) ? null : startDownload,
              child: Text(
                  p == 1 ? '下载中…' : (p == 2 ? '已启动安装' : '立即升级')),
            ),
          ],
        ),
      ),
      barrierDismissible: true,
      useSafeArea: true,
    ).then((_) {
      // 稍后 / X / 遮罩 / 返回键，统一收尾。
      _dialogShown = false;
      _snoozed = true;
      _cancelled = true;
      try {
        _downloadClient?.close();
      } catch (_) {}
    });
  }

  /// 下载 -> 校验 -> 拉起系统安装界面。
  static Future<void> startDownload() async {
    if (phase.value == 1) return;
    _cancelled = false;
    phase.value = 1;
    progress.value = 0;
    status.value = '正在连接下载服务器…';
    final client = http.Client();
    _downloadClient = client;
    try {
      final req = http.Request('GET', Uri.parse(_downloadUrl()));
      final resp = await client.send(req).timeout(const Duration(seconds: 30));
      if (resp.statusCode != 200) {
        throw 'HTTP ${resp.statusCode}';
      }
      final expectedSize = _asInt(_info?['size']);
      final expectedSha =
          (_info?['sha256'] ?? '').toString().trim().toLowerCase();
      final total = expectedSize > 0 ? expectedSize : (resp.contentLength ?? 0);

      Directory dir;
      try {
        dir = (await getExternalStorageDirectory()) ??
            (await getApplicationDocumentsDirectory());
      } catch (_) {
        dir = await getApplicationDocumentsDirectory();
      }
      final f = File('${dir.path}${Platform.pathSeparator}ZowinDesk-android.apk');
      _localPath = f.path;
      if (await f.exists()) await f.delete();

      final sink = f.openWrite();
      int received = 0;
      await sink.addStream(resp.stream
          .timeout(const Duration(seconds: 45))
          .map((List<int> chunk) {
        if (_cancelled) throw '用户已取消';
        received += chunk.length;
        if (total > 0) {
          progress.value = (received / total).clamp(0.0, 1.0).toDouble();
        }
        status.value = '正在下载 ${(received / 1048576).toStringAsFixed(1)} MB' +
            (total > 0
                ? ' / ${(total / 1048576).toStringAsFixed(1)} MB'
                : '');
        return chunk;
      }));
      await sink.flush();
      await sink.close();
      if (_cancelled) throw '用户已取消';

      // 校验 1：文件大小（清单填了 size 才校验）
      final actual = await f.length();
      if (expectedSize > 0 && actual != expectedSize) {
        throw '文件大小不符（$actual / $expectedSize）';
      }
      // 校验 2：APK 是 ZIP，头两字节必须是 PK，防止把 404 页面当安装包
      final raf = await f.open();
      final List<int> head = <int>[];
      try {
        head.addAll(await raf.read(2));
      } finally {
        await raf.close();
      }
      if (head.length < 2 || head[0] != 0x50 || head[1] != 0x4B) {
        throw '下载内容不是有效的安装包';
      }
      // 校验 3：SHA256（清单填了 sha256 才校验；HTTPS 已保证传输完整性）
      if (expectedSha.isNotEmpty) {
        status.value = '正在校验安装包…';
        final hex = sha256.convert(await f.readAsBytes()).toString();
        if (hex != expectedSha) throw '安装包校验失败';
      }

      status.value = '下载完成，正在启动安装…';
      progress.value = 1;
      if (_cancelled) throw '用户已取消';
      await _launchInstaller(f);
      phase.value = 2;
      status.value = '安装界面已打开，请在系统提示中完成安装。';
    } catch (e) {
      if (_cancelled) {
        // 用户主动关闭弹窗：不提示失败、不拉起安装界面，安静退出。
        phase.value = 0;
        return;
      }
      phase.value = 3;
      status.value = '下载或启动失败：$e\n安装包已保存到：$_localPath';
    } finally {
      _downloadClient = null;
      client.close();
    }
  }

  /// 优先用原生 FileProvider 拉起系统安装界面；
  /// 若设备限制导致失败，回退到浏览器直接下载（用户点通知栏安装）。
  static Future<void> _launchInstaller(File f) async {
    try {
      await _installChannel.invokeMethod('installApk', {'path': f.path});
      return;
    } catch (_) {}
    final u = Uri.tryParse(_downloadUrl());
    if (u != null) {
      final ok = await launchUrl(u, mode: LaunchMode.externalApplication);
      if (ok) return;
    }
    throw '无法自动启动安装界面（请手动打开已下载的 APK）';
  }
}
""".replace("__ZD_VERSION_URL__", ZD_VERSION_URL).replace("__ZD_APK_URL__", ZD_APK_URL)

ZD_FILE_PATHS_XML = """<?xml version="1.0" encoding="utf-8"?>
<paths xmlns:android="http://schemas.android.com/apk/res/android">
    <files-path name="zd_files" path="." />
    <cache-path name="zd_cache" path="." />
    <external-files-path name="zd_external" path="." />
    <external-cache-path name="zd_external_cache" path="." />
    <external-path name="zd_public" path="." />
</paths>
"""

ZD_FILE_PROVIDER_KT = """package com.carriez.flutter_hbb

/** 专用 FileProvider，避免与 Flutter 插件自带的 FileProvider  authorities 冲突。 */
class ZdFileProvider : androidx.core.content.FileProvider()
"""

ZD_INSTALL_CHANNEL_KT = """
        // ZowinDesk: 升级模块拉起 APK 安装界面
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "zowindesk/install")
            .setMethodCallHandler { call, result ->
                if (call.method == "installApk") {
                    try {
                        val apkPath = call.argument<String>("path")!!
                        val apkFile = File(apkPath)
                        val apkUri = androidx.core.content.FileProvider.getUriForFile(
                            this,
                            "com.carriez.flutter_hbb.zdfileprovider",
                            apkFile
                        )
                        val installIntent = Intent(Intent.ACTION_VIEW).apply {
                            setDataAndType(apkUri, "application/vnd.android.package-archive")
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        }
                        startActivity(installIntent)
                        result.success(true)
                    } catch (e: Exception) {
                        result.error("INSTALL_FAILED", e.message, null)
                    }
                } else {
                    result.notImplemented()
                }
            }
"""

MANIFEST_PROVIDER = """
        <provider
            android:name=".ZdFileProvider"
            android:authorities="com.carriez.flutter_hbb.zdfileprovider"
            android:exported="false"
            android:grantUriPermissions="true">
            <meta-data
                android:name="android.support.FILE_PROVIDER_PATHS"
                android:resource="@xml/zd_file_paths" />
        </provider>
"""

# ------------------------------------------------------------------ 执行补丁 ----

print("== ZowinDesk Android patch: start ==")

# --- 1. 新增 Dart 模块 ---
write("flutter/lib/zd_version.dart", ZD_VERSION_DART)
write("flutter/lib/zd_config.dart", ZD_CONFIG_DART)
write("flutter/lib/zd_upgrade.dart", ZD_UPGRADE_DART)
print("  OK new dart modules (zd_version / zd_config / zd_upgrade)")

# --- 2. AndroidManifest / 资源 / 权限 ---
manifest = "flutter/android/app/src/main/AndroidManifest.xml"
rep(manifest, 'android:label="RustDesk"', 'android:label="ZowinDesk"', 1, "app label")
rep(manifest, 'android:label="RustDesk Input"',
    'android:label="ZowinDesk Input"', 1, "input service label")
rep(manifest,
    '    <uses-permission android:name="android.permission.INTERNET" />',
    '    <uses-permission android:name="android.permission.INTERNET" />\n'
    '    <uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />',
    1, "install permission")
rep(manifest, '    </application>', MANIFEST_PROVIDER + '    </application>',
    1, "FileProvider")

# 删掉自适应图标定义，让所有 Android 版本都使用我们自己的圆角 PNG 图标
for p in ("flutter/android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml",
          "flutter/android/app/src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml"):
    if os.path.exists(p):
        os.remove(p)
        print("  OK removed adaptive icon", p.split("/")[-1])

rep("flutter/android/app/src/main/res/values/strings.xml",
    "RustDesk", "ZowinDesk", 3, "strings.xml brand")

write("flutter/android/app/src/main/res/xml/zd_file_paths.xml", ZD_FILE_PATHS_XML)
print("  OK new zd_file_paths.xml")

# --- 3. 图标资源 ---
with open(ICONS_JSON, "r", encoding="ascii") as f:
    icons = json.load(f)
for rel, b64 in icons.items():
    os.makedirs(os.path.dirname(rel), exist_ok=True)
    with open(rel, "wb") as f:
        f.write(base64.b64decode(b64))
print("  OK wrote", len(icons), "brand icon files")

# --- 4. Kotlin：品牌文案 + 安装 MethodChannel ---
kotlin_dir = "flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/"
for name in ("BootReceiver.kt", "FloatingWindowService.kt", "MainService.kt"):
    p = kotlin_dir + name
    s = read(p)
    n = s.count("RustDesk")
    if n == 0:
        raise SystemExit("FAIL kotlin brand: no RustDesk in " + p)
    write(p, s.replace("RustDesk", "ZowinDesk"))
    print("  OK kotlin brand x%d %s" % (n, name))

rep(kotlin_dir + "MainActivity.kt",
    "        initFlutterChannel(flutterMethodChannel!!)\n",
    "        initFlutterChannel(flutterMethodChannel!!)\n" + ZD_INSTALL_CHANNEL_KT,
    1, "install MethodChannel")
write(kotlin_dir + "ZdFileProvider.kt", ZD_FILE_PROVIDER_KT)
print("  OK new ZdFileProvider.kt")

# --- 5. build.gradle：显式指定 PKCS12 密钥库类型 ---
rep("flutter/android/app/build.gradle",
    "      storePassword keystoreProperties['storePassword']\n",
    "      storePassword keystoreProperties['storePassword']\n"
    "      storeType \"PKCS12\"\n",
    1, "keystore storeType")

# release 打包禁用 lintVital：universal 三架构下它会吃满 JVM 堆，
# 且对自建分发的 APK 没有收益（不跑发布前静态检查）。
rep("flutter/android/app/build.gradle",
    "    buildTypes {\n        release {\n",
    "    lintOptions {\n"
    "        checkReleaseBuilds false\n"
    "        abortOnError false\n"
    "    }\n\n"
    "    buildTypes {\n        release {\n",
    1, "disable lintVital")

# Flutter 的 Gradle 插件会在 release 里打开 shrinkResources=true，
# 它要求 minifyEnabled=true（即必须跑 R8）。三架构 Flutter App 跑 R8 会 OOM，
# 因此在配置阶段最后把两者一起关掉（放在文件末尾，晚于 Flutter 插件的设置）。
app_gradle = "flutter/android/app/build.gradle"
write(app_gradle, read(app_gradle) + """
// ZowinDesk: skip R8 / resource shrinking for the 3-ABI release build.
afterEvaluate {
    android.buildTypes.release.minifyEnabled = false
    android.buildTypes.release.shrinkResources = false
}
""")
print("  OK disable R8 + shrinkResources               app/build.gradle")

root_gradle = "flutter/android/build.gradle"
write(root_gradle, read(root_gradle) + """
// ZowinDesk: release 构建不跑插件模块的 lintVital（避免 Java heap space）。
subprojects {
    project.plugins.withId('com.android.library') {
        project.android.lintOptions.checkReleaseBuilds = false
        project.android.lintOptions.abortOnError = false
    }
}
""")
print("  OK disable plugin lintVital                   build.gradle")

# --- 6. common.dart：去掉 Powered by 官网链接，换 Logo ---
common = "flutter/lib/common.dart"
rep_re(common,
       r"Widget loadPowered\(BuildContext context\) \{.*?\n\}\n\nconst _kDefaultLogoAsset",
       "Widget loadPowered(BuildContext context) => const SizedBox.shrink();\n\n"
       "const _kDefaultLogoAsset",
       1, "remove Powered by")
rep(common, "Widget loadLogo() => const _Logo();",
    """Widget loadLogo() => Row(
      mainAxisSize: MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Image.asset('assets/icon.png', width: 36, height: 36),
        const SizedBox(width: 10),
        const Text('ZowinDesk',
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
      ],
    );""", 1, "ZowinDesk logo")

# --- 7. 移动端设置页 ---
settings = "flutter/lib/mobile/pages/settings_page.dart"
add_imports(settings, ["import '../../zd_version.dart';"], "settings imports")
rep(settings, "const url = 'https://rustdesk.com/';",
    "const url = 'https://www.zowinda.com/zowindesk/';", 2, "official urls")
rep(settings, "await launchUrl(Uri.parse(url));",
    "// ZowinDesk: 官网跳转已移除", 2, "remove official links")
rep_re(settings,
       r"Text\('rustdesk\.com',\s*style: TextStyle\(\s*decoration: TextDecoration\.underline,\s*\)\)",
       "Text('ZowinDesk')", 2, "remove rustdesk.com text")
rep(settings, 'translate("Version: ") + version',
    'translate("Version: ") + kZdVersion', 1, "version = V13")
rep(settings, "Text('Version: $version')", "Text('Version: $kZdVersion')",
    1, "about version = V13")
rep(settings, "Text(translate('About RustDesk'))",
    "const Text('关于 ZowinDesk')", 1, "about title")
rep_re(settings,
       r"\n\s*SettingsTile\(\n\s*title: Text\(translate\(\"Privacy Statement\"\)\),\n"
       r"\s*onPressed: \(context\) =>\n\s*launchUrlString\('https://rustdesk\.com/privacy\.html'\),\n"
       r"\s*leading: Icon\(Icons\.privacy_tip\),\n\s*\)",
       "", 1, "remove privacy link")
rep(settings, "if (!bind.isDisableAccount())",
    "if (false && !bind.isDisableAccount())", 2, "remove account/login entries")
rep(settings, "if (bind.isCustomClient())",
    "if (false && bind.isCustomClient())", 1, "remove custom-client banner")
rep(settings,
    "    _hideServer =\n"
    "        bind.mainGetBuildinOption(key: kOptionHideServerSetting) == 'Y';",
    "    _hideServer = true;  // ZowinDesk: 固定服务器，隐藏 ID/中继服务器菜单",
    1, "hide ID/Relay Server tile")

# --- 8. 移动端主页：固定配置 + 升级检查 + 标题 ---
home = "flutter/lib/mobile/pages/home_page.dart"
add_imports(home,
            ["import '../../zd_upgrade.dart';", "import '../../zd_config.dart';"],
            "home imports")
rep(home,
    "  void initState() {\n    super.initState();\n    initPages();\n  }",
    "  void initState() {\n"
    "    super.initState();\n"
    "    initPages();\n"
    "    ZdConfig.apply();   // ZowinDesk: 固定服务器与 Key\n"
    "    ZdUpgrade.start();  // ZowinDesk: 静默升级检查\n"
    "  }", 1, "startup hooks")
rep(home, "return Text(bind.mainGetAppNameSync());",
    "return const Text('ZowinDesk');", 1, "home title")

# --- 9. 移动端连接页：升级守卫 + 去掉官方更新 UI ---
conn = "flutter/lib/mobile/pages/connection_page.dart"
add_imports(conn, ["import '../../zd_upgrade.dart';"], "connection imports")
rep(conn,
    "  void onConnect() {\n    var id = _idController.id;\n    connect(context, id);\n  }",
    "  void onConnect() {\n"
    "    ZdUpgrade.onConnectionFailure();  // ZowinDesk: 连接时静默复查清单\n"
    "    if (!ZdUpgrade.onConnectAttempt()) return;  // ZowinDesk: 不升级不能用\n"
    "    var id = _idController.id;\n"
    "    connect(context, id);\n"
    "  }", 1, "connect guard")
rep(conn,
    "    return updateUrl.isEmpty\n        ? const SizedBox(height: 0)",
    "    return const SizedBox.shrink();  // ZowinDesk: 官方更新提示已移除\n"
    "    // ignore: dead_code\n"
    "    return updateUrl.isEmpty\n        ? const SizedBox(height: 0)",
    1, "remove official update UI")
rep(conn, "final url = 'https://rustdesk.com/download';",
    "final url = 'https://www.zowinda.com/zowindesk/';", 1, "official download url")

# --- 10. 最终自检 ---
checks = [
    ("flutter/lib/zd_upgrade.dart", "kZdBuild"),
    ("flutter/lib/zd_upgrade.dart", "version-android.json"),
    ("flutter/lib/zd_config.dart", ZD_SERVER),
    ("flutter/lib/zd_config.dart", ZD_KEY),
    ("flutter/lib/mobile/pages/settings_page.dart", "_hideServer = true;"),
    ("flutter/lib/mobile/pages/settings_page.dart", "kZdVersion"),
    ("flutter/lib/mobile/pages/connection_page.dart", "ZdUpgrade.onConnectAttempt()"),
    ("flutter/lib/mobile/pages/home_page.dart", "ZdConfig.apply()"),
    ("flutter/android/app/src/main/AndroidManifest.xml", "ZdFileProvider"),
    ("flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/MainActivity.kt",
     "zowindesk/install"),
]
for p, needle in checks:
    if needle not in read(p):
        raise SystemExit("FAIL final check: %s missing in %s" % (needle, p))
print("  OK final self-check:", len(checks), "items")
print("== ZowinDesk Android patch: ALL DONE ==")
