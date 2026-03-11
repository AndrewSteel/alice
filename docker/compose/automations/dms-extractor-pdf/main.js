"use strict";

/**
 * dms-extractor-pdf: Subscribes to MQTT topic alice/dms/pdf,
 * extracts text from PDF files using pdf-parse, and pushes
 * the result to Redis list alice:dms:plaintext.
 */

const fs = require("fs");
const mqtt = require("mqtt");
const Redis = require("ioredis");
const pdfParse = require("pdf-parse");

// ---------------------------------------------------------------------------
// Configuration (from environment variables, never hardcoded)
// ---------------------------------------------------------------------------
const MQTT_HOST = process.env.MQTT_HOST || "mqtt";
const MQTT_PORT = parseInt(process.env.MQTT_PORT || "1883", 10);
const MQTT_USERNAME = process.env.MQTT_USERNAME || "";
const MQTT_PASSWORD = process.env.MQTT_PASSWORD || "";

const REDIS_HOST = process.env.REDIS_HOST || "redis";
const REDIS_PORT = parseInt(process.env.REDIS_PORT || "6379", 10);

const MQTT_TOPIC = "alice/dms/pdf";
const REDIS_KEY = "alice:dms:plaintext";
const PLAINTEXT_MAX_CHARS = 50000;
const HEARTBEAT_FILE = "/tmp/heartbeat";
const HEARTBEAT_INTERVAL_MS = 30000;

// ---------------------------------------------------------------------------
// Logging (structured JSON)
// ---------------------------------------------------------------------------
function log(level, message, extra = {}) {
  const entry = {
    timestamp: new Date().toISOString(),
    level,
    service: "dms-extractor-pdf",
    message,
    ...extra,
  };
  if (level === "error") {
    console.error(JSON.stringify(entry));
  } else {
    console.log(JSON.stringify(entry));
  }
}

// ---------------------------------------------------------------------------
// Heartbeat
// ---------------------------------------------------------------------------
function writeHeartbeat() {
  try {
    fs.writeFileSync(HEARTBEAT_FILE, String(Date.now()));
  } catch (err) {
    log("error", "Failed to write heartbeat", { error: err.message });
  }
}

setInterval(writeHeartbeat, HEARTBEAT_INTERVAL_MS);
writeHeartbeat();

// ---------------------------------------------------------------------------
// Redis client
// ---------------------------------------------------------------------------
const redis = new Redis({
  host: REDIS_HOST,
  port: REDIS_PORT,
  password: process.env.REDIS_PASSWORD || undefined,
  maxRetriesPerRequest: null,
  retryStrategy(times) {
    const delay = Math.min(times * 1000, 30000);
    log("warn", `Redis reconnecting in ${delay}ms`, { attempt: times });
    return delay;
  },
});

redis.on("connect", () => log("info", "Connected to Redis"));
redis.on("error", (err) =>
  log("error", "Redis error", { error: err.message })
);

// ---------------------------------------------------------------------------
// MQTT client
// ---------------------------------------------------------------------------
const mqttClient = mqtt.connect(`mqtt://${MQTT_HOST}:${MQTT_PORT}`, {
  username: MQTT_USERNAME,
  password: MQTT_PASSWORD,
  clientId: `dms-extractor-pdf-${Date.now()}`,
  clean: true,
  reconnectPeriod: 5000,
});

mqttClient.on("connect", () => {
  log("info", "Connected to MQTT broker");
  mqttClient.subscribe(MQTT_TOPIC, { qos: 1 }, (err) => {
    if (err) {
      log("error", "Failed to subscribe to MQTT topic", {
        topic: MQTT_TOPIC,
        error: err.message,
      });
    } else {
      log("info", "Subscribed to MQTT topic", { topic: MQTT_TOPIC });
    }
  });
});

mqttClient.on("error", (err) =>
  log("error", "MQTT error", { error: err.message })
);

mqttClient.on("reconnect", () => log("warn", "MQTT reconnecting"));

// ---------------------------------------------------------------------------
// Message handler
// ---------------------------------------------------------------------------
mqttClient.on("message", async (_topic, messageBuffer) => {
  let input;

  // Parse incoming MQTT message
  try {
    input = JSON.parse(messageBuffer.toString());
  } catch (err) {
    log("error", "Invalid JSON in MQTT message, discarding", {
      error: err.message,
      raw: messageBuffer.toString().substring(0, 200),
    });
    return;
  }

  const { file_path, file_hash, file_type, file_size, suggested_type, priority, detected_at } = input;

  if (!file_path || !file_path.startsWith("/mnt/nas/")) {
    log("error", "Rejected message with invalid file_path (must start with /mnt/nas/)", {
      file_path,
    });
    return;
  }

  log("info", "Processing PDF", { file_path, file_hash });

  let plaintext = "";
  let extractionFailed = false;
  const metadata = {};

  try {
    // Read file from NAS mount
    const buffer = fs.readFileSync(file_path);
    const result = await pdfParse(buffer);

    plaintext = result.text || "";
    metadata.page_count = result.numpages || null;
    metadata.char_count = plaintext.length;

    // Truncate if too long
    if (plaintext.length > PLAINTEXT_MAX_CHARS) {
      plaintext = plaintext.substring(0, PLAINTEXT_MAX_CHARS);
      metadata.truncated = true;
      log("warn", "Plaintext truncated", {
        file_path,
        original_length: metadata.char_count,
        truncated_to: PLAINTEXT_MAX_CHARS,
      });
    }

    log("info", "PDF extraction successful", {
      file_path,
      page_count: metadata.page_count,
      char_count: metadata.char_count,
    });
  } catch (err) {
    extractionFailed = true;
    log("error", "PDF extraction failed", {
      file_path,
      error: err.message,
    });
  }

  // Build output message
  const output = {
    file_path,
    file_hash,
    file_type: file_type || "pdf",
    file_size: file_size || 0,
    suggested_type: suggested_type || "",
    priority: priority || "normal",
    detected_at: detected_at || new Date().toISOString(),
    extracted_at: new Date().toISOString(),
    extractor: "dms-extractor-pdf",
    plaintext,
    extraction_failed: extractionFailed,
    metadata,
  };

  // Push to Redis
  try {
    await redis.rpush(REDIS_KEY, JSON.stringify(output));
    log("info", "Result pushed to Redis", { file_path, redis_key: REDIS_KEY });
  } catch (err) {
    log("error", "Failed to push to Redis, result lost", {
      file_path,
      error: err.message,
    });
  }

  writeHeartbeat();
});

// ---------------------------------------------------------------------------
// Graceful shutdown
// ---------------------------------------------------------------------------
function shutdown(signal) {
  log("info", `Received ${signal}, shutting down`);
  mqttClient.end(true);
  redis.quit().catch(() => {});
  process.exit(0);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

log("info", "dms-extractor-pdf starting", {
  mqtt_host: MQTT_HOST,
  mqtt_topic: MQTT_TOPIC,
  redis_host: REDIS_HOST,
  redis_key: REDIS_KEY,
});
