// =============================================================================
// Alice — wyoming_satellite ESPHome external component (PROJ-42, BUG-1)
// =============================================================================
// See wyoming_satellite.h for the protocol summary and the per-turn flow.
//
// NOTE (hardware iteration): three spots are the most version-sensitive across
// ESPHome releases — flagged inline with [VERSION]:
//   1. microphone data-callback element type (int16_t vs uint8_t),
//   2. socket helper factory / connect signature,
//   3. speaker::is_running() semantics.
// If a build fails, start at the [VERSION] markers. See README.md.
// =============================================================================
#include "wyoming_satellite.h"

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cstring>

#include <lwip/netdb.h>  // getaddrinfo — resolves IP literals and hostnames

#include "esphome/core/log.h"
#include "esphome/core/hal.h"

namespace esphome {
namespace wyoming_satellite {

static const char *const TAG = "wyoming_satellite";

// Audio format declared in AudioStart / AudioChunk events sent to the gateway.
// Uses MIC_SAMPLE_RATE (16 kHz) — the actual I2S capture rate. SAMPLE_RATE
// (48 kHz) is the SPEAKER rate and must NOT be used here; declaring 48 kHz
// for 16 kHz audio compresses it 3× in Whisper, producing garbage transcripts.
static std::string audio_format_json() {
  return "{\"rate\": " + std::to_string(MIC_SAMPLE_RATE) +
         ", \"width\": " + std::to_string(SAMPLE_WIDTH) +
         ", \"channels\": " + std::to_string(CHANNELS) + "}";
}

void WyomingSatellite::setup() {
  // The mic stays stopped until start(); we only register the data sink here.
  // ESPHome microphone API delivers raw PCM as uint8_t bytes.
  this->mic_->add_data_callback([this](const std::vector<uint8_t> &data) {
    this->on_mic_data_(data);
  });
  // PROJ-57: the YAML silence_threshold becomes the floor + boot-time starting
  // point for the adaptive noise floor, not a fixed threshold anymore.
  this->configured_min_threshold_ = this->silence_threshold_;
  this->noise_floor_estimate_ = static_cast<float>(this->silence_threshold_);
  ESP_LOGCONFIG(TAG, "wyoming_satellite ready (target %s:%u)", this->host_.c_str(), this->port_);
}

void WyomingSatellite::dump_config() {
  ESP_LOGCONFIG(TAG, "Wyoming Satellite:");
  ESP_LOGCONFIG(TAG, "  Gateway: %s:%u", this->host_.c_str(), this->port_);
  ESP_LOGCONFIG(TAG, "  Silence threshold: %u, silence_ms: %u, listen_timeout_ms: %u",
                this->silence_threshold_, this->silence_ms_, this->listen_timeout_ms_);
}

void WyomingSatellite::loop() {
  switch (this->state_) {
    case State::IDLE:
    case State::CONNECTING:
      break;

    case State::CAPTURE:
      // Detect a peer-side close while we are talking.
      this->read_socket_();
      // Silence detection: end utterance after silence_ms_ of quiet once speech has been
      // detected. on_mic_data_() converts raw I2S to mono 16-bit before updating
      // speech_seen_ / last_voice_ms_, so is_silent_() threshold is calibrated correctly.
      if (this->capturing_utterance_ && this->speech_seen_ &&
          (millis() - this->last_voice_ms_) > this->silence_ms_) {
        ESP_LOGD(TAG, "Silence (%.0f ms) — ending utterance", this->silence_ms_ / 1.0f);
        this->end_utterance_();
        break;
      }
      // Fallback: no speech detected → end session silently without triggering
      // STT. Sending audio-stop would cause the gateway to transcribe silence
      // and reply "Ich habe nichts verstanden" — bad UX for accidental triggers.
      // We disconnect cleanly; the gateway sees an EOF and closes gracefully.
      if (this->capturing_utterance_ && !this->speech_seen_ &&
          (millis() - this->utterance_start_ms_) > this->listen_timeout_ms_) {
        ESP_LOGD(TAG, "Listen timeout (%.0f s) without speech — ending session silently",
                 this->listen_timeout_ms_ / 1000.0f);
        this->finish_session_();
        break;
      }
      // PROJ-57 safety net: an absolute cap independent of speech_seen_/is_silent_.
      // If ambient noise never dips below the (adaptive) threshold for the whole
      // utterance — e.g. a vacuum cleaner right next to the device — the two
      // branches above never fire and capture would otherwise run forever.
      if (this->capturing_utterance_ &&
          (millis() - this->utterance_start_ms_) > this->listen_timeout_ms_) {
        ESP_LOGD(TAG, "Hard timeout (%.0f s) while capturing — ending utterance (safety net)",
                 this->listen_timeout_ms_ / 1000.0f);
        this->end_utterance_();
      }
      break;

    case State::AWAIT_RESPONSE:
      this->read_socket_();
      // After the gateway's audio-stop we wait for the speaker to drain before
      // re-arming the mic (avoids capturing the TTS tail).
      if (this->pending_rearm_)
        this->rearm_when_drained_();
      break;
  }
}

void WyomingSatellite::start() {
  if (this->state_ != State::IDLE) {
    ESP_LOGD(TAG, "start() ignored — session already active");
    return;
  }
  ESP_LOGD(TAG, "Hey Jarvis — connecting to Alice gateway %s:%u", this->host_.c_str(), this->port_);
  this->set_state_(State::CONNECTING);
  if (!this->connect_()) {
    ESP_LOGW(TAG, "Connect failed — returning to wake-word listening");
    this->set_state_(State::IDLE);
    return;
  }
  this->rx_buffer_.clear();
  // Pre-reserve before mic callbacks fragment the heap.
  // Must exceed the largest single Wyoming event: header (~150 B) + piper audio payload
  // (up to ~8 KB per chunk) = ~8.3 KB. Use 16 KB for 2× headroom.
  this->rx_buffer_.reserve(16384);
  // Bypass on-device VAD: start utterance immediately so the gateway receives
  // audio from the first frame. Whisper's vad_filter identifies speech server-side.
  // (The I2S delivers 32-bit stereo data that our 16-bit RMS cannot reliably gate.)
  this->capturing_utterance_ = false;
  this->speech_seen_ = false;
  this->last_voice_ms_ = millis();
  this->capture_armed_ms_ = millis();
  // The mic is already running for wake-word detection; re-calling start()
  // re-initializes the shared I2S parent bus and corrupts any concurrent
  // speaker output (announcement pipeline wake sound). Only start it if we
  // explicitly stopped it during a previous session (Bug 2 fix).
  if (!this->mic_started_)
    this->mic_->start();
  this->mic_started_ = true;
  this->set_state_(State::CAPTURE);
  this->begin_utterance_();  // sends audio-start to gateway
  this->set_led_effect_("Listening For Command");
}

void WyomingSatellite::stop() {
  if (this->state_ == State::IDLE)
    return;
  ESP_LOGD(TAG, "stop() — aborting session");
  this->finish_session_();
}

// ---------------------------------------------------------------------------
// Microphone capture (VAD bypassed — gateway Whisper handles speech detection)
// ---------------------------------------------------------------------------

void WyomingSatellite::on_mic_data_(const std::vector<uint8_t> &data) {
  if (data.empty())
    return;
  // PROJ-57: also process frames while IDLE (wake-word mic is already running)
  // so the noise floor keeps tracking ambient level between utterances. No
  // other state (CONNECTING/AWAIT_RESPONSE) needs this — nothing above is
  // used for VAD then.
  if (this->state_ != State::CAPTURE && this->state_ != State::IDLE)
    return;

  const size_t frames = data.size() / 8;

  if (this->state_ == State::IDLE) {
    // Wake-word-listening frame: only the RMS is needed for the noise floor
    // estimate, so extract samples without heap-allocating a pcm16 buffer —
    // this path runs on every mic frame for as long as the device is idle
    // (i.e. almost always), so it must stay allocation-free.
    uint64_t sum_sq = 0;
    for (size_t i = 0; i < frames * 8; i += 8) {
      const int32_t s32 =
          static_cast<int32_t>(data[i]) |
          (static_cast<int32_t>(data[i + 1]) << 8) |
          (static_cast<int32_t>(data[i + 2]) << 16) |
          (static_cast<int32_t>(data[i + 3]) << 24);
      const int16_t s16 = static_cast<int16_t>(s32 >> 16);
      sum_sq += static_cast<int32_t>(s16) * static_cast<int32_t>(s16);
    }
    this->update_noise_floor_(sum_sq, frames);
    return;
  }

  // The I2S hardware delivers 32-bit stereo PCM (little-endian, MSB-justified):
  // 8 bytes per sample pair — 4 bytes left channel + 4 bytes right channel.
  // Convert to 16-bit mono: take the left channel and extract bits 31-16.
  // This matches the format declared in audio_format_json() (width=2, channels=1).
  std::vector<uint8_t> pcm16;
  pcm16.reserve(frames * 2);
  for (size_t i = 0; i < frames * 8; i += 8) {
    const int32_t s32 =
        static_cast<int32_t>(data[i]) |
        (static_cast<int32_t>(data[i + 1]) << 8) |
        (static_cast<int32_t>(data[i + 2]) << 16) |
        (static_cast<int32_t>(data[i + 3]) << 24);
    const uint16_t s16 = static_cast<uint16_t>(static_cast<int16_t>(s32 >> 16));
    pcm16.push_back(static_cast<uint8_t>(s16 & 0xFF));
    pcm16.push_back(static_cast<uint8_t>(s16 >> 8));
  }

  if (this->capturing_utterance_ && !pcm16.empty()) {
    this->send_event_("audio-chunk", pcm16.data(), pcm16.size());
    // VAD: on_mic_data_() already produces mono 16-bit PCM, so is_silent_() is
    // valid here. Track the last non-silent frame so loop() can end the utterance
    // after silence_ms_ of quiet following speech.
    const int16_t *samples = reinterpret_cast<const int16_t *>(pcm16.data());
    if (!this->is_silent_(samples, pcm16.size() / 2)) {
      this->last_voice_ms_ = millis();
      this->speech_seen_ = true;
    }
  }

  // Diagnostic log every 100 frames.
  // After conversion: bytes/frame should be ~512 (16kHz mono 16-bit, 16ms per DMA buffer).
  {
    static uint32_t s_frame_cnt = 0;
    static uint32_t s_bytes_total = 0;
    s_bytes_total += data.size();
    if (++s_frame_cnt >= 100) {
      ESP_LOGD(TAG, "I2S: raw_bytes/frame=%u pcm16_bytes/frame=%u utterance=%s",
               s_bytes_total / 100, s_bytes_total / 100 / 4,
               this->capturing_utterance_ ? "Y" : "N");
      s_frame_cnt = 0;
      s_bytes_total = 0;
    }
  }
}

void WyomingSatellite::update_noise_floor_(uint64_t sum_sq, size_t num_samples) {
  if (num_samples == 0)
    return;
  const float rms = std::sqrt(static_cast<float>(sum_sq) / num_samples);
  // Slow EWMA: converges over a few seconds of IDLE audio, so a single loud
  // transient (door slam, cough) can't swing the estimate on its own.
  static constexpr float ALPHA = 0.02f;
  this->noise_floor_estimate_ += ALPHA * (rms - this->noise_floor_estimate_);
}

bool WyomingSatellite::is_silent_(const int16_t *samples, size_t num_samples) const {
  if (num_samples == 0)
    return true;
  uint64_t sum_sq = 0;
  for (size_t i = 0; i < num_samples; ++i)
    sum_sq += static_cast<int32_t>(samples[i]) * static_cast<int32_t>(samples[i]);
  const double rms = std::sqrt(static_cast<double>(sum_sq) / num_samples);
  return rms < static_cast<double>(this->silence_threshold_);
}

void WyomingSatellite::begin_utterance_() {
  // PROJ-57: freeze this utterance's speech threshold from the current noise
  // floor estimate. Frozen (not updated during CAPTURE) so the user's own voice
  // can't drag the threshold up mid-utterance. Floored at configured_min_threshold_
  // so a quiet room (noise floor well below the old fixed 700) behaves exactly
  // as before this feature.
  this->silence_threshold_ = std::max(
      this->configured_min_threshold_,
      static_cast<uint16_t>(this->noise_floor_estimate_ * NOISE_MARGIN_FACTOR));
  ESP_LOGD(TAG, "Adaptive silence threshold for this utterance: %u (noise floor ~%.0f)",
           this->silence_threshold_, this->noise_floor_estimate_);

  const std::string fmt = audio_format_json();
  // AudioStart carries the audio format as its data object, no payload.
  if (!this->socket_)
    return;
  std::string header = "{\"type\": \"audio-start\", \"data_length\": " +
                       std::to_string(fmt.size()) + "}\n";
  if (!this->send_raw_(header) || !this->send_raw_(fmt)) {
    ESP_LOGW(TAG, "AudioStart send failed");
    this->finish_session_();
    return;
  }
  this->capturing_utterance_ = true;
  this->utterance_start_ms_ = millis();
  ESP_LOGD(TAG, "Utterance start");
}

void WyomingSatellite::end_utterance_() {
  ESP_LOGD(TAG, "Utterance end (silence) — awaiting response");
  this->send_event_("audio-stop", nullptr, 0);
  this->capturing_utterance_ = false;
  this->mic_->stop();
  this->mic_started_ = false;
  this->pending_rearm_ = false;
  this->set_state_(State::AWAIT_RESPONSE);
  this->set_led_effect_("Thinking");
}

// ---------------------------------------------------------------------------
// Wyoming TCP framing
// ---------------------------------------------------------------------------

bool WyomingSatellite::connect_() {
  // [VERSION] getaddrinfo resolves both dotted-quad IPs and hostnames via lwip.
  // Prefer a fixed IP in the YAML to avoid DNS dependency on the device.
  struct addrinfo hints = {};
  hints.ai_family = AF_INET;
  hints.ai_socktype = SOCK_STREAM;
  struct addrinfo *res = nullptr;
  const std::string port_str = std::to_string(this->port_);
  int err = ::getaddrinfo(this->host_.c_str(), port_str.c_str(), &hints, &res);
  if (err != 0 || res == nullptr) {
    ESP_LOGW(TAG, "Resolve failed for %s: %d", this->host_.c_str(), err);
    if (res != nullptr)
      ::freeaddrinfo(res);
    return false;
  }

  this->socket_ = socket::socket(res->ai_family, res->ai_socktype, res->ai_protocol);
  if (!this->socket_) {
    ::freeaddrinfo(res);
    return false;
  }
  int r = this->socket_->connect(res->ai_addr, res->ai_addrlen);
  ::freeaddrinfo(res);
  if (r != 0) {
    ESP_LOGW(TAG, "connect() failed: errno=%d", errno);
    this->socket_.reset();
    return false;
  }
  this->socket_->setblocking(false);  // reads poll in loop(); writes retry briefly
  return true;
}

void WyomingSatellite::disconnect_() {
  if (this->socket_) {
    this->socket_->close();
    this->socket_.reset();
  }
  // Release the reserved capacity so the next session's reserve() starts from
  // a less fragmented heap (clear() keeps the allocation, swap releases it).
  { std::vector<uint8_t> empty; empty.swap(this->rx_buffer_); }
}

bool WyomingSatellite::send_raw_(const std::string &bytes) {
  return this->write_all_(reinterpret_cast<const uint8_t *>(bytes.data()), bytes.size());
}

bool WyomingSatellite::write_all_(const uint8_t *data, size_t len) {
  if (!this->socket_)
    return false;
  size_t sent = 0;
  const uint32_t deadline = millis() + 250;  // bounded; non-blocking socket
  while (sent < len) {
    ssize_t n = this->socket_->write(data + sent, len - sent);
    if (n > 0) {
      sent += static_cast<size_t>(n);
    } else if (n < 0 && (errno == EWOULDBLOCK || errno == EAGAIN)) {
      if (millis() > deadline) {
        ESP_LOGW(TAG, "write timeout (%u/%u bytes)", (unsigned) sent, (unsigned) len);
        return false;
      }
      delay(1);
    } else {
      ESP_LOGW(TAG, "write error: errno=%d", errno);
      return false;
    }
  }
  return true;
}

bool WyomingSatellite::send_event_(const std::string &type, const uint8_t *payload, size_t payload_len) {
  if (!this->socket_)
    return false;
  // audio-chunk needs the format as its data object so the gateway can decode
  // it; audio-stop has neither data nor payload.
  std::string header = "{\"type\": \"" + type + "\"";
  std::string data_json;
  if (type == "audio-chunk") {
    data_json = audio_format_json();
    header += ", \"data_length\": " + std::to_string(data_json.size());
  }
  if (payload_len > 0)
    header += ", \"payload_length\": " + std::to_string(payload_len);
  header += "}\n";

  if (!this->send_raw_(header))
    return false;
  if (!data_json.empty() && !this->send_raw_(data_json))
    return false;
  if (payload_len > 0 && !this->write_all_(payload, payload_len))
    return false;
  return true;
}

void WyomingSatellite::read_socket_() {
  if (!this->socket_)
    return;
  uint8_t buf[512];
  while (true) {
    ssize_t n = this->socket_->read(buf, sizeof(buf));
    if (n > 0) {
      if (this->rx_buffer_.size() + static_cast<size_t>(n) > this->rx_buffer_.capacity()) {
        // Guard: buffer full even after dispatch — gateway chunk too large.
        ESP_LOGW(TAG, "rx_buffer_ overflow (%u/%u B) — disconnecting",
                 (unsigned)(this->rx_buffer_.size() + n), (unsigned)this->rx_buffer_.capacity());
        this->finish_session_();
        return;
      }
      this->rx_buffer_.insert(this->rx_buffer_.end(), buf, buf + n);
      // Dispatch immediately after each read block so the buffer never
      // accumulates more than one incomplete event (~4 KB with 4 KB gateway chunks).
      this->try_dispatch_();
    } else if (n == 0) {
      ESP_LOGD(TAG, "Gateway closed the connection — ending session");
      this->finish_session_();
      return;
    } else {
      break;  // EWOULDBLOCK / no more data right now
    }
  }
}

void WyomingSatellite::try_dispatch_() {
  while (true) {
    auto nl = std::find(this->rx_buffer_.begin(), this->rx_buffer_.end(), '\n');
    if (nl == this->rx_buffer_.end())
      break;  // header not yet complete
    const size_t header_len = static_cast<size_t>(nl - this->rx_buffer_.begin());
    const std::string header(this->rx_buffer_.begin(), this->rx_buffer_.begin() + header_len);
    const int data_len = json_int_(header, "data_length");
    const int payload_len = json_int_(header, "payload_length");
    const size_t consumed = header_len + 1;  // include '\n'
    const size_t need = consumed + std::max(0, data_len) + std::max(0, payload_len);
    if (this->rx_buffer_.size() < need)
      break;  // payload not yet complete — wait for next read
    const std::string type = json_str_(header, "type");
    const size_t payload_start = consumed + std::max(0, data_len);
    std::vector<uint8_t> payload(this->rx_buffer_.begin() + payload_start,
                                 this->rx_buffer_.begin() + payload_start + std::max(0, payload_len));
    this->handle_inbound_event_(type, payload);
    this->rx_buffer_.erase(this->rx_buffer_.begin(), this->rx_buffer_.begin() + need);
  }
}

void WyomingSatellite::handle_inbound_event_(const std::string &type, const std::vector<uint8_t> &payload) {
  if (type == "audio-start") {
    ESP_LOGD(TAG, "TTS playback start");
    // Cancel any pending mic rearm — new TTS is arriving so the "Warte bitte…"
    // interstitial sequence doesn't erroneously switch to CC-listening state.
    this->pending_rearm_ = false;
    // i2s_audio_speaker is co-owned by the package's mixing_speaker (which feeds
    // it 16-bit stereo from the resampler chain). Using 16-bit stereo here keeps
    // audio_stream_info consistent with what the mixer leaves behind after each
    // use — preventing the I2S channel format from being left in mono mode
    // (I2S_CHANNEL_FMT_ONLY_LEFT), which causes the next wake sound to play at
    // the wrong pitch (Bug 2 root cause).
    this->speaker_->set_audio_stream_info(
        audio::AudioStreamInfo(SAMPLE_WIDTH * 8, 2, SAMPLE_RATE));
    this->speaker_->start();
    this->tts_playing_ = true;
    this->set_led_effect_("Replying");
  } else if (type == "audio-chunk") {
    if (!payload.empty()) {
      // Gateway sends 16-bit mono 48 kHz PCM. Duplicate each sample to stereo so
      // the data matches the 16-bit stereo audio_stream_info set above.
      const size_t samples = payload.size() / 2;
      std::vector<uint8_t> stereo;
      stereo.reserve(samples * 4);  // 2 bytes in → 4 bytes out (L + R)
      for (size_t i = 0; i < samples; ++i) {
        stereo.push_back(payload[i * 2]);      // L low byte
        stereo.push_back(payload[i * 2 + 1]);  // L high byte
        stereo.push_back(payload[i * 2]);      // R low byte (duplicate)
        stereo.push_back(payload[i * 2 + 1]);  // R high byte (duplicate)
      }
      this->speaker_->play(stereo.data(), stereo.size());
    }
  } else if (type == "audio-stop") {
    ESP_LOGD(TAG, "TTS done — will re-arm mic in 400 ms once speaker drains");
    this->tts_stop_ms_ = millis();
    this->tts_playing_ = false;
    this->pending_rearm_ = true;
    this->set_led_effect_("Thinking");
    // Do NOT call rearm_when_drained_() here — the speaker ring buffer is still
    // playing. loop() polls it every tick; the actual rearm fires after the delay.
  }
}

void WyomingSatellite::rearm_when_drained_() {
  // is_running() is unreliable across ESPHome versions — it may never return
  // false even after playback ends ([VERSION] marker). Use a fixed 400 ms delay
  // after audio-stop: the gateway paces audio at 48 kHz real-time, so audio-stop
  // arrives ≤ ~50 ms after the last sample plays. The ring buffer holds ~200 ms,
  // so 400 ms guarantees full drain + a short XMOS AEC settle window.
  if (!this->pending_rearm_)
    return;
  if (millis() - this->tts_stop_ms_ < 400)
    return;
  this->pending_rearm_ = false;
  if (this->speaker_ != nullptr)
    this->speaker_->stop();
  this->capturing_utterance_ = false;
  this->speech_seen_ = false;
  this->last_voice_ms_ = millis();
  this->capture_armed_ms_ = millis();
  this->mic_->start();
  this->mic_started_ = true;
  this->set_state_(State::CAPTURE);
  this->begin_utterance_();
  this->set_led_effect_("Listening For Command");
}

// ---------------------------------------------------------------------------
// Minimal header-JSON field extraction (headers are tiny machine JSON).
// ---------------------------------------------------------------------------

int WyomingSatellite::json_int_(const std::string &json, const std::string &key) {
  const std::string needle = "\"" + key + "\"";
  size_t pos = json.find(needle);
  if (pos == std::string::npos)
    return 0;
  pos = json.find(':', pos + needle.size());
  if (pos == std::string::npos)
    return 0;
  return atoi(json.c_str() + pos + 1);
}

std::string WyomingSatellite::json_str_(const std::string &json, const std::string &key) {
  const std::string needle = "\"" + key + "\"";
  size_t pos = json.find(needle);
  if (pos == std::string::npos)
    return "";
  pos = json.find(':', pos + needle.size());
  if (pos == std::string::npos)
    return "";
  size_t q1 = json.find('"', pos);
  if (q1 == std::string::npos)
    return "";
  size_t q2 = json.find('"', q1 + 1);
  if (q2 == std::string::npos)
    return "";
  return json.substr(q1 + 1, q2 - q1 - 1);
}

// ---------------------------------------------------------------------------

void WyomingSatellite::set_state_(State state) { this->state_ = state; }

void WyomingSatellite::set_led_effect_(const char *effect) {
  if (this->light_ == nullptr) return;
  auto call = this->light_->make_call();
  call.set_state(true);
  call.set_effect(effect);
  call.perform();
}

void WyomingSatellite::led_idle_() {
  if (this->light_ == nullptr) return;
  auto call = this->light_->make_call();
  call.set_state(false);
  call.perform();
}

void WyomingSatellite::finish_session_() {
  // Only stop the mic if we know it is currently running. Unnecessary stop+start
  // cycles re-initialize the shared I2S parent bus and change its clock, which
  // corrupts the announcement pipeline's wake sound on the next activation (Bug 2).
  // end_utterance_() already tracks when it stops the mic; if the mic is already
  // stopped (or rearm already restarted it and we left it running), we leave it alone.
  if (this->mic_ != nullptr && this->mic_started_) {
    this->mic_->stop();
    this->mic_started_ = false;
  }
  // Only stop the speaker if TTS was active. Calling speaker_->stop() while in
  // CAPTURE (no TTS yet) corrupts the I2S bus state used by the announcement
  // pipeline (speaker_mixer), causing the wake sound to play at the wrong rate
  // on subsequent activations.
  if (this->speaker_ != nullptr && this->tts_playing_)
    this->speaker_->stop();
  this->disconnect_();
  this->capturing_utterance_ = false;
  this->tts_playing_ = false;
  this->pending_rearm_ = false;
  this->set_state_(State::IDLE);
  this->led_idle_();
  ESP_LOGD(TAG, "Session ended — wake-word listening");
  // Restart the mic only if it was stopped during the session. micro_wake_word
  // never restarts it after we stop it in end_utterance_().
  if (this->mic_ != nullptr && !this->mic_started_) {
    this->mic_->start();
    this->mic_started_ = true;
  }
}

}  // namespace wyoming_satellite
}  // namespace esphome
