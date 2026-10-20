import { test } from "node:test";
import assert from "node:assert/strict";
import { parseRequest, classifyError, checkNodeVersion, makeRedactor, EXIT, FALLBACK_CODES } from "../lib/protocol.mjs";

test("request mínimo aplica defaults", () => {
  assert.deepEqual(parseRequest('{"prompt":"hola"}', "/w"), {
    prompt: "hola", system: null, model: "composer-2.5", cwd: "/w", timeout_s: 120, stream: false,
    steer_file: null, cancel_file: null, tools: null,
    mcp: false, mcp_servers: null, setting_sources: null, model_params: [{ id: "fast", value: "true" }], http1: false,
    session_id: null, store: "ephemeral", store_dir: null, max_event_bytes: 65536, max_result_chars: 200000,
  });
});

for (const [raw, why] of [
  ["", "vacío"], ["no json", "json inválido"], ["[]", "no objeto"], ['{"prompt":""}', "prompt vacío"],
  ['{"prompt":"x","timeout_s":0}', "timeout 0"], ['{"prompt":"x","timeout_s":"10"}', "timeout string"],
  ['{"prompt":"x","stream":"yes"}', "stream no bool"], ['{"prompt":"x","model":""}', "modelo vacío"],
]) {
  test(`request inválido: ${why}`, () => {
    assert.throws(() => parseRequest(raw, "/w"), (e) => e.code === "BAD_REQUEST");
  });
}

for (const [version, ok] of [["22.13.0", true], ["24.5.0", true], ["23.0.0", true], ["22.12.9", false], ["20.19.2", false], ["v22.13.1", true]]) {
  test(`node ${version} → ${ok ? "ok" : "NODE_TOO_OLD"}`, () => assert.equal(checkNodeVersion(version), ok));
}

for (const [err, code] of [
  [Object.assign(new Error("x"), { name: "AuthenticationError" }), "AUTH_INVALID"],
  [new Error("401 Unauthorized"), "AUTH_INVALID"],
  [Object.assign(new Error("x"), { name: "RateLimitError" }), "USAGE_LIMIT"],
  [new Error("You've hit your usage limit"), "USAGE_LIMIT"],
  [new Error("429 too many requests"), "USAGE_LIMIT"],
  [Object.assign(new Error("x"), { name: "NetworkError" }), "NETWORK"],
  [new Error("algo raro"), "SDK_ERROR"],
]) {
  test(`clasifica ${err.name}:${err.message} → ${code}`, () => assert.equal(classifyError(err), code));
}

test("exit codes estables y fallback", () => {
  assert.deepEqual(EXIT, { BUSY: 12, OK: 0, BAD_REQUEST: 2, NO_KEY: 3, AUTH_INVALID: 4, NODE_TOO_OLD: 5, SDK_MISSING: 6,
    TIMEOUT: 7, USAGE_LIMIT: 8, SDK_ERROR: 9, CANCELLED: 10, NETWORK: 11 });
  assert.deepEqual([...FALLBACK_CODES].sort(), ["AUTH_INVALID", "NETWORK", "NODE_TOO_OLD", "NO_KEY", "SDK_ERROR", "SDK_MISSING", "TIMEOUT", "USAGE_LIMIT"]);
});

test("el redactor borra la key y sus apariciones", () => {
  const red = makeRedactor("crsr_abcdefghijklmnopqrstuvwxyz0123456789");
  assert.equal(red("x crsr_abcdefghijklmnopqrstuvwxyz0123456789 y"), "x <redacted> y");
  assert.equal(makeRedactor("")("nada"), "nada");
});
