"use strict";
// Voert de JavaScript van rpitest/ui/static/index.html uit tegen een nagebootste DOM, zodat de paginalogica
// getest kan worden zonder browser:  node ui_harness.js <index.html> <scenario.js>
// Het scenario definieert `async function scenario()` en geeft een JSON-baar resultaat terug.
const fs = require("fs");
const vm = require("vm");

const [page, scenarioFile] = process.argv.slice(2);
const html = fs.readFileSync(page, "utf8");
const script = /<script>([\s\S]*?)<\/script>/.exec(html)[1];
const scenario = fs.readFileSync(scenarioFile, "utf8");

const elements = {};
function makeEl(id) {
  const e = {
    id, textContent: "", className: "", disabled: false, hidden: false, style: {}, children: [], href: "", onclick: null,
    _classes: new Set(),
    classList: {
      add: c => e._classes.add(c),
      remove: c => e._classes.delete(c),
      toggle(c, force) {
        const on = force === undefined ? !e._classes.has(c) : !!force;
        if (on) e._classes.add(c); else e._classes.delete(c);
        return on;
      },
      contains: c => e._classes.has(c),
    },
    replaceChildren(...c) { e.children = c; },
    append(...c) { e.children.push(...c); },
    addEventListener() {},
  };
  return e;
}
const getEl = id => (elements[id] = elements[id] || makeEl(id));

let state = {};
const postResponses = {};
const fetchLog = [];
let now = 1_000_000;

const sandbox = {
  document: { getElementById: getEl, createElement: tag => makeEl(tag), addEventListener() {} },
  fetch: async (url, opts = {}) => {
    fetchLog.push([url, opts.method || "GET"]);
    if (opts.method === "POST") return { json: async () => postResponses[url] || { ok: true, message: "" } };
    return { json: async () => state };
  },
  setTimeout: () => 0,
  setInterval: () => 0,
  confirm: () => true,
  Date: class { static now() { return now; } toLocaleString() { return ""; } },
  console, encodeURIComponent, JSON, Math, Set, Promise,
  __setState: s => { state = s; },
  __setPost: (path, body) => { postResponses[path] = body; },
  __setNow: ms => { now = ms; },
  __el: getEl,
  __fetchLog: fetchLog,
};

(async () => {
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox);
  await new Promise(r => setImmediate(r));
  const result = await vm.runInContext(scenario + "\n;(async () => JSON.stringify(await scenario()))()", sandbox);
  process.stdout.write(result);
})().catch(e => { console.error(e.stack || String(e)); process.exit(1); });
