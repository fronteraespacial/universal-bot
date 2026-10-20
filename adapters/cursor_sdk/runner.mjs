// Primero los handlers de señal: un SIGTERM que llega antes de cargar el resto igual deja una línea final.
const EARLY = { stopped: null };
globalThis.__sidecarEarly = EARLY;
for (const name of ["SIGTERM", "SIGINT"]) {
  process.on(name, () => {
    if (typeof globalThis.__sidecarOnSignal === "function") return globalThis.__sidecarOnSignal(name);
    EARLY.stopped = name;
    process.stdout.write(JSON.stringify({
      type: "error", ok: false, code: "CANCELLED", message: `${name} antes de arrancar`, fallback: false, exit_code: 10,
    }) + "\n");
    process.exit(10);
  });
}
const MIN = [22, 13];
const [major, minor] = process.versions.node.split(".").map(Number);
if (!(major > MIN[0] || (major === MIN[0] && minor >= MIN[1]))) {
  process.stdout.write(JSON.stringify({
    type: "error", ok: false, code: "NODE_TOO_OLD", fallback: true, exit_code: 5,
    message: `Node ${process.versions.node} < ${MIN.join(".")}`,
  }) + "\n");
  process.exit(5);
}
const { main } = await import("./lib/main.mjs");
const code = await main(process.argv.slice(2), process.env);
// Salir apenas hay línea final: un create/send tardío (timeout) no retiene el proceso.
process.stdout.write("", () => process.exit(code));
