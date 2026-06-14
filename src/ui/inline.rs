// ZowinDesk: inline module - returns complete self-contained HTML
// All CSS and TIS files are inlined at compile time via include_str!

#[cfg(target_os = "windows")]
pub fn start_inline_service() {}

#[cfg(not(target_os = "windows"))]
pub fn start_inline_service() {}

pub fn handle_inline_message(_msg: &str) -> Option<serde_json::Value> { None }
pub fn is_inline_enabled() -> bool { true }

/// Build a complete self-contained HTML page with inlined CSS and TIS
macro_rules! inline_html {
    ($html:expr, $css_files:expr, $tis_files:expr) => {
        {
            let css_content: &[&str] = $css_files;
            let tis_content: &[&str] = $tis_files;
            let mut result = String::from("<html><head><style>");
            // Inline all CSS
            for css in css_content {
                result.push_str(css);
                result.push_str("\n");
            }
            result.push_str("</style>\n<script type=\"text/tiscript\">\n");
            // Inline all TIS
            for tis in tis_content {
                result.push_str(tis);
                result.push_str("\n");
            }
            result.push_str("\n</script></head><body>");
            // Extract body from original HTML (skip head)
            if let Some(body_start) = $html.find("<body>") {
                if let Some(body_end) = $html.find("</body>") {
                    result.push_str(&$html[body_start..body_end + 7]);
                } else {
                    result.push_str(&$html[body_start..]);
                }
            }
            result.push_str("\n</html>");
            result
        }
    };
}

pub fn get_index() -> String {
    inline_html!(
        include_str!("index.html"),
        &[
            include_str!("common.css"),
            include_str!("index.css"),
            include_str!("header.css"),
            include_str!("file_transfer.css"),
        ],
        &[
            include_str!("common.tis"),
            include_str!("msgbox.tis"),
            include_str!("ab.tis"),
            include_str!("index.tis"),
        ]
    )
}

pub fn get_cm() -> String {
    inline_html!(
        include_str!("cm.html"),
        &[
            include_str!("common.css"),
            include_str!("cm.css"),
        ],
        &[
            include_str!("common.tis"),
            include_str!("cm.tis"),
        ]
    )
}

pub fn get_install() -> String {
    inline_html!(
        include_str!("install.html"),
        &[include_str!("common.css")],
        &[include_str!("install.tis")]
    )
}

pub fn get_remote() -> String {
    inline_html!(
        include_str!("remote.html"),
        &[
            include_str!("common.css"),
            include_str!("remote.css"),
            include_str!("file_transfer.css"),
        ],
        &[
            include_str!("common.tis"),
            include_str!("grid.tis"),
            include_str!("remote.tis"),
            include_str!("file_transfer.tis"),
            include_str!("port_forward.tis"),
            include_str!("printer.tis"),
        ]
    )
}

pub fn get_chatbox() -> String {
    "<html><head><style>".to_string()
        + include_str!("common.css")
        + "</style><script type=\"text/tiscript\">"
        + include_str!("common.tis")
        + "\n</script></head><body>Chat</body></html>"
}
