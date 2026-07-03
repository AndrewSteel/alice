// =============================================================================
// Alice — wyoming_satellite ESPHome external component (PROJ-42, BUG-1)
// =============================================================================
//
// A Wyoming protocol TCP client. On `start()` it connects to the Alice speech
// gateway, streams one microphone utterance (gated by a simple energy VAD),
// then plays back the TTS audio the gateway streams in return. It loops for
// continued conversation until the user stays silent past listen_timeout_ms.
//
// Wyoming wire format (one event):
//   <json-header>\n              JSON object with "type" and optional
//                                "data_length" / "payload_length"
//   [<data_length> bytes]        optional JSON "data" object
//   [<payload_length> bytes]     optional binary payload (PCM audio)
//
// Audio: 16 kHz mono signed-16-bit PCM, matching the gateway (_SAMPLE_RATE).
// =============================================================================
#pragma once

#include <memory>
#include <string>
#include <vector>

#include "esphome/core/component.h"
#include "esphome/core/automation.h"
#include "esphome/components/audio/audio.h"
#include "esphome/components/light/light_state.h"
#include "esphome/components/microphone/microphone.h"
#include "esphome/components/speaker/speaker.h"
#include "esphome/components/socket/socket.h"

namespace esphome {
namespace wyoming_satellite {

// Microphone: the I2S hardware delivers 16 kHz stereo 32-bit PCM.
// on_mic_data_() converts each frame to mono 16-bit. AudioStart/AudioChunk
// events sent to the gateway declare this rate so Whisper gets a valid WAV.
static const uint32_t MIC_SAMPLE_RATE = 16000;
// Speaker: i2s_audio_speaker is configured at 48 kHz so audio can be driven
// directly without the speaker_mixer chain's ~6 s startup delay.
// The gateway resamples Piper (22050 Hz) to 48 kHz before sending.
static const uint32_t SAMPLE_RATE = 48000;  // used only for speaker AudioStreamInfo
static const uint8_t SAMPLE_WIDTH = 2;
static const uint8_t CHANNELS = 1;

enum class State {
  IDLE,            // wake word not active; nothing to do
  CONNECTING,      // TCP connect in progress
  CAPTURE,         // streaming a mic utterance to the gateway
  AWAIT_RESPONSE,  // reading the gateway's TTS audio back, playing it
};

class WyomingSatellite : public Component {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  // Run after networking; before the speaker so audio is ready.
  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }

  void set_host(const std::string &host) { this->host_ = host; }
  void set_port(uint16_t port) { this->port_ = port; }
  void set_microphone(microphone::Microphone *mic) { this->mic_ = mic; }
  void set_speaker(speaker::Speaker *spk) { this->speaker_ = spk; }
  void set_light(light::LightState *light) { this->light_ = light; }
  void set_silence_threshold(uint16_t v) { this->silence_threshold_ = v; }
  void set_silence_ms(uint32_t v) { this->silence_ms_ = v; }
  void set_listen_timeout_ms(uint32_t v) { this->listen_timeout_ms_ = v; }

  // Bound to the "Hey Jarvis" wake-word handler via wyoming_satellite.start.
  void start();
  // Abort the session (disconnect, return to wake-word listening).
  void stop();

  bool is_active() const { return this->state_ != State::IDLE; }

 protected:
  // --- mic capture ---
  void on_mic_data_(const std::vector<uint8_t> &data);
  void begin_utterance_();
  void end_utterance_();
  bool is_silent_(const std::vector<int16_t> &data) const;
  // PROJ-57: continuously nudge noise_floor_estimate_ towards the current frame's
  // RMS while IDLE (wake-word mic is already running, so this is free to sample).
  // Takes a pre-computed sum-of-squares rather than a sample buffer so the IDLE
  // path in on_mic_data_() never has to heap-allocate a converted PCM buffer.
  void update_noise_floor_(uint64_t sum_sq, size_t num_samples);

  // --- wyoming framing ---
  bool connect_();
  void disconnect_();
  bool send_event_(const std::string &type, const uint8_t *payload, size_t payload_len);
  bool send_raw_(const std::string &bytes);
  bool write_all_(const uint8_t *data, size_t len);
  // Drain the socket; dispatch any complete inbound events. Non-blocking.
  void read_socket_();
  // Dispatch all complete events currently in rx_buffer_. Called after each
  // socket read so the buffer never accumulates more than one event at a time.
  void try_dispatch_();
  void handle_inbound_event_(const std::string &type, const std::vector<uint8_t> &payload);
  // Re-arm the mic for the next continued-conversation turn once the speaker
  // has drained the current TTS reply.
  void rearm_when_drained_();

  bool is_silent_(const int16_t *samples, size_t num_samples) const;

  static int json_int_(const std::string &json, const std::string &key);
  static std::string json_str_(const std::string &json, const std::string &key);

  void set_state_(State state);
  void finish_session_();
  void set_led_effect_(const char *effect);
  void led_idle_();

  std::string host_;
  uint16_t port_{10300};
  microphone::Microphone *mic_{nullptr};
  speaker::Speaker *speaker_{nullptr};
  uint16_t silence_threshold_{700};
  uint32_t silence_ms_{900};
  uint32_t listen_timeout_ms_{8000};

  // PROJ-57: adaptive noise floor. configured_min_threshold_ is the YAML value
  // (captured once in setup()) and acts both as the boot-time starting point and
  // as the lower bound below which the adaptive threshold never drops — this is
  // what keeps a quiet room's behavior identical to before this feature.
  // noise_floor_estimate_ is a slow EWMA of ambient RMS, updated only while IDLE
  // (never during CAPTURE, so the user's own voice can't skew it). silence_threshold_
  // is recomputed from it once per utterance in begin_utterance_() and then frozen
  // for the rest of that utterance — is_silent_() keeps reading silence_threshold_
  // unchanged.
  uint16_t configured_min_threshold_{700};
  float noise_floor_estimate_{700.0f};
  static constexpr float NOISE_MARGIN_FACTOR = 1.8f;

  light::LightState *light_{nullptr};
  std::unique_ptr<socket::Socket> socket_;
  State state_{State::IDLE};

  // Capture bookkeeping.
  bool capturing_utterance_{false};   // AudioStart already sent for this utterance
  bool speech_seen_{false};           // any non-silent frame since (re)arming
  uint32_t last_voice_ms_{0};         // last frame with speech energy
  uint32_t capture_armed_ms_{0};      // when we (re)armed the mic for an utterance
  uint32_t utterance_start_ms_{0};    // when begin_utterance_() was last called

  // Inbound framing buffer (header line + data + payload).
  std::vector<uint8_t> rx_buffer_;
  bool tts_playing_{false};           // an inbound AudioStart was seen
  bool pending_rearm_{false};         // TTS done; waiting for speaker to drain
  uint32_t tts_stop_ms_{0};           // millis() when audio-stop was received
  // True when the mic is running (started by us or by the wake-word component at boot).
  // Used to skip redundant mic_->start() calls that would re-initialize the shared
  // I2S parent bus and corrupt concurrent speaker output (Bug 2 fix).
  bool mic_started_{true};
};

template<typename... Ts> class StartAction : public Action<Ts...>, public Parented<WyomingSatellite> {
 public:
  void play(const Ts &...x) override { this->parent_->start(); }
};

template<typename... Ts> class StopAction : public Action<Ts...>, public Parented<WyomingSatellite> {
 public:
  void play(const Ts &...x) override { this->parent_->stop(); }
};

}  // namespace wyoming_satellite
}  // namespace esphome
