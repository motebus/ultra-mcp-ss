#!/usr/bin/env node

import { createRequire } from "node:module";
import { readFileSync, realpathSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";


const RESULT_PREFIX = "@@ULTRA_MCP_SS_RESULT@@";
const SS_TOPIC = "ss://mms";
const OPEN_TIMEOUT_MS = 30_000;
const OPEN_CALLBACK_TIMEOUT_MS = 5_000;

const PROFILES = Object.freeze({
  dev: Object.freeze({
    tier: "dev",
    mapName: "ultra-map-dev",
    mapTopic: "map://ultra-map-dev",
    mapMma: "u22/comm/comm-app",
    targetAlias: "ultra_ss_app_lab_mma",
    targetSite: "u22",
  }),
  R: Object.freeze({
    tier: "R",
    mapName: "ultra-map-r",
    mapTopic: "map://ultra-map-r",
    mapMma: "u22/comm/comm-app",
    targetAlias: "ultra_ss_app_mma",
    targetSite: "u22",
  }),
  P: Object.freeze({
    tier: "P",
    mapName: "ultra-map-p",
    mapTopic: "map://ultra-map-p",
    mapMma: "j22/comm/comm-app",
    targetAlias: "ultra_ss_app_mma",
    targetSite: "j22",
  }),
});


class BridgeError extends Error {
  constructor(code, detail, meta = {}) {
    super(detail);
    this.name = "BridgeError";
    this.code = code;
    this.meta = meta;
  }
}


function clean(value) {
  return String(value == null ? "" : value).trim();
}


function positiveInteger(value, fallback, label) {
  const text = clean(value);
  if (!text && fallback != null) return fallback;
  const number = Number(text);
  if (!Number.isInteger(number) || number <= 0) {
    throw new BridgeError("motebus_config_invalid", `${label} must be a positive integer`);
  }
  return number;
}


function nonNegativeInteger(value, fallback, label) {
  const text = clean(value);
  if (!text && fallback != null) return fallback;
  const number = Number(text);
  if (!Number.isInteger(number) || number < 0) {
    throw new BridgeError("motebus_config_invalid", `${label} must be a non-negative integer`);
  }
  return number;
}


function resolveProfile(value) {
  const tier = clean(value);
  const profile = PROFILES[tier];
  if (!profile) {
    throw new BridgeError(
      "motebus_config_invalid",
      "ULTRA_MCP_SS_MAP_TIER must be one of dev, R, or P",
    );
  }
  return profile;
}


function resolveRuntimeConfig(env = process.env) {
  if (clean(env.MCHAT_MMA)) {
    throw new BridgeError(
      "motebus_config_invalid",
      "MCHAT_MMA is forbidden; the live session owns its resolved MMA identity",
    );
  }
  const required = [
    "MCHAT_APPNAME",
    "MCHAT_DC",
    "MCHAT_IOC",
    "MCHAT_MBGWIP",
    "MCHAT_WATCHLEVEL",
  ];
  const missing = required.filter((name) => !clean(env[name]));
  if (missing.length > 0) {
    throw new BridgeError(
      "motebus_config_missing",
      `Missing runtime configuration: ${missing.join(", ")}`,
    );
  }

  const profile = resolveProfile(env.ULTRA_MCP_SS_MAP_TIER);
  const appName = clean(env.MCHAT_APPNAME);
  return {
    profile,
    sendTimeout: positiveInteger(env.ULTRA_MCP_SS_SEND_TIMEOUT, 6, "ULTRA_MCP_SS_SEND_TIMEOUT"),
    waitReply: positiveInteger(env.ULTRA_MCP_SS_WAIT_REPLY, 20, "ULTRA_MCP_SS_WAIT_REPLY"),
    conf: {
      AppName: appName,
      AppKey: "ultra-mcp-ss-bridge",
      DCenter: clean(env.MCHAT_DC),
      IOC: clean(env.MCHAT_IOC),
      MotebusGW: clean(env.MCHAT_MBGWIP),
      WatchLevel: nonNegativeInteger(env.MCHAT_WATCHLEVEL, null, "MCHAT_WATCHLEVEL"),
      UseWeb: "none",
    },
    reginfo: {
      EiToken: "",
      SToken: "",
      WIP: "",
      LIP: "",
      EdgeInfo: {
        EiName: clean(env.MCHAT_EINAME) || appName,
        EiType: ".mcp",
        EiTag: "",
        EiLoc: "",
      },
      Option: { SaveDSIM: false },
    },
  };
}


function validateCommandEnvelope(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new BridgeError("invalid_payload", "SmartScreen payload must be an object");
  }
  if (!value.to || typeof value.to !== "object" || Array.isArray(value.to)) {
    throw new BridgeError("invalid_payload", "payload.to must be an object");
  }
  if (!clean(value.to.name) && !clean(value.to.ddn) && !clean(value.to.mma)) {
    throw new BridgeError("invalid_payload", "payload.to requires name, ddn, or mma");
  }
  if (!value.data || typeof value.data !== "object" || Array.isArray(value.data)) {
    throw new BridgeError("invalid_payload", "payload.data must be an object");
  }
  if (!clean(value.data.cmd)) {
    throw new BridgeError("invalid_payload", "payload.data.cmd is required");
  }
  return {
    to: value.to,
    data: value.data,
  };
}


function loadMotechat() {
  const require = createRequire(import.meta.url);
  const failures = [];
  for (const name of ["@motechat/node", "motechat"]) {
    try {
      return { name, runtime: require(name) };
    } catch (error) {
      failures.push(`${name}: ${error.message}`);
    }
  }
  throw new BridgeError(
    "motebus_runtime_unavailable",
    `Cannot load a native MoteChat runtime (${failures.join("; ")})`,
  );
}


function callbackResult(run, timeoutMs, label) {
  return new Promise((resolveReply, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new BridgeError("motebus_timeout", `${label} timed out`));
    }, timeoutMs);
    const finish = (reply) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolveReply(reply);
    };
    try {
      const immediate = run(finish);
      if (immediate && typeof immediate.then === "function") {
        immediate.then(finish).catch((error) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          reject(error);
        });
      } else if (
        immediate &&
        typeof immediate === "object" &&
        Object.prototype.hasOwnProperty.call(immediate, "ErrCode")
      ) {
        finish(immediate);
      }
    } catch (error) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    }
  });
}


function replyCode(value) {
  return value && typeof value === "object" && Number.isFinite(value.ErrCode)
    ? Number(value.ErrCode)
    : 0;
}


function replyMessage(value, fallback) {
  return clean(value && value.ErrMsg) || fallback;
}


function assertReplyOk(reply, label, meta = {}) {
  const rows = Array.isArray(reply) ? reply : [reply];
  if (rows.length === 0) {
    throw new BridgeError("motebus_empty_reply", `${label} returned no reply`, meta);
  }
  for (const row of rows) {
    const candidates = [
      row,
      row && row.IN && row.IN.State,
      row && row.Reply,
      row && row.Result,
      row && row.result,
      row && row.Result && row.Result.result,
      row && row.result && row.result.result,
    ];
    for (const candidate of candidates) {
      const code = replyCode(candidate);
      if (code !== 0) {
        throw new BridgeError(
          "motebus_owner_error",
          `${label} failed: ${replyMessage(candidate, `ErrCode ${code}`)}`,
          { ...meta, owner_error_code: code },
        );
      }
    }
  }
  return rows[0];
}


function mapPayloadFromReply(reply) {
  const row = Array.isArray(reply) ? reply[0] : reply;
  const candidates = [
    row && row.Result && row.Result.result,
    row && row.result && row.result.result,
    row && row.Reply && row.Reply.result,
    row && row.Result,
    row && row.result,
    row && row.Reply,
    row,
  ];
  return candidates.find((candidate) => candidate && candidate.ok === true) || null;
}


function validateMapReply(reply, profile) {
  const route = {
    rootmap: "ultra-map",
    concrete_map: profile.mapName,
    map_mma: profile.mapMma,
    map_topic: profile.mapTopic,
    alias: profile.targetAlias,
  };
  assertReplyOk(reply, "UltraMap resolve", { map: route });
  const payload = mapPayloadFromReply(reply);
  if (!payload) {
    throw new BridgeError("map_invalid_reply", "UltraMap reply did not contain a successful result", { map: route });
  }
  const map = payload.map && typeof payload.map === "object" ? payload.map : {};
  const invariants = [
    [payload.topic === profile.mapTopic, "topic"],
    [payload.op === "sys.map.resolve", "operation"],
    [payload.alias === profile.targetAlias, "alias"],
    [map.name === profile.mapName, "map name"],
    [map.authority === profile.mapName, "map authority"],
    [map.rootmap === "ultra-map", "rootmap"],
    [clean(map.map_tier) === profile.tier, "map tier"],
    [map.served_by === "ultra-comm", "serving owner"],
    [map.served_by_mma === profile.mapMma, "serving MMA"],
    [map.available === true, "source availability"],
    [map.used_seed === false, "live source"],
  ];
  const failed = invariants.find(([ok]) => !ok);
  if (failed) {
    throw new BridgeError(
      "map_invariant_failed",
      `UltraMap ${failed[1]} invariant failed`,
      { map: route },
    );
  }

  const targetMma = clean(payload.value).replace(/^>+/, "").split(";")[0];
  const expected = `${profile.targetSite}/ss/ss-srv-app`;
  if (targetMma !== expected) {
    throw new BridgeError(
      "map_target_invalid",
      `UltraMap ${profile.targetAlias} must resolve to ${expected}`,
      { map: route, resolved_mma: targetMma || null },
    );
  }
  return {
    targetMma,
    map: {
      rootmap: "ultra-map",
      name: map.name,
      revision: clean(map.revision),
      source_evidence: clean(map.source_evidence),
      served_by: map.served_by,
      served_by_mma: map.served_by_mma,
      used_seed: map.used_seed,
      alias: payload.alias,
    },
  };
}


function dispatchPayloadFromReply(reply) {
  const row = Array.isArray(reply) ? reply[0] : reply;
  const candidates = [
    row && row.Reply,
    row && row.Result && row.Result.result,
    row && row.result && row.result.result,
    row && row.Result,
    row && row.result,
    row,
  ];
  return candidates.find((candidate) => candidate && typeof candidate === "object") || null;
}


function sendXmsg(loaded, request, timeoutMs, label, meta) {
  if (!loaded.runtime || typeof loaded.runtime.mbSend !== "function") {
    throw new BridgeError("motebus_runtime_unavailable", "MoteChat runtime does not expose mbSend", meta);
  }
  return callbackResult(
    (finish) => loaded.runtime.mbSend(request, finish),
    timeoutMs,
    label,
  );
}


async function waitForMbusReady(runtime, timeoutMs) {
  if (!runtime || typeof runtime.getMbusInfo !== "function") return null;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() <= deadline) {
    const info = runtime.getMbusInfo();
    if (info && (info.mma || info.busName || info.localIP || info.wanIP)) return info;
    await new Promise((resolveSleep) => setTimeout(resolveSleep, 250));
  }
  return null;
}


async function openMotechat(loaded, config) {
  const { runtime } = loaded;
  if (!runtime || typeof runtime.Open !== "function") {
    throw new BridgeError("motebus_runtime_unavailable", "MoteChat runtime does not expose Open");
  }
  const openWithRegInfo = loaded.name === "motechat" && Number(runtime.Open.length || 0) >= 3;
  let openReply;
  try {
    openReply = await callbackResult(
      (finish) => openWithRegInfo
        ? runtime.Open(config.conf, config.reginfo, finish)
        : runtime.Open(config.conf, finish),
      OPEN_CALLBACK_TIMEOUT_MS,
      "MoteChat open",
    );
  } catch (error) {
    const ready = await waitForMbusReady(runtime, OPEN_TIMEOUT_MS - OPEN_CALLBACK_TIMEOUT_MS);
    if (!ready) throw error;
    openReply = { ErrCode: 0, ErrMsg: "OK", result: { mbusInfo: ready } };
  }
  assertReplyOk(openReply, "MoteChat open");

  const openResult = openReply && (openReply.result || openReply.Result || openReply);
  if (clean(openResult && openResult.SToken)) return openReply;
  if (typeof runtime.Reg !== "function") {
    throw new BridgeError("motebus_registration_failed", "MoteChat runtime did not return SToken and does not expose Reg");
  }
  const registerReply = await callbackResult(
    (finish) => runtime.Reg(config.reginfo, finish),
    OPEN_TIMEOUT_MS,
    "MoteChat registration",
  );
  assertReplyOk(registerReply, "MoteChat registration");
  return registerReply;
}


async function dispatchSmartScreen(input, options = {}) {
  const config = resolveRuntimeConfig(options.env || process.env);
  const command = validateCommandEnvelope(input);
  const loaded = options.loaded || loadMotechat();
  await openMotechat(loaded, config);

  const profile = config.profile;
  const mapRequest = {
    MMA: profile.mapMma,
    Topic: profile.mapTopic,
    Data: {
      __topic: profile.mapTopic,
      op: "sys.map.resolve",
      key: profile.targetAlias,
    },
    SendTimeout: config.sendTimeout,
    WaitReply: config.waitReply,
  };
  const operationTimeoutMs = (config.sendTimeout + config.waitReply + 1) * 1000;
  const mapReply = await sendXmsg(
    loaded,
    mapRequest,
    operationTimeoutMs,
    "UltraMap resolve",
    { map_mma: profile.mapMma, map_topic: profile.mapTopic },
  );
  const resolved = validateMapReply(mapReply, profile);

  const downstream = {
    transport: "motebus",
    protocol: "mms",
    command: "xmsg",
    dialect: "native-api",
    contract: "device-command",
    mma: resolved.targetMma,
    topic: SS_TOPIC,
    type: "send",
    fallback: "none",
  };
  const dispatchReply = await sendXmsg(
    loaded,
    {
      MMA: resolved.targetMma,
      Topic: SS_TOPIC,
      Data: {
        __topic: SS_TOPIC,
        ...command,
      },
      SendTimeout: config.sendTimeout,
      WaitReply: config.waitReply,
    },
    operationTimeoutMs,
    "SmartScreen owner dispatch",
    { map: resolved.map, downstream },
  );
  const firstReply = assertReplyOk(
    dispatchReply,
    "SmartScreen owner dispatch",
    { map: resolved.map, downstream },
  );
  const domainReply = dispatchPayloadFromReply(firstReply);

  return {
    ok: true,
    result: domainReply,
    meta: {
      provider: "ss",
      ingress: {
        transport: "http",
        dialect: "mcp-api",
        contract: "tool-call",
      },
      map: resolved.map,
      downstream: {
        ...downstream,
        delivery_state: clean(firstReply && firstReply.State) || "reply",
      },
    },
  };
}


function writeResult(value) {
  process.stdout.write(`${RESULT_PREFIX}${JSON.stringify(value)}\n`);
}


async function main() {
  try {
    const text = readFileSync(0, "utf8");
    const input = JSON.parse(text || "{}");
    writeResult(await dispatchSmartScreen(input));
    process.exit(0);
  } catch (error) {
    const bridgeError = error instanceof BridgeError
      ? error
      : new BridgeError("motebus_dispatch_failed", clean(error && error.message) || String(error));
    writeResult({
      ok: false,
      error: {
        code: bridgeError.code,
        detail: bridgeError.message,
      },
      meta: bridgeError.meta,
    });
    process.exit(1);
  }
}


const invokedPath = process.argv[1] ? realpathSync(resolve(process.argv[1])) : "";
if (invokedPath === fileURLToPath(import.meta.url)) {
  main();
}


export {
  BridgeError,
  PROFILES,
  RESULT_PREFIX,
  SS_TOPIC,
  dispatchSmartScreen,
  resolveProfile,
  resolveRuntimeConfig,
  validateCommandEnvelope,
  validateMapReply,
};
