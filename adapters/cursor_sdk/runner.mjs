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
process.exitCode = await main(process.argv.slice(2), process.env);
