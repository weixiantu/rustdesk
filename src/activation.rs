// ZowinDesk: 激活检查模块
// 首次启动要求输入 Key 激活，调用后端 API 验证

use std::fs::{self, File};
use std::io::{self, Write};
use std::path::Path;

const ACTIVATION_FILE: &str = "activation.key";
const API_VERIFY: &str = "http://43.139.157.84/api/v1/key/verify";

/// 检查激活状态
/// 返回 true = 已激活，false = 未激活（调用方应退出程序）
pub fn check_activation() -> bool {
    // 1. 检查环境变量（便于批量部署）
    if let Ok(key) = std::env::var("ZOWINDESK_KEY") {
        let key = key.trim();
        if !key.is_empty() {
            println!("[ZowinDesk] 使用环境变量中的 Key 进行验证...");
            return verify_key(key);
        }
    }

    // 2. 检查本地激活文件
    let path = Path::new(ACTIVATION_FILE);
    if path.exists() {
        if let Ok(key) = fs::read_to_string(path) {
            let key = key.trim();
            if !key.is_empty() {
                println!("[ZowinDesk] 验证本地 Key...");
                return verify_key(key);
            }
        }
    }

    // 3. 未激活，提示用户
    eprintln!("========================================");
    eprintln!("  ZowinDesk 尚未激活");
    eprintln!("  请通过以下方式之一激活：");
    eprintln!("  1. 设置环境变量 ZOWINDESK_KEY=你的Key");
    eprintln!("  2. 创建 {} 文件，内容为你的 Key", ACTIVATION_FILE);
    eprintln!("  3. 运行：{} --activate <Key>", std::env::args().next().unwrap_or_else(|| "zowindesk".to_string()));
    eprintln!("========================================");
    false
}

/// 命令行激活（由 --activate 参数触发）
pub fn activate_with_key(key: &str) -> bool {
    println!("[ZowinDesk] 正在验证 Key...");
    let result = verify_key(key.trim());
    if result {
        println!("[ZowinDesk] ✅ 激活成功！");
    } else {
        eprintln!("[ZowinDesk] ❌ 激活失败，请检查 Key 是否正确。");
    }
    result
}

/// 调用后端 API 验证 Key
fn verify_key(key: &str) -> bool {
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build();

    let client = match client {
        Ok(c) => c,
        Err(e) => {
            eprintln!("[ZowinDesk] 创建 HTTP 客户端失败: {}", e);
            return false;
        }
    };

    let response = client
        .post(API_VERIFY)
        .json(&serde_json::json!({ "key": key }))
        .send();

    match response {
        Ok(r) => {
            let status = r.status();
            let text = r.text().unwrap_or_default();
            if status.is_success() {
                match serde_json::from_str::<serde_json::Value>(&text) {
                    Ok(json) => {
                        let valid = json.get("valid")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(false);
                        if valid {
                            println!("[ZowinDesk] ✅ Key 验证成功！");
                            // 保存 Key 到本地文件
                            let _ = save_key(key);
                            return true;
                        } else {
                            let msg = json.get("message")
                                .and_then(|v| v.as_str())
                                .unwrap_or("Key 无效");
                            eprintln!("[ZowinDesk] ❌ 验证失败: {}", msg);
                        }
                    }
                    Err(e) => {
                        eprintln!("[ZowinDesk] 解析响应失败: {} | body: {}", e, text);
                    }
                }
            } else {
                eprintln!("[ZowinDesk] ❌ 服务器返回错误 {}: {}", status, text);
            }
        }
        Err(e) => {
            eprintln!("[ZowinDesk] ❌ 网络请求失败: {}", e);
            eprintln!("[ZowinDesk] 提示：请检查网络连接，或设置 ZOWINDESK_KEY 跳过在线验证。");
        }
    }
    false
}

/// 保存 Key 到本地文件
fn save_key(key: &str) -> io::Result<()> {
    let mut file = File::create(ACTIVATION_FILE)?;
    file.write_all(key.as_bytes())?;
    file.sync_all()?;
    println!("[ZowinDesk] Key 已保存到 {}", ACTIVATION_FILE);
    Ok(())
}
