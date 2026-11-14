#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZowinDesk macOS 构建补丁（CI 内执行，仓库源码保持官方 1.5.1 状态）。

与 Windows 工作流的补丁步骤一一对应：
  1. libs/hbb_common/src/config.rs  固定服务器 IP/Key、APP_NAME、BUILTIN_SETTINGS
     （只隐藏「ID/中继服务器」一行，网络 tab 其余项保留）
  2. src/common.rs                  get_builtin_option 强制 hide-server-settings
  3. flutter/lib/zd_version.dart    本机版本号 V14（与本脚本同目录的真实文件）
  4. flutter/lib/zd_upgrade.dart    升级模块 macOS 版（version-macos.json + DMG）
  5. desktop_home_page.dart         ZdUpgrade.start()/stop()/onConnectionFailure()
  6. connection_page.dart           onConnectAttempt() 连接前拦截
  7. desktop_setting_page.dart      关于页显示 V14，去掉 About RustDesk
  8. macOS 工程                     PRODUCT_NAME=ZowinDesk、xib 菜单品牌、AppIcon.icns

用法: python3 zd_macos_patch.py <脚本所在目录>   （在仓库根执行）
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

ZD_SERVER = "43.139.157.84"
ZD_KEY = "PMEoK7kHVXLlHB4td8wk13ezTwKABynXQucZURTZtuo="


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)
    print("  ok:", msg)


def patch_config():
    p = "libs/hbb_common/src/config.rs"
    s = read(p)
    s, n1 = re.subn(r"pub const RENDEZVOUS_SERVERS[^;]*;",
                    'pub const RENDEZVOUS_SERVERS: &[&str] = &["%s"];' % ZD_SERVER,
                    s, count=1)
    s, n2 = re.subn(r"pub const RS_PUB_KEY[^;]*;",
                    'pub const RS_PUB_KEY: &str = "%s";' % ZD_KEY,
                    s, count=1)
    check(n1 == 1, "RENDEZVOUS_SERVERS patched")
    check(n2 == 1, "RS_PUB_KEY patched")
    s = s.replace('RwLock::new("RustDesk".to_owned())',
                  'RwLock::new("ZowinDesk".to_owned())')
    bs_old = ("pub static ref BUILTIN_SETTINGS: RwLock<HashMap<String, String>> = "
              "Default::default();")
    bs_new = "\n".join([
        "pub static ref BUILTIN_SETTINGS: RwLock<HashMap<String, String>> = {",
        "        let mut m = HashMap::new();",
        '        m.insert("hide-server-settings".to_owned(), "Y".to_owned());',
        "        RwLock::new(m)",
        "    };",
    ])
    check(bs_old in s, "BUILTIN_SETTINGS anchor found")
    s = s.replace(bs_old, bs_new, 1)
    check('RwLock::new("ZowinDesk"' in s and ZD_SERVER in s and "PMEoK7" in s,
          "config.rs server/brand applied")
    check("hide-network-settings" not in s, "network tab stays visible")
    write(p, s)


def patch_common():
    p = "src/common.rs"
    t = read(p)
    gb_old = "\n".join([
        "pub fn get_builtin_option(key: &str) -> String {",
        "    config::BUILTIN_SETTINGS",
    ])
    gb_new = "\n".join([
        "pub fn get_builtin_option(key: &str) -> String {",
        '    if key == "hide-server-settings" {',
        '        return "Y".to_owned();',
        "    }",
        "    config::BUILTIN_SETTINGS",
    ])
    check(gb_old in t, "get_builtin_option anchor found")
    t = t.replace(gb_old, gb_new, 1)
    write(p, t)


def write_zd_files():
    for src_name, dst in [("zd_version_macos.dart", "flutter/lib/zd_version.dart"),
                          ("zd_upgrade_macos.dart", "flutter/lib/zd_upgrade.dart")]:
        shutil.copyfile(os.path.join(HERE, src_name), dst)
    v = read("flutter/lib/zd_version.dart")
    u = read("flutter/lib/zd_upgrade.dart")
    check("kZdBuild = 14" in v, "zd_version kZdBuild = 14")
    check("kZdVersion = 'V14'" in v, "zd_version V14")
    check("import 'zd_version.dart';" in u, "zd_upgrade imports zd_version")
    check("version-macos.json" in u, "manifest URL is version-macos.json")
    check("ZowinDesk-macOS-arm64.dmg" in u, "DMG download URL fixed")
    check("version.json'" not in u and
          "version-android.json" not in u, "no windows/android manifest leaked")
    check("ZowinDesk \u9700\u8981\u5347\u7ea7" in u, "dialog title present")
    check("barrierDismissible: true" in u, "dialog dismissable")
    check("canPop: false" not in u, "no PopScope blocking")
    check("onConnectAttempt" in u, "connect hook present")
    check("Text(p == 1 ? '\u53d6\u6d88\u5e76\u7a0d\u540e' : '\u7a0d\u540e')" in u,
          "later button present")


def patch_desktop_home():
    p = "flutter/lib/desktop/pages/desktop_home_page.dart"
    t = read(p)
    imp_old = "import 'package:flutter_hbb/common.dart';"
    check(imp_old in t, "home page import anchor")
    t = t.replace(imp_old, imp_old + "\nimport 'package:flutter_hbb/zd_upgrade.dart';", 1)
    err_old = "      final error = await bind.mainGetError();\n"
    check(t.count(err_old) == 1, "mainGetError call site unique")
    t = t.replace(err_old, err_old + "\n".join([
        "      if (error.isNotEmpty) {",
        "        ZdUpgrade.onConnectionFailure();  "
        "// ZowinDesk: recheck manifest when the link breaks",
        "      }",
        "",
    ]), 1)
    obs_old = "    WidgetsBinding.instance.addObserver(this);\n"
    check(t.count(obs_old) == 1, "initState anchor unique")
    t = t.replace(obs_old, obs_old + "    ZdUpgrade.start();  "
                  "// ZowinDesk: silent force-upgrade watcher\n", 1)
    dis_old = "    _updateTimer?.cancel();\n"
    check(t.count(dis_old) == 1, "dispose anchor unique")
    t = t.replace(dis_old, dis_old + "    ZdUpgrade.stop();\n", 1)
    check(t.count("ZdUpgrade.") >= 3, "ZdUpgrade hooks applied")
    write(p, t)


def patch_connection_page():
    p = "flutter/lib/desktop/pages/connection_page.dart"
    t = read(p)
    imp_old = "import 'package:flutter_hbb/consts.dart';"
    check(imp_old in t, "connection page import anchor")
    t = t.replace(imp_old, imp_old + "\nimport 'package:flutter_hbb/zd_upgrade.dart';", 1)
    oc_old = "    var id = _idController.id;\n    connect(context, id,"
    oc_new = ("    if (!ZdUpgrade.onConnectAttempt()) return;  "
              "// ZowinDesk: re-prompt before connecting\n"
              "    var id = _idController.id;\n    connect(context, id,")
    check(t.count(oc_old) == 1, "onConnect anchor unique")
    t = t.replace(oc_old, oc_new, 1)
    write(p, t)


def patch_setting_page():
    p = "flutter/lib/desktop/pages/desktop_setting_page.dart"
    t = read(p)
    imp_old = "import 'package:flutter_hbb/consts.dart';"
    check(imp_old in t, "setting page import anchor")
    t = t.replace(imp_old, imp_old + "\nimport 'package:flutter_hbb/zd_version.dart';", 1)
    ver_old = "      final version = await bind.mainGetVersion();"
    check(t.count(ver_old) == 1, "mainGetVersion call site unique")
    t = t.replace(ver_old, "      final version = kZdVersion;  "
                  "// ZowinDesk: own release number", 1)
    ab_old = "_Card(title: translate('About RustDesk'), children: ["
    check(t.count(ab_old) == 1, "About card anchor unique")
    t = t.replace(ab_old, "_Card(title: '\u5173\u4e8e ZowinDesk', children: [", 1)
    check("About RustDesk" not in t, "About rebranded")
    write(p, t)


def patch_macos_project():
    # 8a. PRODUCT_NAME：产物直接叫 ZowinDesk.app（target/module 名保持 RustDesk 不动，
    #     避免破坏 Swift 模块名与生成的引用）。
    p = "flutter/macos/Runner.xcodeproj/project.pbxproj"
    t = read(p)
    pn_old = 'PRODUCT_NAME = "$(TARGET_NAME)";'
    n = t.count(pn_old)
    check(n == 3, "PRODUCT_NAME anchors found (%d)" % n)
    t = t.replace(pn_old, "PRODUCT_NAME = ZowinDesk;")
    check("PRODUCT_NAME = ZowinDesk;" in t, "PRODUCT_NAME -> ZowinDesk")
    check("PRODUCT_BUNDLE_IDENTIFIER = com.carriez.rustdesk" in t,
          "bundle id intentionally unchanged (service/permission compatibility)")
    write(p, t)

    # 8b. MainMenu.xib：菜单里的 APP_NAME 占位符（关于/隐藏/退出/主菜单/窗口标题）。
    p = "flutter/macos/Runner/Base.lproj/MainMenu.xib"
    t = read(p)
    n = t.count("APP_NAME")
    check(n >= 6, "xib APP_NAME placeholders found (%d)" % n)
    t = t.replace("APP_NAME", "ZowinDesk")
    check("APP_NAME" not in t, "xib fully rebranded")
    write(p, t)

    # 8c. 应用图标。
    src_icns = os.path.join(HERE, "AppIcon.icns")
    dst_icns = "flutter/macos/Runner/AppIcon.icns"
    check(os.path.isfile(src_icns) and os.path.getsize(src_icns) > 100000,
          "brand AppIcon.icns shipped with repo")
    shutil.copyfile(src_icns, dst_icns)

    # 8d. Info.plist：确认 CFBundleName 走 PRODUCT_NAME、图标走 AppIcon.icns。
    p = "flutter/macos/Runner/Info.plist"
    t = read(p)
    check("<string>$(PRODUCT_NAME)</string>" in t, "CFBundleName from PRODUCT_NAME")
    check("<string>AppIcon.icns</string>" in t, "icon file key present")


def main():
    check(len(sys.argv) >= 2, "usage: zd_macos_patch.py <here>")
    print("== ZowinDesk macOS patch ==")
    patch_config()
    patch_common()
    write_zd_files()
    patch_desktop_home()
    patch_connection_page()
    patch_setting_page()
    patch_macos_project()
    print("== ALL ZOWINDESK MACOS PATCHES APPLIED ==")


if __name__ == "__main__":
    main()
