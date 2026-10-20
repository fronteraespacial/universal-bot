// Contrato v2: passthroughs de FE-BOT, fast por defecto, validación estricta, capacidades, señales tempranas,
// timeout que cubre create+send, carrera resultado/cancel, redacción con buffer, truncado, store efímero y modo serve.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const RUNNER = join(ROOT, "runner.mjs");
const LAUNCHER = join(ROOT, "bin", "cursor-sdk-sidecar");
const FAKE = join(HERE, "fake-sdk.mjs");
const FAKE_KEY = "crsr_FAKEKEY_0123456789abcdefghijklmnopqrstuvwxyz";

function setup() {
  const dir = mkdtempSync(join(tmpdir(), "sidecar2-"));
  writeFileSync(join(dir, "key"), FAKE_KEY + "\n");
  return dir;
}

function baseEnv(dir, scenario, env) {
  return { PATH: process.env.PATH, HOME: dir, CURSOR_SDK_MODULE: FAKE, FAKE_SDK_SCENARIO: scenario, CURSOR_SDK_NODE: process.execPath, ...env };
}

function once(request, { scenario = "ok", env = {}, args = [], via = "runner", onSpawn } = {}) {
  const dir = setup();
  const cmd = via === "launcher" ? LAUNCHER : process.execPath;
  const argv = via === "launcher" ? [...args, "--key-file", join(dir, "key")] : [RUNNER, ...args, "--key-file", join(dir, "key")];
  return new Promise((resolve) => {
    const child = spawn(cmd, argv, { env: baseEnv(dir, scenario, env) });
    let out = ""; let err = "";
    child.stdout.on("data", (d) => (out += d)); child.stderr.on("data", (d) => (err += d));
    child.on("close", (code) => {
      const lines = out.trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
      resolve({ code, lines, out, err, last: lines.at(-1), dir });
    });
    onSpawn?.(child, dir);
    if (request !== null) child.stdin.end(typeof request === "string" ? request : JSON.stringify({ cwd: dir, ...request }));
  });
}

const options = (r) => JSON.parse(r.last.text);

// --- 5 passthroughs (FE-BOT) + fast por defecto ---------------------------------
test("default: MCP en disallowedTools, sin settingSources y modelo fast", async () => {
  const r = await once({ prompt: "x" }, { env: { FAKE_SDK_ECHO_OPTIONS: "1" } });
  const o = options(r);
  assert.deepEqual(o.disallowedTools, ["mcp"]);
  assert.equal(o.settingSources, null);
  assert.deepEqual(o.mcpServers, []);
  assert.deepEqual(o.model, { id: "composer-2.5", params: [{ id: "fast", value: "true" }] });
});

test("composer-2.5-fast es composer-2.5 + fast=true; model_params explícito manda", async () => {
  const fast = options(await once({ prompt: "x", model: "composer-2.5-fast" }, { env: { FAKE_SDK_ECHO_OPTIONS: "1" } }));
  assert.deepEqual(fast.model, { id: "composer-2.5", params: [{ id: "fast", value: "true" }] });
  const slow = options(await once({ prompt: "x", model_params: [{ id: "fast", value: "false" }] }, { env: { FAKE_SDK_ECHO_OPTIONS: "1" } }));
  assert.deepEqual(slow.model, { id: "composer-2.5", params: [{ id: "fast", value: "false" }] });
});

test("mcp:true + mcp_servers + setting_sources + model_params + http1 pasan al SDK", async () => {
  const r = await once({ prompt: "x", mcp: true, mcp_servers: { "fe-bot-pack": { command: "/bin/true" } },
    setting_sources: ["user", "project"], model_params: [{ id: "fast", value: "true" }], http1: true },
  { env: { FAKE_SDK_ECHO_OPTIONS: "1" } });
  assert.equal(r.code, 0);
  const o = options(r);
  assert.equal(o.disallowedTools, null);
  assert.deepEqual(o.mcpServers, ["fe-bot-pack"]);
  assert.deepEqual(o.settingSources, ["user", "project"]);
  assert.deepEqual(o.configure, [{ local: { useHttp1ForAgent: true } }]);
});

test("mcp_servers sin mcp:true no se pasan", async () => {
  const o = options(await once({ prompt: "x", mcp_servers: { a: { command: "/bin/true" } } }, { env: { FAKE_SDK_ECHO_OPTIONS: "1" } }));
  assert.deepEqual(o.mcpServers, []);
  assert.deepEqual(o.disallowedTools, ["mcp"]);
});

test("passthroughs con tipo inválido → BAD_REQUEST", async () => {
  for (const bad of [{ mcp: "si" }, { mcp_servers: [] }, { setting_sources: "user" }, { model_params: {} }, { http1: 1 }]) {
    const r = await once({ prompt: "x", ...bad });
    assert.equal(r.last.code, "BAD_REQUEST", JSON.stringify(bad));
  }
});

// --- validación estricta y capacidades -------------------------------------------
test("campo desconocido → BAD_REQUEST que lo nombra", async () => {
  const r = await once({ prompt: "x", promt: "typo" });
  assert.equal(r.code, 2);
  assert.equal(r.last.code, "BAD_REQUEST");
  assert.match(r.last.message, /promt/);
});

test("--capabilities y --version describen el contrato sin leer stdin", async () => {
  const caps = await once(null, { args: ["--capabilities"] });
  assert.equal(caps.code, 0);
  assert.equal(caps.last.type, "capabilities");
  assert.equal(caps.last.protocol, 2);
  for (const f of ["mcp", "mcp_servers", "setting_sources", "model_params", "http1", "session_id", "store"]) assert.ok(caps.last.fields.includes(f), f);
  assert.deepEqual(caps.last.modes, ["oneshot", "serve"]);
  assert.ok(caps.last.ops.includes("steer") && caps.last.ops.includes("cancel"));
  const ver = await once(null, { args: ["--version"] });
  assert.equal(ver.last.version, caps.last.version);
});

// --- launcher sin $HOME, señal temprana ------------------------------------------
test("el launcher no depende de $HOME", async () => {
  const dir = setup();
  const r = await new Promise((resolve) => {
    const env = baseEnv(dir, "ok", {});
    delete env.HOME;
    const child = spawn(LAUNCHER, ["--capabilities"], { env });
    let out = ""; child.stdout.on("data", (d) => (out += d));
    child.on("close", (code) => resolve({ code, out }));
  });
  assert.equal(r.code, 0);
  assert.match(r.out, /"capabilities"/);
});

test("SIGTERM apenas arranca igual deja una línea final", async () => {
  const r = await once(null, { via: "launcher", scenario: "slow", onSpawn: (c) => c.kill("SIGTERM") });
  assert.equal(r.last.type, "error");
  assert.equal(r.last.code, "CANCELLED");
  assert.equal(r.code, 10);
});

// --- timeout y carrera -----------------------------------------------------------
test("timeout_s cubre create+send", async () => {
  const started = Date.now();
  const r = await once({ prompt: "x", timeout_s: 0.4 }, { scenario: "slow_create" });
  assert.equal(r.last.code, "TIMEOUT");
  assert.ok(Date.now() - started < 1400, "no espera a que termine el create");
});

test("si el run ya terminó, el resultado le gana al cancel", async () => {
  const r = await once({ prompt: "x", cancel_file: "CANCEL" }, {
    scenario: "finish_on_cancel",
    onSpawn: (_c, dir) => setTimeout(() => writeFileSync(join(dir, "CANCEL"), ""), 300),
  });
  assert.equal(r.last.type, "result");
  assert.equal(r.code, 0);
});

// --- redacción con buffer, truncado --------------------------------------------------
test("una key partida entre dos writes no se escapa", async () => {
  const r = await once({ prompt: "x" }, { scenario: "split_key" });
  assert.ok(!r.err.includes(FAKE_KEY));
  assert.ok(!r.err.includes(FAKE_KEY.slice(10)), "la segunda mitad tampoco");
  assert.match(r.err, /<redacted>/);
});

test("eventos y resultados grandes se truncan", async () => {
  const r = await once({ prompt: "x", stream: true, max_event_bytes: 2000, max_result_chars: 5000 }, { scenario: "big" });
  const big = r.lines.find((l) => l.type === "event" && l.truncated);
  assert.ok(big && JSON.stringify(big).length < 4000);
  assert.equal(r.last.text.length, 5000);
  assert.equal(r.last.text_truncated, true);
  assert.equal(r.last.text_len, 300000);
});

// --- store de agentes ------------------------------------------------------------
test("store efímero por defecto: JSONL en un dir temporal que se borra al terminar", async () => {
  const r = await once({ prompt: "x" }, { env: { FAKE_SDK_ECHO_OPTIONS: "1" } });
  const o = options(r);
  assert.equal(o.store.kind, "jsonl");
  assert.equal(existsSync(o.store.rootDir), false);
  const keep = options(await once({ prompt: "x", store: "default" }, { env: { FAKE_SDK_ECHO_OPTIONS: "1" } }));
  assert.equal(keep.store, null);
});

// --- modo serve (larga vida) -------------------------------------------------------
function serve({ scenario = "ok", env = {} } = {}) {
  const dir = setup();
  const child = spawn(process.execPath, [RUNNER, "--serve", "--key-file", join(dir, "key")], { env: baseEnv(dir, scenario, env) });
  const lines = [];
  const waiters = [];
  createInterface({ input: child.stdout }).on("line", (line) => {
    const msg = JSON.parse(line);
    lines.push(msg);
    for (const w of [...waiters]) if (w.match(msg)) { waiters.splice(waiters.indexOf(w), 1); w.resolve(msg); }
  });
  let err = ""; child.stderr.on("data", (d) => (err += d));
  const closed = new Promise((resolve) => child.on("close", (code) => resolve(code)));
  return {
    dir, child, lines, closed, err: () => err,
    send: (obj) => child.stdin.write(JSON.stringify({ cwd: dir, ...obj }) + "\n"),
    raw: (text) => child.stdin.write(text + "\n"),
    wait: (match, ms = 5000) => {
      const found = lines.find(match);
      if (found) return Promise.resolve(found);
      return new Promise((resolve, reject) => {
        const w = { match, resolve };
        waiters.push(w);
        setTimeout(() => reject(new Error("timeout esperando línea")), ms);
      });
    },
  };
}

const final = (id) => (m) => m.id === id && (m.type === "result" || m.type === "error");

test("serve: varios requests, un solo proceso, agente reutilizado por session_id", async () => {
  const s = serve({ env: { FAKE_SDK_ECHO_OPTIONS: "1" } });
  s.send({ op: "run", id: "r1", session_id: "s1", prompt: "uno" });
  const one = await s.wait(final("r1"));
  s.send({ op: "run", id: "r2", session_id: "s1", prompt: "dos" });
  const two = await s.wait(final("r2"));
  s.send({ op: "run", id: "r3", prompt: "suelto" });
  const three = await s.wait(final("r3"));
  assert.equal(one.session_id, "s1");
  assert.equal(one.agent_id, two.agent_id, "mismo agente");
  assert.equal(JSON.parse(two.text).sends, 2);
  assert.equal(JSON.parse(two.text).creates, 1);
  assert.notEqual(three.agent_id, one.agent_id);
  s.child.stdin.end();
  assert.equal(await s.closed, 0);
});

test("serve: steer y cancel por request", async () => {
  const s = serve({ scenario: "ok" });
  s.send({ op: "run", id: "a", session_id: "s", prompt: "SLOW contá" });
  await new Promise((r) => setTimeout(r, 200));
  s.send({ op: "steer", id: "st", target: "a", text: "pará" });
  const ack = await s.wait((m) => m.id === "st");
  assert.equal(ack.ok, true);
  const done = await s.wait(final("a"));
  assert.equal(done.text, "OK steered:pará");
  s.send({ op: "run", id: "b", session_id: "s", prompt: "SLOW otra" });
  await new Promise((r) => setTimeout(r, 200));
  s.send({ op: "cancel", id: "c", target: "b" });
  const cancelled = await s.wait(final("b"));
  assert.equal(cancelled.code, "CANCELLED");
  s.send({ op: "close", id: "x", session_id: "s" });
  assert.equal((await s.wait((m) => m.id === "x")).ok, true);
  s.child.stdin.end();
  await s.closed;
});

test("serve: request inválido no tumba el proceso y una sesión ocupada responde BUSY", async () => {
  const s = serve();
  s.raw("{nope");
  const bad = await s.wait((m) => m.type === "error" && m.code === "BAD_REQUEST");
  assert.equal(bad.id, null);
  s.send({ op: "run", id: "a", session_id: "s", prompt: "SLOW" });
  s.send({ op: "run", id: "b", session_id: "s", prompt: "otra" });
  const busy = await s.wait(final("b"));
  assert.equal(busy.code, "BUSY");
  s.send({ op: "ping", id: "p" });
  const pong = await s.wait((m) => m.id === "p");
  assert.equal(pong.type, "pong");
  assert.deepEqual(pong.running, ["a"]);
  s.child.kill("SIGTERM");
  await s.wait(final("a"));
  assert.equal(s.lines.find(final("a")).code, "CANCELLED", "SIGTERM corta los runs vivos con línea final");
  await s.closed;
});
