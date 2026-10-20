import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, appendFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const RUNNER = join(HERE, "..", "runner.mjs");
const FAKE = join(HERE, "fake-sdk.mjs");
const FAKE_KEY = "crsr_FAKEKEY_0123456789abcdefghijklmnopqrstuvwxyz";

function run(request, { scenario = "ok", env = {}, keyFile, node = process.execPath, onSpawn } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "sidecar-"));
  const kf = keyFile === undefined ? join(dir, "key") : keyFile;
  if (keyFile === undefined) writeFileSync(kf, FAKE_KEY + "\n");
  return new Promise((resolve) => {
    const child = spawn(node, [RUNNER, ...(kf ? ["--key-file", kf] : [])], {
      env: { PATH: process.env.PATH, HOME: dir, CURSOR_SDK_MODULE: FAKE, FAKE_SDK_SCENARIO: scenario, ...env },
    });
    let out = ""; let err = "";
    child.stdout.on("data", (d) => (out += d)); child.stderr.on("data", (d) => (err += d));
    child.on("close", (code) => {
      const lines = out.trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
      resolve({ code, lines, out, err, last: lines.at(-1), dir });
    });
    child.stdin.end(typeof request === "string" ? request : JSON.stringify({ cwd: dir, ...request }));
    onSpawn?.(child, dir);
  });
}

test("ok devuelve resultado con usage y run_id", async () => {
  const r = await run({ prompt: "respondé OK" });
  assert.equal(r.code, 0);
  assert.equal(r.last.type, "result");
  assert.equal(r.last.ok, true);
  assert.equal(r.last.text, "OK");
  assert.equal(r.last.run_id, "run-fake-1");
  assert.deepEqual(r.last.usage, { inputTokens: 11, outputTokens: 2, cacheReadTokens: 5, totalTokens: 18 });
  assert.equal(r.last.cost, null);
  assert.equal(typeof r.last.duration_ms, "number");
});

test("stream emite eventos antes del resultado", async () => {
  const r = await run({ prompt: "x", stream: true });
  assert.deepEqual(r.lines.slice(0, -1).map((l) => l.type), ["event", "event"]);
  assert.equal(r.lines[0].event, "status");
});

test("sin stream no emite eventos", async () => {
  const r = await run({ prompt: "x" });
  assert.equal(r.lines.length, 1);
});

test("getUsage con costo incluye chargedCents", async () => {
  const r = await run({ prompt: "x" }, { scenario: "usage_cost" });
  assert.deepEqual(r.last.cost, { chargedCents: 0.5 });
});

for (const [scenario, code, exit, fallback] of [
  ["auth", "AUTH_INVALID", 4, true], ["rate", "USAGE_LIMIT", 8, true], ["network", "NETWORK", 11, true],
  ["crash", "SDK_ERROR", 9, true], ["run_error", "SDK_ERROR", 9, true],
]) {
  test(`error ${scenario} → ${code} exit ${exit}`, async () => {
    const r = await run({ prompt: "x" }, { scenario });
    assert.equal(r.code, exit);
    assert.deepEqual([r.last.type, r.last.ok, r.last.code, r.last.fallback], ["error", false, code, fallback]);
  });
}

test("request inválido → BAD_REQUEST exit 2 sin fallback", async () => {
  const r = await run("{nope");
  assert.equal(r.code, 2);
  assert.deepEqual([r.last.code, r.last.fallback], ["BAD_REQUEST", false]);
});

test("sin key → NO_KEY exit 3", async () => {
  const r = await run({ prompt: "x" }, { keyFile: "" });
  assert.equal(r.code, 3);
  assert.equal(r.last.code, "NO_KEY");
});

test("key por env si no hay archivo", async () => {
  const r = await run({ prompt: "x" }, { keyFile: "", env: { CURSOR_API_KEY: FAKE_KEY } });
  assert.equal(r.code, 0);
});

test("SDK ausente → SDK_MISSING exit 6", async () => {
  const r = await run({ prompt: "x" }, { env: { CURSOR_SDK_MODULE: "/nonexistent/sdk.mjs" } });
  assert.equal(r.code, 6);
  assert.equal(r.last.code, "SDK_MISSING");
});

test("timeout corta el run → TIMEOUT exit 7", async () => {
  const r = await run({ prompt: "x", timeout_s: 0.3 }, { scenario: "slow" });
  assert.equal(r.code, 7);
  assert.equal(r.last.code, "TIMEOUT");
});

test("cancel_file cancela → CANCELLED exit 10", async () => {
  const r = await run({ prompt: "x", cancel_file: "CANCEL" }, {
    scenario: "slow",
    onSpawn: (_c, dir) => setTimeout(() => writeFileSync(join(dir, "CANCEL"), ""), 300),
  });
  assert.equal(r.code, 10);
  assert.equal(r.last.code, "CANCELLED");
});

test("SIGTERM cancela → CANCELLED", async () => {
  const r = await run({ prompt: "x" }, { scenario: "slow", onSpawn: (c) => setTimeout(() => c.kill("SIGTERM"), 300) });
  assert.equal(r.last.code, "CANCELLED");
  assert.equal(r.code, 10);
});

test("steer lee la bandeja y lo entrega al run", async () => {
  const r = await run({ prompt: "x", stream: true, steer_file: "steer.jsonl" }, {
    scenario: "steer",
    onSpawn: (_c, dir) => setTimeout(() => appendFileSync(join(dir, "steer.jsonl"), JSON.stringify({ text: "cambiá a B" }) + "\n"), 300),
  });
  assert.equal(r.code, 0);
  assert.equal(r.last.text, "OK steered:cambiá a B");
  const steer = r.lines.find((l) => l.type === "steer");
  assert.deepEqual([steer.outcome, steer.text_len], ["complete_delivered", 10]);
});

test("mcp deshabilitado por defecto", async () => {
  const r = await run({ prompt: "x" }, { env: { FAKE_SDK_SEEN_KEY_ECHO: "0" } });
  assert.equal(r.code, 0);
});

for (const scenario of ["ok", "auth", "crash", "run_error"]) {
  test(`la key nunca aparece en stdout/stderr (${scenario}, con SDK que la imprime)`, async () => {
    const r = await run({ prompt: "x", stream: true }, { scenario, env: { FAKE_SDK_SEEN_KEY_ECHO: "1" } });
    assert.ok(!r.out.includes(FAKE_KEY), "stdout filtró la key");
    assert.ok(!r.err.includes(FAKE_KEY), "stderr filtró la key");
    assert.ok(!r.out.includes("FAKEKEY"), "stdout filtró parte de la key");
  });
}

test("node viejo → NODE_TOO_OLD exit 5", { skip: !process.env.OLD_NODE }, async () => {
  const r = await run({ prompt: "x" }, { node: process.env.OLD_NODE });
  assert.equal(r.code, 5);
  assert.equal(r.last.code, "NODE_TOO_OLD");
});
