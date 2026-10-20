import { existsSync, mkdtempSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  EXIT, FALLBACK_CODES, SidecarError, VERSION, capabilities, classifyError, makeStreamRedactor, parseRequest,
  parseServeLine, publicUsage, truncateEvent, truncateText,
} from "./protocol.mjs";
import { readKey, resolveKeyFile } from "./key.mjs";
import { steerReader } from "./inbox.mjs";

const POLL_MS = 200;
const USAGE_TIMEOUT_MS = 3000;
const HERE = dirname(fileURLToPath(import.meta.url));

// --- salida -------------------------------------------------------------------
const guards = [];
let writeLine = (text) => process.stdout.write(text);

/**
 * Redacción con buffer en stdout y stderr. stdout queda reservado para el JSONL del sidecar:
 * cualquier otra escritura a process.stdout (logs del SDK, console.log) se desvía a stderr.
 */
function guardOutput(secret) {
  const rawOut = process.stdout.write.bind(process.stdout);
  const rawErr = process.stderr.write.bind(process.stderr);
  const out = makeStreamRedactor(secret, (text) => rawOut(text));
  const err = makeStreamRedactor(secret, (text) => rawErr(text));
  guards.push(out, err);
  const wrap = (guard) => (chunk, encoding, callback) => {
    guard.write(typeof chunk === "string" ? chunk : Buffer.from(chunk).toString("utf8"));
    const done = typeof encoding === "function" ? encoding : callback;
    if (typeof done === "function") done();
    return true;
  };
  writeLine = (text) => out.write(text);
  process.stdout.write = wrap(err);
  process.stderr.write = wrap(err);
}

function flushOutput() {
  for (const guard of guards) guard.flush();
}

function emit(line) {
  writeLine(JSON.stringify(line) + "\n");
}

function errorLine(code, message, extra = {}) {
  return { ...extra, type: "error", ok: false, code, message, fallback: FALLBACK_CODES.has(code), exit_code: EXIT[code] };
}

// --- SDK ----------------------------------------------------------------------
async function loadSdk(env) {
  const target = env.CURSOR_SDK_MODULE;
  try {
    return target ? await import(pathToFileURL(target).href) : await import("@cursor/sdk");
  } catch {
    throw new SidecarError("SDK_MISSING", "no se pudo cargar @cursor/sdk");
  }
}

function sdkVersion() {
  try {
    return JSON.parse(readFileSync(join(HERE, "..", "node_modules", "@cursor", "sdk", "package.json"), "utf8")).version;
  } catch {
    return null;
  }
}

function resolveIn(cwd, path) {
  if (!path) return null;
  return isAbsolute(path) ? path : join(cwd, path);
}

function modelSelection(request) {
  return request.model_params ? { id: request.model, params: request.model_params } : { id: request.model };
}

/** Opciones del agente. Passthroughs FE-BOT: mcp / mcp_servers → mcpServers, setting_sources → settingSources. */
function agentOptions(request, apiKey, store) {
  const options = { apiKey, model: modelSelection(request), local: { cwd: request.cwd } };
  if (!request.mcp) options.disallowedTools = ["mcp"];
  if (request.mcp && request.mcp_servers) options.mcpServers = request.mcp_servers;
  if (request.setting_sources) options.local.settingSources = request.setting_sources;
  if (store) options.local.store = store;
  if (request.system) options.systemPrompt = request.system;
  if (request.tools) options.tools = request.tools;
  return options;
}

/** Store del agente: efímero (JSONL en un dir temporal que se borra), default del SDK o un dir propio. */
function openStore(sdk, request) {
  if (request.store === "default") return { store: null, cleanup: () => {} };
  const Jsonl = sdk.JsonlLocalAgentStore;
  if (typeof Jsonl !== "function") return { store: null, cleanup: () => {} };
  if (request.store === "dir") return { store: new Jsonl(request.store_dir), cleanup: () => {} };
  const dir = mkdtempSync(join(tmpdir(), "cursor-sdk-store-"));
  return { store: new Jsonl(dir), cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}

let http1Configured = false;
function configureHttp1(sdk, request) {
  if (!request.http1 || http1Configured) return;
  http1Configured = true;
  try { sdk.Cursor?.configure?.({ local: { useHttp1ForAgent: true } }); } catch { /* opcional */ }
}

async function costOf(agent) {
  try {
    const usage = await Promise.race([
      agent.getUsage(),
      new Promise((_, reject) => setTimeout(() => reject(new Error("usage timeout")), USAGE_TIMEOUT_MS)),
    ]);
    const cents = usage?.cost?.chargedCents;
    return typeof cents === "number" ? { chargedCents: cents } : null;
  } catch {
    return null;
  }
}

/** Corta una promesa por deadline o por stop; si la promesa resuelve tarde, `late` limpia lo que dejó. */
function guarded(promise, control, late) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn, value) => { if (!settled) { settled = true; control.off(onStop); clearTimeout(timer); fn(value); } };
    const onStop = (reason) => finish(reject, new SidecarError(reason, reason === "TIMEOUT" ? "sin respuesta a tiempo" : "cancelado"));
    const timer = setTimeout(() => onStop("TIMEOUT"), Math.max(0, control.deadline - Date.now()));
    control.on(onStop);
    if (control.stopped) onStop(control.stopped);
    promise.then((value) => { if (settled) late?.(value); else finish(resolve, value); }, (error) => finish(reject, error));
  });
}

function makeControl(timeoutS) {
  const listeners = new Set();
  const control = {
    deadline: Date.now() + timeoutS * 1000,
    stopped: null,
    on: (fn) => listeners.add(fn),
    off: (fn) => listeners.delete(fn),
    stop(reason) {
      if (control.stopped) return;
      control.stopped = reason;
      for (const fn of [...listeners]) fn(reason);
    },
  };
  return control;
}

function deliverSteer(run, text, out) {
  if (typeof run.steer !== "function") {
    out({ type: "steer", ok: false, code: "STEER_UNSUPPORTED", text_len: text.length });
    return Promise.resolve();
  }
  return run.steer(text).then(
    (outcome) => out({ type: "steer", ok: true, outcome, text_len: text.length }),
    (error) => out({ type: "steer", ok: false, code: classifyError(error), text_len: text.length }),
  );
}

/**
 * Un run completo. `agentRef` trae un agente reutilizable (serve con session_id) o se crea uno.
 * El deadline cubre create + send + stream. Si el run ya terminó, el resultado gana a un cancel/timeout tardío.
 */
async function executeRun({ sdk, request, apiKey, out, control, agentRef, onRun }) {
  const started = Date.now();
  let opened = null;
  let agent = agentRef?.agent ?? null;
  const owned = !agent;
  try {
    configureHttp1(sdk, request);
    if (!agent) {
      opened = openStore(sdk, request);
      agent = await guarded(sdk.Agent.create(agentOptions(request, apiKey, opened.store)), control, (late) => late?.close?.());
      if (agentRef) { agentRef.agent = agent; agentRef.cleanup = opened.cleanup; opened = null; }
    }
    const sendOptions = agentRef?.reused ? { model: modelSelection(request) } : undefined;
    if (agentRef) agentRef.reused = true;
    const run = await guarded(agent.send(request.prompt, sendOptions), control, (late) => late?.cancel?.().catch(() => {}));
    onRun?.(run);
    const steers = steerReader(resolveIn(request.cwd, request.steer_file));
    const cancelFile = resolveIn(request.cwd, request.cancel_file);
    const cancelRun = () => run.cancel().catch(() => {});
    control.on(cancelRun);
    const timer = setTimeout(() => control.stop("TIMEOUT"), Math.max(0, control.deadline - Date.now()));
    const poll = setInterval(() => {
      if (cancelFile && existsSync(cancelFile)) control.stop("CANCELLED");
      for (const text of steers()) deliverSteer(run, text, out);
    }, POLL_MS);
    try {
      for await (const message of run.stream()) {
        if (control.stopped) break;
        if (request.stream) out(truncateEvent({ type: "event", event: message.type, data: message }, request.max_event_bytes));
      }
      const result = await run.wait();
      if (result.status === "finished") {
        out({
          type: "result", ok: true, ...truncateText(result.result, request.max_result_chars), usage: publicUsage(result.usage),
          cost: await costOf(agent), duration_ms: Date.now() - started, sdk_duration_ms: result.durationMs ?? null,
          run_id: result.id ?? run.id, agent_id: agent.agentId, model: request.model,
        });
        return EXIT.OK;
      }
      if (control.stopped) return fail(out, control.stopped, control.stopped === "TIMEOUT" ? `sin respuesta en ${request.timeout_s} s` : "cancelado");
      if (result.status === "cancelled") return fail(out, "CANCELLED", "cancelado");
      return fail(out, classifyError(result.error), result.error?.message ?? "el run terminó con error");
    } finally {
      clearTimeout(timer);
      clearInterval(poll);
      control.off(cancelRun);
    }
  } catch (error) {
    if (error instanceof SidecarError) return fail(out, error.code, error.message);
    return fail(out, classifyError(error), error?.message ?? "error del SDK");
  } finally {
    if (owned && !agentRef) {
      try { agent?.close?.(); } catch { /* ya cerrado */ }
      opened?.cleanup();
    }
  }
}

function fail(out, code, message) {
  out(errorLine(code, message));
  return EXIT[code];
}

// --- one-shot -----------------------------------------------------------------
async function readStdin() {
  let data = "";
  for await (const chunk of process.stdin) data += chunk;
  return data;
}

async function oneShot(env, apiKey) {
  const control = makeControl(1e9);
  globalThis.__sidecarOnSignal = () => control.stop("CANCELLED");
  let request;
  try {
    // Una señal mientras se lee stdin corta la lectura: igual hay línea final.
    const stopped = new Promise((resolve) => control.on(() => resolve(null)));
    const raw = await Promise.race([readStdin(), stopped]);
    if (raw === null) { process.stdin.destroy(); return fail(emit, "CANCELLED", "cancelado antes del request"); }
    request = parseRequest(raw, process.cwd());
  } catch (error) {
    return fail(emit, error.code ?? "BAD_REQUEST", error.message);
  }
  if (control.stopped) return fail(emit, "CANCELLED", "cancelado");
  control.deadline = Date.now() + request.timeout_s * 1000;
  if (!apiKey) return fail(emit, "NO_KEY", "no hay CURSOR_API_KEY (archivo de key ni variable de entorno)");
  let sdk;
  try {
    sdk = await loadSdk(env);
  } catch (error) {
    return fail(emit, error.code, error.message);
  }
  return executeRun({ sdk, request, apiKey, out: emit, control });
}

// --- serve (larga vida) -------------------------------------------------------
async function serve(env, apiKey) {
  const sessions = new Map();
  const runs = new Map();
  let sdk = null;
  let closing = false;
  const tasks = new Set();

  const closeSession = (id) => {
    const session = sessions.get(id);
    if (!session) return false;
    sessions.delete(id);
    for (const [runId, entry] of runs) if (entry.session === id) entry.control.stop("CANCELLED");
    try { session.agent?.close?.(); } catch { /* ya cerrado */ }
    session.cleanup?.();
    return true;
  };

  const startRun = (id, request) => {
    const tag = { id, session_id: request.session_id };
    const out = (line) => emit({ id, session_id: request.session_id, ...line });
    if (runs.has(id)) return out(errorLine("BAD_REQUEST", `id repetido: ${id}`));
    if (!apiKey) return out(errorLine("NO_KEY", "no hay CURSOR_API_KEY (archivo de key ni variable de entorno)"));
    let agentRef = null;
    if (request.session_id) {
      agentRef = sessions.get(request.session_id);
      if (agentRef?.busy) return out(errorLine("BUSY", `la sesión ${request.session_id} ya tiene un run (${agentRef.busy})`));
      if (!agentRef) { agentRef = { agent: null, cleanup: null, busy: null, reused: false }; sessions.set(request.session_id, agentRef); }
      agentRef.busy = id;
    }
    const control = makeControl(request.timeout_s);
    const entry = { control, run: null, pending: [], session: request.session_id, tag };
    runs.set(id, entry);
    const task = (async () => {
      try {
        if (!sdk) sdk = await loadSdk(env);
        await executeRun({ sdk, request, apiKey, out, control, agentRef, onRun: (run) => { entry.run = run; for (const [text, ack] of entry.pending.splice(0)) deliverSteer(run, text, ack); } });
      } catch (error) {
        out(errorLine(error.code ?? classifyError(error), error.message ?? "error"));
      } finally {
        runs.delete(id);
        if (agentRef) agentRef.busy = null;
      }
    })();
    tasks.add(task);
    task.finally(() => tasks.delete(task));
  };

  const handle = (raw) => {
    if (!raw.trim()) return;
    let msg;
    try {
      msg = parseServeLine(raw, process.cwd());
    } catch (error) {
      let id = null;
      try { id = JSON.parse(raw)?.id ?? null; } catch { /* no JSON */ }
      return emit(errorLine(error.code ?? "BAD_REQUEST", error.message, { id: typeof id === "string" ? id : null }));
    }
    if (msg.op === "run") return closing ? emit(errorLine("CANCELLED", "cerrando", { id: msg.id })) : startRun(msg.id, msg.request);
    if (msg.op === "steer") {
      const entry = runs.get(msg.target);
      if (!entry) return emit({ id: msg.id, type: "steer", target: msg.target, ok: false, code: "NO_RUN" });
      const ack = (line) => emit({ id: msg.id, target: msg.target, ...line });
      if (!entry.run) return entry.pending.push([msg.text, ack]);
      return deliverSteer(entry.run, msg.text, ack);
    }
    if (msg.op === "cancel") {
      const entry = runs.get(msg.target);
      entry?.control.stop("CANCELLED");
      return emit({ id: msg.id, type: "ack", op: "cancel", target: msg.target, ok: Boolean(entry) });
    }
    if (msg.op === "close") return emit({ id: msg.id, type: "ack", op: "close", session_id: msg.session_id, ok: closeSession(msg.session_id) });
    if (msg.op === "ping") return emit({ id: msg.id, type: "pong", version: VERSION, sessions: [...sessions.keys()], running: [...runs.keys()] });
    if (msg.op === "shutdown") return shutdown();
  };

  let resolveDone;
  const done = new Promise((resolve) => { resolveDone = resolve; });
  const shutdown = async () => {
    if (closing) return;
    closing = true;
    for (const entry of runs.values()) entry.control.stop("CANCELLED");
    await Promise.allSettled([...tasks]);
    for (const id of [...sessions.keys()]) closeSession(id);
    resolveDone(EXIT.OK);
  };
  globalThis.__sidecarOnSignal = () => { shutdown(); };
  const rl = createInterface({ input: process.stdin });
  rl.on("line", handle);
  rl.on("close", () => { shutdown(); });
  return done;
}

// --- entrada ------------------------------------------------------------------
export async function main(argv, env) {
  if (argv.includes("--capabilities")) { emit(capabilities(sdkVersion())); return EXIT.OK; }
  if (argv.includes("--version")) { emit({ type: "version", version: VERSION, sdk: sdkVersion() }); return EXIT.OK; }
  const apiKey = readKey(resolveKeyFile(argv, env), env);
  guardOutput(apiKey);
  try {
    return argv.includes("--serve") ? await serve(env, apiKey) : await oneShot(env, apiKey);
  } finally {
    flushOutput();
  }
}
