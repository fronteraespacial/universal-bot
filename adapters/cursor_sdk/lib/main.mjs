import { existsSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";
import { EXIT, FALLBACK_CODES, SidecarError, classifyError, makeRedactor, parseRequest, publicUsage } from "./protocol.mjs";
import { readKey, resolveKeyFile } from "./key.mjs";
import { steerReader } from "./inbox.mjs";

const POLL_MS = 200;
const USAGE_TIMEOUT_MS = 3000;

function guardOutput(redact) {
  for (const stream of [process.stdout, process.stderr]) {
    const write = stream.write.bind(stream);
    stream.write = (chunk, ...rest) => write(redact(typeof chunk === "string" ? chunk : Buffer.from(chunk).toString("utf8")), ...rest);
  }
}

function emit(line) {
  process.stdout.write(JSON.stringify(line) + "\n");
}

function fail(code, message) {
  emit({ type: "error", ok: false, code, message, fallback: FALLBACK_CODES.has(code), exit_code: EXIT[code] });
  return EXIT[code];
}

async function readStdin() {
  let data = "";
  for await (const chunk of process.stdin) data += chunk;
  return data;
}

async function loadSdk(env) {
  const target = env.CURSOR_SDK_MODULE;
  try {
    return target ? await import(pathToFileURL(target).href) : await import("@cursor/sdk");
  } catch {
    throw new SidecarError("SDK_MISSING", "no se pudo cargar @cursor/sdk");
  }
}

function resolveIn(cwd, path) {
  if (!path) return null;
  return isAbsolute(path) ? path : join(cwd, path);
}

function agentOptions(request, apiKey) {
  const options = { apiKey, model: { id: request.model }, local: { cwd: request.cwd }, disallowedTools: ["mcp"] };
  if (request.system) options.systemPrompt = request.system;
  if (request.tools) options.tools = request.tools;
  return options;
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

function watchRun(run, request, onStop) {
  const steers = steerReader(resolveIn(request.cwd, request.steer_file));
  const cancelFile = resolveIn(request.cwd, request.cancel_file);
  const stop = (reason) => {
    onStop(reason);
    run.cancel().catch(() => {});
  };
  const deadline = setTimeout(() => stop("TIMEOUT"), request.timeout_s * 1000);
  const poll = setInterval(() => {
    if (cancelFile && existsSync(cancelFile)) stop("CANCELLED");
    for (const text of steers()) deliverSteer(run, text);
  }, POLL_MS);
  const onSignal = () => stop("CANCELLED");
  process.once("SIGTERM", onSignal);
  process.once("SIGINT", onSignal);
  return () => {
    clearTimeout(deadline);
    clearInterval(poll);
    process.off("SIGTERM", onSignal);
    process.off("SIGINT", onSignal);
  };
}

function deliverSteer(run, text) {
  if (typeof run.steer !== "function") {
    emit({ type: "steer", ok: false, code: "STEER_UNSUPPORTED", text_len: text.length });
    return;
  }
  run.steer(text).then(
    (outcome) => emit({ type: "steer", ok: true, outcome, text_len: text.length }),
    (error) => emit({ type: "steer", ok: false, code: classifyError(error), text_len: text.length }),
  );
}

async function execute(sdk, request, apiKey) {
  const started = Date.now();
  const agent = await sdk.Agent.create(agentOptions(request, apiKey));
  const run = await agent.send(request.prompt);
  let stopped = null;
  const unwatch = watchRun(run, request, (reason) => { stopped ??= reason; });
  try {
    for await (const message of run.stream()) {
      if (stopped) break;
      if (request.stream) emit({ type: "event", event: message.type, data: message });
    }
    const result = await run.wait();
    if (stopped) return fail(stopped, stopped === "TIMEOUT" ? `sin respuesta en ${request.timeout_s} s` : "cancelado");
    if (result.status === "cancelled") return fail("CANCELLED", "cancelado");
    if (result.status !== "finished") return fail(classifyError(result.error), result.error?.message ?? "el run terminó con error");
    emit({
      type: "result", ok: true, text: result.result ?? "", usage: publicUsage(result.usage),
      cost: await costOf(agent), duration_ms: Date.now() - started, sdk_duration_ms: result.durationMs ?? null,
      run_id: result.id ?? run.id, agent_id: agent.agentId, model: request.model,
    });
    return EXIT.OK;
  } finally {
    unwatch();
  }
}

export async function main(argv, env) {
  const apiKey = readKey(resolveKeyFile(argv, env), env);
  guardOutput(makeRedactor(apiKey));
  try {
    const request = parseRequest(await readStdin(), process.cwd());
    if (!apiKey) return fail("NO_KEY", "no hay CURSOR_API_KEY (archivo de key ni variable de entorno)");
    const sdk = await loadSdk(env);
    return await execute(sdk, request, apiKey);
  } catch (error) {
    if (error instanceof SidecarError) return fail(error.code, error.message);
    return fail(classifyError(error), error?.message ?? "error del SDK");
  }
}
