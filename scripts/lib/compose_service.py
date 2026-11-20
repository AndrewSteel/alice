"""Derives test and staging compose files from a service's production compose.yml.

Used by scripts/test-containers.sh (throwaway test run) and scripts/stage.sh
(staging next to production on the server). Never reads .env files: it only
writes paths to them (staging) or builds a test env from .env.example.

  python compose_service.py test  <svc-dir> <image> <out-dir>
      writes <out-dir>/compose.json and <out-dir>/test.env, prints three lines:
      service name, test profiles, secret files under /run/secrets (space-separated)

  python compose_service.py stage <svc-dir> <image> <compose-root> <out-file>
      writes the staging compose file, prints two lines: staging service name, networks
"""

import json
import os
import re
import sys

import yaml

# Keys of the production service that a test container keeps. Everything else
# (ports, volumes, networks, deploy/GPUs, depends_on, container_name, ...) is
# dropped: it refers to the server or to other production services.
TEST_KEYS = ("build", "command", "entrypoint", "environment", "healthcheck", "user",
             "working_dir", "tmpfs", "shm_size", "stop_grace_period", "init")

PG_DSN = "postgresql://alice:test@test-postgres:5432/alice"
FIXED = {
    "POSTGRES_HOST": "test-postgres", "POSTGRES_PORT": "5432", "POSTGRES_DB": "alice",
    "POSTGRES_USER": "alice", "POSTGRES_PASSWORD": "test",
    "REDIS_HOST": "test-redis", "REDIS_PORT": "6379", "REDIS_PASSWORD": "",
    "REDIS_URL": "redis://test-redis:6379/0",
    "WEAVIATE_URL": "http://test-weaviate:8080",
    "MQTT_HOST": "test-mqtt", "MQTT_PORT": "1883", "MQTT_URL": "mqtt://test-mqtt:1883",
}
PROFILE_KEYS = {"weaviate": ("WEAVIATE_URL",), "mqtt": ("MQTT_HOST", "MQTT_URL")}


def load(svc_dir):
    with open(os.path.join(svc_dir, "compose.yml")) as f:
        doc = yaml.safe_load(f) or {}
    services = doc.get("services") or {}
    name = os.path.basename(os.path.normpath(svc_dir))
    if name not in services:
        built = [k for k, v in services.items() if isinstance(v, dict) and v.get("build")]
        if len(built) != 1:
            sys.exit(f"{svc_dir}/compose.yml: no service named {name!r} and not exactly one service with build:")
        name = built[0]
    svc = services[name]
    if not svc.get("build"):
        sys.exit(f"{name}: service has no build: section (image-only services are not tested)")
    return doc, name, svc


def absolute_build(build, svc_dir):
    build = {"context": build} if isinstance(build, str) else dict(build)
    build["context"] = os.path.abspath(os.path.join(svc_dir, build.get("context", ".")))
    return build


def read_env(path):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path) as f:
        for line in f:
            line = line.strip()
            m = re.match(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            if m:
                env[m.group(1)] = m.group(2).strip().strip("\"'")
    return env


def secret_targets(svc):
    names = []
    for v in svc.get("volumes") or []:
        target = v.get("target", "") if isinstance(v, dict) else (v.split(":")[1] if ":" in v else "")
        if target.startswith("/run/secrets/"):
            names.append(target[len("/run/secrets/"):])
    return names


def test(svc_dir, image, out_dir):
    _, name, svc = load(svc_dir)
    env = read_env(os.path.join(svc_dir, ".env.example"))
    for k, v in list(env.items()):
        if k in FIXED:
            env[k] = FIXED[k]
        elif v.startswith(("postgres://", "postgresql://")) or k in ("POSTGRES_DSN", "POSTGRES_CONNECTION", "DATABASE_URL"):
            env[k] = PG_DSN
    env.update(read_env(os.path.join(svc_dir, "tests", "container.env")))  # service-specific test values
    profiles = sorted(p for p, keys in PROFILE_KEYS.items() if any(env.get(k, "").startswith(("http", "mqtt", "test-")) for k in keys))

    out = {k: svc[k] for k in TEST_KEYS if k in svc}
    out["build"] = absolute_build(svc["build"], svc_dir)
    out.update(image=image, env_file=[os.path.join(out_dir, "test.env")], restart="no",
               labels={"alice.container-test": name})
    with open(os.path.join(out_dir, "compose.json"), "w") as f:
        json.dump({"services": {name: out}}, f, indent=2)
    with open(os.path.join(out_dir, "test.env"), "w") as f:
        f.writelines(f"{k}={v}\n" for k, v in env.items())
    print(name, " ".join(profiles), " ".join(secret_targets(svc)), sep="\n")


def stage(svc_dir, image, compose_root, out_file):
    doc, name, svc = load(svc_dir)
    rel = os.path.relpath(os.path.abspath(svc_dir), os.path.abspath(os.path.join(svc_dir, "..", "..")))
    prod_dir = os.path.join(compose_root, rel)  # e.g. /srv/compose/automations/alice-lists
    staged = f"{name}-staging"

    out = {k: v for k, v in svc.items() if k not in ("container_name", "ports", "restart", "networks", "depends_on", "env_file", "labels")}
    # build stays relative: the staging file is written next to the service's compose.yml
    out.update(image=image, container_name=staged, restart="no")
    # Real .env of the production service (read by docker compose on the server, never copied).
    env_files = svc.get("env_file") or []
    env_files = [env_files] if isinstance(env_files, (str, dict)) else env_files
    out["env_file"] = [os.path.join(prod_dir, e if isinstance(e, str) else e["path"]) for e in env_files]
    out["labels"] = {"com.centurylinklabs.watchtower.enable": "false", "alice.staging": name}
    # Same networks as production, but WITHOUT aliases: otherwise the staging container
    # would answer requests meant for the production service.
    nets = svc.get("networks") or []
    nets = list(nets) if isinstance(nets, list) else list(nets.keys())
    out["networks"] = {n: {} for n in nets}
    top = {n: (doc.get("networks") or {}).get(n) or {} for n in nets}
    result = {"services": {staged: out}}
    if top:
        result["networks"] = top
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2)
    print(staged, " ".join(nets), sep="\n")


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "test" and len(args) == 3:
        test(*args)
    elif cmd == "stage" and len(args) == 4:
        stage(*args)
    else:
        sys.exit(__doc__)
