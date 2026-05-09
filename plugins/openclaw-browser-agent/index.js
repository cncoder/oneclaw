// index.js — OpenClaw plugin entry: computer_use + research_fetch tools
//
// Wraps two existing shell scripts as first-class OpenClaw tools so that
// the agent can call them via tool_use instead of `exec bash ...`.
//
//   computer_use({ task, max_steps?, max_tokens?, viewport_w?, viewport_h? })
//     → runs skills/computer-use/run.sh and returns the final JSON / done_summary
//
//   research_fetch({ url, no_vlm?, no_cdp?, viewport_only?, md_only? })
//     → runs skills/research-fetch/run.sh and returns parsed JSON
//
// Design: both scripts already do the heavy lifting; this plugin is just a thin
// parameter → argv → stdout-JSON wrapper with timeouts and error handling.

import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { spawn } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";
import { existsSync } from "node:fs";

// ─── Config helpers ────────────────────────────────────────────────────────────

const DEFAULT_COMPUTER_USE_SCRIPT = join(
  homedir(),
  ".openclaw/workspace/skills/computer-use/run.sh"
);
const DEFAULT_RESEARCH_FETCH_SCRIPT = join(
  homedir(),
  ".openclaw/workspace/skills/research-fetch/run.sh"
);

function resolveScript(configuredPath, fallback) {
  const path = configuredPath || fallback;
  if (!existsSync(path)) {
    throw new Error(
      `browser-agent: script not found at ${path}. ` +
        `Ensure the computer-use / research-fetch workspace skill is installed, ` +
        `or override via plugins.entries.browser-agent.config.*.`
    );
  }
  return path;
}

// ─── Generic spawn-to-content helper ──────────────────────────────────────────

function runScript(scriptPath, args, { timeoutMs, env = {} }) {
  return new Promise((resolve) => {
    const child = spawn("bash", [scriptPath, ...args], {
      env: {
        ...process.env,
        // Always clear proxy envs — local CDP must not tunnel through Clash/Stash.
        http_proxy: "",
        https_proxy: "",
        HTTP_PROXY: "",
        HTTPS_PROXY: "",
        all_proxy: "",
        ALL_PROXY: "",
        NO_PROXY: "",
        no_proxy: "",
        ...env,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    let killed = false;
    const timer = setTimeout(() => {
      killed = true;
      try {
        child.kill("SIGKILL");
      } catch {}
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({
        code: killed ? -1 : code ?? -1,
        stdout,
        stderr,
        timedOut: killed,
      });
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ code: -1, stdout, stderr: `${stderr}\n${err.message}`, timedOut: false });
    });
  });
}

// ─── computer_use tool ─────────────────────────────────────────────────────────

const computerUseDescriptor = {
  label: "Computer Use (browser agent)",
  name: "computer_use",
  description:
    "High-level browser agent: given a natural-language task, iteratively takes " +
    "screenshots of the attached Chrome (abel-chrome by default), overlays " +
    "Set-of-Marks IDs, asks a VLM what to do next, and executes click/type/goto/key " +
    "via Playwright. Returns the JSON in done_summary. Use for multi-step interactive " +
    "tasks on login-walled sites (search, click, fill, read result). Not for pure " +
    "content extraction — use research_fetch for that.",
  parameters: {
    type: "object",
    required: ["task"],
    additionalProperties: false,
    properties: {
      task: {
        type: "string",
        description:
          "Natural-language task in user's language. E.g. '打开 github.com 搜 remotion 告诉我第一个仓库名 JSON' or 'open twitter.com/i/notifications, scroll once, list 5 most recent mentions'.",
      },
      max_steps: {
        type: "number",
        description: "Max reasoning/action steps. Default 15 for complex tasks, 4-6 for data extraction.",
      },
      viewport_w: {
        type: "number",
        description: "Viewport width in CSS pixels. Default 1400.",
      },
      viewport_h: {
        type: "number",
        description: "Viewport height in CSS pixels. Default 787.",
      },
    },
  },
};

function createComputerUseTool(getConfig) {
  return {
    ...computerUseDescriptor,
    async execute(_toolCallId, args /*, signal, onUpdate */) {
      const cfg = getConfig();
      const scriptPath = resolveScript(cfg.computerUseScript, DEFAULT_COMPUTER_USE_SCRIPT);
      const timeoutMs = (cfg.timeoutSecondsComputerUse ?? 300) * 1000;

      const env = {};
      if (args?.max_steps || cfg.defaultMaxStepsComputerUse) {
        env.MAX_STEPS = String(args?.max_steps ?? cfg.defaultMaxStepsComputerUse);
      }
      if (args?.viewport_w) env.CU_VIEWPORT_W = String(args.viewport_w);
      if (args?.viewport_h) env.CU_VIEWPORT_H = String(args.viewport_h);

      const { code, stdout, stderr, timedOut } = await runScript(
        scriptPath,
        [args.task],
        { timeoutMs, env }
      );

      if (timedOut) {
        return {
          content: [
            {
              type: "text",
              text: `computer_use timed out after ${timeoutMs / 1000}s. Partial stdout:\n\n${stdout.slice(-2000)}\n\nstderr:\n${stderr.slice(-800)}`,
            },
          ],
          isError: true,
        };
      }

      // The run.sh ends with a line like "✅ <done_summary>". Capture it.
      const lastLine = [...stdout.matchAll(/^✅\s+(.*)$/gm)].pop();
      const summary = lastLine ? lastLine[1].trim() : null;

      if (code !== 0 && !summary) {
        return {
          content: [
            {
              type: "text",
              text: `computer_use failed (exit ${code}):\n\nstdout tail:\n${stdout.slice(-1500)}\n\nstderr tail:\n${stderr.slice(-800)}`,
            },
          ],
          isError: true,
        };
      }

      // Try to parse summary as JSON for structured responses.
      let parsed = null;
      if (summary) {
        try {
          parsed = JSON.parse(summary);
        } catch {
          /* leave as string */
        }
      }

      const reply = {
        ok: true,
        result: parsed ?? summary ?? "",
        raw_summary: summary,
      };
      // Also include stdout tail so the agent can see step trace if needed.
      return {
        content: [
          { type: "text", text: JSON.stringify(reply, null, 2) },
          { type: "text", text: `[trace]\n${stdout.slice(-1800)}` },
        ],
      };
    },
  };
}

// ─── research_fetch tool ──────────────────────────────────────────────────────

const researchFetchDescriptor = {
  label: "Research Fetch (accurate content extraction)",
  name: "research_fetch",
  description:
    "Highest-accuracy web-page content extraction. Runs Playwright + Trafilatura + " +
    "Readability.js + full-page VLM screenshot and reconciles the three sources with " +
    "an LLM. Returns {title, author, published_at, language, markdown, excerpt, " +
    "confidence, rejected_noise, notable_media, links_outbound, ...}. Use this " +
    "whenever the user says 'read this URL', 'summarize this article', 'what does " +
    "this page say', or needs markdown extracted from a page. For multi-step " +
    "interactive work (clicks, forms), use computer_use instead.",
  parameters: {
    type: "object",
    required: ["url"],
    additionalProperties: false,
    properties: {
      url: {
        type: "string",
        description: "Absolute http(s) URL to fetch.",
      },
      no_vlm: {
        type: "boolean",
        description: "Skip LLM reconciliation — Trafilatura only, ~3s, 85-90% accuracy. Use for bulk indexing.",
      },
      no_cdp: {
        type: "boolean",
        description: "Launch an isolated headless Chromium instead of attaching to the user's Chrome. Use when CDP is down or the target page should not reuse login state.",
      },
      viewport_only: {
        type: "boolean",
        description: "Screenshot only the first viewport (faster but may miss the tail of long articles).",
      },
      md_only: {
        type: "boolean",
        description: "Return only the extracted markdown string instead of the full JSON result.",
      },
    },
  },
};

function createResearchFetchTool(getConfig) {
  return {
    ...researchFetchDescriptor,
    async execute(_toolCallId, args /*, signal, onUpdate */) {
      const cfg = getConfig();
      const scriptPath = resolveScript(cfg.researchFetchScript, DEFAULT_RESEARCH_FETCH_SCRIPT);
      const timeoutMs = (cfg.timeoutSecondsResearchFetch ?? 180) * 1000;

      const flags = [];
      if (args?.no_vlm) flags.push("--no-vlm");
      if (args?.no_cdp) flags.push("--no-cdp");
      if (args?.viewport_only) flags.push("--viewport-only");
      if (args?.md_only) flags.push("--md-only");

      const { code, stdout, stderr, timedOut } = await runScript(
        scriptPath,
        [args.url, ...flags],
        { timeoutMs }
      );

      if (timedOut) {
        return {
          content: [
            {
              type: "text",
              text: `research_fetch timed out after ${timeoutMs / 1000}s. Partial stdout:\n\n${stdout.slice(-2000)}\n\nstderr:\n${stderr.slice(-800)}`,
            },
          ],
          isError: true,
        };
      }

      if (code !== 0) {
        return {
          content: [
            {
              type: "text",
              text: `research_fetch failed (exit ${code}):\n\nstdout tail:\n${stdout.slice(-1500)}\n\nstderr tail:\n${stderr.slice(-800)}`,
            },
          ],
          isError: true,
        };
      }

      if (args?.md_only) {
        return {
          content: [{ type: "text", text: stdout.trim() }],
        };
      }

      // Parse the JSON output from fetch.py
      let data = null;
      try {
        data = JSON.parse(stdout);
      } catch (err) {
        return {
          content: [
            {
              type: "text",
              text: `research_fetch stdout was not JSON: ${err.message}\n\nstdout:\n${stdout.slice(0, 3000)}`,
            },
          ],
          isError: true,
        };
      }

      // Return a compact view + the full JSON for the agent.
      const compact = {
        url: data.url,
        title: data.title,
        author: data.author,
        published_at: data.published_at,
        language: data.language,
        confidence: data.confidence,
        excerpt: data.excerpt,
        markdown_chars: (data.markdown || "").length,
        elapsed_s: data.elapsed_s,
        tokens_used: data.tokens_used,
        rejected_noise: data.rejected_noise,
      };

      return {
        content: [
          { type: "text", text: JSON.stringify(compact, null, 2) },
          { type: "text", text: `--- markdown ---\n${data.markdown || "(empty)"}` },
        ],
      };
    },
  };
}

// ─── Plugin entry ──────────────────────────────────────────────────────────────

export default definePluginEntry({
  id: "browser-agent",
  name: "Browser Agent (computer_use + research_fetch)",
  description:
    "High-level browser tools that wrap the computer-use SoM loop and the research-fetch three-way content extractor.",
  register(api) {
    const getConfig = () => {
      try {
        // The plugin config is passed to register(api) via api.getPluginConfig?.() in
        // newer SDKs; fall back to empty object if unavailable.
        return typeof api.getPluginConfig === "function"
          ? api.getPluginConfig() || {}
          : {};
      } catch {
        return {};
      }
    };

    api.registerTool(createComputerUseTool(getConfig));
    api.registerTool(createResearchFetchTool(getConfig));
  },
});
