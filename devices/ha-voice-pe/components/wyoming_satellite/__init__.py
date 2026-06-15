# =============================================================================
# Alice — ESPHome external component: wyoming_satellite (PROJ-42, BUG-1)
# =============================================================================
#
# A minimal Wyoming protocol TCP *client* for ESPHome. It lets a "Hey Jarvis"
# wake-word event stream microphone audio straight to the Alice speech gateway
# (ki.lan:10300) and play back the TTS audio the gateway streams back — without
# Home Assistant in the path.
#
# Stock ESPHome `voice_assistant` can only speak the HA native API; it cannot
# open a raw socket to an arbitrary host. This component fills that gap.
#
# It consumes the microphone + speaker that the official HA Voice PE package
# already defines (referenced by id) rather than owning the I2S bus itself, so
# the "Okay Nabu" / HA Assist path keeps working unchanged.
# =============================================================================
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation
from esphome.components import microphone, speaker
from esphome.const import CONF_ID, CONF_MICROPHONE, CONF_SPEAKER

CODEOWNERS = ["@alice"]
# `socket` gives us the TCP client; `network` ensures wifi/IP is up first.
DEPENDENCIES = ["network", "microphone", "speaker"]
AUTO_LOAD = ["socket"]

wyoming_satellite_ns = cg.esphome_ns.namespace("wyoming_satellite")
WyomingSatellite = wyoming_satellite_ns.class_("WyomingSatellite", cg.Component)
StartAction = wyoming_satellite_ns.class_("StartAction", automation.Action)
StopAction = wyoming_satellite_ns.class_("StopAction", automation.Action)

CONF_HOST = "host"
CONF_PORT = "port"
# End-of-utterance / silence tuning (on-device VAD). Defaults are conservative;
# tune on hardware against room noise.
CONF_SILENCE_THRESHOLD = "silence_threshold"
CONF_SILENCE_MS = "silence_ms"
CONF_LISTEN_TIMEOUT_MS = "listen_timeout_ms"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(WyomingSatellite),
        cv.Required(CONF_HOST): cv.string,
        cv.Required(CONF_PORT): cv.port,
        cv.Required(CONF_MICROPHONE): cv.use_id(microphone.Microphone),
        cv.Required(CONF_SPEAKER): cv.use_id(speaker.Speaker),
        # RMS amplitude (0-32767) below which a 16 kHz frame counts as silence.
        cv.Optional(CONF_SILENCE_THRESHOLD, default=700): cv.int_range(min=0, max=32767),
        # Continuous silence that ends one utterance (sends Wyoming AudioStop).
        cv.Optional(CONF_SILENCE_MS, default=900): cv.positive_int,
        # Continued conversation: silence with no speech that ends the session
        # and returns the device to wake-word listening.
        cv.Optional(CONF_LISTEN_TIMEOUT_MS, default=8000): cv.positive_int,
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    cg.add(var.set_host(config[CONF_HOST]))
    cg.add(var.set_port(config[CONF_PORT]))

    mic = await cg.get_variable(config[CONF_MICROPHONE])
    cg.add(var.set_microphone(mic))
    spk = await cg.get_variable(config[CONF_SPEAKER])
    cg.add(var.set_speaker(spk))

    cg.add(var.set_silence_threshold(config[CONF_SILENCE_THRESHOLD]))
    cg.add(var.set_silence_ms(config[CONF_SILENCE_MS]))
    cg.add(var.set_listen_timeout_ms(config[CONF_LISTEN_TIMEOUT_MS]))


WYOMING_SATELLITE_ACTION_SCHEMA = automation.maybe_simple_id(
    {cv.GenerateID(): cv.use_id(WyomingSatellite)}
)


@automation.register_action(
    "wyoming_satellite.start", StartAction, WYOMING_SATELLITE_ACTION_SCHEMA,
    synchronous=False,
)
async def start_action_to_code(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    return var


@automation.register_action(
    "wyoming_satellite.stop", StopAction, WYOMING_SATELLITE_ACTION_SCHEMA,
    synchronous=False,
)
async def stop_action_to_code(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    return var
