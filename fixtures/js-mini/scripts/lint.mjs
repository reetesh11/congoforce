// Tiny stand-in for eslint so the fixture needs no lint dependency:
// fails on `console.log` and `debugger` left in src/.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const bad = [];
for (const f of readdirSync("src")) {
  if (!f.endsWith(".js") || f.includes(".test.")) continue;
  const text = readFileSync(join("src", f), "utf8");
  text.split("\n").forEach((line, i) => {
    if (/console\.log|debugger/.test(line)) bad.push(`src/${f}:${i + 1}: error no-console/no-debugger`);
  });
}
if (bad.length) {
  console.error(bad.join("\n"));
  process.exit(1);
}
console.log("lint ok");
