#![cfg_attr(
  all(not(debug_assertions), target_os = "windows"),
  windows_subsystem = "windows"
)]

use tauri::Manager;

fn main() {
  tauri::Builder::default()
    .setup(|app| {
      let window = app.get_window("main").unwrap();

      // ── macOS: Apply native vibrancy (frosted glass) ──
      #[cfg(target_os = "macos")]
      {
        use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};

        // HudWindow = dark translucent material, perfect for dark-mode apps
        apply_vibrancy(
          &window,
          NSVisualEffectMaterial::HudWindow,
          None,
          None,
        )
        .expect("Failed to apply macOS vibrancy");
      }

      // ── Windows: Apply acrylic/mica if available ──
      #[cfg(target_os = "windows")]
      {
        use window_vibrancy::apply_acrylic;
        let _ = apply_acrylic(&window, Some((18, 18, 18, 200)));
      }

      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
