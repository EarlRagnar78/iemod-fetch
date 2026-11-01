// The interop check of iemod_fetch/bio.py against BIO itself (docs/TESTING.md).
//
// Not part of this project's build. Append it to BIO's
// src/core/app/modlist_share.rs (Born2BSaltys_Infinity_Orchestrator, read at
// 33800cc), then, from BIO's checkout:
//
//   IEMOD_CODE_IN=ours.bio cargo test --lib iemod_interop -- --nocapture
//       BIO decodes and previews a code iemod-fetch wrote
//   IEMOD_PAYLOAD_IN=payload.json IEMOD_CODE_OUT=bio.bio cargo test --lib iemod_interop
//       BIO encodes a payload, for tests/data/bio
//
// It calls only BIO's own functions; nothing of BIO is copied here.

#[cfg(test)]
mod iemod_interop {
    use super::*;

    #[test]
    fn iemod_interop() {
        if let Ok(path) = std::env::var("IEMOD_CODE_IN") {
            let code = std::fs::read_to_string(path).unwrap();
            let payload = decode_share_payload(&code).expect("BIO decodes the iemod-fetch code");
            let preview = share_preview(&payload).expect("BIO previews it");
            println!("IEMOD-INTEROP decoded game_install={} install_mode={} first={} second={} name={:?}",
                     preview.game_install, preview.install_mode, preview.bgee_entries,
                     preview.bg2ee_entries, preview.name);
        }
        if let Ok(path) = std::env::var("IEMOD_PAYLOAD_IN") {
            let text = std::fs::read_to_string(path).unwrap();
            let code = encode_share_payload_text(&text).unwrap();
            std::fs::write(std::env::var("IEMOD_CODE_OUT").unwrap(), code).unwrap();
            println!("IEMOD-INTEROP encoded");
        }
    }
}
