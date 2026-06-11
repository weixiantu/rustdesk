// ZowinDesk: inline module (minimized implementation)
// This module handles inline drawing/annotation features

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
