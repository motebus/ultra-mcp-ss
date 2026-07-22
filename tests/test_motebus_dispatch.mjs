import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeError,
  dispatchSmartScreen,
  resolveProfile,
  resolveRuntimeConfig,
  validateCommandEnvelope,
  validateMapReply,
} from "../app/mcp_ss/motebus_dispatch.mjs";


function env(tier = "dev") {
  return {
    MCHAT_APPNAME: "mcp-ss",
    MCHAT_EINAME: "mcp-ss",
    MCHAT_DC: "dc",
    MCHAT_IOC: "ioc",
    MCHAT_MBGWIP: "motebus:6262",
    MCHAT_WATCHLEVEL: "1",
    ULTRA_MCP_SS_MAP_TIER: tier,
  };
}


function mapReply(profile, targetMma) {
  return {
    ErrCode: 0,
    ErrMsg: "OK",
    State: "Reply",
    Result: {
      ErrCode: 0,
      ErrMsg: "OK",
      result: {
        ok: true,
        topic: profile.mapTopic,
        op: "sys.map.resolve",
        alias: profile.targetAlias,
        value: targetMma,
        map: {
          name: profile.mapName,
          authority: profile.mapName,
          rootmap: "ultra-map",
          map_tier: profile.tier,
          served_by: "ultra-comm",
          served_by_mma: profile.mapMma,
          available: true,
          used_seed: false,
          revision: "revision-1",
          source_evidence: "git://ultra-comm@revision-1/map.yaml",
        },
      },
    },
  };
}


function fakeRuntime(profile) {
  const requests = [];
  const runtime = {
    Open(_conf, _reginfo, callback) {
      callback({ ErrCode: 0, ErrMsg: "OK", result: { SToken: "session" } });
    },
    mbSend(request, callback) {
      requests.push(request);
      if (requests.length === 1) {
        callback(mapReply(profile, `${profile.targetSite}/ss/ss-srv-app`));
        return;
      }
      callback({
        ErrCode: 0,
        ErrMsg: "OK",
        State: "Reply",
        Result: {
          ErrCode: 0,
          ErrMsg: "OK",
          result: { accepted: true, screen: request.Data.to.name },
        },
      });
    },
  };
  return { loaded: { name: "motechat", runtime }, requests };
}


test("profile selection keeps lab and PD maps separate", () => {
  assert.equal(resolveProfile("dev").mapMma, "u22/comm/comm-app");
  assert.equal(resolveProfile("dev").targetAlias, "ultra_ss_app_lab_mma");
  assert.equal(resolveProfile("R").targetAlias, "ultra_ss_app_mma");
  assert.equal(resolveProfile("P").mapMma, "j22/comm/comm-app");
  assert.equal(resolveProfile("P").targetAlias, "ultra_ss_app_mma");
  assert.throws(() => resolveProfile("pd"), BridgeError);
});


test("native command stays a reserved-field-free SmartScreen envelope", () => {
  assert.deepEqual(
    validateCommandEnvelope({
      to: { name: "home" },
      data: { cmd: "notify", msg: "hello" },
    }),
    {
      to: { name: "home" },
      data: { cmd: "notify", msg: "hello" },
    },
  );
});


test("MCHAT_WATCHLEVEL accepts the policy-valid zero value", () => {
  const config = resolveRuntimeConfig({ ...env(), MCHAT_WATCHLEVEL: "0" });
  assert.equal(config.conf.WatchLevel, 0);
  assert.equal(config.conf.AppName, "mcp-ss");
  assert.equal(config.conf.AppKey, "ultra-mcp-ss-bridge");
  assert.throws(
    () => resolveRuntimeConfig({ ...env(), MCHAT_WATCHLEVEL: "-1" }),
    (error) => error instanceof BridgeError && error.code === "motebus_config_invalid",
  );
});


test("map validation rejects another tier's SmartScreen owner", () => {
  const profile = resolveProfile("dev");
  assert.throws(
    () => validateMapReply(mapReply(profile, "j22/ss/ss-srv-app"), profile),
    (error) => error instanceof BridgeError && error.code === "map_target_invalid",
  );
});


test("dispatch resolves UltraMap then sends only native ss://mms xmsg", async () => {
  const profile = resolveProfile("dev");
  const fake = fakeRuntime(profile);
  const result = await dispatchSmartScreen(
    { to: { name: "home" }, data: { cmd: "notify", msg: "hello" } },
    { env: env("dev"), loaded: fake.loaded },
  );

  assert.equal(result.ok, true);
  assert.deepEqual(result.result, { accepted: true, screen: "home" });
  assert.equal(fake.requests.length, 2);
  assert.deepEqual(
    {
      MMA: fake.requests[0].MMA,
      Topic: fake.requests[0].Topic,
      Data: fake.requests[0].Data,
    },
    {
      MMA: "u22/comm/comm-app",
      Topic: "map://ultra-map-dev",
      Data: {
        __topic: "map://ultra-map-dev",
        op: "sys.map.resolve",
        key: "ultra_ss_app_lab_mma",
      },
    },
  );
  assert.equal(fake.requests[1].MMA, "u22/ss/ss-srv-app");
  assert.equal(fake.requests[1].Topic, "ss://mms");
  assert.deepEqual(fake.requests[1].Data, {
    __topic: "ss://mms",
    to: { name: "home" },
    data: { cmd: "notify", msg: "hello" },
  });
  assert.equal(result.meta.downstream.fallback, "none");
});
