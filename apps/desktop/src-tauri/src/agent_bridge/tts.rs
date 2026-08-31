use serde::{Deserialize, Serialize};
use tauri::State;

use crate::agent_bridge::commands::read_voice_settings;
use crate::AppState;

const GLOBAL_ENDPOINT: &str = "https://api.minimax.io/v1/t2a_v2";
const CHINA_ENDPOINT: &str = "https://api.minimaxi.com/v1/t2a_v2";
const DEFAULT_MODEL: &str = "speech-2.8-hd";
const MODELS: [&str; 8] = [
    "speech-2.8-hd",
    "speech-2.8-turbo",
    "speech-2.6-hd",
    "speech-2.6-turbo",
    "speech-02-hd",
    "speech-02-turbo",
    "speech-01-hd",
    "speech-01-turbo",
];
const AUDIO_FORMATS: [&str; 4] = ["mp3", "wav", "flac", "pcm"];

#[derive(Debug, Serialize)]
pub struct TtsOptions {
    pub regions: [&'static str; 2],
    pub models: [&'static str; 8],
    pub audio_formats: [&'static str; 4],
    pub default_model: &'static str,
}

#[derive(Debug, Serialize)]
pub struct TtsAudio {
    pub data_url: String,
    pub format: String,
    pub status: i64,
}

#[derive(Serialize)]
struct TtsRequest<'a> {
    model: &'a str,
    text: &'a str,
    stream: bool,
    output_format: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    voice_setting: Option<TtsVoiceSetting<'a>>,
    audio_setting: TtsAudioSetting<'a>,
}

#[derive(Serialize)]
struct TtsVoiceSetting<'a> {
    voice_id: &'a str,
}

#[derive(Serialize)]
struct TtsAudioSetting<'a> {
    format: &'a str,
}

#[derive(Deserialize)]
struct TtsResponse {
    data: Option<TtsResponseData>,
    base_resp: TtsBaseResponse,
}

#[derive(Deserialize)]
struct TtsResponseData {
    audio: String,
    status: i64,
}

#[derive(Deserialize)]
struct TtsBaseResponse {
    status_code: i64,
    #[serde(default)]
    status_msg: String,
}

#[tauri::command]
pub fn agent_get_tts_options() -> TtsOptions {
    TtsOptions {
        regions: ["global_en", "cn_zh"],
        models: MODELS,
        audio_formats: AUDIO_FORMATS,
        default_model: DEFAULT_MODEL,
    }
}

#[tauri::command]
pub async fn agent_synthesize_speech(
    text: String,
    app_state: State<'_, AppState>,
) -> Result<TtsAudio, String> {
    let settings = read_voice_settings(&app_state);
    let api_key = settings.tts_api_key.trim();
    if api_key.is_empty() {
        return Err("Text-to-speech API key is not configured".to_string());
    }
    let endpoint = match settings.tts_region.as_str() {
        "" | "global_en" => GLOBAL_ENDPOINT,
        "cn_zh" => CHINA_ENDPOINT,
        _ => return Err("Unsupported text-to-speech region".to_string()),
    };
    let model = if settings.tts_model.is_empty() {
        DEFAULT_MODEL
    } else if MODELS.contains(&settings.tts_model.as_str()) {
        settings.tts_model.as_str()
    } else {
        return Err("Unsupported text-to-speech model".to_string());
    };
    let audio_format = if settings.tts_audio_format.is_empty() {
        "mp3"
    } else if AUDIO_FORMATS.contains(&settings.tts_audio_format.as_str()) {
        settings.tts_audio_format.as_str()
    } else {
        return Err("Unsupported text-to-speech audio format".to_string());
    };
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()
        .map_err(|error| error.to_string())?;
    synthesize_speech_request(
        &client,
        endpoint,
        api_key,
        model,
        settings.tts_voice_id.trim(),
        audio_format,
        text.trim(),
    )
    .await
}

async fn synthesize_speech_request(
    client: &reqwest::Client,
    endpoint: &str,
    api_key: &str,
    model: &str,
    voice_id: &str,
    audio_format: &str,
    text: &str,
) -> Result<TtsAudio, String> {
    if text.is_empty() {
        return Err("Text-to-speech input is empty".to_string());
    }
    let request = TtsRequest {
        model,
        text,
        stream: false,
        output_format: "hex",
        voice_setting: (!voice_id.is_empty()).then_some(TtsVoiceSetting { voice_id }),
        audio_setting: TtsAudioSetting {
            format: audio_format,
        },
    };
    let response = client
        .post(endpoint)
        .bearer_auth(api_key)
        .json(&request)
        .send()
        .await
        .map_err(|error| format!("Text-to-speech request failed: {error}"))?;
    let status = response.status();
    if !status.is_success() {
        return Err(format!("Text-to-speech request returned HTTP {status}"));
    }
    let response: TtsResponse = response
        .json()
        .await
        .map_err(|error| format!("Invalid text-to-speech response: {error}"))?;
    if response.base_resp.status_code != 0 {
        return Err(format!(
            "Text-to-speech request failed with status {}: {}",
            response.base_resp.status_code, response.base_resp.status_msg
        ));
    }
    let data = response
        .data
        .ok_or_else(|| "Text-to-speech response did not include audio".to_string())?;
    if data.status != 2 {
        return Err(format!(
            "Text-to-speech response is incomplete (status {})",
            data.status
        ));
    }
    let bytes = decode_hex(&data.audio)?;
    use base64::Engine;
    let encoded = base64::engine::general_purpose::STANDARD.encode(bytes);
    let mime = match audio_format {
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "flac" => "audio/flac",
        "pcm" => "audio/L16",
        _ => return Err("Unsupported text-to-speech audio format".to_string()),
    };
    Ok(TtsAudio {
        data_url: format!("data:{mime};base64,{encoded}"),
        format: audio_format.to_string(),
        status: data.status,
    })
}

fn decode_hex(value: &str) -> Result<Vec<u8>, String> {
    if value.len() % 2 != 0 {
        return Err("Text-to-speech response contained invalid hexadecimal audio".to_string());
    }
    (0..value.len())
        .step_by(2)
        .map(|index| {
            u8::from_str_radix(&value[index..index + 2], 16).map_err(|_| {
                "Text-to-speech response contained invalid hexadecimal audio".to_string()
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{body_json, header, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn synthesizes_hex_audio_with_configured_schema() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/v1/t2a_v2"))
            .and(header("authorization", "Bearer test-key"))
            .and(body_json(serde_json::json!({
                "model": "speech-2.8-hd",
                "text": "Hello",
                "stream": false,
                "output_format": "hex",
                "voice_setting": {"voice_id": "narrator"},
                "audio_setting": {"format": "mp3"}
            })))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "data": {"audio": "010203", "status": 2},
                "base_resp": {"status_code": 0, "status_msg": "success"}
            })))
            .mount(&server)
            .await;

        let result = synthesize_speech_request(
            &reqwest::Client::new(),
            &format!("{}/v1/t2a_v2", server.uri()),
            "test-key",
            "speech-2.8-hd",
            "narrator",
            "mp3",
            "Hello",
        )
        .await
        .expect("speech synthesis should succeed");

        assert_eq!(result.data_url, "data:audio/mpeg;base64,AQID");
        assert_eq!(result.status, 2);
    }

    #[test]
    fn rejects_invalid_hex_audio() {
        assert!(decode_hex("abc").is_err());
        assert!(decode_hex("zz").is_err());
    }
}
