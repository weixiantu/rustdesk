// ZowinDesk: inline module (minimized implementation)
// This module handles inline drawing/annotation features
// Also provides inline HTML content for the `inline` feature

use hbb_common::{allow_err, log};
use serde_json::Value;

#[cfg(target_os = "windows")]
pub fn start_inline_service() {
    log::info!("[ZowinDesk] Inline service started (Windows)");
}

#[cfg(not(target_os = "windows"))]
pub fn start_inline_service() {
    log::info!("[ZowinDesk] Inline service started (non-Windows)");
}

pub fn handle_inline_message(msg: &str) -> Option<Value> {
    log::debug!("[ZowinDesk] Inline message: {}", msg);
    None
}

pub fn is_inline_enabled() -> bool {
    true
}

// Inline HTML content for `inline` feature
// These functions return HTML content as strings
// Uses include_str! to embed HTML files at compile time
// Paths are relative to this source file (src/ui/inline.rs)

pub fn get_index() -> String {
    log::info!("[ZowinDesk] Loading index.html (inline)");
    include_str!("index.html").to_string()
}

pub fn get_cm() -> String {
    log::info!("[ZowinDesk] Loading cm.html (inline)");
    include_str!("cm.html").to_string()
}

pub fn get_install() -> String {
    log::info!("[ZowinDesk] Loading install.html (inline)");
    if let Ok(content) = std::fs::read_to_string("src/ui/install.html") {
        content
    } else {
        "".to_string()
    }
}

pub fn get_remote() -> String {
    log::info!("[ZowinDesk] Loading remote.html (inline)");
    include_str!("remote.html").to_string()
}

pub fn get_chatbox() -> String {
    log::info!("[ZowinDesk] Loading chatbox.html (inline)");
    if let Ok(content) = std::fs::read_to_string("src/ui/chatbox.html") {
        content
    } else {
        "<html><body><h1>Chat</h1></body></html>".to_string()
    }
}
