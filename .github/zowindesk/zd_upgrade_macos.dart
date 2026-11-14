// ============================================================================
// ZowinDesk macOS 升级提示模块（由 Windows 版适配，逻辑保持一致）
//
// 设计原则（重要）：绝不打扰用户正在做的其它工作。
//   1) 前期（version-macos.json min_build <= kZdBuild）完全静默，装完即用、零弹窗；
//   2) 后台换 Key 后把 min_build 调高，提示升级。但弹窗【始终可关闭】：
//      「稍后」/ 右上角 X / 点击遮罩 / Esc / 返回键都能关，下载中也能关；
//   3) 关闭后本次启动不再自动弹出；用户下次点「连接」时再次提醒；
//   4) 不升级就建立不了连接：一方面 Key 已失效，另一方面点「连接」时
//      onConnectAttempt() 会拦下本次连接并弹出提示。不会因为弹窗被关掉
//      就"能用"，也不会因为服务持续报错而在后台反复弹窗骚扰用户；
//   5) 检查走独立 HTTPS，不依赖 hbbs 通道（换 Key 后该通道本身已断）。
//
// 触发时机：启动后 3 秒 / 每 10 分钟（只更新状态，点过稍后不再弹）
//           / 连接状态异常（只静默复查，5 分钟节流）/ 用户点「连接」。
// ============================================================================

import 'dart:async';
import 'dart:convert';
import 'dart:io';

// crypto 已在 pubspec.lock 中（传递依赖），故不改动 pubspec.yaml。
// ignore: depend_on_referenced_packages
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';

import 'zd_version.dart';

/// 版本清单地址，固定不变，所有版本共用。
const String kZdVersionUrl = 'https://www.zowinda.com/zowindesk/version-macos.json';

/// 默认新包下载地址（固定文件名）。version-macos.json 里的 download_url 可覆盖。
const String kZdDefaultDownloadUrl =
    'https://www.zowinda.com/zowindesk/ZowinDesk-macOS-arm64.dmg';

class ZdUpgrade {
  ZdUpgrade._();

  static Timer? _startupTimer;
  static Timer? _periodicTimer;
  static DateTime? _lastFailureCheck;
  static int _holders = 0;
  static bool _dialogShown = false;
  static bool _upgradeRequired = false;
  static bool _snoozed = false;
  static bool _cancelled = false;
  static http.Client? _downloadClient;
  static Map<String, dynamic>? _info;
  static String _localPath = '';

  /// 0 = 等待操作，1 = 下载中，2 = 已完成（已拉起安装），3 = 失败
  static final ValueNotifier<int> phase = ValueNotifier<int>(0);
  static final ValueNotifier<double> progress = ValueNotifier<double>(0);
  static final ValueNotifier<String> status = ValueNotifier<String>('');

  /// 在主界面 initState 调用。用引用计数避免多窗口互相取消检查。
  static void start() {
    _holders++;
    if (_holders != 1) return;
    _startupTimer = Timer(const Duration(seconds: 3), () {
      _checkSilently();
    });
    _periodicTimer = Timer.periodic(const Duration(minutes: 10), (_) {
      _checkSilently();
    });
  }

  /// 在主界面 dispose 调用。
  static void stop() {
    if (_holders == 0) return;
    _holders--;
    if (_holders != 0) return;
    _startupTimer?.cancel();
    _periodicTimer?.cancel();
    _startupTimer = null;
    _periodicTimer = null;
  }

  /// 连接状态异常时【只做静默复查，绝不弹窗】。
  /// 换 Key 后 mainGetError 可能持续非空，若在这里弹窗会变成反复骚扰。
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
  /// 返回 true  = 正常连接。
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
      _info = Map<String, dynamic>.from(decoded as Map);
      // 启动后自动提示一次即可；用户点过「稍后」后不再自动弹，只等点连接。
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

  /// 可关闭的升级弹窗。
  /// 没有 PopScope(canPop:false)，barrierDismissible 为 true，
  /// 并提供「稍后」与右上角 X；任何关闭方式都会中止进行中的下载。
  static void _showDialog() {
    if (_dialogShown) return;
    final ctx = Get.context;
    if (ctx == null) return; // 界面还没就绪，下一轮定时检查会重试
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
          content: SizedBox(
            width: 420,
            child: Column(
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
                    s.isEmpty ? '点击下方按钮自动下载新版本（DMG）。' : s,
                    style: const TextStyle(fontSize: 12, color: Colors.grey),
                  ),
                ),
              ],
            ),
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
                  p == 1 ? '下载中…' : (p == 2 ? '已打开安装包' : '立即升级')),
            ),
          ],
        ),
      ),
      barrierDismissible: true,
      useSafeArea: true,
    ).then((_) {
      // 无论是点「稍后」/ X / 遮罩 / Esc / 返回键，统一在这里收尾。
      _dialogShown = false;
      _snoozed = true;
      _cancelled = true;
      try {
        _downloadClient?.close();
      } catch (_) {}
    });
  }

  /// 下载 -> 校验 -> 打开 DMG。
  /// macOS 没有静默安装：`open` 会挂载 DMG 并弹出访达拖装窗口。
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

      final f = File('${Directory.systemTemp.path}${Platform.pathSeparator}'
          'ZowinDesk-macOS-arm64.dmg');
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
      // 校验 2：DMG/ZIP 头必须是 PK，防止把 404 HTML 当成安装包打开
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

      status.value = '下载完成，正在打开安装包…';
      progress.value = 1;
      if (_cancelled) throw '用户已取消';
      await _launchInstaller(f);
      phase.value = 2;
      status.value = '安装包已打开，请将 ZowinDesk 拖入「应用程序」文件夹完成升级。';
    } catch (e) {
      if (_cancelled) {
        // 用户主动关闭弹窗：不提示失败、不拉起安装界面，安静退出。
        phase.value = 0;
        return;
      }
      phase.value = 3;
      status.value = '下载或打开失败：$e\n安装包已保存到：$_localPath';
    } finally {
      _downloadClient = null;
      client.close();
    }
  }

  static Future<void> _launchInstaller(File f) async {
    final r = await Process.run('open', [f.path]);
    if (r.exitCode != 0) {
      final ok = await launchUrl(Uri.file(f.path),
          mode: LaunchMode.externalApplication);
      if (!ok) throw '无法自动打开安装包（请手动双击已下载的 DMG 文件）';
    }
  }
}
